"""Tests for the BLIND gold-labeling harness (κ-arc segment 3).

The harness lets the USER hand-label the gold set blind to the deterministic score,
the judge, and the authored intent -- the whole point of the κ arc (a label produced
by the machine, or by a human who saw the score, is judge-vs-machine theater). These
tests pin the two safety-critical properties:

1. **Blind render** -- the text shown to the labeler contains the patch and the item
   id and nothing that could leak the proxy verdict or the authored kind: no
   ``diff_minimality`` score, no WASTEFUL/NOT-WASTEFUL hint, and no ``notes`` (which
   carry the authoring rationale + kind).
2. **Honest writer** -- writing a label sets exactly ``label`` / ``labeler`` /
   ``labeled_at`` / ``patch_sha256`` on the target item, leaves every OTHER line
   byte-identical, and the file re-loads via ``gold_load_resolved`` with the human
   label populated. The pinned sha256 matches the documented lifted-patch preimage.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from clinescope.diff_coherence import (
    diff_coherence_read_patch_text,
    diff_coherence_select_apply_patch,
)
from clinescope.gold import (
    GoldSchemaError,
    gold_load_items,
    gold_load_resolved,
    gold_resolve_item,
)
from clinescope.label_gold import (
    label_gold_next_unlabeled,
    label_gold_render_item,
    label_gold_run_cli,
    label_gold_write_label,
)
from clinescope.world_a import load_trace

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLD_JSONL = REPO_ROOT / "gold" / "diff_minimality.gold.jsonl"

_A_HARDCASE_TRACE = "examples/gold/dm-hardcase-01-py-retype-timeout-pair.json"
_A_BLIND_REWRITE_TRACE = "examples/gold/dm-hardcase-13-blind-retype-normalize-fn.json"


def _write_gold(tmp_path: Path, lines: list[dict]) -> Path:
    p = tmp_path / "g.gold.jsonl"
    p.write_text("\n".join(json.dumps(o) for o in lines) + "\n", encoding="utf-8")
    return p


def _item(item_id: str, trace: str, *, label: str | None = None) -> dict:
    return {
        "schema_version": 1,
        "item_id": item_id,
        "dimension": "diff_minimality",
        "source": {"trace": trace},
        "label": label,
        "labeler": None,
        "labeled_at": None,
        "notes": "SECRET AUTHORING RATIONALE kind 5 blind rewrite WASTEFUL",
        "patch_sha256": None,
    }


# --------------------------------------------------------------------------- render


def test_render_shows_item_id_and_patch_text() -> None:
    resolved = gold_load_resolved(GOLD_JSONL, repo_root=REPO_ROOT)
    r = next(x for x in resolved if x.item.trace_path == _A_HARDCASE_TRACE)
    rendered = label_gold_render_item(r)
    assert r.item.item_id in rendered
    # The lifted patch text appears verbatim (the labeler reads the real patch).
    patch_text = diff_coherence_read_patch_text(r.scored_call)
    assert patch_text is not None
    assert "*** Begin Patch" in rendered
    assert "connect=30.0" in rendered  # a real line from this case's patch


def test_render_is_blind_to_proxy_and_intent() -> None:
    """The render leaks NOTHING that could bias a human labeler.

    The blindness check applies to the harness's OWN framing (the lines it adds around
    the patch), NOT to the patch body -- the patch text is exactly what the labeler
    must read and may legitimately contain any code (e.g. a function named
    ``normalize_scores``). We assert (a) the framing carries no proxy/verdict/intent
    vocabulary, and (b) the patch portion is the verbatim lifted patch with nothing
    injected.
    """
    resolved = gold_load_resolved(GOLD_JSONL, repo_root=REPO_ROOT)
    for r in resolved:
        rendered = label_gold_render_item(r)
        patch_text = diff_coherence_read_patch_text(r.scored_call)
        assert patch_text is not None
        # Split the framing (everything before the verbatim patch) from the patch body.
        assert patch_text in rendered, (
            f"{r.item.item_id}: patch text not shown verbatim"
        )
        framing = rendered.split(patch_text)[0].lower()
        # The framing (the harness's OWN lines, patch body excluded) carries no proxy
        # score / verdict / authored-intent vocabulary -- checked in isolation with no
        # patch-body bypass, so a genuine framing leak can never hide behind the patch.
        for leak in ("wasteful", "minimality", "score", "blind", "kind"):
            assert leak not in framing, f"{r.item.item_id}: framing leaks {leak!r}"
        # The authored notes (kind + rationale) never appear.
        if r.item.notes:
            assert r.item.notes not in rendered, f"{r.item.item_id}: render leaks notes"


def test_render_surfaces_call_count_when_multiple() -> None:
    """When a trace has >1 apply_patch, the labeler is told they label the FIRST."""
    # The apply-recovery trace has two apply_patch calls (a fail + a recovery).
    resolved = gold_resolve_item(
        gold_load_items(
            _tmp_single(_A_RECOVERY_ITEM),
            repo_root=REPO_ROOT,
        )[0],
        repo_root=REPO_ROOT,
    )
    assert resolved.apply_patch_call_count > 1
    rendered = label_gold_render_item(resolved)
    assert "first" in rendered.lower()
    assert str(resolved.apply_patch_call_count) in rendered


_A_RECOVERY_ITEM = {
    "schema_version": 1,
    "item_id": "rec-1",
    "dimension": "diff_minimality",
    "source": {"trace": "examples/apply-recovery-trace.json"},
    "label": None,
    "labeler": None,
    "labeled_at": None,
    "notes": "",
    "patch_sha256": None,
}


def _tmp_single(item: dict) -> Path:
    import tempfile

    fh = tempfile.NamedTemporaryFile(
        "w", suffix=".gold.jsonl", delete=False, encoding="utf-8"
    )
    fh.write(json.dumps(item) + "\n")
    fh.close()
    return Path(fh.name)


# --------------------------------------------------------------- next-unlabeled


def test_next_unlabeled_returns_first_unlabeled(tmp_path: Path) -> None:
    p = _write_gold(
        tmp_path,
        [
            _item("a", _A_HARDCASE_TRACE, label="WASTEFUL"),
            _item("b", _A_BLIND_REWRITE_TRACE),
            _item("c", _A_HARDCASE_TRACE),
        ],
    )
    items = gold_load_items(p, repo_root=REPO_ROOT)
    nxt = label_gold_next_unlabeled(items)
    assert nxt is not None and nxt.item_id == "b"


def test_next_unlabeled_none_when_all_labeled(tmp_path: Path) -> None:
    p = _write_gold(
        tmp_path,
        [
            _item("a", _A_HARDCASE_TRACE, label="WASTEFUL"),
            _item("b", _A_BLIND_REWRITE_TRACE, label="NOT-WASTEFUL"),
        ],
    )
    items = gold_load_items(p, repo_root=REPO_ROOT)
    assert label_gold_next_unlabeled(items) is None


# ------------------------------------------------------------------- writer


def test_write_label_sets_provenance_and_reloads(tmp_path: Path) -> None:
    p = _write_gold(
        tmp_path,
        [
            _item("a", _A_HARDCASE_TRACE),
            _item("b", _A_BLIND_REWRITE_TRACE),
        ],
    )
    # Compute the expected pinned sha for item "a".
    trace = load_trace(REPO_ROOT / _A_HARDCASE_TRACE)
    call, _ = diff_coherence_select_apply_patch(trace)
    assert call is not None
    text = diff_coherence_read_patch_text(call)
    assert text is not None
    expected_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()

    label_gold_write_label(
        p,
        "a",
        label="WASTEFUL",
        labeler="minh",
        labeled_at="2026-07-11T12:00:00Z",
        patch_sha256=expected_sha,
    )

    resolved = gold_load_resolved(p, repo_root=REPO_ROOT)
    by_id = {r.item.item_id: r for r in resolved}
    assert by_id["a"].item.human_label == "WASTEFUL"
    assert by_id["a"].item.labeler == "minh"
    assert by_id["a"].item.labeled_at == "2026-07-11T12:00:00Z"
    assert by_id["a"].item.patch_sha256 == expected_sha
    # The other item is untouched.
    assert by_id["b"].item.human_label is None


def test_write_label_leaves_other_lines_byte_identical(tmp_path: Path) -> None:
    p = _write_gold(
        tmp_path,
        [
            _item("a", _A_HARDCASE_TRACE),
            _item("b", _A_BLIND_REWRITE_TRACE),
            _item("c", _A_HARDCASE_TRACE),
        ],
    )
    # Compare at the BYTE level (splitlines() strips terminators and would hide a
    # whole-file CRLF->LF rewrite -- the exact defect this guards).
    before = p.read_bytes().split(b"\n")
    label_gold_write_label(
        p,
        "b",
        label="NOT-WASTEFUL",
        labeler="minh",
        labeled_at="2026-07-11T12:00:00Z",
        patch_sha256=None,
    )
    after = p.read_bytes().split(b"\n")
    assert len(before) == len(after)
    # Only line index 1 (item "b") changed; the other lines are BYTE-identical.
    assert before[0] == after[0]
    assert before[2] == after[2]
    assert before[1] != after[1]
    assert json.loads(after[1].decode("utf-8"))["label"] == "NOT-WASTEFUL"


def test_write_label_preserves_crlf_line_endings(tmp_path: Path) -> None:
    """A CRLF gold file stays CRLF on every platform (the committed contract is CRLF-
    in-tree on Windows); untouched lines keep their exact bytes, terminator included."""
    p = tmp_path / "crlf.gold.jsonl"
    records = [_item("a", _A_HARDCASE_TRACE), _item("b", _A_BLIND_REWRITE_TRACE)]
    # Write explicitly with CRLF terminators + a trailing CRLF.
    p.write_bytes(
        ("\r\n".join(json.dumps(r) for r in records) + "\r\n").encode("utf-8")
    )
    before = p.read_bytes()
    assert b"\r\n" in before and before.count(b"\r\n") == 2

    label_gold_write_label(
        p,
        "a",
        label="WASTEFUL",
        labeler="minh",
        labeled_at="2026-07-11T12:00:00Z",
        patch_sha256=None,
    )
    after = p.read_bytes()
    # Still CRLF, same terminator count, and item "b"'s line byte-identical.
    assert after.count(b"\r\n") == 2, "writer must not collapse CRLF to LF"
    assert b"\n" not in after.replace(b"\r\n", b""), "no bare LF introduced"
    before_b_line = [ln for ln in before.split(b"\r\n") if b'"item_id": "b"' in ln][0]
    after_b_line = [ln for ln in after.split(b"\r\n") if b'"item_id": "b"' in ln][0]
    assert before_b_line == after_b_line, "untouched line drifted at the byte level"


def test_write_label_rejects_bad_label(tmp_path: Path) -> None:
    p = _write_gold(tmp_path, [_item("a", _A_HARDCASE_TRACE)])
    with pytest.raises(ValueError):
        label_gold_write_label(
            p,
            "a",
            label="MAYBE",
            labeler="minh",
            labeled_at="2026-07-11T12:00:00Z",
            patch_sha256=None,
        )


def test_write_label_unknown_item_id_raises(tmp_path: Path) -> None:
    p = _write_gold(tmp_path, [_item("a", _A_HARDCASE_TRACE)])
    with pytest.raises(KeyError):
        label_gold_write_label(
            p,
            "nonexistent",
            label="WASTEFUL",
            labeler="minh",
            labeled_at="2026-07-11T12:00:00Z",
            patch_sha256=None,
        )


def test_written_file_still_passes_schema_gate(tmp_path: Path) -> None:
    """A relabeled file re-parses with no GoldSchemaError (the writer keeps it valid)."""
    p = _write_gold(tmp_path, [_item("a", _A_HARDCASE_TRACE)])
    label_gold_write_label(
        p,
        "a",
        label="WASTEFUL",
        labeler="minh",
        labeled_at="2026-07-11T12:00:00Z",
        patch_sha256=None,
    )
    # No raise:
    items = gold_load_items(p, repo_root=REPO_ROOT)
    assert items[0].human_label == "WASTEFUL"


def test_cli_end_to_end_labels_and_pins_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The interactive CLI labels each unlabeled item from scripted stdin, pins the
    LIFTED-patch sha, and resumes (the one exercise of the actual human-labeling path).
    """
    p = _write_gold(
        tmp_path,
        [_item("a", _A_HARDCASE_TRACE), _item("b", _A_BLIND_REWRITE_TRACE)],
    )
    # Scripted answers: WASTEFUL for the first item, NOT-WASTEFUL for the second.
    answers = iter(["w", "n"])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))

    labeled = label_gold_run_cli(p, repo_root=REPO_ROOT, labeler="tester")
    assert labeled == 2

    resolved = gold_load_resolved(p, repo_root=REPO_ROOT)
    by_id = {r.item.item_id: r for r in resolved}
    assert by_id["a"].item.human_label == "WASTEFUL"
    assert by_id["b"].item.human_label == "NOT-WASTEFUL"
    assert by_id["a"].item.labeler == "tester"
    # The CLI pins the sha of the LIFTED patch text (not the raw JSON line).
    trace = load_trace(REPO_ROOT / _A_HARDCASE_TRACE)
    call, _ = diff_coherence_select_apply_patch(trace)
    assert call is not None
    text = diff_coherence_read_patch_text(call)
    assert text is not None
    assert (
        by_id["a"].item.patch_sha256 == hashlib.sha256(text.encode("utf-8")).hexdigest()
    )


def test_cli_stops_on_blank_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blank input stops the loop mid-way (resumable); a second run finishes the rest."""
    p = _write_gold(
        tmp_path,
        [_item("a", _A_HARDCASE_TRACE), _item("b", _A_BLIND_REWRITE_TRACE)],
    )
    # First run: label "a", then blank -> stop before "b".
    first = iter(["w", ""])
    monkeypatch.setattr("builtins.input", lambda *_: next(first))
    assert label_gold_run_cli(p, repo_root=REPO_ROOT, labeler="tester") == 1
    items = gold_load_items(p, repo_root=REPO_ROOT)
    assert label_gold_next_unlabeled(items) is not None  # "b" still unlabeled

    # Second run resumes at "b".
    second = iter(["n"])
    monkeypatch.setattr("builtins.input", lambda *_: next(second))
    assert label_gold_run_cli(p, repo_root=REPO_ROOT, labeler="tester") == 1
    items = gold_load_items(p, repo_root=REPO_ROOT)
    assert label_gold_next_unlabeled(items) is None  # all labeled now


def test_harness_module_does_not_import_proxy_or_judge() -> None:
    """Structural blindness: the harness must not import diff_minimality or judge.

    If it imported the proxy or the judge, a future edit could accidentally render a
    score. Enforce the boundary by parsing the module's IMPORTS with ast (a docstring
    may name the modules to explain the boundary; an actual import is the violation) --
    a Gate-4-provable property.
    """
    import ast

    src = (REPO_ROOT / "src" / "clinescope" / "label_gold.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
    forbidden = {"clinescope.diff_minimality", "clinescope.judge"}
    leaked = forbidden & imported_modules
    assert not leaked, f"harness imports a proxy/judge module: {leaked}"
    # Sanity: it does import the loader + the patch reader.
    assert "clinescope.gold" in imported_modules
    assert "clinescope.diff_coherence" in imported_modules


def test_gold_schema_error_is_importable() -> None:
    # Guard: the schema error the harness relies on for validation exists.
    assert issubclass(GoldSchemaError, Exception)
