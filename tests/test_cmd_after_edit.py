"""--test-cmd: did a command containing the caller's text run after the last edit?

It reads Cline's own record only: the run_commands entries after the last edit Cline did
not mark failed, and the success flag Cline stored for the matching one. It never runs
anything and never says the fix works. Every expected line below is a literal from the
approved Day 76 wording, never computed from the code's own output.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinescope.__main__ import main
from clinescope.cmd_after_edit import CmdAfterEditCheck, cmd_after_edit_check
from clinescope.report import render_report
from clinescope.tool_selection import score_tool_selection
from clinescope.world_a import ToolCall, Trace, load_trace

_EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
# Real captures from the Cline CLI, copied byte-for-byte on 2026-09-28.
# ran: two editor calls (4, 5), then call 7 runs `python inventory.py`, success.
_RAN = _EXAMPLES / "live-test-cmd-ran.json"
# helper-edit: editor calls 4-7 change inventory.py, call 8 runs `python inventory.py`,
# then editor call 9 CREATES a helper script, _check_docstrings.py, and call 10 runs
# `python _check_docstrings.py; "exit code: $LASTEXITCODE"` (success) and a pydoc pipe
# Cline recorded as exit code 1.
_HELPER_EDIT = _EXAMPLES / "live-test-cmd-helper-edit.json"
_ADD_FILE = _EXAMPLES / "live-gpt-oss-add-file.json"  # `dir` ran before its only edit
_APPLY_FAIL = _EXAMPLES / "live-gpt-oss-apply-fail.json"  # its only edit failed
_GRANITE = (
    _EXAMPLES / "live-granite-editor-recovery.json"
)  # edits, never runs a command
_NO_TOOLS = _EXAMPLES / "corpus" / "qwen-missing-tools.json"  # no tool call at all


def _cli_lines(capsys: pytest.CaptureFixture[str], *argv: str) -> list[str]:
    assert main(list(argv) + ["--details"]) == 0
    return capsys.readouterr().out.splitlines()


def _test_cmd_line(lines: list[str]) -> str:
    return next(line for line in lines if line.startswith("test_cmd"))


# --- the approved lines, on real captures ----------------------------------------


def test_ran_after_the_last_edit_and_cline_recorded_success(
    capsys: pytest.CaptureFixture[str],
) -> None:
    lines = _cli_lines(capsys, str(_RAN), "--test-cmd", "python inventory.py")

    assert _test_cmd_line(lines) == (
        "test_cmd        ran   (after the last edit; Cline: success)"
    )
    assert lines[-1] == "clean run - nothing to fix"


def test_a_run_before_the_last_edit_is_not_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The documented limit: the last edit is the last edit to ANY file. Here it is the
    # helper script, so the run of inventory.py after its own last change still reads
    # "not run". A command is not tied to the files it tests.
    lines = _cli_lines(capsys, str(_HELPER_EDIT), "--test-cmd", "python inventory.py")

    assert _test_cmd_line(lines) == (
        "test_cmd        not run   (no matching command after the last edit)"
    )
    assert "clean run - nothing to fix" not in lines


def test_a_non_zero_exit_shows_clines_reason(
    capsys: pytest.CaptureFixture[str],
) -> None:
    lines = _cli_lines(capsys, str(_HELPER_EDIT), "--test-cmd", "pydoc")

    assert _test_cmd_line(lines) == (
        "test_cmd        ran   (after the last edit; Cline: 'Command exited with code 1')"
    )
    assert "clean run - nothing to fix" not in lines


def test_a_chained_command_reports_its_last_statement(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Cline records one flag for the whole chained line, not one per statement. Here
    # the script itself printed "exit code: 0"; the check reports only Cline's flag.
    lines = _cli_lines(
        capsys, str(_HELPER_EDIT), "--test-cmd", "python _check_docstrings.py"
    )

    assert _test_cmd_line(lines) == (
        "test_cmd        ran   (after the last edit; Cline: success)"
    )


def test_a_command_that_ran_only_before_the_edit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    lines = _cli_lines(capsys, str(_ADD_FILE), "--test-cmd", "dir")

    assert _test_cmd_line(lines) == (
        "test_cmd        not run   (no matching command after the last edit)"
    )


def test_every_edit_failed_is_na(capsys: pytest.CaptureFixture[str]) -> None:
    lines = _cli_lines(capsys, str(_APPLY_FAIL), "--test-cmd", "pytest")

    assert _test_cmd_line(lines) == "test_cmd        n/a   (every edit failed)"


def test_edits_but_no_command_is_not_run(capsys: pytest.CaptureFixture[str]) -> None:
    lines = _cli_lines(capsys, str(_GRANITE), "--test-cmd", "pytest")

    assert _test_cmd_line(lines) == (
        "test_cmd        not run   (no matching command after the last edit)"
    )


def test_no_edit_is_na(capsys: pytest.CaptureFixture[str]) -> None:
    lines = _cli_lines(capsys, str(_NO_TOOLS), "--test-cmd", "pytest")

    assert _test_cmd_line(lines) == "test_cmd        n/a   (no edit in trace)"


def test_without_the_flag_there_is_no_line(capsys: pytest.CaptureFixture[str]) -> None:
    lines = _cli_lines(capsys, str(_RAN))

    assert not any(line.startswith("test_cmd") for line in lines)


@pytest.mark.parametrize("text", ["", "   "])
def test_empty_text_is_a_usage_error(
    capsys: pytest.CaptureFixture[str], text: str
) -> None:
    exit_code = main([str(_RAN), "--test-cmd", text])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == ""
    assert captured.err == "error: --test-cmd needs a non-empty command text\n"


def test_verbose_block(capsys: pytest.CaptureFixture[str]) -> None:
    main([str(_HELPER_EDIT), "--verbose", "--test-cmd", "pydoc"])
    out = capsys.readouterr().out

    assert (
        "[test_cmd]\n"
        "result:         ran   (after the last edit; Cline: 'Command exited with code 1')\n"
        "last_edit_call: 9\n"
        "command_call:   10\n"
    ) in out


def test_a_write_to_file_edit_counts_as_the_last_edit() -> None:
    # Real extension capture: one write_to_file, no command afterwards.
    from clinescope.cline_extension import load_extension_trace

    trace = load_extension_trace(
        _EXAMPLES / "extension" / "api_conversation_history.write-file.json"
    )
    check = cmd_after_edit_check(trace, "pytest")

    assert check.status == "not_run"
    assert check.last_edit_index is not None


# --- hand-built traces (not captures) for shapes no real trace carries ------------


def _call(
    index: int,
    name: str,
    *,
    input: dict[str, object] | None = None,
    result: str | list[object] | None = None,
) -> ToolCall:
    return ToolCall(
        id=f"c{index}",
        name=name,
        input=dict(input or {}),
        result_content=result,
        is_error=None,
    )


def _trace(*calls: ToolCall) -> Trace:
    return Trace(version=1, turns=(), tool_calls=calls, dropped_items=())


_EDIT_OK = json.dumps({"success": True})


def test_execute_command_trace_is_na() -> None:
    trace = _trace(
        _call(0, "write_to_file", result="ok"),
        _call(1, "execute_command", result="pytest output"),
    )

    assert cmd_after_edit_check(trace, "pytest").status == "execute_command"


def test_no_cline_verdict_when_the_entry_has_no_success_flag() -> None:
    trace = _trace(
        _call(0, "editor", result=_EDIT_OK),
        _call(1, "run_commands", result=[{"query": "pytest -q", "result": "..."}]),
    )
    check = cmd_after_edit_check(trace, "pytest")

    assert check.status == "ran"
    assert check.success is None


def test_a_command_with_no_recorded_result_is_read_from_its_input() -> None:
    trace = _trace(
        _call(0, "editor", result=_EDIT_OK),
        _call(1, "run_commands", input={"commands": ["pytest -q"]}, result=None),
    )
    check = cmd_after_edit_check(trace, "pytest")

    assert check.status == "ran"
    assert check.success is None


def test_a_later_failed_edit_does_not_move_the_last_edit() -> None:
    trace = _trace(
        _call(0, "editor", result=_EDIT_OK),
        _call(1, "run_commands", result=[{"query": "pytest", "success": True}]),
        _call(2, "editor", result=json.dumps({"success": False, "error": "x"})),
    )
    check = cmd_after_edit_check(trace, "pytest")

    assert check.status == "ran"
    assert check.last_edit_index == 0
    assert check.command_index == 1


def test_an_edit_with_no_verdict_still_counts() -> None:
    trace = _trace(
        _call(0, "run_commands", result=[{"query": "pytest", "success": True}]),
        _call(1, "editor", result=None),
    )

    assert cmd_after_edit_check(trace, "pytest").status == "not_run"


def test_match_is_case_sensitive() -> None:
    trace = _trace(
        _call(0, "editor", result=_EDIT_OK),
        _call(1, "run_commands", result=[{"query": "PYTEST", "success": True}]),
    )

    assert cmd_after_edit_check(trace, "pytest").status == "not_run"


def test_error_text_from_the_trace_is_escaped(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    raw = json.loads(_RAN.read_bytes())
    for message in raw["messages"]:
        for item in message.get("content", []):
            if isinstance(item, dict) and item.get("type") == "tool_result":
                content = item.get("content")
                if (
                    isinstance(content, list)
                    and content
                    and "python inventory.py" in str(content)
                ):
                    for entry in content:
                        if "python inventory.py" in entry.get("query", ""):
                            entry["success"] = False
                            entry["error"] = "bad\x1b[2Kexit"
    hostile = tmp_path / "hostile.json"
    hostile.write_text(json.dumps(raw), encoding="utf-8", newline="")

    lines = _cli_lines(capsys, str(hostile), "--test-cmd", "python inventory.py")

    assert _test_cmd_line(lines) == (
        "test_cmd        ran   (after the last edit; Cline: 'bad\\x1b[2Kexit')"
    )


def test_real_trace_indices_for_the_ran_case() -> None:
    check = cmd_after_edit_check(load_trace(_RAN), "python inventory.py")

    assert (check.last_edit_index, check.command_index, check.success) == (5, 7, True)


@pytest.mark.parametrize(
    ("check", "expected_line"),
    [
        (
            CmdAfterEditCheck(status="ran", success=False),
            "test_cmd        ran   (after the last edit; Cline: failed)",
        ),
        (
            CmdAfterEditCheck(status="ran", success=None),
            "test_cmd        ran   (after the last edit; no Cline verdict)",
        ),
        (
            CmdAfterEditCheck(status="execute_command"),
            "test_cmd        n/a   (this trace uses execute_command, which is not read)",
        ),
    ],
)
def test_the_remaining_approved_lines(
    check: CmdAfterEditCheck, expected_line: str
) -> None:
    trace = _trace(_call(0, "editor", result=_EDIT_OK))
    report = render_report(
        trace, score_tool_selection(trace, set()), session_id="s1", test_cmd=check
    )

    assert expected_line in report.splitlines()
