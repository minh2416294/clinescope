"""Tests for the per-trace labels manifest loader (clinescope.labels)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinescope.labels import LabelError, TraceLabel, labels_load


def _write(path: Path, obj: object) -> Path:
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def test_labels_load_parses_display_and_expected_tools(tmp_path: Path) -> None:
    manifest = _write(
        tmp_path / "m.json",
        {
            "examples/a.json": {
                "display": "model-a add-file",
                "expected_tools": ["apply_patch"],
            },
            "examples/b.json": {"expected_tools": ["read_files", "apply_patch"]},
        },
    )

    labels = labels_load(manifest)

    assert labels["examples/a.json"] == TraceLabel(
        display="model-a add-file", expected_tools=("apply_patch",)
    )
    assert labels["examples/b.json"] == TraceLabel(
        display=None, expected_tools=("read_files", "apply_patch")
    )


def test_labels_absent_expected_tools_is_none_not_empty(tmp_path: Path) -> None:
    # Absent expected_tools -> None (skip tool_selection), distinct from [] (a real
    # empty expected set). This three-way distinction is load-bearing for the n/a cell.
    manifest = _write(tmp_path / "m.json", {"examples/a.json": {"display": "x"}})

    label = labels_load(manifest)["examples/a.json"]

    assert label.expected_tools is None


def test_labels_explicit_empty_expected_tools_is_empty_tuple(tmp_path: Path) -> None:
    manifest = _write(tmp_path / "m.json", {"examples/a.json": {"expected_tools": []}})

    label = labels_load(manifest)["examples/a.json"]

    assert label.expected_tools == ()
    assert label.expected_tools is not None


def test_labels_null_expected_tools_is_none(tmp_path: Path) -> None:
    manifest = _write(
        tmp_path / "m.json", {"examples/a.json": {"expected_tools": None}}
    )

    assert labels_load(manifest)["examples/a.json"].expected_tools is None


def test_labels_empty_entry_is_all_defaults(tmp_path: Path) -> None:
    manifest = _write(tmp_path / "m.json", {"examples/a.json": {}})

    assert labels_load(manifest)["examples/a.json"] == TraceLabel(
        display=None, expected_tools=None
    )


# --- Fail-loud on malformed input ---------------------------------------------


def test_labels_load_rejects_non_object_root(tmp_path: Path) -> None:
    manifest = _write(tmp_path / "m.json", ["not", "an", "object"])

    with pytest.raises(LabelError, match="must be a JSON object"):
        labels_load(manifest)


def test_labels_load_rejects_non_object_entry(tmp_path: Path) -> None:
    manifest = _write(tmp_path / "m.json", {"examples/a.json": "apply_patch"})

    with pytest.raises(LabelError, match="must be an object"):
        labels_load(manifest)


def test_labels_load_rejects_non_string_display(tmp_path: Path) -> None:
    manifest = _write(tmp_path / "m.json", {"examples/a.json": {"display": 3}})

    with pytest.raises(LabelError, match="'display'.*must be a string"):
        labels_load(manifest)


def test_labels_load_rejects_non_list_expected_tools(tmp_path: Path) -> None:
    manifest = _write(
        tmp_path / "m.json", {"examples/a.json": {"expected_tools": "apply_patch"}}
    )

    with pytest.raises(LabelError, match="'expected_tools'.*must be a list of strings"):
        labels_load(manifest)


def test_labels_load_rejects_non_string_tool_name(tmp_path: Path) -> None:
    manifest = _write(
        tmp_path / "m.json", {"examples/a.json": {"expected_tools": ["ok", 7]}}
    )

    with pytest.raises(LabelError, match="must be a list of strings"):
        labels_load(manifest)


def test_labels_load_rejects_invalid_json(tmp_path: Path) -> None:
    manifest = tmp_path / "m.json"
    manifest.write_text("{not json", encoding="utf-8")

    with pytest.raises(LabelError, match="not valid JSON"):
        labels_load(manifest)
