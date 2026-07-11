"""CI threshold pass/fail gate -- the "suffocate a regressing agent version" gate.

Runs the DETERMINISTIC scorers (:mod:`diff_coherence`, :mod:`diff_minimality`,
:mod:`apply_recovery`) on a trace, compares each against a caller-supplied
``--min-*`` threshold, and EXITS NON-ZERO when any gated score is below its
threshold -- so a CI job can block a regressing agent version.

    python -m clinescope.gate <trace.json> --min-diff-coherence 0.75 [--min-...]

**Why it gates on the deterministic scorers only (the load-bearing constraint).**
The LLM judge (:mod:`clinescope.judge`) is ADVISORY-ONLY: judge<->human agreement
came out at Cohen's kappa = 0.2353 (95% CI [0.0, 0.5229], N=26), which fired the
kappa < 0.5 advisory tripwire. Gating a build on an advisory signal would
contradict the very finding that validation produced. So this module reads ONLY
the three deterministic, keyless, reproducible scorers and imports NONE of the
judge-arc modules (``judge`` / ``judge_run`` / ``agreement`` / ``gold`` /
``label_gold``). An AST test pins that mechanically.

**The exit-code contract (CI depends on it precisely):**

* ``0`` -- every gated scorer that produced a number met its threshold.
* ``1`` -- at least one gated scorer scored below its threshold (the
  build-failing verdict).
* ``2`` -- a USAGE error: no ``--min-*`` flag given (a gate that gates nothing
  is a mistake), the trace could not be loaded, OR every gated scorer abstained
  on this trace (nothing was verified). A usage error must NEVER masquerade as a
  gate pass (0) or a gate failure (1).

**Deliberate decisions (each a stated choice):**

* **Thresholds are OPTIONAL flags with no defaults.** A scorer is gated only if
  its ``--min-*`` flag is passed; the gate echoes back exactly which thresholds
  it used alongside the verdict (a pass/fail is meaningless without the
  thresholds it was measured against -- the charter's "scores are glued to the
  setup"). At least one flag is required.
* **An abstaining scorer is SKIPPED, not failed.** :class:`DiffMinimalityScore`
  and :class:`ApplyRecoveryScore` return ``score is None`` when the metric is
  undefined for the trace (no ``apply_patch`` / nothing failed). ``None`` is not
  ``0.0`` -- it cannot pass or fail a threshold, so it is reported "not gated
  (n/a)" and excluded from the verdict. (:class:`DiffCoherenceScore` never
  abstains: its ``score`` is always a ``float``, a missing ``apply_patch`` being
  a hard ``0.0``.) If EVERY gated scorer abstains, that is the loud exit ``2``
  above -- never a silent pass.

Pure except for :func:`main` (which parses argv, loads the file, and prints):
:func:`run_gate` and :func:`render_gate_report` do no I/O.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from clinescope.apply_recovery import score_apply_recovery
from clinescope.diff_coherence import score_diff_coherence
from clinescope.diff_minimality import score_diff_minimality
from clinescope.world_a import Trace, load_trace

Verdict = Literal["pass", "fail", "skip"]

# The gated deterministic scorers, keyed by the name used in the --min-* flag.
# Each callable takes a Trace and returns a value object exposing ``.score``
# (a ``float`` or ``float | None``). NO judge-arc module appears here.
_ScoreFn = Callable[[Trace], object]
_GATED: tuple[tuple[str, _ScoreFn], ...] = (
    ("diff_coherence", score_diff_coherence),
    ("diff_minimality", score_diff_minimality),
    ("apply_recovery", score_apply_recovery),
)
_GATED_NAMES = tuple(name for name, _ in _GATED)

# Exit codes -- the CI contract.
_EXIT_PASS = 0
_EXIT_FAIL = 1
_EXIT_USAGE = 2


@dataclass(frozen=True, slots=True)
class GateResult:
    """One scorer's verdict against its threshold.

    ``actual`` is the scorer's ``.score`` -- ``None`` when the scorer abstained
    (then ``verdict == "skip"``). ``verdict`` is ``"pass"`` iff
    ``actual >= threshold``, ``"fail"`` iff ``actual < threshold``, ``"skip"``
    iff ``actual is None`` (undefined -- excluded from the aggregate).
    """

    name: str
    threshold: float
    actual: float | None
    verdict: Verdict


@dataclass(frozen=True, slots=True)
class GateReport:
    """Aggregate result of a gate run.

    * ``passed`` is ``True`` iff at least one scorer produced a non-skip verdict
      AND no scorer failed. An all-``skip`` run is NOT a pass (``all_abstained``).
    * ``all_abstained`` is ``True`` iff every gated scorer abstained -- nothing
      was verified, which the CLI surfaces as the usage exit ``2``.
    * ``exit_code`` is the CI contract value (0 pass / 1 fail / 2 all-abstained).
    * ``thresholds`` echoes the caller's requested ``{name: min}`` map.
    """

    results: tuple[GateResult, ...]
    thresholds: dict[str, float]
    passed: bool
    all_abstained: bool
    exit_code: int


def run_gate(trace: Trace, thresholds: dict[str, float]) -> GateReport:
    """Score ``trace`` and compare each requested scorer against its threshold.

    Pure: no I/O, no printing, no ``sys.exit``. ``thresholds`` maps a gated
    scorer name (one of :data:`_GATED_NAMES`) to its minimum acceptable score.
    Unknown names are ignored here (the CLI validates them via argparse).
    """
    results: list[GateResult] = []
    for name, score_fn in _GATED:
        if name not in thresholds:
            continue
        threshold = thresholds[name]
        actual = _gate_score_value(score_fn(trace))
        results.append(
            GateResult(
                name=name,
                threshold=threshold,
                actual=actual,
                verdict=_gate_verdict(actual, threshold),
            )
        )

    # "Nothing verified" -> exit 2, whether that's because every gated scorer
    # abstained OR no threshold was requested at all: an empty gate is a usage
    # mistake, not a pass or a fail. (main() guards the no-threshold case before
    # ever calling run_gate; this keeps the pure function agreeing with it.)
    graded = [r for r in results if r.verdict != "skip"]
    all_abstained = len(graded) == 0
    passed = len(graded) > 0 and all(r.verdict == "pass" for r in graded)
    return GateReport(
        results=tuple(results),
        thresholds=dict(thresholds),
        passed=passed,
        all_abstained=all_abstained,
        exit_code=_gate_exit_code(passed=passed, all_abstained=all_abstained),
    )


def _gate_score_value(score: object) -> float | None:
    """Read ``.score`` off a scorer value object (``float`` or ``float | None``)."""
    value = getattr(score, "score", None)
    if value is None or isinstance(value, float):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    raise TypeError(f"unexpected score type {type(value).__name__} on {score!r:.60}")


def _gate_verdict(actual: float | None, threshold: float) -> Verdict:
    if actual is None:
        return "skip"
    return "pass" if actual >= threshold else "fail"


def _gate_exit_code(*, passed: bool, all_abstained: bool) -> int:
    if all_abstained:
        return _EXIT_USAGE
    return _EXIT_PASS if passed else _EXIT_FAIL


def render_gate_report(report: GateReport) -> str:
    """A human- and CI-log-readable rendering of a gate run.

    Each gated scorer gets one line naming its actual score, threshold, and
    verdict; abstaining scorers are shown as skipped/not-gated. The final line
    is the VERDICT plus the thresholds used (never a floating verdict).
    """
    lines = ["=== clinescope gate ==="]
    for result in report.results:
        lines.append(_render_gate_result(result))
    lines.append("")
    lines.append(_render_gate_verdict(report))
    return "\n".join(lines)


def _render_gate_result(result: GateResult) -> str:
    if result.verdict == "skip":
        return (
            f"[gate] {result.name}: n/a -> SKIP "
            f"(not gated, scorer not applicable to this trace)"
        )
    relation = ">=" if result.verdict == "pass" else "<"
    tag = "PASS" if result.verdict == "pass" else "FAIL"
    return (
        f"[gate] {result.name}: {result.actual:.4f} {relation} "
        f"min {result.threshold:.4f} -> {tag}"
    )


def _render_gate_verdict(report: GateReport) -> str:
    echo = _render_thresholds(report.thresholds)
    if report.all_abstained:
        return (
            "VERDICT: ERROR -- every gated scorer abstained on this trace; "
            f"nothing was verified (thresholds: {echo})"
        )
    tag = "PASS" if report.passed else "FAIL"
    return f"VERDICT: {tag} (thresholds: {echo})"


def _render_thresholds(thresholds: dict[str, float]) -> str:
    if not thresholds:
        return "-"
    return ", ".join(
        f"{name}>={thresholds[name]:.4f}" for name in _GATED_NAMES if name in thresholds
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="clinescope.gate",
        description=(
            "CI threshold gate: fail the build when a deterministic scorer is "
            "below its --min-* threshold. Gates on diff_coherence / "
            "diff_minimality / apply_recovery only -- never the advisory judge."
        ),
    )
    parser.add_argument(
        "trace", type=Path, help="Path to a Cline World-A messages.json trace"
    )
    parser.add_argument(
        "--min-diff-coherence",
        type=float,
        default=None,
        metavar="MIN",
        help="Minimum acceptable diff_coherence score (gates it when given)",
    )
    parser.add_argument(
        "--min-diff-minimality",
        type=float,
        default=None,
        metavar="MIN",
        help="Minimum acceptable diff_minimality score (gates it when given)",
    )
    parser.add_argument(
        "--min-apply-recovery",
        type=float,
        default=None,
        metavar="MIN",
        help="Minimum acceptable apply_recovery score (gates it when given)",
    )
    return parser.parse_args(argv)


def _collect_thresholds(args: argparse.Namespace) -> dict[str, float]:
    raw = {
        "diff_coherence": args.min_diff_coherence,
        "diff_minimality": args.min_diff_minimality,
        "apply_recovery": args.min_apply_recovery,
    }
    return {name: value for name, value in raw.items() if value is not None}


def main(argv: list[str] | None = None) -> int:
    """Parse argv, run the gate, print the report, return the exit code.

    Returns 0 (all gated scorers pass), 1 (a gate failure), or 2 (a usage error:
    no threshold flag, an unloadable trace, or every gated scorer abstained).
    """
    args = _parse_args(argv)

    thresholds = _collect_thresholds(args)
    if not thresholds:
        print(
            "error: no threshold given; pass at least one of "
            f"{', '.join('--min-' + n.replace('_', '-') for n in _GATED_NAMES)}",
            file=sys.stderr,
        )
        return _EXIT_USAGE

    # A trace that cannot be turned into something scorable is a USAGE error
    # (exit 2), never a gate verdict (0/1) -- otherwise CI would read exit 1
    # ("a scorer regressed") for a trace that was never scored at all. The
    # loader raises a WHOLE FAMILY of load/parse failures beyond its own
    # WorldATraceError: OSError/UnicodeDecodeError from reading a missing or
    # non-UTF-8 file, json.JSONDecodeError from bad JSON, and even an
    # AttributeError/TypeError when a JSON-parseable-but-structurally-invalid
    # trace (e.g. "messages" not a list) trips the parser. Catch broadly here so
    # every such failure normalizes to the exit-2 usage path -- this is the
    # deliberate load boundary, not swallowed application logic. (Gate-4 Day-18:
    # a narrow ``except`` leaked UnicodeDecodeError/AttributeError through as 1.)
    try:
        trace = load_trace(args.trace)
    except Exception as err:  # noqa: BLE001 -- deliberate load-failure boundary (see above)
        print(
            f"error: could not load trace {args.trace}: {type(err).__name__}: {err}",
            file=sys.stderr,
        )
        return _EXIT_USAGE

    report = run_gate(trace, thresholds)
    print(render_gate_report(report))
    if report.all_abstained:
        print(
            "error: every gated scorer abstained -- nothing was verified",
            file=sys.stderr,
        )
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
