"""Tests for the apply-recovery scorer (criterion-2 wedge, third slice).

One test per locked decision in ``clinescope.apply_recovery``. Assertions are
mutation-resistant: they pin the exact score AND a direction (an exact number, a
named evidence field), so a constant-return mutant fails. The spine is the
recovered-vs-never-recovered pair: the SAME failed ``apply_patch`` on ``src/auth.py``
scores 1.0 when a later confirmed retry re-touches it and 0.0 when the agent gives
up -- proving the number is computed from the trajectory, not constant.

Unlike the two sibling scorers, apply-recovery reads ``is_error`` as its ORACLE
(the failure/success verdict IS the signal), not as context-only. It also needs
MULTI-CALL traces (a failure followed by a later retry), so these tests build
``Trace`` objects directly from an ``_apply_call`` factory rather than the
single-call ``_patch_trace`` helper the sibling tests use.

Patch bodies follow Cline's real ``apply_patch`` grammar (the ``*** Begin Patch``
envelope, file paths on ``*** Update/Add/Delete File:`` / ``*** Move to:`` headers)
exactly as the sibling scorers' example traces do.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinescope.apply_recovery import (
    ApplyRecoveryScore,
    score_apply_recovery,
)
from clinescope.__main__ import main
from clinescope.report import render_report
from clinescope.tool_selection import score_tool_selection
from clinescope.world_a import ToolCall, Trace, load_trace

# --- patch bodies (Cline apply_patch grammar) --------------------------------


def _update_patch(path: str) -> str:
    """A minimal well-formed single-hunk Update patch touching ``path``."""
    return "\n".join(
        [
            "*** Begin Patch",
            f"*** Update File: {path}",
            "@@",
            " def f():",
            "-    return 1",
            "+    return 2",
            "*** End Patch",
        ]
    )


def _add_patch(path: str) -> str:
    return f"*** Begin Patch\n*** Add File: {path}\n+hello\n*** End Patch"


# A multi-file patch: touches BOTH a.py and b.py in one call.
MULTI_FILE_PATCH = "\n".join(
    [
        "*** Begin Patch",
        "*** Update File: src/a.py",
        "@@",
        " def a():",
        "-    return 1",
        "+    return 2",
        "*** Update File: src/b.py",
        "@@",
        " def b():",
        "-    return 3",
        "+    return 4",
        "*** End Patch",
    ]
)

# A rename: Update source src/app.py, Move destination src/main.py. Under the
# edit-intent-only target rule, targets = {src/app.py, src/main.py}.
RENAME_PATCH = "\n".join(
    [
        "*** Begin Patch",
        "*** Update File: src/app.py",
        "*** Move to: src/main.py",
        "@@",
        " def greet():",
        '-    return "hi"',
        '+    return "hello"',
        "*** End Patch",
    ]
)

# A patch that ONLY deletes a file (no edit-intent target). Under edit-intent-only,
# targets = {} (Delete paths are excluded from the match set).
DELETE_ONLY_PATCH = "*** Begin Patch\n*** Delete File: src/legacy.py\n*** End Patch"

# Unparseable: an unknown '***' header -- diff_coherence_normalize rejects it, so
# no file paths can be extracted (empty target set).
UNPARSEABLE_PATCH = "*** Begin Patch\n*** Frobnicate File: x\n+y\n*** End Patch"


# --- trace builders ----------------------------------------------------------


def _apply_call(
    call_id: str,
    patch_text: str,
    *,
    is_error: bool | None,
) -> ToolCall:
    """One apply_patch tool call carrying ``patch_text`` with the given verdict.

    ``is_error`` is the joined ``tool_result.is_error``: ``True`` = Cline reported
    a failure, ``False`` = Cline confirmed success, ``None`` = no tool_result was
    joined (a truncated trace). The three states are distinct and load-bearing.
    """
    return ToolCall(
        id=call_id,
        name="apply_patch",
        input={"input": patch_text},
        result_content=None if is_error is None else "result",
        is_error=is_error,
    )


def _apply_call_json(
    call_id: str,
    patch_text: str,
    *,
    result_content: str | list[object] | None,
) -> ToolCall:
    """One apply_patch call whose joined tool_result is a REAL Cline result shape.

    Unlike ``_apply_call`` (which sets the loader-level ``is_error`` bool directly),
    this builds the shape a genuine Cline ``apply_patch`` result carries: NO
    ``is_error`` field (so the loader gives ``is_error=None``) and a JSON-string
    ``result_content`` like ``{"query":"apply_patch","result":"...","success":true}``.
    Reading the ``"success"`` bool out of that content is the secondary oracle. The
    ``result_content`` type is deliberately permissive (``str | list | None``) so a
    test can pass a non-str (the ``read_files`` list shape) to prove fail-closed.
    """
    return ToolCall(
        id=call_id,
        name="apply_patch",
        # A list is type-legal here: ToolCall.result_content is ToolResultContent
        # | None (str | list[object] | None) since R3, matching a real read_files
        # list shape -- so the oracle's isinstance(str) abstain path can be tested.
        result_content=result_content,
        input={"input": patch_text},
        is_error=None,
    )


def _apply_result_content(*, success: bool) -> str:
    """The exact JSON-string content Cline writes for an apply_patch result.

    Success: ``{"query":"apply_patch","result":"Successfully applied ...","success":true}``.
    Failure: ``{"query":"apply_patch","result":"","error":"apply_patch failed: ...",
    "success":false}`` (source: cline definitions.ts createApplyPatchTool).
    """
    if success:
        payload = {
            "query": "apply_patch",
            "result": "Successfully applied patch to the following files:\nsrc/auth.py",
            "success": True,
        }
    else:
        payload = {
            "query": "apply_patch",
            "result": "",
            "error": "apply_patch failed: hunk 1: Could not find matching context",
            "success": False,
        }
    return json.dumps(payload)


def _recovery_trace(*calls: ToolCall) -> Trace:
    """A Trace whose tool_calls are exactly ``calls`` in order (chronological)."""
    return Trace(version=1, turns=(), tool_calls=tuple(calls), dropped_items=())


# --- the mutation-proof spine: recovered vs never-recovered ------------------


def test_recovered_same_file_scores_1() -> None:
    # apply_patch fails on src/auth.py, then a later confirmed retry re-touches it.
    trace = _recovery_trace(
        _apply_call("c1", _update_patch("src/auth.py"), is_error=True),
        _apply_call("c2", _update_patch("src/auth.py"), is_error=False),
    )
    result = score_apply_recovery(trace)

    assert isinstance(result, ApplyRecoveryScore)
    assert result.score == 1.0
    assert result.applicable is True
    assert result.total_failed_pairs == 1
    assert result.confirmed_recovered_pairs == 1
    assert result.unrecovered_pairs == 0
    assert result.same_file_refail_count == 0
    assert result.violations == ()


def test_never_recovered_scores_0() -> None:
    # SAME failure as the recovered case, but the agent gives up (no later retry).
    trace = _recovery_trace(
        _apply_call("c1", _update_patch("src/auth.py"), is_error=True),
    )
    result = score_apply_recovery(trace)

    assert result.score == 0.0
    assert result.score < 1.0
    assert result.applicable is True
    assert result.total_failed_pairs == 1
    assert result.confirmed_recovered_pairs == 0
    assert result.unrecovered_pairs == 1
    assert any(
        "unrecovered" in v.lower() or "src/auth.py" in v for v in result.violations
    )


def test_truncated_retry_none_verdict_scores_0() -> None:
    # A second apply_patch on src/auth.py EXISTS but has NO tool_result (verdict
    # None). This is the anti-truncation guard: None is never scored as recovery,
    # so an adversary cannot max the score by truncating the trace after a retry.
    trace = _recovery_trace(
        _apply_call("c1", _update_patch("src/auth.py"), is_error=True),
        _apply_call("c2", _update_patch("src/auth.py"), is_error=None),
    )
    result = score_apply_recovery(trace)

    assert result.score == 0.0  # NOT 1.0
    assert result.confirmed_recovered_pairs == 0
    assert result.unverified_reattempt_pairs == 1


def test_brute_force_spam_scores_1_but_surfaces_refail() -> None:
    # Fail 3x in a row on src/auth.py, then a 4th confirmed success. All three
    # failures are recovered by the terminal success -> 1.0, but the flailing is
    # made VISIBLE via same_file_refail_count, not hidden behind the headline.
    trace = _recovery_trace(
        _apply_call("c1", _update_patch("src/auth.py"), is_error=True),
        _apply_call("c2", _update_patch("src/auth.py"), is_error=True),
        _apply_call("c3", _update_patch("src/auth.py"), is_error=True),
        _apply_call("c4", _update_patch("src/auth.py"), is_error=False),
    )
    result = score_apply_recovery(trace)

    assert result.score == 1.0
    assert result.total_failed_pairs == 3
    assert result.confirmed_recovered_pairs == 3
    assert result.same_file_refail_count == 2  # 2 of the 3 failures re-failed after


def test_multi_file_partial_scores_0_5() -> None:
    # One failed call touches {src/a.py, src/b.py} -> 2 failed pairs. A later
    # confirmed retry fixes only src/a.py -> 1 of 2 recovered -> 0.5.
    trace = _recovery_trace(
        _apply_call("c1", MULTI_FILE_PATCH, is_error=True),
        _apply_call("c2", _update_patch("src/a.py"), is_error=False),
    )
    result = score_apply_recovery(trace)

    assert result.score == 0.5
    assert result.total_failed_pairs == 2
    assert result.confirmed_recovered_pairs == 1
    assert result.partially_recovered_failures == 1


# --- vacuous / not-applicable ------------------------------------------------


def test_no_apply_patch_call_is_not_applicable() -> None:
    trace = _recovery_trace(
        ToolCall(
            id="r1",
            name="read_files",
            input={},
            result_content="ok",
            is_error=False,
        )
    )
    result = score_apply_recovery(trace)

    assert result.applicable is False
    assert result.score is None
    assert result.apply_patch_call_count == 0


def test_vacuous_clean_all_succeed_is_not_applicable() -> None:
    # apply_patch calls present, verdicts present, NONE failed -> recovery rate is
    # undefined (nothing to recover). applicable=False with verdict_coverage > 0.
    trace = _recovery_trace(
        _apply_call("c1", _update_patch("src/x.py"), is_error=False),
        _apply_call("c2", _add_patch("src/y.py"), is_error=False),
    )
    result = score_apply_recovery(trace)

    assert result.applicable is False
    assert result.score is None
    assert result.total_failed_pairs == 0
    assert result.verdict_coverage == 1.0
    assert not any("no apply_patch verdicts" in v.lower() for v in result.violations)


def test_vacuous_no_verdicts_distinguished_from_clean() -> None:
    # apply_patch calls present but ALL have is_error=None (no tool_results joined
    # -- a truncated export). Still not-applicable, but the reason is an EVIDENCE
    # GAP, not "nothing failed" -- so verdict_coverage==0 and a distinct reason.
    trace = _recovery_trace(
        _apply_call("c1", _update_patch("src/x.py"), is_error=None),
        _apply_call("c2", _update_patch("src/y.py"), is_error=None),
    )
    result = score_apply_recovery(trace)

    assert result.applicable is False
    assert result.score is None
    assert result.verdict_coverage == 0.0
    assert any("no apply_patch verdicts" in v.lower() for v in result.violations)


def test_unparseable_failure_counts_in_denominator() -> None:
    # A failed apply_patch whose patch is grammar-unparseable has an EMPTY target
    # set, but the failure still counts: one '<unparseable>' sentinel pair that
    # can never be recovered (illegible failure cannot escape the denominator).
    trace = _recovery_trace(
        _apply_call("c1", UNPARSEABLE_PATCH, is_error=True),
    )
    result = score_apply_recovery(trace)

    assert result.score == 0.0
    assert result.total_failed_pairs == 1
    assert result.unparseable_failed_calls == 1
    assert any("unparseable" in v.lower() for v in result.violations)


# --- target-set edge cases (edit-intent-only rule) ---------------------------


def test_delete_only_retry_does_not_recover_edit_failure() -> None:
    # A failed EDIT on src/auth.py is NOT recovered by a later patch that merely
    # DELETES an unrelated file -- Delete paths are excluded from the match set.
    trace = _recovery_trace(
        _apply_call("c1", _update_patch("src/auth.py"), is_error=True),
        _apply_call("c2", DELETE_ONLY_PATCH, is_error=False),
    )
    result = score_apply_recovery(trace)

    assert result.score == 0.0
    assert result.confirmed_recovered_pairs == 0


def test_move_destination_is_a_recovery_target() -> None:
    # A failed edit naming src/main.py is recovered by a later confirmed patch
    # whose Move-to DESTINATION is src/main.py (destination is in the target set).
    trace = _recovery_trace(
        _apply_call("c1", _update_patch("src/main.py"), is_error=True),
        _apply_call("c2", RENAME_PATCH, is_error=False),
    )
    result = score_apply_recovery(trace)

    assert result.score == 1.0
    assert result.confirmed_recovered_pairs == 1


def test_move_source_alone_does_not_false_recover() -> None:
    # A later confirmed patch whose only edit-intent match would be the Move
    # SOURCE (src/app.py) does NOT recover a failure on src/app.py -- the source
    # is excluded; only the destination src/main.py is a target of RENAME_PATCH.
    trace = _recovery_trace(
        _apply_call("c1", _update_patch("src/app.py"), is_error=True),
        _apply_call("c2", RENAME_PATCH, is_error=False),
    )
    result = score_apply_recovery(trace)

    # src/app.py is the Move SOURCE of c2, excluded -> no recovery.
    assert result.score == 0.0
    assert result.confirmed_recovered_pairs == 0


def test_two_updates_before_move_excludes_only_the_moved_source() -> None:
    # Highest-risk adjacency case: two Update headers, then a Move. The Move binds
    # to the IMMEDIATELY-preceding Update (src/b.py), so src/b.py is the move source
    # (excluded) and src/main.py the destination (included); the first Update
    # (src/a.py), NOT followed by a Move, stays an edit target.
    two_updates_then_move = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: src/a.py",
            "@@",
            " def a():",
            "-    return 1",
            "+    return 2",
            "*** Update File: src/b.py",
            "*** Move to: src/main.py",
            "@@",
            " def b():",
            "-    return 3",
            "+    return 4",
            "*** End Patch",
        ]
    )
    # A confirmed later patch touching src/a.py recovers the a.py failure...
    trace = _recovery_trace(
        _apply_call("c1", two_updates_then_move, is_error=True),
        _apply_call("c2", _update_patch("src/a.py"), is_error=False),
    )
    result = score_apply_recovery(trace)

    # Failed targets = {src/a.py, src/main.py} (src/b.py the move SOURCE excluded).
    assert result.total_failed_pairs == 2
    assert "src/a.py" in result.failed_target_paths
    assert "src/main.py" in result.failed_target_paths
    assert "src/b.py" not in result.failed_target_paths
    # Only src/a.py recovered -> 1 of 2.
    assert result.score == 0.5
    assert result.confirmed_recovered_pairs == 1


def test_recovery_pairs_names_the_fixing_call() -> None:
    # recovery_pairs is surfaced evidence: (failed_call_index, fixer_call_index, path).
    trace = _recovery_trace(
        _apply_call("c1", _update_patch("src/auth.py"), is_error=True),
        _apply_call("c2", _update_patch("src/other.py"), is_error=False),
        _apply_call("c3", _update_patch("src/auth.py"), is_error=False),
    )
    result = score_apply_recovery(trace)

    assert result.score == 1.0
    # The failure at index 0 is fixed by the confirmed call at index 2 (not 1).
    assert result.recovery_pairs == ((0, 2, "src/auth.py"),)


def test_report_shows_recovered_by_line() -> None:
    trace = _recovery_trace(
        _apply_call("c1", _update_patch("src/auth.py"), is_error=True),
        _apply_call("c2", _update_patch("src/auth.py"), is_error=False),
    )
    tool_score = score_tool_selection(trace, {"apply_patch"})
    rec_score = score_apply_recovery(trace)

    report = render_report(trace, tool_score, apply_recovery=rec_score, session_id="s1")

    assert "recovered_by:" in report
    assert "src/auth.py @ call 0->1" in report


def test_earlier_success_does_not_recover_later_failure() -> None:
    # Recovery must be STRICTLY LATER: a success BEFORE the failure is not a fix.
    trace = _recovery_trace(
        _apply_call("c1", _update_patch("src/auth.py"), is_error=False),
        _apply_call("c2", _update_patch("src/auth.py"), is_error=True),
    )
    result = score_apply_recovery(trace)

    assert result.score == 0.0
    assert result.total_failed_pairs == 1
    assert result.confirmed_recovered_pairs == 0


def test_different_file_success_does_not_recover() -> None:
    # A later success on a DIFFERENT file does not recover the failure -- the
    # file-match gate is real, not a rubber-stamp on "any later success".
    trace = _recovery_trace(
        _apply_call("c1", _update_patch("src/auth.py"), is_error=True),
        _apply_call("c2", _update_patch("src/other.py"), is_error=False),
    )
    result = score_apply_recovery(trace)

    assert result.score == 0.0
    assert result.confirmed_recovered_pairs == 0


def test_one_success_recovers_multiple_same_file_failures() -> None:
    # Two separate failures on src/auth.py, one later confirmed success -> both
    # recovered (existential over all later calls).
    trace = _recovery_trace(
        _apply_call("c1", _update_patch("src/auth.py"), is_error=True),
        _apply_call("c2", _update_patch("src/auth.py"), is_error=True),
        _apply_call("c3", _update_patch("src/auth.py"), is_error=False),
    )
    result = score_apply_recovery(trace)

    assert result.score == 1.0
    assert result.total_failed_pairs == 2
    assert result.confirmed_recovered_pairs == 2
    assert result.same_file_refail_count == 1


def test_trace_type_guard_raises_type_error() -> None:
    # The dangerous input: passing the raw patch STRING instead of a Trace.
    with pytest.raises(TypeError):
        score_apply_recovery(_update_patch("src/auth.py"))  # type: ignore[arg-type]


# --- the "success"-JSON secondary oracle (real Cline apply_patch result shape) --
#
# A genuine Cline apply_patch result carries NO is_error field; the outcome lives
# inside the tool_result CONTENT as a JSON string {"...","success":true/false}
# (source: cline definitions.ts createApplyPatchTool + agent-message-codec.ts).
# So on real traces is_error joins as None and the scorer must read "success" as a
# SECONDARY oracle -- else it abstains on every real run (the Day-10 gap). is_error
# stays AUTHORITATIVE when present (a bool wins); the oracle only fills the None gap.


def test_success_json_failure_then_confirmed_retry_scores_1() -> None:
    # THE real-shape recovery: neither call has is_error; the first content says
    # success:false (a failure), the second success:true (a confirmed fix) on the
    # same file. The oracle must resolve both and score recovery = 1.0 -- exactly
    # what the four authored is_error traces could prove but no REAL trace could.
    trace = _recovery_trace(
        _apply_call_json(
            "c1",
            _update_patch("src/auth.py"),
            result_content=_apply_result_content(success=False),
        ),
        _apply_call_json(
            "c2",
            _update_patch("src/auth.py"),
            result_content=_apply_result_content(success=True),
        ),
    )
    result = score_apply_recovery(trace)

    assert result.score == 1.0
    assert result.applicable is True
    assert result.total_failed_pairs == 1
    assert result.confirmed_recovered_pairs == 1
    assert result.verdict_coverage == 1.0


def test_success_json_failure_never_recovered_scores_0() -> None:
    # A real-shape failure (success:false) with no later confirmed retry -> 0.0.
    trace = _recovery_trace(
        _apply_call_json(
            "c1",
            _update_patch("src/auth.py"),
            result_content=_apply_result_content(success=False),
        ),
    )
    result = score_apply_recovery(trace)

    assert result.score == 0.0
    assert result.applicable is True
    assert result.total_failed_pairs == 1
    assert result.confirmed_recovered_pairs == 0


def test_success_json_all_true_is_clean_run_not_truncated() -> None:
    # A real all-success run (both content success:true, no is_error) is a CLEAN
    # run, not a truncated export: verdict_coverage must be 1.0 (the oracle read the
    # verdicts) and the "no verdicts joined" violation must NOT fire. This is the
    # Day-10 misfire fixed -- previously such a trace falsely tripped truncation.
    trace = _recovery_trace(
        _apply_call_json(
            "c1",
            _update_patch("src/x.py"),
            result_content=_apply_result_content(success=True),
        ),
        _apply_call_json(
            "c2",
            _update_patch("src/y.py"),
            result_content=_apply_result_content(success=True),
        ),
    )
    result = score_apply_recovery(trace)

    assert result.applicable is False  # nothing failed -> recovery undefined
    assert result.score is None
    assert result.verdict_coverage == 1.0
    assert not any("no apply_patch verdicts" in v.lower() for v in result.violations)


def test_is_error_bool_wins_over_conflicting_success_json() -> None:
    # PRECEDENCE: is_error is authoritative. is_error=False (Cline-confirmed
    # success) with a conflicting success:false in content -> the bool wins, so the
    # call is a confirmed SUCCESS, and it recovers the earlier failure -> 1.0.
    conflicting = ToolCall(
        id="c2",
        name="apply_patch",
        input={"input": _update_patch("src/auth.py")},
        result_content=_apply_result_content(success=False),  # says failed...
        is_error=False,  # ...but is_error says confirmed success -> WINS
    )
    trace = _recovery_trace(
        _apply_call("c1", _update_patch("src/auth.py"), is_error=True),
        conflicting,
    )
    result = score_apply_recovery(trace)

    assert result.score == 1.0
    assert result.confirmed_recovered_pairs == 1


def test_is_error_true_wins_over_success_true_json() -> None:
    # The other precedence direction: is_error=True (failure) with success:true in
    # content -> the bool wins, so this call is a FAILURE, not a recovery.
    conflicting = ToolCall(
        id="c2",
        name="apply_patch",
        input={"input": _update_patch("src/auth.py")},
        result_content=_apply_result_content(success=True),  # says success...
        is_error=True,  # ...but is_error says failed -> WINS
    )
    trace = _recovery_trace(
        _apply_call("c1", _update_patch("src/auth.py"), is_error=True),
        conflicting,
    )
    result = score_apply_recovery(trace)

    # c1 fails, c2 also fails (is_error wins) and re-touches auth.py -> refail, not
    # recovery: nothing confirmed -> 0.0.
    assert result.score == 0.0
    assert result.confirmed_recovered_pairs == 0
    assert result.same_file_refail_count == 1


@pytest.mark.parametrize(
    "content",
    [
        "result",  # the existing _apply_call non-JSON string
        "",  # empty
        '{"success":tr',  # truncated / invalid JSON
        "null",  # valid JSON but not a dict
        "true",  # valid JSON bool, not a dict
        "[]",  # valid JSON list, not a dict
        "42",  # valid JSON number, not a dict
        '{"query":"apply_patch"}',  # dict but no "success" key
        '{"success":1}',  # "success" present but not a bool (int)
        '{"success":"true"}',  # "success" a string, not a bool
        '{"success":null}',  # "success" explicit null
    ],
)
def test_oracle_fails_closed_on_non_success_content(content: str) -> None:
    # Fail CLOSED: any content the oracle cannot confidently read as a bool
    # "success" leaves the verdict None (abstain) -- never a guessed verdict. A
    # single failing call with unreadable content is thus NOT a confirmed failure;
    # with no readable verdict at all the run is not-applicable (verdict_coverage 0).
    trace = _recovery_trace(
        _apply_call_json("c1", _update_patch("src/x.py"), result_content=content),
    )
    result = score_apply_recovery(trace)

    assert result.applicable is False
    assert result.score is None
    assert result.verdict_coverage == 0.0


def test_oracle_ignores_list_content_read_files_shape() -> None:
    # read_files results carry a LIST content [{...,"success":true}] (structured,
    # not a JSON string). The oracle only parses str content -> a list is ignored
    # (fails closed). Here an apply_patch call is given the list shape defensively;
    # it must abstain, not crash or mis-read.
    list_content: list[object] = [{"query": "x", "result": "y", "success": True}]
    trace = _recovery_trace(
        _apply_call_json("c1", _update_patch("src/x.py"), result_content=list_content),
    )
    result = score_apply_recovery(trace)

    assert result.applicable is False
    assert result.score is None
    assert result.verdict_coverage == 0.0


def test_cline_apply_is_error_stays_raw_none_under_oracle() -> None:
    # The cline_apply_is_error CONTEXT field mirrors the RAW first-call is_error
    # (parity with the sibling scorers), NOT the oracle-resolved verdict. A real
    # apply_patch failure resolved only via the "success" oracle still reports the
    # raw is_error (None) here -- the score uses the effective verdict, the context
    # field stays raw.
    trace = _recovery_trace(
        _apply_call_json(
            "c1",
            _update_patch("src/auth.py"),
            result_content=_apply_result_content(success=False),
        ),
    )
    result = score_apply_recovery(trace)

    assert result.total_failed_pairs == 1  # resolved via the oracle
    assert result.cline_apply_is_error is None  # but the context field is RAW


# --- report integration ------------------------------------------------------


def test_report_contains_apply_recovery_section() -> None:
    trace = _recovery_trace(
        _apply_call("c1", _update_patch("src/auth.py"), is_error=True),
        _apply_call("c2", _update_patch("src/auth.py"), is_error=False),
    )
    tool_score = score_tool_selection(trace, {"apply_patch"})
    rec_score = score_apply_recovery(trace)

    report = render_report(trace, tool_score, apply_recovery=rec_score, session_id="s1")

    assert "[apply_recovery]" in report
    assert "score:          1.0000" in report


def test_report_omits_apply_recovery_section_when_absent() -> None:
    # Back-compat: existing callers that pass no recovery score get no section.
    trace = _recovery_trace(
        _apply_call("c1", _update_patch("src/auth.py"), is_error=True),
        _apply_call("c2", _update_patch("src/auth.py"), is_error=False),
    )
    tool_score = score_tool_selection(trace, {"apply_patch"})

    report = render_report(trace, tool_score, session_id="s1")

    assert "[apply_recovery]" not in report


def test_report_shows_not_applicable_when_score_none() -> None:
    trace = _recovery_trace(
        ToolCall(
            id="r1",
            name="read_files",
            input={},
            result_content="ok",
            is_error=False,
        )
    )
    tool_score = score_tool_selection(trace, {"read_files"})
    rec_score = score_apply_recovery(trace)

    report = render_report(trace, tool_score, apply_recovery=rec_score, session_id="s1")

    assert "[apply_recovery]" in report
    assert "n/a" in report.lower()


# --- end-to-end on the authored real-format trace ----------------------------

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
RECOVERY_EXAMPLE = EXAMPLES / "apply-recovery-trace.json"


@pytest.mark.skipif(
    not RECOVERY_EXAMPLE.exists(), reason="apply-recovery example trace not present"
)
def test_cli_end_to_end_on_recovery_trace(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([str(RECOVERY_EXAMPLE), "--expected", "apply_patch"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "[apply_recovery]" in out
    assert "score:          1.0000" in out


@pytest.mark.skipif(
    not RECOVERY_EXAMPLE.exists(), reason="apply-recovery example trace not present"
)
def test_recovery_example_scores_1_directly() -> None:
    trace = load_trace(RECOVERY_EXAMPLE)
    result = score_apply_recovery(trace)

    assert result.score == 1.0
    assert result.applicable is True
    assert result.total_failed_pairs == 1
    assert result.confirmed_recovered_pairs == 1
