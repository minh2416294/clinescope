import pytest

from agent_eval_harness.tool_selection import ToolSelectionScore, score_tool_selection
from agent_eval_harness.world_a import ToolCall, Trace


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


def test_all_expected_tools_used_scores_1() -> None:
    result = score_tool_selection(_trace("read_files"), {"read_files"})

    assert isinstance(result, ToolSelectionScore)
    assert result.score == 1.0
    assert result.matched == frozenset({"read_files"})
    assert result.missing == frozenset()


def test_missing_expected_tool_lowers_score() -> None:
    result = score_tool_selection(_trace("read_files"), {"read_files", "write_file"})

    assert result.score == 0.5
    assert result.score < 1.0
    assert "write_file" in result.missing
    assert result.matched == frozenset({"read_files"})


def test_only_unexpected_tool_scores_0() -> None:
    result = score_tool_selection(_trace("search"), {"read_files"})

    assert result.score == 0.0
    assert result.matched == frozenset()
    assert result.missing == frozenset({"read_files"})
    assert result.unexpected == frozenset({"search"})


def test_empty_expected_is_vacuously_1() -> None:
    result = score_tool_selection(_trace("read_files"), set())

    assert result.score == 1.0
    assert result.used == frozenset({"read_files"})
    assert result.matched == frozenset()
    assert result.missing == frozenset()


def test_no_tool_calls_against_nonempty_expected_scores_0() -> None:
    result = score_tool_selection(_trace(), {"read_files"})

    assert result.score == 0.0
    assert result.used == frozenset()
    assert result.missing == frozenset({"read_files"})


def test_matched_is_the_numerator() -> None:
    # Independent literals: 1 of 2 expected tools used -> exactly 1 matched, 0.5.
    result = score_tool_selection(_trace("read_files"), {"read_files", "write_file"})

    assert len(result.matched) == 1
    assert len(result.expected) == 2
    assert result.score == 0.5


def test_duplicate_tool_calls_count_once() -> None:
    single = score_tool_selection(_trace("read_files"), {"read_files"})
    doubled = score_tool_selection(_trace("read_files", "read_files"), {"read_files"})

    assert doubled.score == single.score == 1.0
    assert doubled.used == frozenset({"read_files"})


def test_extra_tools_never_penalize_but_are_surfaced() -> None:
    result = score_tool_selection(_trace("read_files", "search"), {"read_files"})

    assert result.score == 1.0
    assert result.unexpected == frozenset({"search"})


def test_errored_tool_call_still_counts_as_used() -> None:
    # Locked decision: selection is judged by invocation, not success.
    errored = Trace(
        version=1,
        turns=(),
        tool_calls=(
            ToolCall(
                id="tool-call-0",
                name="read_files",
                input={},
                result_content="permission denied",
                is_error=True,
            ),
        ),
        dropped_items=(),
    )

    result = score_tool_selection(errored, {"read_files"})

    assert result.score == 1.0
    assert result.used == frozenset({"read_files"})
    assert result.matched == frozenset({"read_files"})


def test_str_expected_raises_type_error() -> None:
    with pytest.raises(TypeError):
        score_tool_selection(_trace("read_files"), "read_files")  # type: ignore[arg-type]
