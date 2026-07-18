"""Tests for the Cline tool-vocabulary guard (Q1 input-footgun fixes).

The vocabulary spans TWO pinned Cline tool families (see ``tool_vocab.py`` for the
cited sources): the World-A / CLI core tools and the VS Code extension tools. These
tests pin that each family stays what we validated against, that ``--expected``
accepts both, and that the nearest-match suggester catches a realistic typo.
"""

from clinescope.tool_vocab import (
    CLINE_EXTENSION_TOOLS,
    CLINE_KNOWN_TOOLS,
    CLINE_WORLD_A_TOOLS,
    tool_vocab_check,
)

# The exact core World-A tool names verified at the pinned ref (definitions.ts
# @ 6309971). If Cline adds a tool upstream and we refresh the snapshot, update
# this set deliberately -- the test is the tripwire that the snapshot changed.
_EXPECTED_WORLD_A_VOCAB = {
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

# The VS Code extension tool-use names, from the ClineDefaultTool enum
# (apps/vscode/src/shared/tools.ts @ cline/cline main). apply_patch is shared with
# the World-A set. Control-flow-only names (plan_mode_respond, act_mode_respond,
# condense, summarize_task, report_bug, new_rule) are excluded: they are not agent
# tool choices a user scores with --expected.
_EXPECTED_EXTENSION_VOCAB = {
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


def test_world_a_vocab_is_the_pinned_cline_core_set() -> None:
    assert set(CLINE_WORLD_A_TOOLS) == _EXPECTED_WORLD_A_VOCAB


def test_extension_vocab_is_the_pinned_cline_default_tool_set() -> None:
    assert set(CLINE_EXTENSION_TOOLS) == _EXPECTED_EXTENSION_VOCAB


def test_known_tools_is_the_union_of_both_families() -> None:
    assert set(CLINE_KNOWN_TOOLS) == _EXPECTED_WORLD_A_VOCAB | _EXPECTED_EXTENSION_VOCAB


def test_extension_tools_are_accepted_with_no_findings() -> None:
    # write_to_file / read_file (the extension's own tools) must not warn as typos.
    assert tool_vocab_check(["write_to_file", "read_file", "replace_in_file"]) == []


def test_known_tool_names_produce_no_findings() -> None:
    findings = tool_vocab_check(["read_files", "apply_patch"])
    assert findings == []


def test_typo_is_flagged_with_the_nearest_real_tool() -> None:
    findings = tool_vocab_check(["aply_patch"])
    assert findings == [("aply_patch", "apply_patch")]


def test_unknown_name_with_no_close_match_suggests_nothing() -> None:
    findings = tool_vocab_check(["zzzzzzzzzzzz"])
    assert findings == [("zzzzzzzzzzzz", None)]


def test_only_unknown_names_are_returned_mixed_input() -> None:
    findings = tool_vocab_check(["read_files", "reed_files", "apply_patch"])
    assert findings == [("reed_files", "read_files")]


def test_empty_input_is_no_findings() -> None:
    assert tool_vocab_check([]) == []
