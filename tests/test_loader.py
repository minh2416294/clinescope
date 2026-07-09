import json
from pathlib import Path

import pytest

from clinescope.world_a import TraceVersionError, WorldATraceError, load_trace


def _golden_messages() -> list[dict]:
    return [
        {
            "id": "msg_user_1",
            "role": "user",
            "content": [
                {"type": "text", "text": "Inspect the README and summarize it."}
            ],
        },
        {
            "id": "msg_assistant_1",
            "ts": 1745343730123,
            "modelInfo": {"id": "claude-sonnet-4-6", "provider": "anthropic"},
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "I should read the README first."},
                {
                    "type": "tool_use",
                    "id": "tool-call-1",
                    "name": "read_files",
                    "input": {"path": "/tmp/project/README.md"},
                },
            ],
        },
        {
            "id": "msg_user_2",
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tool-call-1",
                    "content": "# Project\n\nA small test fixture.",
                    "is_error": False,
                }
            ],
        },
        {
            "id": "msg_assistant_2",
            "ts": 1745343731456,
            "modelInfo": {"id": "claude-sonnet-4-6", "provider": "anthropic"},
            "metrics": {"inputTokens": 21, "outputTokens": 8, "cost": 0.13},
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": "The README describes a small test fixture project.",
                }
            ],
        },
    ]


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "messages.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_loads_golden_v1(tmp_path: Path) -> None:
    payload = {
        "version": 1,
        "updated_at": "2026-04-22T17:42:10.123Z",
        "agent": "lead",
        "sessionId": "fixture-success-01",
        "messages": _golden_messages(),
    }

    trace = load_trace(_write(tmp_path, payload))

    assert trace.version == 1
    assert len(trace.turns) == 4
    assert len(trace.tool_calls) == 1
    assert trace.tool_calls[0].name == "read_files"
    assert trace.tool_calls[0].id == "tool-call-1"
    assert trace.tool_calls[0].is_error is False
    assert trace.dropped_items == ()


def test_unknown_content_type_is_surfaced_not_dropped(tmp_path: Path) -> None:
    typo_item = {"type": "txt", "text": "REAL CONTENT that must not vanish"}
    payload = {
        "version": 1,
        "sessionId": "fixture-drop-01",
        "messages": [
            {
                "id": "m0",
                "role": "user",
                "content": [
                    {"type": "text", "text": "kept"},
                    typo_item,
                ],
            }
        ],
    }

    trace = load_trace(_write(tmp_path, payload))

    assert len(trace.turns[0].content) == 1
    assert trace.turns[0].content[0].text == "kept"
    assert len(trace.dropped_items) == 1
    assert trace.dropped_items[0] == typo_item


def test_rejects_version_2(tmp_path: Path) -> None:
    payload = {
        "version": 2,
        "sessionId": "fixture-success-01",
        "messages": _golden_messages(),
    }

    with pytest.raises(TraceVersionError):
        load_trace(_write(tmp_path, payload))


def test_rejects_non_object_top_level(tmp_path: Path) -> None:
    path = tmp_path / "messages.json"
    path.write_text(json.dumps([{"version": 1}]), encoding="utf-8")

    with pytest.raises(WorldATraceError):
        load_trace(path)
