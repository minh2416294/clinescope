"""Gold-set format + loader for judge validation (κ-arc segment 2).

The gold set is the small HUMAN-labeled corpus a judge is validated against: for
each item a human answers "is this patch WASTEFUL?", the judge answers the same,
and :func:`clinescope.agreement.cohen_kappa` reports their chance-corrected
agreement. This module owns the FORMAT (a committed JSONL contract under ``gold/``)
and the LOADER (parse + resolve each item to the exact apply_patch the scorer grades).

It is the seam only -- it does NOT call a judge, does NOT compute κ, and does NOT
ship any human labels (those are the user's own, added in a later segment; a
seed committed here is deliberately UNLABELED, ``label: null``).

**The format (one JSON object per line in ``gold/<dimension>.gold.jsonl``):**

* ``schema_version`` (int) -- bumped when the field set changes (e.g. a future
  per-call granularity would be a new version, never a silent retrofit).
* ``item_id`` (str) -- stable, human-assigned; rides along for debugging a
  misalignment, never fed to κ (which is positional).
* ``dimension`` (str) -- the scorer this gold set validates ("diff_minimality").
* ``source`` (``{"trace": <repo-relative path>}``) -- a POINTER to a trace, NOT the
  patch text and NOT a ``tool_use_id``. **The pointer is deliberately trace-only,
  never id-keyed:** the scorers select the FIRST apply_patch by scan order and never
  read ``tool_use_id``, so an id-keyed pointer could silently disagree with the
  scorer on a multi-apply_patch trace and mislabel it. The loader resolves to the
  same first call the scorer grades and surfaces the total count.
* ``label`` (``"WASTEFUL"`` | ``"NOT-WASTEFUL"`` | ``null``) -- the human's holistic
  verdict; ``null`` = unlabeled (a seed placeholder).
* ``labeler`` / ``labeled_at`` (str | null) -- provenance of a real label.
* ``notes`` (str) -- free text.
* ``patch_sha256`` (str | null) -- an OPTIONAL drift tripwire: the sha256 of the
  lifted patch text of the first apply_patch. When present it is verified at resolve
  time and fails loud on drift, so a committed trace edit can never silently
  invalidate a label. Preimage = ``sha256(read_patch_text(first_call).encode())`` --
  the lifted patch STRING, not the raw JSON line (mirrors the R4 fixture-drift guard).

**Granularity = one label per TRACE, applied to the first apply_patch** -- matching
the scorer's own scope (``score_diff_coherence`` scores the first apply_patch and
surfaces ``apply_patch_call_count``). A per-CALL label would have no counterpart in
the scorer or in κ. See ``gold/README.md``.

**Fail loud, never skip** (surface hidden failures): a malformed JSONL line, a bad
label value, a missing trace file, a trace with no apply_patch, a first apply_patch
with no readable patch text, or a patch-hash drift each raises a specific
:class:`GoldError` subclass -- a bad pointer must never silently return a wrong item.

Reuses ``clinescope.diff_coherence`` for selecting + reading the apply_patch (no
re-implementation) so the loader and the scorer can never disagree about which call
is graded.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from clinescope.diff_coherence import (
    diff_coherence_read_patch_text,
    diff_coherence_select_apply_patch,
)
from clinescope.world_a import ToolCall, Trace, load_trace

# The holistic binary a human gold labeler answers. Must match judge.JudgeVerdict
# so a human label and a judge label are directly comparable κ inputs. ``None`` (an
# unlabeled seed) is tolerated at load; anything else is a GoldSchemaError.
GOLD_LABELS: frozenset[str] = frozenset({"WASTEFUL", "NOT-WASTEFUL"})

# The only gold-set schema this loader understands. A file written with any other
# version is a hard error, NOT parsed as v1 -- the field exists to make a field-set
# change loud, so silently accepting a future version defeats its purpose (mirrors
# world_a._world_a_check_version).
_SUPPORTED_SCHEMA_VERSION = 1

_REQUIRED_FIELDS = ("schema_version", "item_id", "dimension", "source")

# A sha256 hex digest is exactly 64 lowercase hex chars. Validated at parse time so a
# malformed pin (e.g. a truncated digest) is rejected near its line, not silently
# treated as a value that will always drift-mismatch at resolve time.
_SHA256_HEX_LEN = 64
_HEX_CHARS = frozenset("0123456789abcdef")


class GoldError(Exception):
    """Base for all gold-set loading errors."""


class GoldSchemaError(GoldError):
    """A JSONL line is malformed, a field has the wrong type, or a label is illegal."""


class GoldTraceMissingError(GoldError):
    """An item's ``source.trace`` pointer does not resolve to a file."""


class GoldNoApplyPatchError(GoldError):
    """An item's resolved trace has no apply_patch call to score."""


class GoldMalformedPatchError(GoldError):
    """The item's first apply_patch has no readable patch text (a bad-shape call).

    The scorer (``score_diff_coherence``) hard-zeros such a call; the loader must not
    hand it off as a labelable item -- a human labeler / the judge would have nothing
    to read. Keeps the loader's rejection semantics aligned with the scorer's.
    """


class GoldPatchDriftError(GoldError):
    """An item's ``patch_sha256`` does not match the resolved patch text (drift)."""


@dataclass(frozen=True, slots=True)
class GoldItem:
    """A parsed gold-set record (before its trace pointer is resolved).

    Invariants:

    * ``human_label`` is ``"WASTEFUL"`` / ``"NOT-WASTEFUL"`` / ``None`` (unlabeled).
    * ``trace_path`` is the repo-relative pointer as written in ``source.trace``;
      it is resolved against ``repo_root`` in :func:`gold_resolve_item`.
    * ``patch_sha256`` is ``None`` (no drift check) or a 64-char hex digest verified
      at resolve time against the lifted patch text.
    """

    item_id: str
    dimension: str
    trace_path: str
    human_label: str | None
    labeler: str | None
    labeled_at: str | None
    notes: str
    patch_sha256: str | None


@dataclass(frozen=True, slots=True)
class ResolvedGoldItem:
    """A gold item with its trace loaded and its scored apply_patch selected.

    Invariants:

    * ``scored_call`` is the FIRST apply_patch by scan order --
      ``diff_coherence_select_apply_patch(trace)[0]`` -- the exact call the scorer
      grades and the judge will judge.
    * ``apply_patch_call_count >= 1``. ``> 1`` means the label applies to the FIRST
      of several apply_patch calls; the count is surfaced (not hidden) so a labeler
      can never silently label a different call than the scorer graded.
    """

    item: GoldItem
    trace: Trace
    scored_call: ToolCall
    apply_patch_call_count: int


def gold_load_items(jsonl_path: str | Path, *, repo_root: Path) -> tuple[GoldItem, ...]:
    """Parse a gold JSONL file into items; fail loud on any malformed/invalid line.

    Blank / whitespace-only lines are skipped (a trailing newline is legal); any
    non-empty line that is not a well-formed gold object raises
    :class:`GoldSchemaError` naming the 1-based line number -- never silently skipped.

    Args:
        jsonl_path: Path to the ``.gold.jsonl`` file.
        repo_root: Repo root that item ``source.trace`` pointers are relative to
            (kept on the signature for symmetry with :func:`gold_resolve_item`; the
            path is not touched here, only recorded).

    Raises:
        GoldSchemaError: On a malformed line, wrong field type, or illegal label.
    """
    text = Path(jsonl_path).read_text(encoding="utf-8")
    items: list[GoldItem] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        items.append(_gold_parse_line(line, line_number))
    return tuple(items)


def _gold_parse_line(line: str, line_number: int) -> GoldItem:
    try:
        raw = json.loads(line)
    except json.JSONDecodeError as err:
        raise GoldSchemaError(
            f"gold item line {line_number}: not valid JSON ({err})"
        ) from err
    if not isinstance(raw, dict):
        raise GoldSchemaError(
            f"gold item line {line_number}: expected a JSON object, got "
            f"{type(raw).__name__}"
        )
    for field in _REQUIRED_FIELDS:
        if field not in raw:
            raise GoldSchemaError(
                f"gold item line {line_number}: missing required field {field!r}"
            )
    _gold_check_schema_version(raw, line_number)
    return GoldItem(
        item_id=_gold_require_str(raw, "item_id", line_number),
        dimension=_gold_require_str(raw, "dimension", line_number),
        trace_path=_gold_read_trace_pointer(raw, line_number),
        human_label=_gold_read_label(raw, line_number),
        labeler=_gold_optional_str(raw, "labeler", line_number),
        labeled_at=_gold_optional_str(raw, "labeled_at", line_number),
        notes=_gold_optional_str(raw, "notes", line_number) or "",
        patch_sha256=_gold_read_patch_sha256(raw, line_number),
    )


def _gold_require_str(raw: dict[str, object], field: str, line_number: int) -> str:
    value = raw.get(field)
    if not isinstance(value, str):
        raise GoldSchemaError(
            f"gold item line {line_number}: field {field!r} must be a str, got "
            f"{type(value).__name__}"
        )
    return value


def _gold_optional_str(
    raw: dict[str, object], field: str, line_number: int
) -> str | None:
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise GoldSchemaError(
            f"gold item line {line_number}: field {field!r} must be a str or null, "
            f"got {type(value).__name__}"
        )
    return value


def _gold_read_trace_pointer(raw: dict[str, object], line_number: int) -> str:
    source = raw.get("source")
    trace = source.get("trace") if isinstance(source, dict) else None
    if not isinstance(trace, str):
        raise GoldSchemaError(
            f'gold item line {line_number}: source must be {{"trace": <str path>}}'
        )
    return trace


def _gold_read_label(raw: dict[str, object], line_number: int) -> str | None:
    label = raw.get("label")
    if label is None:
        return None
    if not isinstance(label, str) or label not in GOLD_LABELS:
        raise GoldSchemaError(
            f"gold item line {line_number}: label must be one of "
            f"{sorted(GOLD_LABELS)} or null, got {label!r}"
        )
    return label


def _gold_check_schema_version(raw: dict[str, object], line_number: int) -> None:
    version = raw.get("schema_version")
    # Type-check BEFORE value: a plain `version != 1` fails OPEN on JSON `true`
    # (Python bool, an int subclass, `True == 1`) and JSON `1.0` (`1.0 == 1`), which
    # would silently admit a non-int version as if it were v1 -- the exact silent
    # retrofit this field exists to prevent. `type(version) is int` rejects bool
    # (whose type is not int) and float alike.
    if type(version) is not int or version != _SUPPORTED_SCHEMA_VERSION:
        raise GoldSchemaError(
            f"gold item line {line_number}: unsupported schema_version {version!r}; "
            f"this loader supports integer version {_SUPPORTED_SCHEMA_VERSION} only"
        )


def _gold_read_patch_sha256(raw: dict[str, object], line_number: int) -> str | None:
    value = _gold_optional_str(raw, "patch_sha256", line_number)
    if value is None:
        return None
    if len(value) != _SHA256_HEX_LEN or any(ch not in _HEX_CHARS for ch in value):
        raise GoldSchemaError(
            f"gold item line {line_number}: patch_sha256 must be a 64-char lowercase "
            f"hex sha256 digest or null, got {value!r}"
        )
    return value


def gold_resolve_item(item: GoldItem, *, repo_root: Path) -> ResolvedGoldItem:
    """Resolve an item's trace pointer to the FIRST apply_patch the scorer grades.

    Fails loud on every bad path: a missing trace, a trace with no apply_patch, a
    first apply_patch with no readable patch text, or a ``patch_sha256`` drift. Reuses
    ``diff_coherence_select_apply_patch`` + ``diff_coherence_read_patch_text`` so the
    loader and the scorer can never disagree about which call is graded or reject it.

    Raises:
        GoldTraceMissingError: ``source.trace`` does not resolve to a file.
        GoldNoApplyPatchError: The resolved trace has no apply_patch call.
        GoldMalformedPatchError: The first apply_patch has no str patch text (bad shape).
        GoldPatchDriftError: ``patch_sha256`` is set and does not match the patch text.
    """
    trace_file = (repo_root / item.trace_path).resolve()
    if not trace_file.is_file():
        raise GoldTraceMissingError(
            f"gold item {item.item_id!r}: trace not found at {item.trace_path!r}"
        )
    trace = load_trace(trace_file)
    call, count = diff_coherence_select_apply_patch(trace)
    if call is None:
        raise GoldNoApplyPatchError(
            f"gold item {item.item_id!r}: trace {item.trace_path!r} has no apply_patch "
            f"call to score"
        )
    # The scorer selects the first apply_patch by NAME, then hard-zeros it if its input
    # carries no str patch text (a bad-shape call, e.g. the fictional {"diff": ...}).
    # Lift the text here so the loader's rejection matches the scorer's: an item whose
    # first apply_patch has nothing to read is not labelable, so fail loud rather than
    # hand a labeler / the judge an empty call.
    text = diff_coherence_read_patch_text(call)
    if text is None:
        raise GoldMalformedPatchError(
            f"gold item {item.item_id!r}: first apply_patch in {item.trace_path!r} has "
            f'no str patch text under key "input" (bad shape); nothing to label'
        )
    if item.patch_sha256 is not None:
        _gold_check_patch_drift(item, text)
    return ResolvedGoldItem(
        item=item, trace=trace, scored_call=call, apply_patch_call_count=count
    )


def _gold_check_patch_drift(item: GoldItem, text: str) -> None:
    actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if actual != item.patch_sha256:
        raise GoldPatchDriftError(
            f"gold item {item.item_id!r}: first apply_patch text drifted in "
            f"{item.trace_path!r} (pinned {item.patch_sha256}, got {actual})"
        )


def gold_load_resolved(
    jsonl_path: str | Path, *, repo_root: Path
) -> tuple[ResolvedGoldItem, ...]:
    """Parse a gold JSONL file and resolve every item (parse + resolve convenience)."""
    items = gold_load_items(jsonl_path, repo_root=repo_root)
    return tuple(gold_resolve_item(item, repo_root=repo_root) for item in items)
