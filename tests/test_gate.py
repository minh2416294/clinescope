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
from pathlib import Path

import pytest

from clinescope.gate import GateReport, GateResult, main, render_gate_report, run_gate
from clinescope.world_a import ToolCall, Trace

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
BASELINE = EXAMPLES / "apply-patch-trace.json"
RECOVERY_REGRESSION = EXAMPLES / "live-gpt-oss-apply-fail.json"
COHERENCE_REGRESSION = EXAMPLES / "gate-regression-badpatch.json"
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


# --- the load-bearing constraint: the gate NEVER touches the judge ----------


def test_gate_module_imports_no_judge_or_gold_modules() -> None:
    """AST-prove gate.py imports none of the judge-arc modules.

    The gate must read ONLY the deterministic scorers -- the LLM judge is
    advisory-only (kappa=0.24 fired the advisory tripwire), so gating on it
    would contradict the very finding criterion 3 produced.
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
