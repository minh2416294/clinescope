"""Tool-input recall scorer (deterministic, zero-LLM).

:mod:`clinescope.tool_selection` checks tool NAMES only. This scorer checks that at
least one call to a tool carried an input the caller named, stated on the command line
as ``--expected-input editor path=src/app.py``:

    score = |expected inputs some call carried| / |expected inputs|

Deliberate decisions (each a stated choice, not undefined behaviour):

* **``editor`` only.** It is the tool almost every current Cline session edits with,
  and its inputs are flat keys (``path``, ``old_text``, ``new_text``, ``insert_line``,
  per cline ``sdk/packages/core/src/extensions/tools/schemas.ts``; ``LIMITATIONS.md``
  cites the commit). Another tool is a usage error in :func:`tool_input_parse`, not a
  silent zero: scoring a tool this module cannot read would blame the agent for it.
* **A ``path`` matches on its ending.** Real traces carry absolute paths, spelled
  ``C:\\...`` or ``C:/...``, which a caller writing ``src/app.py`` cannot predict. Both
  sides go through :func:`clinescope.recovery_path.recovery_path_key`, then the trace
  path must equal the expected one or end with ``/`` plus it. Case is kept, as in the
  recovery scorers, so ``Calc.py`` does not match ``calc.py``.
* **Every other key matches as exact text.** ``str(value)`` against the caller's text,
  so an ``insert_line`` sent as ``5`` or as ``"5"`` both match ``insert_line=5``.
* **Recall, never precision.** One matching call is enough; what the other calls
  carried is not checked. A match says the input was sent, not that the call succeeded.
* **Outcomes.** The CLI scores this only when ``--expected-input`` is given, so without
  the flag the report has no line (omitted, the same split ``editor_recovery`` uses).
  With the flag, a trace with no ``editor`` call scores a real ``0.0``: the question
  "did some call carry this input" has a definite answer there, and it is no.

Pure: no I/O, no LLM, deterministic. It reads only ``Trace.tool_calls``.
"""

from __future__ import annotations

from dataclasses import dataclass

from clinescope.recovery_path import recovery_path_key
from clinescope.world_a import Trace

TOOL_INPUT_TOOLS: frozenset[str] = frozenset({"editor"})
TOOL_INPUT_EDITOR_KEYS: frozenset[str] = frozenset(
    {"path", "old_text", "new_text", "insert_line"}
)
_PATH_KEY = "path"


@dataclass(frozen=True, slots=True, order=True)
class ExpectedInput:
    """One ``--expected-input TOOL KEY=VALUE``. Operator text, never trace text."""

    tool: str
    key: str
    value: str

    def __str__(self) -> str:
        return f"{self.tool} {self.key}={self.value}"


@dataclass(frozen=True, slots=True)
class ToolInputScore:
    """Result of :func:`score_tool_input`.

    Invariants: ``matched | missing == expected``, the two are disjoint, and
    ``score = len(matched) / len(expected)`` (``1.0`` if ``expected`` is empty).
    """

    score: float
    expected: frozenset[ExpectedInput]
    matched: frozenset[ExpectedInput]
    missing: frozenset[ExpectedInput]


def tool_input_parse(tool: str, pair: str) -> ExpectedInput:
    """Turn one ``--expected-input TOOL KEY=VALUE`` into an :class:`ExpectedInput`.

    Splits on the FIRST ``=``, so a value may itself contain ``=``.

    Raises:
        ValueError: The tool is not one this scorer reads, or ``pair`` has no ``=`` or
            an empty key. The message is the CLI's error line.
    """
    if tool not in TOOL_INPUT_TOOLS:
        raise ValueError(
            f"--expected-input supports only the editor tool, got '{tool}'"
        )
    key, separator, value = pair.partition("=")
    if not separator or not key:
        raise ValueError(
            f"--expected-input needs KEY=VALUE after the tool, got '{pair}'"
        )
    return ExpectedInput(tool=tool, key=key, value=value)


def score_tool_input(
    trace: Trace, expected: set[ExpectedInput] | frozenset[ExpectedInput]
) -> ToolInputScore:
    """Score recall of ``expected`` inputs over ``trace``'s tool calls."""
    expected_inputs = frozenset(expected)
    matched = frozenset(
        wanted for wanted in expected_inputs if _tool_input_was_sent(trace, wanted)
    )
    missing = expected_inputs - matched
    score = 1.0 if not expected_inputs else len(matched) / len(expected_inputs)
    return ToolInputScore(
        score=score, expected=expected_inputs, matched=matched, missing=missing
    )


def _tool_input_was_sent(trace: Trace, wanted: ExpectedInput) -> bool:
    for call in trace.tool_calls:
        if call.name != wanted.tool or wanted.key not in call.input:
            continue
        actual = str(call.input[wanted.key])
        if wanted.key == _PATH_KEY:
            if _tool_input_path_matches(actual, wanted.value):
                return True
        elif actual == wanted.value:
            return True
    return False


def _tool_input_path_matches(actual: str, wanted: str) -> bool:
    actual_key = recovery_path_key(actual)
    wanted_key = recovery_path_key(wanted)
    return actual_key == wanted_key or actual_key.endswith("/" + wanted_key)
