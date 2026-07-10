"""Apply-recovery scorer (deterministic, zero-LLM) -- the criterion-2 wedge, 3rd slice.

Sits alongside :mod:`clinescope.diff_coherence` and :mod:`clinescope.diff_minimality`.
Where those score a SINGLE patch's shape, apply-recovery scores a TRAJECTORY: of
every ``apply_patch`` call Cline marked FAILED, what fraction was later RECOVERED --
a strictly-later ``apply_patch`` that Cline CONFIRMED non-failing and that re-touches
the same edited file?

    score = confirmed_recovered_pairs / total_failed_pairs   (or None, see below)

This is the first scorer single-shot authored traces cannot fake: it needs a
multi-turn failure -> retry shape.

**What "recovery" means here (the honesty caveat -- read this).**
This measures a TRAJECTORY PATTERN -- "a strictly-later ``apply_patch`` Cline
CONFIRMED non-failing (``is_error is False``) re-touched the same file" -- NOT that
the retry actually fixed the original defect. With no repo checkout and no reference
patch, "recovered" means only: a later ``apply_patch`` on an overlapping
edit-intent file path carried ``is_error is False``, i.e. Cline's executor applied
SOME hunk to that path (the same fuzzy-match caveat :mod:`diff_coherence` states).
It does NOT verify the retry addressed the same HUNK/region (file granularity: a
later unrelated edit to the same file counts), does NOT verify semantic correctness,
and is BLIND to cross-tool recovery: an agent that abandons ``apply_patch`` and
correctly fixes the file via ``write_to_file`` / ``str_replace`` scores that failure
as UNrecovered -- a disclosed false-negative, so a LOW score means "did not recover
via a same-file confirmed apply_patch", NOT "did not recover". Literal path matching
(no case-fold, no slash/relative normalization) false-MISSES the same file spelled
differently. It is deliberately CONSERVATIVE on missing verdicts: a later same-file
retry with ``is_error is None`` (no ``tool_result`` -- a truncated trace) is NOT
scored as recovery, only surfaced on ``unverified_reattempt_pairs``, so the number
can never be inflated by truncating the log. A HIGH score means "failed patches were
re-attempted on the same files and Cline confirmed those re-attempts applied", NOT
"the agent successfully fixed what it broke". Glued to the trace, like every sibling.

**Deliberate decisions (each a stated choice, not undefined behaviour):**

* The VERDICT is the oracle here (unlike the two siblings, which read outcome as
  context only). Apply-recovery is *about* the failure/success verdict, so the score
  reads an EFFECTIVE verdict per call -- ``True`` (failure), ``False`` (confirmed
  success), or ``None`` (a THIRD state: neither failure nor confirmed success).
* The effective verdict is resolved with ``is_error`` AUTHORITATIVE, then a SECONDARY
  ``"success"``-JSON oracle (:func:`_recovery_effective_verdict`): (1) if the loader
  gave a real ``bool`` ``is_error``, use it (and it wins any conflict with the
  content); (2) else, because a genuine Cline ``apply_patch`` result carries NO
  ``is_error`` field and encodes the outcome as ``{...,"success":true/false}`` inside
  the tool_result content JSON (cline ``definitions.ts`` + ``agent-message-codec.ts``),
  read that ``"success"`` bool from a ``str`` content (``not success`` -> the
  ``is_error`` polarity); (3) else ``None``. Without the oracle the scorer abstained on
  every real trace (the Day-10 gap); the oracle is what lets it score genuine runs.
* Recovery requires an effective verdict of ``False`` (Cline-confirmed OR
  ``"success":true``), NOT merely ``is not True``. Admitting ``None`` would let an
  adversary max the score by truncating the trace right after any re-attempt (``None``
  == "no verdict", not "it worked"). The oracle NEVER weakens this: a truncated trace
  loses the tool_result content too, so the ``"success"`` read fails closed to ``None``
  -- the content JSON is written atomically with the result, so a readable ``"success"``
  means the apply actually finished.
* Same-target = literal edit-intent file path. ``targets(call)`` = the paths on
  ``*** Update File:`` and ``*** Add File:`` headers, plus the ``*** Move to:``
  DESTINATION. It EXCLUDES ``*** Delete File:`` paths and the Move SOURCE: re-deleting
  a named file, or touching a file's pre-rename name, is not evidence the failed
  EDIT was re-applied. Paths matched literally (rstrip only), no normalization.
* Scored per failed FILE, not per failed CALL: a call failing on ``{a.py, b.py}``
  contributes 2 pairs; fixing only ``a.py`` scores 0.5 (no laundering a half-fix into
  a full 1.0). ``partially_recovered_failures`` surfaces such calls.
* An UNPARSEABLE failed patch (grammar-broken, so ``targets`` is empty) still counts:
  it contributes ONE ``<unparseable>`` sentinel pair that can never be recovered --
  failing illegibly cannot drop the failure out of the denominator.
* Vacuous case: no failed pair -> ``score=None``, ``applicable=False``. A recovery
  rate is undefined when nothing failed; ``1.0`` would falsely headline flawless
  recovery, ``0.0`` would falsely accuse a clean run. ``verdict_coverage`` splits the
  two honest sub-cases: ``> 0`` = a genuine clean run (EFFECTIVE verdicts present, none
  failed); ``== 0`` = every ``apply_patch`` has a ``None`` effective verdict (neither
  ``is_error`` nor a readable ``"success"`` -- a truncated export) -- surfaced with a
  distinct reason so an evidence gap is never laundered into "nothing failed".

The scorer is pure: no I/O, no LLM, deterministic. It reads only ``Trace.tool_calls``
and reuses the coherence sibling's grammar parser.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from clinescope.diff_coherence import (
    diff_coherence_normalize,
    diff_coherence_read_patch_text,
)
from clinescope.world_a import ToolCall, Trace

# The key inside an apply_patch tool_result's JSON-string content that carries the
# outcome (source: cline definitions.ts createApplyPatchTool -> {query, result,
# [error], success}). The SECONDARY oracle reads this when is_error is absent.
_SUCCESS_KEY = "success"

# Reused verbatim from cline apply-patch-parser.ts markers (see diff_coherence).
# Matched WITH the trailing ": " so "*** End of File" / "*** Begin Patch" etc.
# never mis-extract as a file path.
_UPDATE = "*** Update File: "
_ADD = "*** Add File: "
_MOVE = "*** Move to: "

# Sentinel path for a failed patch whose grammar could not be parsed (no real path
# is extractable, but the failure must still count in the denominator).
_UNPARSEABLE = "<unparseable>"


@dataclass(frozen=True, slots=True)
class ApplyRecoveryScore:
    """Result of :func:`score_apply_recovery`.

    Invariants:

    * ``applicable`` is ``False`` iff no ``apply_patch`` call has an EFFECTIVE verdict
      of ``True`` (nothing failed); then ``score is None`` and the vacuous split is read
      from ``verdict_coverage`` (``> 0`` clean run vs ``== 0`` no verdicts joined). The
      effective verdict is ``is_error`` when present, else the ``"success"``-JSON oracle
      (see the module docstring / :func:`_recovery_effective_verdict`).
    * Otherwise ``score = confirmed_recovered_pairs / total_failed_pairs`` in
      ``[0.0, 1.0]``. It is ``1.0`` iff every failed (call, file) pair was recovered.
    * ``total_failed_pairs`` counts EACH failed file of EACH failed call; an
      unparseable failed call contributes exactly one (unrecoverable) sentinel pair.
    * ``confirmed_recovered_pairs + unrecovered_pairs == total_failed_pairs``.
    * ``partially_recovered_failures`` = failed CALLS with some-but-not-all files
      recovered. ``same_file_refail_count`` = failed pairs that later re-failed on the
      same file (brute-force visibility). ``unverified_reattempt_pairs`` = failed
      pairs with a later same-file ``apply_patch`` whose verdict is ``None`` (a
      re-attempt with no confirmed outcome -- never scored as recovery). These three
      counters are INDEPENDENT existentials, NOT a partition: a pair can be recovered
      (a later ``is_error is False`` exists) AND also have an intervening ``None``
      reattempt, so it counts in both ``confirmed_recovered_pairs`` and
      ``unverified_reattempt_pairs``. Only ``recovered + unrecovered`` partitions.
    * ``recovery_pairs`` = one ``(failed_call_index, fixer_call_index, path)`` triple
      per recovered pair, naming the FIRST later confirmed call that re-touched the
      file -- evidence a reader can scan for a large index gap (a distant, unrelated
      later success that inflated the number -- the disclosed residual risk).
    * ``verdict_coverage`` = fraction of ``apply_patch`` calls carrying a non-``None``
      EFFECTIVE verdict (``is_error`` or the ``"success"`` oracle); ``None`` when there
      are no ``apply_patch`` calls at all.
    * ``violations`` has >=1 entry iff there is an unrecovered pair OR a vacuous
      evidence gap; ordered (detection order).
    * ``cline_apply_is_error`` mirrors the FIRST ``apply_patch`` call's RAW
      ``tool_result.is_error`` (``None`` when the trace has no ``is_error`` field, as
      real Cline apply_patch results do) -- context parity with the sibling scorers,
      which also mirror the raw verdict. This is NOT the oracle-resolved verdict: the
      SCORE reads the effective verdict of every call, the CONTEXT field stays raw.

    Measures a TRAJECTORY PATTERN (same-file confirmed re-attempt), NOT that the
    retry fixed the defect (see the module docstring's honesty caveat).
    """

    score: float | None
    applicable: bool
    total_failed_pairs: int
    confirmed_recovered_pairs: int
    unrecovered_pairs: int
    partially_recovered_failures: int
    same_file_refail_count: int
    unverified_reattempt_pairs: int
    verdict_coverage: float | None
    failed_target_paths: tuple[str, ...]
    recovery_pairs: tuple[tuple[int, int, str], ...]
    unparseable_failed_calls: int
    apply_patch_call_count: int
    violations: tuple[str, ...]
    cline_apply_is_error: bool | None


@dataclass(frozen=True, slots=True)
class _ApplyPatchView:
    """One apply_patch call reduced to what the recovery scorer reads.

    ``is_error`` is the EFFECTIVE verdict the score reads: the loader-level
    ``ToolCall.is_error`` when it is a real bool, else the ``"success"`` oracle's
    reading of the tool_result content (``None`` when neither resolves). ``raw_is_error``
    is the untouched loader verdict -- surfaced ONLY on ``cline_apply_is_error`` for
    context parity with the sibling scorers, never read by the score.
    """

    index: int
    is_error: bool | None
    raw_is_error: bool | None
    targets: frozenset[str]
    unparseable: bool


def score_apply_recovery(trace: Trace) -> ApplyRecoveryScore:
    """Score failure->retry recovery of the ``apply_patch`` calls in ``trace``.

    Args:
        trace: A loaded World-A trace; only ``trace.tool_calls`` is read.

    Raises:
        TypeError: If ``trace`` is not a :class:`~clinescope.world_a.Trace` -- most
            temptingly a raw patch ``str``. Turned into one loud early error rather
            than a cryptic crash or a silently-wrong score on a duck-typed object.
    """
    if not isinstance(trace, Trace):
        raise TypeError(
            f"score_apply_recovery takes a Trace, not {type(trace).__name__} "
            f"({trace!r:.60}); pass a loaded trace, not raw patch text"
        )

    views = _recovery_apply_patch_views(trace)
    if not views:
        return _recovery_not_applicable(apply_patch_call_count=0, verdict_coverage=None)

    verdict_coverage = _recovery_verdict_coverage(views)
    failures = _recovery_failed_pairs(views)
    if not failures:
        return _recovery_vacuous(
            apply_patch_call_count=len(views), verdict_coverage=verdict_coverage
        )

    return _recovery_grade(views, failures, verdict_coverage)


def _recovery_apply_patch_views(trace: Trace) -> list[_ApplyPatchView]:
    """All apply_patch calls, in chronological (index) order, reduced to a view."""
    views: list[_ApplyPatchView] = []
    for index, call in enumerate(trace.tool_calls):
        if call.name != "apply_patch":
            continue
        targets, unparseable = _recovery_targets(call)
        views.append(
            _ApplyPatchView(
                index=index,
                is_error=_recovery_effective_verdict(call),
                raw_is_error=call.is_error,
                targets=targets,
                unparseable=unparseable,
            )
        )
    return views


def _recovery_effective_verdict(call: ToolCall) -> bool | None:
    """The effective failure/success verdict of one apply_patch call.

    Precedence, is_error AUTHORITATIVE:

    1. If ``call.is_error`` is a real ``bool`` -> return it directly (Cline's
       loader-level verdict wins; it also wins any conflict with the content).
    2. Else read the SECONDARY oracle: a genuine Cline apply_patch result carries
       NO ``is_error`` field, so the loader gives ``None``; the outcome lives inside
       the tool_result CONTENT as a JSON string ``{...,"success":true/false}``
       (source: cline definitions.ts + agent-message-codec.ts). If ``result_content``
       is a ``str`` that parses to a ``dict`` with a real ``bool`` ``"success"``,
       return ``not success`` (success -> non-failing verdict ``False``; failure ->
       failing verdict ``True``), matching the ``is_error`` polarity.
    3. Else -> ``None`` (abstain). Fails CLOSED on non-str/list content, invalid or
       truncated JSON, non-dict JSON, a missing/``null``/non-``bool`` ``"success"``.
       Abstaining can only ever UNDER-count recovery (the numerator needs a confirmed
       ``False``), never inflate it -- preserving the anti-truncation guarantee.
    """
    if isinstance(call.is_error, bool):
        return call.is_error

    content = call.result_content
    if not isinstance(content, str):
        return None
    try:
        parsed = json.loads(content)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    success = parsed.get(_SUCCESS_KEY)
    if not isinstance(success, bool):
        return None
    return not success


def _recovery_targets(call: ToolCall) -> tuple[frozenset[str], bool]:
    """Edit-intent target paths of one apply_patch call, and whether it's unparseable.

    Returns ``(paths, unparseable)``. ``paths`` = Update/Add File paths + Move-to
    DESTINATION (Delete paths and the Move SOURCE excluded). ``unparseable`` is True
    when the patch text is absent/mis-shaped or fails the grammar parser (then
    ``paths`` is empty).
    """
    text = diff_coherence_read_patch_text(call)
    if text is None or not text.strip():
        return frozenset(), True

    lines, hard_violation = diff_coherence_normalize(text)
    if hard_violation is not None:
        return frozenset(), True

    return _recovery_extract_targets(lines), False


def _recovery_extract_targets(lines: list[str]) -> frozenset[str]:
    """Edit-intent target paths from parsed patch body lines.

    ``*** Add File:`` and ``*** Move to:`` destinations are always targets. An
    ``*** Update File:`` path is a target ONLY when it is NOT immediately renamed:
    if the next header line is a ``*** Move to:`` (Cline's grammar attaches a Move to
    the immediately-preceding Update), that Update path is the move SOURCE -- excluded
    -- and only the Move destination counts. ``*** Delete File:`` paths are excluded.
    """
    paths: set[str] = set()
    for i, line in enumerate(lines):
        if line.startswith(_ADD):
            paths.add(line[len(_ADD) :].rstrip())
        elif line.startswith(_MOVE):
            paths.add(line[len(_MOVE) :].rstrip())
        elif line.startswith(_UPDATE) and not _recovery_next_is_move(lines, i):
            paths.add(line[len(_UPDATE) :].rstrip())
    return frozenset(paths)


def _recovery_next_is_move(lines: list[str], update_index: int) -> bool:
    """True iff the line IMMEDIATELY after ``lines[update_index]`` is a ``*** Move to:``.

    Mirrors Cline's parser (``apply-patch-parser.ts``), which consumes a Move ONLY as
    ``lines[index+1]`` right after an Update header -- ``@@`` / content / a blank line
    never sits between them. A blank line between the Update and Move headers is out of
    Cline's grammar (its parser rejects it), and clinescope's own ``diff_coherence``
    flags that shape as malformed (the ``move_placement_valid`` gate fails, dropping the
    coherence score). So this deliberately checks the immediate next line, not the next
    non-blank one: a blank-separated Move is not a valid rename, so the preceding Update
    path is a genuine edit target, not a renamed-away source. (Reviewed 2026-07-11.)
    """
    nxt = update_index + 1
    return nxt < len(lines) and lines[nxt].startswith(_MOVE)


def _recovery_verdict_coverage(views: list[_ApplyPatchView]) -> float:
    with_verdict = sum(1 for view in views if view.is_error is not None)
    return with_verdict / len(views)


def _recovery_failed_pairs(views: list[_ApplyPatchView]) -> list[tuple[int, str]]:
    """Every (call_index, path) failed pair, one per edit-intent file of each failed
    call; an unparseable failed call contributes one ``<unparseable>`` sentinel pair."""
    failures: list[tuple[int, str]] = []
    for view in views:
        if view.is_error is not True:
            continue
        if view.unparseable or not view.targets:
            failures.append((view.index, _UNPARSEABLE))
        else:
            failures.extend((view.index, path) for path in sorted(view.targets))
    return failures


def _recovery_grade(
    views: list[_ApplyPatchView],
    failures: list[tuple[int, str]],
    verdict_coverage: float,
) -> ApplyRecoveryScore:
    recovered_flags = [
        _recovery_pair_is_recovered(index, path, views) for index, path in failures
    ]
    recovered = sum(recovered_flags)
    total = len(failures)

    recovery_pairs = tuple(
        (fail_index, _recovery_first_fixer(fail_index, path, views), path)
        for (fail_index, path), flag in zip(failures, recovered_flags)
        if flag
    )
    violations = tuple(
        f"unrecovered apply_patch failure: file {path!r} failed at call {fail_index} "
        f"and no later confirmed apply_patch re-touched it"
        for (fail_index, path), flag in zip(failures, recovered_flags)
        if not flag
    )

    return ApplyRecoveryScore(
        score=recovered / total,
        applicable=True,
        total_failed_pairs=total,
        confirmed_recovered_pairs=recovered,
        unrecovered_pairs=total - recovered,
        partially_recovered_failures=_recovery_partial_calls(failures, recovered_flags),
        same_file_refail_count=_recovery_refail_count(failures, views),
        unverified_reattempt_pairs=_recovery_unverified_count(failures, views),
        verdict_coverage=verdict_coverage,
        failed_target_paths=tuple(sorted({path for _, path in failures})),
        recovery_pairs=recovery_pairs,
        unparseable_failed_calls=sum(
            1
            for view in views
            if view.is_error is True and (view.unparseable or not view.targets)
        ),
        apply_patch_call_count=len(views),
        violations=violations,
        # RAW first-call verdict (parity with the sibling scorers' context field),
        # NOT the effective/oracle-resolved verdict the score reads.
        cline_apply_is_error=views[0].raw_is_error,
    )


def _recovery_pair_is_recovered(
    fail_index: int, path: str, views: list[_ApplyPatchView]
) -> bool:
    """True iff a strictly-later confirmed (is_error is False) call re-touches path.

    An unparseable failure (sentinel path) can never be recovered.
    """
    if path == _UNPARSEABLE:
        return False
    return any(
        view.index > fail_index and view.is_error is False and path in view.targets
        for view in views
    )


def _recovery_first_fixer(
    fail_index: int, path: str, views: list[_ApplyPatchView]
) -> int:
    """Index of the FIRST later confirmed call that re-touched path (for evidence)."""
    for view in views:
        if view.index > fail_index and view.is_error is False and path in view.targets:
            return view.index
    return -1


def _recovery_partial_calls(
    failures: list[tuple[int, str]], recovered_flags: list[bool]
) -> int:
    """Count failed CALLS with some-but-not-all of their files recovered."""
    by_call: dict[int, list[bool]] = {}
    for (fail_index, _), flag in zip(failures, recovered_flags):
        by_call.setdefault(fail_index, []).append(flag)
    return sum(1 for flags in by_call.values() if any(flags) and not all(flags))


def _recovery_refail_count(
    failures: list[tuple[int, str]], views: list[_ApplyPatchView]
) -> int:
    """Count failed pairs whose file failed AGAIN on a strictly-later call."""
    return sum(
        1
        for fail_index, path in failures
        if path != _UNPARSEABLE
        and any(
            view.index > fail_index and view.is_error is True and path in view.targets
            for view in views
        )
    )


def _recovery_unverified_count(
    failures: list[tuple[int, str]], views: list[_ApplyPatchView]
) -> int:
    """Count failed pairs with a later same-file re-attempt whose verdict is None.

    These are NOT recoveries (no confirmed success), only surfaced so a truncated
    trace's re-attempts are visible instead of silently ignored.
    """
    return sum(
        1
        for fail_index, path in failures
        if path != _UNPARSEABLE
        and any(
            view.index > fail_index and view.is_error is None and path in view.targets
            for view in views
        )
    )


def _recovery_not_applicable(
    *, apply_patch_call_count: int, verdict_coverage: float | None
) -> ApplyRecoveryScore:
    return ApplyRecoveryScore(
        score=None,
        applicable=False,
        total_failed_pairs=0,
        confirmed_recovered_pairs=0,
        unrecovered_pairs=0,
        partially_recovered_failures=0,
        same_file_refail_count=0,
        unverified_reattempt_pairs=0,
        verdict_coverage=verdict_coverage,
        failed_target_paths=(),
        recovery_pairs=(),
        unparseable_failed_calls=0,
        apply_patch_call_count=apply_patch_call_count,
        violations=("no apply_patch tool call in trace",),
        cline_apply_is_error=None,
    )


def _recovery_vacuous(
    *, apply_patch_call_count: int, verdict_coverage: float
) -> ApplyRecoveryScore:
    """No failed apply_patch: recovery rate undefined. Split clean-run vs no-verdicts."""
    if verdict_coverage == 0.0:
        violations: tuple[str, ...] = (
            "no apply_patch verdicts joined (all is_error None -- a truncated export); "
            "cannot tell a clean run from an unverified one",
        )
    else:
        violations = ()
    return ApplyRecoveryScore(
        score=None,
        applicable=False,
        total_failed_pairs=0,
        confirmed_recovered_pairs=0,
        unrecovered_pairs=0,
        partially_recovered_failures=0,
        same_file_refail_count=0,
        unverified_reattempt_pairs=0,
        verdict_coverage=verdict_coverage,
        failed_target_paths=(),
        recovery_pairs=(),
        unparseable_failed_calls=0,
        apply_patch_call_count=apply_patch_call_count,
        violations=violations,
        cline_apply_is_error=None,
    )
