"""Editor-recovery scorer (deterministic, zero-LLM) -- the editor-family trajectory slice.

The :mod:`clinescope.apply_recovery` sibling ported to Cline's ``editor`` tool. Of
every ``editor`` call Cline marked FAILED, what fraction was later RECOVERED -- a
strictly-later ``editor`` call Cline CONFIRMED non-failing that re-touches the same
file path?

    score = confirmed_recovered_pairs / total_failed_pairs   (or None, see below)

Why it exists: almost no Cline session emits ``apply_patch`` any more. All five tool
presets set ``enableApplyPatch: false``, and only two routing rules flip a session
back to it (an ``openai-native`` provider, or a model id containing ``codex`` or
``gpt``), both of which also require ``act`` mode. Everything else gets ``editor``,
where all three ``apply_patch`` scorers go silent.

**What "recovery" means here (the honesty caveat -- read this).**
This measures a TRAJECTORY PATTERN -- "a strictly-later ``editor`` call Cline
CONFIRMED non-failing re-touched the same path" -- NOT that the retry actually fixed
anything. It does NOT verify the retry addressed the same region of the file, does
NOT verify semantic correctness, and is BLIND to cross-tool recovery: an agent that
abandons ``editor`` and fixes the file with ``run_commands`` scores that failure as
UNrecovered, a disclosed false negative. Path matching is LITERAL (rstrip only, no
case-fold, no separator normalisation), so the same file spelled two ways is a false
miss -- and on Windows that is a live risk, because the same file reached through Git
Bash arrives as ``/c/Users/...`` and through PowerShell as ``C:\\Users\\...``. A LOW
score means "did not recover via a same-path confirmed editor call", NOT "did not
recover".

**Two differences from the ``apply_patch`` sibling, and nothing else:**

* The target is read straight off ``input["path"]``. An editor call names its file
  directly, so there is no grammar to parse and no Update/Add/Move/Delete
  edit-intent rule to apply.
* There is NO ``partially_recovered_failures`` counter. One editor call touches
  exactly ONE path, so a call can never be half-recovered; the sibling needs that
  counter only because one patch can span several files.

**Deliberate decisions (each a stated choice, not undefined behaviour):**

* The VERDICT is the oracle, resolved by the shared
  :func:`clinescope.tool_verdict.tool_verdict_effective`: ``is_error`` when the
  loader gave a real bool, else the ``"success"`` JSON read of the tool_result
  content. A real captured Cline editor result carries NO ``is_error`` field and
  encodes the outcome as ``{"query":"edit:<path>",...,"success":false}``, so without
  the secondary read this scorer would abstain on every genuine trace.
* Recovery requires an effective verdict of ``False`` (Cline-confirmed), NOT merely
  ``is not True``. Admitting ``None`` would let an adversary max the score by
  truncating the trace right after any re-attempt.
* A failed call with no usable ``path`` (absent, non-``str``, or empty) still counts:
  it contributes ONE ``<no path>`` sentinel pair that can never be recovered. Failing
  illegibly must not drop a failure out of the denominator.
* Vacuous case: no failed call -> ``score=None``, ``applicable=False``.
  ``verdict_coverage`` splits the two honest sub-cases: ``> 0`` = a genuine clean run,
  ``== 0`` = no verdict could be resolved for any call (a truncated export), surfaced
  with its own violation so an evidence gap is never laundered into "nothing failed".

The scorer is pure: no I/O, no LLM, deterministic. It reads only ``Trace.tool_calls``.
"""

from __future__ import annotations

from dataclasses import dataclass

from clinescope.tool_verdict import tool_verdict_effective
from clinescope.world_a import ToolCall, Trace

# Sentinel for a failed editor call carrying no usable path. A real path can never
# collide with it, and it is deliberately unrecoverable.
_PATHLESS = "<no path>"


@dataclass(frozen=True, slots=True)
class EditorRecoveryScore:
    """Result of :func:`score_editor_recovery`.

    Invariants:

    * ``applicable`` is ``False`` iff no ``editor`` call has an effective verdict of
      ``True`` (nothing failed); then ``score is None`` and the vacuous split is read
      from ``verdict_coverage`` (``> 0`` clean run vs ``== 0`` no verdicts joined).
    * Otherwise ``score = confirmed_recovered_pairs / total_failed_pairs`` in
      ``[0.0, 1.0]``, and it is ``1.0`` iff every failed pair was recovered.
    * ``confirmed_recovered_pairs + unrecovered_pairs == total_failed_pairs``. These
      two partition the failures; the counters below do NOT.
    * ``same_file_refail_count`` = failed pairs whose path failed AGAIN strictly
      later. ``unverified_reattempt_pairs`` = failed pairs with a strictly-later
      same-path call whose verdict is ``None`` (never scored as recovery). Both are
      INDEPENDENT existentials: a pair can be recovered AND also have an intervening
      verdictless re-attempt, so it counts in both.
    * ``recovery_pairs`` = one ``(failed_index, fixer_index, path)`` triple per
      recovered pair, naming the FIRST later confirmed call that re-touched the path.
      A large index gap is the reader's evidence that the "fix" may be a distant,
      unrelated later edit -- the disclosed residual risk.
    * ``verdict_coverage`` = fraction of ``editor`` calls with a non-``None``
      effective verdict; ``None`` when there are no editor calls at all.
    * ``cline_editor_is_error`` mirrors the FIRST editor call's RAW
      ``tool_result.is_error`` (``None`` on a real trace, which carries no such
      field) -- context parity with the sibling scorers. This is NOT the
      oracle-resolved verdict the score reads.

    Measures a TRAJECTORY PATTERN, NOT that the retry fixed anything (see the module
    docstring's honesty caveat).
    """

    score: float | None
    applicable: bool
    total_failed_pairs: int
    confirmed_recovered_pairs: int
    unrecovered_pairs: int
    same_file_refail_count: int
    unverified_reattempt_pairs: int
    verdict_coverage: float | None
    failed_target_paths: tuple[str, ...]
    recovery_pairs: tuple[tuple[int, int, str], ...]
    pathless_failed_calls: int
    editor_call_count: int
    violations: tuple[str, ...]
    cline_editor_is_error: bool | None


@dataclass(frozen=True, slots=True)
class _EditorView:
    """One editor call reduced to what the recovery scorer reads.

    ``is_error`` is the EFFECTIVE verdict (the shared oracle); ``raw_is_error`` is the
    untouched loader verdict, surfaced only on ``cline_editor_is_error``. ``path`` is
    the ``<no path>`` sentinel when the call named no usable file.
    """

    index: int
    is_error: bool | None
    raw_is_error: bool | None
    path: str


def score_editor_recovery(trace: Trace) -> EditorRecoveryScore:
    """Score failure-to-retry recovery of the ``editor`` calls in ``trace``.

    Args:
        trace: A loaded World-A trace; only ``trace.tool_calls`` is read.

    Raises:
        TypeError: If ``trace`` is not a :class:`~clinescope.world_a.Trace` -- most
            temptingly a raw ``str``. Turned into one loud early error rather than a
            cryptic crash or a silently-wrong score on a duck-typed object.
    """
    if not isinstance(trace, Trace):
        raise TypeError(
            f"score_editor_recovery takes a Trace, not {type(trace).__name__} "
            f"({trace!r:.60}); pass a loaded trace, not raw text"
        )

    views = _editor_views(trace)
    if not views:
        return _editor_not_applicable()

    coverage = _editor_verdict_coverage(views)
    failures = _editor_failed_pairs(views)
    if not failures:
        return _editor_vacuous(editor_call_count=len(views), verdict_coverage=coverage)

    return _editor_grade(views, failures, coverage)


def _editor_views(trace: Trace) -> list[_EditorView]:
    """All editor calls, in chronological (index) order, reduced to a view."""
    views: list[_EditorView] = []
    for index, call in enumerate(trace.tool_calls):
        if call.name != "editor":
            continue
        views.append(
            _EditorView(
                index=index,
                is_error=tool_verdict_effective(call),
                raw_is_error=call.is_error,
                path=_editor_target_path(call),
            )
        )
    return views


def _editor_target_path(call: ToolCall) -> str:
    """The edited file path, or the ``<no path>`` sentinel.

    Read literally off ``input["path"]`` with a trailing-whitespace strip and no
    other normalisation, matching the sibling's literal-path rule. A non-``str`` or
    empty value is a mis-shaped call, not a path.
    """
    raw = call.input.get("path")
    if not isinstance(raw, str):
        return _PATHLESS
    stripped = raw.rstrip()
    return stripped if stripped else _PATHLESS


def _editor_verdict_coverage(views: list[_EditorView]) -> float:
    with_verdict = sum(1 for view in views if view.is_error is not None)
    return with_verdict / len(views)


def _editor_failed_pairs(views: list[_EditorView]) -> list[tuple[int, str]]:
    """Every (call_index, path) failed pair, one per failed editor call."""
    return [(view.index, view.path) for view in views if view.is_error is True]


def _editor_grade(
    views: list[_EditorView],
    failures: list[tuple[int, str]],
    verdict_coverage: float,
) -> EditorRecoveryScore:
    recovered_flags = [
        _editor_pair_is_recovered(index, path, views) for index, path in failures
    ]
    recovered = sum(recovered_flags)
    total = len(failures)

    recovery_pairs = tuple(
        (fail_index, _editor_first_fixer(fail_index, path, views), path)
        for (fail_index, path), flag in zip(failures, recovered_flags)
        if flag
    )
    violations = tuple(
        f"unrecovered editor failure: file {path!r} failed at call {fail_index} "
        f"and no later confirmed editor call re-touched it"
        for (fail_index, path), flag in zip(failures, recovered_flags)
        if not flag
    )

    return EditorRecoveryScore(
        score=recovered / total,
        applicable=True,
        total_failed_pairs=total,
        confirmed_recovered_pairs=recovered,
        unrecovered_pairs=total - recovered,
        same_file_refail_count=_editor_refail_count(failures, views),
        unverified_reattempt_pairs=_editor_unverified_count(failures, views),
        verdict_coverage=verdict_coverage,
        failed_target_paths=tuple(sorted({path for _, path in failures})),
        recovery_pairs=recovery_pairs,
        pathless_failed_calls=sum(1 for _, path in failures if path == _PATHLESS),
        editor_call_count=len(views),
        violations=violations,
        # RAW first-call verdict (parity with the sibling scorers' context field),
        # NOT the effective/oracle-resolved verdict the score reads.
        cline_editor_is_error=views[0].raw_is_error,
    )


def _editor_pair_is_recovered(
    fail_index: int, path: str, views: list[_EditorView]
) -> bool:
    """True iff a strictly-later confirmed (is_error is False) call re-touches path.

    A pathless failure (sentinel) can never be recovered.
    """
    if path == _PATHLESS:
        return False
    return any(
        view.index > fail_index and view.is_error is False and view.path == path
        for view in views
    )


def _editor_first_fixer(fail_index: int, path: str, views: list[_EditorView]) -> int:
    """Index of the FIRST later confirmed call that re-touched path (for evidence)."""
    for view in views:
        if view.index > fail_index and view.is_error is False and view.path == path:
            return view.index
    return -1


def _editor_refail_count(
    failures: list[tuple[int, str]], views: list[_EditorView]
) -> int:
    """Count failed pairs whose path failed AGAIN on a strictly-later call."""
    return sum(
        1
        for fail_index, path in failures
        if path != _PATHLESS
        and any(
            view.index > fail_index and view.is_error is True and view.path == path
            for view in views
        )
    )


def _editor_unverified_count(
    failures: list[tuple[int, str]], views: list[_EditorView]
) -> int:
    """Count failed pairs with a later same-path re-attempt whose verdict is None.

    These are NOT recoveries (no confirmed success), only surfaced so a truncated
    trace's re-attempts are visible instead of silently ignored.
    """
    return sum(
        1
        for fail_index, path in failures
        if path != _PATHLESS
        and any(
            view.index > fail_index and view.is_error is None and view.path == path
            for view in views
        )
    )


def _editor_not_applicable() -> EditorRecoveryScore:
    return EditorRecoveryScore(
        score=None,
        applicable=False,
        total_failed_pairs=0,
        confirmed_recovered_pairs=0,
        unrecovered_pairs=0,
        same_file_refail_count=0,
        unverified_reattempt_pairs=0,
        verdict_coverage=None,
        failed_target_paths=(),
        recovery_pairs=(),
        pathless_failed_calls=0,
        editor_call_count=0,
        violations=("no editor tool call in trace",),
        cline_editor_is_error=None,
    )


def _editor_vacuous(
    *, editor_call_count: int, verdict_coverage: float
) -> EditorRecoveryScore:
    """No failed editor call: recovery rate undefined. Split clean-run vs no-verdicts."""
    if verdict_coverage == 0.0:
        violations: tuple[str, ...] = (
            "no editor verdicts joined (no is_error and no readable success field -- "
            "a truncated export); cannot tell a clean run from an unverified one",
        )
    else:
        violations = ()
    return EditorRecoveryScore(
        score=None,
        applicable=False,
        total_failed_pairs=0,
        confirmed_recovered_pairs=0,
        unrecovered_pairs=0,
        same_file_refail_count=0,
        unverified_reattempt_pairs=0,
        verdict_coverage=verdict_coverage,
        failed_target_paths=(),
        recovery_pairs=(),
        pathless_failed_calls=0,
        editor_call_count=editor_call_count,
        violations=violations,
        cline_editor_is_error=None,
    )
