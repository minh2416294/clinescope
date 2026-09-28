"""Tests for the CI threshold gate (``clinescope.gate``).

The gate runs the DETERMINISTIC scorers on a trace, compares each against a
caller-supplied ``--min-*`` threshold, and returns an exit code:
``0`` = all gated scorers pass, ``1`` = at least one below threshold (build
fails), ``2`` = a usage error (no threshold flag, unloadable trace, or every
gated scorer abstained -- nothing verified).

Mirrors the repo's CLI-test convention (``test_report.py``): call ``main(argv)``
and assert its ``int`` return + ``capsys`` stdout -- no subprocess. Real-trace
tests are ``skipif``-gated on the committed ``examples/*.json`` files.

Ground-truth is the real scorers, never a hand-asserted score (Day-16 lesson):
* ``examples/apply-patch-trace.json`` -> coh 1.0 / min 1.0 / rec n/a (baseline)
* ``examples/live-gpt-oss-apply-fail.json`` -> rec 0.0 (real live regression)
* ``examples/gate-regression-badpatch.json`` -> coh 0.75 (authored regression)
"""

from __future__ import annotations

import ast
import json
from math import sqrt
from pathlib import Path
from statistics import NormalDist

import pytest

from clinescope.diff_minimality import score_diff_minimality
from clinescope.gate import GateReport, GateResult, main, render_gate_report, run_gate
from clinescope.gold import gold_load_resolved
from clinescope.world_a import ToolCall, Trace

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLD_SET = REPO_ROOT / "gold" / "diff_minimality.gold.jsonl"
EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
BASELINE = EXAMPLES / "apply-patch-trace.json"
RECOVERY_REGRESSION = EXAMPLES / "live-gpt-oss-apply-fail.json"
COHERENCE_REGRESSION = EXAMPLES / "gate-regression-badpatch.json"
# A real captured session that edits with `editor` and never calls apply_patch, which
# is what almost every current Cline session looks like.
EDITOR_ONLY = EXAMPLES / "live-granite-editor-recovery.json"
GATE_SOURCE = Path(__file__).resolve().parent.parent / "src" / "clinescope" / "gate.py"


def _trace_with_apply_patch(patch: str, *, is_error: bool | None = None) -> Trace:
    """A minimal one-apply_patch Trace, for pure run_gate unit tests (no file)."""
    call = ToolCall(
        id="call-1",
        name="apply_patch",
        input={"input": patch},
        result_content=None,
        is_error=is_error,
    )
    return Trace(version=1, turns=(), tool_calls=(call,), dropped_items=())


_CLEAN_ADD = "*** Begin Patch\n*** Add File: note.txt\n+hello\n*** End Patch"
_BAD_ADD = "*** Begin Patch\n*** Add File: note.txt\n+ok\ndone\n*** End Patch"


# --- pure run_gate unit tests (no file I/O) ---------------------------------


def test_run_gate_pass_when_score_at_or_above_threshold() -> None:
    trace = _trace_with_apply_patch(_CLEAN_ADD)
    report = run_gate(trace, {"diff_coherence": 0.75})
    assert report.passed is True
    assert report.exit_code == 0
    (result,) = report.results
    assert result.name == "diff_coherence"
    assert result.verdict == "pass"
    assert result.actual == 1.0


def test_run_gate_fail_when_score_below_threshold() -> None:
    trace = _trace_with_apply_patch(_BAD_ADD)  # coherence 0.75
    report = run_gate(trace, {"diff_coherence": 1.0})
    assert report.passed is False
    assert report.exit_code == 1
    (result,) = report.results
    assert result.verdict == "fail"
    assert result.actual == 0.75


def test_run_gate_boundary_equal_threshold_is_pass() -> None:
    trace = _trace_with_apply_patch(_BAD_ADD)  # coherence 0.75
    report = run_gate(trace, {"diff_coherence": 0.75})
    assert report.passed is True
    assert report.exit_code == 0
    (result,) = report.results
    assert result.verdict == "pass"


def test_run_gate_skips_abstaining_scorer_not_counted() -> None:
    # A clean run: apply_recovery abstains (nothing failed) -> skip, not fail.
    trace = _trace_with_apply_patch(_CLEAN_ADD, is_error=False)
    report = run_gate(trace, {"diff_coherence": 1.0, "apply_recovery": 1.0})
    verdicts = {r.name: r.verdict for r in report.results}
    assert verdicts["diff_coherence"] == "pass"
    assert verdicts["apply_recovery"] == "skip"
    assert report.passed is True  # the skip did not fail the gate
    assert report.exit_code == 0
    assert report.all_abstained is False


def test_run_gate_all_abstained_is_exit_2_not_silent_pass() -> None:
    # Only apply_recovery gated, but the trace has nothing to recover -> every
    # gated scorer abstains -> nothing verified -> a loud usage error, not 0.
    trace = _trace_with_apply_patch(_CLEAN_ADD, is_error=False)
    report = run_gate(trace, {"apply_recovery": 1.0})
    assert report.all_abstained is True
    assert report.passed is False
    assert report.exit_code == 2
    (result,) = report.results
    assert result.verdict == "skip"


def test_run_gate_empty_thresholds_is_usage_not_pass() -> None:
    # An empty gate verifies nothing -> exit 2 (usage), never a silent pass.
    # main() guards this before calling run_gate; the pure function must agree.
    trace = _trace_with_apply_patch(_CLEAN_ADD)
    report = run_gate(trace, {})
    assert report.results == ()
    assert report.all_abstained is True
    assert report.passed is False
    assert report.exit_code == 2


def test_run_gate_fail_takes_precedence_over_pass() -> None:
    trace = _trace_with_apply_patch(_BAD_ADD)  # coherence 0.75, minimality 1.0
    report = run_gate(trace, {"diff_coherence": 1.0, "diff_minimality": 1.0})
    verdicts = {r.name: r.verdict for r in report.results}
    assert verdicts["diff_coherence"] == "fail"
    assert verdicts["diff_minimality"] == "pass"
    assert report.passed is False
    assert report.exit_code == 1


def test_run_gate_preserves_requested_thresholds_for_echo() -> None:
    trace = _trace_with_apply_patch(_CLEAN_ADD)
    report = run_gate(trace, {"diff_coherence": 0.75})
    assert report.thresholds == {"diff_coherence": 0.75}


# --- render_gate_report -----------------------------------------------------


def test_render_report_echoes_thresholds_and_verdict() -> None:
    trace = _trace_with_apply_patch(_BAD_ADD)
    report = run_gate(trace, {"diff_coherence": 1.0})
    text = render_gate_report(report)
    assert "VERDICT: FAIL" in text
    assert "diff_coherence" in text
    assert "0.7500" in text  # the actual score, .4f like report.py
    assert "1.0000" in text  # the threshold echoed
    assert ">=" in text or "min" in text  # the threshold is shown


def test_render_report_marks_skip_as_not_gated() -> None:
    trace = _trace_with_apply_patch(_CLEAN_ADD, is_error=False)
    report = run_gate(trace, {"diff_coherence": 1.0, "apply_recovery": 1.0})
    text = render_gate_report(report)
    assert "SKIP" in text
    assert "n/a" in text or "not applicable" in text or "not gated" in text


# --- The gated scorer's measured agreement is disclosed at the point of use --
# LIMITATIONS.md carries the full finding, but somebody wiring this into CI reads
# --help and never opens the repo. The number belongs where the decision is made.


def test_help_discloses_diff_minimality_agreement(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    # The measured agreement with the 50 human gold labels.
    assert "0.2599" in help_text
    # And the consequence a CI user most needs: it has never failed a build.
    assert "never" in help_text.lower()


def test_help_discloses_layout_dependence(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The score is not a property of the agent alone: the SAME edit scores 1.0
    # or 0.0 depending on how many lines the file puts between the anchor and
    # the change (a FLOOR boundary crossing, measured 2026-08-20). Somebody
    # gating CI on this must read that where they set the threshold, so it is
    # pinned here rather than left to survive on goodwill.
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    # argparse re-wraps help text at the terminal width, so collapse whitespace
    # before matching a phrase that spans a wrap point.
    help_text = " ".join(capsys.readouterr().out.split())
    assert "the same edit can score 1.0 or 0.0" in help_text
    assert "lines sit between an anchor and the change" in help_text


def _wilson_95(k: int, n: int) -> str:
    z = NormalDist().inv_cdf(0.975)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return f"[{centre - half:.3f}, {centre + half:.3f}]"


def test_minimality_help_publishes_both_rates(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A catch rate alone cannot tell a scorer from one that flags everything:
    # flagging all 50 gold patches would catch 24 of 24. Only the pair says
    # anything, so the help carries both. They are recomputed here from the frozen
    # gold set and the real scorer, never copied from the text they check.
    caught = missed = false_alarms = cleared = 0
    for resolved in gold_load_resolved(GOLD_SET, repo_root=REPO_ROOT):
        label = resolved.item.human_label
        if label is None:
            continue
        score = score_diff_minimality(resolved.trace).score
        assert score is not None, resolved.item.item_id
        flagged = score < 1.0
        if label == "WASTEFUL" and flagged:
            caught += 1
        elif label == "WASTEFUL":
            missed += 1
        elif flagged:
            false_alarms += 1
        else:
            cleared += 1
    assert (caught, caught + missed) == (7, 24)
    assert (false_alarms, false_alarms + cleared) == (1, 26)
    # Each rate carries a Wilson 95% interval, recomputed here from those counts so
    # a mistyped or Wald interval in the help fails, not only a changed count. The
    # literals are the spec values the helper must reproduce.
    catch_interval = _wilson_95(caught, caught + missed)
    false_alarm_interval = _wilson_95(false_alarms, false_alarms + cleared)
    assert catch_interval == "[0.149, 0.492]"
    assert false_alarm_interval == "[0.007, 0.189]"

    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    help_text = " ".join(capsys.readouterr().out.split())
    # The last mention of the flag is its own entry; the usage line comes first.
    flag_help = help_text.rsplit("--min-diff-minimality MIN", 1)[1]
    flag_help = flag_help.split("--min-apply-recovery", 1)[0]
    # A low false-alarm rate must not read as a reason to gate, so the sentence
    # saying the flag has never failed a real build stays in the same paragraph.
    assert (
        "this flag has never failed a build on any real captured trace shipped "
        "with Clinescope, at any threshold"
    ) in flag_help
    assert f"7 of 24 (Wilson 95% CI {catch_interval})" in flag_help
    assert f"1 of 26 (Wilson 95% CI {false_alarm_interval})" in flag_help


# --- main(argv) exit-code contract (the CI-facing seam) ---------------------


def test_main_no_threshold_flag_is_usage_error_exit_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([str(BASELINE)])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "threshold" in err.lower() or "--min" in err


def test_main_missing_trace_file_is_usage_error_exit_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [str(EXAMPLES / "does-not-exist.json"), "--min-diff-coherence", "0.75"]
    )
    assert exit_code == 2
    err = capsys.readouterr().err
    assert err.strip()  # a reason is printed, not a bare crash


def test_main_malformed_but_loadable_trace_is_usage_error_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A trace that JSON-parses but is structurally invalid (messages not a list)
    # trips the loader's parser (AttributeError), NOT WorldATraceError. It must
    # normalize to the usage exit 2 -- never masquerade as a gate FAIL (1),
    # because the trace was never scored. (Gate-4 Day-18 regression.)
    bad = tmp_path / "malformed.json"
    bad.write_text('{"version": 1, "messages": "notalist"}', encoding="utf-8")
    exit_code = main([str(bad), "--min-diff-coherence", "0.75"])
    assert exit_code == 2
    assert capsys.readouterr().err.strip()


def test_main_non_utf8_trace_is_usage_error_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A file that cannot be decoded as UTF-8 raises UnicodeDecodeError (a
    # ValueError, NOT an OSError) inside the loader. It must exit 2, not leak
    # through as a gate FAIL (1). (Gate-4 Day-18 regression.)
    bad = tmp_path / "non-utf8.json"
    bad.write_bytes(b"\xff\xfe\x00\x01not valid utf-8")
    exit_code = main([str(bad), "--min-diff-coherence", "0.75"])
    assert exit_code == 2
    assert capsys.readouterr().err.strip()


# --- real-trace end-to-end (both exit directions, ground-truthed) -----------


@pytest.mark.skipif(not BASELINE.exists(), reason="baseline example trace not present")
def test_main_baseline_passes_exit_0(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([str(BASELINE), "--min-diff-coherence", "0.75"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "VERDICT: PASS" in out


@pytest.mark.skipif(
    not RECOVERY_REGRESSION.exists(),
    reason="live apply-fail regression trace not present",
)
def test_main_recovery_regression_fails_exit_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([str(RECOVERY_REGRESSION), "--min-apply-recovery", "1.0"])
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "VERDICT: FAIL" in out
    assert "apply_recovery" in out


@pytest.mark.skipif(
    not COHERENCE_REGRESSION.exists(),
    reason="authored coherence regression trace not present",
)
def test_main_coherence_regression_fails_exit_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([str(COHERENCE_REGRESSION), "--min-diff-coherence", "1.0"])
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "VERDICT: FAIL" in out
    assert "diff_coherence" in out


@pytest.mark.skipif(
    not COHERENCE_REGRESSION.exists(),
    reason="authored coherence regression trace not present",
)
def test_main_threshold_below_actual_flips_to_pass(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Same trace (coherence 0.75): threshold above -> fail, below/equal -> pass.
    # Proves the exit code is COMPUTED from the real scorer, not hardcoded.
    fail_code = main([str(COHERENCE_REGRESSION), "--min-diff-coherence", "1.0"])
    capsys.readouterr()
    pass_code = main([str(COHERENCE_REGRESSION), "--min-diff-coherence", "0.5"])
    assert fail_code == 1
    assert pass_code == 0


@pytest.mark.skipif(not BASELINE.exists(), reason="baseline example trace not present")
def test_main_all_abstained_on_real_trace_is_exit_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Baseline has no failed apply_patch -> apply_recovery abstains. Gating only
    # on it means nothing is verified -> exit 2, never a silent pass.
    exit_code = main([str(BASELINE), "--min-apply-recovery", "1.0"])
    assert exit_code == 2
    combined = capsys.readouterr()
    text = combined.out + combined.err
    assert "abstain" in text.lower() or "nothing" in text.lower()


# --- absence is not a regression -------------------------------------------
# Almost no current Cline session emits apply_patch, so the common trace has none at
# all. diff_coherence hard-zeros on one by design, and that 0.0 used to count as a
# graded result: the gate then exited 1, "at least one gated scorer scored below its
# threshold", for a scorer that never graded anything. The module docstring's contract
# says exit 2 covers "every gated scorer abstained on this trace (nothing was
# verified)", and on a trace with no apply_patch that is the true statement.


@pytest.mark.skipif(
    not EDITOR_ONLY.exists(), reason="real editor-only trace not present"
)
def test_main_no_apply_patch_is_exit_2_not_a_regression(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([str(EDITOR_ONLY), "--min-diff-coherence", "0.75"])
    assert exit_code == 2
    combined = capsys.readouterr()
    text = combined.out + combined.err
    assert "SKIP" in text
    assert "FAIL" not in text


@pytest.mark.skipif(
    not EDITOR_ONLY.exists(), reason="real editor-only trace not present"
)
def test_main_no_apply_patch_stays_exit_2_alongside_the_abstainers() -> None:
    # The case that made this a defect rather than a quirk: adding
    # --min-diff-coherence to a config used to convert an honest exit 2 into exit 1.
    exit_code = main(
        [
            str(EDITOR_ONLY),
            "--min-diff-coherence",
            "0.75",
            "--min-diff-minimality",
            "0.75",
            "--min-apply-recovery",
            "0.75",
        ]
    )
    assert exit_code == 2


def test_malformed_patch_still_fails_the_gate() -> None:
    # The guard keys on "no apply_patch call", NOT on a zero score, so every genuine
    # malformed-patch failure keeps failing. A patch IS present here; it is just wrong.
    trace = _trace_with_apply_patch("*** Begin Patch\nnonsense\n*** End Patch")
    report = run_gate(trace, {"diff_coherence": 0.75})
    assert report.exit_code == 1
    assert report.all_abstained is False


# --- gating an editor run: --min-editor-recovery and --min-tool-selection ----
# Almost every current Cline session edits with `editor`. editor_recovery is the one
# scorer that grades those edits, and tool_selection is the one that yields a number on
# every run, so a clean editor run (nothing failed, editor_recovery n/a) can still pass.


def _editor_call(call_id: str, path: str, *, is_error: bool | None) -> ToolCall:
    return ToolCall(
        id=call_id,
        name="editor",
        input={"path": path, "old_text": "a\n", "new_text": "b\n"},
        result_content=None if is_error is None else "result",
        is_error=is_error,
    )


def _write_clean_editor_trace(tmp_path: Path) -> Path:
    trace = tmp_path / "clean-editor.json"
    trace.write_text(
        json.dumps(
            {
                "version": 1,
                "sessionId": "clean-editor-1",
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "call-1",
                                "name": "editor",
                                "input": {"path": "a.py", "new_text": "x = 1\n"},
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "call-1",
                                "content": "ok",
                                "is_error": False,
                            }
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return trace


@pytest.mark.skipif(
    not EDITOR_ONLY.exists(), reason="real editor-only trace not present"
)
def test_main_editor_recovery_passes_on_a_recovered_editor_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([str(EDITOR_ONLY), "--min-editor-recovery", "1.0"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "[gate] editor_recovery: 1.0000 >= min 1.0000 -> PASS" in out
    assert "VERDICT: PASS (thresholds: editor_recovery>=1.0000)" in out


def test_run_gate_unrecovered_editor_failure_fails_exit_1() -> None:
    trace = Trace(
        version=1,
        turns=(),
        tool_calls=(_editor_call("c1", "a.py", is_error=True),),
        dropped_items=(),
    )
    report = run_gate(trace, {"editor_recovery": 1.0})

    assert report.exit_code == 1
    assert report.results[0].actual == 0.0


def test_main_clean_editor_run_needs_tool_selection_to_pass(tmp_path: Path) -> None:
    clean = _write_clean_editor_trace(tmp_path)

    # Nothing failed, so editor_recovery abstains and nothing is verified.
    assert main([str(clean), "--min-editor-recovery", "1.0"]) == 2
    # tool_selection yields a number on every run, so the clean run can pass.
    assert (
        main(
            [
                str(clean),
                "--min-editor-recovery",
                "1.0",
                "--min-tool-selection",
                "1.0",
                "--expected",
                "editor",
            ]
        )
        == 0
    )


@pytest.mark.skipif(
    not EDITOR_ONLY.exists(), reason="real editor-only trace not present"
)
def test_main_tool_selection_below_its_bar_fails_exit_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The trace calls read_files and editor, never apply_patch: recall 1 of 2.
    exit_code = main(
        [
            str(EDITOR_ONLY),
            "--min-tool-selection",
            "1.0",
            "--expected",
            "editor",
            "apply_patch",
        ]
    )

    assert exit_code == 1
    assert (
        "[gate] tool_selection: 0.5000 < min 1.0000 -> FAIL" in capsys.readouterr().out
    )


@pytest.mark.skipif(
    not EDITOR_ONLY.exists(), reason="real editor-only trace not present"
)
def test_main_editor_run_gated_only_on_apply_patch_flags_prints_a_hint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([str(EDITOR_ONLY), "--min-diff-coherence", "0.75"])

    assert exit_code == 2
    err = capsys.readouterr().err
    assert (
        "hint: this trace has 2 editor calls and 0 apply_patch calls; "
        "gate it with --min-editor-recovery" in err
    )


def test_main_min_tool_selection_without_expected_is_exit_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([str(BASELINE), "--min-tool-selection", "1.0"])

    assert exit_code == 2
    assert "error: --min-tool-selection needs --expected" in capsys.readouterr().err


def test_main_expected_without_min_tool_selection_is_exit_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [str(BASELINE), "--min-diff-coherence", "0.75", "--expected", "apply_patch"]
    )

    assert exit_code == 2
    err = capsys.readouterr().err
    assert "error: --expected is only read by --min-tool-selection" in err


def test_main_no_threshold_error_names_the_new_flags(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([str(BASELINE)]) == 2
    err = capsys.readouterr().err
    assert "--min-tool-selection" in err
    assert "--min-editor-recovery" in err


def test_main_unknown_expected_name_warns_like_the_cli(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main([str(BASELINE), "--min-tool-selection", "0.5", "--expected", "editr"])

    assert "warning: unknown tool 'editr'" in capsys.readouterr().err


def test_help_says_tool_selection_checks_names_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])

    help_text = " ".join(capsys.readouterr().out.split())
    assert "tool names only, not their arguments" in help_text


# --- the load-bearing constraint: the gate NEVER touches the judge ----------


def test_gate_module_imports_no_judge_or_gold_modules() -> None:
    """AST-prove gate.py imports none of the judge-arc modules.

    The gate must read ONLY the deterministic scorers -- the LLM judge is
    advisory-only (Cohen's kappa 0.0433, 95% CI [0.0000, 0.1503], N=50, which fires
    the advisory tripwire), so gating on it would contradict the very finding
    criterion 3 produced. The figure this docstring used to cite, 0.24, is the
    RETRACTED one from the earlier and smaller N=26 gold set, which was
    NOT-WASTEFUL-heavy and flattered a biased judge; ``gate.py`` says to cite only
    the N=50 number.

    The kappa moved from 0.0496 to 0.0433 when the judge prompt was fenced and all 50
    verdicts were recomputed. Neither number is gateable and the move does not change
    that: this test pins the constraint, not the figure.
    """
    tree = ast.parse(GATE_SOURCE.read_text(encoding="utf-8"))
    forbidden = {"judge", "judge_run", "agreement", "gold", "label_gold"}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[-1])
            for alias in node.names:
                imported.add(alias.name.split(".")[-1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[-1])
    leaked = imported & forbidden
    assert not leaked, f"gate.py must not import judge-arc modules, found: {leaked}"


def test_gate_result_and_report_are_frozen_value_objects() -> None:
    trace = _trace_with_apply_patch(_CLEAN_ADD)
    report = run_gate(trace, {"diff_coherence": 1.0})
    assert isinstance(report, GateReport)
    assert all(isinstance(r, GateResult) for r in report.results)
    with pytest.raises((AttributeError, TypeError)):
        report.passed = False  # type: ignore[misc]
