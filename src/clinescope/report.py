"""Report emitter: the EMIT stage of the walking skeleton (load -> score -> EMIT).

A single pure function, :func:`render_report`, turns a loaded World-A
:class:`~clinescope.world_a.Trace` and a
:class:`~clinescope.tool_selection.ToolSelectionScore` (and, optionally, a
:class:`~clinescope.diff_coherence.DiffCoherenceScore`) into one
human-readable, machine-greppable report string.

No I/O, no LLM: aligned ``key: value`` lines, each frozenset ``sorted()`` for
stable output. The ``.score`` float stays exact on the dataclass; only the
displayed value is formatted (``.4f``). ``sessionId`` is not modelled on
``Trace`` (the loader discards it), so it is passed in by the caller rather
than read here. ``diff_coherence`` is an optional keyword: when ``None`` the
``[diff_coherence]`` section is omitted, so existing single-scorer callers keep
their exact output.
"""

from __future__ import annotations

from clinescope.diff_coherence import DiffCoherenceScore
from clinescope.tool_selection import ToolSelectionScore
from clinescope.world_a import Trace


def render_report(
    trace: Trace,
    score: ToolSelectionScore,
    *,
    session_id: str | None = None,
    diff_coherence: DiffCoherenceScore | None = None,
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


def _render_names(names: frozenset[str]) -> str:
    return ", ".join(sorted(names)) if names else "-"


def _render_violations(violations: tuple[str, ...]) -> str:
    # Order-preserving (detection order is information), so NOT sorted.
    return "; ".join(violations) if violations else "-"
