"""Regression test pinning a LIVE-captured Cline trace (retires the overfit tripwire).

Every other scorer test runs on AUTHORED real-format traces. This one runs on a
trace CAPTURED from a real Cline CLI run against a locally-served ``gpt-oss:20b``
model via Ollama (``examples/live-gpt-oss-trace.json``) -- genuine agent output,
not hand-written. It is the first evidence that a real coding-agent run in the
wild emits ``apply_patch`` patches the four scorers actually handle.

The captured run: task "fix multiply() in calc.py (adds instead of multiplies)"
-> gpt-oss read the file, then emitted ONE ``apply_patch`` (``*** Update File:
calc.py`` swapping ``return a + b`` for ``return a * b``), which Cline's executor
CONFIRMED applied (``"success": true``). Provenance is in the trace itself
(``modelInfo: {id: "gpt-oss:20b", provider: "ollama"}``).

**Real-shape finding this trace surfaced (the value of a live capture):** Cline's
real ``apply_patch`` ``tool_result`` carries ``"success": true`` in its JSON
``content`` but NO ``is_error`` field at all. The loader maps a missing ``is_error``
to ``None`` (the R11 fix -- an unknown verdict, never a coerced success). The three
text-only scorers are unaffected (they never read ``is_error``); ``tool_selection`` /
``diff_coherence`` / ``diff_minimality`` all score exactly as the live run produced.

**Day-11 update (the "success"-JSON secondary oracle).** Day 10 recorded that
``apply_recovery`` ABSTAINED on this trace: keying strictly on ``is_error``, it read
the ``None`` verdict as "no confirmed outcome" and reported a truncated-export gap.
Day 11 taught the scorer to read the ``"success"`` boolean out of the tool_result
content JSON as a SECONDARY oracle (``is_error`` still wins when present). Now this
trace's ``"success": true`` resolves to a confirmed-success verdict, so the run is
correctly recognized as a genuinely CLEAN run: nothing failed, so recovery is still
undefined (``score=None``, ``applicable=False``) -- but for the honest reason, with
``verdict_coverage == 1.0`` and NO false "no verdicts joined" violation (the Day-10
misfire, fixed). The abstain is now a clean-run abstain, not an evidence-gap abstain.

The test is ``skipif``-gated on the example file's presence, mirroring the authored
example tests in ``test_diff_coherence.py`` / ``test_apply_recovery.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clinescope.apply_recovery import score_apply_recovery
from clinescope.diff_coherence import score_diff_coherence
from clinescope.diff_minimality import score_diff_minimality
from clinescope.tool_selection import score_tool_selection
from clinescope.world_a import load_trace

LIVE_TRACE = (
    Path(__file__).resolve().parent.parent / "examples" / "live-gpt-oss-trace.json"
)


@pytest.mark.skipif(
    not LIVE_TRACE.exists(), reason="live gpt-oss capture trace not present"
)
def test_live_trace_loads_as_world_a_v1() -> None:
    # A REAL captured session parses through the unmodified World-A v1 loader.
    trace = load_trace(LIVE_TRACE)

    assert trace.version == 1
    # 6 turns: user task, assistant(read_files), tool_result, assistant(apply_patch),
    # tool_result, assistant(final text).
    assert len(trace.turns) == 6
    # Two tool calls, id-keyed joined; nothing dropped (all content types modelled).
    names = [c.name for c in trace.tool_calls]
    assert names == ["read_files", "apply_patch"]
    assert trace.dropped_items == ()


@pytest.mark.skipif(
    not LIVE_TRACE.exists(), reason="live gpt-oss capture trace not present"
)
def test_live_trace_apply_patch_is_genuine_envelope() -> None:
    # The captured apply_patch carries a real ``*** Begin Patch`` envelope at the
    # ``input.input`` key -- Cline's true shape, not the fictional ``{"diff": ...}``.
    trace = load_trace(LIVE_TRACE)
    patch_calls = [c for c in trace.tool_calls if c.name == "apply_patch"]

    assert len(patch_calls) == 1
    patch_text = patch_calls[0].input["input"]
    assert "diff" not in patch_calls[0].input
    assert patch_text.startswith("*** Begin Patch")
    assert "*** Update File: calc.py" in patch_text
    assert "-    return a + b" in patch_text
    assert "+    return a * b" in patch_text
    # Real-shape finding: the success tool_result omits is_error -> loader gives None.
    assert patch_calls[0].is_error is None


@pytest.mark.skipif(
    not LIVE_TRACE.exists(), reason="live gpt-oss capture trace not present"
)
def test_live_trace_tool_selection_scores_1() -> None:
    trace = load_trace(LIVE_TRACE)
    score = score_tool_selection(trace, {"apply_patch"})

    assert score.score == 1.0
    assert "apply_patch" in score.matched
    # read_files is used-but-not-expected; correct, not a defect.
    assert score.unexpected == frozenset({"read_files"})


@pytest.mark.skipif(
    not LIVE_TRACE.exists(), reason="live gpt-oss capture trace not present"
)
def test_live_trace_diff_coherence_scores_1() -> None:
    # gpt-oss:20b produced a grammatically perfect single-hunk Update patch.
    trace = load_trace(LIVE_TRACE)
    score = score_diff_coherence(trace)

    assert score.score == 1.0
    assert score.failed_gates == frozenset()
    assert score.apply_patch_call_count == 1
    # is_error is context-only here and absent in the real trace -> None.
    assert score.cline_apply_is_error is None


@pytest.mark.skipif(
    not LIVE_TRACE.exists(), reason="live gpt-oss capture trace not present"
)
def test_live_trace_diff_minimality_scores_1() -> None:
    # A clean 1-line surgical fix: one Update hunk, zero blind whole-block rewrites.
    trace = load_trace(LIVE_TRACE)
    score = score_diff_minimality(trace)

    assert score.score == 1.0
    assert score.applicable is True
    assert score.blind_rewrite_hunks == 0
    assert score.hunks_with_body == 1
    assert score.violations == ()


@pytest.mark.skipif(
    not LIVE_TRACE.exists(), reason="live gpt-oss capture trace not present"
)
def test_live_trace_apply_recovery_reads_success_as_clean_run() -> None:
    # Day-11 behavior (supersedes the Day-10 abstain-on-absent-verdict pin): the
    # apply_patch tool_result omits is_error but carries "success": true in its
    # content JSON. The secondary oracle reads that -> a confirmed-success verdict,
    # so the run is a genuinely CLEAN run (nothing failed). Recovery is still
    # undefined (score=None, applicable=False), but now for the honest reason:
    # verdict_coverage == 1.0 (the verdict WAS read) with NO false "no verdicts
    # joined" violation. Previously (Day 10) this abstained with verdict_coverage
    # 0.0 and a truncated-export violation -- that misfire is fixed.
    trace = load_trace(LIVE_TRACE)
    score = score_apply_recovery(trace)

    assert score.score is None
    assert score.applicable is False
    assert score.total_failed_pairs == 0
    assert score.apply_patch_call_count == 1
    # The oracle resolved the verdict from "success": true -> full coverage.
    assert score.verdict_coverage == 1.0
    # A clean run raises no evidence-gap violation (the Day-10 false accusation).
    assert score.violations == ()
    # The RAW context field stays None (the trace really has no is_error field);
    # only the SCORE reads the oracle-resolved verdict.
    assert score.cline_apply_is_error is None
