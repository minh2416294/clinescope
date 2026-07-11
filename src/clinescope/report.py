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
    diff_coherence: DiffCoherenceScore | None = None,
    diff_minimality: DiffMinimalityScore | None = None,
    apply_recovery: ApplyRecoveryScore | None = None,
    verbose: bool = False,
) -> str:
    if verbose:
        return _render_verbose(
            trace,
            score,
            session_id=session_id,
            diff_coherence=diff_coherence,
            diff_minimality=diff_minimality,
            apply_recovery=apply_recovery,
        )
    return _render_summary(
        trace,
        score,
        session_id=session_id,
        diff_coherence=diff_coherence,
        diff_minimality=diff_minimality,
        apply_recovery=apply_recovery,
    )


# --- Default summary rendering (one line per scorer) --------------------------


def _render_summary(
    trace: Trace,
    score: ToolSelectionScore,
    *,
    session_id: str | None,
    diff_coherence: DiffCoherenceScore | None,
    diff_minimality: DiffMinimalityScore | None,
    apply_recovery: ApplyRecoveryScore | None,
) -> str:
    sid = session_id if session_id is not None else "<unknown>"
    lines = [
        f"clinescope report - session {sid} ({len(trace.tool_calls)} tool calls)",
        _render_summary_tool_selection(score),
    ]
    if diff_coherence is not None:
        lines.append(
            _render_summary_line(
                "diff_coherence",
                _render_score_out_of_100(diff_coherence.score),
                _summary_verdict(diff_coherence.score),
            )
        )
    if diff_minimality is not None:
        lines.append(
            _render_summary_line(
                "diff_minimality",
                _render_score_out_of_100(diff_minimality.score),
                _summary_verdict(diff_minimality.score),
            )
        )
    if apply_recovery is not None:
        lines.append(_render_summary_apply_recovery(apply_recovery))
    return "\n".join(lines)


def _render_summary_tool_selection(score: ToolSelectionScore) -> str:
    # tool_selection is a recall metric with no threshold, so a sub-100 score
    # gets NO PASS/FAIL word -- just the number and the actionable missing tools.
    # The gate (clinescope.gate) is the thing that turns a score into a verdict.
    verdict = "PASS" if score.score == 1.0 else ""
    extra = f"(missing: {_render_names(score.missing)})" if score.missing else ""
    return _render_summary_line(
        "tool_selection",
        _render_score_out_of_100(score.score),
        verdict,
        extra,
    )


def _render_summary_apply_recovery(score: ApplyRecoveryScore) -> str:
    # Only when the metric applies (something failed) do we report the N/M count;
    # a clean run with nothing to recover abstains (n/a) with no extra.
    extra = (
        f"({score.confirmed_recovered_pairs}/{score.total_failed_pairs} "
        "failed patches recovered)"
        if score.applicable
        else ""
    )
    return _render_summary_line(
        "apply_recovery",
        _render_score_out_of_100(score.score),
        _summary_verdict(score.score),
        extra,
    )


def _render_summary_line(name: str, cell: str, verdict: str, extra: str = "") -> str:
    line = f"{name:<{_SUMMARY_NAME_WIDTH}} {cell:>{_SUMMARY_CELL_WIDTH}}"
    if verdict:
        line = f"{line}  {verdict}"
    if extra:
        line = f"{line}   {extra}"
    return line


def _render_score_out_of_100(score: float | None) -> str:
    # None means the scorer abstained (metric undefined for this trace) -> "n/a";
    # a real 0.0 float (e.g. diff_coherence's hard-zero) still renders "0/100".
    # Round-half-up: int(x*100 + 0.5), the single source of the NN/100 rounding.
    if score is None:
        return "n/a"
    return f"{int(score * 100 + 0.5)}/100"


def _summary_verdict(score: float | None) -> str:
    if score is None:
        return "n/a"
    return "PASS" if score == 1.0 else "FAIL"


# --- Verbose rendering (the full debug dump; unchanged byte-for-byte) ---------


def _render_verbose(
    trace: Trace,
    score: ToolSelectionScore,
    *,
    session_id: str | None,
    diff_coherence: DiffCoherenceScore | None,
    diff_minimality: DiffMinimalityScore | None,
    apply_recovery: ApplyRecoveryScore | None,
) -> str:
    lines = [
        "=== clinescope report ===",
        f"sessionId:      {session_id if session_id is not None else '<unknown>'}",
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
