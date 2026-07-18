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
  scorer (``score is None``) shows ``n/a``. This is what a developer glancing at a
  run reads in ~2 seconds.
* **``verbose=True`` -- the full DEBUG DUMP:** aligned ``key: value`` lines with
  every gate, counter, and piece of evidence, each frozenset ``sorted()`` for
  stable output and each score formatted ``.4f`` for exactness. Unchanged from the
  historical output byte-for-byte.

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
    advice_for_tool_selection,
)
from clinescope.apply_recovery import ApplyRecoveryScore
from clinescope.diff_coherence import DiffCoherenceScore
from clinescope.diff_minimality import DiffMinimalityScore
from clinescope.tool_selection import ToolSelectionScore
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
    expected_provided: bool = True,
    advice: bool = False,
    verbose: bool = False,
) -> str:
    # session_label, when given, replaces the "session <id>" phrase in the header
    # verbatim (e.g. an "extension session <taskId> \"title\" [Code]" line for a
    # VS Code extension trace, which has no World-A sessionId). When None the
    # header is unchanged, so every existing caller is byte-identical.
    if verbose:
        return _render_verbose(
            trace,
            score,
            session_id=session_id,
            session_label=session_label,
            diff_coherence=diff_coherence,
            diff_minimality=diff_minimality,
            apply_recovery=apply_recovery,
        )
    summary = _render_summary(
        trace,
        score,
        session_id=session_id,
        session_label=session_label,
        diff_coherence=diff_coherence,
        diff_minimality=diff_minimality,
        apply_recovery=apply_recovery,
        expected_provided=expected_provided,
    )
    if not advice:
        return summary
    advice_block = _render_advice_block(
        score, diff_coherence, diff_minimality, apply_recovery
    )
    return summary if advice_block is None else f"{summary}\n{advice_block}"


# --- Advice / coach layer (opt-in via --advice; reads existing evidence) -------


def _render_advice_block(
    score: ToolSelectionScore,
    diff_coherence: DiffCoherenceScore | None,
    diff_minimality: DiffMinimalityScore | None,
    apply_recovery: ApplyRecoveryScore | None,
) -> str | None:
    # One advice entry per FAILING scorer, in report order; a passing/abstaining
    # scorer contributes nothing. Returns None when there is nothing to coach, so
    # a clean run under --advice adds no block.
    entries: list[tuple[str, ScorerAdvice]] = []
    ts = advice_for_tool_selection(score)
    if ts is not None:
        entries.append(("tool_selection", ts))
    if diff_coherence is not None:
        dc = advice_for_diff_coherence(diff_coherence)
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
    expected_provided: bool,
) -> str:
    subject = _header_subject(session_id, session_label)
    lines = [
        f"clinescope report - {subject} ({len(trace.tool_calls)} tool calls)",
        _render_summary_tool_selection(score, expected_provided),
    ]
    if diff_coherence is not None:
        lines.append(
            _render_summary_line(
                "diff_coherence",
                render_score_out_of_100(diff_coherence.score),
                summary_verdict(diff_coherence.score),
                _summary_reason_diff_coherence(diff_coherence),
            )
        )
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
    footer = _summary_footer(
        score,
        expected_provided,
        diff_coherence,
        diff_minimality,
        apply_recovery,
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


def _summary_reason_diff_coherence(score: DiffCoherenceScore) -> str:
    # diff_coherence never abstains (no apply_patch is a hard 0.0, not n/a), so a
    # reason is only useful to name WHY a hard-zero happened -- the first violation.
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
) -> str | None:
    # A positive takeaway on a clean run (U1): if nothing scored below its bar,
    # say so plainly rather than leaving the reader to eyeball four lines. A
    # scorer that abstained (n/a) is neutral -- it neither passes nor fails, so it
    # does not block the clean verdict. tool_selection counts only when scored.
    tool_ok = (not expected_provided) or not score.missing
    coherence_ok = diff_coherence is None or diff_coherence.score == 1.0
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
    if tool_ok and coherence_ok and minimality_ok and recovery_ok:
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


# --- Verbose rendering (the full debug dump; unchanged byte-for-byte) ---------


def _header_subject(session_id: str | None, session_label: str | None) -> str:
    # An explicit label (e.g. an extension session's taskId + title + variant) wins;
    # otherwise fall back to the World-A "session <id>" phrasing, unchanged.
    if session_label is not None:
        return session_label
    sid = session_id if session_id is not None else "<unknown>"
    return f"session {sid}"


def _render_verbose(
    trace: Trace,
    score: ToolSelectionScore,
    *,
    session_id: str | None,
    session_label: str | None = None,
    diff_coherence: DiffCoherenceScore | None,
    diff_minimality: DiffMinimalityScore | None,
    apply_recovery: ApplyRecoveryScore | None,
) -> str:
    lines = ["=== clinescope report ==="]
    if session_label is not None:
        lines.append(f"session:        {session_label}")
    else:
        lines.append(
            f"sessionId:      {session_id if session_id is not None else '<unknown>'}"
        )
    lines += [
        f"trace.version:  {trace.version}",
        f"turns:          {len(trace.turns)}",
        f"tool_calls:     {len(trace.tool_calls)}",
        "",
        "[tool_selection]",
        f"score:          {score.score:.4f}",
        f"expected:       {_render_names(score.expected)}",
        f"used:           {_render_names(score.used)}",
        f"matched:        {_render_names(score.matched)}",
        f"missing:        {_render_names(score.missing)}",
        f"unexpected:     {_render_names(score.unexpected)}",
    ]
    if diff_coherence is not None:
        lines.extend(_render_diff_coherence(diff_coherence))
    if diff_minimality is not None:
        lines.extend(_render_diff_minimality(diff_minimality))
    if apply_recovery is not None:
        lines.extend(_render_apply_recovery(apply_recovery))
    return "\n".join(lines)


def _render_diff_coherence(score: DiffCoherenceScore) -> list[str]:
    return [
        "",
        "[diff_coherence]",
        f"score:          {score.score:.4f}",
        f"passed_gates:   {_render_names(score.passed_gates)}",
        f"failed_gates:   {_render_names(score.failed_gates)}",
        f"violations:     {_render_violations(score.violations)}",
        f"apply_patch_calls: {score.apply_patch_call_count}",
        f"cline_is_error: {score.cline_apply_is_error}",
    ]


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
        f"failed_files:   {_render_violations(score.failed_target_paths)}",
        f"recovered_by:   {_render_recovery_pairs(score.recovery_pairs)}",
        f"unparseable_failed_calls: {score.unparseable_failed_calls}",
        f"violations:     {_render_violations(score.violations)}",
        f"apply_patch_calls: {score.apply_patch_call_count}",
        f"cline_is_error: {score.cline_apply_is_error}",
    ]


def _render_recovery_pairs(pairs: tuple[tuple[int, int, str], ...]) -> str:
    # Each triple: the failed call index, the confirming call index, the file. The
    # index gap is the evidence -- a large gap is a distant (possibly unrelated) fix.
    return (
        "; ".join(f"{path} @ call {fail}->{fixer}" for fail, fixer, path in pairs)
        if pairs
        else "-"
    )


def _render_optional_4f(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def _render_names(names: frozenset[str]) -> str:
    return ", ".join(sorted(names)) if names else "-"


def _render_violations(violations: tuple[str, ...]) -> str:
    # Order-preserving (detection order is information), so NOT sorted.
    return "; ".join(violations) if violations else "-"
