"""Tests for the plain-English default report and the ``--details`` view.

The plain view is what a Cline user sees first, so every sentence here is a contract: it
must stay inside what the check measures (LIMITATIONS.md), name every check that ran
exactly once (a problem, "What went well", or "Did not apply"), and give every problem
its "What to do" and "Why". Expected text was written from the approved Day 80 wording,
not copied from the renderer's output.

``--details`` keeps today's technical report, with advice on every failing run. On a
clean run, and on the bundled demo, it is byte for byte what the default printed before
the plain view existed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clinescope.__main__ import main
from clinescope.apply_recovery import ApplyRecoveryScore
from clinescope.cmd_after_edit import CmdAfterEditCheck
from clinescope.diff_coherence import DiffCoherenceScore
from clinescope.diff_minimality import DiffMinimalityScore
from clinescope.editor_newlines import EditorNewlinesCheck
from clinescope.editor_recovery import EditorRecoveryScore
from clinescope.plain_report import plain_report_render
from clinescope.tool_input import ExpectedInput, ToolInputScore
from clinescope.tool_selection import score_tool_selection
from clinescope.world_a import ToolCall, Trace

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
_APPLY_FAIL = _EXAMPLES / "live-gpt-oss-apply-fail.json"
_CLEAN = _EXAMPLES / "live-gpt-oss-trace.json"
_NO_TOOL_CALLS = _EXAMPLES / "corpus" / "llama-code-dump.json"
_EDITOR_RUN = _EXAMPLES / "live-granite-editor-recovery.json"
_NEWLINES = _EXAMPLES / "live-granite-escaped-newlines.json"

_ERASE_LINE = "\x1b[2K\r"


def _stdout(capsys: pytest.CaptureFixture[str], argv: list[str]) -> str:
    assert main(argv) == 0
    return capsys.readouterr().out


# --- the plain view: the four Day 80 cases --------------------------------------

_DEMO_PLAIN = """\
Clinescope found 1 problem in this Cline run.

Problem
- Cline marked the agent's edit to 'validator.py' as failed.
- No later edit to that file went through.

What to do
- Your prompt should tell the agent to retry after a failed edit.
- The agent should re-read the file first.
- Then it should try a corrected edit instead of giving up.

Why
- Clinescope only counts a later edit to the same file with the same tool.
- A fix made another way does not show up in this check.

What went well
- The agent used every tool you listed.
- The agent's first patch follows the format Cline expects.
- No part of the patch was deleted and retyped whole.

Session '1783723826783_g3hi7'
"""


def test_demo_shows_the_problem_what_to_do_why_and_what_went_well(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _stdout(capsys, ["--demo"]) == _DEMO_PLAIN


def test_clean_apply_patch_run_lists_every_passing_check(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _stdout(capsys, [str(_CLEAN), "--expected", "read_files", "apply_patch"])
    assert out == (
        "Clinescope found no problems in the checks below.\n"
        "\n"
        "What went well\n"
        "- The agent used every tool you listed.\n"
        "- The agent's first patch follows the format Cline expects.\n"
        "- No part of the patch was deleted and retyped whole.\n"
        "- No edit failed, so there was nothing to retry.\n"
        "\n"
        "Session '1783709423832_y5y2f'\n"
    )


def test_run_with_no_tool_calls_never_calls_the_missing_patch_malformed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _stdout(
        capsys, [str(_NO_TOOL_CALLS), "--expected", "read_files", "apply_patch"]
    )
    assert out == (
        "Clinescope found 2 problems in this Cline run.\n"
        "\n"
        "Problem 1 of 2\n"
        "- The agent never used apply_patch or read_files.\n"
        "- You listed them as tools the agent should use.\n"
        "\n"
        "What to do\n"
        "- Your prompt should name the tools the agent must use.\n"
        '- One example rule is "Always read a file with read_files before you patch'
        ' it."\n'
        "\n"
        "Why\n"
        "- Clinescope only checks that each tool you listed was called.\n"
        "- It does not check what the agent sent to the tool.\n"
        "\n"
        "Problem 2 of 2\n"
        "- The agent made no edit that Clinescope can check.\n"
        "\n"
        "What to do\n"
        "- If the agent changed files another way, this is expected.\n"
        "- If the task needed an edit and none happened, your prompt should tell the"
        " agent to edit the file with its tools.\n"
        "\n"
        "Why\n"
        "- Clinescope checks the format of only one kind of edit.\n"
        "- This run made no edit of that kind.\n"
        "\n"
        "Did not apply\n"
        "- 2 checks did not apply, because the run had no patch to read.\n"
        "\n"
        "Session '1783823326027_o96p6'\n"
    )
    assert "malformed" not in out


def test_editor_run_shows_the_apply_patch_checks_as_not_applying(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _stdout(capsys, [str(_EDITOR_RUN), "--expected", "read_files", "editor"])
    assert out == (
        "Clinescope found no problems in the checks below.\n"
        "\n"
        "What went well\n"
        "- The agent used every tool you listed.\n"
        "- 1 edit failed, and a later edit to the same file went through.\n"
        "- No editor edit replaced two or more lines with one line that holds the text \\n.\n"
        "\n"
        "Did not apply\n"
        "- 3 checks did not apply, because they only read a kind of edit this run did"
        " not use.\n"
        "\n"
        "Session '1787455395427_4abgw'\n"
    )


# --- the plain view: more problems ----------------------------------------------


def test_two_problems_each_get_what_to_do_and_why(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _stdout(
        capsys,
        [str(_APPLY_FAIL), "--expected", "read_files", "apply_patch", "run_commands"],
    )
    assert out == (
        "Clinescope found 2 problems in this Cline run.\n"
        "\n"
        "Problem 1 of 2\n"
        "- The agent never used run_commands.\n"
        "- You listed it as a tool the agent should use.\n"
        "\n"
        "What to do\n"
        "- Your prompt should name the tools the agent must use.\n"
        '- One example rule is "Always read a file with read_files before you patch'
        ' it."\n'
        "\n"
        "Why\n"
        "- Clinescope only checks that each tool you listed was called.\n"
        "- It does not check what the agent sent to the tool.\n"
        "\n"
        "Problem 2 of 2\n"
        "- Cline marked the agent's edit to 'validator.py' as failed.\n"
        "- No later edit to that file went through.\n"
        "\n"
        "What to do\n"
        "- Your prompt should tell the agent to retry after a failed edit.\n"
        "- The agent should re-read the file first.\n"
        "- Then it should try a corrected edit instead of giving up.\n"
        "\n"
        "Why\n"
        "- Clinescope only counts a later edit to the same file with the same tool.\n"
        "- A fix made another way does not show up in this check.\n"
        "\n"
        "What went well\n"
        "- The agent's first patch follows the format Cline expects.\n"
        "- No part of the patch was deleted and retyped whole.\n"
        "\n"
        "Session '1783723826783_g3hi7'\n"
    )


def test_context_line_problems_get_what_to_do_and_why(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _stdout(capsys, [str(_NEWLINES), "--test-cmd", "pytest"])
    assert out == (
        "Clinescope found 2 problems in this Cline run.\n"
        "\n"
        "Problem 1 of 2\n"
        "- An edit to 'inventory.py' replaced real line breaks with the two characters"
        " \\n.\n"
        "- Cline did not mark that edit as failed.\n"
        "\n"
        "What to do\n"
        "- Open the file named above and check that its line breaks are still in"
        " place.\n"
        "\n"
        "Why\n"
        "- Clinescope did not open the file.\n"
        "- It only saw the shape of the edit.\n"
        "\n"
        "Problem 2 of 2\n"
        '- No command containing "pytest" ran after the last edit.\n'
        "\n"
        "What to do\n"
        "- Run your tests yourself on the final files.\n"
        "- Your prompt can tell the agent to run the tests after its last edit.\n"
        "\n"
        "Why\n"
        '- "The last edit" means the last edit to any file.\n'
        "- A helper file written after the tests can make this wrong.\n"
        "\n"
        "What went well\n"
        "- 1 edit failed, and a later edit to the same file went through.\n"
        "\n"
        "Did not apply\n"
        "- Clinescope did not check tool use, because you listed no tools.\n"
        "- 3 checks did not apply, because they only read a kind of edit this run did"
        " not use.\n"
        "\n"
        "Session '1790447882966_iep7l'\n"
    )


def test_clean_run_has_no_what_to_do(capsys: pytest.CaptureFixture[str]) -> None:
    out = _stdout(capsys, [str(_CLEAN), "--expected", "read_files", "apply_patch"])
    assert "What to do" not in out
    assert "Problem" not in out


def test_plain_view_shows_no_scorer_name_score_or_flag(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _stdout(capsys, ["--demo"])
    for technical in (
        "tool_selection",
        "diff_coherence",
        "diff_minimality",
        "apply_recovery",
        "/100",
        "PASS",
        "FAIL",
        "n/a",
        "--",
    ):
        assert technical not in out


# --- untrusted trace text --------------------------------------------------------


def _trace(*tool_names: str) -> Trace:
    tool_calls = tuple(
        ToolCall(
            id=f"tool-call-{i}",
            name=name,
            input={},
            result_content=None,
            is_error=None,
        )
        for i, name in enumerate(tool_names)
    )
    return Trace(version=1, turns=(), tool_calls=tool_calls, dropped_items=())


def _unrecovered(path: str) -> ApplyRecoveryScore:
    return ApplyRecoveryScore(
        score=0.0,
        applicable=True,
        total_failed_pairs=1,
        confirmed_recovered_pairs=0,
        unrecovered_pairs=1,
        partially_recovered_failures=0,
        same_file_refail_count=0,
        unverified_reattempt_pairs=0,
        verdict_coverage=1.0,
        failed_target_paths=(path,),
        recovery_pairs=(),
        unparseable_failed_calls=0,
        apply_patch_call_count=1,
        violations=(),
        cline_apply_is_error=True,
    )


def test_hostile_file_name_cannot_repaint_the_plain_view() -> None:
    trace = _trace("apply_patch")
    out = plain_report_render(
        score_tool_selection(trace, {"apply_patch"}),
        session_id=f"{_ERASE_LINE}clean-run",
        apply_recovery=_unrecovered(f"C:\\repo\\{_ERASE_LINE}victory.py"),
    )
    assert "\x1b" not in out
    assert "\r" not in out
    assert "'\\x1b[2K\\rvictory.py'" in out
    assert "repo" not in out


@pytest.mark.parametrize(
    "path",
    ["C:\\Users\\user\\repo\\validator.py", "/home/user/repo/validator.py"],
)
def test_plain_view_shows_the_file_name_only(path: str) -> None:
    trace = _trace("apply_patch")
    out = plain_report_render(
        score_tool_selection(trace, {"apply_patch"}),
        session_id="s-1",
        apply_recovery=_unrecovered(path),
    )
    assert "- Cline marked the agent's edit to 'validator.py' as failed." in out
    assert "user" not in out


# --- --details: today's report, with advice on every failing run ------------------

_DEMO_DETAILS = """\
clinescope report - session '1783723826783_g3hi7' (2 tool calls)
tool_selection  100/100  PASS
diff_coherence  100/100  PASS
cline_verdict   rejected   ('apply_patch failed: Patch could not be applied because 1 hunk did not match the current file content.')
diff_minimality 100/100  PASS
apply_recovery    0/100  FAIL   (0/1 failed patches recovered)

advice (how to improve the agent):
  [apply_recovery] no_apply_recovery
    - The agent failed a patch and did not recover it (0/1 recovered; failed files: 'C:\\\\Users\\\\user\\\\clinescope-day11\\\\cap2\\\\repo\\\\validator.py').
    - Add a retry instruction: after a failed apply_patch, re-read the file and try a corrected patch instead of giving up.
"""  # noqa: E501 -- a pinned report line is as wide as the report prints it


def test_details_demo_is_the_demo_report_from_before_the_plain_view(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _stdout(capsys, ["--demo", "--details"]) == _DEMO_DETAILS


def test_details_clean_run_is_the_default_report_from_before_the_plain_view(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _stdout(
        capsys, [str(_CLEAN), "--expected", "read_files", "apply_patch", "--details"]
    )
    assert out == (
        "clinescope report - session '1783709423832_y5y2f' (2 tool calls)\n"
        "tool_selection  100/100  PASS\n"
        "diff_coherence  100/100  PASS\n"
        "cline_verdict   applied\n"
        "diff_minimality 100/100  PASS\n"
        "apply_recovery      n/a  n/a   (no failed patches - nothing to recover)\n"
        "clean run - nothing to fix\n"
    )


def test_details_editor_run_is_the_default_report_from_before_the_plain_view(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _stdout(
        capsys, [str(_EDITOR_RUN), "--expected", "read_files", "editor", "--details"]
    )
    assert out == (
        "clinescope report - session '1787455395427_4abgw' (3 tool calls)\n"
        "note: 0 apply_patch calls, 2 editor calls - the 3 apply_patch checks did not"
        " run\n"
        "tool_selection  100/100  PASS\n"
        "diff_coherence      n/a  n/a   (editor run - no apply_patch to check)\n"
        "diff_minimality     n/a  n/a   (no apply_patch - nothing to check)\n"
        "apply_recovery      n/a  n/a   (no apply_patch - nothing to recover)\n"
        "editor_recovery 100/100  PASS   (1/1 failed edits recovered)\n"
        "clean run - nothing to fix\n"
    )


def test_details_shows_advice_without_the_advice_flag_and_no_false_malformed_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _stdout(
        capsys,
        [str(_NO_TOOL_CALLS), "--expected", "read_files", "apply_patch", "--details"],
    )
    assert out == (
        "clinescope report - session '1783823326027_o96p6' (0 tool calls)\n"
        "tool_selection    0/100   (missing: apply_patch, read_files)\n"
        "diff_coherence    0/100  FAIL   (no apply_patch tool call in trace)\n"
        "diff_minimality     n/a  n/a   (no apply_patch - nothing to check)\n"
        "apply_recovery      n/a  n/a   (no apply_patch - nothing to recover)\n"
        "\n"
        "advice (how to improve the agent):\n"
        "  [tool_selection] missing_tools\n"
        "    - The agent never called: apply_patch, read_files.\n"
        "    - Add to your prompt an instruction to use the right tool for the task"
        " (e.g. 'Always read a file with read_files before you patch it').\n"
        "  [diff_coherence] malformed_patch\n"
        "    - The agent made no edit that Clinescope can check (no apply_patch tool"
        " call in trace).\n"
        "    - If the agent changed files another way, this is expected.\n"
        "    - If the task needed an edit and none happened, your prompt should tell"
        " the agent to edit the file with its tools.\n"
    )


def test_details_gives_advice_for_the_context_line_problems(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _stdout(capsys, [str(_NEWLINES), "--test-cmd", "pytest", "--details"])
    assert out.endswith(
        "advice (how to improve the agent):\n"
        "  [editor_newlines]\n"
        "    - 1 editor call wrote literal \\n where the old text had line breaks"
        " (call 3: 'C:\\\\cs-day65-capture\\\\inventory.py').\n"
        "    - Open the file named above and check that its line breaks are still in"
        " place.\n"
        "  [test_cmd]\n"
        "    - No matching command ran after the last edit.\n"
        "    - Run your tests yourself on the final files.\n"
        "    - Your prompt can tell the agent to run the tests after its last edit.\n"
    )


def test_advice_flag_is_accepted_and_changes_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    argv = [str(_APPLY_FAIL), "--expected", "read_files", "apply_patch"]
    plain = _stdout(capsys, argv)
    assert _stdout(capsys, [*argv, "--advice"]) == plain
    details = _stdout(capsys, [*argv, "--details"])
    assert _stdout(capsys, [*argv, "--details", "--advice"]) == details


def test_verbose_wins_over_details(capsys: pytest.CaptureFixture[str]) -> None:
    argv = [str(_CLEAN), "--expected", "apply_patch", "--verbose"]
    assert _stdout(capsys, [*argv, "--details"]) == _stdout(capsys, argv)


# --- every other result the plain view can show, pinned to the approved wording ---


def _render(**checks: object) -> str:
    trace = _trace("apply_patch")
    return plain_report_render(
        score_tool_selection(trace, {"apply_patch"}),
        session_id="s-1",
        **checks,  # type: ignore[arg-type]
    )


def _coherence(score: float, calls: int) -> DiffCoherenceScore:
    return DiffCoherenceScore(
        score=score,
        passed_gates=frozenset(),
        failed_gates=frozenset(),
        violations=("missing *** End Patch",),
        apply_patch_call_count=calls,
        cline_apply_is_error=None,
    )


def _minimality(score: float, blind: int, hunks: int) -> DiffMinimalityScore:
    return DiffMinimalityScore(
        score=score,
        applicable=True,
        blind_rewrite_hunks=blind,
        hunks_with_body=hunks,
        violations=(),
        mean_context_density=None,
        add_file_lines=0,
        apply_patch_call_count=1,
        cline_apply_is_error=None,
    )


def _apply_recovery(
    *,
    score: float | None,
    total: int = 0,
    unrecovered: int = 0,
    paths: tuple[str, ...] = (),
    coverage: float = 1.0,
) -> ApplyRecoveryScore:
    return ApplyRecoveryScore(
        score=score,
        applicable=score is not None,
        total_failed_pairs=total,
        confirmed_recovered_pairs=total - unrecovered,
        unrecovered_pairs=unrecovered,
        partially_recovered_failures=0,
        same_file_refail_count=0,
        unverified_reattempt_pairs=0,
        verdict_coverage=coverage,
        failed_target_paths=paths,
        recovery_pairs=(),
        unparseable_failed_calls=0,
        apply_patch_call_count=3,
        violations=(),
        cline_apply_is_error=None,
    )


def _editor_recovery(*, score: float, paths: tuple[str, ...]) -> EditorRecoveryScore:
    return EditorRecoveryScore(
        score=score,
        applicable=True,
        total_failed_pairs=1,
        confirmed_recovered_pairs=0,
        unrecovered_pairs=1,
        same_file_refail_count=0,
        unverified_reattempt_pairs=0,
        verdict_coverage=1.0,
        failed_target_paths=paths,
        recovery_pairs=(),
        pathless_failed_calls=0,
        editor_call_count=2,
        violations=(),
        cline_editor_is_error=None,
    )


def _block(*lines: str) -> str:
    return "\n".join(lines)


def test_missing_editor_inputs_are_a_problem_with_new_advice() -> None:
    first = ExpectedInput(tool="editor", key="path", value="calc.py")
    second = ExpectedInput(tool="editor", key="old_text", value="x")
    out = _render(
        tool_input=ToolInputScore(
            score=0.0,
            expected=frozenset({first, second}),
            matched=frozenset(),
            missing=frozenset({first, second}),
        )
    )
    assert (
        _block(
            "Problem",
            "- No editor edit used old_text=x or path=calc.py.",
            "- You named them as inputs the agent should use.",
            "",
            "What to do",
            "- Your prompt should name the input the agent must use.",
            "- For a file, your task should give its path.",
            "",
            "Why",
            "- Clinescope only checks that some editor call carried this input.",
            "- It does not check whether that call worked.",
        )
        in out
    )


def test_found_editor_input_goes_under_what_went_well() -> None:
    found = ExpectedInput(tool="editor", key="path", value="calc.py")
    out = _render(
        tool_input=ToolInputScore(
            score=1.0,
            expected=frozenset({found}),
            matched=frozenset({found}),
            missing=frozenset(),
        )
    )
    assert "- Every input you named was used by some editor edit." in out


def test_malformed_patch_is_a_format_problem_never_a_correctness_one() -> None:
    out = _render(diff_coherence=_coherence(0.75, calls=1))
    assert (
        _block(
            "Problem",
            "- The agent's first patch does not follow the format Cline expects.",
            "",
            "What to do",
            "- Your prompt should include an example of a correct patch.",
            "- You can also try a stronger model.",
            "",
            "Why",
            "- Clinescope reads only the text of the patch.",
            "- It does not check whether the patch fits the file.",
        )
        in out
    )


@pytest.mark.parametrize(
    ("blind", "sentence"),
    [
        (1, "- 1 of 3 changed blocks in the patch was deleted and retyped whole."),
        (2, "- 2 of 3 changed blocks in the patch were deleted and retyped whole."),
    ],
)
def test_retyped_blocks_are_a_problem(blind: int, sentence: str) -> None:
    out = _render(diff_minimality=_minimality(0.5, blind=blind, hunks=3))
    assert (
        _block(
            sentence,
            "",
            "What to do",
            "- Your prompt should tell the agent to change only the lines that must"
            " change.",
            "- It should keep the lines around them as they are.",
            "",
            "Why",
            "- This check finds only one kind of oversized edit.",
            "- A large rewrite is sometimes needed.",
        )
        in out
    )


def test_unreadable_patch_does_not_count_as_a_retyped_block() -> None:
    out = _render(diff_minimality=_minimality(0.0, blind=0, hunks=0))
    assert "Problem" not in out
    assert (
        "- Clinescope could not look for retyped blocks, because it could not read"
        " the patch." in out
    )


def test_some_failed_edits_recovered_and_some_did_not() -> None:
    out = _render(
        apply_recovery=_apply_recovery(
            score=2 / 3, total=3, unrecovered=1, paths=("C:\\r\\a.py", "/r/b.py")
        )
    )
    assert (
        _block(
            "Problem",
            "- Cline marked the agent's edits to 'a.py' and 'b.py' as failed.",
            "- For some of those files, a failed edit had no later edit to the same"
            " file that went through.",
        )
        in out
    )


def test_no_failed_edit_recovered_across_several_files() -> None:
    out = _render(
        apply_recovery=_apply_recovery(
            score=0.0, total=2, unrecovered=2, paths=("a.py", "b.py")
        )
    )
    assert (
        _block(
            "- Cline marked the agent's edits to 'a.py' and 'b.py' as failed.",
            "- No later edit to those files went through.",
        )
        in out
    )


def test_one_failed_patch_touching_three_files_is_not_counted_as_three_edits() -> None:
    # total_failed_pairs counts each failed FILE of each failed call, so one patch
    # touching three files is three pairs. The sentence must not call it three edits.
    out = _render(
        apply_recovery=_apply_recovery(
            score=0.0, total=3, unrecovered=3, paths=("a.py", "b.py", "c.py")
        )
    )
    assert (
        _block(
            "- Cline marked the agent's edits to 'a.py', 'b.py' and 'c.py' as failed.",
            "- No later edit to those files went through.",
        )
        in out
    )
    assert "3 of the agent's edits" not in out


@pytest.mark.parametrize(
    ("paths", "lines"),
    [
        (
            ("a.py",),
            (
                "- Cline marked the agent's edits to 'a.py' as failed.",
                "- No later edit to that file went through.",
            ),
        ),
        (
            ("<unparseable>",),
            (
                "- Cline marked several of the agent's edits as failed.",
                "- Clinescope could not tell which file some of them were for.",
                "- No later edit to those files went through.",
            ),
        ),
    ],
)
def test_two_failed_edits_with_one_or_no_named_file(
    paths: tuple[str, ...], lines: tuple[str, ...]
) -> None:
    out = _render(
        apply_recovery=_apply_recovery(score=0.0, total=2, unrecovered=2, paths=paths)
    )
    assert _block(*lines) in out


def test_several_unreadable_failed_edits_say_so() -> None:
    out = _render(
        apply_recovery=_apply_recovery(
            score=0.0, total=2, unrecovered=2, paths=("<unparseable>", "a.py")
        )
    )
    assert (
        _block(
            "- Cline marked the agent's edits to 'a.py' as failed.",
            "- Clinescope could not tell which file some of them were for.",
            "- No later edit to those files went through.",
        )
        in out
    )


def test_failed_edit_with_no_readable_file_says_so() -> None:
    out = _render(
        apply_recovery=_apply_recovery(
            score=0.0, total=1, unrecovered=1, paths=("<unparseable>",)
        )
    )
    assert (
        _block(
            "- Cline marked the agent's edit as failed.",
            "- Clinescope could not tell which file that edit was for.",
        )
        in out
    )
    assert "unparseable" not in out


@pytest.mark.parametrize(
    ("paths", "sentence"),
    [
        (
            ("a.py",),
            "- Edits to 'a.py' failed, and that file later got an edit that went"
            " through.",
        ),
        (
            ("a.py", "b.py"),
            "- Edits to 'a.py' and 'b.py' failed, and each of those files later got"
            " an edit that went through.",
        ),
    ],
)
def test_several_recovered_failures_go_under_what_went_well(
    paths: tuple[str, ...], sentence: str
) -> None:
    out = _render(apply_recovery=_apply_recovery(score=1.0, total=2, paths=paths))
    assert sentence in out
    assert "2 edits" not in out


def test_retries_without_any_cline_verdict_did_not_apply() -> None:
    out = _render(apply_recovery=_apply_recovery(score=None, coverage=0.0))
    assert (
        "- Clinescope could not check retries, because Cline recorded no pass or fail"
        " for any edit." in out
    )


def test_failed_editor_edit_adds_the_known_cause() -> None:
    out = _render(
        editor_recovery=_editor_recovery(score=0.0, paths=("C:\\r\\calc.py",))
    )
    assert (
        _block(
            "- Cline marked the agent's edit to 'calc.py' as failed.",
            "- No later edit to that file went through.",
            "",
            "What to do",
            "- Your prompt should tell the agent to retry after a failed edit.",
            "- The agent should re-read the file first.",
            "- Then it should try a corrected edit instead of giving up.",
            "- One known cause is an edit that leaves out the old text on a file that"
            " already exists.",
        )
        in out
    )


def test_several_flattened_edits_name_each_file() -> None:
    out = _render(editor_newlines=EditorNewlinesCheck(hits=((1, "a.py"), (4, None))))
    assert (
        _block(
            "- 2 edits replaced real line breaks with the two characters \\n.",
            "- They were edits to 'a.py'.",
            "- Cline did not mark those edits as failed.",
            "",
            "What to do",
            "- Open each file named above and check that its line breaks are still in"
            " place.",
        )
        in out
    )


def test_flattened_edit_with_no_path_still_shows() -> None:
    out = _render(editor_newlines=EditorNewlinesCheck(hits=((3, None),)))
    assert "- An edit replaced real line breaks with the two characters \\n." in out


def test_test_command_cline_marked_failed_is_a_problem() -> None:
    out = _render(
        test_cmd=CmdAfterEditCheck(status="ran", command_index=5, success=False),
        test_cmd_text="pytest",
    )
    assert (
        _block(
            "Problem",
            '- A command containing "pytest" ran after the last edit.',
            "- Cline marked that command as failed.",
            "",
            "What to do",
            "- Read the command's output in the Cline run to see what failed.",
            "- Run your tests yourself on the final files.",
            "",
            "Why",
            "- Cline keeps one result for a whole command line.",
            "- So this result can be wrong in either direction.",
        )
        in out
    )


@pytest.mark.parametrize(
    ("check", "group", "sentence"),
    [
        (
            CmdAfterEditCheck(status="ran", command_index=5, success=True),
            "What went well",
            '- A command containing "pytest" ran after the last edit, and Cline'
            " recorded success.",
        ),
        (
            CmdAfterEditCheck(status="ran", command_index=5, success=None),
            "Did not apply",
            '- A command containing "pytest" ran after the last edit, but Cline'
            " recorded no result for it.",
        ),
        (
            CmdAfterEditCheck(status="no_edit"),
            "Did not apply",
            "- Clinescope could not check the test command, because the run made no"
            " edit.",
        ),
        (
            CmdAfterEditCheck(status="every_edit_failed"),
            "Did not apply",
            "- Clinescope could not check the test command, because every edit failed.",
        ),
        (
            CmdAfterEditCheck(status="execute_command"),
            "Did not apply",
            "- Clinescope could not check the test command, because this run ran"
            " commands in a way Clinescope does not read.",
        ),
    ],
)
def test_test_command_results_that_are_not_problems(
    check: CmdAfterEditCheck, group: str, sentence: str
) -> None:
    out = _render(test_cmd=check, test_cmd_text="pytest")
    assert "Problem" not in out
    assert f"{group}\n" in out
    assert sentence in out


def test_extension_session_line_starts_with_a_capital() -> None:
    trace = _trace("apply_patch")
    out = plain_report_render(
        score_tool_selection(trace, {"apply_patch"}),
        session_label="extension session 1000 'Fix it' [Code]",
    )
    assert out.splitlines()[-1] == "Extension session 1000 'Fix it' [Code]"
