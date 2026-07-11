"""Blind gold-labeling harness for judge validation (κ-arc segment 3).

A human labeler answers one holistic question per gold item -- *"is this patch
WASTEFUL?"* -- BLIND to the deterministic ``diff_minimality`` score, to the judge,
and to the authored intent. Their labels + a judge's labels feed
:func:`clinescope.agreement.cohen_kappa` for the κ number (segment 4). If a label is
machine-generated, or a human sees the proxy score first, the κ measures the judge
against itself instead of against an independent human -- not validation. So this
module is a LABELING UI over the existing gold format, deliberately with NO access to
the proxy:

* It imports :mod:`clinescope.gold` (to load + resolve items) and
  :mod:`clinescope.diff_coherence` (to lift the patch text the labeler reads). It does
  **NOT** import :mod:`clinescope.diff_minimality` (the proxy) or
  :mod:`clinescope.judge` -- a structural guarantee that a render can never leak a
  score (a Gate-4-provable property; see ``tests/test_label_gold.py``).
* :func:`label_gold_render_item` shows ONLY the item id, the first apply_patch's patch
  text, and (when a trace has more than one apply_patch) which call is being labeled.
  It never shows the score, the WASTEFUL/NOT-WASTEFUL vocabulary, or the authored
  ``notes`` (which carry the kind + rationale).
* :func:`label_gold_write_label` rewrites exactly the target item's line -- setting
  ``label`` / ``labeler`` / ``labeled_at`` / ``patch_sha256`` -- and leaves every other
  line byte-identical, so an interrupted labeling session is resumable and a relabel
  never disturbs the rest of the corpus.

The one truly-human step (the label) is the user's, always: this module supplies the
UI + the writer, never a label value of its own.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from clinescope.diff_coherence import diff_coherence_read_patch_text
from clinescope.gold import (
    GOLD_LABELS,
    GoldItem,
    ResolvedGoldItem,
    gold_load_items,
    gold_resolve_item,
)

# The prompt string used for both the CLI and the in-chat labeling loop -- the one
# holistic question, matching gold/README.md's protocol. Kept here so the question a
# human answers is defined in exactly one place.
LABEL_PROMPT = (
    "Is this patch WASTEFUL -- does it rewrite more than the change needs "
    "(e.g. retyping whole blocks it could have edited in place)?"
)


def label_gold_render_item(resolved: ResolvedGoldItem) -> str:
    """Render one gold item for a BLIND human labeler: id + patch text only.

    Deliberately shows nothing that could bias the call: no ``diff_minimality`` score,
    no WASTEFUL/NOT-WASTEFUL hint, no authored ``notes``. When the trace has more than
    one apply_patch call, states that the FIRST is the one being labeled (matching the
    scorer's scope) so the labeler never silently grades a different call.

    Args:
        resolved: A resolved gold item (its trace loaded, first apply_patch selected).

    Returns:
        A multi-line string safe to display to the labeler.
    """
    patch_text = diff_coherence_read_patch_text(resolved.scored_call)
    if patch_text is None:  # pragma: no cover - gold_resolve_item already rejects this
        raise ValueError(
            f"gold item {resolved.item.item_id!r}: first apply_patch has no readable "
            f"patch text (should have been rejected at resolve time)"
        )
    lines = [f"item: {resolved.item.item_id}"]
    if resolved.apply_patch_call_count > 1:
        lines.append(
            f"(labeling the FIRST of {resolved.apply_patch_call_count} apply_patch "
            f"calls in this trace)"
        )
    lines.append("patch:")
    lines.append(patch_text)
    return "\n".join(lines)


def label_gold_next_unlabeled(items: tuple[GoldItem, ...]) -> GoldItem | None:
    """Return the first item with no human label yet, or None if all are labeled.

    Lets a labeling session resume: already-labeled items are skipped, so re-running
    the harness on a partially-labeled file picks up where it left off.
    """
    for item in items:
        if item.human_label is None:
            return item
    return None


def label_gold_write_label(
    jsonl_path: str | Path,
    item_id: str,
    *,
    label: str,
    labeler: str,
    labeled_at: str,
    patch_sha256: str | None,
) -> None:
    """Write a human label + provenance into the one matching item's JSONL line.

    Rewrites ONLY the target item's line (``label`` / ``labeler`` / ``labeled_at`` /
    ``patch_sha256``), preserving field order and leaving every other line byte for
    byte identical, so a relabel is surgical and an interrupted session is resumable.

    Newline handling is byte-preserving and platform-independent: the file's own line
    terminator (CRLF or LF) is detected and reused, so untouched lines keep their exact
    bytes on Windows AND on Linux/CI. (A ``read_text``/``"\n".join``/``write_text``
    round-trip would silently rewrite a CRLF file to LF off-Windows, drifting every
    line -- the gold set is a versioned contract, so that is a real defect.) The final
    newline is preserved only if the file already ended with one.

    ``labeled_at`` is passed IN (never stamped inside) so the writer stays deterministic
    and testable; the CLI supplies :func:`label_gold_now_iso`.

    Args:
        jsonl_path: The gold JSONL file to update in place.
        item_id: The ``item_id`` of the item to label.
        label: ``"WASTEFUL"`` or ``"NOT-WASTEFUL"`` -- the human's own call.
        labeler: Who labeled it (provenance).
        labeled_at: When, ISO 8601 (provenance).
        patch_sha256: The pinned lifted-patch digest, or None to leave unpinned.

    Raises:
        ValueError: ``label`` is not a legal gold label.
        KeyError: No item with ``item_id`` is present in the file.
    """
    if label not in GOLD_LABELS:
        raise ValueError(f"label must be one of {sorted(GOLD_LABELS)}, got {label!r}")
    path = Path(jsonl_path)
    raw = path.read_bytes()
    newline = b"\r\n" if b"\r\n" in raw else b"\n"
    trailing_newline = raw.endswith(newline)
    text = raw.decode("utf-8")
    # Split on the file's own terminator so every UNTOUCHED segment stays byte-identical.
    segments = text.split(newline.decode("ascii"))
    if trailing_newline and segments and segments[-1] == "":
        segments = segments[:-1]  # drop the empty tail from a trailing terminator
    updated: list[str] = []
    found = False
    for segment in segments:
        if not segment.strip():
            updated.append(segment)
            continue
        record = json.loads(segment)
        if record.get("item_id") == item_id:
            record["label"] = label
            record["labeler"] = labeler
            record["labeled_at"] = labeled_at
            record["patch_sha256"] = patch_sha256
            updated.append(json.dumps(record))
            found = True
        else:
            updated.append(segment)
    if not found:
        raise KeyError(f"no gold item with item_id {item_id!r} in {path}")
    body = newline.decode("ascii").join(updated)
    if trailing_newline:
        body += newline.decode("ascii")
    path.write_bytes(body.encode("utf-8"))


def label_gold_now_iso() -> str:
    """Current UTC time as an ISO-8601 string (the CLI's ``labeled_at`` source)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def label_gold_run_cli(jsonl_path: str | Path, *, repo_root: Path, labeler: str) -> int:
    """Interactively label every unlabeled item in a gold file (the CLI entry point).

    Presents each unlabeled item blind, reads a WASTEFUL / NOT-WASTEFUL answer from
    stdin, and writes it with provenance. Blank input / EOF stops (resumable).

    Returns the number of items labeled this run.
    """
    import hashlib

    labeled = 0
    while True:
        items = gold_load_items(jsonl_path, repo_root=repo_root)
        nxt = label_gold_next_unlabeled(items)
        if nxt is None:
            print("All items labeled.")
            break
        resolved = gold_resolve_item(nxt, repo_root=repo_root)
        print("\n" + "=" * 70)
        print(label_gold_render_item(resolved))
        print("=" * 70)
        print(LABEL_PROMPT)
        answer = _label_gold_read_answer()
        if answer is None:
            print(f"Stopped. {labeled} item(s) labeled this run.")
            break
        text = diff_coherence_read_patch_text(resolved.scored_call)
        sha = (
            hashlib.sha256(text.encode("utf-8")).hexdigest()
            if text is not None
            else None
        )
        label_gold_write_label(
            jsonl_path,
            nxt.item_id,
            label=answer,
            labeler=labeler,
            labeled_at=label_gold_now_iso(),
            patch_sha256=sha,
        )
        labeled += 1
        print(f"Recorded {answer} for {nxt.item_id}.")
    return labeled


def _label_gold_read_answer() -> str | None:
    """Read one WASTEFUL / NOT-WASTEFUL answer from stdin; None to stop.

    Accepts ``w`` / ``n`` shortcuts and the full words (case-insensitive).
    """
    while True:
        try:
            raw = input("  [w]ASTEFUL / [n]OT-WASTEFUL / blank to stop > ").strip()
        except EOFError:
            return None
        if not raw:
            return None
        lowered = raw.lower()
        if lowered in ("w", "wasteful"):
            return "WASTEFUL"
        if lowered in ("n", "not-wasteful", "not wasteful"):
            return "NOT-WASTEFUL"
        print("  please answer w, n, or blank to stop")


def main() -> int:
    """CLI: ``python -m clinescope.label_gold <gold.jsonl> [--labeler NAME]``."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="clinescope.label_gold",
        description="Blindly hand-label a diff_minimality gold set for judge validation.",
    )
    parser.add_argument("jsonl_path", type=Path, help="path to the .gold.jsonl file")
    parser.add_argument(
        "--labeler", default="user", help="labeler name recorded as provenance"
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="repo root that item source.trace pointers resolve against",
    )
    args = parser.parse_args()
    label_gold_run_cli(args.jsonl_path, repo_root=args.repo_root, labeler=args.labeler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
