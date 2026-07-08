"""Cline World-A trace loader.

Reads a Cline World-A ``messages.json`` v1 trace, version-gates it (fail loud on
any other version), tolerantly ignores unknown keys, and normalizes the raw
messages into turns with tool calls joined to their results on ``tool_use_id``.

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
    is_error: bool


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


def load_trace(path: str | Path) -> Trace:
    raw = _world_a_read_json(Path(path))
    _world_a_check_version(raw)
    turns = _world_a_parse_turns(raw.get("messages", []))
    tool_calls = _world_a_join_tool_calls(turns)
    return Trace(version=1, turns=turns, tool_calls=tool_calls)


def _world_a_read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _world_a_check_version(raw: dict[str, Any]) -> None:
    version = raw.get("version")
    if version != 1:
        raise TraceVersionError(
            f"Unsupported Cline World-A trace version {version!r}; loader supports version 1 only"
        )


def _world_a_parse_turns(messages: list[dict[str, Any]]) -> tuple[Turn, ...]:
    turns = []
    for message in messages:
        content = _world_a_parse_content(message.get("content", []))
        turns.append(Turn(role=message.get("role", ""), content=content))
    return tuple(turns)


def _world_a_parse_content(items: list[dict[str, Any]]) -> tuple[ContentItem, ...]:
    parsed: list[ContentItem] = []
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
                parsed.append(
                    ToolResultItem(
                        tool_use_id=item.get("tool_use_id", ""),
                        content=item.get("content", ""),
                        is_error=bool(item.get("is_error", False)),
                    )
                )
            case _:
                continue
    return tuple(parsed)


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
