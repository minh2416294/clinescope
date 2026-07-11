"""Live-model tests for the judge (skipif-gated on Ollama being reachable).

These are the ONLY tests that call a real model. They are gated on a cheap
``GET /api/tags`` reachability probe (``judge_ollama_reachable``), mirroring the
fixture-file ``skipif`` pattern in ``test_live_capture.py`` -- so CI without Ollama
stays green while a machine with ``ollama serve`` + ``gpt-oss:20b`` exercises the real
call.

**Determinism is NOT assumed -- it was tested and FOUND FALSE.** An early version of
this file asserted ``first.label == second.label`` (temp 0 => stable). A Gate-4
adversarial check disproved that: on ``dm-hc-13``, SHA-verified identical input at
``temperature=0, top_p=1, seed=0``, ``gpt-oss:20b`` via Ollama flips WASTEFUL <->
NOT-WASTEFUL run-to-run (~1/3 flip rate observed, both across and within sessions) --
GPU/batch/KV-cache nondeterminism that temp-0 + a fixed seed do NOT fully suppress. So
the committed κ (``gold/diff_minimality.judge.jsonl``) is a **single-draw snapshot**,
not a reproducible constant, and the reported κ is documented that way.

Because the label is genuinely stochastic, a hard ``==`` assertion either direction is
wrong: asserting equality flakes (~1/3 of runs), and asserting inequality also flakes.
So the determinism test below is **observational** -- it draws the flip-prone item
several times and asserts only that every draw is a *valid* verdict, while surfacing the
observed distribution so a regression to (or from) determinism is visible in the output.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from clinescope.judge import JudgeLabel, judge_diff_minimality, judge_ollama_reachable
from clinescope.world_a import load_trace

_REPO_ROOT = Path(__file__).resolve().parent.parent
# A clean 2-line timeout bump: a real, small, arguable diff for a single live judgement.
_LIVE_ITEM = (
    _REPO_ROOT / "examples" / "gold" / "dm-hardcase-01-py-retype-timeout-pair.json"
)
# The item Gate-4 found to FLIP run-to-run at temp 0 -- the honest determinism probe.
_FLIP_PRONE_ITEM = (
    _REPO_ROOT / "examples" / "gold" / "dm-hardcase-13-blind-retype-normalize-fn.json"
)

_OLLAMA_UP = judge_ollama_reachable()
_skip_no_ollama = pytest.mark.skipif(
    not _OLLAMA_UP, reason="Ollama endpoint not reachable at localhost:11434"
)


@_skip_no_ollama
def test_live_judge_returns_a_real_judge_label() -> None:
    trace = load_trace(_LIVE_ITEM)
    label = judge_diff_minimality(trace)

    assert isinstance(label, JudgeLabel)
    assert label.label in ("WASTEFUL", "NOT-WASTEFUL")
    assert label.model_id == "gpt-oss:20b"
    assert label.rationale.strip() != ""


@_skip_no_ollama
def test_live_judge_verdict_is_not_assumed_deterministic() -> None:
    # HONEST determinism probe (NOT an assertion of stability -- Gate-4 disproved that).
    # Draw the flip-prone item several times; assert only that each draw is a VALID
    # verdict, and surface the observed distribution. The judge is stochastic at temp 0
    # (GPU/batch nondeterminism), so the committed κ is a single-draw snapshot -- this
    # test documents that rather than asserting a determinism the model does not provide.
    trace = load_trace(_FLIP_PRONE_ITEM)
    draws = [judge_diff_minimality(trace).label for _ in range(4)]

    assert all(d in ("WASTEFUL", "NOT-WASTEFUL") for d in draws)
    distribution = Counter(draws)
    # If this item ever becomes stable (one label across all draws), that is a *finding*
    # worth noticing, not a pass to hide -- print it so a determinism change is visible.
    print(
        f"\n[determinism probe] dm-hc-13 over {len(draws)} draws: {dict(distribution)}"
    )
