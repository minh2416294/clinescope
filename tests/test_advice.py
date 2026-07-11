"""CHECK tests for the Q2 advice/coach layer (written first, TDD).

Turns each FAILING scorer's existing evidence into a taxonomy label + concrete
"what to do" guidance -- deterministic, no LLM, no recomputation. The tests pin
that (a) a failing scorer yields advice that quotes its REAL evidence (the actual
missing tool / violation / count / failed file), (b) a passing or abstaining scorer
yields NO advice (no noise), and (c) the taxonomy label matches the failure kind.
"""

from pathlib import Path

import pytest

from clinescope.__main__ import main
from clinescope.advice import (
    FailureLabel,
    advice_for_apply_recovery,
    advice_for_diff_coherence,
    advice_for_diff_minimality,
    advice_for_tool_selection,
)
from clinescope.apply_recovery import ApplyRecoveryScore
from clinescope.diff_coherence import DiffCoherenceScore
from clinescope.diff_minimality import DiffMinimalityScore
from clinescope.tool_selection import ToolSelectionScore

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
# A trace that fails multiple scorers: tool_selection (no read_files),
# diff_coherence (75/100, a real Add-File violation), apply_recovery (0/1 on note.txt).
BADPATCH = EXAMPLES / "gate-regression-badpatch.json"
# A clean trace: everything passes / abstains -> --advice must add no block.
CLEAN = EXAMPLES / "apply-patch-trace.json"


@pytest.mark.skipif(not BADPATCH.exists(), reason="needs example trace")
def test_cli_advice_on_failing_trace_quotes_real_evidence(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [str(BADPATCH), "--expected", "read_files", "apply_patch", "--advice"]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "advice (how to improve the agent):" in out
    # Each advice entry must reference the scorer's REAL evidence, not a template.
    assert "read_files" in out  # tool_selection: the actual missing tool
    assert "malformed" in out  # diff_coherence: the malformed-patch label/line
    assert "note.txt" in out  # apply_recovery: the actual unrecovered file
    # Taxonomy labels present.
    assert "missing_tools" in out
    assert "no_apply_recovery" in out


@pytest.mark.skipif(not CLEAN.exists(), reason="needs example trace")
def test_cli_advice_on_clean_trace_adds_no_block(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main([str(CLEAN), "--expected", "read_files", "apply_patch", "--advice"])
    out = capsys.readouterr().out
    assert "advice (how to improve the agent):" not in out


@pytest.mark.skipif(not BADPATCH.exists(), reason="needs example trace")
def test_cli_default_output_has_no_advice_without_flag(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The default (no --advice) must be unchanged: no advice block appears.
    main([str(BADPATCH), "--expected", "read_files", "apply_patch"])
    out = capsys.readouterr().out
    assert "advice (how to improve the agent):" not in out


# --- tool_selection ----------------------------------------------------------


def test_tool_selection_advice_names_the_missing_tool() -> None:
    score = ToolSelectionScore(
        score=0.5,
        expected=frozenset({"read_files", "apply_patch"}),
        used=frozenset({"apply_patch"}),
        matched=frozenset({"apply_patch"}),
        missing=frozenset({"read_files"}),
        unexpected=frozenset(),
    )
    advice = advice_for_tool_selection(score)
    assert advice is not None
    assert advice.label is FailureLabel.MISSING_TOOLS
    blob = "\n".join(advice.lines)
    assert "read_files" in blob  # the REAL missing tool, quoted from evidence


def test_tool_selection_perfect_score_yields_no_advice() -> None:
    score = ToolSelectionScore(
        score=1.0,
        expected=frozenset({"read_files"}),
        used=frozenset({"read_files"}),
        matched=frozenset({"read_files"}),
        missing=frozenset(),
        unexpected=frozenset(),
    )
    assert advice_for_tool_selection(score) is None


# --- diff_coherence ----------------------------------------------------------


def test_diff_coherence_advice_quotes_the_real_violation() -> None:
    score = DiffCoherenceScore(
        score=0.75,
        passed_gates=frozenset({"update_hunks_wellformed"}),
        failed_gates=frozenset({"add_files_all_plus"}),
        violations=("Add File content line missing '+': 'done'",),
        apply_patch_call_count=1,
        cline_apply_is_error=None,
    )
    advice = advice_for_diff_coherence(score)
    assert advice is not None
    assert advice.label is FailureLabel.MALFORMED_PATCH
    blob = "\n".join(advice.lines)
    assert "Add File content line missing '+': 'done'" in blob


def test_diff_coherence_perfect_score_yields_no_advice() -> None:
    score = DiffCoherenceScore(
        score=1.0,
        passed_gates=frozenset(),
        failed_gates=frozenset(),
        violations=(),
        apply_patch_call_count=1,
        cline_apply_is_error=None,
    )
    assert advice_for_diff_coherence(score) is None


# --- diff_minimality ---------------------------------------------------------


def test_diff_minimality_advice_reports_the_real_blind_count() -> None:
    score = DiffMinimalityScore(
        score=0.25,
        applicable=True,
        blind_rewrite_hunks=3,
        hunks_with_body=4,
        violations=("blind block rewrite in hunk 0: ...",),
        mean_context_density=0.1,
        add_file_lines=0,
        apply_patch_call_count=1,
        cline_apply_is_error=None,
    )
    advice = advice_for_diff_minimality(score)
    assert advice is not None
    assert advice.label is FailureLabel.BLIND_REWRITE
    blob = "\n".join(advice.lines)
    assert "3 of 4" in blob  # the REAL N-of-M count, in order (template-proof)


def test_diff_minimality_perfect_yields_no_advice() -> None:
    score = DiffMinimalityScore(
        score=1.0,
        applicable=True,
        blind_rewrite_hunks=0,
        hunks_with_body=2,
        violations=(),
        mean_context_density=0.3,
        add_file_lines=0,
        apply_patch_call_count=1,
        cline_apply_is_error=None,
    )
    assert advice_for_diff_minimality(score) is None


def test_diff_minimality_abstain_yields_no_advice() -> None:
    score = DiffMinimalityScore(
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
    assert advice_for_diff_minimality(score) is None


# --- apply_recovery ----------------------------------------------------------


def test_apply_recovery_advice_names_the_unrecovered_file() -> None:
    score = ApplyRecoveryScore(
        score=0.0,
        applicable=True,
        total_failed_pairs=1,
        confirmed_recovered_pairs=0,
        unrecovered_pairs=1,
        partially_recovered_failures=0,
        same_file_refail_count=0,
        unverified_reattempt_pairs=0,
        verdict_coverage=1.0,
        failed_target_paths=("note.txt",),
        recovery_pairs=(),
        unparseable_failed_calls=0,
        apply_patch_call_count=1,
        violations=("unrecovered apply_patch failure: file 'note.txt' ...",),
        cline_apply_is_error=None,
    )
    advice = advice_for_apply_recovery(score)
    assert advice is not None
    assert advice.label is FailureLabel.NO_APPLY_RECOVERY
    blob = "\n".join(advice.lines)
    assert "note.txt" in blob  # the REAL unrecovered file
    assert "0/1" in blob  # the REAL recovered/total count


def test_apply_recovery_full_recovery_yields_no_advice() -> None:
    score = ApplyRecoveryScore(
        score=1.0,
        applicable=True,
        total_failed_pairs=1,
        confirmed_recovered_pairs=1,
        unrecovered_pairs=0,
        partially_recovered_failures=0,
        same_file_refail_count=0,
        unverified_reattempt_pairs=0,
        verdict_coverage=1.0,
        failed_target_paths=("a.py",),
        recovery_pairs=((0, 1, "a.py"),),
        unparseable_failed_calls=0,
        apply_patch_call_count=2,
        violations=(),
        cline_apply_is_error=None,
    )
    assert advice_for_apply_recovery(score) is None


def test_apply_recovery_abstain_yields_no_advice() -> None:
    score = ApplyRecoveryScore(
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
    assert advice_for_apply_recovery(score) is None
