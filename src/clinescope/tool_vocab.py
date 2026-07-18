"""Cline tool vocabulary + a typo guard for ``--expected`` (deterministic).

The ``tool_selection`` scorer takes a caller-supplied set of expected tool names
and never validates them, so a misspelled name (``aply_patch``) silently scores as
a MISSING tool -- a false negative that blames the agent for the user's typo. This
module is the input guard: a pinned snapshot of Cline's real tool names and a
nearest-match check that turns a likely typo into a loud, actionable warning.

Cline has TWO tool families, and a run comes from one or the other:

* **World-A / CLI** (``CLINE_WORLD_A_TOOLS``) -- what the ``cline`` CLI emits
  (``apply_patch``, ``read_files``, ...). Source: Cline's
  ``sdk/packages/core/src/extensions/tools/definitions.ts`` at upstream commit
  ``6309971`` (verified via ``gh api``).
* **VS Code extension** (``CLINE_EXTENSION_TOOLS``) -- what the extension emits
  (``write_to_file``, ``replace_in_file``, ``read_file``, ...). Source: the
  ``ClineDefaultTool`` enum in ``apps/vscode/src/shared/tools.ts`` @ cline/cline
  main. ``apply_patch`` is in both. Control-flow-only names (``plan_mode_respond``,
  ``act_mode_respond``, ``condense``, ...) are excluded: they are not agent tool
  choices a user scores with ``--expected``.

``CLINE_KNOWN_TOOLS`` is the union, and is what ``--expected`` is validated against,
so an extension user passing ``write_to_file`` and a CLI user passing ``apply_patch``
both avoid a spurious typo warning. All sets are HARD-CODED, not fetched at runtime,
so the package keeps ``dependencies=[]`` and the CLI stays offline. They are
SNAPSHOTS: if Cline adds or renames a tool upstream, refresh the relevant set here
and the matching ``_EXPECTED_*_VOCAB`` in ``tests/test_tool_vocab.py``.

The guard is advisory, not fatal: an unknown name still scores (the user might mean
a genuinely custom tool), but a close typo surfaces a "did you mean" suggestion.
Pure stdlib (``difflib``): no I/O, no LLM, deterministic.
"""

from __future__ import annotations

import difflib

# Cline World-A core tool names -- source: sdk/packages/core/src/extensions/tools/
# definitions.ts @ cline/cline commit 6309971 (the `name:`/`tool_name:` fields of
# the core tool definitions). A pinned snapshot; see the module docstring to refresh.
CLINE_WORLD_A_TOOLS: frozenset[str] = frozenset(
    {
        "read_files",
        "search_codebase",
        "run_commands",
        "fetch_web_content",
        "apply_patch",
        "editor",
        "skills",
        "ask_question",
        "submit_and_exit",
    }
)

# Cline VS Code extension tool-use names -- source: the ClineDefaultTool enum in
# apps/vscode/src/shared/tools.ts @ cline/cline main. The agent-action tools the
# extension emits (apply_patch is shared with the World-A set). See the module
# docstring for the excluded control-flow names and how to refresh.
CLINE_EXTENSION_TOOLS: frozenset[str] = frozenset(
    {
        "ask_followup_question",
        "attempt_completion",
        "execute_command",
        "replace_in_file",
        "read_file",
        "write_to_file",
        "search_files",
        "list_files",
        "list_code_definition_names",
        "browser_action",
        "use_mcp_tool",
        "access_mcp_resource",
        "load_mcp_documentation",
        "new_task",
        "focus_chain",
        "web_fetch",
        "web_search",
        "apply_patch",
        "use_skill",
        "use_subagents",
    }
)

# The union of both families -- what --expected is validated against, so a CLI user
# (apply_patch) and an extension user (write_to_file) both avoid a false typo warning.
CLINE_KNOWN_TOOLS: frozenset[str] = CLINE_WORLD_A_TOOLS | CLINE_EXTENSION_TOOLS

# difflib cutoff for "this is probably that tool misspelled". 0.7 accepts a
# one/two-character slip (aply_patch -> apply_patch = 0.95) while rejecting an
# unrelated custom name, which returns no suggestion rather than a wrong one.
_SUGGESTION_CUTOFF = 0.7


def tool_vocab_check(names: list[str]) -> list[tuple[str, str | None]]:
    """Return one ``(name, suggestion)`` per name NOT in the Cline vocabulary.

    Args:
        names: The ``--expected`` tool names as the user typed them.

    Returns:
        A list with one entry per UNKNOWN name (known names are omitted), in input
        order. ``suggestion`` is the nearest real tool name when one is within the
        typo cutoff, else ``None``. An empty list means every name is a known tool.
    """
    findings: list[tuple[str, str | None]] = []
    for name in names:
        if name in CLINE_KNOWN_TOOLS:
            continue
        matches = difflib.get_close_matches(
            name, CLINE_KNOWN_TOOLS, n=1, cutoff=_SUGGESTION_CUTOFF
        )
        findings.append((name, matches[0] if matches else None))
    return findings
