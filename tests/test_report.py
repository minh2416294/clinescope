from pathlib import Path

import pytest

from clinescope.__main__ import main
from clinescope.report import render_report
from clinescope.tool_selection import score_tool_selection
from clinescope.world_a import ToolCall, Trace, load_trace

GOLDEN = Path(
    "C:/Users/admin/PycharmProjects/cline/sdk/packages/core/fixtures/messages/success.messages.json"
)


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


def test_report_contains_score_1_and_matched_tool() -> None:
    trace = _trace("read_files")
    score = score_tool_selection(trace, {"read_files"})

    report = render_report(trace, score, session_id="fixture-success-01")

    assert isinstance(report, str)
    assert "1.0" in report
    assert "matched:        read_files" in report
    assert "missing:        -" in report
    assert "unexpected:     -" in report
    assert "sessionId:      fixture-success-01" in report
    assert "trace.version:  1" in report


def test_report_shows_missing_name_when_extra_expected() -> None:
    trace = _trace("read_files")
    score = score_tool_selection(trace, {"read_files", "write_file"})

    report = render_report(trace, score, session_id="fixture-success-01")

    assert "0.5000" in report
    assert "matched:        read_files" in report
    assert "missing:        write_file" in report


def test_report_multiple_expected_names_render_sorted() -> None:
    trace = _trace("read_files")
    score = score_tool_selection(trace, {"write_file", "read_files", "search"})

    report = render_report(trace, score)

    assert "expected:       read_files, search, write_file" in report
    assert "missing:        search, write_file" in report


def test_report_session_id_defaults_to_unknown() -> None:
    trace = _trace("read_files")
    score = score_tool_selection(trace, {"read_files"})

    report = render_report(trace, score)

    assert "sessionId:      <unknown>" in report


@pytest.mark.skipif(
    not GOLDEN.exists(), reason="Cline golden fixture not checked out at expected path"
)
def test_report_on_real_golden_fixture_end_to_end() -> None:
    trace = load_trace(GOLDEN)
    score = score_tool_selection(trace, {"read_files"})

    report = render_report(trace, score, session_id="fixture-success-01")

    assert "score:          1.0000" in report
    assert "matched:        read_files" in report
    assert "sessionId:      fixture-success-01" in report
    assert "trace.version:  1" in report
    assert "turns:          4" in report
    assert "tool_calls:     1" in report


@pytest.mark.skipif(
    not GOLDEN.exists(), reason="Cline golden fixture not checked out at expected path"
)
def test_cli_main_reads_session_id_from_file_and_prints_report(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Proves the on-disk sessionId lift (main -> _read_session_id) is exercised:
    # sessionId is NOT hand-passed here, so it can only appear if read from the file.
    exit_code = main([str(GOLDEN), "--expected", "read_files"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "sessionId:      fixture-success-01" in out
    assert "score:          1.0000" in out
    assert "matched:        read_files" in out
