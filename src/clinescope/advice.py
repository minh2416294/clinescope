"""Rule-based advice/coach layer (deterministic, zero-LLM).

Clinescope scores a run, then leaves the developer with bare numbers -- a real
user's reaction was "it scored... now what?". This module turns a FAILING scorer
into (1) a short failure-taxonomy label and (2) concrete "what to do" guidance
(usually a prompt fix), keyed to that scorer's EXISTING evidence fields. It
RECOMPUTES nothing and changes no score: every advice string reads fields the
scorers already surfaced (missing tools, gate violations, blind-rewrite counts,
failed files). The CLI shows it on every failing run, in the plain view and under
``--details``.

The taxonomy labels are the minimal first slice of the charter's roadmap metric
#7 (failure taxonomy): a fixed enum, one label selected per failing scorer from
its evidence -- NOT a learned classifier and NOT an LLM. A scorer that PASSED or
ABSTAINED yields no advice (``None``), so a clean run stays quiet.

Every problem the report names carries advice, so ``tool_input`` and the two context
lines (``editor_newlines``, ``test_cmd``) have advice too. Those entries carry no
label: the taxonomy stays the five failure modes the corpus measures.

Line 0 of every entry states the evidence; the lines after it say what to do. The
plain view prints those later lines as written, except for the five labelled
entries, whose wording it rephrases.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from clinescope.apply_recovery import ApplyRecoveryScore
from clinescope.cmd_after_edit import CmdAfterEditCheck
from clinescope.diff_coherence import DiffCoherenceScore
from clinescope.diff_minimality import DiffMinimalityScore
from clinescope.editor_newlines import EditorNewlinesCheck
from clinescope.editor_recovery import EditorRecoveryScore
from clinescope.render_safety import quote_untrusted_text
from clinescope.tool_input import ToolInputScore
from clinescope.tool_selection import ToolSelectionScore


class FailureLabel(Enum):
    """A fixed, pre-defined failure category per scorer (roadmap metric #7, v1)."""

    MISSING_TOOLS = "missing_tools"
    MALFORMED_PATCH = "malformed_patch"
    BLIND_REWRITE = "blind_rewrite"
    NO_APPLY_RECOVERY = "no_apply_recovery"
    NO_EDITOR_RECOVERY = "no_editor_recovery"


@dataclass(frozen=True, slots=True)
class ScorerAdvice:
    """One failing check's taxonomy label + human-readable guidance lines.

    ``lines`` quote the check's OWN evidence (a missing tool name, a violation
    string, a count, a file path) -- never a recomputed value. ``label`` is ``None``
    for a check outside the failure taxonomy.
    """

    label: FailureLabel | None
    lines: tuple[str, ...]


def advice_for_tool_selection(score: ToolSelectionScore) -> ScorerAdvice | None:
    """Advise when expected tools were not used; ``None`` when all were."""
    if not score.missing:
        return None
    tools = ", ".join(sorted(score.missing))
    return ScorerAdvice(
        label=FailureLabel.MISSING_TOOLS,
        lines=(
            f"The agent never called: {tools}.",
            "Add to your prompt an instruction to use the right tool for the task "
            "(e.g. 'Always read a file with read_files before you patch it').",
        ),
    )


def advice_for_tool_input(score: ToolInputScore) -> ScorerAdvice | None:
    """Advise when an ``editor`` input the caller named was never sent; else ``None``.

    The inputs are the caller's own ``--expected-input`` text, so they are not
    neutralized, for the same reason ``--expected`` names are not.
    """
    if not score.missing:
        return None
    inputs = ", ".join(str(item) for item in sorted(score.missing))
    return ScorerAdvice(
        label=None,
        lines=(
            f"No editor call carried: {inputs}.",
            "Your prompt should name the input the agent must use.",
            "For a file, your task should give its path.",
        ),
    )


def advice_for_diff_coherence(
    score: DiffCoherenceScore, *, editor_run: bool = False
) -> ScorerAdvice | None:
    """Advise when the apply_patch grammar is malformed; ``None`` at a perfect score.

    diff_coherence never abstains (no apply_patch is a hard 0.0), so a score below
    1.0 is a malformed-patch signal worth coaching, with one exception. On an editor
    run (``editor_run``, decided by :func:`clinescope.report.is_editor_run`) the agent
    edited through ``editor``, so there was no patch to be malformed and no advice.
    A run with neither tool still gets advice, but not the malformed-patch kind: there
    was no patch to be malformed. It keeps the label and the violation text, which the
    corpus checks.
    """
    if editor_run or score.score == 1.0:
        return None
    reason = score.violations[0] if score.violations else "malformed apply_patch"
    if score.apply_patch_call_count == 0:
        return ScorerAdvice(
            label=FailureLabel.MALFORMED_PATCH,
            lines=(
                f"The agent made no edit that Clinescope can check ({reason}).",
                "If the agent changed files another way, this is expected.",
                "If the task needed an edit and none happened, your prompt should "
                "tell the agent to edit the file with its tools.",
            ),
        )
    return ScorerAdvice(
        label=FailureLabel.MALFORMED_PATCH,
        lines=(
            f"The patch is malformed: {reason}.",
            "The model is emitting invalid apply_patch grammar. Add a few-shot "
            "example of a correct '*** Begin Patch' block to your prompt, or try a "
            "stronger model.",
        ),
    )


def advice_for_diff_minimality(score: DiffMinimalityScore) -> ScorerAdvice | None:
    """Advise when hunks are blind whole-block rewrites; ``None`` when clean/abstaining.

    Abstains (``applicable=False``) and perfect scores yield no advice. A hard-zero
    (mis-shaped patch) is a coherence problem, not a minimality one, so it is left to
    diff_coherence; here we only coach the genuine blind-rewrite signal.
    """
    if not score.applicable or score.score == 1.0:
        return None
    if score.blind_rewrite_hunks == 0:
        return None
    return ScorerAdvice(
        label=FailureLabel.BLIND_REWRITE,
        lines=(
            f"{score.blind_rewrite_hunks} of {score.hunks_with_body} edited hunks "
            "are blind whole-block rewrites (delete the whole block, retype it).",
            "Prompt the agent to change only the lines that must change and keep "
            "the surrounding lines as context.",
        ),
    )


def advice_for_apply_recovery(score: ApplyRecoveryScore) -> ScorerAdvice | None:
    """Advise when a failed patch was never recovered; ``None`` when clean/abstaining.

    The file list is every file a failed patch touched, recovered or not, so it is
    called "failed files": the counts carry how many were recovered.
    """
    if not score.applicable or score.score == 1.0:
        return None
    # The paths come straight off the trace, so neutralize each before it is rendered.
    files = (
        ", ".join(quote_untrusted_text(path) for path in score.failed_target_paths)
        if score.failed_target_paths
        else "-"
    )
    return ScorerAdvice(
        label=FailureLabel.NO_APPLY_RECOVERY,
        lines=(
            f"The agent failed a patch and did not recover it "
            f"({score.confirmed_recovered_pairs}/{score.total_failed_pairs} "
            f"recovered; failed files: {files}).",
            "Add a retry instruction: after a failed apply_patch, re-read the file "
            "and try a corrected patch instead of giving up.",
        ),
    )


def advice_for_editor_recovery(score: EditorRecoveryScore) -> ScorerAdvice | None:
    """Advise when a failed editor call was never recovered; ``None`` when clean.

    The ``apply_recovery`` sibling's advice, keyed to the ``editor`` tool. Abstains
    and perfect scores yield nothing, so a clean run stays quiet.
    """
    if not score.applicable or score.score == 1.0:
        return None
    # The paths come straight off the trace, so neutralize each before it is rendered.
    files = (
        ", ".join(quote_untrusted_text(path) for path in score.failed_target_paths)
        if score.failed_target_paths
        else "-"
    )
    return ScorerAdvice(
        label=FailureLabel.NO_EDITOR_RECOVERY,
        lines=(
            f"The agent failed an editor call and no later confirmed editor call "
            f"re-touched that path "
            f"({score.confirmed_recovered_pairs}/{score.total_failed_pairs} "
            f"recovered; failed files: {files}).",
            "Add a retry instruction: after a failed editor call, re-read the file "
            "and try a corrected edit instead of giving up. One cause cline names "
            "explicitly is a missing old_text on a file that already exists.",
        ),
    )


def advice_for_editor_newlines(check: EditorNewlinesCheck) -> ScorerAdvice | None:
    """Advise when an accepted ``editor`` call flattened line breaks; else ``None``.

    The check never opens the file, so the advice is to open it and look.
    """
    if not check.hits:
        return None
    count = len(check.hits)
    noun = "call" if count == 1 else "calls"
    # The paths come straight off the trace, so neutralize each before it is rendered.
    where = "; ".join(
        f"call {index}: {'-' if path is None else quote_untrusted_text(path)}"
        for index, path in check.hits
    )
    target = "the file" if count == 1 else "each file"
    return ScorerAdvice(
        label=None,
        lines=(
            f"{count} editor {noun} wrote literal \\n where the old text had line "
            f"breaks ({where}).",
            f"Open {target} named above and check that its line breaks are still in "
            "place.",
        ),
    )


def advice_for_test_cmd(check: CmdAfterEditCheck) -> ScorerAdvice | None:
    """Advise when the test command did not run after the last edit, or Cline marked
    it failed; ``None`` otherwise.

    Cline keeps one flag per command line, so a failed flag is a reason to read the
    output, never proof that a test failed.
    """
    if check.status == "not_run":
        return ScorerAdvice(
            label=None,
            lines=(
                "No matching command ran after the last edit.",
                "Run your tests yourself on the final files.",
                "Your prompt can tell the agent to run the tests after its last edit.",
            ),
        )
    if check.status == "ran" and check.success is False:
        return ScorerAdvice(
            label=None,
            lines=(
                "A matching command ran after the last edit, and Cline marked it as "
                "failed.",
                "Read the command's output in the Cline run to see what failed.",
                "Run your tests yourself on the final files.",
            ),
        )
    return None
