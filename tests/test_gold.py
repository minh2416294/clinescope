"""Tests for the gold-set loader + judge seam (κ-arc segment 2).

Written test-first (TDD). Every fail-loud path is a raised, tested error -- a bad
pointer must never silently return a wrong item (surface hidden failures). The
load-bearing test is ``test_resolves_first_of_n_apply_patch``: it pins that the
loader scores the FIRST apply_patch (the failed ``call-2`` in the 2-call recovery
trace) and surfaces ``apply_patch_call_count == 2`` -- the exact silent-mislabel
trap the trace-only (never id-keyed) pointer design was chosen to avoid.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from clinescope.gold import (
    GOLD_LABELS,
    GoldItem,
    GoldMalformedPatchError,
    GoldNoApplyPatchError,
    GoldPatchDriftError,
    GoldSchemaError,
    GoldTraceMissingError,
    ResolvedGoldItem,
    gold_load_items,
    gold_load_resolved,
    gold_resolve_item,
)
from clinescope.judge import JudgeLabel, judge_diff_minimality
from clinescope.world_a import Trace, load_trace

# The repo root of THIS worktree (tests/ -> repo root), so repo-relative
# ``source.trace`` pointers in a gold item resolve against the checked-out repo.
_REPO_ROOT = Path(__file__).resolve().parent.parent

# Verified real values (see the Day-15 plan): the first apply_patch of each trace
# by scan order + its patch-text sha256 (sha256 of diff_coherence_read_patch_text).
_APPLY_PATCH_TRACE = "examples/apply-patch-trace.json"
_APPLY_PATCH_SHA = "fe656a02be2be9fc541bca813c1c840a4ea88b32c57e0408e0ece48e6a2f0433"
_RECOVERY_TRACE = "examples/apply-recovery-trace.json"
_RECOVERY_FIRST_SHA = "884848c828664ad2e6cfee752c17bf5d888764bf96e65364c917ae79effed0c3"


def _item(**overrides: object) -> dict[str, object]:
    """A well-formed gold-item dict; override fields per test."""
    base: dict[str, object] = {
        "schema_version": 1,
        "item_id": "dm-test",
        "dimension": "diff_minimality",
        "source": {"trace": _APPLY_PATCH_TRACE},
        "label": None,
        "labeler": None,
        "labeled_at": None,
        "notes": "",
        "patch_sha256": None,
    }
    base.update(overrides)
    return base


def _write_jsonl(tmp_path: Path, *items: dict[str, object]) -> Path:
    path = tmp_path / "gold.jsonl"
    path.write_text(
        "\n".join(json.dumps(item) for item in items) + "\n", encoding="utf-8"
    )
    return path


def _write_raw(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "gold.jsonl"
    path.write_text(text, encoding="utf-8")
    return path


# ---- parsing: gold_load_items -------------------------------------------------


def test_load_items_parses_a_well_formed_line(tmp_path: Path) -> None:
    path = _write_jsonl(tmp_path, _item(item_id="dm-0001"))
    items = gold_load_items(path, repo_root=_REPO_ROOT)
    assert len(items) == 1
    item = items[0]
    assert isinstance(item, GoldItem)
    assert item.item_id == "dm-0001"
    assert item.dimension == "diff_minimality"
    assert item.trace_path == _APPLY_PATCH_TRACE
    assert item.human_label is None  # unlabeled seed tolerated


def test_load_items_tolerates_blank_and_whitespace_lines(tmp_path: Path) -> None:
    # A trailing newline / blank separators are legal, not a parse error.
    text = json.dumps(_item(item_id="a")) + "\n\n   \n" + json.dumps(_item(item_id="b"))
    path = _write_raw(tmp_path, text + "\n")
    items = gold_load_items(path, repo_root=_REPO_ROOT)
    assert [i.item_id for i in items] == ["a", "b"]


def test_load_items_accepts_valid_labels(tmp_path: Path) -> None:
    path = _write_jsonl(
        tmp_path,
        _item(item_id="w", label="WASTEFUL"),
        _item(item_id="n", label="NOT-WASTEFUL"),
    )
    items = gold_load_items(path, repo_root=_REPO_ROOT)
    assert [i.human_label for i in items] == ["WASTEFUL", "NOT-WASTEFUL"]


def test_malformed_jsonl_line_raises_schema_error_naming_the_line(
    tmp_path: Path,
) -> None:
    text = json.dumps(_item(item_id="ok")) + "\n{not valid json\n"
    path = _write_raw(tmp_path, text)
    with pytest.raises(GoldSchemaError) as exc:
        gold_load_items(path, repo_root=_REPO_ROOT)
    # Fails loud AND names the offending 1-based line (line 2), never skips it.
    assert "line 2" in str(exc.value)


def test_bad_label_value_raises_schema_error(tmp_path: Path) -> None:
    path = _write_jsonl(tmp_path, _item(label="MAYBE"))
    with pytest.raises(GoldSchemaError):
        gold_load_items(path, repo_root=_REPO_ROOT)


def test_non_object_json_line_raises_schema_error(tmp_path: Path) -> None:
    path = _write_raw(tmp_path, "[1, 2, 3]\n")
    with pytest.raises(GoldSchemaError):
        gold_load_items(path, repo_root=_REPO_ROOT)


def test_missing_required_field_raises_schema_error(tmp_path: Path) -> None:
    bad = _item()
    del bad["item_id"]
    path = _write_jsonl(tmp_path, bad)
    with pytest.raises(GoldSchemaError):
        gold_load_items(path, repo_root=_REPO_ROOT)


def test_bad_source_shape_raises_schema_error(tmp_path: Path) -> None:
    # source must be {"trace": <str>}; a string / missing key is a schema error.
    path = _write_jsonl(tmp_path, _item(source="examples/apply-patch-trace.json"))
    with pytest.raises(GoldSchemaError):
        gold_load_items(path, repo_root=_REPO_ROOT)


# ---- resolution: gold_resolve_item -------------------------------------------


def test_resolves_single_apply_patch_trace(tmp_path: Path) -> None:
    (item,) = gold_load_items(
        _write_jsonl(tmp_path, _item(source={"trace": _APPLY_PATCH_TRACE})),
        repo_root=_REPO_ROOT,
    )
    resolved = gold_resolve_item(item, repo_root=_REPO_ROOT)
    assert isinstance(resolved, ResolvedGoldItem)
    assert isinstance(resolved.trace, Trace)
    assert resolved.scored_call.id == "call-2"
    assert resolved.apply_patch_call_count == 1


def test_resolves_first_of_n_apply_patch(tmp_path: Path) -> None:
    # THE LANDMINE: the recovery trace has TWO apply_patch calls -- call-2 (failed
    # first) and call-3 (the recovery). The loader must score the FIRST (call-2)
    # and surface count==2, matching diff_coherence_select_apply_patch, so a human
    # can't eyeball the successful call-3 and silently mislabel. This assertion is
    # false for any "first==only" or id-keyed design -> the test can actually fail.
    (item,) = gold_load_items(
        _write_jsonl(tmp_path, _item(source={"trace": _RECOVERY_TRACE})),
        repo_root=_REPO_ROOT,
    )
    resolved = gold_resolve_item(item, repo_root=_REPO_ROOT)
    assert resolved.scored_call.id == "call-2"
    assert resolved.apply_patch_call_count == 2


def test_resolved_scored_call_equals_diff_coherence_selection(tmp_path: Path) -> None:
    # Cross-check the loader against the scorer's own selection on the same trace.
    from clinescope.diff_coherence import diff_coherence_select_apply_patch

    (item,) = gold_load_items(
        _write_jsonl(tmp_path, _item(source={"trace": _RECOVERY_TRACE})),
        repo_root=_REPO_ROOT,
    )
    resolved = gold_resolve_item(item, repo_root=_REPO_ROOT)
    trace = load_trace(_REPO_ROOT / _RECOVERY_TRACE)
    expected_call, expected_count = diff_coherence_select_apply_patch(trace)
    assert expected_call is not None
    assert resolved.scored_call.id == expected_call.id
    assert resolved.apply_patch_call_count == expected_count


def test_missing_trace_raises_trace_missing_error(tmp_path: Path) -> None:
    (item,) = gold_load_items(
        _write_jsonl(tmp_path, _item(source={"trace": "examples/does-not-exist.json"})),
        repo_root=_REPO_ROOT,
    )
    with pytest.raises(GoldTraceMissingError):
        gold_resolve_item(item, repo_root=_REPO_ROOT)


def test_trace_without_apply_patch_raises_no_apply_patch_error(
    tmp_path: Path,
) -> None:
    # A read_files-only trace (no committed example is apply_patch-free, so author
    # one here) must fail loud: it has no first apply_patch to label.
    no_patch_trace = {
        "version": 1,
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call-1",
                        "name": "read_files",
                        "input": {"path": "/tmp/x.py"},
                    }
                ],
            }
        ],
    }
    trace_path = tmp_path / "no-patch-trace.json"
    trace_path.write_text(json.dumps(no_patch_trace), encoding="utf-8")
    item = GoldItem(
        item_id="np",
        dimension="diff_minimality",
        trace_path=trace_path.name,
        human_label=None,
        labeler=None,
        labeled_at=None,
        notes="",
        patch_sha256=None,
    )
    with pytest.raises(GoldNoApplyPatchError):
        gold_resolve_item(item, repo_root=tmp_path)


def test_mis_shaped_apply_patch_raises_malformed_patch_error(tmp_path: Path) -> None:
    # A first apply_patch whose input carries no str under key "input" (the fictional
    # {"diff": ...} shape) is hard-zeroed by the scorer; the loader must reject it too
    # rather than hand a labeler / the judge a call with no patch text to read. Keeps
    # the loader's rejection semantics aligned with score_diff_coherence's.
    bad_shape_trace = {
        "version": 1,
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call-1",
                        "name": "apply_patch",
                        "input": {"diff": "@@ -1 +1 @@\n-a\n+b"},
                    }
                ],
            }
        ],
    }
    trace_path = tmp_path / "bad-shape-trace.json"
    trace_path.write_text(json.dumps(bad_shape_trace), encoding="utf-8")
    item = GoldItem(
        item_id="bad",
        dimension="diff_minimality",
        trace_path=trace_path.name,
        human_label=None,
        labeler=None,
        labeled_at=None,
        notes="",
        patch_sha256=None,
    )
    with pytest.raises(GoldMalformedPatchError):
        gold_resolve_item(item, repo_root=tmp_path)


def test_unsupported_schema_version_raises_schema_error(tmp_path: Path) -> None:
    # schema_version exists to make a field-set change LOUD; a v2 file must not be
    # parsed silently as v1 (mirrors world_a's version gate).
    path = _write_jsonl(tmp_path, _item(schema_version=2))
    with pytest.raises(GoldSchemaError) as exc:
        gold_load_items(path, repo_root=_REPO_ROOT)
    assert "schema_version" in str(exc.value)


def test_missing_schema_version_raises_schema_error(tmp_path: Path) -> None:
    bad = _item()
    del bad["schema_version"]
    path = _write_jsonl(tmp_path, bad)
    with pytest.raises(GoldSchemaError):
        gold_load_items(path, repo_root=_REPO_ROOT)


def test_boolean_schema_version_raises_schema_error(tmp_path: Path) -> None:
    # JSON `true` is a Python bool; `True == 1` would fail OPEN under a value-only
    # check and silently admit the item as v1. The type check must reject it.
    path = _write_jsonl(tmp_path, _item(schema_version=True))
    with pytest.raises(GoldSchemaError):
        gold_load_items(path, repo_root=_REPO_ROOT)


def test_float_schema_version_raises_schema_error(tmp_path: Path) -> None:
    # JSON `1.0` is a Python float; `1.0 == 1` would likewise fail OPEN.
    path = _write_jsonl(tmp_path, _item(schema_version=1.0))
    with pytest.raises(GoldSchemaError):
        gold_load_items(path, repo_root=_REPO_ROOT)


def test_malformed_patch_sha256_digest_raises_schema_error(tmp_path: Path) -> None:
    # A pin that is not a 64-char lowercase hex digest is rejected at parse time with
    # a clear message, not silently treated as a value that always drift-mismatches.
    path = _write_jsonl(tmp_path, _item(patch_sha256="deadbeef"))
    with pytest.raises(GoldSchemaError) as exc:
        gold_load_items(path, repo_root=_REPO_ROOT)
    assert "sha256" in str(exc.value)


# ---- patch_sha256 drift tripwire ---------------------------------------------


def test_patch_sha256_match_resolves_clean(tmp_path: Path) -> None:
    (item,) = gold_load_items(
        _write_jsonl(
            tmp_path,
            _item(source={"trace": _RECOVERY_TRACE}, patch_sha256=_RECOVERY_FIRST_SHA),
        ),
        repo_root=_REPO_ROOT,
    )
    resolved = gold_resolve_item(item, repo_root=_REPO_ROOT)
    assert resolved.scored_call.id == "call-2"


def test_patch_sha256_drift_raises_patch_drift_error(tmp_path: Path) -> None:
    (item,) = gold_load_items(
        _write_jsonl(
            tmp_path,
            _item(source={"trace": _RECOVERY_TRACE}, patch_sha256="0" * 64),
        ),
        repo_root=_REPO_ROOT,
    )
    with pytest.raises(GoldPatchDriftError):
        gold_resolve_item(item, repo_root=_REPO_ROOT)


def test_patch_sha256_preimage_is_the_lifted_patch_text(tmp_path: Path) -> None:
    # Pin the preimage so a future labeler hashes the right thing: it is
    # sha256(diff_coherence_read_patch_text(first_call)), NOT the raw JSON line.
    from clinescope.diff_coherence import (
        diff_coherence_read_patch_text,
        diff_coherence_select_apply_patch,
    )

    trace = load_trace(_REPO_ROOT / _APPLY_PATCH_TRACE)
    call, _ = diff_coherence_select_apply_patch(trace)
    assert call is not None
    text = diff_coherence_read_patch_text(call)
    assert text is not None
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == _APPLY_PATCH_SHA


# ---- gold_load_resolved (parse + resolve all) --------------------------------


def test_load_resolved_parses_and_resolves_every_item(tmp_path: Path) -> None:
    path = _write_jsonl(
        tmp_path,
        _item(item_id="a", source={"trace": _APPLY_PATCH_TRACE}),
        _item(item_id="b", source={"trace": _RECOVERY_TRACE}),
    )
    resolved = gold_load_resolved(path, repo_root=_REPO_ROOT)
    assert [r.item.item_id for r in resolved] == ["a", "b"]
    assert [r.apply_patch_call_count for r in resolved] == [1, 2]


# ---- the committed seed file loads -------------------------------------------


def test_committed_gold_file_loads_and_resolves() -> None:
    # After S3 the committed gold set is HUMAN-labeled (each label the user's own, a
    # legal GOLD_LABELS value); before S3 it shipped unlabeled. Either way it must load,
    # every item must resolve to a real first apply_patch, and any present label must be
    # legal. (The pre-S3 "seed is unlabeled" assertion is now stale -- superseded by the
    # labeled corpus S3 produces; the harness/loader guarantee is load+resolve+valid.)
    seed = _REPO_ROOT / "gold" / "diff_minimality.gold.jsonl"
    items = gold_load_items(seed, repo_root=_REPO_ROOT)
    assert len(items) >= 1
    for item in items:
        assert item.human_label is None or item.human_label in GOLD_LABELS
        resolved = gold_resolve_item(item, repo_root=_REPO_ROOT)
        assert resolved.apply_patch_call_count >= 1


# ---- the judge seam (now a live LLM call; segment 4) --------------------------


def test_judge_diff_minimality_is_wired_to_a_real_http_call(tmp_path: Path) -> None:
    # Segment 4 filled the stub with a real Ollama HTTP call. Pointed at a dead port,
    # the judge fails loud with a JudgeUnreachableError (a JudgeError) -- proving the
    # seam now reaches the network rather than raising NotImplementedError. (The real
    # live-model behavior is exercised by the skipif-gated tests in test_judge_live.py.)
    from clinescope.judge import JudgeUnreachableError

    trace = load_trace(_REPO_ROOT / _APPLY_PATCH_TRACE)
    with pytest.raises(JudgeUnreachableError):
        judge_diff_minimality(trace, base_url="http://127.0.0.1:1", timeout=1.0)


def test_judge_label_is_a_frozen_value_object() -> None:
    label = JudgeLabel(
        label="WASTEFUL", rationale="blind whole-block rewrite", model_id="stub"
    )
    assert label.label == "WASTEFUL"
    assert label.model_id == "stub"
    with pytest.raises(AttributeError):
        label.label = "NOT-WASTEFUL"  # type: ignore[misc]  # frozen
