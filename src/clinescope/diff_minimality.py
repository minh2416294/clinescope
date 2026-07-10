"""Diff-minimality scorer (deterministic, zero-LLM) -- the criterion-2 wedge, 2nd slice.

Sits alongside :mod:`clinescope.diff_coherence`. Where coherence asks "is the
``apply_patch`` patch *well-formed*?", minimality asks one narrow, honest question
about its *shape*: does each edited region retain an anchor, or is it a **blind
whole-block rewrite** -- delete N lines, retype N lines, keeping nothing?

    score = 1 - (blind_rewrite_hunks / hunks_with_body)   (floored to a 1/4 grid)

**What "minimality" means here (the honesty caveat -- read this).**
This detects EXACTLY ONE bloat shape: a *blind whole-block rewrite* inside an
``*** Update File`` hunk -- a maximal run of ``>= FLOOR`` consecutive ``-`` lines
immediately followed by a run of ``>= FLOOR`` ``+`` lines, with no anchor line
retained. It is **BLIND to the other, more common bloat: dragging large unchanged
context.** It deliberately does NOT threshold on context-line count, because
context is what ``apply_patch`` needs to anchor a hunk -- penalizing it would
*invert* the metric on well-formed patches (a design workflow proved every
context-count / line-similarity signal inverts on real patches; only run-length
blind-rewrite detection survived). Therefore a heavily context-padded patch can
still score 1.0.

A LOW score means "contains a large blind rewrite" (which MAY be necessary --
read it as *large-block*, not *wasteful*); a HIGH score means "no blind rewrite",
NOT "minimal". Read ``mean_context_density`` (descriptive evidence, never scored)
alongside the number; never read the score as a standalone minimality verdict.
This is NOT churn-vs-an-ideal-patch (no reference exists) nor repo-anchored
minimality (no checkout exists) -- both would be theatre. It is a structural
property of the patch TEXT ALONE, like its coherence sibling. (Mirrors the
charter's "scores are glued to the setup".)

**Deliberate decisions (each a stated choice, not undefined behaviour):**

* No ``apply_patch`` call -> ``applicable=False``, ``score=None`` (NOT hard-zero,
  NOT floating-1.0: minimality is undefined when there is no patch to shape-check,
  exactly as an absent action type is vacuous in the coherence sibling).
* ``apply_patch`` present but ``input`` carries no ``str`` under ``"input"``
  (e.g. the fictional ``{"diff": ...}`` shape) -> hard 0.0, shape violation.
* Empty / whitespace-only, or grammar-unparseable, patch text -> hard 0.0 (the
  artifact is mis-shaped -- reuses the coherence sibling's grammar parser, so a
  patch that fails coherence's sentinel/header rules also fails here).
* Multiple ``apply_patch`` calls -> the FIRST is scored; the count is surfaced.
* Parses, but has no ``*** Update File`` hunk body (e.g. an Add-File-only patch)
  -> ``hunks_with_body == 0`` -> vacuous 1.0. Add is definitionally all-``+``;
  sizing a new file needs a reference we do not have, so Add is never penalized.
  ``add_file_lines`` is surfaced as context.
* ``FLOOR = 3``: a 1-2 line delete-then-retype run is the commonest *legitimate*
  surgical edit; a run of ``>= 3`` is the text-provable "rewrote the whole block".
  A named module constant, cited as a heuristic in the violation string.
* Selection-vs-success separation: ``tool_result.is_error`` is CONTEXT ONLY on
  ``cline_apply_is_error``; it NEVER enters the score (mirrors the siblings).

The scorer is pure: no I/O, no LLM, deterministic. It reads only
``Trace.tool_calls`` and reuses the coherence sibling's grammar parser.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from clinescope.diff_coherence import (
    diff_coherence_normalize,
    diff_coherence_read_patch_text,
    diff_coherence_select_apply_patch,
)
from clinescope.world_a import Trace

# The commonest legitimate surgical edit is a 1-2 line delete-then-retype; a run
# of this many or more consecutive -/+ lines is the text-provable "blind rewrite".
FLOOR = 3

_UPDATE = "*** Update File: "
_ADD = "*** Add File: "
_SECTION = "@@"
_MOVE = "*** Move to: "


@dataclass(frozen=True, slots=True)
class DiffMinimalityScore:
    """Result of :func:`score_diff_minimality`.

    Invariants (all derived from the FIRST ``apply_patch`` call's patch text):

    * ``applicable`` is ``False`` iff there is no ``apply_patch`` call at all; then
      ``score is None`` and every other field is its empty/zero default.
    * When ``applicable`` and the patch is mis-shaped/empty/unparseable, ``score``
      is a hard ``0.0`` and ``violations`` explains why.
    * Otherwise ``score = floor_to_quarter(1 - blind_rewrite_hunks / hunks_with_body)``
      in ``{0.0, 0.25, 0.5, 0.75, 1.0}``, or ``1.0`` when ``hunks_with_body == 0``.
      It is ``1.0`` IFF ``blind_rewrite_hunks == 0`` (flooring never rounds a blind
      rewrite away into a perfect headline).
    * ``violations`` has >=1 entry iff the score is a hard-zero OR at least one hunk
      is a blind rewrite; it is ordered (detection order).
    * ``mean_context_density`` is the mean over update hunks of
      ``context / (context + changed)`` -- DESCRIPTIVE EVIDENCE ONLY, never in the
      score. ``None`` when there are no update-hunk bodies.
    * ``cline_apply_is_error`` mirrors the scored call's ``tool_result.is_error`` --
      CONTEXT ONLY, never an input to the score.

    Detects ONE bloat shape (blind whole-block rewrites); BLIND to context-drag
    bloat (see the module docstring's honesty caveat).
    """

    score: float | None
    applicable: bool
    blind_rewrite_hunks: int
    hunks_with_body: int
    violations: tuple[str, ...]
    mean_context_density: float | None
    add_file_lines: int
    apply_patch_call_count: int
    cline_apply_is_error: bool | None


def score_diff_minimality(trace: Trace) -> DiffMinimalityScore:
    """Score blind-whole-block-rewrite minimality of the ``apply_patch`` in ``trace``.

    Args:
        trace: A loaded World-A trace; only ``trace.tool_calls`` is read.

    Raises:
        TypeError: If ``trace`` is not a :class:`~clinescope.world_a.Trace` -- most
            temptingly a raw patch ``str``. Turned into one loud early error rather
            than a cryptic crash or a silently-wrong score on a duck-typed object.
    """
    if not isinstance(trace, Trace):
        raise TypeError(
            f"score_diff_minimality takes a Trace, not {type(trace).__name__} "
            f"({trace!r:.60}); pass a loaded trace, not raw patch text"
        )

    call, count = diff_coherence_select_apply_patch(trace)
    if call is None:
        return _minimality_not_applicable()

    is_error = call.is_error
    text = diff_coherence_read_patch_text(call)
    if text is None:
        return _minimality_hard_zero(
            ('apply_patch input has no str under key "input" (bad shape)',),
            count,
            is_error,
        )
    if not text.strip():
        return _minimality_hard_zero(("empty patch text",), count, is_error)

    lines, hard_violation = diff_coherence_normalize(text)
    if hard_violation is not None:
        return _minimality_hard_zero(
            (f"unparseable patch grammar: {hard_violation}",), count, is_error
        )

    hunks = _minimality_split_update_hunks(lines)
    add_file_lines = _minimality_count_add_lines(lines)
    if not hunks:
        return DiffMinimalityScore(
            score=1.0,
            applicable=True,
            blind_rewrite_hunks=0,
            hunks_with_body=0,
            violations=(),
            mean_context_density=None,
            add_file_lines=add_file_lines,
            apply_patch_call_count=count,
            cline_apply_is_error=is_error,
        )

    return _minimality_grade_hunks(hunks, add_file_lines, count, is_error)


def _minimality_not_applicable() -> DiffMinimalityScore:
    return DiffMinimalityScore(
        score=None,
        applicable=False,
        blind_rewrite_hunks=0,
        hunks_with_body=0,
        violations=("no apply_patch tool call in trace",),
        mean_context_density=None,
        add_file_lines=0,
        apply_patch_call_count=0,
        cline_apply_is_error=None,
    )


def _minimality_hard_zero(
    violations: tuple[str, ...], count: int, is_error: bool | None
) -> DiffMinimalityScore:
    return DiffMinimalityScore(
        score=0.0,
        applicable=True,
        blind_rewrite_hunks=0,
        hunks_with_body=0,
        violations=violations,
        mean_context_density=None,
        add_file_lines=0,
        apply_patch_call_count=count,
        cline_apply_is_error=is_error,
    )


def _minimality_split_update_hunks(lines: list[str]) -> list[list[str]]:
    """Return the body lines of each '@@' hunk under an '*** Update File' header.

    A hunk's body runs from just after its '@@' marker to the next '@@' or the
    next '***' header. Only content lines (prefixed ' '/'-'/'+') are kept; the
    '@@' markers and Move/Delete headers carry no minimality signal.
    """
    hunks: list[list[str]] = []
    in_update = False
    current: list[str] | None = None
    for line in lines:
        if line.startswith(_UPDATE):
            in_update = True
            current = None
            continue
        if line.startswith("***"):
            # any other header (Add/Delete/Move/Begin/End) closes update context
            if not line.startswith(_MOVE):
                in_update = False
            current = None
            continue
        if not in_update:
            continue
        if line.startswith(_SECTION):
            current = []
            hunks.append(current)
            continue
        if current is not None and line and line[0] in (" ", "-", "+"):
            current.append(line)
    return [hunk for hunk in hunks if hunk]


def _minimality_count_add_lines(lines: list[str]) -> int:
    """Count '+' content lines inside '*** Add File' blocks (context only)."""
    in_add = False
    total = 0
    for line in lines:
        if line.startswith(_ADD):
            in_add = True
            continue
        if line.startswith("***"):
            in_add = False
            continue
        if in_add and line.startswith("+"):
            total += 1
    return total


def _minimality_hunk_is_blind(hunk: list[str]) -> bool:
    """True iff the hunk contains a run of >=FLOOR '-' lines immediately followed
    by a run of >=FLOOR '+' lines (a blind whole-block rewrite)."""
    minus_run = 0
    plus_run = 0
    for line in hunk:
        if line.startswith("-"):
            minus_run += 1
            plus_run = 0
        elif line.startswith("+"):
            if minus_run >= FLOOR:
                plus_run += 1
                if plus_run >= FLOOR:
                    return True
            else:
                minus_run = 0
        else:
            minus_run = 0
            plus_run = 0
    return False


def _minimality_context_density(hunk: list[str]) -> float | None:
    context = sum(1 for line in hunk if line.startswith(" "))
    changed = sum(1 for line in hunk if line[0] in ("-", "+"))
    total = context + changed
    return context / total if total else None


def _minimality_floor_quarter(value: float) -> float:
    # FLOOR to the quarter below, NOT round(): the invariant that matters is
    # "score == 1.0 IFF zero blind rewrites". Rounding (banker's OR half-up)
    # ties a raw 0.875 (1 blind hunk of 8) UP to 1.0, hiding the blind rewrite
    # behind a perfect headline. Flooring guarantees any blind rewrite drops the
    # score strictly below 1.0, and leaves exact quarters (0.0/.25/.5/.75/1.0)
    # untouched -- the number never rounds a real defect away.
    return math.floor(value * 4) / 4


def _minimality_grade_hunks(
    hunks: list[list[str]],
    add_file_lines: int,
    count: int,
    is_error: bool | None,
) -> DiffMinimalityScore:
    blind_flags = [_minimality_hunk_is_blind(hunk) for hunk in hunks]
    blind = sum(blind_flags)
    total = len(hunks)

    violations = tuple(
        f"blind block rewrite in hunk {i}: >= FLOOR={FLOOR} consecutive '-' lines "
        f"retyped as '+' with no anchor retained"
        for i, flag in enumerate(blind_flags)
        if flag
    )

    densities = [
        d
        for d in (_minimality_context_density(hunk) for hunk in hunks)
        if d is not None
    ]
    mean_density = sum(densities) / len(densities) if densities else None

    score = _minimality_floor_quarter(1 - blind / total)
    return DiffMinimalityScore(
        score=score,
        applicable=True,
        blind_rewrite_hunks=blind,
        hunks_with_body=total,
        violations=violations,
        mean_context_density=mean_density,
        add_file_lines=add_file_lines,
        apply_patch_call_count=count,
        cline_apply_is_error=is_error,
    )
