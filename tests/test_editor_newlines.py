"""editor_newlines: an editor call that flattened real line breaks into literal \\n.

The shape: Cline did not mark the call failed, its old_text had real line breaks, and its
new_text has none but has the two characters backslash and n. Cline accepts that call and
reports success, so no scorer sees it. It is a context line, not a scorer: it shows only
when it fires, and it keeps the clean-run footer off.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from clinescope.__main__ import main
from clinescope.editor_newlines import EditorNewlinesCheck, editor_newlines_check
from clinescope.world_a import load_trace

_EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
# Real capture from the Cline CLI 3.0.65 (granite4.1:8b), copied byte-for-byte on
# 2026-09-28 from session 1790447882966_iep7l. Tool call 1 is an editor call with no
# old_text, which Cline rejected. Tool call 3 is an editor call Cline confirmed: its
# old_text has 30 real line breaks and its new_text is one line with 78 literal \n.
_ESCAPED = _EXAMPLES / "live-granite-escaped-newlines.json"
_ESCAPED_PATH = "C:\\cs-day65-capture\\inventory.py"
# The four other committed traces that contain editor calls. None has the shape.
_OTHER_EDITOR_TRACES = (
    _EXAMPLES / "live-granite-editor-recovery.json",
    _EXAMPLES / "harness-gap" / "granite-harness.messages.json",
    _EXAMPLES / "live-test-cmd-helper-edit.json",
    _EXAMPLES / "live-test-cmd-ran.json",
)


def _cli_lines(capsys: pytest.CaptureFixture[str], *argv: str) -> list[str]:
    assert main(list(argv) + ["--details"]) == 0
    return capsys.readouterr().out.splitlines()


def _newlines_line(lines: list[str]) -> str:
    return next(line for line in lines if line.startswith("editor_newlines"))


def test_the_flattened_edit_gets_a_line_and_no_clean_run_footer(
    capsys: pytest.CaptureFixture[str],
) -> None:
    lines = _cli_lines(capsys, str(_ESCAPED), "--expected", "editor")

    assert _newlines_line(lines) == (
        r"editor_newlines 1 editor call wrote literal \n where the old text had line"
        r" breaks (call 3: 'C:\\cs-day65-capture\\inventory.py')"
    )
    assert "clean run - nothing to fix" not in lines


def test_the_verbose_block(capsys: pytest.CaptureFixture[str]) -> None:
    lines = _cli_lines(capsys, str(_ESCAPED), "--expected", "editor", "--verbose")

    block = lines[lines.index("[editor_newlines]") :]
    assert block[1:3] == [
        r"result:         1 editor call wrote literal \n where the old text had line"
        r" breaks (call 3: 'C:\\cs-day65-capture\\inventory.py')",
        "calls:          3",
    ]


@pytest.mark.parametrize("trace", _OTHER_EDITOR_TRACES, ids=lambda p: p.name)
def test_no_line_on_the_other_real_editor_traces(
    capsys: pytest.CaptureFixture[str], trace: Path
) -> None:
    summary = _cli_lines(capsys, str(trace), "--expected", "editor")
    verbose = _cli_lines(capsys, str(trace), "--expected", "editor", "--verbose")

    assert not any(line.startswith("editor_newlines") for line in summary)
    assert "[editor_newlines]" not in verbose


def test_the_check_on_the_real_trace() -> None:
    assert editor_newlines_check(load_trace(_ESCAPED)) == EditorNewlinesCheck(
        hits=((3, _ESCAPED_PATH),)
    )


# --- one rule each, on variants of the real capture --------------------------------

# The tool_use id of tool call 3, the confirmed editor call.
_CONFIRMED_ID = "call_u541bmre"


def _variant(tmp_path: Path, edit: str, value: Any) -> Path:
    raw = json.loads(_ESCAPED.read_bytes())
    for message in raw["messages"]:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if item.get("type") == "tool_use" and item.get("id") == _CONFIRMED_ID:
                if edit in ("path", "old_text"):
                    item["input"][edit] = value
            if item.get("type") == "tool_result" and (
                item.get("tool_use_id") == _CONFIRMED_ID and edit == "result"
            ):
                item["content"] = value
    variant = tmp_path / "variant.json"
    variant.write_text(json.dumps(raw), encoding="utf-8", newline="")
    return variant


def test_a_call_cline_marked_failed_is_not_a_hit(tmp_path: Path) -> None:
    failed = json.dumps({"query": "edit", "result": "", "error": "x", "success": False})
    variant = _variant(tmp_path, "result", failed)

    assert editor_newlines_check(load_trace(variant)).hits == ()


def test_a_one_line_old_text_is_not_a_hit(tmp_path: Path) -> None:
    # A one-line replacement whose new text holds a \n inside a string literal is an
    # ordinary edit, so the rule needs real line breaks in old_text.
    variant = _variant(tmp_path, "old_text", 'print("done")')

    assert editor_newlines_check(load_trace(variant)).hits == ()


def test_the_path_from_the_trace_is_escaped(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    variant = _variant(tmp_path, "path", "bad\x1b[2Kname.py")

    lines = _cli_lines(capsys, str(variant), "--expected", "editor")

    assert _newlines_line(lines).endswith(r"(call 3: 'bad\x1b[2Kname.py')")


def test_a_call_with_no_string_path_still_shows(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    variant = _variant(tmp_path, "path", None)

    lines = _cli_lines(capsys, str(variant), "--expected", "editor")

    assert editor_newlines_check(load_trace(variant)).hits == ((3, None),)
    assert _newlines_line(lines).endswith("(call 3: -)")
