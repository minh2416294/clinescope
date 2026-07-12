"""Tests for the multi-trace comparison scorecard (clinescope.compare).

The load-bearing test is the ANTI-DRIFT guard: every compare row must reproduce
exactly what the single-trace CLI prints for that trace. It renders each example
trace both ways and asserts the compare cell + verdict appear in the matching
single-trace summary line -- checking compare against the REAL single-trace output
path, not merely a shared helper.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinescope.apply_recovery import score_apply_recovery
from clinescope.compare import CompareRow, main, run_compare
from clinescope.diff_coherence import score_diff_coherence
from clinescope.diff_minimality import score_diff_minimality
from clinescope.labels import LabelError, TraceLabel
from clinescope.report import render_report
from clinescope.tool_selection import score_tool_selection
from clinescope.world_a import load_trace

EXAMPLES = Path("examples")
_SCORERS = ("tool_selection", "diff_coherence", "diff_minimality", "apply_recovery")

# Every committed example trace the loader can read -- the anti-drift guard is
# parametrized across ALL of them so no trace shape escapes the check.
_EXAMPLE_TRACES = sorted(p for p in EXAMPLES.glob("*.json") if p.is_file())


def _single_trace_summary_lines(
    trace_path: Path, expected_tools: list[str] | None
) -> dict[str, str]:
    """Render the single-trace summary and return {scorer_name: its line}.

    Mirrors exactly how clinescope.__main__ scores + renders a single trace, so
    the lines are the true single-trace output, not a reconstruction.
    """
    trace = load_trace(trace_path)
    expected_provided = expected_tools is not None
    score = score_tool_selection(trace, set(expected_tools or ()))
    summary = render_report(
        trace,
        score,
        diff_coherence=score_diff_coherence(trace),
        diff_minimality=score_diff_minimality(trace),
        apply_recovery=score_apply_recovery(trace),
        expected_provided=expected_provided,
        verbose=False,
    )
    lines: dict[str, str] = {}
    for line in summary.splitlines():
        for name in _SCORERS:
            if line.startswith(name):
                lines[name] = line
    return lines


@pytest.mark.parametrize("trace_path", _EXAMPLE_TRACES, ids=lambda p: p.stem)
def test_compare_row_reproduces_single_trace_cells(trace_path: Path) -> None:
    # ANTI-DRIFT: with no label (tool_selection n/a, as single-trace with no
    # --expected), each compare cell + verdict must appear in the matching
    # single-trace summary line.
    report = run_compare([trace_path])
    row = report.rows[0]
    single = _single_trace_summary_lines(trace_path, expected_tools=None)

    for name in _SCORERS:
        cell = row.cells[name]
        line = single[name]
        assert cell.cell in line, (
            f"{trace_path.stem} {name}: cell {cell.cell!r} not in {line!r}"
        )
        if cell.verdict:
            assert cell.verdict in line, (
                f"{trace_path.stem} {name}: verdict {cell.verdict!r} not in {line!r}"
            )


def test_compare_row_reproduces_single_trace_cells_with_expected_tools() -> None:
    # ANTI-DRIFT with a per-trace label: tool_selection now scores, and its cell +
    # verdict must still match the single-trace path given the same expected set.
    trace_path = EXAMPLES / "apply-patch-trace.json"
    expected = ["apply_patch"]
    labels = {str(trace_path): TraceLabel(display=None, expected_tools=tuple(expected))}

    row = run_compare([trace_path], labels).rows[0]
    single = _single_trace_summary_lines(trace_path, expected_tools=expected)

    ts = row.cells["tool_selection"]
    assert ts.cell in single["tool_selection"]
    # apply_patch is used in this trace -> perfect recall -> PASS, matching single-trace.
    assert ts.verdict == "PASS"
    assert "PASS" in single["tool_selection"]


def test_compare_tool_selection_sub_perfect_recall_matches_single_trace() -> None:
    # ANTI-DRIFT over the branch the plan explicitly flags: sub-perfect recall must
    # render the NN/100 cell with a BLANK verdict (never FAIL), byte-identical to
    # the single-trace path. apply-patch-trace uses {apply_patch, read_files}, so
    # expecting one more tool it does NOT use -> recall 2/3 -> 67/100, blank verdict.
    trace_path = EXAMPLES / "apply-patch-trace.json"
    expected = ["apply_patch", "read_files", "write_file"]
    labels = {str(trace_path): TraceLabel(display=None, expected_tools=tuple(expected))}

    row = run_compare([trace_path], labels).rows[0]
    single = _single_trace_summary_lines(trace_path, expected_tools=expected)

    ts = row.cells["tool_selection"]
    assert ts.cell == "67/100"
    assert ts.cell in single["tool_selection"]
    # Sub-perfect recall gets NO verdict word (not FAIL) -- matching single-trace.
    assert ts.verdict == ""
    assert "FAIL" not in single["tool_selection"]


# --- Table content + behavior -------------------------------------------------


def test_compare_renders_one_row_per_trace_with_all_four_scorers() -> None:
    traces = [
        EXAMPLES / "apply-patch-trace.json",
        EXAMPLES / "gate-regression-badpatch.json",
    ]
    report = run_compare(traces)

    assert len(report.rows) == 2
    for row in report.rows:
        assert set(row.cells) == set(_SCORERS)
        assert row.loaded


def test_compare_mixes_clean_and_failing_traces() -> None:
    # A clean trace (apply-patch-trace: coherence 100) and a failing one
    # (gate-regression-badpatch: coherence < 100) both render, with different cells.
    clean = EXAMPLES / "apply-patch-trace.json"
    failing = EXAMPLES / "gate-regression-badpatch.json"
    report = run_compare([clean, failing])

    clean_row = _row_by_label(report.rows, clean.stem)
    failing_row = _row_by_label(report.rows, failing.stem)
    assert clean_row.cells["diff_coherence"].verdict == "PASS"
    assert failing_row.cells["diff_coherence"].verdict == "FAIL"


def test_compare_abstaining_scorer_renders_na_not_blank_or_zero(tmp_path: Path) -> None:
    # A read-only trace with NO apply_patch: diff_minimality + apply_recovery
    # abstain -> n/a, NEVER blank and NEVER a fake 0/100.
    trace = tmp_path / "read-only.json"
    trace.write_text(
        json.dumps(
            {
                "version": 1,
                "sessionId": "readonly-1",
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "call-1",
                                "name": "read_files",
                                "input": {"path": "a.py"},
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    row = run_compare([trace]).rows[0]

    for name in ("diff_minimality", "apply_recovery"):
        assert row.cells[name].cell == "n/a"
        assert row.cells[name].verdict == "n/a"


def test_compare_tool_selection_without_label_is_na_not_fail() -> None:
    trace = EXAMPLES / "gate-regression-badpatch.json"
    row = run_compare([trace]).rows[0]

    ts = row.cells["tool_selection"]
    assert ts.cell == "n/a"
    assert ts.verdict != "FAIL"


def test_compare_bad_trace_becomes_error_row_not_abort(tmp_path: Path) -> None:
    good = EXAMPLES / "apply-patch-trace.json"
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    report = run_compare([good, bad])

    assert len(report.rows) == 2
    good_row = _row_by_label(report.rows, good.stem)
    bad_row = _row_by_label(report.rows, "bad")
    assert good_row.loaded
    assert not bad_row.loaded
    assert bad_row.error is not None
    assert all(cell.cell == "n/a" for cell in bad_row.cells.values())
    # A load failure is a usage-level problem -> exit 2, never a silent 0.
    assert report.exit_code == 2


def test_compare_all_loaded_exit_0() -> None:
    report = run_compare([EXAMPLES / "apply-patch-trace.json"])
    assert report.exit_code == 0


def test_compare_label_matches_by_resolved_path_not_spelling() -> None:
    # A manifest key spelled differently from the CLI trace arg (absolute vs
    # relative, "./" prefix) must still match -- matching is by resolved path.
    trace = EXAMPLES / "apply-patch-trace.json"
    key = str((EXAMPLES / "apply-patch-trace.json").resolve())
    labels = {key: TraceLabel(display="matched", expected_tools=("apply_patch",))}

    row = run_compare([Path("./") / trace], labels).rows[0]

    assert row.label == "matched"
    assert row.cells["tool_selection"].verdict == "PASS"


def test_compare_conflicting_same_path_labels_raise() -> None:
    # Two DIFFERENT-string keys that resolve to the SAME path with DIFFERENT labels
    # must fail loud, not silently collapse (last-write-wins would score the wrong
    # expected set). Forward-slash vs OS-native spellings are distinct strings.
    trace = EXAMPLES / "apply-patch-trace.json"
    key_native = str(trace)
    key_fwd = trace.as_posix()
    assert key_native != key_fwd  # guard: they are genuinely different strings
    labels = {
        key_native: TraceLabel(display="a", expected_tools=("apply_patch",)),
        key_fwd: TraceLabel(display="b", expected_tools=("read_files",)),
    }

    with pytest.raises(LabelError, match="resolve to the same path"):
        run_compare([trace], labels)


def test_compare_identical_same_path_labels_are_allowed() -> None:
    # A redundant (identical) dupe for the same path is harmless -> no error.
    trace = EXAMPLES / "apply-patch-trace.json"
    same = TraceLabel(display="a", expected_tools=("apply_patch",))
    labels = {str(trace): same, trace.as_posix(): same}

    report = run_compare([trace], labels)

    assert report.rows[0].cells["tool_selection"].verdict == "PASS"


# --- CLI ----------------------------------------------------------------------


def test_compare_cli_prints_table_and_exits_0(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            str(EXAMPLES / "apply-patch-trace.json"),
            str(EXAMPLES / "gate-regression-badpatch.json"),
        ]
    )
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "clinescope compare" in out
    for name in _SCORERS:
        assert name in out
    assert "apply-patch-trace" in out
    assert "gate-regression-badpatch" in out


def test_compare_cli_with_labels_scores_tool_selection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    trace = EXAMPLES / "apply-patch-trace.json"
    manifest = tmp_path / "labels.json"
    manifest.write_text(
        json.dumps({str(trace): {"expected_tools": ["apply_patch"]}}), encoding="utf-8"
    )
    exit_code = main([str(trace), "--labels", str(manifest)])
    out = capsys.readouterr().out

    assert exit_code == 0
    # tool_selection scored PASS (apply_patch used) rather than n/a.
    assert "PASS" in out


def test_compare_cli_malformed_labels_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = tmp_path / "labels.json"
    manifest.write_text("[]", encoding="utf-8")
    exit_code = main(
        [str(EXAMPLES / "apply-patch-trace.json"), "--labels", str(manifest)]
    )
    err = capsys.readouterr().err

    assert exit_code == 2
    assert "could not load labels" in err


def test_compare_cli_conflicting_labels_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    trace = EXAMPLES / "apply-patch-trace.json"
    manifest = tmp_path / "labels.json"
    manifest.write_text(
        json.dumps(
            {
                str(trace): {"expected_tools": ["apply_patch"]},
                trace.as_posix(): {"expected_tools": ["read_files"]},
            }
        ),
        encoding="utf-8",
    )
    exit_code = main([str(trace), "--labels", str(manifest)])
    err = capsys.readouterr().err

    assert exit_code == 2
    assert "invalid labels" in err


def _row_by_label(rows: tuple[CompareRow, ...], label: str) -> CompareRow:
    for row in rows:
        if row.label == label:
            return row
    raise AssertionError(f"no row labelled {label!r} in {[r.label for r in rows]}")
