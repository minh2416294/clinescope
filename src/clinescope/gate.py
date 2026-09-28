"""CI threshold pass/fail gate -- the "suffocate a regressing agent version" gate.

Runs the DETERMINISTIC scorers (:mod:`tool_selection`, :mod:`diff_coherence`,
:mod:`diff_minimality`, :mod:`apply_recovery`, :mod:`editor_recovery`) on a trace,
compares each against a caller-supplied
``--min-*`` threshold, and EXITS NON-ZERO when any gated score is below its
threshold -- so a CI job can block a regressing agent version.

    python -m clinescope.gate <trace.json> --min-diff-coherence 0.75 [--min-...]

**Why it gates on the deterministic scorers only (the load-bearing constraint).**
The LLM judge (:mod:`clinescope.judge`) is ADVISORY-ONLY: judge<->human agreement
came out at Cohen's kappa = 0.0433 (95% CI [0.0000, 0.1503], N=50), which fired the
kappa < 0.5 advisory tripwire. Gating a build on an advisory signal would contradict
the very finding that validation produced.
(A higher figure from an earlier, smaller gold set is RETRACTED: that set was
NOT-WASTEFUL-heavy and flattered a biased judge. The bigger, balanced, blind set
LOWERED the number. Cite only the N=50 figure above.)
(That CI bottoming out at zero rather than going negative is NOT the judge doing
better. It answered WASTEFUL once in fifty, so a bootstrap resample missing that one
item scores exactly zero, and 36% of them do. The prior run, before the judge prompt
fenced its patch text, measured 0.0496 with a CI of [-0.1200, 0.2175]; both are single
draws on a label-flipping model, so the gap is noise, not a prompt effect.)
So this module reads ONLY deterministic, keyless, reproducible scorers (five of the
six; tool_input has no --min-* flag)
and imports NONE of the judge-arc modules (``judge`` / ``judge_run`` /
``agreement`` / ``gold`` / ``label_gold``). An AST test pins that mechanically.

**What the deterministic scorers are NOT (read before you gate on one).**
Deterministic does not mean validated. Only ``diff_minimality`` has ever been
measured against a human label: Cohen's kappa 0.2599 (95% CI [0.0574, 0.4777],
N=50), recall 7 of 24 with a false-alarm rate of 1 of 26, on a gold set that is
authored end to end by one labeler.
``tool_selection``, ``diff_coherence``, ``apply_recovery`` and ``editor_recovery``
have no agreement number at all, so read their silence as unmeasured rather than
as validated. ``tool_selection`` checks tool names only, never their arguments. ``LIMITATIONS.md``
carries the full finding.

**The exit-code contract (CI depends on it precisely):**

* ``0`` -- every gated scorer that produced a number met its threshold.
* ``1`` -- at least one gated scorer scored below its threshold (the
  build-failing verdict).
* ``2`` -- a USAGE error: no ``--min-*`` flag given (a gate that gates nothing
  is a mistake), ``--min-tool-selection`` and ``--expected`` not given together
  (either alone gates nothing), the trace could not be loaded, OR every gated
  scorer abstained on this trace (nothing was verified). A usage error must NEVER masquerade as a
  gate pass (0) or a gate failure (1).

**Deliberate decisions (each a stated choice):**

* **Thresholds are OPTIONAL flags with no defaults.** A scorer is gated only if
  its ``--min-*`` flag is passed; the gate echoes back exactly which thresholds
  it used alongside the verdict (a pass/fail is meaningless without the
  thresholds it was measured against -- the charter's "scores are glued to the
  setup"). At least one flag is required.
* **An abstaining scorer is SKIPPED, not failed.** :class:`DiffMinimalityScore`,
  :class:`ApplyRecoveryScore` and :class:`EditorRecoveryScore` return
  ``score is None`` when the metric is undefined for the trace (no ``apply_patch``,
  no ``editor`` call, or nothing failed). On an editor run where no edit failed,
  ``editor_recovery`` therefore abstains, and only ``--min-tool-selection`` can
  make that clean run pass. ``None`` is not
  ``0.0`` -- it cannot pass or fail a threshold, so it is reported "not gated
  (n/a)" and excluded from the verdict. If EVERY gated scorer abstains, that is
  the loud exit ``2`` above -- never a silent pass.
* **A trace with no ``apply_patch`` is NOT APPLICABLE to the whole apply_patch
  family, including :class:`DiffCoherenceScore`.** That scorer cannot abstain --
  its ``score`` is typed ``float`` and a missing ``apply_patch`` is a deliberate
  hard ``0.0`` (``diff_coherence`` states why: the artifact it was asked to grade
  is absent, so failing loud beats a vacuous ``1.0``). That is the right answer
  for a REPORT on a trace with neither tool (on an editor run the report shows it
  as ``n/a``, see :func:`clinescope.report.is_editor_run`) and the wrong one for a
  GATE, where ``0.0`` is indistinguishable
  from a patch that really did score badly, and exit ``1`` would claim a scorer
  regressed on a trace nothing graded. So the GATE reads
  ``apply_patch_call_count`` and treats a count of ``0`` as not applicable, which
  makes all three apply_patch-family scorers agree at this boundary instead of
  carving one out. Keying on the COUNT and not on the score is what keeps every
  genuine malformed-patch failure failing: a bad input shape, empty patch text,
  unbalanced sentinels and a sub-threshold score all carry a count of at least 1.
  This matters because almost no current Cline session emits ``apply_patch``.

Pure except for :func:`main` (which parses argv, loads the file, and prints):
:func:`run_gate` and :func:`render_gate_report` do no I/O.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from clinescope.apply_recovery import score_apply_recovery
from clinescope.diff_coherence import score_diff_coherence
from clinescope.diff_minimality import score_diff_minimality
from clinescope.editor_recovery import score_editor_recovery
from clinescope.tool_selection import score_tool_selection
from clinescope.tool_vocab import tool_vocab_check
from clinescope.world_a import Trace, load_trace

Verdict = Literal["pass", "fail", "skip"]

# The gated deterministic scorers, keyed by the name used in the --min-* flag, in
# single-trace report order. Each callable takes a Trace and the --expected names
# (read by tool_selection only) and returns a value object exposing ``.score``
# (a ``float`` or ``float | None``). NO judge-arc module appears here.
_ScoreFn = Callable[[Trace, frozenset[str]], object]
_GATED: tuple[tuple[str, _ScoreFn], ...] = (
    (
        "tool_selection",
        lambda trace, expected: score_tool_selection(trace, set(expected)),
    ),
    ("diff_coherence", lambda trace, _expected: score_diff_coherence(trace)),
    ("diff_minimality", lambda trace, _expected: score_diff_minimality(trace)),
    ("apply_recovery", lambda trace, _expected: score_apply_recovery(trace)),
    ("editor_recovery", lambda trace, _expected: score_editor_recovery(trace)),
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


def run_gate(
    trace: Trace,
    thresholds: dict[str, float],
    *,
    expected_tools: Collection[str] = (),
) -> GateReport:
    """Score ``trace`` and compare each requested scorer against its threshold.

    Pure: no I/O, no printing, no ``sys.exit``. ``thresholds`` maps a gated
    scorer name (one of :data:`_GATED_NAMES`) to its minimum acceptable score.
    Unknown names are ignored here (the CLI validates them via argparse).
    ``expected_tools`` is read by ``tool_selection`` only; :func:`main` refuses
    one without the other.
    """
    expected = frozenset(expected_tools)
    results: list[GateResult] = []
    for name, score_fn in _GATED:
        if name not in thresholds:
            continue
        threshold = thresholds[name]
        actual = _gate_score_value(score_fn(trace, expected))
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
    """Read the gateable score off a scorer value object.

    ``None`` means "this scorer did not apply to this trace"; :func:`_gate_verdict`
    turns that into ``skip`` and :func:`run_gate` leaves it out of the verdict. A
    scorer says that in one of two ways, and the second is the one worth explaining.

    ``diff_minimality`` and ``apply_recovery`` return ``score is None`` themselves.
    ``diff_coherence`` cannot, because its ``score`` is typed ``float``. Its hard
    ``0.0`` on a trace with no ``apply_patch`` is deliberate and stays: for a report,
    a missing artifact should read as a loud zero rather than a vacuous 1.0. For a
    GATE it is ambiguous, and the ambiguity is the defect: ``0.0`` from an absent
    patch and ``0.0`` from a genuinely broken one produce the same build-failing
    exit 1, so CI reports "a scorer regressed" about a trace nothing graded.

    ``apply_patch_call_count`` resolves it and is already public on all three
    apply_patch-family results, so no type changes and no new field. Keying on the
    COUNT rather than on the score is deliberate: a bad input shape, empty patch text,
    unbalanced sentinels and a real sub-threshold score all carry a count of at least
    one, so every genuine malformed-patch failure still fails.
    """
    if getattr(score, "apply_patch_call_count", None) == 0:
        return None
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
            "below its --min-* threshold. Gates on deterministic "
            "scorers only -- never the advisory judge."
        ),
    )
    parser.add_argument(
        "trace", type=Path, help="Path to a Cline World-A messages.json trace"
    )
    parser.add_argument(
        "--min-tool-selection",
        type=float,
        default=None,
        metavar="MIN",
        help=(
            "Minimum acceptable tool_selection score, the share of the --expected "
            "tools the run called (gates it when given; needs --expected). It "
            "checks tool names only, not their arguments. It is the one scorer "
            "that gives a number on every run, so it lets a clean editor run pass"
        ),
    )
    parser.add_argument(
        "--expected",
        nargs="+",
        default=None,
        metavar="TOOL",
        help=(
            "Tool names --min-tool-selection checks for, space-separated; run "
            "`clinescope --list-tools` to see valid names"
        ),
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
        help=(
            "Minimum acceptable diff_minimality score (gates it when given). "
            "Against 50 human labels it has Cohen's kappa 0.2599. Of the patches "
            "a human called wasteful it catches "
            "7 of 24 (Wilson 95%% CI [0.149, 0.492]); of those a human did not, "
            "it raises a false alarm on "
            "1 of 26 (Wilson 95%% CI [0.007, 0.189]). Both rates and their "
            "intervals come from authored patches, not "
            "real traces, so the low false-alarm rate is no reason to gate on "
            "it: this flag has never failed a build on any real captured trace "
            "shipped with Clinescope, at any threshold. It scores the "
            "patch text, so the same edit can score 1.0 or 0.0 depending on how "
            "many lines sit between an anchor and the change in the file being "
            "edited. Treat it as a regression tripwire for a shape you have "
            "confirmed in your own traces, not as a general bloat filter. "
            "See LIMITATIONS.md"
        ),
    )
    parser.add_argument(
        "--min-apply-recovery",
        type=float,
        default=None,
        metavar="MIN",
        help="Minimum acceptable apply_recovery score (gates it when given)",
    )
    parser.add_argument(
        "--min-editor-recovery",
        type=float,
        default=None,
        metavar="MIN",
        help=(
            "Minimum acceptable editor_recovery score (gates it when given). It "
            "abstains when no editor call failed, so on its own a clean editor "
            "run verifies nothing and exits 2; add --min-tool-selection for that"
        ),
    )
    return parser.parse_args(argv)


def _collect_thresholds(args: argparse.Namespace) -> dict[str, float]:
    raw = {
        "tool_selection": args.min_tool_selection,
        "diff_coherence": args.min_diff_coherence,
        "diff_minimality": args.min_diff_minimality,
        "apply_recovery": args.min_apply_recovery,
        "editor_recovery": args.min_editor_recovery,
    }
    return {name: value for name, value in raw.items() if value is not None}


def _gate_expected_pairing_error(
    thresholds: dict[str, float], expected: list[str] | None
) -> str | None:
    """A named error when --min-tool-selection and --expected are not given together.

    Either one alone gates nothing, which is the same mistake as passing no
    threshold at all, so both directions are usage errors (exit 2).
    """
    if "tool_selection" in thresholds and expected is None:
        return "error: --min-tool-selection needs --expected TOOL [TOOL ...]"
    if expected is not None and "tool_selection" not in thresholds:
        return "error: --expected is only read by --min-tool-selection"
    return None


def _gate_warn_unknown_expected(expected: list[str]) -> None:
    # Same wording as the clinescope CLI: a typo would silently score as a missing
    # tool, so warn with the nearest known name (a custom tool is still legal).
    for name, suggestion in tool_vocab_check(expected):
        hint = f" - did you mean '{suggestion}'?" if suggestion else ""
        print(f"warning: unknown tool '{name}'{hint}", file=sys.stderr)


def _gate_editor_hint(trace: Trace, thresholds: dict[str, float]) -> str | None:
    """Point an editor run gated only on apply_patch flags at --min-editor-recovery.

    Only counts are printed, never text from the trace.
    """
    if "editor_recovery" in thresholds:
        return None
    editor_calls = sum(1 for call in trace.tool_calls if call.name == "editor")
    patch_calls = sum(1 for call in trace.tool_calls if call.name == "apply_patch")
    if editor_calls == 0 or patch_calls > 0:
        return None
    noun = "call" if editor_calls == 1 else "calls"
    return (
        f"hint: this trace has {editor_calls} editor {noun} and 0 apply_patch "
        "calls; gate it with --min-editor-recovery"
    )


def main(argv: list[str] | None = None) -> int:
    """Parse argv, run the gate, print the report, return the exit code.

    Returns 0 (all gated scorers pass), 1 (a gate failure), or 2 (a usage error:
    no threshold flag, --min-tool-selection and --expected not given together, an
    unloadable trace, or every gated scorer abstained).
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
    pairing_error = _gate_expected_pairing_error(thresholds, args.expected)
    if pairing_error is not None:
        print(pairing_error, file=sys.stderr)
        return _EXIT_USAGE
    if args.expected is not None:
        _gate_warn_unknown_expected(args.expected)

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

    report = run_gate(trace, thresholds, expected_tools=args.expected or ())
    print(render_gate_report(report))
    if report.all_abstained:
        print(
            "error: every gated scorer abstained -- nothing was verified",
            file=sys.stderr,
        )
        hint = _gate_editor_hint(trace, thresholds)
        if hint is not None:
            print(hint, file=sys.stderr)
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
