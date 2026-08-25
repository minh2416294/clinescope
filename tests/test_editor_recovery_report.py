"""Report, advice and CLI wiring for the editor-recovery scorer.

Separate from ``test_editor_recovery.py``, which tests the scorer in isolation.
This file pins the INTEGRATION contract, and its most important assertion is a
negative one: a trace with no ``editor`` call must render EXACTLY as it did before
this scorer existed. That is the whole reason the CLI scores editor recovery
conditionally instead of always.
"""

from __future__ import annotations

from pathlib import Path

from clinescope.__main__ import main
from clinescope.editor_recovery import score_editor_recovery
from clinescope.report import render_report
from clinescope.tool_selection import score_tool_selection
from clinescope.world_a import ToolCall, Trace

_EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
_REAL_EDITOR_TRACE = _EXAMPLES / "live-granite-editor-recovery.json"
_APPLY_PATCH_TRACE = _EXAMPLES / "live-gpt-oss-apply-fail.json"

CALC = "C:\\work\\calc.py"
# The same path as it appears in rendered output: trace-derived text is neutralized
# before display, so it arrives quote-delimited with each backslash escaped. Pinned as
# a literal on purpose; computing it with repr() would just restate how the code does
# it, and the test would pass no matter what the code did.
CALC_RENDERED = "'C:\\\\work\\\\calc.py'"


def _editor_call(call_id: str, *, is_error: bool | None) -> ToolCall:
    return ToolCall(
        id=call_id,
        name="editor",
        input={"path": CALC, "old_text": "a\n", "new_text": "b\n"},
        result_content="result",
        is_error=is_error,
    )


def _render(trace: Trace, *, with_editor: bool, advice: bool = False) -> str:
    return render_report(
        trace,
        score_tool_selection(trace, set()),
        session_id="s1",
        editor_recovery=score_editor_recovery(trace) if with_editor else None,
        expected_provided=False,
        advice=advice,
    )


# --- the negative contract: no editor call means no change --------------------


def test_report_omits_the_line_when_the_scorer_is_not_passed() -> None:
    trace = Trace(version=1, turns=(), tool_calls=(), dropped_items=())

    # Byte-identity, not just absence of the name: assert the whole rendered string
    # equals what the pre-change call shape produces. A weaker "editor_recovery not
    # in out" would still pass if spacing, the footer, or line order had shifted.
    before = render_report(
        trace,
        score_tool_selection(trace, set()),
        session_id="s1",
        expected_provided=False,
    )
    assert _render(trace, with_editor=False) == before
    assert "editor_recovery" not in before


def test_cli_adds_no_editor_line_to_an_apply_patch_trace(capsys) -> None:  # type: ignore[no-untyped-def]
    exit_code = main([str(_APPLY_PATCH_TRACE), "--expected", "apply_patch"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "apply_recovery" in out
    assert "editor_recovery" not in out


# --- the positive contract ----------------------------------------------------


def test_cli_renders_the_editor_line_on_the_real_capture(capsys) -> None:  # type: ignore[no-untyped-def]
    exit_code = main([str(_REAL_EDITOR_TRACE), "--expected", "editor", "read_files"])
    out = capsys.readouterr().out

    assert exit_code == 0
    # The exact rendered line, so a formatting regression or a wrong count fails.
    assert "editor_recovery 100/100  PASS   (1/1 failed edits recovered)" in out
    # And the motivating defect, still visible on the same report.
    assert "diff_coherence    0/100  FAIL" in out


def test_summary_line_reports_an_unrecovered_failure() -> None:
    trace = Trace(
        version=1,
        turns=(),
        tool_calls=(_editor_call("c1", is_error=True),),
        dropped_items=(),
    )
    out = _render(trace, with_editor=True)

    assert "editor_recovery   0/100  FAIL   (0/1 failed edits recovered)" in out
    assert "clean run - nothing to fix" not in out


def test_abstaining_scorer_names_its_reason() -> None:
    trace = Trace(
        version=1,
        turns=(),
        tool_calls=(_editor_call("c1", is_error=False),),
        dropped_items=(),
    )
    out = _render(trace, with_editor=True)

    assert (
        "editor_recovery     n/a  n/a   (no failed edits - nothing to recover)" in out
    )
    # An abstaining scorer is neutral, so the clean-run footer still fires.
    assert "clean run - nothing to fix" in out


def test_verbose_renders_the_editor_recovery_section() -> None:
    trace = Trace(
        version=1,
        turns=(),
        tool_calls=(
            _editor_call("c1", is_error=True),
            _editor_call("c2", is_error=False),
        ),
        dropped_items=(),
    )
    out = render_report(
        trace,
        score_tool_selection(trace, set()),
        session_id="s1",
        editor_recovery=score_editor_recovery(trace),
        verbose=True,
    )

    assert "[editor_recovery]" in out
    assert "score:          1.0000" in out
    assert "total_failed_pairs: 1" in out
    assert "pathless_failed_calls: 0" in out
    assert "editor_calls:   2" in out


def test_advice_fires_for_an_unrecovered_editor_failure() -> None:
    trace = Trace(
        version=1,
        turns=(),
        tool_calls=(_editor_call("c1", is_error=True),),
        dropped_items=(),
    )
    out = _render(trace, with_editor=True, advice=True)

    assert "[editor_recovery] no_editor_recovery" in out
    # Deliberately NOT "did not recover it": LIMITATIONS tells the reader a low
    # score means "not recovered via a same-path confirmed editor call", so the
    # advice line must not make the broader claim.
    assert "no later confirmed editor call re-touched that path" in out
    assert "did not recover it" not in out
    assert CALC_RENDERED in out


def test_advice_stays_quiet_when_recovery_succeeded() -> None:
    trace = Trace(
        version=1,
        turns=(),
        tool_calls=(
            _editor_call("c1", is_error=True),
            _editor_call("c2", is_error=False),
        ),
        dropped_items=(),
    )
    out = _render(trace, with_editor=True, advice=True)

    assert "editor_recovery 100/100  PASS" in out
    assert "no_editor_recovery" not in out
