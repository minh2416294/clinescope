"""Per-trace label schema + loader (deterministic, zero-LLM, stdlib-only).

A single JSON manifest describes, per trace, the context a multi-trace run needs
that a lone ``messages.json`` cannot carry -- most importantly the EXPECTED TOOLS
for that trace's task. ``tool_selection`` is a recall metric against a
caller-supplied expected set; across N heterogeneous traces (each a different
task) a single global ``--expected`` is meaningless, so the expected set is
attached PER TRACE here instead.

This module is the shared foundation for two features:

* ``clinescope.compare`` reads it (optionally, via ``--labels``) so each row can
  score ``tool_selection`` against that trace's own expected tools -- and shows
  ``n/a`` for any trace with no label, exactly as the single-trace CLI does when
  ``--expected`` is omitted.
* the validation corpus (``clinescope.corpus``, a later slice) extends the SAME
  :class:`TraceLabel` with expected-score / failure-label fields; the loader and
  the ``display`` / ``expected_tools`` fields stay shared.

Manifest shape (one object, trace path -> label object)::

    {
      "examples/apply-patch-trace.json": {
        "display": "gpt-oss add-file",
        "expected_tools": ["apply_patch"]
      },
      "examples/multi-op-trace.json": {}
    }

* ``display`` (optional): a human-readable row label; falls back to the trace
  filename stem when absent.
* ``expected_tools`` (optional): the tool names ``tool_selection`` should score
  against. ABSENT or ``null`` means "do not score tool_selection for this trace"
  (rendered ``n/a``, mirroring an omitted ``--expected``); an explicit ``[]`` is
  a real empty expected set (vacuously perfect recall), distinct from absent.

The loader fails LOUD on a malformed manifest (not-an-object, a non-object label
entry, a wrong field type) -- a silently-ignored bad label would score the wrong
thing, so it raises :class:`LabelError` with the offending path/key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


class LabelError(ValueError):
    """A labels manifest was malformed (bad JSON, wrong shape, or a bad field)."""


# The closed vocabularies for the corpus-superset enum fields. A typo'd value
# (e.g. "cleen" for "clean") must fail LOUD, not be silently accepted -- an item
# mislabeled "cleen" would silently skip the no-false-positive check the corpus
# exists to prove, so these are validated in the loader like any other field.
_VALID_KINDS = frozenset({"clean", "failing"})
_VALID_SOURCES = frozenset({"real", "authored"})


@dataclass(frozen=True, slots=True)
class ScorerExpectation:
    """One scorer's expected outcome for one corpus trace (all fields optional).

    * ``expected_cell`` -- the rendered ``NN/100`` / ``n/a`` string the scorer
      must produce (the primary assertion). ``None`` = do not assert the cell.
    * ``score_is_none`` -- assert the raw score is / is not ``None`` (abstention).
    * ``applicable`` -- assert the scorer's ``.applicable`` flag (diff_minimality /
      apply_recovery). ``None`` = do not assert it.

    A scorer with no expectation object at all is simply not asserted for that
    trace -- the corpus opts in per scorer.
    """

    expected_cell: str | None = None
    score_is_none: bool | None = None
    applicable: bool | None = None


@dataclass(frozen=True, slots=True)
class TraceLabel:
    """One trace's label. ``expected_tools is None`` means "skip tool_selection".

    ``expected_tools`` is a distinct three-way signal:

    * ``None`` -- no expected set given (skip tool_selection -> ``n/a``).
    * ``()`` -- an explicit empty expected set (vacuous perfect recall).
    * a non-empty tuple -- the tool names to score recall against.

    The remaining fields are the CORPUS superset (all default to empty/None, so a
    minimal ``compare`` label -- just ``display`` + ``expected_tools`` -- is still
    a valid :class:`TraceLabel`): ``model`` / ``task`` describe the captured run;
    ``source`` is ``"real"`` (a real Cline capture) or ``"authored"`` (a
    hand-built edge case, never counted as real evidence); ``kind`` is ``"clean"``
    or ``"failing"``; ``scorers`` maps a scorer name to its
    :class:`ScorerExpectation`; ``expected_failure_labels`` are the
    ``FailureLabel.value`` strings the advice must emit; ``evidence_tokens`` are
    the concrete strings (a file, a tool, a violation) the advice must name.
    """

    display: str | None
    expected_tools: tuple[str, ...] | None
    model: str | None = None
    task: str | None = None
    source: str | None = None
    kind: str | None = None
    scorers: dict[str, ScorerExpectation] = field(default_factory=dict)
    expected_failure_labels: tuple[str, ...] = ()
    evidence_tokens: tuple[str, ...] = ()


def labels_load(path: Path) -> dict[str, TraceLabel]:
    """Load and validate a labels manifest, keyed by the manifest's trace paths.

    Keys are returned VERBATIM as written in the manifest (the caller matches
    them against the trace paths it was given). Fails loud via
    :class:`LabelError` on any malformed input.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise LabelError(f"labels manifest {path} is not valid JSON: {err}") from err
    if not isinstance(raw, dict):
        raise LabelError(
            f"labels manifest {path} must be a JSON object mapping trace path -> label, "
            f"got {type(raw).__name__}"
        )
    return {key: _labels_parse_entry(path, key, value) for key, value in raw.items()}


def _labels_parse_entry(manifest: Path, key: str, value: object) -> TraceLabel:
    if not isinstance(value, dict):
        raise LabelError(
            f"label for {key!r} in {manifest} must be an object, got {type(value).__name__}"
        )
    return TraceLabel(
        display=_labels_read_display(manifest, key, value.get("display")),
        expected_tools=_labels_read_expected_tools(
            manifest, key, value.get("expected_tools")
        ),
        model=_labels_read_str_field(manifest, key, "model", value.get("model")),
        task=_labels_read_str_field(manifest, key, "task", value.get("task")),
        source=_labels_read_enum_field(
            manifest, key, "source", value.get("source"), _VALID_SOURCES
        ),
        kind=_labels_read_enum_field(
            manifest, key, "kind", value.get("kind"), _VALID_KINDS
        ),
        scorers=_labels_read_scorers(manifest, key, value.get("scorers")),
        expected_failure_labels=_labels_read_str_list(
            manifest,
            key,
            "expected_failure_labels",
            value.get("expected_failure_labels"),
        ),
        evidence_tokens=_labels_read_str_list(
            manifest, key, "evidence_tokens", value.get("evidence_tokens")
        ),
    )


def _labels_read_display(manifest: Path, key: str, value: object) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise LabelError(
        f"'display' for {key!r} in {manifest} must be a string, got {type(value).__name__}"
    )


def _labels_read_expected_tools(
    manifest: Path, key: str, value: object
) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise LabelError(
            f"'expected_tools' for {key!r} in {manifest} must be a list of strings, "
            f"got {value!r:.60}"
        )
    return tuple(value)


# --- Corpus-superset field parsers (all optional; absent -> the field default) --


def _labels_read_str_field(
    manifest: Path, key: str, field_name: str, value: object
) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise LabelError(
        f"{field_name!r} for {key!r} in {manifest} must be a string, "
        f"got {type(value).__name__}"
    )


def _labels_read_enum_field(
    manifest: Path, key: str, field_name: str, value: object, allowed: frozenset[str]
) -> str | None:
    # Absent is allowed (the field stays None); a present value must be one of the
    # closed vocabulary. A wrong-but-well-typed string is the silent-mislabel bug
    # this catches, so it fails LOUD rather than passing through.
    if value is None:
        return None
    if not isinstance(value, str) or value not in allowed:
        raise LabelError(
            f"{field_name!r} for {key!r} in {manifest} must be one of "
            f"{sorted(allowed)}, got {value!r:.60}"
        )
    return value


def _labels_read_str_list(
    manifest: Path, key: str, field_name: str, value: object
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise LabelError(
            f"{field_name!r} for {key!r} in {manifest} must be a list of strings, "
            f"got {value!r:.60}"
        )
    return tuple(value)


def _labels_read_scorers(
    manifest: Path, key: str, value: object
) -> dict[str, ScorerExpectation]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise LabelError(
            f"'scorers' for {key!r} in {manifest} must be an object mapping scorer "
            f"name -> expectation, got {type(value).__name__}"
        )
    return {
        name: _labels_read_one_scorer(manifest, key, name, entry)
        for name, entry in value.items()
    }


def _labels_read_one_scorer(
    manifest: Path, key: str, scorer: str, value: object
) -> ScorerExpectation:
    if not isinstance(value, dict):
        raise LabelError(
            f"scorer {scorer!r} for {key!r} in {manifest} must be an object, "
            f"got {type(value).__name__}"
        )
    return ScorerExpectation(
        expected_cell=_labels_read_str_field(
            manifest, key, f"scorers.{scorer}.expected_cell", value.get("expected_cell")
        ),
        score_is_none=_labels_read_bool_field(
            manifest, key, f"scorers.{scorer}.score_is_none", value.get("score_is_none")
        ),
        applicable=_labels_read_bool_field(
            manifest, key, f"scorers.{scorer}.applicable", value.get("applicable")
        ),
    )


def _labels_read_bool_field(
    manifest: Path, key: str, field_name: str, value: object
) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise LabelError(
        f"{field_name!r} for {key!r} in {manifest} must be a boolean, "
        f"got {type(value).__name__}"
    )
