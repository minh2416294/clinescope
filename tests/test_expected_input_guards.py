"""CHECK tests for the Q1 --expected input-footgun fixes (written first, TDD).

Three behaviours, each a footgun a real user hit while dogfooding:

* Omitting --expected must NOT print a vacuous ``tool_selection 100/100 PASS``
  (a false positive); it shows ``n/a`` + how to enable scoring.
* A typo in a tool name must warn ``did you mean ...`` to stderr (a false
  negative otherwise -- blaming the agent for the user's spelling); the run
  still scores and exits 0.
* --list-tools prints the vocabulary and exits 0 with no trace required.

Plus the U1/U2 report changes (clean-run footer, self-explaining n/a).
"""

from pathlib import Path

import pytest

from clinescope.__main__ import main
from clinescope.apply_recovery import ApplyRecoveryScore
from clinescope.diff_coherence import DiffCoherenceScore
from clinescope.diff_minimality import DiffMinimalityScore
from clinescope.report import render_report
from clinescope.tool_selection import score_tool_selection
from clinescope.world_a import ToolCall, Trace

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
APPLY_PATCH_TRACE = EXAMPLES / "apply-patch-trace.json"


def _trace(*tool_names: str) -> Trace:
    tool_calls = tuple(
        ToolCall(
            id=f"tool-call-{i}",
            name=name,
            input={},
            result_content=None,
            is_error=None,
        )
        for i, name in enumerate(tool_names)
    )
    return Trace(version=1, turns=(), tool_calls=tool_calls, dropped_items=())


# --- Footgun 1: omitting --expected is no longer a vacuous pass ---------------


def test_omitting_expected_shows_na_not_vacuous_pass_render() -> None:
    trace = _trace("read_files", "apply_patch")
    score = score_tool_selection(trace, set())
    report = render_report(trace, score, session_id="s1", expected_provided=False)
    tool_line = next(
        ln for ln in report.splitlines() if ln.startswith("tool_selection")
    )
    assert "n/a" in tool_line
    assert "100/100" not in tool_line
    assert "PASS" not in tool_line
    assert "--expected" in tool_line


def test_expected_provided_still_scores_normally_render() -> None:
    trace = _trace("read_files", "apply_patch")
    score = score_tool_selection(trace, {"read_files", "apply_patch"})
    report = render_report(trace, score, session_id="s1", expected_provided=True)
    tool_line = next(
        ln for ln in report.splitlines() if ln.startswith("tool_selection")
    )
    assert "100/100" in tool_line
    assert "PASS" in tool_line


@pytest.mark.skipif(not APPLY_PATCH_TRACE.exists(), reason="needs example trace")
def test_cli_no_expected_prints_na_and_note(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([str(APPLY_PATCH_TRACE)])
    out = capsys.readouterr().out
    assert exit_code == 0
    tool_line = next(ln for ln in out.splitlines() if ln.startswith("tool_selection"))
    assert "n/a" in tool_line
    assert "100/100" not in tool_line


# --- Footgun 2: a typo warns instead of silently scoring 0 -------------------


@pytest.mark.skipif(not APPLY_PATCH_TRACE.exists(), reason="needs example trace")
def test_cli_typo_warns_with_suggestion_and_still_exits_0(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([str(APPLY_PATCH_TRACE), "--expected", "read_files", "aply_patch"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "unknown tool 'aply_patch'" in captured.err
    assert "did you mean 'apply_patch'?" in captured.err
    # It STILL scores (the report prints); the warning does not abort.
    assert "tool_selection" in captured.out


@pytest.mark.skipif(not APPLY_PATCH_TRACE.exists(), reason="needs example trace")
def test_cli_valid_expected_emits_no_warning(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main([str(APPLY_PATCH_TRACE), "--expected", "read_files", "apply_patch"])
    err = capsys.readouterr().err
    assert err == ""


# --- --list-tools ------------------------------------------------------------


def test_list_tools_prints_vocab_and_exits_0(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--list-tools"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "apply_patch" in out
    assert "read_files" in out
    assert "submit_and_exit" in out


# --- U2: self-explaining n/a --------------------------------------------------


def test_diff_minimality_na_says_why() -> None:
    trace = _trace("read_files")
    score = score_tool_selection(trace, {"read_files"})
    minimality = DiffMinimalityScore(
        score=None,
        applicable=False,
        blind_rewrite_hunks=0,
        hunks_with_body=0,
        violations=("no apply_patch tool call in trace",),
        mean_context_density=None,
        add_file_lines=0,
        apply_patch_call_count=0,
        cline_apply_is_error=None,
    )
    report = render_report(trace, score, session_id="s1", diff_minimality=minimality)
    line = next(ln for ln in report.splitlines() if ln.startswith("diff_minimality"))
    assert "n/a" in line
    assert "nothing to check" in line


def test_apply_recovery_na_says_nothing_failed() -> None:
    trace = _trace("read_files", "apply_patch")
    score = score_tool_selection(trace, {"read_files"})
    recovery = ApplyRecoveryScore(
        score=None,
        applicable=False,
        total_failed_pairs=0,
        confirmed_recovered_pairs=0,
        unrecovered_pairs=0,
        partially_recovered_failures=0,
        same_file_refail_count=0,
        unverified_reattempt_pairs=0,
        verdict_coverage=1.0,
        failed_target_paths=(),
        recovery_pairs=(),
        unparseable_failed_calls=0,
        apply_patch_call_count=1,
        violations=(),
        cline_apply_is_error=None,
    )
    report = render_report(trace, score, session_id="s1", apply_recovery=recovery)
    line = next(ln for ln in report.splitlines() if ln.startswith("apply_recovery"))
    assert "n/a" in line
    assert "nothing to recover" in line


# --- U1: clean-run footer -----------------------------------------------------


def test_clean_run_footer_when_everything_passes() -> None:
    trace = _trace("read_files", "apply_patch")
    score = score_tool_selection(trace, {"read_files", "apply_patch"})
    coherence = DiffCoherenceScore(
        score=1.0,
        passed_gates=frozenset(),
        failed_gates=frozenset(),
        violations=(),
        apply_patch_call_count=1,
        cline_apply_is_error=None,
    )
    report = render_report(trace, score, session_id="s1", diff_coherence=coherence)
    assert "clean run - nothing to fix" in report


def test_no_clean_run_footer_when_a_scorer_fails() -> None:
    trace = _trace("apply_patch")
    score = score_tool_selection(trace, {"read_files", "apply_patch"})  # missing 1
    report = render_report(trace, score, session_id="s1")
    assert "clean run" not in report


def test_omitted_expected_does_not_block_clean_run_footer() -> None:
    # tool_selection abstains (no --expected), coherence passes -> still a clean run.
    trace = _trace("apply_patch")
    score = score_tool_selection(trace, set())
    coherence = DiffCoherenceScore(
        score=1.0,
        passed_gates=frozenset(),
        failed_gates=frozenset(),
        violations=(),
        apply_patch_call_count=1,
        cline_apply_is_error=None,
    )
    report = render_report(
        trace,
        score,
        session_id="s1",
        diff_coherence=coherence,
        expected_provided=False,
    )
    assert "clean run - nothing to fix" in report
