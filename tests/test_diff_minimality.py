"""Tests for the diff-minimality scorer (criterion-2 wedge, second slice).

One test per locked decision in ``clinescope.diff_minimality``. Assertions are
mutation-resistant: they pin the exact score AND a direction (an exact number, a
named field), so a constant-return mutant fails. The spine is the tight-vs-bloated
pair: the SAME two real edits score 1.0 when surgical and 0.0 when each hunk is a
blind whole-block rewrite -- proving the number is computed from the patch text,
not constant.

The good patch bodies are the repo's own real-format example traces
(``examples/apply-patch-trace.json`` Add File; ``examples/multi-op-trace.json``
2-hunk Update + Move + Delete). The bloated body is authored from the SAME real
grammar (Cline's ``apply-patch-parser.ts``), differing only in that each hunk
deletes and retypes its whole function body instead of touching one line.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clinescope.__main__ import main
from clinescope.diff_minimality import (
    FLOOR,
    DiffMinimalityScore,
    score_diff_minimality,
)
from clinescope.report import render_report
from clinescope.tool_selection import score_tool_selection
from clinescope.world_a import ToolCall, Trace, load_trace

# --- real + authored patch bodies --------------------------------------------

# Tight: the multi-op body verbatim from examples/multi-op-trace.json -- each of
# the two hunks touches exactly one line (1 context / 1 '-' / 1 '+'). min(d,a)=1.
TIGHT_MULTI_OP = "\n".join(
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

# Bloated: the SAME two edits, but each hunk deletes the whole 4-line function
# body and retypes it (only the greeting/parting string actually changes). Each
# hunk is now a run of 4 '-' immediately followed by 4 '+' -> min(d,a)=4 >= FLOOR.
BLOATED_MULTI_OP = "\n".join(
    [
        "*** Begin Patch",
        "*** Update File: src/app.py",
        "*** Move to: src/main.py",
        "@@",
        "-def greet(name):",
        '-    greeting = "hi"',
        '-    msg = greeting + " " + name',
        "-    return msg",
        "+def greet(name):",
        '+    greeting = "hello"',
        '+    msg = greeting + " " + name',
        "+    return msg",
        "@@",
        "-def farewell(name):",
        '-    parting = "bye"',
        '-    msg = parting + " " + name',
        "-    return msg",
        "+def farewell(name):",
        '+    parting = "goodbye"',
        '+    msg = parting + " " + name',
        "+    return msg",
        "*** Delete File: src/legacy.py",
        "*** End Patch",
    ]
)

# Add File only (verbatim from examples/apply-patch-trace.json): no Update hunks.
ADD_FILE_ONLY = "*** Begin Patch\n*** Add File: note.txt\n+hello\n*** End Patch"

# One blind hunk + one tight hunk -> exactly half the hunks are blind -> 0.5.
HALF_BLIND = "\n".join(
    [
        "*** Begin Patch",
        "*** Update File: a.py",
        "@@",
        "-line one",
        "-line two",
        "-line three",
        "+new one",
        "+new two",
        "+new three",
        "*** Update File: b.py",
        "@@",
        " kept",
        "-old",
        "+new",
        "*** End Patch",
    ]
)

# Unparseable: an unknown '***' header -- diff_coherence_normalize rejects it, so
# no hunks can be extracted -> hard 0.0 (mis-shape), mirroring the sibling.
UNPARSEABLE = "*** Begin Patch\n*** Frobnicate File: x\n+y\n*** End Patch"


def _patch_trace(
    patch_text: str | None,
    *,
    extra_tools: tuple[str, ...] = (),
    is_error: bool | None = None,
    input_override: dict[str, object] | None = None,
) -> Trace:
    """Build a Trace whose last tool call is an apply_patch carrying ``patch_text``.

    Mirrors the helper in test_diff_coherence.py so the two scorers are tested
    against identically-shaped traces.
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


# --- the mutation-proof spine: same edits, tight vs bloated -------------------


def test_tight_multi_op_scores_1() -> None:
    result = score_diff_minimality(_patch_trace(TIGHT_MULTI_OP))

    assert isinstance(result, DiffMinimalityScore)
    assert result.score == 1.0
    assert result.applicable is True
    assert result.blind_rewrite_hunks == 0
    assert result.hunks_with_body == 2
    assert result.violations == ()


def test_bloated_multi_op_scores_0() -> None:
    # SAME two edits as tight, but each hunk is a blind whole-block rewrite.
    result = score_diff_minimality(_patch_trace(BLOATED_MULTI_OP))

    assert result.score == 0.0
    assert result.score < 1.0
    assert result.blind_rewrite_hunks == 2
    assert result.hunks_with_body == 2
    assert any("blind" in v.lower() for v in result.violations)


def test_half_blind_scores_0_5() -> None:
    # One blind hunk, one tight hunk -> exactly one of two hunks flagged.
    result = score_diff_minimality(_patch_trace(HALF_BLIND))

    assert result.score == 0.5
    assert result.blind_rewrite_hunks == 1
    assert result.hunks_with_body == 2


def test_one_blind_of_eight_does_not_round_up_to_1() -> None:
    # Regression: 1 blind hunk of 8 -> raw 1 - 1/8 = 0.875. round() (banker's OR
    # half-up) ties 0.875 UP to 1.0 -> a WRONG headline that hides the blind
    # rewrite. Flooring to the quarter below gives 0.75, upholding the invariant
    # "score == 1.0 iff zero blind rewrites". (Found in Day-8 code review.)
    hunks = ["*** Begin Patch", "*** Update File: a.py"]
    # one blind hunk: 3x'-' then 3x'+'
    hunks += ["@@", "-b1", "-b2", "-b3", "+n1", "+n2", "+n3"]
    # seven tight hunks: 1 context, 1 '-', 1 '+'
    for i in range(7):
        hunks += ["@@", f" ctx{i}", f"-old{i}", f"+new{i}"]
    hunks.append("*** End Patch")
    result = score_diff_minimality(_patch_trace("\n".join(hunks)))

    assert result.hunks_with_body == 8
    assert result.blind_rewrite_hunks == 1
    assert result.score == 0.75  # NOT 1.0


# --- vacuous / not-applicable / hard-zero ------------------------------------


def test_add_file_only_scores_vacuous_1() -> None:
    result = score_diff_minimality(_patch_trace(ADD_FILE_ONLY))

    assert result.score == 1.0
    assert result.applicable is True
    assert result.hunks_with_body == 0
    assert result.add_file_lines == 1


def test_no_apply_patch_call_is_not_applicable() -> None:
    result = score_diff_minimality(_patch_trace(None, extra_tools=("read_files",)))

    assert result.applicable is False
    assert result.score is None
    assert result.apply_patch_call_count == 0


def test_empty_patch_text_scores_hard_0() -> None:
    result = score_diff_minimality(_patch_trace("   \n  "))

    assert result.score == 0.0
    assert result.applicable is True
    assert any("empty" in v.lower() for v in result.violations)


def test_unparseable_patch_scores_hard_0() -> None:
    result = score_diff_minimality(_patch_trace(UNPARSEABLE))

    assert result.score == 0.0
    assert any(
        "unparseable" in v.lower() or "grammar" in v.lower() or "header" in v.lower()
        for v in result.violations
    )


def test_fictional_diff_shape_is_not_applicable() -> None:
    # {"diff": ...} is a shape Cline never emits; there is no readable patch text.
    result = score_diff_minimality(
        _patch_trace(None, input_override={"diff": "--- a\n+++ b\n@@\n-x\n+y"})
    )

    assert result.score == 0.0
    assert any("input" in v.lower() or "shape" in v.lower() for v in result.violations)


# --- descriptive evidence + orthogonality ------------------------------------


def test_mean_context_density_reported_on_tight() -> None:
    # Each of the 2 hunks: 1 context / 2 changed -> ratio 1/3; mean = 1/3.
    result = score_diff_minimality(_patch_trace(TIGHT_MULTI_OP))

    assert result.mean_context_density == pytest.approx(1 / 3)


def test_context_density_never_enters_score() -> None:
    # A padded-context hunk (lots of context) is NOT blind, so it still scores
    # 1.0 -- context is deliberately descriptive-only, never penalized.
    padded = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: a.py",
            "@@",
            " ctx one",
            " ctx two",
            " ctx three",
            " ctx four",
            "-old",
            "+new",
            "*** End Patch",
        ]
    )
    result = score_diff_minimality(_patch_trace(padded))

    assert result.score == 1.0
    # 4 context lines, 2 changed (1 '-' + 1 '+') -> density 4/6, NOT in the score.
    assert result.mean_context_density == pytest.approx(4 / 6)


def test_is_error_does_not_change_score() -> None:
    # Locked decision: Cline's real verdict is CONTEXT ONLY, never the oracle.
    for flag in (True, False, None):
        result = score_diff_minimality(_patch_trace(TIGHT_MULTI_OP, is_error=flag))
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
                input={"input": TIGHT_MULTI_OP},
                result_content=None,
                is_error=None,
            ),
            ToolCall(
                id="c2",
                name="apply_patch",
                input={"input": BLOATED_MULTI_OP},
                result_content=None,
                is_error=None,
            ),
        ),
        dropped_items=(),
    )

    result = score_diff_minimality(trace)

    assert result.score == 1.0
    assert result.apply_patch_call_count == 2


def test_floor_is_three() -> None:
    # A 2-line delete-then-retype block is below FLOOR -> not blind (surgical).
    below_floor = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: a.py",
            "@@",
            "-old one",
            "-old two",
            "+new one",
            "+new two",
            "*** End Patch",
        ]
    )
    result = score_diff_minimality(_patch_trace(below_floor))

    assert FLOOR == 3
    assert result.score == 1.0
    assert result.blind_rewrite_hunks == 0


def test_trace_type_guard_raises_type_error() -> None:
    # The dangerous input: passing the raw patch STRING instead of a Trace.
    with pytest.raises(TypeError):
        score_diff_minimality(TIGHT_MULTI_OP)  # type: ignore[arg-type]


# --- report integration ------------------------------------------------------


def test_report_contains_diff_minimality_section() -> None:
    trace = _patch_trace(TIGHT_MULTI_OP)
    tool_score = score_tool_selection(trace, {"apply_patch"})
    min_score = score_diff_minimality(trace)

    report = render_report(
        trace, tool_score, diff_minimality=min_score, session_id="s1", verbose=True
    )

    assert "[diff_minimality]" in report
    assert "score:          1.0000" in report


def test_report_omits_diff_minimality_section_when_absent() -> None:
    # Back-compat: existing callers that pass no minimality score get no section.
    trace = _patch_trace(TIGHT_MULTI_OP)
    tool_score = score_tool_selection(trace, {"apply_patch"})

    report = render_report(trace, tool_score, session_id="s1")

    assert "[diff_minimality]" not in report


def test_report_shows_not_applicable_when_score_none() -> None:
    trace = _patch_trace(None, extra_tools=("read_files",))
    tool_score = score_tool_selection(trace, {"read_files"})
    min_score = score_diff_minimality(trace)

    report = render_report(
        trace, tool_score, diff_minimality=min_score, session_id="s1", verbose=True
    )

    assert "[diff_minimality]" in report
    assert "n/a" in report.lower()


# --- end-to-end on the authored real-format traces ---------------------------

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
MULTI_OP_EXAMPLE = EXAMPLES / "multi-op-trace.json"
ADD_FILE_EXAMPLE = EXAMPLES / "apply-patch-trace.json"


@pytest.mark.skipif(
    not MULTI_OP_EXAMPLE.exists(), reason="multi-op example trace not present"
)
def test_cli_end_to_end_on_multi_op_trace(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([str(MULTI_OP_EXAMPLE), "--expected", "apply_patch", "--verbose"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "[diff_minimality]" in out
    assert "score:          1.0000" in out


@pytest.mark.skipif(
    not MULTI_OP_EXAMPLE.exists(), reason="multi-op example trace not present"
)
def test_multi_op_example_scores_1_directly() -> None:
    trace = load_trace(MULTI_OP_EXAMPLE)
    result = score_diff_minimality(trace)

    assert result.score == 1.0
    assert result.hunks_with_body == 2


@pytest.mark.skipif(
    not ADD_FILE_EXAMPLE.exists(), reason="add-file example trace not present"
)
def test_add_file_example_scores_vacuous_1() -> None:
    trace = load_trace(ADD_FILE_EXAMPLE)
    result = score_diff_minimality(trace)

    assert result.score == 1.0
    assert result.hunks_with_body == 0
    assert result.add_file_lines == 1
