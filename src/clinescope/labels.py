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
from dataclasses import dataclass
from pathlib import Path


class LabelError(ValueError):
    """A labels manifest was malformed (bad JSON, wrong shape, or a bad field)."""


@dataclass(frozen=True, slots=True)
class TraceLabel:
    """One trace's label. ``expected_tools is None`` means "skip tool_selection".

    ``expected_tools`` is a distinct three-way signal:

    * ``None`` -- no expected set given (skip tool_selection -> ``n/a``).
    * ``()`` -- an explicit empty expected set (vacuous perfect recall).
    * a non-empty tuple -- the tool names to score recall against.
    """

    display: str | None
    expected_tools: tuple[str, ...] | None


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
