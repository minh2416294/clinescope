"""Pure wiring tests for the multi-draw judge-stability harness (NO live model call).

Every test authors cache ratings by hand and exercises the pure stats + cache round
trip -- never a real Ollama call. The live multi-draw path shares
``judge_run_over_gold`` (already live-tested skipif-gated in ``test_judge_live.py``),
so nothing here needs a model.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from clinescope.judge_multidraw import (
    _CachedRating,
    judge_multidraw_load_cache,
    judge_multidraw_report,
    judge_multidraw_stats,
    main,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _rating(
    draw: int, item_id: str, label: str | None, outcome: str = "verdict"
) -> _CachedRating:
    return _CachedRating(draw=draw, item_id=item_id, outcome=outcome, judge_label=label)


def test_stats_per_draw_cohen_kappa_moves_when_the_judge_flips() -> None:
    # 2 items, 2 draws. Humans: i1=WASTEFUL, i2=NOT-WASTEFUL. The judge agrees fully in
    # draw 0 (kappa 1.0) and flips both in draw 1 (kappa -1.0) -> a wide spread.
    humans = {"i1": "WASTEFUL", "i2": "NOT-WASTEFUL"}
    ratings = (
        _rating(0, "i1", "WASTEFUL"),
        _rating(0, "i2", "NOT-WASTEFUL"),
        _rating(1, "i1", "NOT-WASTEFUL"),
        _rating(1, "i2", "WASTEFUL"),
    )
    stats = judge_multidraw_stats(ratings, humans)
    assert stats.n_draws == 2
    assert stats.n_items == 2
    assert stats.cohen_kappa_max == 1.0
    assert stats.cohen_kappa_min == -1.0
    assert stats.cohen_kappa_max - stats.cohen_kappa_min == 2.0


def test_self_consistency_fleiss_is_perfect_when_the_judge_never_flips() -> None:
    # The judge gives the same verdicts in all 3 draws -> self-consistency kappa 1.0.
    humans = {"i1": "WASTEFUL", "i2": "NOT-WASTEFUL"}
    ratings = tuple(
        _rating(d, item, label)
        for d in range(3)
        for item, label in (("i1", "WASTEFUL"), ("i2", "NOT-WASTEFUL"))
    )
    stats = judge_multidraw_stats(ratings, humans)
    assert stats.self_consistency_defined
    assert stats.self_consistency_fleiss_kappa == 1.0
    assert stats.n_items_full_verdicts == 2


def test_an_item_missing_a_verdict_in_one_draw_is_dropped_from_fleiss_and_counted() -> (
    None
):
    humans = {"i1": "WASTEFUL", "i2": "WASTEFUL"}
    ratings = (
        _rating(0, "i1", "WASTEFUL"),
        _rating(0, "i2", "WASTEFUL"),
        _rating(1, "i1", "WASTEFUL"),
        _rating(1, "i2", None, outcome="unparseable"),  # no verdict this draw
    )
    stats = judge_multidraw_stats(ratings, humans)
    # i2 lacks a verdict in draw 1 -> dropped from the rectangular Fleiss design.
    assert stats.n_items_full_verdicts == 1
    assert stats.n_ratings_dropped == 1


def test_unlabeled_human_items_are_excluded_from_per_draw_cohen() -> None:
    # i3 has no human label -> it must not enter the human-vs-judge kappa. The two
    # labeled items (i1, i2) span both classes and the judge agrees on both -> kappa 1.0.
    humans: dict[str, str | None] = {
        "i1": "WASTEFUL",
        "i2": "NOT-WASTEFUL",
        "i3": None,
    }
    ratings = (
        _rating(0, "i1", "WASTEFUL"),
        _rating(0, "i2", "NOT-WASTEFUL"),
        _rating(0, "i3", "WASTEFUL"),  # unlabeled human -> excluded from the pairing
    )
    stats = judge_multidraw_stats(ratings, humans)
    # Only i1 + i2 are labeled pairs (both classes present, both agree) -> kappa 1.0;
    # i3 was dropped, so the kappa rests on 2 pairs, not 3.
    assert stats.per_draw_cohen_kappa == (1.0,)


def test_cache_round_trips_through_the_loader(tmp_path: Path) -> None:
    cache = tmp_path / "md.jsonl"
    body = "\n".join(
        [
            '{"schema_version": 1, "dimension": "diff_minimality", "draw": 0, '
            '"item_id": "i1", "outcome": "verdict", "judge_label": "WASTEFUL", '
            '"model_id": "gpt-oss:20b", "patch_sha256": "x", "judged_at": "t"}',
            '{"schema_version": 1, "dimension": "diff_minimality", "draw": 1, '
            '"item_id": "i1", "outcome": "unparseable", "judge_label": null, '
            '"model_id": "gpt-oss:20b", "patch_sha256": "x", "judged_at": "t"}',
        ]
    )
    cache.write_bytes((body + "\n").encode("utf-8"))
    ratings = judge_multidraw_load_cache(cache)
    assert len(ratings) == 2
    assert ratings[0].outcome == "verdict" and ratings[0].judge_label == "WASTEFUL"
    assert ratings[1].outcome == "unparseable" and ratings[1].judge_label is None


def test_load_cache_missing_file_is_a_clean_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no multi-draw cache"):
        judge_multidraw_load_cache(tmp_path / "nope.jsonl")


def test_load_cache_rejects_a_verdict_row_without_a_label(tmp_path: Path) -> None:
    cache = tmp_path / "bad.jsonl"
    cache.write_bytes(
        b'{"schema_version": 1, "dimension": "diff_minimality", "draw": 0, '
        b'"item_id": "i1", "outcome": "verdict", "judge_label": null, '
        b'"model_id": "m", "patch_sha256": "x", "judged_at": "t"}\n'
    )
    with pytest.raises(ValueError, match="verdict row needs"):
        judge_multidraw_load_cache(cache)


def test_report_names_the_spread_and_self_consistency() -> None:
    humans = {"i1": "WASTEFUL", "i2": "NOT-WASTEFUL"}
    ratings = (
        _rating(0, "i1", "WASTEFUL"),
        _rating(0, "i2", "NOT-WASTEFUL"),
        _rating(1, "i1", "NOT-WASTEFUL"),
        _rating(1, "i2", "NOT-WASTEFUL"),
    )
    report = judge_multidraw_report(
        judge_multidraw_stats(ratings, humans), "gpt-oss:20b"
    )
    assert "multi-draw judge stability" in report
    assert "per_draw:" in report
    assert "self-consistency" in report
    assert "spread:" in report


def test_report_only_reads_the_cache_with_no_model_call(tmp_path: Path) -> None:
    # Author a 2-draw cache for the two committed seed items, then --report-only:
    # it must load the gold labels + the cache and print a report, no Ollama.
    cache = tmp_path / "md.jsonl"
    rows = []
    for draw in range(2):
        for item_id in ("dm-0001", "dm-0002"):
            rows.append(
                '{"schema_version": 1, "dimension": "diff_minimality", "draw": '
                + str(draw)
                + ', "item_id": "'
                + item_id
                + '", "outcome": "verdict", "judge_label": "NOT-WASTEFUL", '
                '"model_id": "gpt-oss:20b", "patch_sha256": "x", "judged_at": "t"}'
            )
    cache.write_bytes(("\n".join(rows) + "\n").encode("utf-8"))

    captured = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    exit_code = main(
        [
            "--report-only",
            "--gold",
            str(_REPO_ROOT / "gold" / "diff_minimality.gold.jsonl"),
            "--cache",
            str(cache),
            "--repo-root",
            str(_REPO_ROOT),
        ]
    )
    assert exit_code == 0
    # (Also asserts the UTF-8 stdout reconfigure works: main() printed the kappa report
    # without a cp1252 crash on the process stdout.)
    assert captured is not None
