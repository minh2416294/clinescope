"""The cline_verdict report line: Cline's own verdict on the patch diff_coherence graded.

diff_coherence reads the patch TEXT, so a patch Cline rejected can still score 100/100.
Before this line existed the only hint was the apply_recovery count two rows down, which
does not say which patch failed. Every expected line below is pinned as a literal from
the approved wording (Day 76 plan), never computed from the code's own output.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinescope.__main__ import main
from clinescope.diff_coherence import score_diff_coherence
from clinescope.report import render_report
from clinescope.tool_selection import score_tool_selection
from clinescope.tool_verdict import tool_verdict_error_line
from clinescope.world_a import ToolCall, Trace

_EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
# Real captures. The apply-fail trace has exactly one apply_patch and Cline rejected it.
_APPLY_FAIL = _EXAMPLES / "live-gpt-oss-apply-fail.json"
_CLEAN = _EXAMPLES / "live-gpt-oss-trace.json"
_EDITOR_RUN = _EXAMPLES / "live-granite-editor-recovery.json"

_REJECTED_LINE = (
    "cline_verdict   rejected   ('apply_patch failed: Patch could not be applied "
    "because 1 hunk did not match the current file content.')"
)
_PATCH = "*** Begin Patch\n*** Add File: a.py\n+x = 1\n*** End Patch"


def _patch_call(result_content: str, *, is_error: bool | None = None) -> ToolCall:
    return ToolCall(
        id="p1",
        name="apply_patch",
        input={"input": _PATCH},
        result_content=result_content,
        is_error=is_error,
    )


def _summary(trace: Trace) -> list[str]:
    return render_report(
        trace,
        score_tool_selection(trace, set()),
        session_id="s1",
        diff_coherence=score_diff_coherence(trace),
        expected_provided=False,
    ).splitlines()


def _trace(*calls: ToolCall) -> Trace:
    return Trace(version=1, turns=(), tool_calls=calls, dropped_items=())


# --- real captured traces, through the CLI ------------------------------------


def test_rejected_patch_shows_clines_reason(capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        main([str(_APPLY_FAIL), "--expected", "read_files", "apply_patch", "--details"])
        == 0
    )
    lines = capsys.readouterr().out.splitlines()

    assert _REJECTED_LINE in lines


def test_line_sits_directly_under_diff_coherence(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main([str(_APPLY_FAIL), "--details"])
    lines = capsys.readouterr().out.splitlines()

    coherence = next(
        i for i, line in enumerate(lines) if line.startswith("diff_coherence")
    )
    assert lines[coherence + 1] == _REJECTED_LINE


def test_applied_patch_shows_applied(capsys: pytest.CaptureFixture[str]) -> None:
    main([str(_CLEAN), "--expected", "read_files", "apply_patch", "--details"])
    lines = capsys.readouterr().out.splitlines()

    assert "cline_verdict   applied" in lines
    # Context only: an applied first patch leaves the clean-run footer in place.
    assert lines[-1] == "clean run - nothing to fix"


def test_editor_run_gets_no_line(capsys: pytest.CaptureFixture[str]) -> None:
    main([str(_EDITOR_RUN), "--details"])

    assert "cline_verdict" not in capsys.readouterr().out


def test_verbose_shows_the_same_verdict(capsys: pytest.CaptureFixture[str]) -> None:
    main([str(_APPLY_FAIL), "--verbose"])
    lines = capsys.readouterr().out.splitlines()

    assert (
        "cline_verdict:  rejected   ('apply_patch failed: Patch could not be applied "
        "because 1 hunk did not match the current file content.')"
    ) in lines
    # The raw loader field keeps its documented parity contract: None on a real trace.
    assert "cline_is_error: None" in lines


def test_verbose_editor_run_gets_no_line(capsys: pytest.CaptureFixture[str]) -> None:
    main([str(_EDITOR_RUN), "--verbose"])

    assert "cline_verdict" not in capsys.readouterr().out


# --- the three states, on in-memory traces (hand-built, not real captures) -----


def test_no_verdict_is_a_third_state_never_applied() -> None:
    lines = _summary(_trace(_patch_call("")))

    assert "cline_verdict   no verdict" in lines


def test_rejected_without_error_text_shows_no_reason() -> None:
    lines = _summary(_trace(_patch_call(json.dumps({"success": False}))))

    assert "cline_verdict   rejected" in lines


def test_raw_bool_verdict_is_read() -> None:
    lines = _summary(_trace(_patch_call("", is_error=False)))

    assert "cline_verdict   applied" in lines


def test_only_the_first_patch_is_reported() -> None:
    first = _patch_call(json.dumps({"success": True}))
    second = ToolCall(
        id="p2",
        name="apply_patch",
        input={"input": _PATCH},
        result_content=json.dumps({"success": False, "error": "later failure"}),
        is_error=None,
    )
    lines = _summary(_trace(first, second))

    assert "cline_verdict   applied" in lines
    assert not any("later failure" in line for line in lines)


def test_error_text_from_the_trace_is_escaped() -> None:
    content = json.dumps({"success": False, "error": "bad\x1b[2Kpatch\nsecond line"})
    lines = _summary(_trace(_patch_call(content)))

    assert "cline_verdict   rejected   ('bad\\x1b[2Kpatch')" in lines


def test_no_line_when_diff_coherence_is_not_passed() -> None:
    trace = _trace(_patch_call(json.dumps({"success": False, "error": "x"})))
    out = render_report(
        trace,
        score_tool_selection(trace, set()),
        session_id="s1",
        expected_provided=False,
    )

    assert "cline_verdict" not in out


# --- the reader, fail-closed ----------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        "",
        "not json",
        "[1, 2]",
        json.dumps({"success": False}),
        json.dumps({"success": False, "error": None}),
        json.dumps({"success": False, "error": 7}),
        json.dumps({"success": False, "error": "   "}),
    ],
)
def test_error_line_reader_fails_closed(content: str) -> None:
    assert tool_verdict_error_line(_patch_call(content)) is None


def test_error_line_reader_ignores_list_content() -> None:
    call = ToolCall(
        id="r1",
        name="run_commands",
        input={},
        result_content=[{"query": "x", "error": "boom"}],
        is_error=None,
    )

    assert tool_verdict_error_line(call) is None


def test_error_line_reader_returns_the_first_non_blank_line() -> None:
    content = json.dumps({"success": False, "error": "\n  first\nsecond"})

    assert tool_verdict_error_line(_patch_call(content)) == "first"
