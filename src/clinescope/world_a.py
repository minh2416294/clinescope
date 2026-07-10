"""Cline World-A trace loader.

Reads a Cline World-A ``messages.json`` v1 trace, version-gates it (fail loud on
any other version), tolerantly ignores unknown keys, and normalizes the raw
messages into turns with tool calls joined to their results on ``tool_use_id``.

Content items whose ``type`` is unmodeled or mistyped are not dropped silently:
they are collected on ``Trace.dropped_items`` so a caller can see what the loader
could not model (surface hidden failures, never swallow them).

This is the "load" stage of the walking skeleton (load trace -> score -> emit).
No scorer, no report emitter, no CLI here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeAlias


class WorldATraceError(Exception):
    """Base for all World-A trace loading errors."""


class TraceVersionError(WorldATraceError):
    """Trace version is not the supported v1."""


@dataclass(frozen=True, slots=True)
class TextItem:
    text: str


@dataclass(frozen=True, slots=True)
class ThinkingItem:
    thinking: str


@dataclass(frozen=True, slots=True)
class ToolUseItem:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResultItem:
    tool_use_id: str
    content: str
    # None = no explicit verdict (key missing OR an explicit JSON null); a bool is
    # Cline's real verdict. Distinguishing null-from-false matters downstream: a
    # scorer must not read an unknown verdict as a confirmed success.
    is_error: bool | None


ContentItem: TypeAlias = TextItem | ThinkingItem | ToolUseItem | ToolResultItem


@dataclass(frozen=True, slots=True)
class Turn:
    role: str
    content: tuple[ContentItem, ...]


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]
    result_content: str | None
    is_error: bool | None


@dataclass(frozen=True, slots=True)
class Trace:
    version: int
    turns: tuple[Turn, ...]
    tool_calls: tuple[ToolCall, ...]
    dropped_items: tuple[dict[str, Any], ...]


def load_trace(path: str | Path) -> Trace:
    raw = _world_a_read_json(Path(path))
    _world_a_check_version(raw)
    turns, dropped_items = _world_a_parse_turns(raw.get("messages", []))
    tool_calls = _world_a_join_tool_calls(turns)
    return Trace(
        version=1, turns=turns, tool_calls=tool_calls, dropped_items=dropped_items
    )


def _world_a_read_json(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise WorldATraceError(
            f"Cline World-A trace must be a JSON object, got {type(raw).__name__}"
        )
    return raw


def _world_a_check_version(raw: dict[str, Any]) -> None:
    version = raw.get("version")
    if version != 1:
        raise TraceVersionError(
            f"Unsupported Cline World-A trace version {version!r}; loader supports version 1 only"
        )


def _world_a_parse_turns(
    messages: list[dict[str, Any]],
) -> tuple[tuple[Turn, ...], tuple[dict[str, Any], ...]]:
    turns = []
    dropped: list[dict[str, Any]] = []
    for message in messages:
        content, message_dropped = _world_a_parse_content(message.get("content", []))
        turns.append(Turn(role=message.get("role", ""), content=content))
        dropped.extend(message_dropped)
    return tuple(turns), tuple(dropped)


def _world_a_parse_content(
    items: list[dict[str, Any]],
) -> tuple[tuple[ContentItem, ...], list[dict[str, Any]]]:
    parsed: list[ContentItem] = []
    dropped: list[dict[str, Any]] = []
    for item in items:
        match item.get("type"):
            case "text":
                parsed.append(TextItem(text=item.get("text", "")))
            case "thinking":
                parsed.append(ThinkingItem(thinking=item.get("thinking", "")))
            case "tool_use":
                parsed.append(
                    ToolUseItem(
                        id=item.get("id", ""),
                        name=item.get("name", ""),
                        input=item.get("input", {}),
                    )
                )
            case "tool_result":
                raw_is_error = item.get("is_error")
                parsed.append(
                    ToolResultItem(
                        tool_use_id=item.get("tool_use_id", ""),
                        content=item.get("content", ""),
                        # Only a real bool is a verdict; a missing key or an explicit
                        # null is an UNKNOWN verdict (None), never a coerced False.
                        is_error=raw_is_error
                        if isinstance(raw_is_error, bool)
                        else None,
                    )
                )
            case _:
                dropped.append(item)
    return tuple(parsed), dropped


def _world_a_join_tool_calls(turns: tuple[Turn, ...]) -> tuple[ToolCall, ...]:
    results_by_id: dict[str, ToolResultItem] = {}
    for turn in turns:
        for item in turn.content:
            if isinstance(item, ToolResultItem):
                results_by_id[item.tool_use_id] = item

    tool_calls = []
    for turn in turns:
        for item in turn.content:
            if not isinstance(item, ToolUseItem):
                continue
            result = results_by_id.get(item.id)
            if result is None:
                tool_calls.append(
                    ToolCall(
                        id=item.id,
                        name=item.name,
                        input=item.input,
                        result_content=None,
                        is_error=None,
                    )
                )
            else:
                tool_calls.append(
                    ToolCall(
                        id=item.id,
                        name=item.name,
                        input=item.input,
                        result_content=result.content,
                        is_error=result.is_error,
                    )
                )
    return tuple(tool_calls)
