import json
from pathlib import Path

import pytest

from clinescope.world_a import (
    ToolResultItem,
    TraceVersionError,
    WorldATraceError,
    load_trace,
)


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


def _tool_result_trace(tmp_path: Path, result_item: dict) -> Path:
    """A minimal v1 trace: one tool_use joined to ``result_item``."""
    payload = {
        "version": 1,
        "sessionId": "fixture-is-error-01",
        "messages": [
            {
                "id": "m0",
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tc-1",
                        "name": "apply_patch",
                        "input": {"input": "*** Begin Patch\n*** End Patch"},
                    }
                ],
            },
            {"id": "m1", "role": "user", "content": [result_item]},
        ],
    }
    return _write(tmp_path, payload)


def test_explicit_is_error_null_maps_to_none_not_false(tmp_path: Path) -> None:
    # A PRESENT tool_result with an explicit JSON null verdict is NOT a confirmed
    # success -- it is an unknown verdict. Coercing it to False (the old
    # bool(get(...)) behavior) would let a null-verdict retry count as a recovery
    # in apply_recovery. It must map to None (distinct from True/False).
    path = _tool_result_trace(
        tmp_path,
        {
            "type": "tool_result",
            "tool_use_id": "tc-1",
            "content": "x",
            "is_error": None,
        },
    )

    trace = load_trace(path)

    assert trace.tool_calls[0].is_error is None


def test_missing_is_error_key_maps_to_none(tmp_path: Path) -> None:
    # A tool_result with no is_error field at all is likewise an unknown verdict,
    # not a success. (Cline always emits is_error; this is malformed-input hardening.)
    path = _tool_result_trace(
        tmp_path,
        {"type": "tool_result", "tool_use_id": "tc-1", "content": "x"},
    )

    trace = load_trace(path)

    assert trace.tool_calls[0].is_error is None


def test_explicit_is_error_true_and_false_preserved(tmp_path: Path) -> None:
    # The real verdicts still map to themselves (regression guard for the fix).
    for flag in (True, False):
        path = _tool_result_trace(
            tmp_path,
            {
                "type": "tool_result",
                "tool_use_id": "tc-1",
                "content": "x",
                "is_error": flag,
            },
        )
        trace = load_trace(path)
        assert trace.tool_calls[0].is_error is flag


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


# --- R3: honest, tested tool_result content-type contract -------------------
# Real Cline traces emit LIST-valued tool_result content on read_files /
# run_commands results (a single-element [{"query","result","success"}] object),
# not just the str a JSON-string apply_patch result carries. These tests pin
# that the loader PRESERVES either shape without error or dropping -- so the
# widened `ToolResultContent = str | list[object]` annotation matches reality and
# the apply_recovery oracle's isinstance(str) abstain boundary is the documented,
# tested contract, never a silent typing lie.

# The exact list shape a live read_files result carries (see the committed
# examples/live-gpt-oss-*.json traces).
_LIST_CONTENT: list[object] = [
    {"query": "calc.py", "result": "def f(): ...", "success": True}
]

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
_ALL_EXAMPLE_TRACES = sorted(EXAMPLES.glob("*.json"))


def test_list_content_is_preserved_on_tool_result_item(tmp_path: Path) -> None:
    # A list-valued content rides onto ToolResultItem.content unchanged -- not
    # stringified, not dropped. (The read_files list shape a live trace carries.)
    path = _tool_result_trace(
        tmp_path,
        {"type": "tool_result", "tool_use_id": "tc-1", "content": _LIST_CONTENT},
    )

    trace = load_trace(path)

    result_item = trace.turns[1].content[0]
    assert isinstance(result_item, ToolResultItem)
    assert result_item.content == _LIST_CONTENT


def test_list_content_rides_into_tool_call_result_content(tmp_path: Path) -> None:
    # The tool_use->tool_result join copies the list through to
    # ToolCall.result_content; the field now legitimately holds a list.
    path = _tool_result_trace(
        tmp_path,
        {"type": "tool_result", "tool_use_id": "tc-1", "content": _LIST_CONTENT},
    )

    trace = load_trace(path)

    assert trace.tool_calls[0].result_content == _LIST_CONTENT


def test_str_content_still_loads_as_str(tmp_path: Path) -> None:
    # Regression guard for the widening: a str content (the apply_patch
    # JSON-string shape) still loads as a str, unchanged.
    str_content = '{"query": "apply_patch", "result": "ok", "success": true}'
    path = _tool_result_trace(
        tmp_path,
        {"type": "tool_result", "tool_use_id": "tc-1", "content": str_content},
    )

    trace = load_trace(path)

    assert trace.tool_calls[0].result_content == str_content
    assert isinstance(trace.tool_calls[0].result_content, str)


def test_missing_content_key_defaults_to_empty_str(tmp_path: Path) -> None:
    # The item.get("content", "") default fires ONLY when the key is entirely
    # absent, yielding a str "" (a valid ToolResultContent the oracle abstains
    # on) -- pins the deliberate "leave the default unchanged" decision.
    path = _tool_result_trace(
        tmp_path,
        {"type": "tool_result", "tool_use_id": "tc-1"},
    )

    trace = load_trace(path)

    assert trace.tool_calls[0].result_content == ""


@pytest.mark.parametrize("trace_path", _ALL_EXAMPLE_TRACES, ids=lambda p: p.name)
def test_all_committed_example_traces_load_with_no_dropped_items(
    trace_path: Path,
) -> None:
    # Every committed example trace (incl. the 4 live captures carrying
    # list-content) loads with nothing the loader could not model -- the concrete
    # "runtime unchanged" pin at the loader level for the R3 widening.
    trace = load_trace(trace_path)

    assert trace.dropped_items == ()
