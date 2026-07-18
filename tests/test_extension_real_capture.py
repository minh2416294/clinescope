"""Regression tests pinning REAL captured Cline VS Code extension traces.

The constructed fixture (``test_cline_extension.py``) uses list-content messages
and never exercised the bare-string-content path or the extension's own tool set.
These two traces are CAPTURED from real Cline VS Code extension (saoudrizwan.claude-dev
4.0.9) tasks against a locally-served Ollama model, so they are the strongest
evidence the adapter + the four scorers handle a genuine extension session.

Both are ``skipif``-gated on the capture file's presence (mirroring the CLI
live-capture tests), so the always-on suite and CI stay green without them.

The two captures, and what each proves:

1. ``api_conversation_history.real.json`` -- gpt-oss/qwen2.5-coder said it would
   create ``calc.py`` but only emitted ``plan_mode_respond`` twice and NEVER called
   an edit tool. This is the "said done, did nothing" catch on a real extension
   session: 0 tool calls, every scorer reports the gap honestly.

2. ``api_conversation_history.write-file.json`` -- gpt-oss:20b actually created
   ``calc.py`` via ``write_to_file`` (this build's default edit tool; it reported
   ``apply_patch`` unavailable). A real SUCCESSFUL edit. It proves ``tool_selection``
   scores the extension's own tools, and that the three ``apply_patch``-based diff
   scorers correctly ABSTAIN (no ``apply_patch`` to grade) rather than crash -- an
   honest finding, not a bug (a ``write_to_file`` diff scorer is roadmap).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clinescope.apply_recovery import score_apply_recovery
from clinescope.cline_extension import load_extension_trace
from clinescope.diff_coherence import score_diff_coherence
from clinescope.diff_minimality import score_diff_minimality
from clinescope.tool_selection import score_tool_selection
from clinescope.world_a import Trace

_EXT = Path(__file__).resolve().parent.parent / "examples" / "extension"
_NOOP = _EXT / "api_conversation_history.real.json"
_WRITE_FILE = _EXT / "api_conversation_history.write-file.json"


@pytest.mark.skipif(
    not _NOOP.exists(), reason="real no-op extension capture not present"
)
def test_real_noop_capture_loads_and_catches_zero_edits() -> None:
    # A real extension session where the model claimed to create a file but never
    # called an edit tool. The adapter loads it, and every scorer reports the gap.
    trace = load_extension_trace(_NOOP)

    assert isinstance(trace, Trace)
    assert trace.version == 1
    assert trace.dropped_items == ()  # every content block modelled, none dropped
    assert [c.name for c in trace.tool_calls] == []  # zero tool calls: nothing done

    # tool_selection catches that the edit tools were never called.
    ts = score_tool_selection(trace, expected={"apply_patch", "read_files"})
    assert ts.score == 0.0
    # diff_coherence hard-zeros (no apply_patch); the two shape scorers abstain.
    assert score_diff_coherence(trace).score == 0.0
    assert score_diff_minimality(trace).applicable is False
    assert score_apply_recovery(trace).applicable is False


@pytest.mark.skipif(
    not _WRITE_FILE.exists(), reason="real write_to_file extension capture not present"
)
def test_real_write_file_capture_scores_tool_selection_and_abstains_on_diff() -> None:
    # A real extension session that actually created calc.py via write_to_file
    # (this build reported apply_patch unavailable).
    trace = load_extension_trace(_WRITE_FILE)

    assert trace.version == 1
    assert trace.dropped_items == ()
    names = [c.name for c in trace.tool_calls]
    assert "write_to_file" in names  # the real edit tool this build used
    assert (
        "read_file" in names
    )  # the extension's singular read tool (vs CLI read_files)

    # tool_selection scores the extension's OWN tools (not apply_patch): perfect
    # recall when the expected set matches what the run used.
    ts = score_tool_selection(trace, expected={"write_to_file", "read_file"})
    assert ts.score == 1.0

    # The apply_patch-based diff scorers ABSTAIN honestly on a write_to_file trace
    # -- there is no apply_patch grammar to grade. This is the correct behavior, not
    # a crash: a write_to_file diff scorer is a roadmap item.
    assert score_diff_coherence(trace).score == 0.0  # hard-zero: no apply_patch
    assert score_diff_minimality(trace).applicable is False
    assert score_apply_recovery(trace).applicable is False
