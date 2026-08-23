"""Shared failure/success verdict oracle for a Cline tool result (deterministic).

Two scorers need the same question answered: did Cline consider this tool call a
failure? :mod:`clinescope.apply_recovery` asks it of ``apply_patch`` calls and
:mod:`clinescope.editor_recovery` asks it of ``editor`` calls. The answer is
resolved identically for both, so it lives here once rather than being copied.

The oracle exists because a genuine Cline tool result carries NO ``is_error``
field: the loader therefore reports ``is_error=None``, and the real outcome is
encoded as ``{...,"success":true/false}`` inside the tool_result content JSON
(cline ``definitions.ts`` createApplyPatchTool / createEditorTool, plus
``agent-message-codec.ts``). Without the secondary read, both scorers abstain on
every real trace.

**Precedence, ``is_error`` AUTHORITATIVE:**

1. A real ``bool`` ``call.is_error`` is returned directly, and it WINS any
   conflict with the content.
2. Otherwise, when ``result_content`` is a ``str`` that parses to a ``dict``
   carrying a real ``bool`` under ``"success"``, return ``not success`` (a
   success is a non-failing verdict ``False``), matching the ``is_error``
   polarity.
3. Otherwise ``None`` -- abstain.

Step 3 fails CLOSED on non-``str`` content (a ``read_files``-shaped list), on
invalid or truncated JSON, on non-dict JSON, and on a missing, ``null`` or
non-``bool`` ``"success"``. Abstaining can only ever UNDER-count recovery,
because a recovery numerator requires a CONFIRMED ``False``. It can never
inflate a score, which is what preserves both scorers' anti-truncation
guarantee: an adversary who truncates a trace right after a re-attempt loses the
content too, so the read fails closed rather than reading as success.

Pure: no I/O, no LLM, deterministic.
"""

from __future__ import annotations

import json

from clinescope.world_a import ToolCall

# The key inside a tool_result's JSON-string content that carries the outcome.
# Source: cline definitions.ts, where both createApplyPatchTool and
# createEditorTool return {query, result, [error], success}.
_SUCCESS_KEY = "success"


def tool_verdict_effective(call: ToolCall) -> bool | None:
    """The effective failure verdict of one tool call.

    Args:
        call: Any joined :class:`~clinescope.world_a.ToolCall`. The caller decides
            which tool names to ask about; this function does not filter by name.

    Returns:
        ``True`` when Cline treated the call as a failure, ``False`` when Cline
        confirmed it succeeded, and ``None`` when neither the loader verdict nor
        the content oracle resolves one. ``None`` is a THIRD state, never a
        coerced success.
    """
    if isinstance(call.is_error, bool):
        return call.is_error

    content = call.result_content
    if not isinstance(content, str):
        return None
    try:
        parsed = json.loads(content)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    success = parsed.get(_SUCCESS_KEY)
    if not isinstance(success, bool):
        return None
    return not success
