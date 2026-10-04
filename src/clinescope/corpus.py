"""Real-trace validation corpus runner (deterministic, zero-LLM, stdlib-only).

The corpus is clinescope's evidence layer. It has NO users yet, so a maintainer
or recruiter cannot take "it works" on faith; the corpus answers that by pinning
clinescope's behaviour to traces declared as real Cline captures; nothing here can
detect a false one (see "Provenance" in ``examples/corpus/README.md``). Each committed
trace carries a hand-written label (:class:`~clinescope.labels.TraceLabel`, the
corpus superset) naming its model + task, its expected per-scorer cell, its
expected failure taxonomy, and the concrete evidence the advice must name. This
runner scores every trace and asserts clinescope reproduces each label:

    python -m clinescope.corpus [manifest.json]

(defaulting to the committed ``examples/corpus/corpus.json``.)

Four checks per item, straight from the charter's GOAL-2 spec:

1. **Scores are correct** -- each scorer's rendered ``NN/100`` cell matches the
   label, plus the exact abstention facts the label pins (``score is None`` and
   ``.applicable``). Catches a scorer regression.
2. **Advice is right + actionable** -- each labelled ``FailureLabel`` is emitted
   by the matching ``advice_for_*`` AND every labelled evidence token appears in
   that advice's lines. Asserted at the :class:`~clinescope.advice.ScorerAdvice`
   level, never a rendered string.
3. **No false positives** -- a ``clean`` item must emit NO advice at all (across
   all four scorers). Proves clinescope does not cry wolf.
4. **A shareable report** -- by default plain English (:func:`render_corpus_plain`):
   whether each run matched its label, its problems, the kinds of failure covered,
   and one What to do and one Why per kind of problem. ``--details`` prints one
   table (reusing :func:`clinescope.compare.render_compare_report`) plus a
   per-check verdict and a failure-mode breakdown.

The runner is a REAL regression gate, not a demo: exit ``0`` when every item
matches its label, ``1`` when ANY item fails a check, ``2`` for a usage-level
problem (unloadable trace, empty corpus, malformed manifest). ``run_corpus`` and
both renderers are pure; only :func:`main` does I/O.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from clinescope.advice import (
    FailureLabel,
    ScorerAdvice,
    advice_for_apply_recovery,
    advice_for_diff_coherence,
    advice_for_diff_minimality,
    advice_for_tool_selection,
)
from clinescope.apply_recovery import score_apply_recovery
from clinescope.compare import (
    CompareReport,
    CompareRow,
    ScorerCell,
    editor_recovery_cell,
    render_compare_report,
    unloaded_row_cells,
)
from clinescope.diff_coherence import score_diff_coherence
from clinescope.diff_minimality import score_diff_minimality
from clinescope.editor_newlines import editor_newlines_check
from clinescope.editor_recovery import score_editor_recovery
from clinescope.render_safety import quote_untrusted_text
from clinescope.labels import (
    LabelError,
    ScorerExpectation,
    TraceLabel,
    labels_load,
)
from clinescope.plain_report import (
    PLAIN_UNREADABLE,
    PlainProblem,
    PlainResults,
    _plain_and_list,
    plain_kind_blocks,
    plain_report_results,
    plain_run_lines,
)
from clinescope.report import (
    diff_coherence_cell_verdict,
    is_editor_run,
    render_score_out_of_100,
    summary_verdict,
    tool_selection_cell_verdict,
)
from clinescope._datafiles import DataFilesNotFound, datafiles_path, datafiles_root
from clinescope.tool_selection import score_tool_selection
from clinescope.world_a import load_trace


def _default_manifest() -> Path:
    """The bundled corpus manifest, resolved from source-checkout OR installed wheel."""
    return datafiles_path("examples", "corpus", "corpus.json")


_SCORER_COLUMNS = (
    "tool_selection",
    "diff_coherence",
    "diff_minimality",
    "apply_recovery",
)

_EXIT_OK = 0
_EXIT_LABEL_MISMATCH = 1
_EXIT_USAGE = 2

# Starts the one mismatch an unloadable item carries; main strips it for stderr.
_LOAD_FAILURE = "could not load trace: "


@dataclass(frozen=True, slots=True)
class _ScoredTrace:
    """The four scores + rendered cells + advice for one loaded trace.

    A small internal value object so the check functions read the SAME rendered
    cell (via :func:`clinescope.report.render_score_out_of_100`) and the SAME
    advice objects the single-trace CLI would produce -- never a recomputation.
    """

    cells: dict[str, str]
    score_is_none: dict[str, bool]
    applicable: dict[str, bool | None]
    advice: dict[str, ScorerAdvice]
    # The per-scorer (cell, verdict) for the summary table, built here from the
    # real score objects via the SAME helpers compare._score_cells uses, so the
    # corpus table is byte-identical to a compare table over the same traces.
    compare_cells: dict[str, ScorerCell]
    # The plain-English results, from the same score objects.
    plain: PlainResults


@dataclass(frozen=True, slots=True)
class CorpusItemResult:
    """One corpus item's verdict: what was labelled, what actually happened.

    ``matched`` is True only when EVERY applicable check passed. ``mismatches``
    lists a one-line reason per failed check (empty when matched). ``loaded`` is
    False when the trace could not be read at all (a usage-level failure).
    """

    key: str
    display: str
    model: str | None
    task: str | None
    source: str | None
    kind: str | None
    expected_cells: dict[str, str]
    actual_cells: dict[str, str]
    expected_failure_labels: tuple[str, ...]
    evidence_tokens: tuple[str, ...]
    actual_advice: dict[str, ScorerAdvice]
    matched: bool
    loaded: bool
    mismatches: tuple[str, ...] = field(default_factory=tuple)
    # The per-scorer (cell, verdict) computed EXACTLY like compare._score_cells
    # (from the raw score, not the rendered string) so the summary table is
    # byte-identical to a compare table over the same traces. Empty when unloaded.
    compare_cells: dict[str, ScorerCell] = field(default_factory=dict)
    # The plain-English results for the run. None when unloaded.
    plain: PlainResults | None = None


@dataclass(frozen=True, slots=True)
class CorpusReport:
    """The whole corpus run: one result per item + the overall exit code.

    ``exit_code`` is ``0`` (all items matched), ``1`` (at least one label
    mismatch), or ``2`` (a usage-level failure: an unloadable trace or an empty
    corpus). A load failure dominates a mismatch (it is the more serious signal).
    """

    items: tuple[CorpusItemResult, ...]
    exit_code: int


def run_corpus(manifest_path: Path, *, base_dir: Path | None = None) -> CorpusReport:
    """Load the manifest, score + check every corpus trace. Pure: no printing.

    Each manifest key is a trace path resolved against ``base_dir`` (default: the current
    working directory, the historical behaviour). :func:`main` passes the data root for
    the bundled corpus so its ``examples/corpus/...`` keys resolve from a pip install too.

    Raises nothing for a per-trace load failure (it becomes an unloaded item and
    forces exit 2); only a malformed MANIFEST propagates as :class:`LabelError`,
    which :func:`main` turns into exit 2.
    """
    root = base_dir if base_dir is not None else Path.cwd()
    labels = labels_load(manifest_path)
    if not labels:
        return CorpusReport(items=(), exit_code=_EXIT_USAGE)
    items = tuple(
        _check_item(key, label, base_dir=root) for key, label in labels.items()
    )
    return CorpusReport(items=items, exit_code=_corpus_exit_code(items))


def _corpus_exit_code(items: tuple[CorpusItemResult, ...]) -> int:
    if any(not item.loaded for item in items):
        return _EXIT_USAGE
    if any(not item.matched for item in items):
        return _EXIT_LABEL_MISMATCH
    return _EXIT_OK


def _check_item(key: str, label: TraceLabel, *, base_dir: Path) -> CorpusItemResult:
    display = label.display if label.display is not None else Path(key).stem
    expected_cells = {
        name: exp.expected_cell
        for name, exp in label.scorers.items()
        if exp.expected_cell is not None
    }
    try:
        scored = _score_trace(base_dir / key, label)
    except Exception as err:  # noqa: BLE001 -- deliberate per-trace load boundary
        return CorpusItemResult(
            key=key,
            display=display,
            model=label.model,
            task=label.task,
            source=label.source,
            kind=label.kind,
            expected_cells=expected_cells,
            actual_cells={},
            expected_failure_labels=label.expected_failure_labels,
            evidence_tokens=label.evidence_tokens,
            actual_advice={},
            matched=False,
            loaded=False,
            mismatches=(f"{_LOAD_FAILURE}{type(err).__name__}: {err}",),
        )

    mismatches = _collect_mismatches(label, scored)
    return CorpusItemResult(
        key=key,
        display=display,
        model=label.model,
        task=label.task,
        source=label.source,
        kind=label.kind,
        expected_cells=expected_cells,
        actual_cells=dict(scored.cells),
        expected_failure_labels=label.expected_failure_labels,
        evidence_tokens=label.evidence_tokens,
        actual_advice=dict(scored.advice),
        matched=not mismatches,
        loaded=True,
        mismatches=tuple(mismatches),
        compare_cells=dict(scored.compare_cells),
        plain=scored.plain,
    )


def _score_trace(trace_path: Path, label: TraceLabel) -> _ScoredTrace:
    trace = load_trace(trace_path)
    expected_tools = set(label.expected_tools or ())
    expected_provided = label.expected_tools is not None
    ts = score_tool_selection(trace, expected_tools)
    dc = score_diff_coherence(trace)
    dm = score_diff_minimality(trace)
    ar = score_apply_recovery(trace)
    er = score_editor_recovery(trace)
    # The same editor-run rule the single-trace report applies, so a corpus cell and
    # its advice match what `clinescope <trace>` prints for that trace.
    dc_cell, dc_verdict = diff_coherence_cell_verdict(dc, er)

    cells = {
        "tool_selection": render_score_out_of_100(ts.score),
        "diff_coherence": dc_cell,
        "diff_minimality": render_score_out_of_100(dm.score),
        "apply_recovery": render_score_out_of_100(ar.score),
    }
    score_is_none = {
        "tool_selection": ts.score is None,
        "diff_coherence": dc.score is None,
        "diff_minimality": dm.score is None,
        "apply_recovery": ar.score is None,
    }
    applicable = {
        "tool_selection": None,
        "diff_coherence": None,
        "diff_minimality": dm.applicable,
        "apply_recovery": ar.applicable,
    }
    advice: dict[str, ScorerAdvice] = {}
    for name, entry in (
        ("tool_selection", advice_for_tool_selection(ts)),
        (
            "diff_coherence",
            advice_for_diff_coherence(dc, editor_run=is_editor_run(dc, er)),
        ),
        ("diff_minimality", advice_for_diff_minimality(dm)),
        ("apply_recovery", advice_for_apply_recovery(ar)),
    ):
        if entry is not None:
            advice[name] = entry
    # Build the summary-table (cell, verdict) per scorer from the REAL score
    # objects via the SAME helpers compare._score_cells uses, so the corpus table
    # is byte-identical to a compare table over the same traces (no round-trip
    # through the rendered string, so no [0.995, 1.0) verdict drift).
    ts_cell, ts_verdict = tool_selection_cell_verdict(ts, expected_provided)
    compare_cells = {
        "tool_selection": ScorerCell(cell=ts_cell, verdict=ts_verdict),
        "diff_coherence": ScorerCell(cell=dc_cell, verdict=dc_verdict),
    }
    for name, value in (
        ("diff_minimality", dm.score),
        ("apply_recovery", ar.score),
    ):
        compare_cells[name] = ScorerCell(
            cell=render_score_out_of_100(value),
            verdict=summary_verdict(value),
        )
    # Table only: editor_recovery is not in the label vocabulary (_SCORER_COLUMNS).
    compare_cells["editor_recovery"] = editor_recovery_cell(er)
    has_editor = er.editor_call_count > 0
    plain = plain_report_results(
        ts,
        diff_coherence=dc,
        diff_minimality=dm,
        apply_recovery=ar,
        editor_recovery=er if has_editor else None,
        editor_newlines=editor_newlines_check(trace) if has_editor else None,
        expected_provided=expected_provided,
    )
    return _ScoredTrace(
        cells=cells,
        score_is_none=score_is_none,
        applicable=applicable,
        advice=advice,
        compare_cells=compare_cells,
        plain=plain,
    )


# --- The four checks (each appends a one-line reason on failure) ---------------


def _collect_mismatches(label: TraceLabel, scored: _ScoredTrace) -> list[str]:
    reasons: list[str] = []
    reasons.extend(_check_scores(label, scored))
    reasons.extend(_check_advice_labels(label, scored))
    reasons.extend(_check_evidence_tokens(label, scored))
    reasons.extend(_check_no_false_positive(label, scored))
    return reasons


def _check_scores(label: TraceLabel, scored: _ScoredTrace) -> list[str]:
    # Check 1: each labelled scorer's rendered cell + pinned abstention facts.
    reasons: list[str] = []
    for name, exp in label.scorers.items():
        reasons.extend(_check_one_scorer(name, exp, scored))
    return reasons


def _check_one_scorer(
    name: str, exp: ScorerExpectation, scored: _ScoredTrace
) -> list[str]:
    reasons: list[str] = []
    if name not in _SCORER_COLUMNS:
        return [f"{name}: unknown scorer name in label"]
    if exp.expected_cell is not None and scored.cells[name] != exp.expected_cell:
        reasons.append(
            f"{name}: cell {scored.cells[name]!r} != labelled {exp.expected_cell!r}"
        )
    if (
        exp.score_is_none is not None
        and scored.score_is_none[name] != exp.score_is_none
    ):
        reasons.append(
            f"{name}: score_is_none {scored.score_is_none[name]} "
            f"!= labelled {exp.score_is_none}"
        )
    if exp.applicable is not None and scored.applicable[name] != exp.applicable:
        reasons.append(
            f"{name}: applicable {scored.applicable[name]} != labelled {exp.applicable}"
        )
    return reasons


def _check_advice_labels(label: TraceLabel, scored: _ScoredTrace) -> list[str]:
    # Check 2a: every labelled FailureLabel is actually emitted by some scorer.
    actual_labels = {a.label for a in scored.advice.values() if a.label is not None}
    reasons: list[str] = []
    for value in label.expected_failure_labels:
        try:
            expected = FailureLabel(value)
        except ValueError:
            reasons.append(f"unknown failure label in manifest: {value!r}")
            continue
        if expected not in actual_labels:
            emitted = sorted(a.value for a in actual_labels)
            reasons.append(f"advice missing failure label {value!r}; emitted {emitted}")
    return reasons


def _check_evidence_tokens(label: TraceLabel, scored: _ScoredTrace) -> list[str]:
    # Check 2b: every labelled evidence token appears in some advice line.
    advice_text = "\n".join(line for a in scored.advice.values() for line in a.lines)
    return [
        f"advice does not name evidence token {token!r}"
        for token in label.evidence_tokens
        if token not in advice_text
    ]


def _check_no_false_positive(label: TraceLabel, scored: _ScoredTrace) -> list[str]:
    # Check 3: a clean-labelled item must emit no advice at all.
    if label.kind != "clean":
        return []
    if scored.advice:
        emitted = sorted(scored.advice)
        return [f"clean item emitted advice for {emitted} (cried wolf)"]
    return []


# --- Rendering (pure) ---------------------------------------------------------


def render_corpus_report(report: CorpusReport) -> str:
    """Render the corpus results: the scorecard table + a per-check verdict block.

    The scorecard reuses :func:`clinescope.compare.render_compare_report` so the
    corpus table is byte-identical to the ``compare`` table (one presentation, one
    source of truth). A verdict block below it names, per item, PASS/FAIL and the
    reasons on failure, then a failure-mode breakdown of the labelled taxonomy.
    """
    table = render_compare_report(_as_compare_report(report))
    lines = [table, "", "=== corpus verdict ==="]
    passed = sum(1 for item in report.items if item.matched)
    total = len(report.items)
    lines.append(f"{passed}/{total} items match their labels")
    for item in report.items:
        verdict = "PASS" if item.matched else "FAIL"
        lines.append(f"  [{verdict}] {item.display} ({item.source or '?'})")
        for reason in item.mismatches:
            lines.append(f"      - {reason}")
    breakdown = _failure_mode_breakdown(report)
    if breakdown:
        lines.append("")
        lines.append("failure modes covered:")
        lines.extend(f"  {label}: {count}" for label, count in breakdown)
    return "\n".join(lines)


def _as_compare_report(report: CorpusReport) -> CompareReport:
    # Reuse the compare table renderer: map each corpus item to a CompareRow whose
    # cells are the (cell, verdict) already built at score time via the same
    # helpers compare._score_cells uses. exit_code is unused by
    # render_compare_report (it recomputes load errors from the rows), so pass a
    # constant -- the corpus exit code is owned by CorpusReport.exit_code.
    rows = tuple(_as_compare_row(item) for item in report.items)
    return CompareReport(rows=rows, exit_code=0)


def _as_compare_row(item: CorpusItemResult) -> CompareRow:
    if not item.loaded:
        return CompareRow(
            label=item.display,
            cells=unloaded_row_cells(),
            loaded=False,
            error="; ".join(item.mismatches),
        )
    return CompareRow(
        label=item.display, cells=dict(item.compare_cells), loaded=True, error=None
    )


def _failure_mode_breakdown(report: CorpusReport) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for item in report.items:
        for a in item.actual_advice.values():
            if a.label is not None:
                counts[a.label.value] = counts.get(a.label.value, 0) + 1
    return sorted(counts.items())


_PLAIN_FAILURE_NAMES = {
    FailureLabel.MISSING_TOOLS: "tools you listed were not used",
    FailureLabel.MALFORMED_PATCH: "a missing or badly formed patch",
    FailureLabel.BLIND_REWRITE: "blocks deleted and retyped whole",
    FailureLabel.NO_APPLY_RECOVERY: (
        "a failed patch with no later patch that went through"
    ),
    FailureLabel.NO_EDITOR_RECOVERY: (
        "a failed editor edit with no later editor edit that went through"
    ),
}

_PLAIN_MISMATCH = PlainProblem(
    "Runs that did not match their expected result",
    ("It did not match its expected result.",),
    (
        "The details view shows which result differs.",
        "Find the change that made a check give a different answer.",
    ),
    (
        "Each example run has a fixed expected result, written by hand.",
        "A difference means a check now answers differently for that run.",
    ),
)


def render_corpus_plain(report: CorpusReport) -> str:
    """Render the corpus run in plain English: whether each run matched its expected
    result, its problems, the kinds of failure the runs show, then one What to do and
    one Why per kind of problem."""
    total = len(report.items)
    if total == 0:
        return "Clinescope found no runs to score in this corpus."
    matched = sum(1 for item in report.items if item.matched)
    lines = _plain_corpus_header(total, matched)
    entries: list[tuple[str, PlainProblem]] = []
    for item in report.items:
        lines.append("")
        if item.plain is None:
            results = PlainResults(problems=[PLAIN_UNREADABLE])
            lines.extend(plain_run_lines(item.display, results))
        elif item.matched:
            results = item.plain
            lines.extend(plain_run_lines(item.display, results, suffix=", as expected"))
        else:
            results = item.plain
            lines.extend(
                plain_run_lines(item.display, results, notes=_PLAIN_MISMATCH.problem)
            )
        entries.extend((item.display, problem) for problem in results.problems)
        if item.plain is not None and not item.matched:
            entries.append((item.display, _PLAIN_MISMATCH))
    coverage = _plain_coverage(report)
    if coverage:
        lines.extend(["", coverage])
    lines.extend(plain_kind_blocks(entries))
    return "\n".join(lines)


def _plain_corpus_header(total: int, matched: int) -> list[str]:
    if total == 1:
        verdict = "matched" if matched else "did not match"
        return [
            "Clinescope scored 1 example run and compared it with its expected result.",
            f"The run {verdict} its expected result.",
        ]
    if matched == total:
        verdict = f"All {total} runs matched their expected result."
    else:
        verdict = f"{matched} of {total} runs matched their expected result."
    return [
        f"Clinescope scored {total} example runs and compared each with its expected "
        "result.",
        verdict,
    ]


def _plain_coverage(report: CorpusReport) -> str:
    breakdown = _failure_mode_breakdown(report)
    if not breakdown:
        return ""
    parts = [
        f"{_PLAIN_FAILURE_NAMES[FailureLabel(value)]} "
        f"({count} {'run' if count == 1 else 'runs'})"
        for value, count in breakdown
    ]
    return (
        f"The example runs show {len(breakdown)} of the {len(FailureLabel)} kinds of "
        f"failure Clinescope names: {_plain_and_list(parts)}."
    )


# --- CLI ----------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="clinescope.corpus",
        description=(
            "Score every trace in a validation corpus and assert clinescope "
            "reproduces each hand-written label (scores, advice, no-false-"
            "positives). Exits non-zero if any item fails its label."
        ),
    )
    parser.add_argument(
        "manifest",
        type=Path,
        nargs="?",
        default=None,
        metavar="MANIFEST",
        help=(
            "The corpus manifest (JSON: trace path -> label). Defaults to the bundled "
            "examples/corpus/corpus.json (works from a source checkout or a pip install)."
        ),
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="Print the scorecard table and the per-item verdicts instead",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Parse argv, run the corpus, print the report, return the exit code.

    Returns ``0`` when every item matches its label, ``1`` when any item fails a
    check, ``2`` for a usage-level failure (unloadable trace, empty corpus, or a
    malformed manifest).
    """
    args = _parse_args(argv)
    # Default manifest -> the bundled corpus, whose trace keys are relative to the data
    # root (so they resolve from a pip install too). A user-supplied manifest keeps the
    # historical cwd-relative resolution for its keys.
    if args.manifest is None:
        try:
            manifest = _default_manifest()
            base_dir = datafiles_root()
        except DataFilesNotFound as err:
            print(f"error: {err}", file=sys.stderr)
            return _EXIT_USAGE
    else:
        manifest = args.manifest
        base_dir = Path.cwd()
    try:
        report = run_corpus(manifest, base_dir=base_dir)
    except LabelError as err:
        print(f"error: invalid corpus manifest {manifest}: {err}", file=sys.stderr)
        return _EXIT_USAGE
    except OSError as err:
        print(
            f"error: could not read corpus manifest {manifest}: {err}",
            file=sys.stderr,
        )
        return _EXIT_USAGE
    if args.details:
        print(render_corpus_report(report))
    else:
        print(render_corpus_plain(report))
        # The plain view names no error text, so each load failure's reason goes to
        # stderr, escaped because exception text can carry trace content.
        for item in report.items:
            if not item.loaded:
                reason = item.mismatches[0].removeprefix(_LOAD_FAILURE)
                print(
                    f"error: could not load {item.display}: "
                    f"{quote_untrusted_text(reason)}",
                    file=sys.stderr,
                )
    if report.exit_code == _EXIT_USAGE:
        print(
            "error: corpus run failed at the usage level "
            "(an unloadable trace or an empty corpus)",
            file=sys.stderr,
        )
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
