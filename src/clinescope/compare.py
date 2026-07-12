"""Multi-trace comparison scorecard (deterministic, zero-LLM, stdlib-only).

Scores N traces side by side and prints one comparison TABLE -- a row per trace,
a column per scorer -- so a developer can eyeball, e.g., the same task run
against five different models at once (the Day-22 5-model failure sweep, as a
first-class feature).

    python -m clinescope.compare traceA.json traceB.json ... [--labels manifest.json]

A SIBLING CLI (like :mod:`clinescope.gate`), NOT a flag on the single-trace CLI:
the single-trace ``python -m clinescope`` takes ONE positional trace, and its
output is contractually byte-identical -- so multi-trace comparison lives in its
own module and touches nothing there.

**The anti-drift guarantee (the load-bearing property).** Each table cell and
verdict is produced by the SAME functions the single-trace summary uses -- so a
compare row reproduces exactly what ``python -m clinescope <trace>`` prints for
that trace:

* the three diff scorers -> :func:`clinescope.report.render_score_out_of_100`
  (round-half-up ``NN/100`` / ``n/a``) + :func:`clinescope.report.summary_verdict`
  (``PASS`` at 1.0 / ``FAIL`` / ``n/a`` when abstaining).
* ``tool_selection`` -> :func:`clinescope.report.tool_selection_cell_verdict`,
  which encodes tool_selection's deliberate asymmetry (``n/a`` with no expected
  set; ``PASS`` only at 1.0; a BLANK verdict, never ``FAIL``, for sub-perfect
  recall). A test asserts every ``examples/*.json`` row matches its single-trace
  summary cells.

**Per-trace expected tools.** ``tool_selection`` scores recall against a
caller-supplied expected set. Across N heterogeneous traces a single global
``--expected`` is meaningless, so the expected set is supplied PER TRACE via an
optional ``--labels`` manifest (:mod:`clinescope.labels`). A trace with no label
(or ``expected_tools`` absent/null) shows ``n/a`` for tool_selection -- identical
to omitting ``--expected`` on the single-trace CLI. This same manifest is the
foundation the validation corpus (:mod:`clinescope.corpus`) builds on.

**A per-trace load failure does not abort the table.** Like the single-trace CLI
and the gate, the loader can raise a whole family of failures on a bad trace;
here each is caught PER ROW and rendered as an ``error`` row (all cells ``n/a``)
so one unreadable trace never hides the others' scores. The exit code reflects
whether any row failed to load: ``0`` all traces scored, ``2`` at least one trace
could not be loaded (a usage-level problem), mirroring the gate's "a load failure
is never a silent success" discipline. Comparison itself never "fails" a build --
it is a scorecard, not a threshold gate (that is :mod:`clinescope.gate`).

Pure except for :func:`main`: :func:`run_compare` and
:func:`render_compare_report` do no I/O.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from clinescope.apply_recovery import score_apply_recovery
from clinescope.diff_coherence import score_diff_coherence
from clinescope.diff_minimality import score_diff_minimality
from clinescope.labels import LabelError, TraceLabel, labels_load
from clinescope.report import (
    render_score_out_of_100,
    summary_verdict,
    tool_selection_cell_verdict,
)
from clinescope.tool_selection import score_tool_selection
from clinescope.world_a import Trace, load_trace

# The scorer columns, in single-trace report order. Names match the report labels.
_SCORER_COLUMNS = (
    "tool_selection",
    "diff_coherence",
    "diff_minimality",
    "apply_recovery",
)

_EXIT_OK = 0
_EXIT_LOAD_ERROR = 2


@dataclass(frozen=True, slots=True)
class ScorerCell:
    """One trace x one scorer: the rendered cell + verdict word (may be empty).

    ``cell`` is the ``NN/100`` / ``n/a`` string; ``verdict`` is ``PASS`` / ``FAIL``
    / ``n/a`` / ``""`` (tool_selection's blank sub-100 verdict). Both come from the
    single-trace report helpers, so they are byte-identical to what the
    single-trace CLI prints for the same trace.
    """

    cell: str
    verdict: str


@dataclass(frozen=True, slots=True)
class CompareRow:
    """One trace's row: its display label, per-scorer cells, and load status.

    ``loaded`` is ``False`` when the trace could not be loaded; then every
    :class:`ScorerCell` is ``n/a`` and ``error`` holds the one-line reason.
    """

    label: str
    cells: dict[str, ScorerCell]
    loaded: bool
    error: str | None


@dataclass(frozen=True, slots=True)
class CompareReport:
    """The whole scorecard: one row per input trace, in input order.

    ``exit_code`` is ``0`` when every trace loaded, ``2`` when at least one did
    not (a usage-level failure, never a silent success).
    """

    rows: tuple[CompareRow, ...]
    exit_code: int


def run_compare(
    traces: list[Path], labels: dict[str, TraceLabel] | None = None
) -> CompareReport:
    """Score every trace and build one comparison row each. Pure: no I/O printing.

    ``labels`` maps a trace path to its :class:`~clinescope.labels.TraceLabel`.
    Matching is by RESOLVED path so a manifest key and the CLI trace argument need
    not be spelled identically (``examples/a.json`` vs an absolute path vs a
    backslash/forward-slash separator all match); a verbatim-string fallback keeps
    a key that does not resolve (e.g. a path that no longer exists) still matchable.
    A trace absent from the map (or with ``expected_tools`` ``None``) gets ``n/a``
    for tool_selection. A trace that fails to load becomes an ``error`` row rather
    than aborting the run.
    """
    label_map = labels or {}
    resolved = _resolve_label_keys(label_map)
    rows = [
        _compare_row(trace, _lookup_label(trace, label_map, resolved))
        for trace in traces
    ]
    exit_code = _EXIT_LOAD_ERROR if any(not row.loaded for row in rows) else _EXIT_OK
    return CompareReport(rows=tuple(rows), exit_code=exit_code)


def _resolve_label_keys(labels: dict[str, TraceLabel]) -> dict[Path, TraceLabel]:
    # Index labels by resolved path so path SPELLING (separator, relative vs
    # absolute, "./" prefix) never causes a silent miss. A key that cannot be
    # resolved is skipped here and still reachable via the verbatim fallback.
    #
    # Two DIFFERENT keys that resolve to the SAME path with CONFLICTING labels
    # (e.g. different expected_tools) would otherwise collapse silently -- a
    # silently-ignored label scores the wrong thing, exactly what labels.py's
    # fail-loud discipline forbids. Raise naming both keys. Identical labels for
    # the same path are harmless and allowed (a redundant, not conflicting, dupe).
    resolved: dict[Path, TraceLabel] = {}
    source_key: dict[Path, str] = {}
    for key, label in labels.items():
        try:
            path = Path(key).resolve()
        except OSError:
            continue
        prior = resolved.get(path)
        if prior is not None and prior != label:
            raise LabelError(
                f"labels keys {source_key[path]!r} and {key!r} resolve to the same "
                f"path {path} but carry different labels"
            )
        resolved[path] = label
        source_key[path] = key
    return resolved


def _lookup_label(
    trace: Path,
    verbatim: dict[str, TraceLabel],
    resolved: dict[Path, TraceLabel],
) -> TraceLabel | None:
    try:
        by_resolved = resolved.get(trace.resolve())
    except OSError:
        by_resolved = None
    if by_resolved is not None:
        return by_resolved
    return verbatim.get(str(trace))


def _compare_row(trace_path: Path, label: TraceLabel | None) -> CompareRow:
    display = _row_label(trace_path, label)
    # Per-row load boundary: mirror the single-trace CLI / gate broad catch so one
    # unreadable trace renders as an error row (all cells n/a) instead of taking
    # the whole table down. The loader raises a family of failures on bad input
    # (OSError, json.JSONDecodeError, WorldATraceError, AttributeError/TypeError on
    # structurally-invalid JSON) -- this is the deliberate boundary, not swallowed
    # application logic.
    try:
        trace = load_trace(trace_path)
    except Exception as err:  # noqa: BLE001 -- deliberate per-row load boundary (see above)
        return CompareRow(
            label=display,
            cells=_all_na_cells(),
            loaded=False,
            error=f"{type(err).__name__}: {err}",
        )
    return CompareRow(
        label=display,
        cells=_score_cells(trace, label),
        loaded=True,
        error=None,
    )


def _row_label(trace_path: Path, label: TraceLabel | None) -> str:
    # A human-readable row name: the manifest's display override if given, else
    # the trace filename stem (stable + greppable, unlike a volatile sessionId).
    if label is not None and label.display is not None:
        return label.display
    return trace_path.stem


def _score_cells(trace: Trace, label: TraceLabel | None) -> dict[str, ScorerCell]:
    # tool_selection is opt-in per trace: only score it when the label supplies an
    # expected-tools set. Absent/None -> expected_provided False -> the same n/a
    # cell the single-trace CLI shows for an omitted --expected.
    expected_tools = label.expected_tools if label is not None else None
    expected_provided = expected_tools is not None
    ts_score = score_tool_selection(trace, set(expected_tools or ()))
    ts_cell, ts_verdict = tool_selection_cell_verdict(ts_score, expected_provided)

    diff_scores = {
        "diff_coherence": score_diff_coherence(trace).score,
        "diff_minimality": score_diff_minimality(trace).score,
        "apply_recovery": score_apply_recovery(trace).score,
    }
    cells = {"tool_selection": ScorerCell(cell=ts_cell, verdict=ts_verdict)}
    for name, value in diff_scores.items():
        cells[name] = ScorerCell(
            cell=render_score_out_of_100(value),
            verdict=summary_verdict(value),
        )
    return cells


def _all_na_cells() -> dict[str, ScorerCell]:
    return {name: ScorerCell(cell="n/a", verdict="n/a") for name in _SCORER_COLUMNS}


# --- Rendering (pure) ---------------------------------------------------------


def render_compare_report(report: CompareReport) -> str:
    """Render the scorecard as an aligned text table (header + one row per trace).

    Each scorer column shows ``NN/100`` with its verdict word appended when the
    verdict is non-empty (e.g. ``100/100 PASS``, ``0/100 FAIL``, ``n/a``). Column
    widths are computed from the actual content so the table stays aligned for any
    trace set.
    """
    header = ["trace", *_SCORER_COLUMNS]
    body = [[row.label, *_row_cell_texts(row)] for row in report.rows]
    widths = _column_widths(header, body)
    lines = [
        "=== clinescope compare ===",
        _render_table_row(header, widths),
        _render_table_row(["-" * w for w in widths], widths),
    ]
    lines.extend(_render_table_row(cols, widths) for cols in body)
    load_errors = [row for row in report.rows if not row.loaded]
    if load_errors:
        lines.append("")
        lines.extend(
            f"error: could not load {row.label}: {row.error}" for row in load_errors
        )
    return "\n".join(lines)


def _row_cell_texts(row: CompareRow) -> list[str]:
    return [_cell_text(row.cells[name]) for name in _SCORER_COLUMNS]


def _cell_text(cell: ScorerCell) -> str:
    # Append the verdict word only when it ADDS information: skip it when empty
    # (tool_selection's sub-100 blank verdict shows just the number, matching the
    # single-trace summary) and skip it when it just repeats the cell (an
    # abstaining scorer's cell is already "n/a" -- "n/a n/a" is noise).
    if cell.verdict and cell.verdict != cell.cell:
        return f"{cell.cell} {cell.verdict}"
    return cell.cell


def _column_widths(header: list[str], body: list[list[str]]) -> list[int]:
    widths = [len(col) for col in header]
    for cols in body:
        for i, col in enumerate(cols):
            widths[i] = max(widths[i], len(col))
    return widths


def _render_table_row(cols: list[str], widths: list[int]) -> str:
    return "  ".join(col.ljust(widths[i]) for i, col in enumerate(cols)).rstrip()


# --- CLI ----------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="clinescope.compare",
        description=(
            "Score N Cline World-A traces side by side and print a comparison "
            "table (one row per trace; columns = the four scorers). Use --labels "
            "to supply per-trace expected tools for the tool_selection column."
        ),
    )
    parser.add_argument(
        "traces",
        type=Path,
        nargs="+",
        metavar="TRACE",
        help="One or more Cline World-A messages.json traces to compare",
    )
    parser.add_argument(
        "--labels",
        type=Path,
        default=None,
        metavar="MANIFEST",
        help=(
            "Optional JSON manifest mapping trace path -> {display, expected_tools}; "
            "supplies per-trace expected tools so tool_selection can be scored"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Parse argv, score the traces, print the table, return the exit code.

    Returns ``0`` when every trace loaded and scored, ``2`` when at least one
    trace could not be loaded (an error row is still shown for it) or the
    ``--labels`` manifest is malformed.
    """
    args = _parse_args(argv)
    labels: dict[str, TraceLabel] | None = None
    if args.labels is not None:
        try:
            labels = labels_load(args.labels)
        except Exception as err:  # noqa: BLE001 -- deliberate manifest-load boundary
            print(
                f"error: could not load labels {args.labels}: "
                f"{type(err).__name__}: {err}",
                file=sys.stderr,
            )
            return _EXIT_LOAD_ERROR
    # run_compare resolves the label keys and raises LabelError on a same-path
    # conflict -- a manifest-shape problem, so it joins the usage exit 2 above.
    try:
        report = run_compare(list(args.traces), labels)
    except LabelError as err:
        print(f"error: invalid labels {args.labels}: {err}", file=sys.stderr)
        return _EXIT_LOAD_ERROR
    print(render_compare_report(report))
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
