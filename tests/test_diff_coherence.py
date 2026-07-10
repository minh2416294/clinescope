"""Tests for the apply-coherence diff-quality scorer (criterion-2 wedge).

One test per locked decision in ``clinescope.diff_coherence``. Assertions are
mutation-resistant: they pin the exact score AND a direction (``< 1.0`` / a named
gate), so a constant-return mutant fails.

The good/bad patch bodies are transcribed VERBATIM from Cline's own executor
tests (``sdk/packages/core/src/extensions/tools/executors/apply-patch.test.ts``)
so the scorer is validated against the real grammar, not a fiction.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clinescope.__main__ import main
from clinescope.diff_coherence import DiffCoherenceScore, score_diff_coherence
from clinescope.report import render_report
from clinescope.tool_selection import score_tool_selection
from clinescope.world_a import ToolCall, Trace, load_trace

# --- Cline's real patch bodies (verbatim from apply-patch.test.ts) ------------

# Good: documented freeform Update File, no sentinels, no wrapper (test l.36-48).
GOOD_FREEFORM_UPDATE = "\n".join(
    [
        "*** Update File: page.tsx",
        "@@",
        " export default function Page() {",
        " \treturn (",
        " \t\t<div>",
        ' \t\t\t<button onClick={() => console.log("clicked")}>Click me</button>',
        '+\t\t\t<button onClick={() => console.log("cancel clicked")}>Cancel</button>',
        " \t\t</div>",
        " \t);",
        " }",
    ]
)

# Good: Add File wrapped in the legacy bash wrapper + full sentinels (test l.67-75).
GOOD_WRAPPER_ADD = "\n".join(
    [
        "%%bash",
        'apply_patch <<"EOF"',
        "*** Begin Patch",
        "*** Add File: note.txt",
        "+hello",
        "*** End Patch",
        "EOF",
    ]
)

# Good: Add File with a trailing-whitespace End sentinel (test l.120-125).
GOOD_TRAILING_WS_END = "\n".join(
    [
        "*** Begin Patch",
        "*** Add File: note.txt",
        "+hello",
        "*** End Patch ",
    ]
)

# Good: Update whose context lines start with wrapper tokens (test l.95-104) --
# proves wrapper-stripping does not corrupt a valid patch body.
GOOD_WRAPPER_TOKEN_AS_CONTEXT = "\n".join(
    [
        "*** Update File: note.txt",
        "@@",
        " alpha",
        " EOF literal",
        " ``` fence",
        "+tail",
        " omega",
    ]
)

# Bad: incomplete sentinels -- Begin present, no End (test l.140).
BAD_INCOMPLETE_SENTINELS = "*** Begin Patch\n*** Add File: note.txt\n+hello"

# Bad (grammar-only, no file needed): an Add File content line missing '+'.
BAD_ADD_FILE_MISSING_PLUS = "\n".join(
    [
        "*** Begin Patch",
        "*** Add File: note.txt",
        "+first line",
        "second line has no plus",
        "*** End Patch",
    ]
)

# Bad: a stray '***' header that is not a recognized marker.
BAD_UNKNOWN_HEADER = "\n".join(
    [
        "*** Begin Patch",
        "*** Frobnicate File: note.txt",
        "+hello",
        "*** End Patch",
    ]
)

# Bad: an Update block with no '@@' section marker at all.
BAD_UPDATE_NO_SECTION = "\n".join(
    [
        "*** Update File: note.txt",
        " alpha",
        "+beta",
        " gamma",
    ]
)

# Bad: a bash-wrapper token appears MID-BODY inside an Add block (not at an edge).
# Cline's trimWrapperLines strips wrappers only at the leading/trailing edges, so
# this reaches parseAdd and throws "missing '+'". A whole-body exact-match strip
# would wrongly delete it and score 1.0 -- the wrapper-fidelity regression.
BAD_MIDBODY_WRAPPER_IN_ADD = "\n".join(
    [
        "*** Add File: note.txt",
        "+first line",
        "apply_patch",
        "+third line",
    ]
)

# Bad: End sentinel precedes Begin -- Cline throws "incomplete sentinels".
BAD_END_BEFORE_BEGIN = "\n".join(
    [
        "*** End Patch",
        "*** Add File: note.txt",
        "+hello",
        "*** Begin Patch",
    ]
)

# Good: a structurally DIFFERENT multi-op patch -- a multi-hunk Update File with a
# Move-to rename PLUS a Delete File, exercising gates G4 (>=1 '@@' + diff-prefixed
# content across two hunks) and G6 (Move immediately after the Update header) that
# the Day-6 single-line Add-File trace never hit. CONSTRUCTED from Cline's real
# apply-patch-parser.ts grammar (parseUpdate reads '*** Move to:' on the line right
# after the header; parseDelete is a body-less header) -- NOT copied from a passing
# Cline test, because apply-patch.test.ts has no delete/rename/multi-hunk fixture.
GOOD_MULTI_OP_UPDATE_MOVE_DELETE = "\n".join(
    [
        "*** Begin Patch",
        "*** Update File: src/app.py",
        "*** Move to: src/main.py",
        "@@",
        " def greet(name):",
        '-    return "hi " + name',
        '+    return f"hello {name}"',
        "@@",
        " def farewell(name):",
        '-    return "bye " + name',
        '+    return f"goodbye {name}"',
        "*** Delete File: src/legacy.py",
        "*** End Patch",
    ]
)

# Bad: the SAME multi-op patch, but with '*** Move to:' relocated to AFTER the first
# '@@' so it no longer sits immediately after the Update header. Breaks EXACTLY one
# gate (G6 move_placement_valid); G4 still passes because the '*** Move to:' skip in
# the update-content loop is position-independent. Proves the score is COMPUTED
# (1.0 -> 0.75), not hardcoded to the Day-6 value.
BAD_MULTI_OP_MISPLACED_MOVE = "\n".join(
    [
        "*** Begin Patch",
        "*** Update File: src/app.py",
        "@@",
        "*** Move to: src/main.py",
        " def greet(name):",
        '-    return "hi " + name',
        '+    return f"hello {name}"',
        "@@",
        " def farewell(name):",
        '-    return "bye " + name',
        '+    return f"goodbye {name}"',
        "*** Delete File: src/legacy.py",
        "*** End Patch",
    ]
)


def _patch_trace(
    patch_text: str | None,
    *,
    extra_tools: tuple[str, ...] = (),
    is_error: bool | None = None,
    input_override: dict[str, object] | None = None,
) -> Trace:
    """Build a Trace whose last tool call is an apply_patch carrying ``patch_text``.

    ``input_override`` lets a test supply a deliberately mis-shaped input (e.g. the
    fictional ``{"diff": ...}``) instead of the real ``{"input": patch_text}``.
    """
    calls = [
        ToolCall(
            id=f"tool-call-{i}",
            name=name,
            input={},
            result_content=None,
            is_error=None,
        )
        for i, name in enumerate(extra_tools)
    ]
    if patch_text is not None or input_override is not None:
        payload = (
            input_override if input_override is not None else {"input": patch_text}
        )
        calls.append(
            ToolCall(
                id=f"tool-call-{len(extra_tools)}",
                name="apply_patch",
                input=payload,
                result_content="Applied" if is_error is False else None,
                is_error=is_error,
            )
        )
    return Trace(version=1, turns=(), tool_calls=tuple(calls), dropped_items=())


# --- clean / valid patches score 1.0 -----------------------------------------


def test_clean_freeform_update_scores_1() -> None:
    result = score_diff_coherence(_patch_trace(GOOD_FREEFORM_UPDATE))

    assert isinstance(result, DiffCoherenceScore)
    assert result.score == 1.0
    assert result.failed_gates == frozenset()
    assert result.violations == ()


def test_legacy_wrapper_add_scores_1() -> None:
    # The bash wrapper (%%bash / apply_patch <<"EOF" / EOF) is stripped, not scored.
    result = score_diff_coherence(_patch_trace(GOOD_WRAPPER_ADD))

    assert result.score == 1.0
    assert result.failed_gates == frozenset()


def test_trailing_ws_end_sentinel_scores_1() -> None:
    # Proves the END match uses startsWith, not '==': "*** End Patch " still balances.
    result = score_diff_coherence(_patch_trace(GOOD_TRAILING_WS_END))

    assert result.score == 1.0


def test_wrapper_token_as_context_not_stripped_scores_1() -> None:
    result = score_diff_coherence(_patch_trace(GOOD_WRAPPER_TOKEN_AS_CONTEXT))

    assert result.score == 1.0


# --- hard-zero short-circuits ------------------------------------------------


def test_incomplete_sentinels_scores_0() -> None:
    result = score_diff_coherence(_patch_trace(BAD_INCOMPLETE_SENTINELS))

    assert result.score == 0.0
    assert result.score < 0.25
    assert any("sentinel" in v.lower() for v in result.violations)


def test_unknown_header_scores_0() -> None:
    result = score_diff_coherence(_patch_trace(BAD_UNKNOWN_HEADER))

    assert result.score == 0.0
    assert any(
        "header" in v.lower() or "marker" in v.lower() for v in result.violations
    )


def test_no_apply_patch_call_scores_0() -> None:
    result = score_diff_coherence(_patch_trace(None, extra_tools=("read_files",)))

    assert result.score == 0.0
    assert result.apply_patch_call_count == 0
    assert any("apply_patch" in v.lower() for v in result.violations)


def test_fictional_diff_shape_scores_0() -> None:
    # The old examples/sample-trace.json used {"diff": <unified diff>} -- a shape
    # Cline never emits. It must score 0.0, not silently score the wrong format.
    result = score_diff_coherence(
        _patch_trace(None, input_override={"diff": "--- a\n+++ b\n@@ -1 +1 @@\n-x\n+y"})
    )

    assert result.score == 0.0
    assert any("input" in v.lower() or "shape" in v.lower() for v in result.violations)


def test_empty_patch_text_scores_0() -> None:
    result = score_diff_coherence(_patch_trace("   \n  "))

    assert result.score == 0.0
    assert any("empty" in v.lower() for v in result.violations)


def test_midbody_wrapper_in_add_is_not_stripped_and_dings() -> None:
    # Wrapper-fidelity regression: Cline strips wrappers only at the EDGES, so a
    # mid-body 'apply_patch' line inside an Add block is real content that fails
    # the '+' rule. A whole-body exact-match strip would wrongly score this 1.0.
    result = score_diff_coherence(_patch_trace(BAD_MIDBODY_WRAPPER_IN_ADD))

    assert result.score < 1.0
    assert "add_files_all_plus" in result.failed_gates


def test_end_before_begin_sentinel_scores_0() -> None:
    result = score_diff_coherence(_patch_trace(BAD_END_BEFORE_BEGIN))

    assert result.score == 0.0
    assert any("sentinel" in v.lower() for v in result.violations)


# --- averaged-gate partial scores --------------------------------------------


def test_add_file_missing_plus_scores_0_75() -> None:
    # Parseable, but one Add-File line lacks '+': exactly one of four gates fails.
    result = score_diff_coherence(_patch_trace(BAD_ADD_FILE_MISSING_PLUS))

    assert result.score == 0.75
    assert result.score < 1.0
    assert "add_files_all_plus" in result.failed_gates
    assert "add_files_all_plus" not in result.passed_gates


def test_update_hunk_without_section_marker_lowers_score() -> None:
    result = score_diff_coherence(_patch_trace(BAD_UPDATE_NO_SECTION))

    assert result.score < 1.0
    assert "update_hunks_wellformed" in result.failed_gates


# --- second real-format trace: a structurally different multi-op patch --------
# Retires (narrows) the Day-6 overfit tripwire -- the scorer is exercised on a
# multi-hunk Update + Move + Delete shape, not just a single-line Add File.


def test_multi_op_update_move_delete_scores_1() -> None:
    # All four gates pass via DIFFERENT paths than Day-6's Add-File trace: G3
    # vacuously (no Add), G4 across two '@@' hunks, G5 (all '***' known), G6
    # (Move immediately after the Update header). Pins the passed-gate set so a
    # constant-return mutant that always yields 1.0 is still caught elsewhere.
    result = score_diff_coherence(_patch_trace(GOOD_MULTI_OP_UPDATE_MOVE_DELETE))

    assert result.score == 1.0
    assert result.failed_gates == frozenset()
    assert result.violations == ()
    assert "update_hunks_wellformed" in result.passed_gates
    assert "move_placement_valid" in result.passed_gates


def test_multi_op_misplaced_move_lowers_score_to_0_75() -> None:
    # The anti-hardcode proof: the SAME patch with only the Move relocated to
    # after '@@' breaks EXACTLY one gate (G6). The score moves 1.0 -> 0.75, so
    # it is computed from this trace, not pinned to the Day-6 value. G4 must
    # still pass -- if it also failed the score would be 0.50.
    result = score_diff_coherence(_patch_trace(BAD_MULTI_OP_MISPLACED_MOVE))

    assert result.score == 0.75
    assert result.score < 1.0
    assert "move_placement_valid" in result.failed_gates
    assert "move_placement_valid" not in result.passed_gates
    assert "update_hunks_wellformed" in result.passed_gates


# --- oracle / multiplicity / guard -------------------------------------------


def test_is_error_does_not_change_score() -> None:
    # Locked decision: Cline's real verdict is CONTEXT ONLY, never the oracle.
    for flag in (True, False, None):
        result = score_diff_coherence(_patch_trace(GOOD_FREEFORM_UPDATE, is_error=flag))
        assert result.score == 1.0
        assert result.cline_apply_is_error is flag


def test_multiple_apply_patch_scores_first() -> None:
    trace = Trace(
        version=1,
        turns=(),
        tool_calls=(
            ToolCall(
                id="c1",
                name="apply_patch",
                input={"input": GOOD_FREEFORM_UPDATE},
                result_content=None,
                is_error=None,
            ),
            ToolCall(
                id="c2",
                name="apply_patch",
                input={"input": "garbage that is not a patch"},
                result_content=None,
                is_error=None,
            ),
        ),
        dropped_items=(),
    )

    result = score_diff_coherence(trace)

    assert result.score == 1.0
    assert result.apply_patch_call_count == 2


def test_trace_type_guard_raises_type_error() -> None:
    # The dangerous input: passing the raw patch STRING instead of a Trace.
    with pytest.raises(TypeError):
        score_diff_coherence(GOOD_FREEFORM_UPDATE)  # type: ignore[arg-type]


# --- report integration ------------------------------------------------------


def test_report_contains_diff_coherence_section() -> None:
    trace = _patch_trace(GOOD_FREEFORM_UPDATE)
    tool_score = score_tool_selection(trace, {"apply_patch"})
    diff_score = score_diff_coherence(trace)

    report = render_report(
        trace, tool_score, diff_coherence=diff_score, session_id="s1"
    )

    assert "[diff_coherence]" in report
    assert "score:          1.0000" in report
    assert "failed_gates:   -" in report


def test_report_omits_diff_coherence_section_when_absent() -> None:
    # Back-compat: existing single-scorer callers get no diff section.
    trace = _patch_trace(GOOD_FREEFORM_UPDATE)
    tool_score = score_tool_selection(trace, {"apply_patch"})

    report = render_report(trace, tool_score, session_id="s1")

    assert "[diff_coherence]" not in report


# --- end-to-end on the authored real-format trace ----------------------------

APPLY_PATCH_EXAMPLE = (
    Path(__file__).resolve().parent.parent / "examples" / "apply-patch-trace.json"
)


@pytest.mark.skipif(
    not APPLY_PATCH_EXAMPLE.exists(), reason="apply-patch example trace not present"
)
def test_cli_end_to_end_on_apply_patch_trace(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([str(APPLY_PATCH_EXAMPLE), "--expected", "apply_patch"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "[diff_coherence]" in out
    assert "score:          1.0000" in out


@pytest.mark.skipif(
    not APPLY_PATCH_EXAMPLE.exists(), reason="apply-patch example trace not present"
)
def test_load_apply_patch_trace_is_real_input_shape() -> None:
    # The authored trace must use Cline's real {"input": ...} shape, not {"diff": ...}.
    trace = load_trace(APPLY_PATCH_EXAMPLE)
    patch_calls = [c for c in trace.tool_calls if c.name == "apply_patch"]

    assert patch_calls, "expected an apply_patch call in the example trace"
    assert "input" in patch_calls[0].input
    assert "diff" not in patch_calls[0].input


# --- end-to-end on the SECOND authored real-format trace (multi-op) -----------
# The second, structurally-different trace that narrows the overfit tripwire: a
# multi-hunk Update + Move + Delete, distinct from Day-6's single Add-File.

MULTI_OP_EXAMPLE = (
    Path(__file__).resolve().parent.parent / "examples" / "multi-op-trace.json"
)


@pytest.mark.skipif(
    not MULTI_OP_EXAMPLE.exists(), reason="multi-op example trace not present"
)
def test_cli_end_to_end_on_multi_op_trace(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([str(MULTI_OP_EXAMPLE), "--expected", "apply_patch"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "[diff_coherence]" in out
    assert "score:          1.0000" in out
    # Proves it exercised the Move/Update gates, not just the Day-6 Add path.
    assert "move_placement_valid" in out
    assert "update_hunks_wellformed" in out


@pytest.mark.skipif(
    not MULTI_OP_EXAMPLE.exists(), reason="multi-op example trace not present"
)
def test_multi_op_trace_scores_1_via_multi_hunk_update_and_move() -> None:
    # Loads the real JSON off disk (not an inline body) and confirms the score is
    # 1.0 through the multi-hunk Update + Move + Delete gates -- and that its patch
    # text is genuinely different from Day-6's Add-File trace (id-keyed join gives
    # cline_apply_is_error, and the patch carries a Move + Delete).
    trace = load_trace(MULTI_OP_EXAMPLE)
    result = score_diff_coherence(trace)

    assert result.score == 1.0
    assert result.failed_gates == frozenset()
    assert result.cline_apply_is_error is False

    patch_calls = [c for c in trace.tool_calls if c.name == "apply_patch"]
    assert patch_calls, "expected an apply_patch call in the multi-op trace"
    patch_text = patch_calls[0].input["input"]
    assert "*** Move to:" in patch_text
    assert "*** Delete File:" in patch_text
    assert patch_text.count("@@") == 2
