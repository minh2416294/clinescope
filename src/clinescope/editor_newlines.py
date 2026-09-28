"""Did an editor call flatten real line breaks into literal ``\\n``? (deterministic)

``clinescope`` reports one narrow shape that Cline accepts and so no scorer sees: an
``editor`` call Cline did not mark failed whose ``old_text`` has real line breaks while
its ``new_text`` has none but carries the two characters backslash and ``n``. On
2026-09-27 a granite4.1:8b session made exactly that call: it replaced 30 lines of
``inventory.py`` with one line holding 78 literal ``\\n``, Cline reported success, and
the file no longer parsed (``examples/live-granite-escaped-newlines.json``). It is a
context line in the report, not a scorer: no score, no gate flag.

It does NOT say the file is broken, and it does NOT catch every broken edit. Deliberate
decisions (each a stated choice, not undefined behaviour):

* **Structural, no count.** Requiring real line breaks in ``old_text`` is what keeps an
  ordinary one-line edit such as ``print("a\\nb")`` from matching. The cost is that a
  call with no ``old_text`` (creating a file, or ``insert_line``) is never checked.
* **A call Cline marked failed is skipped** (:func:`clinescope.tool_verdict.tool_verdict_effective`
  is ``True``): it changed nothing. A call with no verdict is still checked, because an
  unresolved verdict is a third state, never read as a failure.
* **A later edit is not read.** A hit stays a hit even if a later call rewrote the same
  lines, since telling which lines a later edit touched would need the file itself.

Pure: no I/O, no LLM, deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass

from clinescope.tool_verdict import tool_verdict_effective
from clinescope.world_a import ToolCall, Trace

_EDITOR_TOOL = "editor"
_LINE_BREAK = "\n"
_LITERAL_LINE_BREAK = "\\n"


@dataclass(frozen=True, slots=True)
class EditorNewlinesCheck:
    """Result of :func:`editor_newlines_check`.

    ``hits`` holds one ``(index, path)`` per flagged call, in trace order. ``index`` is
    the position in ``Trace.tool_calls``. ``path`` is the RAW trace value, ``None`` when
    the call carried no string path: a caller that renders it must neutralize it first.
    """

    hits: tuple[tuple[int, str | None], ...]


def editor_newlines_check(trace: Trace) -> EditorNewlinesCheck:
    """Find every editor call that flattened real line breaks into literal ``\\n``."""
    hits: list[tuple[int, str | None]] = []
    for index, call in enumerate(trace.tool_calls):
        if _editor_newlines_flattened(call):
            path = call.input.get("path")
            hits.append((index, path if isinstance(path, str) else None))
    return EditorNewlinesCheck(hits=tuple(hits))


def _editor_newlines_flattened(call: ToolCall) -> bool:
    if call.name != _EDITOR_TOOL or tool_verdict_effective(call) is True:
        return False
    old_text = call.input.get("old_text")
    new_text = call.input.get("new_text")
    if not isinstance(old_text, str) or not isinstance(new_text, str):
        return False
    return (
        _LINE_BREAK in old_text
        and _LINE_BREAK not in new_text
        and _LITERAL_LINE_BREAK in new_text
    )
