"""Pins the plain-English output of ``compare`` and ``clinescope-corpus``.

Each run gets one line (its problems, then how many checks went well or did not
apply) and one bullet per problem. Under the runs, each kind of problem gets one
What to do and one Why, naming the runs it applies to. ``--details`` keeps the
technical tables exactly as they were.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from clinescope import compare, corpus
from clinescope.compare import render_compare_report, run_compare
from clinescope.corpus import render_corpus_report, run_corpus
from clinescope.plain_report import PlainProblem, PlainResults, plain_run_lines

_ROOT = Path(__file__).resolve().parent.parent
_EXAMPLES = _ROOT / "examples"
_CLEAN = _EXAMPLES / "live-gpt-oss-trace.json"
_NO_EDIT = _EXAMPLES / "corpus" / "llama-code-dump.json"
_QWEN = _EXAMPLES / "corpus" / "qwen-missing-tools.json"
_EDITOR = _EXAMPLES / "live-granite-editor-recovery.json"
_APPLY_FAIL = _EXAMPLES / "live-gpt-oss-apply-fail.json"
_CORPUS_APPLY_FAIL = _EXAMPLES / "corpus" / "live-gpt-oss-apply-fail.json"
_CORPUS_CLEAN = _EXAMPLES / "corpus" / "live-gpt-oss-trace.json"

_NO_EDIT_BLOCK = (
    "What to do\n"
    "- If the agent changed files another way, this is expected.\n"
    "- If the task needed an edit and none happened, your prompt should tell the agent"
    " to edit the file with its tools.\n"
    "\n"
    "Why\n"
    "- Clinescope checks the format of only one kind of edit.\n"
    "- Clinescope found no edit of that kind.\n"
)
_RETRY_BLOCK = (
    "What to do\n"
    "- Your prompt should tell the agent to retry after a failed edit.\n"
    "- The agent should re-read the file first.\n"
    "- Then it should try a corrected edit instead of giving up.\n"
    "\n"
    "Why\n"
    "- Clinescope only counts a later edit to the same file with the same tool.\n"
    "- A fix made another way does not show up in this check.\n"
)
_TOOLS_BLOCK = (
    "What to do\n"
    "- Your prompt should name the tools the agent must use.\n"
    '- One example rule is "Always read a file with read_files before you patch it."\n'
    "\n"
    "Why\n"
    "- Clinescope only checks that each tool you listed was called.\n"
    "- It does not check what the agent sent to the tool.\n"
)
_APPLY_FAIL_PROBLEM = (
    "- Cline marked the agent's edit to 'validator.py' as failed. No later edit to"
    " that file went through.\n"
)
_TOOLS_PROBLEM = (
    "- The agent never used apply_patch or read_files. You listed them as tools the"
    " agent should use.\n"
)


def _labels(tmp_path: Path, entries: Mapping[Path, Mapping[str, object]]) -> Path:
    manifest = tmp_path / "labels.json"
    manifest.write_text(
        json.dumps({str(path): label for path, label in entries.items()}),
        encoding="utf-8",
    )
    return manifest


def _run(
    module_main: object, argv: list[str], capsys: pytest.CaptureFixture[str]
) -> tuple[int, str]:
    code = module_main(argv)  # type: ignore[operator]
    return code, capsys.readouterr().out


# --- compare -------------------------------------------------------------------


def test_compare_lists_each_run_then_one_advice_block_per_kind(
    capsys: pytest.CaptureFixture[str],
) -> None:
    traces = [_CLEAN, _NO_EDIT, _EDITOR, _APPLY_FAIL]
    code, out = _run(compare.main, [str(path) for path in traces], capsys)
    assert code == 0
    assert out == (
        "Clinescope compared 4 Cline runs and found problems in 2 of them.\n"
        "\n"
        "live-gpt-oss-trace: no problems. 3 checks went well, and 1 did not apply.\n"
        "\n"
        "llama-code-dump: 1 problem. 3 checks did not apply.\n"
        "- The agent made no edit that Clinescope can check.\n"
        "\n"
        "live-granite-editor-recovery: no problems. 1 check went well, and 4 did not"
        " apply.\n"
        "\n"
        "live-gpt-oss-apply-fail: 1 problem. 2 checks went well, and 1 did not apply.\n"
        f"{_APPLY_FAIL_PROBLEM}"
        "\n"
        "No edit that Clinescope can check\n"
        "Runs: llama-code-dump\n"
        "\n"
        f"{_NO_EDIT_BLOCK}"
        "\n"
        "A failed patch with no later patch that went through\n"
        "Runs: live-gpt-oss-apply-fail\n"
        "\n"
        f"{_RETRY_BLOCK}"
    )


def test_compare_names_every_run_a_shared_kind_applies_to(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    expected = {"expected_tools": ["read_files", "apply_patch"]}
    manifest = _labels(tmp_path, {_QWEN: expected, _NO_EDIT: expected})
    argv = [str(_QWEN), str(_NO_EDIT), "--labels", str(manifest)]
    code, out = _run(compare.main, argv, capsys)
    assert code == 0
    assert out == (
        "Clinescope compared 2 Cline runs and found problems in 2 of them.\n"
        "\n"
        "qwen-missing-tools: 2 problems. 2 checks did not apply.\n"
        f"{_TOOLS_PROBLEM}"
        "- The agent made no edit that Clinescope can check.\n"
        "\n"
        "llama-code-dump: 2 problems. 2 checks did not apply.\n"
        f"{_TOOLS_PROBLEM}"
        "- The agent made no edit that Clinescope can check.\n"
        "\n"
        "Tools you listed were not used\n"
        "Runs: qwen-missing-tools and llama-code-dump\n"
        "\n"
        f"{_TOOLS_BLOCK}"
        "\n"
        "No edit that Clinescope can check\n"
        "Runs: qwen-missing-tools and llama-code-dump\n"
        "\n"
        f"{_NO_EDIT_BLOCK}"
    )


def test_compare_of_one_clean_run_has_no_advice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _labels(tmp_path, {_CLEAN: {"expected_tools": ["read_files"]}})
    code, out = _run(compare.main, [str(_CLEAN), "--labels", str(manifest)], capsys)
    assert code == 0
    assert out == (
        "Clinescope compared 1 Cline run and found no problems.\n"
        "\n"
        "live-gpt-oss-trace: no problems. 4 checks went well.\n"
    )


def test_compare_of_one_failing_run_says_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out = _run(compare.main, [str(_NO_EDIT)], capsys)
    assert code == 0
    assert out.startswith("Clinescope compared 1 Cline run and found problems in it.\n")


def test_compare_shows_an_unreadable_run_as_a_problem_and_keeps_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("not json", encoding="utf-8")
    code, out = _run(compare.main, [str(_CLEAN), str(broken)], capsys)
    assert code == 2
    assert out == (
        "Clinescope compared 2 Cline runs and found problems in 1 of them.\n"
        "\n"
        "live-gpt-oss-trace: no problems. 3 checks went well, and 1 did not apply.\n"
        "\n"
        "broken: 1 problem.\n"
        "- Clinescope could not read this run.\n"
        "\n"
        "Runs Clinescope could not read\n"
        "Runs: broken\n"
        "\n"
        "What to do\n"
        "- Check that the file exists and is a log the Cline CLI wrote.\n"
        "\n"
        "Why\n"
        "- This command reads only the log format the Cline CLI writes.\n"
    )


def test_compare_details_prints_todays_table(
    capsys: pytest.CaptureFixture[str],
) -> None:
    traces = [_CLEAN, _NO_EDIT, _EDITOR, _APPLY_FAIL]
    code, out = _run(
        compare.main, [*[str(path) for path in traces], "--details"], capsys
    )
    assert code == 0
    assert out == render_compare_report(run_compare(traces)) + "\n"


# --- corpus --------------------------------------------------------------------


def test_corpus_lists_each_run_as_expected_then_the_advice(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out = _run(corpus.main, [], capsys)
    assert code == 0
    qwen = "qwen2.5-coder:1.5b hallucinated-tool (no apply_patch)"
    llama = "llama3.1:8b code-dump (no apply_patch)"
    assert out == (
        "Clinescope scored 6 example runs and compared each with its expected result.\n"
        "All 6 runs matched their expected result.\n"
        "\n"
        "gpt-oss:20b update-1hunk (clean): no problems, as expected. 4 checks went"
        " well.\n"
        "\n"
        "gpt-oss:20b add-file (clean): no problems, as expected. 4 checks went well.\n"
        "\n"
        "gpt-oss:20b update-2hunk (clean): no problems, as expected. 4 checks went"
        " well.\n"
        "\n"
        "gpt-oss:20b apply-fail (no recovery): 1 problem, as expected. 3 checks went"
        " well.\n"
        f"{_APPLY_FAIL_PROBLEM}"
        "\n"
        f"{qwen}: 2 problems, as expected. 2 checks did not apply.\n"
        f"{_TOOLS_PROBLEM}"
        "- The agent made no edit that Clinescope can check.\n"
        "\n"
        f"{llama}: 2 problems, as expected. 2 checks did not apply.\n"
        f"{_TOOLS_PROBLEM}"
        "- The agent made no edit that Clinescope can check.\n"
        "\n"
        "The example runs show 3 of the 5 kinds of failure Clinescope names: a missing"
        " or badly formed patch (2 runs), tools you listed were not used (2 runs) and a"
        " failed patch with no later patch that went through (1 run).\n"
        "\n"
        "A failed patch with no later patch that went through\n"
        "Runs: gpt-oss:20b apply-fail (no recovery)\n"
        "\n"
        f"{_RETRY_BLOCK}"
        "\n"
        "Tools you listed were not used\n"
        f"Runs: {qwen} and {llama}\n"
        "\n"
        f"{_TOOLS_BLOCK}"
        "\n"
        "No edit that Clinescope can check\n"
        f"Runs: {qwen} and {llama}\n"
        "\n"
        f"{_NO_EDIT_BLOCK}"
    )


def test_corpus_names_a_run_that_did_not_match_and_keeps_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tools = ["read_files", "apply_patch"]
    manifest = _labels(
        tmp_path,
        {
            _CORPUS_CLEAN: {
                "display": "clean run",
                "kind": "clean",
                "expected_tools": tools,
                "scorers": {"tool_selection": {"expected_cell": "100/100"}},
            },
            _CORPUS_APPLY_FAIL: {
                "display": "apply-fail run",
                "expected_tools": tools,
                "scorers": {"apply_recovery": {"expected_cell": "100/100"}},
            },
        },
    )
    code, out = _run(corpus.main, [str(manifest)], capsys)
    assert code == 1
    assert out == (
        "Clinescope scored 2 example runs and compared each with its expected result.\n"
        "1 of 2 runs matched their expected result.\n"
        "\n"
        "clean run: no problems, as expected. 4 checks went well.\n"
        "\n"
        "apply-fail run: 1 problem. It did not match its expected result. 3 checks went"
        " well.\n"
        f"{_APPLY_FAIL_PROBLEM}"
        "\n"
        "The example runs show 1 of the 5 kinds of failure Clinescope names: a failed"
        " patch with no later patch that went through (1 run).\n"
        "\n"
        "A failed patch with no later patch that went through\n"
        "Runs: apply-fail run\n"
        "\n"
        f"{_RETRY_BLOCK}"
        "\n"
        "Runs that did not match their expected result\n"
        "Runs: apply-fail run\n"
        "\n"
        "What to do\n"
        "- The details view shows which result differs.\n"
        "- Find the change that made a check give a different answer.\n"
        "\n"
        "Why\n"
        "- Each example run has a fixed expected result, written by hand.\n"
        "- A difference means a check now answers differently for that run.\n"
    )


def test_corpus_of_one_run_says_it_and_shows_an_unreadable_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _labels(tmp_path, {tmp_path / "missing.json": {"display": "gone"}})
    code, out = _run(corpus.main, [str(manifest)], capsys)
    assert code == 2
    assert out == (
        "Clinescope scored 1 example run and compared it with its expected result.\n"
        "The run did not match its expected result.\n"
        "\n"
        "gone: 1 problem.\n"
        "- Clinescope could not read this run.\n"
        "\n"
        "Runs Clinescope could not read\n"
        "Runs: gone\n"
        "\n"
        "What to do\n"
        "- Check that the file exists and is a log the Cline CLI wrote.\n"
        "\n"
        "Why\n"
        "- This command reads only the log format the Cline CLI writes.\n"
    )


def test_corpus_of_one_matching_run_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _labels(tmp_path, {_CORPUS_CLEAN: {"display": "clean run"}})
    code, out = _run(corpus.main, [str(manifest)], capsys)
    assert code == 0
    assert out.startswith(
        "Clinescope scored 1 example run and compared it with its expected result.\n"
        "The run matched its expected result.\n"
    )


def test_an_empty_corpus_says_so_and_keeps_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _labels(tmp_path, {})
    code, out = _run(corpus.main, [str(manifest)], capsys)
    assert code == 2
    assert out == "Clinescope found no runs to score in this corpus.\n"


def test_corpus_details_prints_todays_report(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out = _run(corpus.main, ["--details"], capsys)
    assert code == 0
    report = run_corpus(_EXAMPLES / "corpus" / "corpus.json", base_dir=_ROOT)
    assert out == render_corpus_report(report) + "\n"


# --- the run line on its own ------------------------------------------------------


def test_a_run_whose_every_check_is_a_problem_has_no_count_sentence() -> None:
    problem = PlainProblem("Kind", ("One.", "Two."), ("Do.",), ("Because.",))
    lines = plain_run_lines("run", PlainResults(problems=[problem]))
    assert lines == ["run: 1 problem.", "- One. Two."]
