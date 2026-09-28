"""Report emitter: the EMIT stage of the walking skeleton (load -> score -> EMIT).

A single pure function, :func:`render_report`, turns a loaded World-A
:class:`~clinescope.world_a.Trace` and a
:class:`~clinescope.tool_selection.ToolSelectionScore` (and, optionally, a
:class:`~clinescope.diff_coherence.DiffCoherenceScore`, a
:class:`~clinescope.diff_minimality.DiffMinimalityScore`, and/or an
:class:`~clinescope.apply_recovery.ApplyRecoveryScore`) into one report string.

Two renderings, both pure (no I/O, no LLM):

* **Default (``verbose=False``) -- a scannable SUMMARY:** a one-line header plus
  ONE line per scorer, each ``name  NN/100  VERDICT  [extra]``. Scores are shown
  as ``round(score * 100)`` out of 100 (``100/100``, ``75/100``); an abstaining
  scorer (``score is None``) shows ``n/a``. On an editor run (:func:`is_editor_run`)
  diff_coherence also shows ``n/a``, under a ``note:`` line naming both call counts.
  When diff_coherence graded a patch, a ``cline_verdict`` context line follows it
  with Cline's own verdict on that patch; it is not a scorer line and has no score.
  This is what a developer glancing at a run reads in ~2 seconds.
* **``verbose=True`` -- the full DEBUG DUMP:** aligned ``key: value`` lines with
  every gate, counter, and piece of evidence, each frozenset ``sorted()`` for
  stable output and each score formatted ``.4f`` for exactness. The only addition
  to the historical output is the same ``cline_verdict:`` line in
  ``[diff_coherence]``.

The ``.score`` float stays exact on the dataclass; only the displayed value is
formatted. ``sessionId`` is not modelled on ``Trace`` (the loader discards it), so
it is passed in by the caller rather than read here. ``diff_coherence``,
``diff_minimality``, and ``apply_recovery`` are optional keywords: when ``None``
the matching line/section is omitted, so existing single-scorer callers keep their
exact output in both renderings.
"""

from __future__ import annotations

from clinescope.advice import (
    ScorerAdvice,
    advice_for_apply_recovery,
    advice_for_diff_coherence,
    advice_for_diff_minimality,
    advice_for_editor_recovery,
    advice_for_tool_selection,
)
from clinescope.apply_recovery import ApplyRecoveryScore
from clinescope.cmd_after_edit import CmdAfterEditCheck
from clinescope.diff_coherence import (
    DiffCoherenceScore,
    diff_coherence_select_apply_patch,
)
from clinescope.diff_minimality import DiffMinimalityScore
from clinescope.editor_newlines import EditorNewlinesCheck
from clinescope.editor_recovery import EditorRecoveryScore
from clinescope.render_safety import quote_untrusted_text
from clinescope.tool_input import ExpectedInput, ToolInputScore
from clinescope.tool_selection import ToolSelectionScore
from clinescope.tool_verdict import tool_verdict_effective, tool_verdict_error_line
from clinescope.world_a import Trace

# The summary name column is left-justified to the longest scorer name
# ("diff_minimality" = 15) so the NN/100 cells line up; the cell itself is
# right-justified to 7 ("100/100"), so "n/a" / "0/100" align under the hundreds.
_SUMMARY_NAME_WIDTH = 15
_SUMMARY_CELL_WIDTH = 7


def render_report(
    trace: Trace,
    score: ToolSelectionScore,
    *,
    session_id: str | None = None,
    session_label: str | None = None,
    diff_coherence: DiffCoherenceScore | None = None,
    diff_minimality: DiffMinimalityScore | None = None,
    apply_recovery: ApplyRecoveryScore | None = None,
    editor_recovery: EditorRecoveryScore | None = None,
    tool_input: ToolInputScore | None = None,
    test_cmd: CmdAfterEditCheck | None = None,
    editor_newlines: EditorNewlinesCheck | None = None,
    expected_provided: bool = True,
    advice: bool = False,
    verbose: bool = False,
) -> str:
    # session_label, when given, replaces the "session <id>" phrase in the header
    # verbatim (e.g. an "extension session <taskId> \"title\" [Code]" line for a
    # VS Code extension trace, which has no World-A sessionId). When None the
    # header is unchanged, so every existing caller is byte-identical.
    #
    # editor_recovery is the editor-family sibling of apply_recovery. Callers pass
    # it only when the trace actually contains an editor call, so an apply_patch
    # trace renders byte-identically to before this scorer existed. tool_input is
    # passed only when --expected-input was given, and test_cmd only when --test-cmd
    # was, for the same reason. editor_newlines is passed on the same rule as
    # editor_recovery, and even then it renders only when it has a hit.
    if verbose:
        return _render_verbose(
            trace,
            score,
            session_id=session_id,
            session_label=session_label,
            diff_coherence=diff_coherence,
            diff_minimality=diff_minimality,
            apply_recovery=apply_recovery,
            editor_recovery=editor_recovery,
            tool_input=tool_input,
            test_cmd=test_cmd,
            editor_newlines=editor_newlines,
        )
    summary = _render_summary(
        trace,
        score,
        session_id=session_id,
        session_label=session_label,
        diff_coherence=diff_coherence,
        diff_minimality=diff_minimality,
        apply_recovery=apply_recovery,
        editor_recovery=editor_recovery,
        tool_input=tool_input,
        test_cmd=test_cmd,
        editor_newlines=editor_newlines,
        expected_provided=expected_provided,
    )
    if not advice:
        return summary
    advice_block = _render_advice_block(
        score, diff_coherence, diff_minimality, apply_recovery, editor_recovery
    )
    return summary if advice_block is None else f"{summary}\n{advice_block}"


# --- Advice / coach layer (opt-in via --advice; reads existing evidence) -------


def _render_advice_block(
    score: ToolSelectionScore,
    diff_coherence: DiffCoherenceScore | None,
    diff_minimality: DiffMinimalityScore | None,
    apply_recovery: ApplyRecoveryScore | None,
    editor_recovery: EditorRecoveryScore | None = None,
) -> str | None:
    # One advice entry per FAILING scorer, in report order; a passing/abstaining
    # scorer contributes nothing. Returns None when there is nothing to coach, so
    # a clean run under --advice adds no block.
    entries: list[tuple[str, ScorerAdvice]] = []
    ts = advice_for_tool_selection(score)
    if ts is not None:
        entries.append(("tool_selection", ts))
    if diff_coherence is not None:
        dc = advice_for_diff_coherence(
            diff_coherence,
            editor_run=is_editor_run(diff_coherence, editor_recovery),
        )
        if dc is not None:
            entries.append(("diff_coherence", dc))
    if diff_minimality is not None:
        dm = advice_for_diff_minimality(diff_minimality)
        if dm is not None:
            entries.append(("diff_minimality", dm))
    if apply_recovery is not None:
        ar = advice_for_apply_recovery(apply_recovery)
        if ar is not None:
            entries.append(("apply_recovery", ar))
    if editor_recovery is not None:
        er = advice_for_editor_recovery(editor_recovery)
        if er is not None:
            entries.append(("editor_recovery", er))
    if not entries:
        return None

    lines = ["", "advice (how to improve the agent):"]
    for name, entry in entries:
        lines.append(f"  [{name}] {entry.label.value}")
        lines.extend(f"    - {line}" for line in entry.lines)
    return "\n".join(lines)


# --- Default summary rendering (one line per scorer) --------------------------


def _render_summary(
    trace: Trace,
    score: ToolSelectionScore,
    *,
    session_id: str | None,
    session_label: str | None = None,
    diff_coherence: DiffCoherenceScore | None,
    diff_minimality: DiffMinimalityScore | None,
    apply_recovery: ApplyRecoveryScore | None,
    editor_recovery: EditorRecoveryScore | None = None,
    tool_input: ToolInputScore | None = None,
    test_cmd: CmdAfterEditCheck | None = None,
    editor_newlines: EditorNewlinesCheck | None = None,
    expected_provided: bool,
) -> str:
    subject = _header_subject(session_id, session_label)
    lines = [f"clinescope report - {subject} ({len(trace.tool_calls)} tool calls)"]
    note = _editor_run_note(diff_coherence, editor_recovery)
    if note is not None:
        lines.append(note)
    lines.append(_render_summary_tool_selection(score, expected_provided))
    if tool_input is not None:
        lines.append(_render_summary_tool_input(tool_input))
    if diff_coherence is not None:
        lines.append(_render_summary_diff_coherence(diff_coherence, editor_recovery))
    cline_verdict = _cline_verdict_text(trace, diff_coherence)
    if cline_verdict is not None:
        lines.append(f"{'cline_verdict':<{_SUMMARY_NAME_WIDTH}} {cline_verdict}")
    if diff_minimality is not None:
        lines.append(
            _render_summary_line(
                "diff_minimality",
                render_score_out_of_100(diff_minimality.score),
                summary_verdict(diff_minimality.score),
                _summary_reason_diff_minimality(diff_minimality),
            )
        )
    if apply_recovery is not None:
        lines.append(_render_summary_apply_recovery(apply_recovery))
    if editor_recovery is not None:
        lines.append(_render_summary_editor_recovery(editor_recovery))
    if editor_newlines is not None and editor_newlines.hits:
        lines.append(
            f"{'editor_newlines':<{_SUMMARY_NAME_WIDTH}} "
            f"{_editor_newlines_text(editor_newlines)}"
        )
    if test_cmd is not None:
        lines.append(f"{'test_cmd':<{_SUMMARY_NAME_WIDTH}} {_test_cmd_text(test_cmd)}")
    footer = _summary_footer(
        score,
        expected_provided,
        diff_coherence,
        diff_minimality,
        apply_recovery,
        editor_recovery,
        tool_input,
        test_cmd,
        editor_newlines,
    )
    if footer is not None:
        lines.append(footer)
    return "\n".join(lines)


def tool_selection_cell_verdict(
    score: ToolSelectionScore, expected_provided: bool
) -> tuple[str, str]:
    """The canonical (cell, verdict) pair for tool_selection -- the ONE source.

    tool_selection does NOT go through :func:`summary_verdict`: it is a recall
    metric with no threshold, so it is deliberately asymmetric --

    * no ``--expected`` (``expected_provided`` False) -> cell ``"n/a"``, verdict ``""``.
    * expected given, perfect recall (``score == 1.0``) -> ``"PASS"``.
    * expected given, sub-perfect recall -> verdict ``""`` (a BLANK word, never
      ``"FAIL"`` -- the gate is what turns a score into a fail).

    Both the single-trace summary line and the ``compare`` table call this, so a
    compare row's tool_selection cell/verdict is byte-identical to the single-trace
    one by construction.
    """
    if not expected_provided:
        return "n/a", ""
    verdict = "PASS" if score.score == 1.0 else ""
    return render_score_out_of_100(score.score), verdict


def is_editor_run(
    diff_coherence: DiffCoherenceScore, editor_recovery: EditorRecoveryScore | None
) -> bool:
    """True when the trace made no ``apply_patch`` call and at least one ``editor`` call.

    The ONE rule the report, :mod:`clinescope.compare` and :mod:`clinescope.corpus`
    share, so they cannot disagree. On such a run diff_coherence has no patch to check.
    Its scorer still returns the hard 0.0 and :mod:`clinescope.gate` still decides on
    ``apply_patch_call_count``, but these three read that zero as ``n/a`` and give no
    malformed-patch advice. A trace with neither tool is not an editor run, so it keeps
    ``0/100 FAIL``: nothing was edited there at all.

    ``editor_recovery`` is ``None`` when the caller did not score it, which the CLI
    does only for a trace with no ``editor`` call.
    """
    return (
        diff_coherence.apply_patch_call_count == 0
        and editor_recovery is not None
        and editor_recovery.editor_call_count > 0
    )


def diff_coherence_cell_verdict(
    diff_coherence: DiffCoherenceScore, editor_recovery: EditorRecoveryScore | None
) -> tuple[str, str]:
    """The canonical (cell, verdict) pair for diff_coherence -- the ONE source.

    ``("n/a", "n/a")`` on an editor run (:func:`is_editor_run`), otherwise the score
    through :func:`render_score_out_of_100` and :func:`summary_verdict`. The summary
    line, the ``compare`` table and the corpus all call this.
    """
    if is_editor_run(diff_coherence, editor_recovery):
        return "n/a", "n/a"
    return (
        render_score_out_of_100(diff_coherence.score),
        summary_verdict(diff_coherence.score),
    )


def _editor_run_note(
    diff_coherence: DiffCoherenceScore | None,
    editor_recovery: EditorRecoveryScore | None,
) -> str | None:
    # Printed under the header on an editor run only, so the n/a on the three
    # apply_patch lines cannot be read as a pass. Both numbers are counts the
    # scorers computed, so no trace text reaches this line.
    if diff_coherence is None or editor_recovery is None:
        return None
    if not is_editor_run(diff_coherence, editor_recovery):
        return None
    count = editor_recovery.editor_call_count
    noun = "call" if count == 1 else "calls"
    return (
        f"note: 0 apply_patch calls, {count} editor {noun} "
        "- the 3 apply_patch checks did not run"
    )


def _cline_verdict_text(
    trace: Trace, diff_coherence: DiffCoherenceScore | None
) -> str | None:
    # Cline's own verdict on the patch diff_coherence graded (its FIRST apply_patch),
    # shown beside the grammar score because the two can disagree: a patch Cline
    # rejected can still score 100/100. Context only: it never feeds a score, the
    # clean-run footer or the gate. No apply_patch means no graded patch, so no line.
    if diff_coherence is None:
        return None
    call, _ = diff_coherence_select_apply_patch(trace)
    if call is None:
        return None
    verdict = tool_verdict_effective(call)
    if verdict is None:
        return "no verdict"
    if not verdict:
        return "applied"
    reason = tool_verdict_error_line(call)
    if reason is None:
        return "rejected"
    return f"rejected   ({quote_untrusted_text(reason)})"


def _render_summary_diff_coherence(
    score: DiffCoherenceScore, editor_recovery: EditorRecoveryScore | None
) -> str:
    cell, verdict = diff_coherence_cell_verdict(score, editor_recovery)
    if is_editor_run(score, editor_recovery):
        extra = "(editor run - no apply_patch to check)"
    else:
        extra = _summary_reason_diff_coherence(score)
    return _render_summary_line("diff_coherence", cell, verdict, extra)


def _render_summary_tool_input(score: ToolInputScore) -> str:
    # Same shape as tool_selection: a recall with no threshold, so PASS at 100 and
    # no word below it. The expected inputs are the operator's own text, so they
    # are not neutralized; no trace text reaches this line.
    verdict = "PASS" if score.score == 1.0 else ""
    extra = (
        f"(missing: {_render_expected_inputs(score.missing)})" if score.missing else ""
    )
    return _render_summary_line(
        "tool_input", render_score_out_of_100(score.score), verdict, extra
    )


def _render_summary_tool_selection(
    score: ToolSelectionScore, expected_provided: bool
) -> str:
    # Opt-in: with no --expected there is nothing to recall against, so the old
    # vacuous 100/100 PASS was a false positive. Show n/a + how to enable it
    # instead (mirrors the abstaining scorers), never a fake pass.
    cell, verdict = tool_selection_cell_verdict(score, expected_provided)
    if not expected_provided:
        return _render_summary_line(
            "tool_selection",
            cell,
            verdict,
            "(pass --expected <tools> to score tool selection)",
        )
    # tool_selection is a recall metric with no threshold, so a sub-100 score
    # gets NO PASS/FAIL word -- just the number and the actionable missing tools.
    # The gate (clinescope.gate) is the thing that turns a score into a verdict.
    extra = f"(missing: {_render_names(score.missing)})" if score.missing else ""
    return _render_summary_line(
        "tool_selection",
        cell,
        verdict,
        extra,
    )


def _render_summary_apply_recovery(score: ApplyRecoveryScore) -> str:
    # Only when the metric applies (something failed) do we report the N/M count;
    # a clean run with nothing to recover abstains (n/a) -- but say WHY it abstained
    # (nothing failed vs no verdicts in the trace) so bare "n/a" is never cryptic.
    if score.applicable:
        extra = (
            f"({score.confirmed_recovered_pairs}/{score.total_failed_pairs} "
            "failed patches recovered)"
        )
    else:
        extra = _summary_reason_apply_recovery(score)
    return _render_summary_line(
        "apply_recovery",
        render_score_out_of_100(score.score),
        summary_verdict(score.score),
        extra,
    )


def _render_summary_editor_recovery(score: EditorRecoveryScore) -> str:
    # Same shape as the apply_patch sibling above: the N/M count when something
    # failed, otherwise a named reason so a bare n/a is never cryptic. The name is
    # 15 characters, the same as "diff_minimality", so the existing column width
    # holds and no other report line moves.
    if score.applicable:
        extra = (
            f"({score.confirmed_recovered_pairs}/{score.total_failed_pairs} "
            "failed edits recovered)"
        )
    else:
        extra = _summary_reason_editor_recovery(score)
    return _render_summary_line(
        "editor_recovery",
        render_score_out_of_100(score.score),
        summary_verdict(score.score),
        extra,
    )


def _summary_reason_editor_recovery(score: EditorRecoveryScore) -> str:
    # The two honest n/a sub-cases, mirroring the apply_patch sibling: a genuine
    # clean run vs a trace that carried no pass/fail verdict at all.
    if score.editor_call_count == 0:
        return "(no editor call - nothing to recover)"
    if score.verdict_coverage == 0:
        return "(no pass/fail verdicts in trace - nothing to score)"
    return "(no failed edits - nothing to recover)"


def _summary_reason_diff_coherence(score: DiffCoherenceScore) -> str:
    # Off an editor run the hard 0.0 is shown as 0/100, so a reason is only useful
    # to name WHY a hard-zero happened -- the first violation.
    if score.score == 0.0 and score.violations:
        return f"({score.violations[0]})"
    return ""


def _summary_reason_diff_minimality(score: DiffMinimalityScore) -> str:
    # n/a here means "no apply_patch to shape-check"; spell that out so the bare
    # n/a is self-explaining (U2). A hard-zero names its first violation.
    if not score.applicable:
        return "(no apply_patch - nothing to check)"
    if score.score == 0.0 and score.violations:
        return f"({score.violations[0]})"
    return ""


def _summary_reason_apply_recovery(score: ApplyRecoveryScore) -> str:
    # The two honest n/a sub-cases (see apply_recovery's verdict_coverage): a
    # genuine clean run vs a trace that carried no pass/fail verdict at all.
    if score.apply_patch_call_count == 0:
        return "(no apply_patch - nothing to recover)"
    if score.verdict_coverage == 0:
        return "(no pass/fail verdicts in trace - nothing to score)"
    return "(no failed patches - nothing to recover)"


def _summary_footer(
    score: ToolSelectionScore,
    expected_provided: bool,
    diff_coherence: DiffCoherenceScore | None,
    diff_minimality: DiffMinimalityScore | None,
    apply_recovery: ApplyRecoveryScore | None,
    editor_recovery: EditorRecoveryScore | None = None,
    tool_input: ToolInputScore | None = None,
    test_cmd: CmdAfterEditCheck | None = None,
    editor_newlines: EditorNewlinesCheck | None = None,
) -> str | None:
    # A positive takeaway on a clean run (U1): if nothing scored below its bar,
    # say so plainly rather than leaving the reader to eyeball four lines. A
    # scorer that abstained (n/a) is neutral -- it neither passes nor fails, so it
    # does not block the clean verdict. tool_selection counts only when scored, and
    # diff_coherence is neutral on an editor run, where the report shows it as n/a.
    # tool_input, like tool_selection, blocks it with any missing input.
    tool_ok = ((not expected_provided) or not score.missing) and (
        tool_input is None or not tool_input.missing
    )
    # test_cmd is not a scorer, but a command that did not run after the last edit,
    # or ran and Cline marked it failed, is something to fix (decided 2026-09-28).
    # n/a and a missing Cline verdict stay neutral.
    test_cmd_ok = test_cmd is None or not (
        test_cmd.status == "not_run"
        or (test_cmd.status == "ran" and test_cmd.success is False)
    )
    # editor_newlines is not a scorer either, but a hit is an edit Cline accepted that
    # flattened real line breaks, which broke the file in the one real case.
    editor_newlines_ok = editor_newlines is None or not editor_newlines.hits
    coherence_ok = (
        diff_coherence is None
        or diff_coherence.score == 1.0
        or is_editor_run(diff_coherence, editor_recovery)
    )
    minimality_ok = (
        diff_minimality is None
        or not diff_minimality.applicable
        or diff_minimality.score == 1.0
    )
    recovery_ok = (
        apply_recovery is None
        or not apply_recovery.applicable
        or apply_recovery.score == 1.0
    )
    editor_recovery_ok = (
        editor_recovery is None
        or not editor_recovery.applicable
        or editor_recovery.score == 1.0
    )
    if (
        tool_ok
        and coherence_ok
        and minimality_ok
        and recovery_ok
        and editor_recovery_ok
        and test_cmd_ok
        and editor_newlines_ok
    ):
        return "clean run - nothing to fix"
    return None


def _render_summary_line(name: str, cell: str, verdict: str, extra: str = "") -> str:
    line = f"{name:<{_SUMMARY_NAME_WIDTH}} {cell:>{_SUMMARY_CELL_WIDTH}}"
    if verdict:
        line = f"{line}  {verdict}"
    if extra:
        line = f"{line}   {extra}"
    return line


def render_score_out_of_100(score: float | None) -> str:
    # None means the scorer abstained (metric undefined for this trace) -> "n/a";
    # a real 0.0 float (e.g. diff_coherence's hard-zero) still renders "0/100".
    # Round-half-up: int(x*100 + 0.5), the single source of the NN/100 rounding.
    if score is None:
        return "n/a"
    return f"{int(score * 100 + 0.5)}/100"


def summary_verdict(score: float | None) -> str:
    if score is None:
        return "n/a"
    return "PASS" if score == 1.0 else "FAIL"


# --- Verbose rendering (the full debug dump; see the module docstring) --------


def _header_subject(session_id: str | None, session_label: str | None) -> str:
    # An explicit label (e.g. an extension session's taskId + title + variant) wins;
    # otherwise fall back to the World-A "session <id>" phrasing, unchanged.
    # The id is trace content, so it is neutralized before it reaches a terminal. It is
    # the FIRST thing printed, which makes it the strongest position in the report for
    # an escape sequence to overwrite everything below it. "<unknown>" is ours, not the
    # trace's, so it stays literal.
    if session_label is not None:
        return session_label
    if session_id is None:
        return "session <unknown>"
    return f"session {quote_untrusted_text(session_id)}"


def _render_verbose(
    trace: Trace,
    score: ToolSelectionScore,
    *,
    session_id: str | None,
    session_label: str | None = None,
    diff_coherence: DiffCoherenceScore | None,
    diff_minimality: DiffMinimalityScore | None,
    apply_recovery: ApplyRecoveryScore | None,
    editor_recovery: EditorRecoveryScore | None = None,
    tool_input: ToolInputScore | None = None,
    test_cmd: CmdAfterEditCheck | None = None,
    editor_newlines: EditorNewlinesCheck | None = None,
) -> str:
    lines = ["=== clinescope report ==="]
    if session_label is not None:
        lines.append(f"session:        {session_label}")
    elif session_id is None:
        lines.append("sessionId:      <unknown>")
    else:
        lines.append(f"sessionId:      {quote_untrusted_text(session_id)}")
    lines += [
        f"trace.version:  {trace.version}",
        f"turns:          {len(trace.turns)}",
        f"tool_calls:     {len(trace.tool_calls)}",
    ]
    # The dump keeps the scorer's own 0.0000 for diff_coherence; the note is what
    # stops that number reading as a failed patch on an editor run.
    note = _editor_run_note(diff_coherence, editor_recovery)
    if note is not None:
        lines.append(note)
    lines += [
        "",
        "[tool_selection]",
        f"score:          {score.score:.4f}",
        f"expected:       {_render_names(score.expected)}",
        # used/unexpected carry names the TRACE chose, so they are neutralized.
        # expected/matched/missing are subsets of the operator's own --expected, so
        # they are left alone: quoting them would change the most-read summary line
        # for no reduction in risk.
        f"used:           {_render_trace_names(score.used)}",
        f"matched:        {_render_names(score.matched)}",
        f"missing:        {_render_names(score.missing)}",
        f"unexpected:     {_render_trace_names(score.unexpected)}",
    ]
    if tool_input is not None:
        # All three sets are the operator's own --expected-input text.
        lines += [
            "",
            "[tool_input]",
            f"score:          {tool_input.score:.4f}",
            f"expected:       {_render_expected_inputs(tool_input.expected)}",
            f"matched:        {_render_expected_inputs(tool_input.matched)}",
            f"missing:        {_render_expected_inputs(tool_input.missing)}",
        ]
    if diff_coherence is not None:
        lines.extend(
            _render_diff_coherence(
                diff_coherence, _cline_verdict_text(trace, diff_coherence)
            )
        )
    if diff_minimality is not None:
        lines.extend(_render_diff_minimality(diff_minimality))
    if apply_recovery is not None:
        lines.extend(_render_apply_recovery(apply_recovery))
    if editor_recovery is not None:
        lines.extend(_render_editor_recovery(editor_recovery))
    if editor_newlines is not None and editor_newlines.hits:
        lines += [
            "",
            "[editor_newlines]",
            f"result:         {_editor_newlines_text(editor_newlines)}",
            f"calls:          {', '.join(str(index) for index, _ in editor_newlines.hits)}",
        ]
    if test_cmd is not None:
        lines += [
            "",
            "[test_cmd]",
            f"result:         {_test_cmd_text(test_cmd)}",
            f"last_edit_call: {_render_optional_index(test_cmd.last_edit_index)}",
            f"command_call:   {_render_optional_index(test_cmd.command_index)}",
        ]
    return "\n".join(lines)


def _test_cmd_text(check: CmdAfterEditCheck) -> str:
    # What Cline recorded, never a verdict of Clinescope's own: "ran" plus Cline's
    # flag, or why nothing could be read. Cline's error text is trace content, so it is
    # neutralized here, where it is read.
    if check.status == "ran":
        if check.success is True:
            detail = "Cline: success"
        elif check.success is False and check.error is not None:
            detail = f"Cline: {quote_untrusted_text(check.error)}"
        elif check.success is False:
            detail = "Cline: failed"
        else:
            detail = "no Cline verdict"
        return f"ran   (after the last edit; {detail})"
    if check.status == "not_run":
        return "not run   (no matching command after the last edit)"
    if check.status == "no_edit":
        return "n/a   (no edit in trace)"
    if check.status == "every_edit_failed":
        return "n/a   (every edit failed)"
    return "n/a   (this trace uses execute_command, which is not read)"


def _editor_newlines_text(check: EditorNewlinesCheck) -> str:
    # The path is trace content, so it is neutralized here, where it is read.
    count = len(check.hits)
    noun = "call" if count == 1 else "calls"
    where = "; ".join(
        f"call {index}: {'-' if path is None else quote_untrusted_text(path)}"
        for index, path in check.hits
    )
    return (
        f"{count} editor {noun} wrote literal \\n where the old text had line breaks"
        f" ({where})"
    )


def _render_optional_index(index: int | None) -> str:
    return "-" if index is None else str(index)


def _render_diff_coherence(
    score: DiffCoherenceScore, cline_verdict: str | None
) -> list[str]:
    lines = [
        "",
        "[diff_coherence]",
        f"score:          {score.score:.4f}",
        f"passed_gates:   {_render_names(score.passed_gates)}",
        f"failed_gates:   {_render_names(score.failed_gates)}",
        f"violations:     {_render_violations(score.violations)}",
        f"apply_patch_calls: {score.apply_patch_call_count}",
        f"cline_is_error: {score.cline_apply_is_error}",
    ]
    if cline_verdict is not None:
        lines.append(f"cline_verdict:  {cline_verdict}")
    return lines


def _render_diff_minimality(score: DiffMinimalityScore) -> list[str]:
    return [
        "",
        "[diff_minimality]",
        f"score:          {_render_optional_4f(score.score)}",
        f"applicable:     {score.applicable}",
        f"blind_rewrite_hunks: {score.blind_rewrite_hunks}",
        f"hunks_with_body: {score.hunks_with_body}",
        f"context_density: {_render_optional_4f(score.mean_context_density)}",
        f"add_file_lines: {score.add_file_lines}",
        f"violations:     {_render_violations(score.violations)}",
        f"apply_patch_calls: {score.apply_patch_call_count}",
        f"cline_is_error: {score.cline_apply_is_error}",
    ]


def _render_apply_recovery(score: ApplyRecoveryScore) -> list[str]:
    return [
        "",
        "[apply_recovery]",
        f"score:          {_render_optional_4f(score.score)}",
        f"applicable:     {score.applicable}",
        f"total_failed_pairs: {score.total_failed_pairs}",
        f"recovered_pairs: {score.confirmed_recovered_pairs}",
        f"unrecovered_pairs: {score.unrecovered_pairs}",
        f"partially_recovered: {score.partially_recovered_failures}",
        f"same_file_refail: {score.same_file_refail_count}",
        f"unverified_reattempts: {score.unverified_reattempt_pairs}",
        f"verdict_coverage: {_render_optional_4f(score.verdict_coverage)}",
        f"failed_files:   {_render_trace_paths(score.failed_target_paths)}",
        f"recovered_by:   {_render_recovery_pairs(score.recovery_pairs)}",
        f"unparseable_failed_calls: {score.unparseable_failed_calls}",
        f"violations:     {_render_violations(score.violations)}",
        f"apply_patch_calls: {score.apply_patch_call_count}",
        f"cline_is_error: {score.cline_apply_is_error}",
    ]


def _render_editor_recovery(score: EditorRecoveryScore) -> list[str]:
    # The apply_patch sibling's verbose block, minus partially_recovered (one editor
    # call touches exactly one path, so a call can never be half-recovered) and with
    # unparseable_failed_calls replaced by pathless_failed_calls.
    return [
        "",
        "[editor_recovery]",
        f"score:          {_render_optional_4f(score.score)}",
        f"applicable:     {score.applicable}",
        f"total_failed_pairs: {score.total_failed_pairs}",
        f"recovered_pairs: {score.confirmed_recovered_pairs}",
        f"unrecovered_pairs: {score.unrecovered_pairs}",
        f"same_file_refail: {score.same_file_refail_count}",
        f"unverified_reattempts: {score.unverified_reattempt_pairs}",
        f"verdict_coverage: {_render_optional_4f(score.verdict_coverage)}",
        f"failed_files:   {_render_trace_paths(score.failed_target_paths)}",
        f"recovered_by:   {_render_recovery_pairs(score.recovery_pairs)}",
        f"pathless_failed_calls: {score.pathless_failed_calls}",
        f"violations:     {_render_violations(score.violations)}",
        f"editor_calls:   {score.editor_call_count}",
        f"cline_is_error: {score.cline_editor_is_error}",
    ]


def _render_recovery_pairs(pairs: tuple[tuple[int, int, str], ...]) -> str:
    # Each triple: the failed call index, the confirming call index, the file. The
    # index gap is the evidence -- a large gap is a distant (possibly unrelated) fix.
    # The path is raw trace content; the two indices are ints the scorer computed.
    return (
        "; ".join(
            f"{quote_untrusted_text(path)} @ call {fail}->{fixer}"
            for fail, fixer, path in pairs
        )
        if pairs
        else "-"
    )


def _render_optional_4f(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def _render_names(names: frozenset[str]) -> str:
    return ", ".join(sorted(names)) if names else "-"


def _render_expected_inputs(inputs: frozenset[ExpectedInput]) -> str:
    return ", ".join(str(item) for item in sorted(inputs)) if inputs else "-"


def _render_trace_names(names: frozenset[str]) -> str:
    # Tool names are lifted from the trace, so they are attacker-chosen. Neutralize
    # each one at the source rather than the join: a joined line can already contain
    # scorer-built violation text that was escaped with !r, and escaping twice is ugly.
    return _render_names(frozenset(quote_untrusted_text(name) for name in names))


def _render_violations(violations: tuple[str, ...]) -> str:
    # Order-preserving (detection order is information), so NOT sorted.
    # Deliberately does NOT neutralize: every violation string reaching it is built by
    # a scorer, and the two that embed a trace path already use !r
    # (apply_recovery.py, editor_recovery.py). Raw trace values go through
    # _render_trace_paths instead.
    return "; ".join(violations) if violations else "-"


def _render_trace_paths(paths: tuple[str, ...]) -> str:
    # Raw file paths straight off the trace, unlike the scorer-built violation strings.
    return _render_violations(tuple(quote_untrusted_text(path) for path in paths))
