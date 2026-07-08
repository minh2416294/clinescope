"""Tool-selection-correctness scorer (deterministic, zero-LLM).

The first metric of the walking skeleton's "score" stage (load -> SCORE -> emit).
It scores a loaded :class:`~agent_eval_harness.world_a.Trace` against a
caller-supplied set of expected tool names, using name-only *recall*:

    score = |used names intersect expected| / |expected|

This is DeepEval's ``ToolCorrectness`` default (name-only, set-based, unordered).
It is NOT the ordered or argument-matching variant.

Deliberate decisions (each a stated choice, not undefined behaviour):

* Duplicate tool calls with the same name count once -- recall asks "was this
  expected tool used at all", a yes/no per name; multiplicity is a different
  metric, out of scope.
* Extra tools (used beyond expected) never lower the score -- that is the
  definition of recall; penalising extras is precision's job. Extras are
  surfaced via ``unexpected`` so a caller can still see them.
* ``expected`` names never used land in ``missing`` and drag the score down.
* An empty ``expected`` set scores 1.0 (vacuous recall: nothing was required,
  so nothing was missed); the empty guard keys on ``expected``, not ``used``.
* Selection is judged by *invocation*, not success: an errored tool call
  (``ToolCall.is_error is True``) still counts as the tool having been used.
  A "successfully used" metric would be a separate scorer keyed on ``is_error``.

The scorer is pure: no I/O, no LLM, deterministic. It reads only
``Trace.tool_calls`` and ``ToolCall.name``.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_eval_harness.world_a import Trace


@dataclass(frozen=True, slots=True)
class ToolSelectionScore:
    """Result of :func:`score_tool_selection`.

    Invariants (all derived from ``used`` and ``expected``):

    * ``matched = used & expected`` -- literally the score numerator.
    * ``missing = expected - used``
    * ``unexpected = used - expected``
    * ``score = len(matched) / len(expected)`` (or ``1.0`` if ``expected`` is empty).
    """

    score: float
    expected: frozenset[str]
    used: frozenset[str]
    matched: frozenset[str]
    missing: frozenset[str]
    unexpected: frozenset[str]


def score_tool_selection(trace: Trace, expected: set[str]) -> ToolSelectionScore:
    """Score name-only tool-selection recall of ``trace`` against ``expected``.

    Args:
        trace: A loaded World-A trace; only ``trace.tool_calls`` is read.
        expected: The set of tool names that should have been used.

    Raises:
        TypeError: If ``expected`` is a ``str``. A bare string where a set is
            expected does not raise on its own -- ``frozenset("read_files")``
            would silently become a set of characters and return a plausible
            but wrong score -- so this one silent-wrong-answer case is guarded.
    """
    if isinstance(expected, str):
        raise TypeError(
            f"expected must be a set of tool names, not a str ({expected!r}); "
            "a str would be split into characters and score wrongly"
        )

    expected_names = frozenset(expected)
    used_names = frozenset(call.name for call in trace.tool_calls)
    matched = used_names & expected_names
    missing = expected_names - used_names
    unexpected = used_names - expected_names
    score = 1.0 if not expected_names else len(matched) / len(expected_names)

    return ToolSelectionScore(
        score=score,
        expected=expected_names,
        used=used_names,
        matched=matched,
        missing=missing,
        unexpected=unexpected,
    )
