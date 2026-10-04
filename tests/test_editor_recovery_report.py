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
from clinescope.diff_coherence import score_diff_coherence
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
    exit_code = main(
        [str(_APPLY_PATCH_TRACE), "--expected", "apply_patch", "--details"]
    )
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "apply_recovery" in out
    assert "editor_recovery" not in out


# --- the positive contract ----------------------------------------------------


def test_cli_renders_the_editor_line_on_the_real_capture(capsys) -> None:  # type: ignore[no-untyped-def]
    exit_code = main(
        [str(_REAL_EDITOR_TRACE), "--expected", "editor", "read_files", "--details"]
    )
    out = capsys.readouterr().out

    assert exit_code == 0
    # The exact rendered line, so a formatting regression or a wrong count fails.
    assert "editor_recovery 100/100  PASS   (1/1 failed edits recovered)" in out
    # An editor run: diff_coherence has no apply_patch to check, so it reads n/a,
    # and the note line keeps the missing apply_patch visible.
    assert (
        "diff_coherence      n/a  n/a   (editor run - no apply_patch to check)" in out
    )
    assert _EDITOR_RUN_NOTE in out.splitlines()


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


# --- an editor run: no apply_patch for diff_coherence to check ------------------
# An editor run is 0 apply_patch calls and at least 1 editor call. The scorer still
# returns 0.0 and the gate still decides on apply_patch_call_count; the report, the
# compare cell and the advice read that zero as n/a. A run with neither tool keeps
# its hard zero, because there nothing edited at all.

_NEITHER_TOOL_TRACE = _EXAMPLES / "corpus" / "qwen-missing-tools.json"

# The report approved for this trace on 2026-09-28, pinned as a literal.
_EDITOR_RUN_REPORT = (
    "clinescope report - session '1787455395427_4abgw' (3 tool calls)\n"
    "note: 0 apply_patch calls, 2 editor calls - the 3 apply_patch checks did not run\n"
    "tool_selection      n/a   (pass --expected <tools> to score tool selection)\n"
    "diff_coherence      n/a  n/a   (editor run - no apply_patch to check)\n"
    "diff_minimality     n/a  n/a   (no apply_patch - nothing to check)\n"
    "apply_recovery      n/a  n/a   (no apply_patch - nothing to recover)\n"
    "editor_recovery 100/100  PASS   (1/1 failed edits recovered)\n"
    "clean run - nothing to fix\n"
)
_EDITOR_RUN_NOTE = _EDITOR_RUN_REPORT.splitlines()[1]


def _apply_patch_call(call_id: str) -> ToolCall:
    return ToolCall(
        id=call_id,
        name="apply_patch",
        input={"input": "*** Begin Patch\n*** End Patch\n"},
        result_content="result",
        is_error=False,
    )


def test_cli_editor_run_report_is_the_approved_report(capsys) -> None:  # type: ignore[no-untyped-def]
    exit_code = main([str(_REAL_EDITOR_TRACE), "--details"])

    assert exit_code == 0
    assert capsys.readouterr().out == _EDITOR_RUN_REPORT


def test_cli_editor_run_gives_no_malformed_patch_advice(capsys) -> None:  # type: ignore[no-untyped-def]
    # Nothing failed on this run, so --advice adds no block and the output is the
    # same report, byte for byte.
    exit_code = main([str(_REAL_EDITOR_TRACE), "--advice", "--details"])

    assert exit_code == 0
    assert capsys.readouterr().out == _EDITOR_RUN_REPORT


def test_cli_run_with_neither_tool_keeps_the_hard_zero(capsys) -> None:  # type: ignore[no-untyped-def]
    exit_code = main([str(_NEITHER_TOOL_TRACE), "--advice", "--details"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "diff_coherence    0/100  FAIL   (no apply_patch tool call in trace)" in out
    assert "[diff_coherence] malformed_patch" in out
    assert "note:" not in out


def test_note_line_names_one_editor_call_in_the_singular() -> None:
    trace = Trace(
        version=1,
        turns=(),
        tool_calls=(_editor_call("c1", is_error=False),),
        dropped_items=(),
    )
    out = render_report(
        trace,
        score_tool_selection(trace, set()),
        session_id="s1",
        diff_coherence=score_diff_coherence(trace),
        editor_recovery=score_editor_recovery(trace),
        expected_provided=False,
    )

    assert out.splitlines()[1] == (
        "note: 0 apply_patch calls, 1 editor call - the 3 apply_patch checks did not run"
    )


def test_trace_with_both_tools_is_not_an_editor_run() -> None:
    trace = Trace(
        version=1,
        turns=(),
        tool_calls=(_apply_patch_call("c1"), _editor_call("c2", is_error=False)),
        dropped_items=(),
    )
    out = render_report(
        trace,
        score_tool_selection(trace, set()),
        session_id="s1",
        diff_coherence=score_diff_coherence(trace),
        editor_recovery=score_editor_recovery(trace),
        expected_provided=False,
    )

    assert "note:" not in out
    assert "editor run" not in out


def test_verbose_editor_run_keeps_the_raw_zero_and_adds_the_note(capsys) -> None:  # type: ignore[no-untyped-def]
    # The verbose dump shows the scorer's own numbers, so the 0.0000 stays. The note
    # line is added so the dump does not read as a failed patch.
    exit_code = main([str(_REAL_EDITOR_TRACE), "--verbose"])
    lines = capsys.readouterr().out.splitlines()

    assert exit_code == 0
    assert _EDITOR_RUN_NOTE in lines
    block = lines.index("[diff_coherence]")
    assert lines[block + 1] == "score:          0.0000"
