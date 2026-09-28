"""tool_input: recall of caller-stated editor inputs, and its report and CLI wiring.

tool_selection checks tool names only. tool_input checks that at least one ``editor``
call carried an input the caller named with ``--expected-input editor KEY=VALUE``.
Every expected line below is a literal from the approved Day 76 wording, never computed
from the code's own output.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clinescope.__main__ import main
from clinescope.report import render_report
from clinescope.tool_input import (
    ExpectedInput,
    score_tool_input,
    tool_input_parse,
)
from clinescope.tool_selection import score_tool_selection
from clinescope.world_a import ToolCall, Trace, load_trace

# A real capture: two editor calls, both on
# C:\Users\admin\AppData\Local\Temp\cs-editor-capture\calc.py (the first failed).
_GRANITE = (
    Path(__file__).resolve().parent.parent
    / "examples"
    / "live-granite-editor-recovery.json"
)


def _path(value: str) -> ExpectedInput:
    return ExpectedInput(tool="editor", key="path", value=value)


def _editor(**inputs: object) -> ToolCall:
    return ToolCall(
        id="e1", name="editor", input=dict(inputs), result_content="", is_error=None
    )


def _trace(*calls: ToolCall) -> Trace:
    return Trace(version=1, turns=(), tool_calls=calls, dropped_items=())


# --- path matching on the real capture ------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "cs-editor-capture/calc.py",
        "calc.py",
        "C:/Users/admin/AppData/Local/Temp/cs-editor-capture/calc.py",
        "C:\\Users\\admin\\AppData\\Local\\Temp\\cs-editor-capture\\calc.py",
        "/c/Users/admin/AppData/Local/Temp/cs-editor-capture/calc.py",
        "cs-editor-capture\\calc.py",
    ],
)
def test_path_matches_on_its_ending_after_folding(value: str) -> None:
    score = score_tool_input(load_trace(_GRANITE), {_path(value)})

    assert score.score == 1.0
    assert score.missing == frozenset()


@pytest.mark.parametrize(
    "value",
    [
        "other.py",
        "alc.py",  # not at a folder boundary
        "Calc.py",  # case is kept, as in the recovery scorers
        "Temp/calc.py",  # a folder is skipped
    ],
)
def test_path_that_is_not_there_scores_zero(value: str) -> None:
    score = score_tool_input(load_trace(_GRANITE), {_path(value)})

    assert score.score == 0.0
    assert score.missing == frozenset({_path(value)})


def test_recall_over_several_expectations() -> None:
    expected = {_path("calc.py"), _path("other.py")}
    score = score_tool_input(load_trace(_GRANITE), expected)

    assert score.score == 0.5
    assert score.matched == frozenset({_path("calc.py")})
    assert score.missing == frozenset({_path("other.py")})


# --- non-path keys: exact text (hand-built traces, not captures) ---------------


def test_non_path_key_matches_exact_text_only() -> None:
    trace = _trace(_editor(path="a.py", old_text="x = 1\n", new_text="x = 2\n"))

    assert (
        score_tool_input(trace, {ExpectedInput("editor", "new_text", "x = 2\n")}).score
        == 1.0
    )
    assert (
        score_tool_input(trace, {ExpectedInput("editor", "new_text", "x = 2")}).score
        == 0.0
    )


def test_values_compare_as_text() -> None:
    # A real session sent insert_line as the string "5"; another could send 5.
    as_int = _trace(_editor(path="a.py", insert_line=5, new_text="y"))
    as_str = _trace(_editor(path="a.py", insert_line="5", new_text="y"))
    expected = {ExpectedInput("editor", "insert_line", "5")}

    assert score_tool_input(as_int, expected).score == 1.0
    assert score_tool_input(as_str, expected).score == 1.0


def test_a_key_no_call_has_is_missing() -> None:
    trace = _trace(_editor(path="a.py", new_text="y"))

    assert (
        score_tool_input(trace, {ExpectedInput("editor", "old_text", "y")}).score == 0.0
    )


def test_other_tools_never_match() -> None:
    other = ToolCall(
        id="r1",
        name="read_files",
        input={"path": "a.py"},
        result_content="",
        is_error=None,
    )

    assert score_tool_input(_trace(other), {_path("a.py")}).score == 0.0


def test_a_trace_with_no_editor_call_scores_zero_not_na() -> None:
    score = score_tool_input(_trace(), {_path("a.py")})

    assert score.score == 0.0
    assert score.missing == frozenset({_path("a.py")})


# --- parsing the flag ------------------------------------------------------------


def test_parse_splits_on_the_first_equals_sign() -> None:
    assert tool_input_parse("editor", "new_text=a=b") == ExpectedInput(
        "editor", "new_text", "a=b"
    )


@pytest.mark.parametrize(
    ("tool", "pair"),
    [("read_files", "path=a.py"), ("editor", "pathx"), ("editor", "=a.py")],
)
def test_parse_rejects_what_it_cannot_score(tool: str, pair: str) -> None:
    with pytest.raises(ValueError):
        tool_input_parse(tool, pair)


# --- the report and the CLI ---------------------------------------------------------


def test_cli_prints_a_pass_line_under_tool_selection(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([str(_GRANITE), "--expected-input", "editor", "path=calc.py"]) == 0
    lines = capsys.readouterr().out.splitlines()

    selection = next(
        i for i, line in enumerate(lines) if line.startswith("tool_selection")
    )
    assert lines[selection + 1] == "tool_input      100/100  PASS"


def test_cli_names_the_missing_input(capsys: pytest.CaptureFixture[str]) -> None:
    main(
        [
            str(_GRANITE),
            "--expected-input",
            "editor",
            "path=calc.py",
            "--expected-input",
            "editor",
            "path=other.py",
        ]
    )
    lines = capsys.readouterr().out.splitlines()

    assert "tool_input       50/100   (missing: editor path=other.py)" in lines
    # A miss blocks the clean-run footer, as a tool_selection miss does.
    assert "clean run - nothing to fix" not in lines


def test_cli_without_the_flag_prints_no_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main([str(_GRANITE)])

    assert "tool_input" not in capsys.readouterr().out


def test_cli_a_match_keeps_the_clean_run_footer(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main([str(_GRANITE), "--expected-input", "editor", "path=calc.py"])

    assert capsys.readouterr().out.splitlines()[-1] == "clean run - nothing to fix"


def test_cli_other_tool_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([str(_GRANITE), "--expected-input", "read_files", "path=a.py"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == ""
    assert captured.err == (
        "error: --expected-input supports only the editor tool, got 'read_files'\n"
    )


def test_cli_missing_equals_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([str(_GRANITE), "--expected-input", "editor", "pathx"])

    assert exit_code == 2
    assert capsys.readouterr().err == (
        "error: --expected-input needs KEY=VALUE after the tool, got 'pathx'\n"
    )


def test_cli_unknown_key_warns_and_still_scores(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([str(_GRANITE), "--expected-input", "editor", "pth=calc.py"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == (
        "warning: unknown editor input key 'pth' - editor takes insert_line, "
        "new_text, old_text, path\n"
    )
    assert "tool_input        0/100   (missing: editor pth=calc.py)" in captured.out


def test_verbose_block(capsys: pytest.CaptureFixture[str]) -> None:
    main(
        [
            str(_GRANITE),
            "--verbose",
            "--expected-input",
            "editor",
            "path=calc.py",
            "--expected-input",
            "editor",
            "path=other.py",
        ]
    )
    out = capsys.readouterr().out

    assert (
        "[tool_input]\n"
        "score:          0.5000\n"
        "expected:       editor path=calc.py, editor path=other.py\n"
        "matched:        editor path=calc.py\n"
        "missing:        editor path=other.py\n"
    ) in out


def test_render_report_without_the_score_is_unchanged() -> None:
    trace = load_trace(_GRANITE)
    selection = score_tool_selection(trace, set())
    before = render_report(trace, selection, session_id="s1", expected_provided=False)

    assert (
        render_report(
            trace, selection, session_id="s1", expected_provided=False, tool_input=None
        )
        == before
    )
