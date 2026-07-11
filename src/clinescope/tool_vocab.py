"""Cline World-A tool vocabulary + a typo guard for ``--expected`` (deterministic).

The ``tool_selection`` scorer takes a caller-supplied set of expected tool names
and never validates them, so a misspelled name (``aply_patch``) silently scores as
a MISSING tool -- a false negative that blames the agent for the user's typo. This
module is the input guard: a pinned snapshot of Cline's real World-A tool names and
a nearest-match check that turns a likely typo into a loud, actionable warning.

**Pinned source (protocol rule 12 -- the local Cline clone can be stale).** The set
is the core World-A tool names defined in Cline's
``sdk/packages/core/src/extensions/tools/definitions.ts`` at upstream commit
``6309971`` (verified via ``gh api`` -- the local checkout was hundreds of commits
behind). It is HARD-CODED, not fetched at runtime, so the package keeps
``dependencies=[]`` and the CLI stays offline. It is a SNAPSHOT: if Cline adds or
renames a tool upstream, refresh it by re-reading that file at a new ref and
updating both this set and ``tests/test_tool_vocab.py``'s ``_EXPECTED_VOCAB``.

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
        if name in CLINE_WORLD_A_TOOLS:
            continue
        matches = difflib.get_close_matches(
            name, CLINE_WORLD_A_TOOLS, n=1, cutoff=_SUGGESTION_CUTOFF
        )
        findings.append((name, matches[0] if matches else None))
    return findings
