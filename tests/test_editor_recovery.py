"""Tests for the editor-recovery scorer (the editor-family trajectory slice).

One test per locked decision in ``clinescope.editor_recovery``. Assertions are
mutation-resistant: they pin the exact score AND a direction (an exact number, a
named evidence field), so a constant-return mutant fails. The spine is the
recovered-vs-never-recovered pair: the SAME failed ``editor`` call on ``calc.py``
scores 1.0 when a later confirmed call re-touches it and 0.0 when the agent gives
up -- proving the number is computed from the trajectory, not constant.

This scorer is the ``apply_recovery`` sibling ported to Cline's ``editor`` tool.
Two things differ and nothing else:

* the target is read straight off ``input["path"]``, because an editor call names
  its file directly instead of hiding it in patch grammar;
* there is no ``partially_recovered_failures`` counter, because one editor call
  touches exactly ONE path, so a call can never be half-recovered.

The verdict oracle is shared verbatim with ``apply_recovery`` via
``clinescope.tool_verdict``. The result-content shapes below are copied from the
real captured Cline CLI run committed at ``examples/live-granite-editor-recovery.json``,
not invented: a failure carries ``{"query":"edit:<path>","result":"","error":"Editor
operation failed: ...","success":false}`` and a success carries
``{"query":"edit:<path>","result":"Edited <path>...","success":true}``, in both cases
with NO ``is_error`` field, which is exactly why the secondary ``"success"`` oracle is
load-bearing here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinescope.apply_recovery import score_apply_recovery
from clinescope.diff_coherence import score_diff_coherence
from clinescope.diff_minimality import score_diff_minimality
from clinescope.editor_recovery import (
    EditorRecoveryScore,
    score_editor_recovery,
)
from clinescope.world_a import ToolCall, Trace, load_trace

CALC = "C:\\work\\calc.py"
OTHER = "C:\\work\\other.py"

# A REAL captured Cline CLI session (granite4.1:8b via Ollama, 2026-08-23). The agent
# first called editor with no old_text, Cline rejected it, and the agent retried with
# old_text and succeeded -- a genuine failure-then-recovery trajectory that no
# authored fixture can prove exists in the wild.
_REAL_TRACE = (
    Path(__file__).resolve().parent.parent
    / "examples"
    / "live-granite-editor-recovery.json"
)


# --- trace builders ----------------------------------------------------------


def _editor_call(
    call_id: str,
    path: str | None,
    *,
    is_error: bool | None,
    old_text: str | None = "def f():\n    return 1\n",
    new_text: str = "def f():\n    return 2\n",
    insert_line: int | None = None,
) -> ToolCall:
    """One editor tool call on ``path`` with the given loader-level verdict.

    ``is_error`` is the joined ``tool_result.is_error``: ``True`` = Cline reported
    a failure, ``False`` = Cline confirmed success, ``None`` = no verdict was
    joined. The three states are distinct and load-bearing. ``path=None`` builds
    the pathless call that must fall to the ``<no path>`` sentinel.
    """
    payload: dict[str, object] = {"new_text": new_text}
    if path is not None:
        payload["path"] = path
    if old_text is not None:
        payload["old_text"] = old_text
    if insert_line is not None:
        payload["insert_line"] = insert_line
    return ToolCall(
        id=call_id,
        name="editor",
        input=payload,
        result_content=None if is_error is None else "result",
        is_error=is_error,
    )


def _editor_call_json(
    call_id: str,
    path: str,
    *,
    result_content: str | list[object] | None,
) -> ToolCall:
    """An editor call whose joined tool_result is a REAL Cline result shape.

    No ``is_error`` field (so the loader gives ``None``) and a JSON-string
    ``result_content``, which is what a genuine Cline editor result looks like.
    ``result_content`` is deliberately permissive so a test can pass a non-str and
    prove the oracle fails closed.
    """
    return ToolCall(
        id=call_id,
        name="editor",
        input={"path": path, "old_text": "a\n", "new_text": "b\n"},
        result_content=result_content,
        is_error=None,
    )


def _editor_result_content(*, success: bool, path: str) -> str:
    """The exact JSON-string content Cline writes for an editor result.

    Copied from the committed real capture; see the module docstring.
    """
    if success:
        payload: dict[str, object] = {
            "query": f"edit:{path}",
            "result": f"Edited {path}\n```diff\n+4: def sub(a, b):\n```",
            "success": True,
        }
    else:
        payload = {
            "query": f"edit:{path}",
            "result": "",
            "error": (
                "Editor operation failed: Parameter `old_text` is required when "
                "editing an existing file without `insert_line`"
            ),
            "success": False,
        }
    return json.dumps(payload)


def _editor_trace(*calls: ToolCall) -> Trace:
    """A Trace whose tool_calls are exactly ``calls`` in chronological order."""
    return Trace(version=1, turns=(), tool_calls=tuple(calls), dropped_items=())


# --- the mutation-proof spine: recovered vs never-recovered ------------------


def test_recovered_same_path_scores_1() -> None:
    trace = _editor_trace(
        _editor_call("c1", CALC, is_error=True),
        _editor_call("c2", CALC, is_error=False),
    )
    result = score_editor_recovery(trace)

    assert isinstance(result, EditorRecoveryScore)
    assert result.score == 1.0
    assert result.applicable is True
    assert result.total_failed_pairs == 1
    assert result.confirmed_recovered_pairs == 1
    assert result.unrecovered_pairs == 0
    assert result.same_file_refail_count == 0
    assert result.recovery_pairs == ((0, 1, CALC),)
    assert result.violations == ()


def test_unrecovered_same_path_scores_0() -> None:
    # The SAME failure as above, with the retry removed. Only the trajectory
    # differs, so a constant-return mutant cannot pass both this and the test above.
    trace = _editor_trace(_editor_call("c1", CALC, is_error=True))
    result = score_editor_recovery(trace)

    assert result.score == 0.0
    assert result.applicable is True
    assert result.total_failed_pairs == 1
    assert result.confirmed_recovered_pairs == 0
    assert result.unrecovered_pairs == 1
    assert result.recovery_pairs == ()
    assert len(result.violations) == 1
    # The violation renders the path with !r, matching the apply_patch sibling, so
    # a Windows path arrives backslash-escaped. Pin the rendered form exactly.
    assert repr(CALC) in result.violations[0]


def test_two_failures_one_recovered_scores_half() -> None:
    # Pins a NON-endpoint value, so a mutant that returns only 0.0/1.0 fails.
    trace = _editor_trace(
        _editor_call("c1", CALC, is_error=True),
        _editor_call("c2", OTHER, is_error=True),
        _editor_call("c3", CALC, is_error=False),
    )
    result = score_editor_recovery(trace)

    assert result.score == 0.5
    assert result.total_failed_pairs == 2
    assert result.confirmed_recovered_pairs == 1
    assert result.unrecovered_pairs == 1
    assert result.failed_target_paths == tuple(sorted({CALC, OTHER}))


# --- abstention: the three honest vacuous cases -------------------------------


def test_no_editor_calls_abstains() -> None:
    trace = _editor_trace(
        ToolCall(
            id="r1",
            name="read_files",
            input={"paths": [CALC]},
            result_content="ok",
            is_error=False,
        )
    )
    result = score_editor_recovery(trace)

    assert result.score is None
    assert result.applicable is False
    assert result.editor_call_count == 0
    assert result.verdict_coverage is None
    assert result.violations == ("no editor tool call in trace",)


def test_clean_run_abstains_without_an_evidence_gap() -> None:
    trace = _editor_trace(
        _editor_call("c1", CALC, is_error=False),
        _editor_call("c2", CALC, is_error=False),
    )
    result = score_editor_recovery(trace)

    assert result.score is None
    assert result.applicable is False
    assert result.verdict_coverage == 1.0
    assert result.violations == ()


def test_all_verdicts_missing_abstains_with_a_named_evidence_gap() -> None:
    # A truncated export must never launder into "nothing failed".
    trace = _editor_trace(
        _editor_call("c1", CALC, is_error=None),
        _editor_call("c2", CALC, is_error=None),
    )
    result = score_editor_recovery(trace)

    assert result.score is None
    assert result.applicable is False
    assert result.verdict_coverage == 0.0
    assert len(result.violations) == 1
    assert "no editor verdicts joined" in result.violations[0]


# --- the shared "success"-JSON oracle -----------------------------------------


def test_success_json_oracle_resolves_a_failure_and_a_recovery() -> None:
    # The real Cline shape: no is_error field anywhere, outcome only in the content.
    trace = _editor_trace(
        _editor_call_json(
            "c1", CALC, result_content=_editor_result_content(success=False, path=CALC)
        ),
        _editor_call_json(
            "c2", CALC, result_content=_editor_result_content(success=True, path=CALC)
        ),
    )
    result = score_editor_recovery(trace)

    assert result.score == 1.0
    assert result.total_failed_pairs == 1
    assert result.confirmed_recovered_pairs == 1
    assert result.verdict_coverage == 1.0
    # The CONTEXT field stays RAW: the trace carried no is_error field at all.
    assert result.cline_editor_is_error is None


def test_is_error_wins_over_the_content_oracle() -> None:
    # A real bool is authoritative even when the content disagrees.
    conflicted = ToolCall(
        id="c1",
        name="editor",
        input={"path": CALC, "old_text": "a\n", "new_text": "b\n"},
        result_content=_editor_result_content(success=True, path=CALC),
        is_error=True,
    )
    result = score_editor_recovery(_editor_trace(conflicted))

    assert result.total_failed_pairs == 1
    assert result.score == 0.0
    assert result.cline_editor_is_error is True


def test_non_str_content_fails_closed_to_no_verdict() -> None:
    trace = _editor_trace(_editor_call_json("c1", CALC, result_content=[{"a": 1}]))
    result = score_editor_recovery(trace)

    assert result.verdict_coverage == 0.0
    assert result.applicable is False


def test_unparseable_json_content_fails_closed_to_no_verdict() -> None:
    trace = _editor_trace(_editor_call_json("c1", CALC, result_content="{truncated"))
    result = score_editor_recovery(trace)

    assert result.verdict_coverage == 0.0
    assert result.applicable is False


# --- target rules --------------------------------------------------------------


def test_pathless_failed_call_can_never_be_recovered() -> None:
    # A failed call with no usable path still counts in the denominator: failing
    # illegibly must not drop the failure out of the score.
    trace = _editor_trace(
        _editor_call("c1", None, is_error=True),
        _editor_call("c2", CALC, is_error=False),
    )
    result = score_editor_recovery(trace)

    assert result.score == 0.0
    assert result.total_failed_pairs == 1
    assert result.pathless_failed_calls == 1
    assert result.failed_target_paths == ("<no path>",)


def test_empty_path_is_treated_as_pathless() -> None:
    trace = _editor_trace(_editor_call("c1", "", is_error=True))
    result = score_editor_recovery(trace)

    assert result.pathless_failed_calls == 1
    assert result.failed_target_paths == ("<no path>",)


def test_non_str_path_is_treated_as_pathless() -> None:
    # Guards the isinstance(raw, str) test specifically: a `raw is None` check
    # would let a numeric path through and then crash or mis-match downstream.
    call = ToolCall(
        id="c1",
        name="editor",
        input={"path": 123, "old_text": "a\n", "new_text": "b\n"},
        result_content="result",
        is_error=True,
    )
    result = score_editor_recovery(_editor_trace(call))

    assert result.score == 0.0
    assert result.pathless_failed_calls == 1
    assert result.failed_target_paths == ("<no path>",)


def test_trailing_whitespace_is_stripped_before_paths_are_matched() -> None:
    # Guards the .rstrip() in _editor_target_path: without it these two calls
    # name different files and the failure reads as unrecovered.
    trace = _editor_trace(
        _editor_call("c1", CALC + "   ", is_error=True),
        _editor_call("c2", CALC, is_error=False),
    )
    result = score_editor_recovery(trace)

    assert result.score == 1.0
    assert result.failed_target_paths == (CALC,)


def test_verdict_coverage_reports_a_partial_fraction() -> None:
    # One resolved verdict, one unresolved. Pins a NON-endpoint coverage value so a
    # mutant returning only 0.0/1.0 for coverage fails.
    trace = _editor_trace(
        _editor_call("c1", CALC, is_error=True),
        _editor_call("c2", CALC, is_error=None),
    )
    result = score_editor_recovery(trace)

    assert result.verdict_coverage == 0.5


def test_a_different_path_does_not_recover_the_failure() -> None:
    trace = _editor_trace(
        _editor_call("c1", CALC, is_error=True),
        _editor_call("c2", OTHER, is_error=False),
    )
    result = score_editor_recovery(trace)

    assert result.score == 0.0
    assert result.unrecovered_pairs == 1


def test_recovery_must_be_strictly_later() -> None:
    # An EARLIER success does not recover a LATER failure.
    trace = _editor_trace(
        _editor_call("c1", CALC, is_error=False),
        _editor_call("c2", CALC, is_error=True),
    )
    result = score_editor_recovery(trace)

    assert result.score == 0.0
    assert result.unrecovered_pairs == 1


def test_a_later_verdictless_reattempt_is_not_a_recovery() -> None:
    # None means "no verdict", not "it worked". Admitting it would let an
    # adversary max the score by truncating the trace after any re-attempt.
    trace = _editor_trace(
        _editor_call("c1", CALC, is_error=True),
        _editor_call("c2", CALC, is_error=None),
    )
    result = score_editor_recovery(trace)

    assert result.score == 0.0
    assert result.confirmed_recovered_pairs == 0
    assert result.unverified_reattempt_pairs == 1


def test_same_path_refail_is_counted() -> None:
    trace = _editor_trace(
        _editor_call("c1", CALC, is_error=True),
        _editor_call("c2", CALC, is_error=True),
        _editor_call("c3", CALC, is_error=False),
    )
    result = score_editor_recovery(trace)

    assert result.score == 1.0
    assert result.total_failed_pairs == 2
    assert result.same_file_refail_count == 1
    assert result.recovery_pairs == ((0, 2, CALC), (1, 2, CALC))


def test_recovery_pair_names_the_first_confirming_call() -> None:
    trace = _editor_trace(
        _editor_call("c1", CALC, is_error=True),
        _editor_call("c2", CALC, is_error=False),
        _editor_call("c3", CALC, is_error=False),
    )
    result = score_editor_recovery(trace)

    assert result.recovery_pairs == ((0, 1, CALC),)


def test_apply_patch_calls_are_ignored_entirely() -> None:
    # The editor scorer must not read its sibling's tool, and vice versa.
    trace = _editor_trace(
        ToolCall(
            id="p1",
            name="apply_patch",
            input={"input": "*** Begin Patch\n*** Update File: x\n*** End Patch"},
            result_content="result",
            is_error=True,
        )
    )
    result = score_editor_recovery(trace)

    assert result.applicable is False
    assert result.editor_call_count == 0


def test_non_trace_input_raises_type_error() -> None:
    with pytest.raises(TypeError, match="takes a Trace"):
        score_editor_recovery("def f():\n    return 1\n")  # type: ignore[arg-type]


# --- the real captured trace ---------------------------------------------------


def test_real_capture_scores_a_genuine_failure_then_recovery() -> None:
    trace = load_trace(_REAL_TRACE)
    editor_paths = {
        call.input["path"] for call in trace.tool_calls if call.name == "editor"
    }
    assert len(editor_paths) == 1
    path = editor_paths.pop()
    assert path.endswith("calc.py")

    result = score_editor_recovery(trace)

    assert result.editor_call_count == 2
    assert result.score == 1.0
    assert result.applicable is True
    assert result.total_failed_pairs == 1
    assert result.confirmed_recovered_pairs == 1
    assert result.unrecovered_pairs == 0
    # Both verdicts came from the "success"-JSON oracle: the real trace carries no
    # is_error field at all, which is exactly why the secondary read exists.
    assert result.verdict_coverage == 1.0
    assert result.cline_editor_is_error is None
    assert result.recovery_pairs == ((1, 2, path),)
    assert result.violations == ()


def test_real_capture_makes_the_apply_patch_scorers_go_dark() -> None:
    # The motivating failure, pinned on real data: on an editor-only session the
    # three apply_patch scorers produce one meaningless hard zero and two blanks.
    trace = load_trace(_REAL_TRACE)

    assert score_diff_coherence(trace).score == 0.0
    assert score_diff_minimality(trace).score is None
    assert score_apply_recovery(trace).score is None
