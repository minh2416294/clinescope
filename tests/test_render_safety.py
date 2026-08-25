"""Tests for :mod:`clinescope.render_safety`.

A trace is untrusted input. The bug-report template at
``.github/ISSUE_TEMPLATE/bug_report.yml`` asks a stranger to paste a ``messages.json``
snippet, so running clinescope on someone else's trace is a documented workflow rather
than a hypothetical. Trace-derived strings (a ``sessionId``, a file path, a tool name,
an extension task title) therefore reach the terminal as attacker-chosen bytes.

The specific damage is not generic terminal mischief. Erase-line and cursor-movement
sequences land AHEAD of the scorer lines, so they can overwrite them and display a
score the tool never computed. For a tool whose entire output is a score, that is an
attack on the one property it exists to provide.

Expected values here are pinned from Python's documented ``repr`` behaviour (it escapes
exactly the non-printable set), NOT copied from what this module happens to emit.
"""

from __future__ import annotations

from clinescope.apply_recovery import ApplyRecoveryScore
from clinescope.render_safety import quote_untrusted_text
from clinescope.report import render_report
from clinescope.tool_selection import score_tool_selection
from clinescope.world_a import ToolCall, Trace

# A real erase-line-and-return sequence: ESC [ 2 K then CR. Printed ahead of a scorer
# line it wipes that line and parks the cursor at column 0 to retype it.
_ERASE_LINE = "\x1b[2K\r"


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


# --- the helper itself --------------------------------------------------------


def test_ordinary_path_is_quoted_and_otherwise_unchanged() -> None:
    assert quote_untrusted_text("src/app.py") == "'src/app.py'"


def test_escape_byte_is_neutralized() -> None:
    assert quote_untrusted_text("a\x1bb") == "'a\\x1bb'"


def test_carriage_return_and_newline_are_neutralized() -> None:
    assert quote_untrusted_text("a\rb") == "'a\\rb'"
    assert quote_untrusted_text("a\nb") == "'a\\nb'"


def test_delete_and_line_separator_are_neutralized() -> None:
    assert quote_untrusted_text("q\x7fz") == "'q\\x7fz'"
    assert quote_untrusted_text("x y") == "'x\\u2028y'"


def test_printable_non_ascii_survives() -> None:
    # Escaping every non-ASCII byte would mangle a legitimate path. repr escapes the
    # non-printable set only, which is exactly the line we want.
    assert quote_untrusted_text("café.py") == "'café.py'"


def test_no_raw_control_byte_survives_any_input() -> None:
    # The property, stated once over the whole C0 range plus DEL, rather than as a
    # handful of examples: a tenth sink added later inherits this guarantee.
    hostile = "".join(chr(code) for code in list(range(0x20)) + [0x7F])
    rendered = quote_untrusted_text(hostile)
    assert not any(ch in rendered for ch in hostile)


# --- the render boundary ------------------------------------------------------


def _recovery_score(path: str) -> ApplyRecoveryScore:
    return ApplyRecoveryScore(
        score=0.0,
        applicable=True,
        total_failed_pairs=1,
        confirmed_recovered_pairs=0,
        unrecovered_pairs=1,
        partially_recovered_failures=0,
        same_file_refail_count=0,
        unverified_reattempt_pairs=0,
        verdict_coverage=1.0,
        failed_target_paths=(path,),
        recovery_pairs=((0, 1, path),),
        unparseable_failed_calls=0,
        apply_patch_call_count=1,
        violations=(),
        cline_apply_is_error=True,
    )


def test_hostile_path_cannot_repaint_the_report() -> None:
    trace = _trace("apply_patch")
    report = render_report(
        trace,
        score_tool_selection(trace, {"apply_patch"}),
        session_id="s-1",
        apply_recovery=_recovery_score(f"{_ERASE_LINE}victory.py"),
        verbose=True,
    )
    assert "\x1b" not in report
    assert "\r" not in report
    assert "\\x1b[2K\\r" in report


def test_hostile_session_id_cannot_repaint_the_report() -> None:
    trace = _trace("apply_patch")
    report = render_report(
        trace,
        score_tool_selection(trace, {"apply_patch"}),
        session_id=f"{_ERASE_LINE}clean-run",
    )
    assert "\x1b" not in report
    assert "\r" not in report


def test_hostile_tool_name_cannot_repaint_the_verbose_dump() -> None:
    # Tool names come from the trace too, and the verbose dump prints the ones the
    # caller never asked for.
    trace = _trace(f"{_ERASE_LINE}apply_patch")
    report = render_report(
        trace,
        score_tool_selection(trace, {"read_files"}),
        session_id="s-1",
        verbose=True,
    )
    assert "\x1b" not in report
    assert "\r" not in report
