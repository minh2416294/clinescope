"""Report emitter: the EMIT stage of the walking skeleton (load -> score -> EMIT).

A single pure function, :func:`render_report`, turns a loaded World-A
:class:`~clinescope.world_a.Trace` and a
:class:`~clinescope.tool_selection.ToolSelectionScore` (and, optionally, a
:class:`~clinescope.diff_coherence.DiffCoherenceScore` and/or a
:class:`~clinescope.diff_minimality.DiffMinimalityScore`) into one
human-readable, machine-greppable report string.

No I/O, no LLM: aligned ``key: value`` lines, each frozenset ``sorted()`` for
stable output. The ``.score`` float stays exact on the dataclass; only the
displayed value is formatted (``.4f``). ``sessionId`` is not modelled on
``Trace`` (the loader discards it), so it is passed in by the caller rather
than read here. ``diff_coherence`` and ``diff_minimality`` are optional
keywords: when ``None`` the matching section is omitted, so existing
single-scorer callers keep their exact output.
"""

from __future__ import annotations

from clinescope.apply_recovery import ApplyRecoveryScore
from clinescope.diff_coherence import DiffCoherenceScore
from clinescope.diff_minimality import DiffMinimalityScore
from clinescope.tool_selection import ToolSelectionScore
from clinescope.world_a import Trace


def render_report(
    trace: Trace,
    score: ToolSelectionScore,
    *,
    session_id: str | None = None,
    diff_coherence: DiffCoherenceScore | None = None,
    diff_minimality: DiffMinimalityScore | None = None,
    apply_recovery: ApplyRecoveryScore | None = None,
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
