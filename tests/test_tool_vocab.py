"""Tests for the Cline tool-vocabulary guard (Q1 input-footgun fixes).

The vocabulary is a pinned snapshot of Cline's World-A core tools (see
``tool_vocab.py`` for the cited source). These tests pin the two behaviours the
CLI relies on: the known set stays what we validated against, and the
nearest-match suggester catches a realistic typo.
"""

from clinescope.tool_vocab import (
    CLINE_WORLD_A_TOOLS,
    tool_vocab_check,
)

# The exact core World-A tool names verified at the pinned ref (definitions.ts
# @ 6309971). If Cline adds a tool upstream and we refresh the snapshot, update
# this set deliberately -- the test is the tripwire that the snapshot changed.
_EXPECTED_VOCAB = {
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


def test_vocab_is_the_pinned_cline_world_a_core_set() -> None:
    assert set(CLINE_WORLD_A_TOOLS) == _EXPECTED_VOCAB


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
