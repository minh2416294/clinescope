"""Pure wiring tests for the judge + κ runner (NO live model call).

This is how the wiring is verified -- by tests over the machinery (verdict parsing,
request-body shape, the byte-preserving cache writer, the confusion matrix, and the κ
report) -- never by an agent's claim about what the model "would" answer. The live
model behavior is exercised separately, skipif-gated, in ``test_judge_live.py``.

Every test here runs with no Ollama: the request body is pure, parsing is pure, the
cache writer is filesystem-only, and the κ report is computed from an authored cache.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from clinescope.judge import (
    JudgeTruncatedError,
    JudgeUnparseableError,
    JudgeUnreachableError,
    JudgeVerdict,
    judge_build_request_body,
    judge_diff_minimality,
    judge_extract_response_text,
    judge_parse_verdict,
    judge_user_prompt,
)
from clinescope.judge_run import (
    JudgeCacheRow,
    JudgeRunResult,
    judge_kappa_confusion,
    judge_kappa_load_pairs,
    judge_kappa_report,
    judge_run_write_cache,
)
from clinescope.world_a import load_trace

_REPO_ROOT = Path(__file__).resolve().parent.parent
_APPLY_PATCH_TRACE = "examples/apply-patch-trace.json"


# ---- verdict parsing (robust, explicit-unparseable, no silent default) --------


@pytest.mark.parametrize(
    "answer,expected",
    [
        ("VERDICT: WASTEFUL", "WASTEFUL"),
        ("VERDICT: NOT-WASTEFUL", "NOT-WASTEFUL"),
        ("some reasoning\nVERDICT: WASTEFUL", "WASTEFUL"),
        ("some reasoning\nverdict: not-wasteful", "NOT-WASTEFUL"),
        ("  VERDICT:   WASTEFUL  ", "WASTEFUL"),
    ],
)
def test_parse_verdict_reads_the_sentinel(answer: str, expected: JudgeVerdict) -> None:
    assert judge_parse_verdict(answer) == expected


def test_parse_verdict_takes_the_last_sentinel_bottom_up() -> None:
    # The model may restate the word mid-reasoning; the final VERDICT line wins.
    answer = (
        "The patch could be seen as WASTEFUL at first glance.\n"
        "But it edits in place.\n"
        "VERDICT: NOT-WASTEFUL"
    )
    assert judge_parse_verdict(answer) == "NOT-WASTEFUL"


def test_parse_verdict_not_wasteful_is_not_shadowed_by_wasteful_substring() -> None:
    # NOT-WASTEFUL contains "WASTEFUL"; the alternation must not misread it as WASTEFUL.
    assert judge_parse_verdict("VERDICT: NOT-WASTEFUL") == "NOT-WASTEFUL"


def test_parse_verdict_raises_on_no_sentinel_never_defaults() -> None:
    # A rambly answer with no VERDICT line is an EXPLICIT error, never a silent class.
    with pytest.raises(JudgeUnparseableError):
        judge_parse_verdict("I think this patch is probably fine, honestly.")


def test_parse_verdict_raises_on_mid_line_verdict_word() -> None:
    # "the VERDICT: is unclear" is not an anchored sentinel line -> unparseable.
    with pytest.raises(JudgeUnparseableError):
        judge_parse_verdict("the VERDICT: is unclear to me")


# ---- request body (blind: patch text present, no label/score leak) ------------


def test_build_request_body_is_temp0_capped_and_nonstreaming() -> None:
    body = judge_build_request_body("*** Begin Patch\n*** End Patch", model_id="m")
    assert body["model"] == "m"
    assert body["stream"] is False
    options = body["options"]
    assert isinstance(options, dict)
    assert options["temperature"] == 0
    assert options["num_predict"] == 1024


def test_build_request_body_contains_the_patch_text_and_no_label() -> None:
    patch = "*** Begin Patch\n*** Update File: a.py\n@@\n-x\n+y\n*** End Patch"
    body = judge_build_request_body(patch, model_id="m")
    prompt = body["prompt"]
    assert isinstance(prompt, str)
    assert patch in prompt
    # Blindness: the judge prompt never carries a human label or a proxy score.
    system = body["system"]
    assert isinstance(system, str)
    haystack = (prompt + system).lower()
    assert "human_label" not in haystack
    assert "diff_minimality" not in haystack
    assert "score" not in prompt.lower()


def test_user_prompt_frames_only_the_patch_text() -> None:
    prompt = judge_user_prompt("PATCHBODY")
    assert "PATCHBODY" in prompt


# ---- response extraction (truncation is loud, not a half-parse) ---------------


def test_extract_response_text_returns_the_response_field() -> None:
    assert (
        judge_extract_response_text({"response": "hi", "done_reason": "stop"}) == "hi"
    )


def test_extract_response_text_raises_on_length_truncation() -> None:
    with pytest.raises(JudgeTruncatedError):
        judge_extract_response_text({"response": "half", "done_reason": "length"})


# ---- HTTP error mapping (dead endpoint -> unreachable, fail loud) -------------


def test_judge_diff_minimality_unreachable_endpoint_raises_loud() -> None:
    trace = load_trace(_REPO_ROOT / _APPLY_PATCH_TRACE)
    with pytest.raises(JudgeUnreachableError):
        judge_diff_minimality(trace, base_url="http://127.0.0.1:1", timeout=1.0)


# ---- confusion matrix ---------------------------------------------------------


def test_confusion_matrix_counts_the_four_cells() -> None:
    human = ("WASTEFUL", "WASTEFUL", "NOT-WASTEFUL", "NOT-WASTEFUL", "WASTEFUL")
    judge = ("WASTEFUL", "NOT-WASTEFUL", "WASTEFUL", "NOT-WASTEFUL", "WASTEFUL")
    # a: HW&JW=2, b: HW&JNW=1, c: HNW&JW=1, d: HNW&JNW=1
    assert judge_kappa_confusion(human, judge) == (2, 1, 1, 1)


# ---- the LF cache writer (byte-identical, LF, one object per line) ------------


def _row(item_id: str, outcome: str, label: str | None) -> JudgeCacheRow:
    return JudgeCacheRow(
        item_id=item_id,
        outcome=outcome,  # type: ignore[arg-type]  # test passes a literal string
        judge_label=label,
        rationale="r",
        model_id="gpt-oss:20b",
        patch_sha256="0" * 64,
        judged_at="2026-07-11T00:00:00+00:00",
    )


def test_cache_writer_emits_lf_only_one_object_per_line(tmp_path: Path) -> None:
    result = JudgeRunResult(
        rows=(_row("a", "verdict", "WASTEFUL"), _row("b", "unparseable", None)),
        model_id="gpt-oss:20b",
        n_attempted=2,
        n_verdicts=1,
        n_unparseable=1,
        n_error=0,
    )
    cache = tmp_path / "diff_minimality.judge.jsonl"
    judge_run_write_cache(result, cache)

    raw = cache.read_bytes()
    assert b"\r\n" not in raw  # LF only (matches .gitattributes)
    assert raw.endswith(b"\n")
    lines = raw.decode("utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["item_id"] == "a"
    assert first["outcome"] == "verdict"
    assert first["judge_label"] == "WASTEFUL"
    second = json.loads(lines[1])
    assert second["outcome"] == "unparseable"
    assert second["judge_label"] is None


# ---- κ report over an authored gold+cache pair (no model) ---------------------


def _write_gold(path: Path, rows: list[dict[str, object]]) -> None:
    body = "\n".join(json.dumps(r) for r in rows) + "\n"
    path.write_bytes(body.encode("utf-8"))


def _gold_item(item_id: str, trace: str, label: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "item_id": item_id,
        "dimension": "diff_minimality",
        "source": {"trace": trace},
        "label": label,
        "labeler": "minh",
        "labeled_at": "2026-07-11T00:00:00+00:00",
        "notes": "",
        "patch_sha256": None,
    }


def _cache_row(item_id: str, sha: str, label: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "item_id": item_id,
        "dimension": "diff_minimality",
        "outcome": "verdict",
        "judge_label": label,
        "rationale": "r",
        "model_id": "gpt-oss:20b",
        "patch_sha256": sha,
        "judged_at": "2026-07-11T00:00:00+00:00",
    }


def _sha_of_trace(trace_rel: str) -> str:
    import hashlib

    from clinescope.diff_coherence import (
        diff_coherence_read_patch_text,
        diff_coherence_select_apply_patch,
    )

    trace = load_trace(_REPO_ROOT / trace_rel)
    call, _ = diff_coherence_select_apply_patch(trace)
    assert call is not None
    text = diff_coherence_read_patch_text(call)
    assert text is not None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_kappa_report_perfect_agreement_over_authored_cache(tmp_path: Path) -> None:
    # Two gold items whose human labels the judge matches exactly -> κ report defined.
    # (This proves the join + report wiring, not a specific κ value.)
    traces = ["examples/apply-patch-trace.json", "examples/multi-op-trace.json"]
    gold = tmp_path / "g.jsonl"
    cache = tmp_path / "c.jsonl"
    _write_gold(
        gold,
        [
            _gold_item("x", traces[0], "NOT-WASTEFUL"),
            _gold_item("y", traces[1], "WASTEFUL"),
        ],
    )
    _write_gold(
        cache,
        [
            _cache_row("x", _sha_of_trace(traces[0]), "NOT-WASTEFUL"),
            _cache_row("y", _sha_of_trace(traces[1]), "WASTEFUL"),
        ],
    )
    inputs = judge_kappa_load_pairs(gold, cache, repo_root=_REPO_ROOT)
    assert inputs.human_labels == ("NOT-WASTEFUL", "WASTEFUL")
    assert inputs.judge_labels == ("NOT-WASTEFUL", "WASTEFUL")
    report = judge_kappa_report(inputs)
    assert "clinescope judge κ report" in report
    assert "cohen_kappa:" in report
    assert "confusion matrix" in report


def test_kappa_report_excludes_unparseable_from_kappa(tmp_path: Path) -> None:
    trace = "examples/apply-patch-trace.json"
    gold = tmp_path / "g.jsonl"
    cache = tmp_path / "c.jsonl"
    _write_gold(gold, [_gold_item("x", trace, "WASTEFUL")])
    unparseable = {
        "schema_version": 1,
        "item_id": "x",
        "dimension": "diff_minimality",
        "outcome": "unparseable",
        "judge_label": None,
        "rationale": "no verdict",
        "model_id": "gpt-oss:20b",
        "patch_sha256": _sha_of_trace(trace),
        "judged_at": "2026-07-11T00:00:00+00:00",
    }
    _write_gold(cache, [unparseable])
    inputs = judge_kappa_load_pairs(gold, cache, repo_root=_REPO_ROOT)
    assert inputs.human_labels == ()
    assert inputs.n_unparseable == 1
    report = judge_kappa_report(inputs)
    assert "unparseable:     1" in report
    assert "no verdicts to score" in report


def test_kappa_load_pairs_fails_loud_on_patch_drift(tmp_path: Path) -> None:
    trace = "examples/apply-patch-trace.json"
    gold = tmp_path / "g.jsonl"
    cache = tmp_path / "c.jsonl"
    _write_gold(gold, [_gold_item("x", trace, "WASTEFUL")])
    # A wrong (drifted) sha in the cache must be caught, not silently trusted.
    _write_gold(cache, [_cache_row("x", "0" * 64, "WASTEFUL")])
    from clinescope.judge import JudgeError

    with pytest.raises(JudgeError):
        judge_kappa_load_pairs(gold, cache, repo_root=_REPO_ROOT)


def test_kappa_load_pairs_rejects_a_duplicate_cache_item_id(tmp_path: Path) -> None:
    # A duplicated item_id in the cache would double-count / mislabel a κ pairing; the
    # loader rejects it loudly rather than last-write-wins collapsing it.
    trace = "examples/apply-patch-trace.json"
    gold = tmp_path / "g.jsonl"
    cache = tmp_path / "c.jsonl"
    _write_gold(gold, [_gold_item("x", trace, "WASTEFUL")])
    sha = _sha_of_trace(trace)
    _write_gold(
        cache, [_cache_row("x", sha, "WASTEFUL"), _cache_row("x", sha, "NOT-WASTEFUL")]
    )
    from clinescope.judge import JudgeError

    with pytest.raises(JudgeError):
        judge_kappa_load_pairs(gold, cache, repo_root=_REPO_ROOT)


def test_kappa_load_pairs_missing_cache_is_a_clean_error(tmp_path: Path) -> None:
    # --report-only before any run must give the actionable message, not a raw traceback.
    gold = tmp_path / "g.jsonl"
    _write_gold(gold, [_gold_item("x", "examples/apply-patch-trace.json", "WASTEFUL")])
    from clinescope.judge import JudgeError

    with pytest.raises(JudgeError, match="no judge cache"):
        judge_kappa_load_pairs(
            gold, tmp_path / "does-not-exist.jsonl", repo_root=_REPO_ROOT
        )


def test_kappa_report_tripwire_text_appears_below_floor() -> None:
    # An authored low-agreement KappaInputs prints the κ<0.5 advisory tripwire.
    from clinescope.judge_run import KappaInputs

    human = tuple(["WASTEFUL", "NOT-WASTEFUL"] * 8)  # 16 items, alternating
    judge = tuple(["NOT-WASTEFUL", "WASTEFUL"] * 8)  # maximal disagreement
    inputs = KappaInputs(
        human_labels=human,
        judge_labels=judge,
        model_id="gpt-oss:20b",
        n_gold=16,
        n_unparseable=0,
        n_error=0,
    )
    report = judge_kappa_report(inputs)
    assert "ADVISORY-ONLY" in report
    assert "protocol §7" in report


def test_report_only_does_not_crash_on_a_cp1252_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The κ report prints κ / → / § / ≥. On a Windows console stdout defaults to cp1252,
    # which cannot encode those -> UnicodeEncodeError mid-print. main() reconfigures the
    # stream to UTF-8 first; without that the exact README command crashes. Reproduce a
    # cp1252 console with a strict TextIOWrapper and assert the run survives + emits κ.
    from clinescope.judge_run import main

    raw = io.BytesIO()
    cp1252_stdout = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", cp1252_stdout)

    exit_code = main(
        [
            "--report-only",
            "--gold",
            str(_REPO_ROOT / "gold" / "diff_minimality.gold.jsonl"),
            "--cache",
            str(_REPO_ROOT / "gold" / "diff_minimality.judge.jsonl"),
            "--repo-root",
            str(_REPO_ROOT),
        ]
    )

    assert exit_code == 0
    cp1252_stdout.flush()
    printed = raw.getvalue().decode("utf-8")
    # The fix flipped the stream to UTF-8, so the κ glyph survives round-trip.
    assert "κ report" in printed
    assert "cohen_kappa:" in printed
