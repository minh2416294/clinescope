"""Tests for the Cline VS Code extension-format adapter.

The extension writes a bare JSON array (no {version, messages} envelope) to
api_conversation_history.json; the World-A loader hard-rejects it. The adapter
wraps the array in the envelope and reuses the existing loader unchanged. These
tests pin that the wrap works, the four scorers run on the adapted trace, and the
adapter fails loud on a shape it cannot handle.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinescope.apply_recovery import score_apply_recovery
from clinescope.cline_extension import (
    ClineExtensionTraceError,
    load_extension_trace,
)
from clinescope.diff_coherence import score_diff_coherence
from clinescope.diff_minimality import score_diff_minimality
from clinescope.tool_selection import score_tool_selection
from clinescope.world_a import Trace, WorldATraceError, load_trace

_CONSTRUCTED = (
    Path(__file__).resolve().parent.parent
    / "examples"
    / "extension"
    / "api_conversation_history.constructed.json"
)


def _write(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "api_conversation_history.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_loader_rejects_the_bare_extension_array() -> None:
    # Documents the exact gap the adapter closes: world_a.load_trace cannot read
    # the extension's bare-array file directly.
    with pytest.raises(WorldATraceError):
        load_trace(_CONSTRUCTED)


def test_adapter_loads_constructed_extension_trace() -> None:
    trace = load_extension_trace(_CONSTRUCTED)
    assert isinstance(trace, Trace)
    assert trace.version == 1
    names = [call.name for call in trace.tool_calls]
    assert names == ["read_files", "apply_patch"]


def test_four_scorers_run_on_adapted_extension_trace() -> None:
    # The point of the adapter: the existing scorers produce numbers on an
    # extension-sourced trace, end to end.
    trace = load_extension_trace(_CONSTRUCTED)

    ts = score_tool_selection(trace, expected={"read_files", "apply_patch"})
    assert ts.score == 1.0

    dc = score_diff_coherence(trace)
    assert dc.score == 1.0

    dm = score_diff_minimality(trace)
    assert dm.applicable is True
    assert dm.score == 1.0

    ar = score_apply_recovery(trace)
    # Nothing failed in this trace, so apply_recovery abstains (not an error).
    assert ar.applicable is False


def test_adapter_ignores_cline_specific_message_fields(tmp_path: Path) -> None:
    # id / ts / modelInfo on a message must not break the wrap-and-load.
    payload = [
        {
            "id": "msg_x",
            "ts": 123,
            "modelInfo": {"provider": "anthropic"},
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "c1", "name": "read_files", "input": {}}
            ],
        }
    ]
    trace = load_extension_trace(_write(tmp_path, payload))
    assert [c.name for c in trace.tool_calls] == ["read_files"]


def test_adapter_rejects_a_json_object_not_an_array(tmp_path: Path) -> None:
    # A World-A envelope (a dict) is NOT the extension shape; the adapter is for
    # the bare array only. Fail loud rather than silently double-wrap.
    with pytest.raises(ClineExtensionTraceError):
        load_extension_trace(_write(tmp_path, {"version": 1, "messages": []}))


def test_adapter_rejects_non_json(tmp_path: Path) -> None:
    path = tmp_path / "api_conversation_history.json"
    path.write_text("not json at all", encoding="utf-8")
    with pytest.raises(ClineExtensionTraceError):
        load_extension_trace(path)


def test_adapter_rejects_array_with_non_object_element(tmp_path: Path) -> None:
    # A bare array whose elements are not objects must fail loud with the
    # adapter's own error, not leak a raw AttributeError from the loader.
    with pytest.raises(ClineExtensionTraceError):
        load_extension_trace(_write(tmp_path, [{"role": "user", "content": []}, 42]))


def test_extension_error_is_a_world_a_error() -> None:
    # Callers that already catch WorldATraceError keep working.
    assert issubclass(ClineExtensionTraceError, WorldATraceError)
