"""Did a command containing the caller's text run after the last edit? (deterministic)

``clinescope --test-cmd TEXT`` answers one narrow question from Cline's own record:
after the last edit Cline did not mark failed, did a ``run_commands`` entry whose command
contains TEXT appear, and what did Cline record for it? It is a context line in the
report, not a scorer: no score, no gate flag, and it never runs anything.

It does NOT say the fix works. A ``success`` Cline recorded means that command line
exited 0 on the agent's machine, nothing more: the tests may not cover the change, and a
chained command (``pytest; echo done``) reports its LAST statement, so the test run's own
exit can be hidden. An edit made by a shell command (``sed``, ``Remove-Item``) is not an
edit here, because only edit tools are read.

Deliberate decisions (each a stated choice, not undefined behaviour):

* **The last edit** is the last ``apply_patch``, ``editor``, ``write_to_file`` or
  ``replace_in_file`` call whose verdict (:func:`clinescope.tool_verdict.tool_verdict_effective`)
  is not "failed". A failed edit changed nothing, so a command run before it still ran
  against the final file. An edit with no verdict still counts: an unresolved verdict is
  a third state, never read as a failure (``docs/internal/INVARIANTS.md``).
* **Only ``run_commands`` is read.** Its result is a list with one dict per command:
  ``query`` (the command), ``result``, ``success`` and, on a non-zero exit, ``error``.
  A call with no list result falls back to its input ``commands``, with no verdict. A
  trace containing ``execute_command`` (the VS Code extension's command tool, whose
  results this module does not read) gets status ``execute_command``, shown as ``n/a``,
  because "not run" there would be a false miss.
* **The match is the caller's own text,** a case-sensitive substring of ``query``. No
  list of test-runner names. When several entries match after the last edit, the last
  one is reported, since it ran against the final state.
* **Position in ``Trace.tool_calls`` is time,** so this never sorts or filters that
  sequence before indexing it.

Pure: no I/O, no LLM, deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from clinescope.tool_verdict import tool_verdict_effective
from clinescope.world_a import ToolCall, Trace

CmdAfterEditStatus = Literal[
    "ran", "not_run", "no_edit", "every_edit_failed", "execute_command"
]

_EDIT_TOOLS = frozenset({"apply_patch", "editor", "write_to_file", "replace_in_file"})
_COMMAND_TOOL = "run_commands"
_UNREAD_COMMAND_TOOL = "execute_command"


@dataclass(frozen=True, slots=True)
class CmdAfterEditCheck:
    """Result of :func:`cmd_after_edit_check`.

    ``success`` is Cline's own flag for the matched command, ``None`` when it recorded
    none. ``error`` is the RAW first line of Cline's error text for it: a caller that
    renders it must neutralize it first. The indices are positions in
    ``Trace.tool_calls``.
    """

    status: CmdAfterEditStatus
    last_edit_index: int | None = None
    command_index: int | None = None
    success: bool | None = None
    error: str | None = None


def cmd_after_edit_check(trace: Trace, text: str) -> CmdAfterEditCheck:
    """Find the last command containing ``text`` after the last standing edit."""
    calls = trace.tool_calls
    if any(call.name == _UNREAD_COMMAND_TOOL for call in calls):
        return CmdAfterEditCheck(status="execute_command")
    edits = [index for index, call in enumerate(calls) if call.name in _EDIT_TOOLS]
    if not edits:
        return CmdAfterEditCheck(status="no_edit")
    standing = [
        index for index in edits if tool_verdict_effective(calls[index]) is not True
    ]
    if not standing:
        return CmdAfterEditCheck(status="every_edit_failed")
    last_edit = standing[-1]

    match: tuple[int, dict[str, object]] | None = None
    for index in range(last_edit + 1, len(calls)):
        for entry in _cmd_after_edit_entries(calls[index]):
            query = entry.get("query")
            if isinstance(query, str) and text in query:
                match = (index, entry)
    if match is None:
        return CmdAfterEditCheck(status="not_run", last_edit_index=last_edit)

    command_index, entry = match
    success = entry.get("success")
    error = entry.get("error")
    return CmdAfterEditCheck(
        status="ran",
        last_edit_index=last_edit,
        command_index=command_index,
        success=success if isinstance(success, bool) else None,
        error=error.strip().splitlines()[0]
        if isinstance(error, str) and error.strip()
        else None,
    )


def _cmd_after_edit_entries(call: ToolCall) -> list[dict[str, object]]:
    if call.name != _COMMAND_TOOL:
        return []
    content = call.result_content
    if isinstance(content, list):
        return [entry for entry in content if isinstance(entry, dict)]
    commands = call.input.get("commands")
    if isinstance(commands, list):
        return [{"query": command} for command in commands if isinstance(command, str)]
    return []
