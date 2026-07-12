"""Multi-draw judge stability -- how much a single-draw kappa can be trusted.

:mod:`clinescope.judge_run` computes ONE Cohen's kappa from ONE judge draw over the
gold set. But the judge (``gpt-oss:20b`` via Ollama) flips labels run-to-run even at
temperature 0 (GPU/KV-cache nondeterminism a fixed seed does not suppress) -- so that
single kappa is a SNAPSHOT, and the honest question is: *how much does it move across
draws?* This module answers that by judging the gold set ``K`` times and reporting the
DISTRIBUTION, turning the "single-draw" caveat from prose into a measured spread.

Two complementary views over the same ``K`` draws:

* **Human-vs-judge Cohen's kappa per draw** -- one kappa per draw (each draw is a full
  judge pass vs the fixed human labels), summarised as mean / min / max / spread. This
  is the direct "how unstable is the headline kappa?" number.
* **Judge self-consistency via Fleiss' kappa** -- treat the ``K`` draws as ``K`` raters
  and measure how much the judge agrees WITH ITSELF across draws
  (:func:`clinescope.agreement_multi.fleiss_kappa`). Low self-consistency is itself a
  finding: a judge that cannot reproduce its own verdict cannot be a stable gate signal.

**Deliberate decisions:**

* Reuses :func:`clinescope.judge_run.judge_run_over_gold` for each draw (no re-implemented
  judging) and :func:`clinescope.agreement.cohen_kappa` /
  :func:`clinescope.agreement_multi.fleiss_kappa` for the stats (no re-implemented math).
* Split run/report like ``judge_run``: :func:`judge_multidraw_run` makes the ``K*N`` model
  calls and returns a plain data structure; :func:`judge_multidraw_write_cache` /
  :func:`judge_multidraw_load_cache` persist it (LF-only JSONL, one row per draw x item);
  :func:`judge_multidraw_report` is pure and recomputable from the cache with NO model.
* Only ``outcome == "verdict"`` ratings enter the stats. A draw where an item was
  unparseable/errored makes that item's rater column ragged, so per-draw Cohen's kappa
  uses each draw's own verdict subset (aligned to the humans that HAVE a verdict that
  draw), and Fleiss' self-consistency uses only items with a full ``K`` verdicts (a
  ragged Fleiss design is undefined) -- both drops are COUNTED and surfaced, never
  silently defaulted.
* dependencies=[] preserved: stdlib + the existing zero-dep stats.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from clinescope.agreement import cohen_kappa
from clinescope.agreement_multi import fleiss_kappa
from clinescope.gold import gold_load_resolved
from clinescope.judge_run import (
    JudgeCacheRow,
    judge_run_now_iso,
    judge_run_over_gold,
)

_MULTIDRAW_SCHEMA_VERSION = 1
_DIMENSION = "diff_minimality"
_KAPPA_ADVISORY_FLOOR = 0.5


@dataclass(frozen=True, slots=True)
class MultiDrawResult:
    """Every judge verdict across ``K`` draws x ``N`` gold items (before caching).

    ``draws`` is ``K`` tuples, each the per-item :class:`~clinescope.judge_run.JudgeCacheRow`
    for one full judge pass in gold file order. ``human_labels`` is the fixed human gold
    label per item (``None`` for an unlabeled item), aligned to the same order.
    """

    draws: tuple[tuple[JudgeCacheRow, ...], ...]
    human_labels: tuple[str | None, ...]
    item_ids: tuple[str, ...]
    model_id: str
    n_draws: int
    n_items: int


def judge_multidraw_run(
    gold_path: str | Path,
    *,
    repo_root: Path,
    model_id: str,
    base_url: str,
    n_draws: int,
    now_iso: str,
) -> MultiDrawResult:
    """Judge the whole gold set ``n_draws`` times; collect every verdict.

    Makes ``n_draws * len(gold)`` model calls. ``now_iso`` is passed in (never stamped
    inside) so the run stays testable / deterministic in wiring tests.
    """
    if n_draws < 2:
        raise ValueError(f"multi-draw needs at least two draws, got {n_draws}")
    resolved = gold_load_resolved(gold_path, repo_root=repo_root)
    item_ids = tuple(r.item.item_id for r in resolved)
    human_labels = tuple(r.item.human_label for r in resolved)
    draws = tuple(
        judge_run_over_gold(
            gold_path,
            repo_root=repo_root,
            model_id=model_id,
            base_url=base_url,
            now_iso=now_iso,
        ).rows
        for _ in range(n_draws)
    )
    return MultiDrawResult(
        draws=draws,
        human_labels=human_labels,
        item_ids=item_ids,
        model_id=model_id,
        n_draws=n_draws,
        n_items=len(resolved),
    )


# ------------------------------------------------------------------- cache I/O


def judge_multidraw_write_cache(
    result: MultiDrawResult, cache_path: str | Path
) -> None:
    """Write one JSONL row per (draw, item), LF-only (mirrors judge_run's cache writer)."""
    lines: list[str] = []
    for draw_index, rows in enumerate(result.draws):
        for row in rows:
            lines.append(
                json.dumps(
                    {
                        "schema_version": _MULTIDRAW_SCHEMA_VERSION,
                        "dimension": _DIMENSION,
                        "draw": draw_index,
                        "item_id": row.item_id,
                        "outcome": row.outcome,
                        "judge_label": row.judge_label,
                        "model_id": row.model_id,
                        "patch_sha256": row.patch_sha256,
                        "judged_at": row.judged_at,
                    },
                    ensure_ascii=False,
                )
            )
    body = "\n".join(lines) + "\n" if lines else ""
    Path(cache_path).write_bytes(body.encode("utf-8"))


@dataclass(frozen=True, slots=True)
class _CachedRating:
    draw: int
    item_id: str
    outcome: str
    judge_label: str | None


def judge_multidraw_load_cache(
    cache_path: str | Path,
) -> tuple[_CachedRating, ...]:
    """Parse the multi-draw cache into rating rows (fail loud on a bad line)."""
    try:
        text = Path(cache_path).read_text(encoding="utf-8")
    except FileNotFoundError as err:
        raise ValueError(
            f"no multi-draw cache at {cache_path}; run "
            f"`python -m clinescope.judge_multidraw` first"
        ) from err
    ratings: list[_CachedRating] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        ratings.append(_multidraw_parse_line(line, line_number))
    return tuple(ratings)


def _multidraw_parse_line(line: str, line_number: int) -> _CachedRating:
    try:
        raw = json.loads(line)
    except json.JSONDecodeError as err:
        raise ValueError(
            f"multi-draw cache line {line_number}: not valid JSON ({err})"
        ) from err
    if not isinstance(raw, dict):
        raise ValueError(f"multi-draw cache line {line_number}: expected a JSON object")
    draw = raw.get("draw")
    item_id = raw.get("item_id")
    outcome = raw.get("outcome")
    label = raw.get("judge_label")
    if not isinstance(draw, int) or isinstance(draw, bool):
        raise ValueError(f"multi-draw cache line {line_number}: draw must be an int")
    if not isinstance(item_id, str):
        raise ValueError(f"multi-draw cache line {line_number}: item_id must be a str")
    if outcome not in ("verdict", "unparseable", "error"):
        raise ValueError(
            f"multi-draw cache line {line_number}: outcome must be "
            f"verdict/unparseable/error"
        )
    if outcome == "verdict" and label not in ("WASTEFUL", "NOT-WASTEFUL"):
        raise ValueError(
            f"multi-draw cache line {line_number}: a verdict row needs a "
            f"WASTEFUL/NOT-WASTEFUL judge_label"
        )
    return _CachedRating(
        draw=draw,
        item_id=item_id,
        outcome=outcome,
        judge_label=label if isinstance(label, str) else None,
    )


# ------------------------------------------------------------------- reporting


@dataclass(frozen=True, slots=True)
class MultiDrawStats:
    """The computed stability numbers (pure; recomputable from the cache, no model)."""

    n_draws: int
    n_items: int
    per_draw_cohen_kappa: tuple[float, ...]
    cohen_kappa_mean: float
    cohen_kappa_min: float
    cohen_kappa_max: float
    self_consistency_fleiss_kappa: float
    self_consistency_defined: bool
    n_items_full_verdicts: int
    n_ratings_dropped: int


def judge_multidraw_stats(
    ratings: tuple[_CachedRating, ...],
    human_labels: dict[str, str | None],
) -> MultiDrawStats:
    """Compute per-draw Cohen's kappa + Fleiss' self-consistency from cached ratings."""
    draws = sorted({r.draw for r in ratings})
    by_draw: dict[int, dict[str, _CachedRating]] = {d: {} for d in draws}
    for r in ratings:
        by_draw[r.draw][r.item_id] = r

    per_draw_kappa = _multidraw_per_draw_cohen(by_draw, draws, human_labels)
    fleiss_kappa_value, fleiss_defined, n_full, n_dropped = _multidraw_self_consistency(
        by_draw, draws, human_labels
    )
    n_items = len({r.item_id for r in ratings})
    return MultiDrawStats(
        n_draws=len(draws),
        n_items=n_items,
        per_draw_cohen_kappa=tuple(per_draw_kappa),
        cohen_kappa_mean=sum(per_draw_kappa) / len(per_draw_kappa)
        if per_draw_kappa
        else float("nan"),
        cohen_kappa_min=min(per_draw_kappa) if per_draw_kappa else float("nan"),
        cohen_kappa_max=max(per_draw_kappa) if per_draw_kappa else float("nan"),
        self_consistency_fleiss_kappa=fleiss_kappa_value,
        self_consistency_defined=fleiss_defined,
        n_items_full_verdicts=n_full,
        n_ratings_dropped=n_dropped,
    )


def _multidraw_per_draw_cohen(
    by_draw: dict[int, dict[str, _CachedRating]],
    draws: list[int],
    human_labels: dict[str, str | None],
) -> list[float]:
    """One human-vs-judge Cohen's kappa per draw (verdict-only, labeled-only items)."""
    per_draw: list[float] = []
    for draw in draws:
        human: list[str] = []
        judge: list[str] = []
        for item_id, rating in by_draw[draw].items():
            gold = human_labels.get(item_id)
            if gold is None or rating.outcome != "verdict":
                continue
            assert rating.judge_label is not None
            human.append(gold)
            judge.append(rating.judge_label)
        if len(human) >= 1:
            per_draw.append(cohen_kappa(human, judge).kappa)
    return per_draw


def _multidraw_self_consistency(
    by_draw: dict[int, dict[str, _CachedRating]],
    draws: list[int],
    human_labels: dict[str, str | None],
) -> tuple[float, bool, int, int]:
    """Fleiss' kappa over items that got a verdict in EVERY draw (rectangular design).

    Returns ``(kappa, defined, n_items_full, n_ratings_dropped)``. An item missing a
    verdict in any draw is dropped from the Fleiss design (it would make the design
    ragged); the count of dropped ratings is surfaced.
    """
    item_ids = sorted({item_id for d in by_draw.values() for item_id in d})
    rows: list[list[str]] = []
    n_dropped = 0
    for item_id in item_ids:
        verdicts: list[str] = []
        for draw in draws:
            rating = by_draw[draw].get(item_id)
            if rating is not None and rating.outcome == "verdict":
                assert rating.judge_label is not None
                verdicts.append(rating.judge_label)
        if len(verdicts) == len(draws):
            rows.append(verdicts)
        else:
            n_dropped += len(verdicts)
    # Self-consistency is only defined for >= 2 draws (Fleiss needs >= 2 raters). A
    # single-draw cache has nothing to be self-consistent WITH, so report it undefined
    # rather than crash -- the stats function must survive any cache the CLI feeds it.
    if len(draws) < 2 or len(rows) < 1:
        return float("nan"), False, len(rows), n_dropped
    result = fleiss_kappa(rows)
    return result.kappa, result.defined, len(rows), n_dropped


def judge_multidraw_report(stats: MultiDrawStats, model_id: str) -> str:
    """Format the stability report (pure; no I/O)."""
    lines = [
        f"=== clinescope multi-draw judge stability ({_DIMENSION}) ===",
        f"model_id:        {model_id}",
        f"draws:           {stats.n_draws}",
        f"items:           {stats.n_items}",
        "",
        "[human-vs-judge Cohen's kappa, per draw]",
        f"  per_draw:      {_multidraw_fmt_list(stats.per_draw_cohen_kappa)}",
        f"  mean:          {stats.cohen_kappa_mean:.4f}",
        f"  min / max:     {stats.cohen_kappa_min:.4f} / {stats.cohen_kappa_max:.4f}",
        f"  spread:        {stats.cohen_kappa_max - stats.cohen_kappa_min:.4f}",
        "",
        "[judge self-consistency across draws, Fleiss' kappa]",
    ]
    if stats.self_consistency_defined:
        lines.append(f"  fleiss_kappa:  {stats.self_consistency_fleiss_kappa:.4f}")
    else:
        lines.append("  fleiss_kappa:  undefined (one-class ratings across all draws)")
    lines.append(
        f"  over items with a verdict in all {stats.n_draws} draws: "
        f"{stats.n_items_full_verdicts}"
    )
    if stats.n_ratings_dropped:
        lines.append(
            f"  ({stats.n_ratings_dropped} ratings dropped: item lacked a verdict in "
            f"some draw)"
        )
    lines.append("")
    lines.append("[interpretation]")
    spread = stats.cohen_kappa_max - stats.cohen_kappa_min
    lines.append(
        f"  the headline single-draw kappa moves by up to {spread:.4f} across "
        f"{stats.n_draws} draws --"
    )
    lines.append(
        "  a single number is a snapshot; report the range, not one draw. "
        f"(advisory floor {_KAPPA_ADVISORY_FLOOR}.)"
    )
    return "\n".join(lines)


def _multidraw_fmt_list(values: tuple[float, ...]) -> str:
    return "[" + ", ".join(f"{v:.4f}" for v in values) + "]"


# --------------------------------------------------------------------------- CLI


def _judge_multidraw_force_utf8_stdout() -> None:
    """UTF-8 stdout/stderr so the kappa report never crashes on a cp1252 console."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def _judge_multidraw_parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="clinescope.judge_multidraw",
        description=(
            "Judge a diff_minimality gold set K times and report how much the "
            "human-vs-judge Cohen's kappa moves across draws, plus the judge's Fleiss' "
            "self-consistency (opt-in; the default clinescope CLI stays keyless)."
        ),
    )
    # None defaults resolved in main() against the bundled data root (works from a pip
    # install); an explicit --gold/--cache/--repo-root always wins.
    parser.add_argument("--gold", type=Path, default=None)
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--model", default="gpt-oss:20b")
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument("--draws", type=int, default=5)
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="skip the model run; report stability from the existing cache",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _judge_multidraw_force_utf8_stdout()
    args = _judge_multidraw_parse_args(argv)
    from clinescope._datafiles import DataFilesNotFound, datafiles_path, datafiles_root

    try:
        repo_root = args.repo_root if args.repo_root is not None else datafiles_root()
        gold = (
            args.gold
            if args.gold is not None
            else datafiles_path("gold", "diff_minimality.gold.jsonl")
        )
        cache = (
            args.cache
            if args.cache is not None
            else datafiles_path("gold", "diff_minimality.multidraw.jsonl")
        )
    except DataFilesNotFound as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    resolved = gold_load_resolved(gold, repo_root=repo_root)
    human_labels = {r.item.item_id: r.item.human_label for r in resolved}
    model_id = args.model
    if not args.report_only:
        result = judge_multidraw_run(
            gold,
            repo_root=repo_root,
            model_id=args.model,
            base_url=args.base_url,
            n_draws=args.draws,
            now_iso=judge_run_now_iso(),
        )
        judge_multidraw_write_cache(result, cache)
        model_id = result.model_id
        print(f"judged {result.n_items} items x {result.n_draws} draws -> {cache}")
    try:
        ratings = judge_multidraw_load_cache(cache)
    except ValueError as err:
        # e.g. --report-only before any run: a clean actionable message, not a traceback.
        print(f"error: {err}", file=sys.stderr)
        return 2
    stats = judge_multidraw_stats(ratings, human_labels)
    print(judge_multidraw_report(stats, model_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
