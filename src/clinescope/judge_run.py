"""Opt-in judge runner + Cohen's-κ reporter -- judge-validation, segment 4.

Two responsibilities, deliberately split so re-running κ never re-hits the model:

* **Run** (`judge_run_over_gold` + `judge_run_write_cache`): judge every gold item's
  first apply_patch with the live model and CACHE the verdicts to a committed
  ``gold/diff_minimality.judge.jsonl``. This is the ONLY step that costs a model call.
* **Report** (`judge_kappa_load_pairs` + `judge_kappa_confusion` + `judge_kappa_report`):
  read the human gold labels + the cached judge labels, align them, and print
  chance-corrected agreement (Cohen's κ + a bootstrap CI + a stratified breakdown)
  via :func:`clinescope.agreement.cohen_kappa`. Free, deterministic, re-runnable with
  no model call.

**Deliberate decisions:**

* This is an OPT-IN entry point (``python -m clinescope.judge_run``). It is NOT wired
  into ``python -m clinescope <trace>`` -- the default path stays keyless / zero-LLM /
  deterministic, which is the harness's identity.
* The judge is BLIND and answers from patch text alone (see :mod:`clinescope.judge`).
  An unparseable / errored item is recorded EXPLICITLY in the cache and EXCLUDED from
  the κ input lists (never silently defaulted to a class, which would bias κ); the
  runner surfaces the dropped count loudly.
* The cache is written LF-only (``.gitattributes`` pins ``*.jsonl eol=lf``) via
  ``write_bytes`` with explicit ``\n`` -- never ``write_text`` / ``print`` (which drift
  CRLF↔LF across platforms). The cache is a fresh authored file, so a full LF rewrite
  is correct; it mirrors ``label_gold.label_gold_write_label``'s byte discipline.
* κ is computed by the REUSED :func:`clinescope.agreement.cohen_kappa` -- never
  reimplemented. Alignment is positional over the gold file order; each cache row
  carries the item's ``patch_sha256`` so the reporter fails LOUD if the gold patch
  drifted since the cache was written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from clinescope.agreement import CohenKappaResult, cohen_kappa
from clinescope.diff_coherence import diff_coherence_read_patch_text
from clinescope.gold import ResolvedGoldItem, gold_load_resolved
from clinescope.judge import (
    JudgeError,
    judge_diff_minimality,
)

_JUDGE_CACHE_SCHEMA_VERSION = 1
_DIMENSION = "diff_minimality"

# A cache row's outcome: a usable verdict, an unparseable answer, or a call error.
JudgeOutcome = Literal["verdict", "unparseable", "error"]

# The κ<0.5 tripwire (protocol §7): below this the judge is advisory-only.
_KAPPA_ADVISORY_FLOOR = 0.5


@dataclass(frozen=True, slots=True)
class JudgeCacheRow:
    """One judged gold item, as cached in ``gold/diff_minimality.judge.jsonl``.

    Invariants:

    * ``outcome == "verdict"`` iff ``judge_label`` is a real verdict; for
      ``"unparseable"`` / ``"error"`` the ``judge_label`` is ``None`` and the item is
      EXCLUDED from κ. ``rationale`` / ``raw_response`` keep the model text for audit.
    * ``patch_sha256`` pins the exact lifted patch text judged, so the reporter can
      fail loud if the gold trace drifted between the run and the report.
    """

    item_id: str
    outcome: JudgeOutcome
    judge_label: str | None
    rationale: str
    model_id: str
    patch_sha256: str
    judged_at: str


@dataclass(frozen=True, slots=True)
class JudgeRunResult:
    """The outcome of judging every gold item once (before caching)."""

    rows: tuple[JudgeCacheRow, ...]
    model_id: str
    n_attempted: int
    n_verdicts: int
    n_unparseable: int
    n_error: int


@dataclass(frozen=True, slots=True)
class KappaInputs:
    """Aligned human + judge label lists (verdict-only) plus the dropped counts."""

    human_labels: tuple[str, ...]
    judge_labels: tuple[str, ...]
    model_id: str
    n_gold: int
    n_unparseable: int
    n_error: int


# --------------------------------------------------------------------------- run


def judge_run_over_gold(
    gold_path: str | Path,
    *,
    repo_root: Path,
    model_id: str,
    base_url: str,
    now_iso: str,
) -> JudgeRunResult:
    """Judge every gold item's first apply_patch once; collect cache rows.

    Loads the gold items in FILE ORDER (κ is positional), judges each blind, and records
    a verdict / unparseable / error outcome per item. ``now_iso`` is passed in (never
    stamped inside) so the run is deterministic and testable.
    """
    resolved = gold_load_resolved(gold_path, repo_root=repo_root)
    rows = tuple(
        _judge_run_one(item, model_id=model_id, base_url=base_url, now_iso=now_iso)
        for item in resolved
    )
    return JudgeRunResult(
        rows=rows,
        model_id=model_id,
        n_attempted=len(rows),
        n_verdicts=sum(1 for r in rows if r.outcome == "verdict"),
        n_unparseable=sum(1 for r in rows if r.outcome == "unparseable"),
        n_error=sum(1 for r in rows if r.outcome == "error"),
    )


def _judge_run_one(
    item: ResolvedGoldItem, *, model_id: str, base_url: str, now_iso: str
) -> JudgeCacheRow:
    """Judge one resolved gold item, mapping any JudgeError to an explicit outcome."""
    patch_sha256 = _judge_run_patch_sha256(item)
    try:
        label = judge_diff_minimality(item.trace, model_id=model_id, base_url=base_url)
    except JudgeError as err:
        outcome = _judge_error_outcome(err)
        return JudgeCacheRow(
            item_id=item.item.item_id,
            outcome=outcome,
            judge_label=None,
            rationale=f"{type(err).__name__}: {err}",
            model_id=model_id,
            patch_sha256=patch_sha256,
            judged_at=now_iso,
        )
    return JudgeCacheRow(
        item_id=item.item.item_id,
        outcome="verdict",
        judge_label=label.label,
        rationale=label.rationale,
        model_id=label.model_id,
        patch_sha256=patch_sha256,
        judged_at=now_iso,
    )


def _judge_error_outcome(err: JudgeError) -> Literal["unparseable", "error"]:
    """An unparseable answer is its own outcome; every other JudgeError is an error."""
    from clinescope.judge import JudgeUnparseableError

    return "unparseable" if isinstance(err, JudgeUnparseableError) else "error"


def _judge_run_patch_sha256(item: ResolvedGoldItem) -> str:
    """sha256 of the exact lifted patch text judged (matches the gold-drift preimage)."""
    text = diff_coherence_read_patch_text(item.scored_call)
    if text is None:  # pragma: no cover - gold_resolve_item already rejects this
        raise JudgeError(
            f"gold item {item.item.item_id!r}: first apply_patch has no readable text"
        )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def judge_run_write_cache(result: JudgeRunResult, cache_path: str | Path) -> None:
    """Write the run's rows to a committed JSONL cache, LF-only, one object per line.

    Uses ``write_bytes`` with an explicit ``\\n`` terminator (never ``write_text`` /
    ``print``) so the file is byte-identical on Windows and Linux/CI -- the cache is a
    versioned artifact and ``.gitattributes`` pins ``*.jsonl eol=lf``.
    """
    lines = [_judge_cache_row_json(row) for row in result.rows]
    body = "\n".join(lines) + "\n" if lines else ""
    Path(cache_path).write_bytes(body.encode("utf-8"))


def _judge_cache_row_json(row: JudgeCacheRow) -> str:
    """Serialize one cache row to a compact JSON object (stable key order)."""
    record = {
        "schema_version": _JUDGE_CACHE_SCHEMA_VERSION,
        "item_id": row.item_id,
        "dimension": _DIMENSION,
        "outcome": row.outcome,
        "judge_label": row.judge_label,
        "rationale": row.rationale,
        "model_id": row.model_id,
        "patch_sha256": row.patch_sha256,
        "judged_at": row.judged_at,
    }
    return json.dumps(record, ensure_ascii=False)


def judge_run_now_iso() -> str:
    """Current UTC time as an ISO-8601 string (the CLI's ``judged_at`` source)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ------------------------------------------------------------------------ report


def judge_kappa_load_pairs(
    gold_path: str | Path, cache_path: str | Path, *, repo_root: Path
) -> KappaInputs:
    """Join human gold labels with cached judge labels; build aligned verdict-only lists.

    Aligns by ``item_id`` in gold file order. Verifies each cache row's ``patch_sha256``
    against the gold patch (fail loud on drift). Only ``outcome == "verdict"`` items with
    a non-null human label enter the κ lists; unparseable / error items are dropped and
    counted.

    Raises:
        JudgeError: A gold item is unlabeled, has no cache row, or the cached patch
            digest disagrees with the gold trace (drift).
    """
    resolved = gold_load_resolved(gold_path, repo_root=repo_root)
    cache = _judge_load_cache(cache_path)
    human: list[str] = []
    judge: list[str] = []
    model_ids: set[str] = set()
    n_unparseable = 0
    n_error = 0
    for item in resolved:
        row = _judge_require_cache_row(cache, item)
        model_ids.add(row.model_id)
        _judge_verify_no_drift(item, row)
        if row.outcome == "unparseable":
            n_unparseable += 1
            continue
        if row.outcome == "error":
            n_error += 1
            continue
        human.append(_judge_require_human_label(item))
        judge.append(_judge_require_cached_verdict(row))
    return KappaInputs(
        human_labels=tuple(human),
        judge_labels=tuple(judge),
        model_id=_judge_join_model_ids(model_ids),
        n_gold=len(resolved),
        n_unparseable=n_unparseable,
        n_error=n_error,
    )


def _judge_load_cache(cache_path: str | Path) -> dict[str, JudgeCacheRow]:
    """Parse the judge cache JSONL into an item_id -> row map (fail loud on a bad line).

    A missing cache file is a clean :class:`JudgeError` (the actionable "run the judge
    first" message), never a raw ``FileNotFoundError`` traceback. A DUPLICATE ``item_id``
    is rejected, not last-write-wins collapsed -- the κ alignment joins the gold tuple
    against this map, so a repeated id would silently mislabel / double-count a pairing.
    """
    try:
        text = Path(cache_path).read_text(encoding="utf-8")
    except FileNotFoundError as err:
        raise JudgeError(
            f"no judge cache at {cache_path}; run `python -m clinescope.judge_run` "
            f"first to build it"
        ) from err
    rows: dict[str, JudgeCacheRow] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        item_id = _judge_parse_cache_id(line, line_number)
        if item_id in rows:
            raise JudgeError(
                f"judge cache line {line_number}: duplicate item_id {item_id!r}; each "
                f"gold item must be judged exactly once"
            )
        rows[item_id] = _judge_parse_cache_row(line, line_number)
    return rows


def _judge_parse_cache_id(line: str, line_number: int) -> str:
    row = _judge_cache_raw(line, line_number)
    item_id = row.get("item_id")
    if not isinstance(item_id, str):
        raise JudgeError(f"judge cache line {line_number}: item_id must be a str")
    return item_id


def _judge_cache_raw(line: str, line_number: int) -> dict[str, object]:
    try:
        raw = json.loads(line)
    except json.JSONDecodeError as err:
        raise JudgeError(
            f"judge cache line {line_number}: not valid JSON ({err})"
        ) from err
    if not isinstance(raw, dict):
        raise JudgeError(f"judge cache line {line_number}: expected a JSON object")
    return raw


def _judge_parse_cache_row(line: str, line_number: int) -> JudgeCacheRow:
    raw = _judge_cache_raw(line, line_number)
    outcome = raw.get("outcome")
    if outcome not in ("verdict", "unparseable", "error"):
        raise JudgeError(
            f"judge cache line {line_number}: outcome must be verdict/unparseable/error"
        )
    label = raw.get("judge_label")
    if outcome == "verdict" and label not in ("WASTEFUL", "NOT-WASTEFUL"):
        raise JudgeError(
            f"judge cache line {line_number}: a verdict row needs a WASTEFUL/"
            f"NOT-WASTEFUL judge_label, got {label!r}"
        )
    return JudgeCacheRow(
        item_id=_judge_cache_str(raw, "item_id", line_number),
        outcome=outcome,
        judge_label=label if isinstance(label, str) else None,
        rationale=_judge_cache_str(raw, "rationale", line_number, default=""),
        model_id=_judge_cache_str(raw, "model_id", line_number),
        patch_sha256=_judge_cache_str(raw, "patch_sha256", line_number),
        judged_at=_judge_cache_str(raw, "judged_at", line_number, default=""),
    )


def _judge_cache_str(
    raw: dict[str, object], field: str, line_number: int, *, default: str | None = None
) -> str:
    value = raw.get(field)
    if value is None and default is not None:
        return default
    if not isinstance(value, str):
        raise JudgeError(
            f"judge cache line {line_number}: field {field!r} must be a str"
        )
    return value


def _judge_require_cache_row(
    cache: dict[str, JudgeCacheRow], item: ResolvedGoldItem
) -> JudgeCacheRow:
    row = cache.get(item.item.item_id)
    if row is None:
        raise JudgeError(
            f"gold item {item.item.item_id!r} has no row in the judge cache; "
            f"re-run `python -m clinescope.judge_run` to (re)build it"
        )
    return row


def _judge_verify_no_drift(item: ResolvedGoldItem, row: JudgeCacheRow) -> None:
    text = diff_coherence_read_patch_text(item.scored_call)
    actual = (
        hashlib.sha256(text.encode("utf-8")).hexdigest() if text is not None else ""
    )
    if actual != row.patch_sha256:
        raise JudgeError(
            f"gold item {item.item.item_id!r}: patch drifted since it was judged "
            f"(cache {row.patch_sha256}, now {actual}); re-run the judge"
        )


def _judge_require_human_label(item: ResolvedGoldItem) -> str:
    label = item.item.human_label
    if label is None:
        raise JudgeError(
            f"gold item {item.item.item_id!r} has no human_label; the gold set must be "
            f"fully labeled before κ can be computed"
        )
    return label


def _judge_require_cached_verdict(row: JudgeCacheRow) -> str:
    if row.judge_label is None:  # pragma: no cover - guarded by outcome=="verdict"
        raise JudgeError(f"judge cache row {row.item_id!r}: verdict with no label")
    return row.judge_label


def _judge_join_model_ids(model_ids: set[str]) -> str:
    if not model_ids:
        return "<none>"
    return ", ".join(sorted(model_ids))


def judge_kappa_confusion(
    human_labels: tuple[str, ...], judge_labels: tuple[str, ...]
) -> tuple[int, int, int, int]:
    """Return the 2x2 confusion counts ``(a, b, c, d)`` for the aligned label lists.

    Rows = HUMAN, cols = JUDGE::

        a = human WASTEFUL     & judge WASTEFUL
        b = human WASTEFUL     & judge NOT-WASTEFUL
        c = human NOT-WASTEFUL & judge WASTEFUL
        d = human NOT-WASTEFUL & judge NOT-WASTEFUL
    """
    a = b = c = d = 0
    for h, j in zip(human_labels, judge_labels):
        if h == "WASTEFUL" and j == "WASTEFUL":
            a += 1
        elif h == "WASTEFUL" and j == "NOT-WASTEFUL":
            b += 1
        elif h == "NOT-WASTEFUL" and j == "WASTEFUL":
            c += 1
        else:
            d += 1
    return a, b, c, d


def judge_kappa_report(inputs: KappaInputs) -> str:
    """Format the stratified κ report string (pure; no I/O, testable without a model).

    Prints the overall Cohen's κ + a seeded bootstrap 95% CI, the counts (gold /
    verdicts / unparseable / errors / effective N), the 2x2 confusion matrix, per-label
    agreement, the κ<0.5 → advisory tripwire (protocol §7), and the honest small-N
    wide-CI caveat.
    """
    n_kappa = len(inputs.human_labels)
    lines = _judge_report_header(inputs, n_kappa)
    if n_kappa == 0:
        lines.append("")
        lines.append("no verdicts to score -- κ is undefined (every item dropped).")
        return "\n".join(lines)
    result = cohen_kappa(inputs.human_labels, inputs.judge_labels)
    lines.extend(_judge_report_kappa(result))
    lines.extend(_judge_report_confusion(inputs))
    lines.extend(_judge_report_interpretation(result, n_kappa))
    return "\n".join(lines)


def _judge_report_header(inputs: KappaInputs, n_kappa: int) -> list[str]:
    return [
        f"=== clinescope judge κ report ({_DIMENSION}) ===",
        f"model_id:        {inputs.model_id}",
        f"gold_items:      {inputs.n_gold}",
        f"judged_verdicts: {n_kappa}",
        f"unparseable:     {inputs.n_unparseable}   (excluded from κ)",
        f"errors:          {inputs.n_error}   (excluded from κ)",
        f"n_for_kappa:     {n_kappa}",
    ]


def _judge_report_kappa(result: CohenKappaResult) -> list[str]:
    if not result.defined:
        return [
            "",
            "[agreement: judge vs human]",
            "cohen_kappa:     undefined (degenerate one-class marginals; p_e == 1)",
            f"p_observed:      {result.p_observed:.4f}",
            f"p_expected:      {result.p_expected:.4f}",
        ]
    boot = ""
    if result.n_boot_effective < result.n_boot:
        boot = (
            f"   (n_boot_effective {result.n_boot_effective}/{result.n_boot} -- "
            f"thin/biased CI pool)"
        )
    return [
        "",
        "[agreement: judge vs human]",
        f"cohen_kappa:     {result.kappa:.4f}",
        f"95% CI:          [{result.ci_low:.4f}, {result.ci_high:.4f}]{boot}",
        f"p_observed:      {result.p_observed:.4f}",
        f"p_expected:      {result.p_expected:.4f}",
    ]


def _judge_report_confusion(inputs: KappaInputs) -> list[str]:
    a, b, c, d = judge_kappa_confusion(inputs.human_labels, inputs.judge_labels)
    w_total = a + b
    nw_total = c + d
    w_agree = f"{a}/{w_total}" if w_total else "n/a"
    nw_agree = f"{d}/{nw_total}" if nw_total else "n/a"
    return [
        "",
        "[confusion matrix]  rows = HUMAN, cols = JUDGE",
        "                       judge WASTEFUL   judge NOT-WASTEFUL",
        f"  human WASTEFUL              {a:>3}              {b:>3}",
        f"  human NOT-WASTEFUL         {c:>3}              {d:>3}",
        "",
        "[per-label agreement]",
        f"  WASTEFUL:     judge agreed on {w_agree} human-WASTEFUL items",
        f"  NOT-WASTEFUL: judge agreed on {nw_agree} human-NOT-WASTEFUL items",
    ]


def _judge_report_interpretation(result: CohenKappaResult, n_kappa: int) -> list[str]:
    lines = ["", "[interpretation]"]
    if result.defined and result.kappa < _KAPPA_ADVISORY_FLOOR:
        lines.append(
            f"  !! κ = {result.kappa:.2f} < {_KAPPA_ADVISORY_FLOOR} -> JUDGE IS "
            f"ADVISORY-ONLY (protocol §7 tripwire)."
        )
        lines.append(
            "     A free gpt-oss:20b is not yet a trustworthy diff judge; rewrite the "
            "rubric, target κ >= 0.6."
        )
    elif result.defined:
        lines.append(
            f"  κ = {result.kappa:.2f} >= {_KAPPA_ADVISORY_FLOOR}: agreement clears the "
            f"advisory floor (target κ >= 0.6)."
        )
    lines.append(
        f"  CAVEAT: N is small ({n_kappa}). The 95% CI is WIDE -- read the interval, "
        f"not the point estimate."
    )
    lines.append(
        "  CAVEAT: this κ is a SINGLE-DRAW SNAPSHOT -- gpt-oss:20b via Ollama flips "
        "labels run-to-run even at temp 0, so it is not reproducible to the digit."
    )
    return lines


# --------------------------------------------------------------------------- CLI


def _judge_run_parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="clinescope.judge_run",
        description=(
            "Run the LLM judge over a diff_minimality gold set and report Cohen's κ "
            "vs the human labels (opt-in; the default clinescope CLI stays keyless)."
        ),
    )
    parser.add_argument(
        "--gold", type=Path, default=Path("gold/diff_minimality.gold.jsonl")
    )
    parser.add_argument(
        "--cache", type=Path, default=Path("gold/diff_minimality.judge.jsonl")
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--model", default="gpt-oss:20b")
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument(
        "--report",
        action="store_true",
        help="after writing the cache, print the κ report",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="skip the model run; report κ from the existing cache",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _judge_run_parse_args(argv)
    if not args.report_only:
        result = judge_run_over_gold(
            args.gold,
            repo_root=args.repo_root,
            model_id=args.model,
            base_url=args.base_url,
            now_iso=judge_run_now_iso(),
        )
        judge_run_write_cache(result, args.cache)
        print(
            f"judged {result.n_attempted} items "
            f"({result.n_verdicts} verdicts, {result.n_unparseable} unparseable, "
            f"{result.n_error} error) -> {args.cache}"
        )
    if args.report or args.report_only:
        inputs = judge_kappa_load_pairs(args.gold, args.cache, repo_root=args.repo_root)
        print(judge_kappa_report(inputs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
