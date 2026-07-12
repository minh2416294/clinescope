"""Grammar-validity + divergence-design pins for the authored hard-case gold corpus.

κ-arc segment 3 authors 24 balanced hard-case ``diff_minimality`` gold traces under
``examples/gold/`` so a human's holistic "is this patch WASTEFUL?" call can plausibly
DIVERGE from the deterministic blind-rewrite proxy. These tests pin two properties of
the AUTHORED corpus (not the human labels, which are the user's own):

1. **Grammar-validity** — every authored trace loads via the World-A loader and scores
   under ALL FOUR existing scorers without raising, and each apply_patch is coherent
   (``diff_coherence == 1.0``) so a labeler always has a clean patch to read.
2. **Divergence design** — the proxy verdict of each case lands in the bucket the
   corpus needs: the blind-spot + tight cases score ``diff_minimality == 1.0`` (the
   surface where a human WASTEFUL call diverges from the proxy) and the caught blind
   rewrites score ``< 1.0``. This is the whole reason κ over this set is not degenerate;
   pinning it here means the divergence is machine-verified, not asserted in prose.

The tests read only the committed ``examples/gold/*.json`` traces + the gold JSONL;
they never read a human label and never write one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinescope.apply_recovery import score_apply_recovery
from clinescope.diff_coherence import score_diff_coherence
from clinescope.diff_minimality import score_diff_minimality
from clinescope.gold import gold_load_items, gold_load_resolved
from clinescope.tool_selection import score_tool_selection
from clinescope.world_a import load_trace

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLD_DIR = REPO_ROOT / "examples" / "gold"
GOLD_JSONL = REPO_ROOT / "gold" / "diff_minimality.gold.jsonl"

# The four caught blind-rewrites (kind 5): the ONLY authored cases whose first
# apply_patch the proxy flags (score < 1.0). Every other authored case is a proxy
# blind-spot (kinds 1-4) or a genuinely tight edit (kind 6), all scoring exactly 1.0.
# This split is the divergence surface; pin both sides.
_CAUGHT_BLIND_REWRITE_SLUGS = frozenset(
    {
        "dm-hardcase-13-blind-retype-normalize-fn",
        "dm-hardcase-14-blind-retype-js-retry-config",
        "dm-hardcase-15-blind-retype-go-limits-mixed",
        "dm-hardcase-16-blind-retype-yaml-ci-matrix",
        # P3b additions (dm-hc-41..44): four more caught blind rewrites.
        "dm-hardcase-41-blind-retype-py-config-block",
        "dm-hardcase-42-blind-retype-go-struct-literal",
        "dm-hardcase-43-blind-retype-yaml-service",
        "dm-hardcase-44-blind-retype-js-handlers",
    }
)

_EXPECTED_HARDCASE_COUNT = 48
_EXPECTED_TOTAL_GOLD_ITEMS = 50  # 2 seed + 48 hard cases


def _hardcase_trace_paths() -> list[Path]:
    return sorted(GOLD_DIR.glob("dm-hardcase-*.json"))


def test_authored_hardcase_count() -> None:
    paths = _hardcase_trace_paths()
    assert len(paths) == _EXPECTED_HARDCASE_COUNT, (
        f"expected {_EXPECTED_HARDCASE_COUNT} authored hard-case traces, "
        f"found {len(paths)}"
    )


@pytest.mark.parametrize("trace_path", _hardcase_trace_paths(), ids=lambda p: p.stem)
def test_hardcase_loads_and_scores_under_all_scorers(trace_path: Path) -> None:
    """Every authored trace loads + scores under all four scorers without error."""
    trace = load_trace(trace_path)
    # All four run without raising; each returns a value object.
    coherence = score_diff_coherence(trace)
    minimality = score_diff_minimality(trace)
    recovery = score_apply_recovery(trace)
    selection = score_tool_selection(trace, expected={"apply_patch"})

    # The patch is coherent (a labeler must have a clean patch to read).
    assert coherence.score == 1.0, (
        f"{trace_path.name}: diff_coherence {coherence.score} != 1.0 "
        f"(violations: {coherence.violations})"
    )
    # Minimality is applicable (there is an apply_patch to shape-check).
    assert minimality.applicable, f"{trace_path.name}: minimality not applicable"
    # The other two run cleanly; tool_selection sees apply_patch.
    assert selection.score == 1.0
    assert recovery is not None


@pytest.mark.parametrize("trace_path", _hardcase_trace_paths(), ids=lambda p: p.stem)
def test_hardcase_proxy_verdict_matches_divergence_design(trace_path: Path) -> None:
    """The proxy lands each case in its designed bucket (the divergence surface).

    Caught blind-rewrites score < 1.0; every other case scores exactly 1.0. A human
    may still call a 1.0-scored case WASTEFUL -- that divergence is what κ measures.
    """
    trace = load_trace(trace_path)
    score = score_diff_minimality(trace).score
    assert score is not None
    if trace_path.stem in _CAUGHT_BLIND_REWRITE_SLUGS:
        assert score < 1.0, (
            f"{trace_path.name}: designed as a CAUGHT blind rewrite but proxy "
            f"scored {score} (expected < 1.0)"
        )
    else:
        assert score == 1.0, (
            f"{trace_path.name}: designed as a proxy blind-spot / tight case but "
            f"proxy scored {score} (expected exactly 1.0)"
        )


def test_divergence_surface_has_both_margins() -> None:
    """The corpus has cases on BOTH sides of the proxy so κ is not degenerate by design.

    (This checks the AUTHORED proxy split, not the human labels -- a lopsided HUMAN
    labeling can still yield a degenerate κ, which is a real S4 finding, not a bug.)
    """
    proxy_one = 0
    proxy_below_one = 0
    for trace_path in _hardcase_trace_paths():
        score = score_diff_minimality(load_trace(trace_path)).score
        if score == 1.0:
            proxy_one += 1
        else:
            proxy_below_one += 1
    assert proxy_one >= 1 and proxy_below_one >= 1, (
        f"divergence surface lopsided: {proxy_one} proxy-1.0 vs "
        f"{proxy_below_one} proxy-<1.0"
    )
    # Guard the specific designed split so an accidental corpus edit is caught.
    assert proxy_below_one == len(_CAUGHT_BLIND_REWRITE_SLUGS)


def test_gold_jsonl_loads_all_items_and_labels_are_valid() -> None:
    """The full gold set (2 seed + 24 hard cases) parses + resolves; every present label
    is a legal, human-provided value.

    Before S3 the corpus shipped UNLABELED (a Claude-authored label would be theater);
    after S3 the user has hand-labeled it. Either way, every item must resolve to its
    first apply_patch, and any non-null label must be a legal ``GOLD_LABELS`` value that
    carries a ``labeler`` (provenance) -- so a machine-authored label with no labeler
    could never masquerade as a human label.
    """
    from clinescope.gold import GOLD_LABELS

    items = gold_load_items(GOLD_JSONL, repo_root=REPO_ROOT)
    assert len(items) == _EXPECTED_TOTAL_GOLD_ITEMS
    resolved = gold_load_resolved(GOLD_JSONL, repo_root=REPO_ROOT)
    assert len(resolved) == _EXPECTED_TOTAL_GOLD_ITEMS
    for r in resolved:
        assert r.scored_call.name == "apply_patch"
        if r.item.human_label is not None:
            assert r.item.human_label in GOLD_LABELS, (
                f"{r.item.item_id}: illegal label {r.item.human_label!r}"
            )
            assert r.item.labeler, (
                f"{r.item.item_id}: labeled but has no labeler (provenance missing)"
            )


def test_every_hardcase_item_pins_patch_sha256() -> None:
    """Each authored hard-case item pins ``patch_sha256`` (drift tripwire on the patch).

    A pinned digest means a committed trace edit cannot silently invalidate a future
    human label (``gold_resolve_item`` raises ``GoldPatchDriftError`` on drift).
    """
    pinned = 0
    for line in GOLD_JSONL.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item["item_id"].startswith("dm-hc-"):
            assert item["patch_sha256"] is not None, (
                f"{item['item_id']}: hard-case item must pin patch_sha256"
            )
            assert len(item["patch_sha256"]) == 64
            pinned += 1
    # Fail loud if the id scheme drifts and this guard silently stops covering cases.
    assert pinned == _EXPECTED_HARDCASE_COUNT, (
        f"expected {_EXPECTED_HARDCASE_COUNT} pinned hard-case items, found {pinned} "
        f"(did the dm-hc- id scheme change?)"
    )
