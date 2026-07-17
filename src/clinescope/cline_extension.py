"""Cline VS Code extension-format adapter.

The Cline CLI writes a World-A trace as ``{"version": 1, "messages": [...]}``,
which ``world_a.load_trace`` reads directly. The Cline VS Code *extension* stores
a task's API history differently: a bare JSON array of messages (no envelope) in
``api_conversation_history.json`` under its global storage. Verified against Cline
source: ``apps/vscode/src/core/storage/disk.ts::saveApiConversationHistory``
writes ``JSON.stringify(apiConversationHistory)`` where the argument is an
``Anthropic.MessageParam[]``; ``apps/vscode/src/shared/messages/content.ts``
defines ``ClineStorageMessage extends Anthropic.MessageParam`` with extra optional
fields (``id``, ``ts``, ``modelInfo``, ``metrics``).

The only structural delta from the CLI format is the missing envelope. So this
adapter wraps the bare array in ``{"version": 1, "messages": <array>}`` with a
synthesized ``sessionId`` and feeds the **existing** loader unchanged. The
content-block vocabulary (``text`` / ``thinking`` / ``tool_use`` / ``tool_result``)
is identical, and the loader already ignores unknown per-message keys, so the
Cline-specific extras pass through harmlessly.

This is an adapter onto the existing World-A loader, not a new trace model or a
second framework adapter: it reuses ``world_a.load_trace`` and every scorer as-is.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from clinescope.world_a import Trace, WorldATraceError, load_trace_from_dict


class ClineExtensionTraceError(WorldATraceError):
    """The file is not a readable Cline extension api_conversation_history.json.

    Inherits from ``WorldATraceError`` so callers that already catch World-A
    load errors keep working unchanged.
    """


def load_extension_trace(path: str | Path) -> Trace:
    """Load a Cline VS Code extension ``api_conversation_history.json`` trace.

    Reads the bare message array the extension writes, wraps it in the World-A
    envelope, and returns a normalized ``Trace`` via the existing loader.

    Raises:
        ClineExtensionTraceError: the file is not valid JSON, or is not the bare
            array shape the extension writes (e.g. a World-A envelope dict is
            passed instead -- use ``world_a.load_trace`` for that).
    """
    source = Path(path)
    messages = _extension_read_messages(source)
    return _extension_load_from_messages(messages, source)


def _extension_read_messages(source: Path) -> list[Any]:
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as err:
        raise ClineExtensionTraceError(
            f"Cline extension trace {source} is not valid JSON"
        ) from err
    if not isinstance(raw, list):
        raise ClineExtensionTraceError(
            "Cline extension api_conversation_history.json must be a bare JSON "
            f"array of messages, got {type(raw).__name__}. If this is a "
            "{version, messages} World-A trace, use world_a.load_trace instead."
        )
    # Guard at the boundary: the World-A loader assumes each message is an object
    # and would raise a bare AttributeError on a non-dict element. Fail loud here
    # with the adapter's own error instead, so a partially-malformed real capture
    # surfaces cleanly rather than crashing mid-parse.
    bad = next(((i, m) for i, m in enumerate(raw) if not isinstance(m, dict)), None)
    if bad is not None:
        index, value = bad
        raise ClineExtensionTraceError(
            f"Cline extension trace {source} message at index {index} is a "
            f"{type(value).__name__}, expected a JSON object"
        )
    return raw


def _extension_load_from_messages(messages: list[Any], source: Path) -> Trace:
    envelope: dict[str, Any] = {
        "version": 1,
        "sessionId": source.stem,
        "messages": messages,
    }
    return load_trace_from_dict(envelope)
