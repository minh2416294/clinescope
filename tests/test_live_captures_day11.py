"""Regression tests pinning THREE more LIVE-captured Cline traces (Day 11).

These extend ``test_live_capture.py`` (the Day-10 single ``calc.py`` capture) with
three more real Cline CLI runs against a locally-served ``gpt-oss:20b`` model via
Ollama -- genuine agent output, scrubbed only of the OS username (paths read
``C:\\Users\\user\\...``), never content-edited. Together they broaden the live
evidence from one trace / one shape to four traces across distinct shapes, and --
via the Day-11 ``"success"``-JSON oracle -- exercise ``apply_recovery``'s SCORING
path on real data for the first time.

The three captures (provenance in each trace's ``modelInfo`` /
``system_prompt`` env block):

* ``live-gpt-oss-update-2hunk.json`` -- a TWO-hunk ``*** Update File`` patch
  (``3.14`` -> ``math.pi`` on two lines of ``geometry.py``), applied cleanly. A
  structurally richer Update than Day-10's single hunk.
* ``live-gpt-oss-add-file.json`` -- an ``*** Add File`` patch creating
  ``helpers.py``, preceded by a ``run_commands`` (``dir``) and a ``read_files``.
  Exercises the Add-File path (``add_file_lines``, zero update hunks) and a third
  tool (``run_commands``) the other traces don't use. (The generated file has a
  subtly broken Python docstring, yet Cline reports ``success:true`` -- a real
  "applied but not necessarily correct" case; ``diff_coherence`` scores grammar,
  not Python validity, exactly as documented.)
* ``live-gpt-oss-apply-fail.json`` -- THE milestone: a first ``apply_patch`` that
  MIS-ANCHORED and Cline reported ``"success": false`` (a genuine
  ``similarity: 0.55`` context-match failure), with no later confirmed retry
  (the weak model ran out of turn before re-patching). Because a real Cline
  ``apply_patch`` result carries NO ``is_error`` field -- the outcome is the
  ``"success"`` bool inside the tool_result content JSON -- ``apply_recovery``
  reads that via the Day-11 secondary oracle and produces a genuine NUMERIC
  score (``0.0``: one failed file, never recovered), ``applicable=True``. Before
  the oracle this trace would have abstained (``is_error`` all ``None``). This is
  the first time ``apply_recovery`` SCORES on live data, not just abstains.

Every test is ``skipif``-gated on the example file's presence, mirroring the
authored example tests in ``test_diff_coherence.py`` / ``test_apply_recovery.py``
and the Day-10 ``test_live_capture.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clinescope.__main__ import main
from clinescope.apply_recovery import score_apply_recovery
from clinescope.diff_coherence import score_diff_coherence
from clinescope.diff_minimality import score_diff_minimality
from clinescope.tool_selection import score_tool_selection
from clinescope.world_a import load_trace

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
UPDATE_2HUNK = EXAMPLES / "live-gpt-oss-update-2hunk.json"
ADD_FILE = EXAMPLES / "live-gpt-oss-add-file.json"
APPLY_FAIL = EXAMPLES / "live-gpt-oss-apply-fail.json"


# --- capture 1: a two-hunk Update, applied cleanly ---------------------------


@pytest.mark.skipif(
    not UPDATE_2HUNK.exists(), reason="update-2hunk capture not present"
)
def test_update_2hunk_loads_and_shapes() -> None:
    trace = load_trace(UPDATE_2HUNK)

    assert trace.version == 1
    assert [c.name for c in trace.tool_calls] == ["read_files", "apply_patch"]
    assert trace.dropped_items == ()
    patch = next(c for c in trace.tool_calls if c.name == "apply_patch")
    # Real Cline apply_patch result: "success" JSON in content, NO is_error field.
    assert patch.is_error is None
    assert isinstance(patch.result_content, str)
    assert '"success":true' in patch.result_content.replace(" ", "")


@pytest.mark.skipif(
    not UPDATE_2HUNK.exists(), reason="update-2hunk capture not present"
)
def test_update_2hunk_scores() -> None:
    trace = load_trace(UPDATE_2HUNK)

    assert score_tool_selection(trace, {"apply_patch"}).score == 1.0

    coherence = score_diff_coherence(trace)
    assert coherence.score == 1.0
    assert coherence.failed_gates == frozenset()

    minimality = score_diff_minimality(trace)
    assert minimality.score == 1.0
    assert minimality.blind_rewrite_hunks == 0
    # Two @@ hunks -- structurally richer than Day-10's single hunk.
    assert minimality.hunks_with_body == 2

    # A clean run (all success) -> recovery undefined, but via the oracle: the
    # verdict WAS read (coverage 1.0), so no false "truncated export" violation.
    recovery = score_apply_recovery(trace)
    assert recovery.score is None
    assert recovery.applicable is False
    assert recovery.verdict_coverage == 1.0
    assert recovery.violations == ()


# --- capture 2: an Add File (plus run_commands) ------------------------------


@pytest.mark.skipif(not ADD_FILE.exists(), reason="add-file capture not present")
def test_add_file_loads_and_shapes() -> None:
    trace = load_trace(ADD_FILE)

    assert trace.version == 1
    # A third tool (run_commands) appears; nothing is dropped by the loader.
    assert [c.name for c in trace.tool_calls] == [
        "run_commands",
        "read_files",
        "apply_patch",
    ]
    assert trace.dropped_items == ()
    patch = next(c for c in trace.tool_calls if c.name == "apply_patch")
    assert patch.is_error is None
    assert "*** Add File:" in patch.input["input"]


@pytest.mark.skipif(not ADD_FILE.exists(), reason="add-file capture not present")
def test_add_file_scores() -> None:
    trace = load_trace(ADD_FILE)

    assert score_tool_selection(trace, {"apply_patch"}).score == 1.0
    assert score_diff_coherence(trace).score == 1.0

    minimality = score_diff_minimality(trace)
    # Add-File-only -> no update hunks -> vacuous 1.0; add lines surfaced as context.
    assert minimality.score == 1.0
    assert minimality.applicable is True
    assert minimality.hunks_with_body == 0
    assert minimality.add_file_lines == 4

    recovery = score_apply_recovery(trace)
    assert recovery.score is None
    assert recovery.applicable is False
    assert recovery.verdict_coverage == 1.0


# --- capture 3: THE milestone -- a real apply_patch FAILURE, scored via oracle --


@pytest.mark.skipif(not APPLY_FAIL.exists(), reason="apply-fail capture not present")
def test_apply_fail_loads_and_shapes() -> None:
    trace = load_trace(APPLY_FAIL)

    assert trace.version == 1
    # A failed apply_patch, then a read (the model re-inspecting before it ran out
    # of turn); no second apply_patch was emitted.
    assert [c.name for c in trace.tool_calls] == ["apply_patch", "read_files"]
    assert trace.dropped_items == ()
    patch = next(c for c in trace.tool_calls if c.name == "apply_patch")
    # The real failure shape: NO is_error field, "success":false + an error string.
    assert patch.is_error is None
    assert isinstance(patch.result_content, str)
    compact = patch.result_content.replace(" ", "")
    assert '"success":false' in compact
    assert "apply_patch failed" in patch.result_content


@pytest.mark.skipif(not APPLY_FAIL.exists(), reason="apply-fail capture not present")
def test_apply_fail_recovery_scores_zero_via_success_oracle() -> None:
    # THE Day-11 milestone pinned: on GENUINE live data, apply_recovery produces a
    # real NUMERIC score, not an abstain. The apply_patch has NO is_error field
    # (real Cline shape) -- the secondary oracle reads "success": false from the
    # content JSON, so the call is a real FAILURE (one failed file), never
    # recovered (no later confirmed same-file apply_patch) -> score 0.0,
    # applicable=True. Before the oracle this trace abstained (is_error all None).
    trace = load_trace(APPLY_FAIL)
    recovery = score_apply_recovery(trace)

    assert recovery.score == 0.0
    assert recovery.applicable is True
    assert recovery.total_failed_pairs == 1
    assert recovery.confirmed_recovered_pairs == 0
    assert recovery.unrecovered_pairs == 1
    assert recovery.verdict_coverage == 1.0
    # The failed file is named in the evidence (username-scrubbed path).
    assert recovery.failed_target_paths == (
        "C:\\Users\\user\\clinescope-day11\\cap2\\repo\\validator.py",
    )
    assert recovery.violations  # says WHY: an unrecovered failure, in the open
    # The RAW context field stays None (the trace truly has no is_error field);
    # only the SCORE reads the oracle-resolved verdict.
    assert recovery.cline_apply_is_error is None


@pytest.mark.skipif(not APPLY_FAIL.exists(), reason="apply-fail capture not present")
def test_apply_fail_other_scorers() -> None:
    # The text-only scorers are unaffected by the failure verdict: the patch is
    # grammatically well-formed (it just didn't MATCH the file), so coherence and
    # minimality still score it 1.0 -- exactly their documented scope (grammar/shape,
    # not apply-against-file success).
    trace = load_trace(APPLY_FAIL)

    assert score_tool_selection(trace, {"apply_patch"}).score == 1.0
    assert score_diff_coherence(trace).score == 1.0

    minimality = score_diff_minimality(trace)
    assert minimality.score == 1.0
    assert minimality.hunks_with_body == 1


# --- CLI end-to-end on the milestone trace -----------------------------------


@pytest.mark.skipif(not APPLY_FAIL.exists(), reason="apply-fail capture not present")
def test_cli_end_to_end_apply_fail_shows_real_recovery_score(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([str(APPLY_FAIL), "--expected", "apply_patch", "--verbose"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "[apply_recovery]" in out
    # A REAL numeric recovery score on live data (not "n/a"), and it is 0.0.
    assert "score:          0.0000" in out
    assert "applicable:     True" in out
