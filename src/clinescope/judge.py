"""LLM-judge seam for diff_minimality -- judge-validation, segment 2 (STUB ONLY).

This is the INTERFACE the κ arc's later segments fill; nothing here calls a model.
Segment 3 authors balanced hard-case patches and the USER hand-labels them blind;
segment 4 implements a real ``judge_diff_minimality`` that asks an LLM the same
holistic question the human answered ("is this patch WASTEFUL?"), then feeds the
two aligned label lists to :func:`clinescope.agreement.cohen_kappa` for the κ number.

**Deliberate decisions (each a stated choice):**

* ``judge_diff_minimality`` takes a :class:`~clinescope.world_a.Trace`, NOT patch
  text -- exactly parallel to the four deterministic scorers, which each take a
  Trace and select the apply_patch internally. This means segment 4's real judge
  slots into this signature with no interface change (it will select the FIRST
  apply_patch, the same call the scorer and the gold loader score).
* ``JudgeLabel.model_id`` is load-bearing, not decorative: the free-vs-paid story
  (which model produced this verdict) must ride with every label, per the charter's
  "scores are glued to the exact setup" caveat -- a κ against a free local model and
  a κ against a paid frontier model are different claims and must be told apart.
* NO ``Protocol`` / ABC. Zero real judge implementations exist yet; a seam earns an
  abstraction only when a SECOND implementation justifies it (two-implementation
  rule). ``judge_diff_minimality`` is one plain module-level function, mirroring the
  scorers and ``cohen_kappa``.
* The label vocabulary is the holistic binary WASTEFUL / NOT-WASTEFUL -- the same
  question the human gold labeler answers, decoupled from ``diff_minimality``'s
  deterministic blind-rewrite SHAPE proxy. Judge and human must answer the SAME
  question or the κ is judge-vs-scorer theater, not judge-vs-human validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from clinescope.world_a import Trace

# The holistic binary a human gold labeler and the judge both answer. This is the
# same vocabulary the gold loader validates human labels against (clinescope.gold
# GOLD_LABELS); keep the two in sync -- judge and human answer ONE shared question.
JudgeVerdict = Literal["WASTEFUL", "NOT-WASTEFUL"]


@dataclass(frozen=True, slots=True)
class JudgeLabel:
    """One judge verdict on a trace's first apply_patch.

    Invariants:

    * ``label`` is the holistic binary the human gold set also uses -- ``"WASTEFUL"``
      or ``"NOT-WASTEFUL"`` -- so a judge label and a human label are directly
      comparable inputs to :func:`clinescope.agreement.cohen_kappa`.
    * ``rationale`` is the judge's free-text justification (why it called the patch
      wasteful or not) -- kept for auditing a low-κ disagreement, never scored.
    * ``model_id`` identifies the exact model that produced the verdict (load-bearing
      for the free-vs-paid claim; see the module docstring).
    """

    label: JudgeVerdict
    rationale: str
    model_id: str


def judge_diff_minimality(trace: Trace) -> JudgeLabel:
    """Judge whether the first apply_patch in ``trace`` is wastefully written.

    SEAM STUB (κ-arc segment 2): raises today. Segment 4 will select the FIRST
    apply_patch (the same call the scorer and the gold loader score), ask an LLM the
    holistic "is this patch WASTEFUL?" question, and return a :class:`JudgeLabel`.

    Args:
        trace: A loaded World-A trace; the real judge will read its first apply_patch.

    Raises:
        NotImplementedError: Always, today -- no judge model is wired yet.
    """
    raise NotImplementedError(
        "judge_diff_minimality is a seam stub (κ-arc segment 2); no judge model is "
        "wired yet -- segment 4 implements the LLM call"
    )
