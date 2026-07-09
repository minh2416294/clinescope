"""Report emitter: the EMIT stage of the walking skeleton (load -> score -> EMIT).

A single pure function, :func:`render_report`, turns a loaded World-A
:class:`~clinescope.world_a.Trace` and a
:class:`~clinescope.tool_selection.ToolSelectionScore` into one
human-readable, machine-greppable report string.

No I/O, no LLM: aligned ``key: value`` lines, each frozenset ``sorted()`` for
stable output. The ``.score`` float stays exact on the dataclass; only the
displayed value is formatted (``.4f``). ``sessionId`` is not modelled on
``Trace`` (the loader discards it), so it is passed in by the caller rather
than read here.
"""

from __future__ import annotations

from clinescope.tool_selection import ToolSelectionScore
from clinescope.world_a import Trace


def render_report(
    trace: Trace,
    score: ToolSelectionScore,
    *,
    session_id: str | None = None,
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
    return "\n".join(lines)


def _render_names(names: frozenset[str]) -> str:
    return ", ".join(sorted(names)) if names else "-"
