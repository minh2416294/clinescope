"""Tests for the real-trace validation corpus runner (clinescope.corpus).

The corpus is the un-fakeable evidence layer: real captured Cline traces, each
hand-labeled with its expected score profile + failure taxonomy, and a runner
that asserts clinescope reproduces every label and gives the right advice. These
tests pin the runner's contract:

* every committed corpus item's ACTUAL scores match its LABELLED cells + exact
  abstention facts (``score is None`` / ``applicable``);
* every FAILING item's advice emits the labelled ``FailureLabel`` AND names each
  labelled evidence token;
* every CLEAN item emits NO advice (clinescope does not cry wolf);
* the runner prints a shareable summary table and EXITS NON-ZERO if any item
  fails its label -- a real regression gate, verified by a deliberately
  mislabeled fixture that must make the runner exit 1.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from clinescope.advice import FailureLabel
from clinescope.corpus import (
    CorpusItemResult,
    main,
    render_corpus_report,
    run_corpus,
)

# The committed real corpus + its manifest.
CORPUS_DIR = Path("examples/corpus")
CORPUS_MANIFEST = CORPUS_DIR / "corpus.json"

_SCORERS = ("tool_selection", "diff_coherence", "diff_minimality", "apply_recovery")


def _manifest_entries() -> dict[str, dict[str, object]]:
    raw = json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


# --- The committed corpus passes its own labels (the real gate, green) --------


def test_committed_corpus_all_items_match_their_labels() -> None:
    report = run_corpus(CORPUS_MANIFEST)

    assert report.exit_code == 0, _mismatch_detail(report)
    assert len(report.items) == len(_manifest_entries())
    assert all(item.matched for item in report.items)


def test_committed_corpus_has_at_least_one_real_failing_and_one_clean() -> None:
    # The corpus is only evidence if it contains BOTH a real failure (something
    # to catch) and a real clean run (the false-positive check). Guard that the
    # committed corpus never silently degrades to all-clean or all-failing.
    report = run_corpus(CORPUS_MANIFEST)
    kinds = {item.kind for item in report.items}
    sources = {item.source for item in report.items}
    assert "failing" in kinds
    assert "clean" in kinds
    assert "real" in sources


def test_committed_corpus_covers_the_real_failure_modes() -> None:
    # The corpus is evidence only if it covers real failure MODES, not a count.
    # These three are captured from REAL weak-model runs; guard that a future
    # corpus edit cannot silently drop coverage of a mode it once had. The 4th
    # mode (blind_rewrite) is an honestly-stated gap -- see examples/corpus/
    # README.md; the local model set could not emit a valid-but-bloated patch.
    report = run_corpus(CORPUS_MANIFEST)
    covered = {
        a.label.value for item in report.items for a in item.actual_advice.values()
    }
    assert "missing_tools" in covered
    assert "malformed_patch" in covered
    assert "no_apply_recovery" in covered
    # Every failing item is a REAL capture (no authored trace masquerading as one).
    for item in report.items:
        if item.kind == "failing":
            assert item.source == "real"


@pytest.mark.parametrize("trace_key", sorted(_manifest_entries()))
def test_each_corpus_item_scores_match_labelled_cells(trace_key: str) -> None:
    # Per item: the actual rendered NN/100 cell for every scorer equals the label,
    # and the abstention facts (score_is_none / applicable) the label pins hold.
    report = run_corpus(CORPUS_MANIFEST)
    item = _item_for(report, trace_key)

    assert item.matched, item.mismatches
    for scorer in _SCORERS:
        assert item.actual_cells[scorer] == item.expected_cells[scorer], (
            f"{trace_key}: {scorer} cell {item.actual_cells[scorer]!r} "
            f"!= labelled {item.expected_cells[scorer]!r}"
        )


def test_failing_item_advice_names_label_and_every_evidence_token() -> None:
    report = run_corpus(CORPUS_MANIFEST)
    failing = [item for item in report.items if item.kind == "failing"]
    assert failing, "corpus must contain a failing item"

    for item in failing:
        assert item.expected_failure_labels, f"{item.key}: failing item has no label"
        # Every labelled FailureLabel appears in the item's actual advice labels.
        actual_labels = {a.label for a in item.actual_advice.values()}
        for label_value in item.expected_failure_labels:
            expected = FailureLabel(label_value)
            assert expected in actual_labels, (
                f"{item.key}: advice missing label {label_value!r}; "
                f"got {[a.value for a in actual_labels]}"
            )
        # Every labelled evidence token appears somewhere in the advice lines.
        advice_text = "\n".join(
            line for a in item.actual_advice.values() for line in a.lines
        )
        for token in item.evidence_tokens:
            assert token in advice_text, (
                f"{item.key}: advice does not name evidence token {token!r}"
            )


def test_clean_items_emit_no_advice() -> None:
    report = run_corpus(CORPUS_MANIFEST)
    clean = [item for item in report.items if item.kind == "clean"]
    assert clean, "corpus must contain a clean item"

    for item in clean:
        assert item.actual_advice == {}, (
            f"{item.key}: clean item emitted advice {list(item.actual_advice)} "
            "(clinescope cried wolf on a clean run)"
        )
        assert item.expected_failure_labels == ()
        assert item.evidence_tokens == ()


# --- The summary table (the shareable artifact) -------------------------------


def test_render_corpus_report_shows_every_item_and_a_verdict() -> None:
    report = run_corpus(CORPUS_MANIFEST)
    text = render_corpus_report(report)

    for item in report.items:
        assert item.display in text
    # A machine-readable pass/fail verdict line so the report is scannable.
    assert "PASS" in text or "pass" in text
    # The failure-mode breakdown names the taxonomy label present in the corpus.
    assert "no_apply_recovery" in text


# --- The runner is a REAL gate: a mislabeled item makes it exit non-zero ------


def _write_corpus(tmp_path: Path, entries: Mapping[str, object]) -> Path:
    manifest = tmp_path / "corpus.json"
    manifest.write_text(json.dumps(entries), encoding="utf-8")
    return manifest


def _real_apply_fail_key() -> str:
    return "examples/corpus/live-gpt-oss-apply-fail.json"


def test_mislabeled_score_makes_runner_exit_1(tmp_path: Path) -> None:
    # Take the real apply-fail trace but claim apply_recovery should be 100/100.
    # The runner must catch the mismatch and exit 1 -- proving it is a gate, not
    # a rubber stamp. Absolute path to the real committed trace so tmp manifest
    # can point at it.
    real_trace = (CORPUS_DIR / "live-gpt-oss-apply-fail.json").resolve()
    entries = {
        str(real_trace): {
            "display": "deliberately mislabeled",
            "model": "gpt-oss:20b",
            "task": "apply-fail",
            "source": "real",
            "kind": "failing",
            "expected_tools": ["read_files", "apply_patch"],
            "scorers": {
                "tool_selection": {"expected_cell": "100/100"},
                "diff_coherence": {"expected_cell": "100/100"},
                "diff_minimality": {"expected_cell": "100/100"},
                "apply_recovery": {"expected_cell": "100/100"},
            },
            "expected_failure_labels": [],
            "evidence_tokens": [],
        }
    }
    manifest = _write_corpus(tmp_path, entries)

    report = run_corpus(manifest)

    assert report.exit_code == 1
    assert any(not item.matched for item in report.items)
    assert main([str(manifest)]) == 1


def test_mislabeled_missing_evidence_token_makes_runner_exit_1(
    tmp_path: Path,
) -> None:
    # Correct score + correct label, but claim advice names a file it does not.
    real_trace = (CORPUS_DIR / "live-gpt-oss-apply-fail.json").resolve()
    entries = {
        str(real_trace): {
            "display": "wrong evidence token",
            "model": "gpt-oss:20b",
            "task": "apply-fail",
            "source": "real",
            "kind": "failing",
            "expected_tools": ["read_files", "apply_patch"],
            "scorers": {
                "tool_selection": {"expected_cell": "100/100"},
                "diff_coherence": {"expected_cell": "100/100"},
                "diff_minimality": {"expected_cell": "100/100"},
                "apply_recovery": {
                    "expected_cell": "0/100",
                    "score_is_none": False,
                    "applicable": True,
                },
            },
            "expected_failure_labels": ["no_apply_recovery"],
            "evidence_tokens": ["this_file_is_not_in_the_trace.py"],
        }
    }
    manifest = _write_corpus(tmp_path, entries)

    report = run_corpus(manifest)

    assert report.exit_code == 1


def test_clean_item_that_actually_emits_advice_makes_runner_exit_1(
    tmp_path: Path,
) -> None:
    # Label the real apply-fail trace as "clean". It DOES emit apply_recovery
    # advice, so the no-false-positive check must fail and the runner exit 1.
    real_trace = (CORPUS_DIR / "live-gpt-oss-apply-fail.json").resolve()
    entries = {
        str(real_trace): {
            "display": "mislabeled clean",
            "model": "gpt-oss:20b",
            "task": "apply-fail",
            "source": "real",
            "kind": "clean",
            "expected_tools": ["read_files", "apply_patch"],
            "scorers": {
                "tool_selection": {"expected_cell": "100/100"},
                "diff_coherence": {"expected_cell": "100/100"},
                "diff_minimality": {"expected_cell": "100/100"},
                "apply_recovery": {
                    "expected_cell": "0/100",
                    "score_is_none": False,
                    "applicable": True,
                },
            },
            "expected_failure_labels": [],
            "evidence_tokens": [],
        }
    }
    manifest = _write_corpus(tmp_path, entries)

    assert run_corpus(manifest).exit_code == 1


# --- Usage-level failures exit 2 (never a silent success) ---------------------


def test_unloadable_trace_exits_2(tmp_path: Path) -> None:
    bad = tmp_path / "not-a-trace.json"
    bad.write_text("{not valid json", encoding="utf-8")
    entries = {
        str(bad): {
            "display": "broken",
            "model": "x",
            "task": "x",
            "source": "real",
            "kind": "clean",
            "scorers": {},
            "expected_failure_labels": [],
            "evidence_tokens": [],
        }
    }
    manifest = _write_corpus(tmp_path, entries)

    assert run_corpus(manifest).exit_code == 2
    assert main([str(manifest)]) == 2


def test_load_failure_dominates_a_mismatch_exit_2_not_1(tmp_path: Path) -> None:
    # A corpus with BOTH an unloadable item AND a mislabeled item must exit 2 (usage),
    # never 1 (mismatch): a broken input is a harder failure than a wrong label, and a
    # usage error must never be masked as a gate result. Pin the documented precedence.
    bad = tmp_path / "not-a-trace.json"
    bad.write_text("{not valid json", encoding="utf-8")
    real_trace = (CORPUS_DIR / "live-gpt-oss-apply-fail.json").resolve()
    entries = {
        str(bad): {
            "display": "broken",
            "model": "x",
            "task": "x",
            "source": "real",
            "kind": "clean",
            "scorers": {},
            "expected_failure_labels": [],
            "evidence_tokens": [],
        },
        str(real_trace): {
            "display": "deliberately mislabeled",
            "model": "gpt-oss:20b",
            "task": "apply-fail",
            "source": "real",
            "kind": "failing",
            "expected_tools": ["read_files", "apply_patch"],
            "scorers": {
                "tool_selection": {"expected_cell": "100/100"},
                "diff_coherence": {"expected_cell": "100/100"},
                "diff_minimality": {"expected_cell": "100/100"},
                "apply_recovery": {"expected_cell": "100/100"},
            },
            "expected_failure_labels": [],
            "evidence_tokens": [],
        },
    }
    manifest = _write_corpus(tmp_path, entries)

    report = run_corpus(manifest)

    assert report.exit_code == 2  # load failure dominates, NOT 1
    assert any(not item.loaded for item in report.items)
    assert any(not item.matched for item in report.items)
    assert main([str(manifest)]) == 2


def test_empty_corpus_exits_2(tmp_path: Path) -> None:
    manifest = _write_corpus(tmp_path, {})

    assert run_corpus(manifest).exit_code == 2
    assert main([str(manifest)]) == 2


def test_malformed_manifest_exits_2(tmp_path: Path) -> None:
    manifest = tmp_path / "corpus.json"
    manifest.write_text("[not, an, object]", encoding="utf-8")

    assert main([str(manifest)]) == 2


# --- main() prints the table + returns the report's exit code -----------------


def test_main_on_committed_corpus_prints_table_and_exits_0(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main([str(CORPUS_MANIFEST)])
    out = capsys.readouterr().out

    assert code == 0
    assert "clinescope" in out
    # Every committed item's display label shows in the printed table.
    for entry in _manifest_entries().values():
        assert isinstance(entry, dict)
        display = entry.get("display")
        if isinstance(display, str):
            assert display in out


def test_main_defaults_to_the_committed_manifest(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Run with no argument -> defaults to examples/corpus/corpus.json so the
    # canonical `python -m clinescope.corpus` "just works" as the demo command.
    code = main([])
    capsys.readouterr()
    assert code == 0


# --- helpers ------------------------------------------------------------------


def _item_for(report: object, trace_key: str) -> CorpusItemResult:
    items = report.items  # type: ignore[attr-defined]
    for item in items:
        if item.key == trace_key:
            return item
    raise AssertionError(f"no corpus item for {trace_key!r}")


def _mismatch_detail(report: object) -> str:
    items = report.items  # type: ignore[attr-defined]
    return "\n".join(
        f"{item.key}: {item.mismatches}" for item in items if not item.matched
    )
