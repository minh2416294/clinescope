"""Apply-coherence diff-quality scorer (deterministic, zero-LLM).

The criterion-2 wedge: the diff-quality scorer no general eval framework ships.
It reads a loaded :class:`~clinescope.world_a.Trace`, finds the ``apply_patch``
tool call, and grades the coherence of the patch text against Cline's REAL
``apply_patch`` grammar -- the ``*** Begin Patch`` envelope, NOT a unified diff.

    score = (G3 + G4 + G5 + G6) / 4   (or a hard 0.0, see below)

**What "coherence" means here (the honesty caveat -- read this).**
This is GRAMMAR coherence decidable from the patch TEXT ALONE, NOT
apply-against-real-file success. Cline's real executor also fuzzy-matches each
hunk's context against the on-disk file (Levenshtein similarity), which a
standalone trace cannot reproduce -- there is no repo checkout to match against.
So a patch can score 1.0 here and still fail Cline's executor because its context
does not locate in the target file. The report labels this ``[diff_coherence]``,
never ``apply_success``. (Mirrors the charter's "scores are glued to the setup".)

**Deliberate decisions (each a stated choice, not undefined behaviour):**

* No ``apply_patch`` call in the trace -> 0.0 (fail loud: the artifact we were
  asked to score is absent -- NOT vacuously 1.0, because something concrete is
  missing, unlike an empty ``expected`` set in tool_selection).
* Multiple ``apply_patch`` calls -> the FIRST is scored; the total count is
  surfaced on ``apply_patch_call_count``. No min/mean aggregation (speculative).
* ``apply_patch`` present but ``input`` carries no ``str`` under the key
  ``"input"`` (e.g. the fictional ``{"diff": <unified diff>}`` shape Cline never
  emits) -> 0.0 with a shape violation. This is the shape guard.
* Empty / whitespace-only patch text -> 0.0.
* Sentinels: ``*** Begin Patch`` / ``*** End Patch`` are OPTIONAL, but if one
  appears both must (Cline's executor throws "incomplete sentinels" otherwise) ->
  unbalanced sentinels are a hard 0.0. The END match uses ``startswith`` so a
  trailing-whitespace ``*** End Patch `` still balances.
* Legacy bash wrappers (``%%bash`` / ``apply_patch <<"EOF"`` / ``EOF`` / ```` ``` ````)
  are stripped before grading, but ONLY when no sentinels are present -- matching
  Cline's ``normalizePatchInput``. A wrapper token appearing as a real context
  line (`` EOF literal``) is NOT stripped (it is content, not a wrapper).
* An unknown ``***``-prefixed header, or a patch body with no action header at
  all, is a hard 0.0 (Cline throws "Unknown line while parsing").
* Selection-vs-success separation: ``tool_result.is_error`` (Cline's real
  verdict) is CONTEXT ONLY on ``cline_apply_is_error``; it NEVER enters the
  score. Keying the number on it would just parrot Cline and go undefined when
  there is no ``tool_result``. Mirrors tool_selection's "invocation, not success".

The four averaged gates (each 1.0 or 0.0, vacuously passed if its action type is
absent from the patch): G3 every ``*** Add File:`` content line starts with
``+``; G4 every ``*** Update File:`` block has >=1 ``@@`` and only
`` ``/``-``/``+``/blank content lines; G5 no content line starts with ``***``
except a recognized marker; G6 any ``*** Move to:`` sits immediately after an
``*** Update File:`` header.

The scorer is pure: no I/O, no LLM, deterministic. It reads only
``Trace.tool_calls`` (``ToolCall.name`` / ``.input`` / ``.is_error``).
"""

from __future__ import annotations

from dataclasses import dataclass

from clinescope.world_a import ToolCall, Trace

# Verbatim from cline apply-patch-parser.ts (PATCH_MARKERS / BASH_WRAPPERS).
# source: sdk/packages/core/src/extensions/tools/executors/apply-patch-parser.ts
_BEGIN = "*** Begin Patch"
_END = "*** End Patch"
_ADD = "*** Add File: "
_UPDATE = "*** Update File: "
_DELETE = "*** Delete File: "
_MOVE = "*** Move to: "
_SECTION = "@@"
_END_FILE = "*** End of File"
_BASH_WRAPPERS = ("%%bash", "apply_patch", "EOF", "```")

_ACTION_HEADERS = (_ADD, _UPDATE, _DELETE)
_KNOWN_MARKERS = (_BEGIN, _END, _ADD, _UPDATE, _DELETE, _MOVE, _END_FILE)

_AVERAGED_GATES = (
    "add_files_all_plus",
    "update_hunks_wellformed",
    "no_stray_triple_star",
    "move_placement_valid",
)


@dataclass(frozen=True, slots=True)
class DiffCoherenceScore:
    """Result of :func:`score_diff_coherence`.

    Invariants (all derived from the FIRST ``apply_patch`` call's patch text):

    * ``score`` in ``{0.0, 0.25, 0.5, 0.75, 1.0}``. It is ``0.0`` iff the patch is
      absent / mis-shaped / empty OR a hard gate (sentinels, headers) fails;
      otherwise ``len(passed_gates) / 4``.
    * ``passed_gates | failed_gates`` == the four averaged-gate names when the
      patch parses; both are empty on a hard-zero (nothing was graded).
    * ``violations`` has >=1 entry iff ``score < 1.0`` and is empty iff
      ``score == 1.0`` -- the EVIDENCE of *why*, never a silent low score. It is
      an ordered tuple (detection order; the first failure is most proximate).
    * ``apply_patch_call_count``: ``0`` => the "no call" 0.0; ``>1`` => the first
      call was the one scored.
    * ``cline_apply_is_error`` mirrors the scored call's ``tool_result.is_error``
      (``True`` / ``False`` / ``None``) -- CONTEXT ONLY, never an input to score.

    GRAMMAR coherence of the patch TEXT, NOT apply-against-real-file success (see
    the module docstring's honesty caveat).
    """

    score: float
    passed_gates: frozenset[str]
    failed_gates: frozenset[str]
    violations: tuple[str, ...]
    apply_patch_call_count: int
    cline_apply_is_error: bool | None


def score_diff_coherence(trace: Trace) -> DiffCoherenceScore:
    """Score grammar-coherence of the ``apply_patch`` patch in ``trace``.

    Args:
        trace: A loaded World-A trace; only ``trace.tool_calls`` is read.

    Raises:
        TypeError: If ``trace`` is not a :class:`~clinescope.world_a.Trace` -- most
            temptingly a raw patch ``str`` ("just score this patch text"). A bare
            string would crash cryptically deep inside, and a duck-typed object
            with a ``.tool_calls`` would silently misscore, so this misuse is
            turned into one loud, early error.
    """
    _diff_coherence_guard_trace_type(trace)

    call, count = diff_coherence_select_apply_patch(trace)
    if call is None:
        return _diff_coherence_zero(("no apply_patch tool call in trace",), 0, None)

    is_error = call.is_error
    text = diff_coherence_read_patch_text(call)
    if text is None:
        return _diff_coherence_zero(
            ('apply_patch input has no str under key "input" (bad shape)',),
            count,
            is_error,
        )
    if not text.strip():
        return _diff_coherence_zero(("empty patch text",), count, is_error)

    lines, hard_violation = diff_coherence_normalize(text)
    if hard_violation is not None:
        return _diff_coherence_zero((hard_violation,), count, is_error)

    passed, failed, violations = diff_coherence_grade_gates(lines)
    score = len(passed) / len(_AVERAGED_GATES)
    return DiffCoherenceScore(
        score=score,
        passed_gates=frozenset(passed),
        failed_gates=frozenset(failed),
        violations=tuple(violations),
        apply_patch_call_count=count,
        cline_apply_is_error=is_error,
    )


def _diff_coherence_guard_trace_type(trace: Trace) -> None:
    if not isinstance(trace, Trace):
        raise TypeError(
            f"score_diff_coherence takes a Trace, not {type(trace).__name__} "
            f"({trace!r:.60}); pass a loaded trace, not raw patch text"
        )


def _diff_coherence_zero(
    violations: tuple[str, ...], count: int, is_error: bool | None
) -> DiffCoherenceScore:
    return DiffCoherenceScore(
        score=0.0,
        passed_gates=frozenset(),
        failed_gates=frozenset(),
        violations=violations,
        apply_patch_call_count=count,
        cline_apply_is_error=is_error,
    )


def diff_coherence_select_apply_patch(trace: Trace) -> tuple[ToolCall | None, int]:
    """Return the FIRST apply_patch call (or None) and the total apply_patch count."""
    patch_calls = [call for call in trace.tool_calls if call.name == "apply_patch"]
    if not patch_calls:
        return None, 0
    return patch_calls[0], len(patch_calls)


def diff_coherence_read_patch_text(call: ToolCall) -> str | None:
    """Lift the real ``input`` string; None if the shape is wrong (e.g. {"diff": ...})."""
    value = call.input.get("input")
    return value if isinstance(value, str) else None


def diff_coherence_normalize(text: str) -> tuple[list[str], str | None]:
    """Strip wrappers, enforce sentinel balance + known headers.

    Returns the body lines to grade, or a hard-violation message (score 0.0).
    Faithfully mirrors Cline's ``normalizePatchInput``: the FIRST ``Begin`` and
    the LAST ``End`` define the sentinel pair; if either is present without the
    other, OR the End precedes the Begin, that is "incomplete sentinels". When
    sentinels are absent, bash wrappers are trimmed only at the leading/trailing
    EDGES (``trimWrapperLines``), never mid-body.
    """
    lines = [line.rstrip("\r") for line in text.split("\n")]
    begin_index = next(
        (i for i, line in enumerate(lines) if line.startswith(_BEGIN)), -1
    )
    end_index = next(
        (i for i in range(len(lines) - 1, -1, -1) if lines[i].startswith(_END)), -1
    )

    if begin_index != -1 or end_index != -1:
        if begin_index == -1 or end_index == -1 or end_index < begin_index:
            return (
                [],
                "unbalanced patch sentinels (Begin/End incomplete or out of order)",
            )
        body = lines[begin_index : end_index + 1]
    else:
        body = _diff_coherence_trim_wrapper_edges(lines)

    stray = _diff_coherence_first_unknown_header(body)
    if stray is not None:
        return [], f"unknown '***' header / marker: {stray!r}"
    if not any(_diff_coherence_action_of(line) for line in body):
        return [], "no action header (Add/Update/Delete File) in patch body"
    return body, None


def _diff_coherence_is_wrapper_line(line: str) -> bool:
    # Mirrors Cline isWrapperLine: startswith (not exact), blank lines excluded.
    if not line.strip():
        return False
    return any(line.startswith(wrapper) for wrapper in _BASH_WRAPPERS)


def _diff_coherence_trim_wrapper_edges(lines: list[str]) -> list[str]:
    # Mirrors Cline trimWrapperLines: strip contiguous wrapper lines at the
    # leading/trailing EDGES only -- an interior line is never examined.
    start = 0
    end = len(lines)
    while start < end and _diff_coherence_is_wrapper_line(lines[start]):
        start += 1
    while end > start and _diff_coherence_is_wrapper_line(lines[end - 1]):
        end -= 1
    return lines[start:end]


def _diff_coherence_action_of(line: str) -> str | None:
    for header in _ACTION_HEADERS:
        if line.startswith(header):
            return header
    return None


def _diff_coherence_first_unknown_header(lines: list[str]) -> str | None:
    for line in lines:
        if line.startswith("***") and not any(
            line.startswith(marker) for marker in _KNOWN_MARKERS
        ):
            return line
    return None


def diff_coherence_grade_gates(
    lines: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """Grade the four averaged gates; return (passed, failed, violations)."""
    checks = (
        ("add_files_all_plus", diff_coherence_check_add_plus(lines)),
        ("update_hunks_wellformed", diff_coherence_check_update_hunks(lines)),
        ("no_stray_triple_star", diff_coherence_check_stray_triple_star(lines)),
        ("move_placement_valid", diff_coherence_check_move_placement(lines)),
    )
    passed: list[str] = []
    failed: list[str] = []
    violations: list[str] = []
    for gate, violation in checks:
        if violation is None:
            passed.append(gate)
        else:
            failed.append(gate)
            violations.append(violation)
    return passed, failed, violations


def diff_coherence_check_add_plus(lines: list[str]) -> str | None:
    """G3: every content line inside an Add File block must start with '+'."""
    in_add = False
    for line in lines:
        action = _diff_coherence_action_of(line)
        if action is not None:
            in_add = action == _ADD
            continue
        if line.startswith(_BEGIN) or line.startswith(_END) or line == _END_FILE:
            in_add = False
            continue
        if in_add and line and not line.startswith("+"):
            return f"Add File content line missing '+': {line!r}"
    return None


def diff_coherence_check_update_hunks(lines: list[str]) -> str | None:
    """G4: every Update File block has >=1 '@@' and only space/-/+/blank content."""
    in_update = False
    saw_section = False
    for line in lines:
        action = _diff_coherence_action_of(line)
        if action is not None:
            if in_update and not saw_section:
                return "Update File block has no '@@' section marker"
            in_update = action == _UPDATE
            saw_section = False
            continue
        if line.startswith(_BEGIN) or line.startswith(_END):
            if in_update and not saw_section:
                return "Update File block has no '@@' section marker"
            in_update = False
            continue
        if not in_update:
            continue
        if line.startswith(_SECTION):
            saw_section = True
            continue
        if line.startswith(_MOVE):
            continue
        if line and line[0] not in (" ", "-", "+"):
            return f"Update File content line has no diff prefix: {line!r}"
    if in_update and not saw_section:
        return "Update File block has no '@@' section marker"
    return None


def diff_coherence_check_stray_triple_star(lines: list[str]) -> str | None:
    """G5: no content line starts with '***' unless it is a known marker."""
    stray = _diff_coherence_first_unknown_header(lines)
    return None if stray is None else f"stray '***' line: {stray!r}"


def diff_coherence_check_move_placement(lines: list[str]) -> str | None:
    """G6: a Move header must sit immediately after an Update File header."""
    prev_was_update = False
    for line in lines:
        if line.startswith(_MOVE) and not prev_was_update:
            return (
                f"'*** Move to:' not immediately after an Update File header: {line!r}"
            )
        prev_was_update = line.startswith(_UPDATE)
    return None
