"""Regression tests pinning the harness-gap A/B experiment traces.

These are REAL captured Cline CLI (World-A) traces from an A/B experiment: the same
task ("add sub(a, b) to calc.py") run on the same model with and without a
``.clinerules`` harness that forces ``apply_patch`` and teaches its grammar. The
experiment, and the "model gap vs harness gap" framing behind it, came from Cline
community feedback. See ``docs/harness-gap.md`` and ``examples/harness-gap/README.md``.

Each trace is ``skipif``-gated on the capture file's presence (mirroring the CLI
live-capture and extension real-capture tests), so the always-on suite and CI stay
green without them.

The four captures, and what each pins:

1. ``qwen-bare.messages.json`` -- qwen2.5-coder:7b, NO harness. The model chose the
   default ``editor`` tool and emitted it as JSON in prose; Cline recorded ZERO real
   tool calls. Every scorer reports the gap: tool_selection 0, diff_coherence 0.

2. ``qwen-harness.messages.json`` -- qwen2.5-coder:7b, WITH the harness. The harness
   moved the model's tool CHOICE from ``editor`` to ``apply_patch`` (its prose now
   names apply_patch), but the model still could not emit a real tool call, so Cline
   again recorded ZERO tool calls and every scorer stays 0. This is the model-capability
   ceiling: a rules file shifts intent but cannot manufacture tool-calling ability.

3. ``gptoss-bare.messages.json`` -- gpt-oss:20b, NO harness. The model did not produce
   a first token inside Cline's local 30s Ollama request timeout, so the assistant turn
   is empty (an infra timeout, not a model behavior). Kept as an honest record; it
   pins the same all-zero shape a no-tool-call trace produces.

4. ``gptoss-harness.messages.json`` -- gpt-oss:20b, WITH the harness. The model made
   real tool calls (search_codebase, read_files, run_commands, apply_patch), emitted a
   grammar-valid ``*** Begin Patch`` that succeeded, and actually edited calc.py. A
   clean 100/100/100 run: the harness path working end to end on a capable model.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinescope.apply_recovery import score_apply_recovery
from clinescope.diff_coherence import score_diff_coherence
from clinescope.diff_minimality import score_diff_minimality
from clinescope.tool_selection import score_tool_selection
from clinescope.world_a import Trace, load_trace

_DIR = Path(__file__).resolve().parent.parent / "examples" / "harness-gap"
_QWEN_BARE = _DIR / "qwen-bare.messages.json"
_QWEN_HARNESS = _DIR / "qwen-harness.messages.json"
_GPTOSS_BARE = _DIR / "gptoss-bare.messages.json"
_GPTOSS_HARNESS = _DIR / "gptoss-harness.messages.json"

# The CLI World-A read + edit tools this task should have used.
_EXPECTED = {"read_files", "apply_patch"}


def _assistant_text(trace_path: Path) -> str:
    """Concatenate the assistant text blocks of a trace (for the prose-tool check)."""
    raw = json.loads(trace_path.read_text(encoding="utf-8"))
    out: list[str] = []
    for message in raw["messages"]:
        if message.get("role") != "assistant":
            continue
        content = message.get("content")
        if isinstance(content, str):
            out.append(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    out.append(item.get("text", ""))
    return "\n".join(out)


@pytest.mark.skipif(not _QWEN_BARE.exists(), reason="qwen bare capture not present")
def test_qwen_bare_chose_editor_and_scores_zero() -> None:
    trace = load_trace(_QWEN_BARE)

    assert isinstance(trace, Trace)
    assert trace.version == 1
    assert trace.dropped_items == ()
    assert [c.name for c in trace.tool_calls] == []  # JSON was prose, not a real call

    # It reached for the DEFAULT editor tool (named in prose), not apply_patch.
    text = _assistant_text(_QWEN_BARE)
    assert "editor" in text
    assert "apply_patch" not in text

    assert score_tool_selection(trace, expected=_EXPECTED).score == 0.0
    assert score_diff_coherence(trace).score == 0.0
    assert score_diff_minimality(trace).applicable is False
    assert score_apply_recovery(trace).applicable is False


@pytest.mark.skipif(
    not _QWEN_HARNESS.exists(), reason="qwen harness capture not present"
)
def test_qwen_harness_moved_choice_to_apply_patch_but_still_zero() -> None:
    # The load-bearing finding: the harness shifted the model's tool CHOICE from
    # editor to apply_patch (visible in prose), but it still emitted zero real tool
    # calls, so every scorer stays 0. Harness moves intent, not capability.
    trace = load_trace(_QWEN_HARNESS)

    assert trace.version == 1
    assert trace.dropped_items == ()
    assert [c.name for c in trace.tool_calls] == []  # still no real tool call

    text = _assistant_text(_QWEN_HARNESS)
    assert "apply_patch" in text  # the harness moved the choice onto apply_patch

    assert score_tool_selection(trace, expected=_EXPECTED).score == 0.0
    assert score_diff_coherence(trace).score == 0.0
    assert score_diff_minimality(trace).applicable is False
    assert score_apply_recovery(trace).applicable is False


@pytest.mark.skipif(
    not _GPTOSS_BARE.exists(), reason="gpt-oss bare capture not present"
)
def test_gptoss_bare_empty_under_timeout_scores_zero() -> None:
    # gpt-oss did not produce a first token inside the local 30s Ollama timeout, so
    # the assistant turn is empty. An honest infra record, not a scored model failure.
    trace = load_trace(_GPTOSS_BARE)

    assert trace.version == 1
    assert trace.dropped_items == ()
    assert [c.name for c in trace.tool_calls] == []

    assert score_tool_selection(trace, expected=_EXPECTED).score == 0.0
    assert score_diff_coherence(trace).score == 0.0
    assert score_diff_minimality(trace).applicable is False
    assert score_apply_recovery(trace).applicable is False


@pytest.mark.skipif(
    not _GPTOSS_HARNESS.exists(), reason="gpt-oss harness capture not present"
)
def test_gptoss_harness_makes_real_apply_patch_and_scores_perfect() -> None:
    # The contrast case: on a capable model the harness path works end to end -- real
    # tool calls, a grammar-valid apply_patch, and a clean 100/100/100.
    trace = load_trace(_GPTOSS_HARNESS)

    assert trace.version == 1
    assert trace.dropped_items == ()
    names = [c.name for c in trace.tool_calls]
    assert "apply_patch" in names  # a real apply_patch tool call, not prose
    assert "read_files" in names

    assert score_tool_selection(trace, expected=_EXPECTED).score == 1.0
    assert score_diff_coherence(trace).score == 1.0
    diff_min = score_diff_minimality(trace)
    assert diff_min.applicable is True
    assert diff_min.score == 1.0
    # Nothing failed, so apply_recovery abstains rather than scoring.
    assert score_apply_recovery(trace).applicable is False
