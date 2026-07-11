"""Rule-based advice/coach layer (deterministic, zero-LLM).

Clinescope scores a run, then leaves the developer with bare numbers -- a real
user's reaction was "it scored... now what?". This module turns a FAILING scorer
into (1) a short failure-taxonomy label and (2) concrete "what to do" guidance
(usually a prompt fix), keyed to that scorer's EXISTING evidence fields. It
RECOMPUTES nothing and changes no score: every advice string reads fields the
scorers already surfaced (missing tools, gate violations, blind-rewrite counts,
unrecovered files). Off by default; the CLI renders it only under ``--advice``.

The taxonomy labels are the minimal first slice of the charter's roadmap metric
#7 (failure taxonomy): a fixed enum, one label selected per failing scorer from
its evidence -- NOT a learned classifier and NOT an LLM. A scorer that PASSED or
ABSTAINED yields no advice (``None``), so a clean run stays quiet.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from clinescope.apply_recovery import ApplyRecoveryScore
from clinescope.diff_coherence import DiffCoherenceScore
from clinescope.diff_minimality import DiffMinimalityScore
from clinescope.tool_selection import ToolSelectionScore


class FailureLabel(Enum):
    """A fixed, pre-defined failure category per scorer (roadmap metric #7, v1)."""

    MISSING_TOOLS = "missing_tools"
    MALFORMED_PATCH = "malformed_patch"
    BLIND_REWRITE = "blind_rewrite"
    NO_APPLY_RECOVERY = "no_apply_recovery"


@dataclass(frozen=True, slots=True)
class ScorerAdvice:
    """One failing scorer's taxonomy label + human-readable guidance lines.

    ``lines`` quote the scorer's OWN evidence (a missing tool name, a violation
    string, a count, a file path) -- never a recomputed value.
    """

    label: FailureLabel
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


def advice_for_diff_coherence(score: DiffCoherenceScore) -> ScorerAdvice | None:
    """Advise when the apply_patch grammar is malformed; ``None`` at a perfect score.

    diff_coherence never abstains (no apply_patch is a hard 0.0), so any score below
    1.0 is a real malformed-patch signal worth coaching.
    """
    if score.score == 1.0:
        return None
    reason = score.violations[0] if score.violations else "malformed apply_patch"
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
    """Advise when a failed patch was never recovered; ``None`` when clean/abstaining."""
    if not score.applicable or score.score == 1.0:
        return None
    files = ", ".join(score.failed_target_paths) if score.failed_target_paths else "-"
    return ScorerAdvice(
        label=FailureLabel.NO_APPLY_RECOVERY,
        lines=(
            f"The agent failed a patch and did not recover it "
            f"({score.confirmed_recovered_pairs}/{score.total_failed_pairs} "
            f"recovered; unrecovered files: {files}).",
            "Add a retry instruction: after a failed apply_patch, re-read the file "
            "and try a corrected patch instead of giving up.",
        ),
    )
