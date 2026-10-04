"""Plain-English report: the default output of the ``clinescope`` CLI.

The reader is a Cline user who has never opened the README, so this view names no
scorer, shows no score and no flag, and uses whole sentences. ``--details`` keeps the
technical report (:func:`clinescope.report.render_report`).

Every check that ran is shown exactly once, in report order, as one of three things:

* a **problem**, with what to do (from :mod:`clinescope.advice`) and why (the check's
  limit, as ``LIMITATIONS.md`` states it), so a problem is never shown without a next
  step;
* a line under **What went well**;
* a line under **Did not apply**, for a check that did not run. That is never shown
  as good or bad, because "did not run" is not "failed".

Every sentence stays inside what its check measures. A recovered edit "went through";
it is never "fixed". A passing patch "follows the format Cline expects"; it is never
"correct".

Trace text (a file name, the session id) is neutralized with
:func:`clinescope.render_safety.quote_untrusted_text` where it is read. A file shows as
its name only; the full path stays in ``--details``. The operator's own text (tool
names after ``--expected``, ``--expected-input`` values, the ``--test-cmd`` text) is
shown as typed, the same rule the technical report follows.

``compare`` and ``clinescope-corpus`` build the same :class:`PlainResults` per run and
lay them out with :func:`plain_run_lines` and :func:`plain_kind_blocks`, so a run reads
the same in a table as on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PureWindowsPath

from clinescope.advice import (
    ScorerAdvice,
    advice_for_diff_coherence,
    advice_for_editor_newlines,
    advice_for_test_cmd,
    advice_for_tool_input,
)
from clinescope.apply_recovery import _UNPARSEABLE, ApplyRecoveryScore
from clinescope.cmd_after_edit import CmdAfterEditCheck
from clinescope.diff_coherence import DiffCoherenceScore
from clinescope.diff_minimality import DiffMinimalityScore
from clinescope.editor_newlines import EditorNewlinesCheck
from clinescope.editor_recovery import _PATHLESS, EditorRecoveryScore
from clinescope.render_safety import quote_untrusted_text
from clinescope.report import _header_subject, is_editor_run
from clinescope.tool_input import ToolInputScore
from clinescope.tool_selection import ToolSelectionScore

_WHY_TOOLS = (
    "Clinescope only checks that each tool you listed was called.",
    "It does not check what the agent sent to the tool.",
)
_WHY_INPUTS = (
    "Clinescope only checks that some editor call carried this input.",
    "It does not check whether that call worked.",
)
_WHY_NO_EDIT = (
    "Clinescope checks the format of only one kind of edit.",
    "Clinescope found no edit of that kind.",
)
_WHY_FORMAT = (
    "Clinescope reads only the text of the patch.",
    "It does not check whether the patch fits the file.",
)
_WHY_RETYPED = (
    "This check finds only one kind of oversized edit.",
    "A large rewrite is sometimes needed.",
)
_WHY_RETRY = (
    "Clinescope only counts a later edit to the same file with the same tool.",
    "A fix made another way does not show up in this check.",
)
_WHY_NEWLINES = (
    "Clinescope did not open the file.",
    "It only saw the shape of the edit.",
)
_WHY_NOT_RUN = (
    '"The last edit" means the last edit to any file.',
    "A helper file written after the tests can make this wrong.",
)
_WHY_CMD_FAILED = (
    "Cline keeps one result for a whole command line.",
    "So this result can be wrong in either direction.",
)

# The five labelled advice entries keep their technical wording for --details, so the
# plain view says the same thing in its own words here.
_DO_TOOLS = (
    "Your prompt should name the tools the agent must use.",
    'One example rule is "Always read a file with read_files before you patch it."',
)
_DO_FORMAT = (
    "Your prompt should include an example of a correct patch.",
    "You can also try a stronger model.",
)
_DO_RETYPED = (
    "Your prompt should tell the agent to change only the lines that must change.",
    "It should keep the lines around them as they are.",
)
_DO_RETRY = (
    "Your prompt should tell the agent to retry after a failed edit.",
    "The agent should re-read the file first.",
    "Then it should try a corrected edit instead of giving up.",
)
_DO_EDITOR_RETRY_CAUSE = (
    "One known cause is an edit that leaves out the old text on a file that "
    "already exists."
)

_NO_RETRY_NEEDED = "No edit failed, so there was nothing to retry."
_NO_VERDICTS = (
    "Clinescope could not check retries, because Cline recorded no pass or fail for "
    "any edit."
)


@dataclass(frozen=True, slots=True)
class PlainProblem:
    """One problem: a short name for its kind, its sentences, what to do, and why.

    A table groups problems that share all of ``kind``, ``what_to_do`` and ``why``
    into one advice block.
    """

    kind: str
    problem: tuple[str, ...]
    what_to_do: tuple[str, ...]
    why: tuple[str, ...]


@dataclass(slots=True)
class PlainResults:
    """Every check that ran, sorted into problems, what went well, and what did not apply.

    ``skipped`` counts the checks behind the "Did not apply" sentences, because one
    sentence can cover several checks.
    """

    problems: list[PlainProblem] = field(default_factory=list)
    went_well: list[str] = field(default_factory=list)
    did_not_apply: list[str] = field(default_factory=list)
    skipped: int = 0

    def skip(self, sentence: str, checks: int = 1) -> None:
        self.did_not_apply.append(sentence)
        self.skipped += checks


PLAIN_UNREADABLE = PlainProblem(
    "Runs Clinescope could not read",
    ("Clinescope could not read this run.",),
    ("Check that the file exists and is a log the Cline CLI wrote.",),
    ("This command reads only the log format the Cline CLI writes.",),
)


def plain_report_render(
    score: ToolSelectionScore,
    *,
    session_id: str | None = None,
    session_label: str | None = None,
    diff_coherence: DiffCoherenceScore | None = None,
    diff_minimality: DiffMinimalityScore | None = None,
    apply_recovery: ApplyRecoveryScore | None = None,
    editor_recovery: EditorRecoveryScore | None = None,
    tool_input: ToolInputScore | None = None,
    test_cmd: CmdAfterEditCheck | None = None,
    test_cmd_text: str = "",
    editor_newlines: EditorNewlinesCheck | None = None,
    expected_provided: bool = True,
) -> str:
    """Render the plain-English report from the same scores ``render_report`` takes,
    plus the ``--test-cmd`` text, which the technical report never prints."""
    results = plain_report_results(
        score,
        diff_coherence=diff_coherence,
        diff_minimality=diff_minimality,
        apply_recovery=apply_recovery,
        editor_recovery=editor_recovery,
        tool_input=tool_input,
        test_cmd=test_cmd,
        test_cmd_text=test_cmd_text,
        editor_newlines=editor_newlines,
        expected_provided=expected_provided,
    )
    subject = _header_subject(session_id, session_label)
    return _plain_layout(results, subject[:1].upper() + subject[1:])


def plain_report_results(
    score: ToolSelectionScore,
    *,
    diff_coherence: DiffCoherenceScore | None = None,
    diff_minimality: DiffMinimalityScore | None = None,
    apply_recovery: ApplyRecoveryScore | None = None,
    editor_recovery: EditorRecoveryScore | None = None,
    tool_input: ToolInputScore | None = None,
    test_cmd: CmdAfterEditCheck | None = None,
    test_cmd_text: str = "",
    editor_newlines: EditorNewlinesCheck | None = None,
    expected_provided: bool = True,
) -> PlainResults:
    """Sort every check that was given into problems, what went well, and what did
    not apply. A check passed as ``None`` is left out, as in the report."""
    results = PlainResults()
    _plain_tool_selection(results, score, expected_provided)
    if tool_input is not None:
        _plain_tool_input(results, tool_input)
    if diff_coherence is not None and is_editor_run(diff_coherence, editor_recovery):
        _plain_editor_run_skips(
            results, diff_coherence, diff_minimality, apply_recovery
        )
    else:
        _plain_apply_patch_family(
            results, diff_coherence, diff_minimality, apply_recovery
        )
    if editor_recovery is not None:
        _plain_recovery(results, editor_recovery, _PATHLESS, editor=True)
    if editor_newlines is not None:
        _plain_editor_newlines(results, editor_newlines)
    if test_cmd is not None:
        _plain_test_cmd(results, test_cmd, test_cmd_text)
    return results


# --- one function per check ---------------------------------------------------


def _plain_tool_selection(
    results: PlainResults, score: ToolSelectionScore, expected_provided: bool
) -> None:
    if not expected_provided:
        results.skip("Clinescope did not check tool use, because you listed no tools.")
        return
    if not score.missing:
        results.went_well.append("The agent used every tool you listed.")
        return
    missing = sorted(score.missing)
    listed = (
        "You listed it as a tool the agent should use."
        if len(missing) == 1
        else "You listed them as tools the agent should use."
    )
    results.problems.append(
        PlainProblem(
            "Tools you listed were not used",
            (f"The agent never used {_plain_or_list(missing)}.", listed),
            _DO_TOOLS,
            _WHY_TOOLS,
        )
    )


def _plain_tool_input(results: PlainResults, score: ToolInputScore) -> None:
    advice = advice_for_tool_input(score)
    if advice is None:
        results.went_well.append("Every input you named was used by some editor edit.")
        return
    missing = [f"{item.key}={item.value}" for item in sorted(score.missing)]
    named = (
        "You named it as an input the agent should use."
        if len(missing) == 1
        else "You named them as inputs the agent should use."
    )
    results.problems.append(
        PlainProblem(
            "Inputs you named were not used",
            (f"No editor edit used {_plain_or_list(missing)}.", named),
            _plain_steps(advice),
            _WHY_INPUTS,
        )
    )


def _plain_editor_run_skips(
    results: PlainResults,
    diff_coherence: DiffCoherenceScore,
    diff_minimality: DiffMinimalityScore | None,
    apply_recovery: ApplyRecoveryScore | None,
) -> None:
    count = sum(
        1
        for check in (diff_coherence, diff_minimality, apply_recovery)
        if check is not None
    )
    results.skip(
        f"{_plain_count(count, 'check')} did not apply, because they only read a kind "
        "of edit this run did not use.",
        count,
    )


def _plain_apply_patch_family(
    results: PlainResults,
    diff_coherence: DiffCoherenceScore | None,
    diff_minimality: DiffMinimalityScore | None,
    apply_recovery: ApplyRecoveryScore | None,
) -> None:
    # A score below 1 with no retyped block is the hard zero for a patch that could not
    # be read. The same patch fails the format check, so that problem tells it.
    unreadable = (
        diff_minimality is not None
        and diff_minimality.apply_patch_call_count > 0
        and diff_minimality.score != 1.0
        and diff_minimality.blind_rewrite_hunks == 0
    )
    if diff_coherence is not None:
        _plain_diff_coherence(results, diff_coherence, unreadable=unreadable)
    no_patch = 0
    if diff_minimality is not None:
        if diff_minimality.apply_patch_call_count == 0:
            no_patch += 1
        elif not unreadable:
            _plain_diff_minimality(results, diff_minimality)
    if apply_recovery is not None:
        if apply_recovery.apply_patch_call_count == 0:
            no_patch += 1
        else:
            _plain_recovery(results, apply_recovery, _UNPARSEABLE, editor=False)
    if no_patch:
        results.skip(
            f"{_plain_count(no_patch, 'check')} did not apply, because the run had no "
            "patch to read.",
            no_patch,
        )


def _plain_diff_coherence(
    results: PlainResults, score: DiffCoherenceScore, *, unreadable: bool
) -> None:
    if score.score == 1.0:
        results.went_well.append(
            "The agent's first patch follows the format Cline expects."
        )
        return
    if score.apply_patch_call_count == 0:
        advice = advice_for_diff_coherence(score)
        results.problems.append(
            PlainProblem(
                "No edit that Clinescope can check",
                ("The agent made no edit that Clinescope can check.",),
                _plain_steps(advice),
                _WHY_NO_EDIT,
            )
        )
        return
    problem: tuple[str, ...] = (
        "The agent's first patch does not follow the format Cline expects.",
    )
    if unreadable:
        problem += (
            "Clinescope could not read it, so the check for retyped blocks failed too.",
        )
    results.problems.append(
        PlainProblem(
            "A patch that does not follow the format Cline expects",
            problem,
            _DO_FORMAT,
            _WHY_FORMAT,
        )
    )


def _plain_diff_minimality(results: PlainResults, score: DiffMinimalityScore) -> None:
    if score.score == 1.0:
        results.went_well.append("No part of the patch was deleted and retyped whole.")
        return
    count = score.blind_rewrite_hunks
    verb = "was" if count == 1 else "were"
    results.problems.append(
        PlainProblem(
            "Blocks deleted and retyped whole",
            (
                f"{count} of {score.hunks_with_body} changed blocks in the patch "
                f"{verb} deleted and retyped whole.",
            ),
            _DO_RETYPED,
            _WHY_RETYPED,
        )
    )


def _plain_recovery(
    results: PlainResults,
    score: ApplyRecoveryScore | EditorRecoveryScore,
    sentinel: str,
    *,
    editor: bool,
) -> None:
    if not score.applicable:
        if score.verdict_coverage == 0:
            results.skip(_NO_VERDICTS)
        else:
            results.went_well.append(_NO_RETRY_NEEDED)
        return
    # The counts are per (call, file) pair, so one failed apply_patch touching three
    # files counts three. The sentences therefore name the files and never count
    # edits, except for a single pair, which is one call on one file.
    # failed_target_paths lists every failed file, recovered or not.
    total = score.total_failed_pairs
    names = [
        _plain_file_name(path) for path in score.failed_target_paths if path != sentinel
    ]
    if score.score == 1.0:
        results.went_well.append(_plain_recovered_sentence(total, names))
        return
    unnamed = len(names) < len(score.failed_target_paths)
    steps: tuple[str, ...]
    if editor:
        kind = "A failed editor edit with no later editor edit that went through"
        steps = (*_DO_RETRY, _DO_EDITOR_RETRY_CAUSE)
    else:
        kind = "A failed patch with no later patch that went through"
        steps = _DO_RETRY
    results.problems.append(
        PlainProblem(
            kind,
            _plain_recovery_problem(total, score.unrecovered_pairs, names, unnamed),
            steps,
            _WHY_RETRY,
        )
    )


def _plain_recovered_sentence(total: int, names: list[str]) -> str:
    # A score of 1.0 means every pair was recovered, and a pair with no readable file
    # never is, so every failed file is named here.
    if total == 1:
        return "1 edit failed, and a later edit to the same file went through."
    if len(names) == 1:
        return (
            f"Edits to {names[0]} failed, and that file later got an edit that went "
            "through."
        )
    return (
        f"Edits to {_plain_and_list(names)} failed, and each of those files later got "
        "an edit that went through."
    )


def _plain_recovery_problem(
    total: int, unrecovered: int, names: list[str], unnamed: bool
) -> tuple[str, ...]:
    if total == 1:
        if not names:
            return (
                "Cline marked the agent's edit as failed.",
                "Clinescope could not tell which file that edit was for.",
            )
        return (
            f"Cline marked the agent's edit to {names[0]} as failed.",
            "No later edit to that file went through.",
        )
    if names:
        lines = [
            f"Cline marked the agent's edits to {_plain_and_list(names)} as failed."
        ]
    else:
        lines = ["Cline marked several of the agent's edits as failed."]
    if unnamed:
        lines.append("Clinescope could not tell which file some of them were for.")
    if unrecovered < total:
        lines.append(
            "For some of those files, a failed edit had no later edit to the same file "
            "that went through."
        )
    elif len(names) == 1 and not unnamed:
        lines.append("No later edit to that file went through.")
    else:
        lines.append("No later edit to those files went through.")
    return tuple(lines)


def _plain_editor_newlines(results: PlainResults, check: EditorNewlinesCheck) -> None:
    advice = advice_for_editor_newlines(check)
    if advice is None:
        results.went_well.append(
            "No editor edit replaced two or more lines with one line that holds the text \\n."
        )
        return
    names = [_plain_file_name(path) for _, path in check.hits if path is not None]
    if len(check.hits) == 1:
        target = f" to {names[0]}" if names else ""
        problem: tuple[str, ...] = (
            f"An edit{target} replaced real line breaks with the two characters \\n.",
            "Cline did not mark that edit as failed.",
        )
    else:
        problem = (
            f"{len(check.hits)} edits replaced real line breaks with the two "
            "characters \\n.",
        )
        if names:
            problem += (f"They were edits to {_plain_and_list(names)}.",)
        problem += ("Cline did not mark those edits as failed.",)
    results.problems.append(
        PlainProblem(
            "Line breaks replaced with the text \\n",
            problem,
            _plain_steps(advice),
            _WHY_NEWLINES,
        )
    )


def _plain_test_cmd(results: PlainResults, check: CmdAfterEditCheck, text: str) -> None:
    command = f'A command containing "{text}"'
    advice = advice_for_test_cmd(check)
    if check.status == "not_run":
        results.problems.append(
            PlainProblem(
                "A command that did not run after the last edit",
                (f'No command containing "{text}" ran after the last edit.',),
                _plain_steps(advice),
                _WHY_NOT_RUN,
            )
        )
    elif check.status == "ran" and check.success is False:
        results.problems.append(
            PlainProblem(
                "A command Cline marked as failed",
                (
                    f"{command} ran after the last edit.",
                    "Cline marked that command as failed.",
                ),
                _plain_steps(advice),
                _WHY_CMD_FAILED,
            )
        )
    elif check.status == "ran" and check.success is True:
        results.went_well.append(
            f"{command} ran after the last edit, and Cline recorded success."
        )
    elif check.status == "ran":
        results.skip(
            f"{command} ran after the last edit, but Cline recorded no result for it."
        )
    else:
        results.skip(
            "Clinescope could not check the test command, because "
            f"{_TEST_CMD_REASONS[check.status]}."
        )


_TEST_CMD_REASONS = {
    "no_edit": "the run made no edit",
    "every_edit_failed": "every edit failed",
    "execute_command": "this run ran commands in a way Clinescope does not read",
}


# --- layout and small text helpers --------------------------------------------


def _plain_layout(results: PlainResults, session_line: str) -> str:
    count = len(results.problems)
    if count:
        lines = [
            f"Clinescope found {_plain_count(count, 'problem')} in this Cline run.",
            "",
        ]
    else:
        lines = ["Clinescope found no problems in the checks below.", ""]
    for number, problem in enumerate(results.problems, start=1):
        lines.append("Problem" if count == 1 else f"Problem {number} of {count}")
        lines.extend(_plain_bullets(problem.problem))
        lines.extend(["", "What to do", *_plain_bullets(problem.what_to_do)])
        lines.extend(["", "Why", *_plain_bullets(problem.why), ""])
    if results.went_well:
        lines.extend(["What went well", *_plain_bullets(results.went_well), ""])
    if results.did_not_apply:
        lines.extend(["Did not apply", *_plain_bullets(results.did_not_apply), ""])
    lines.append(session_line)
    return "\n".join(lines)


def plain_run_lines(
    label: str,
    results: PlainResults,
    *,
    suffix: str = "",
    notes: tuple[str, ...] = (),
) -> list[str]:
    """One run in a plain table: a line with its problem count and how many checks
    went well or did not apply, then one bullet per problem.

    ``suffix`` ends the problem count (the corpus passes ", as expected") and
    ``notes`` are sentences placed right after it.
    """
    count = len(results.problems)
    found = _plain_count(count, "problem") if count else "no problems"
    sentences = [f"{label}: {found}{suffix}.", *notes]
    went_well = len(results.went_well)
    if went_well and results.skipped:
        sentences.append(
            f"{_plain_count(went_well, 'check')} went well, and {results.skipped} did "
            "not apply."
        )
    elif went_well:
        sentences.append(f"{_plain_count(went_well, 'check')} went well.")
    elif results.skipped:
        sentences.append(f"{_plain_count(results.skipped, 'check')} did not apply.")
    return [
        " ".join(sentences),
        *(f"- {' '.join(problem.problem)}" for problem in results.problems),
    ]


def plain_kind_blocks(entries: list[tuple[str, PlainProblem]]) -> list[str]:
    """One block per kind of problem, in the order kinds first appear: its name, the
    runs it applies to, then one What to do and one Why. Each block starts with a
    blank line, so it can follow the run lines directly."""
    groups: dict[tuple[str, tuple[str, ...], tuple[str, ...]], list[str]] = {}
    for label, problem in entries:
        key = (problem.kind, problem.what_to_do, problem.why)
        groups.setdefault(key, []).append(label)
    lines: list[str] = []
    for (kind, what_to_do, why), runs in groups.items():
        lines.extend(["", kind, f"Runs: {_plain_and_list(runs)}", ""])
        lines.extend(["What to do", *_plain_bullets(what_to_do), ""])
        lines.extend(["Why", *_plain_bullets(why)])
    return lines


def _plain_bullets(sentences: tuple[str, ...] | list[str]) -> list[str]:
    return [f"- {sentence}" for sentence in sentences]


def _plain_steps(advice: ScorerAdvice | None) -> tuple[str, ...]:
    # Line 0 of an advice entry is its evidence; the lines after it say what to do.
    return advice.lines[1:] if advice is not None else ()


def _plain_file_name(path: str) -> str:
    # PureWindowsPath splits on both "\" and "/", so a Windows trace scored on Linux
    # still shows only the file name.
    return quote_untrusted_text(PureWindowsPath(path).name or path)


def _plain_count(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _plain_or_list(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} or {items[-1]}"


def _plain_and_list(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"
