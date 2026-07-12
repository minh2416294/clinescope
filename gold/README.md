# Gold sets — human labels for judge validation

This directory holds the small **human-labeled** corpora that clinescope validates its
LLM judge against. For each labeled item a human answers one holistic question about a
patch, the judge answers the same question, and
[`clinescope.agreement.cohen_kappa`](../src/clinescope/agreement.py) reports their
chance-corrected agreement (Cohen's κ + a bootstrap CI) — the "prove the evaluator is
correct" number an eval reader looks for.

> **These files are a committed, versioned contract** (not git-excluded), because the
> loader, the future judge wiring, and the κ computation all depend on the exact field
> set. Changing a field is a `schema_version` bump, never a silent edit.

Today one gold set exists: `diff_minimality.gold.jsonl` (**50 items**, all human-labeled).
New items are always committed as **unlabeled seeds** (`"label": null`) first — real labels
are added by a human (see the protocol below), never machine-generated, or the κ measures the
judge against itself instead of against a human, which is not validation.

Two agreement views are computed over this set: `python -m clinescope.judge_run` reports the
single-draw human-vs-judge **Cohen's κ**, and `python -m clinescope.judge_multidraw` reports how
much that κ moves across repeated judge draws (per-draw spread) plus the judge's **Fleiss' κ**
self-consistency (draws treated as raters) — because the model flips labels run-to-run even at
temperature 0.

## Format — one JSON object per line (JSONL)

`gold/<dimension>.gold.jsonl`, one labeled item per line. Fields:

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | int | Bumped when the field set changes. |
| `item_id` | str | Stable, human-assigned id (e.g. `dm-0001`). For debugging a misalignment; never fed to κ. |
| `dimension` | str | The scorer this gold set validates — `"diff_minimality"`. |
| `source` | `{"trace": <path>}` | A **pointer** to a trace file, **repo-relative**. NOT the patch text, NOT a `tool_use_id` (see "Which call is labeled"). |
| `label` | `"WASTEFUL"` \| `"NOT-WASTEFUL"` \| `null` | The human's holistic verdict. `null` = unlabeled (a seed placeholder). |
| `labeler` | str \| null | Who labeled it. |
| `labeled_at` | str \| null | When (ISO 8601). |
| `notes` | str | Free text (why, or what makes the case arguable). |
| `patch_sha256` | str \| null | Optional drift tripwire — see "Drift tripwire". |

Blank / whitespace-only lines are ignored (a trailing newline is legal). Any other
malformed line is a **hard error naming the line number** — the loader never silently
skips a bad item.

## Which call is labeled — the FIRST apply_patch, per trace

A trace can contain **several** `apply_patch` calls. Every clinescope scorer that reads a
patch scopes to the **first `apply_patch` by scan order** and never reads `tool_use_id`
(`diff_coherence_select_apply_patch`). The gold pointer is therefore **trace-only, never
id-keyed** — an id-keyed pointer could silently disagree with the scorer about which call
is graded and mislabel a multi-`apply_patch` trace.

**Granularity is one label per trace, applied to the first apply_patch.** When a trace has
more than one `apply_patch` call, the loader surfaces `apply_patch_call_count > 1` on the
resolved item so a labeler always knows they are grading the **first** call, not a later
one. (Example: `examples/apply-recovery-trace.json` has two calls — a failed `call-2` and a
recovery `call-3`; the label applies to the failed `call-2`, the same call the scorer
grades.) A future need for per-*call* labels would be a **new `schema_version`**, not a
retrofit of this one.

## Drift tripwire — `patch_sha256`

`patch_sha256`, when set, is the sha256 of the **lifted patch text** of the first
apply_patch — the exact string `diff_coherence_read_patch_text(first_call)` returns, UTF-8
encoded — **not** the raw JSON line, **not** `call.input`. The loader verifies it at resolve
time and **fails loud on a mismatch**, so a committed example trace can never change
underneath a human label without the drift being caught (mirrors the golden-fixture drift
guard, `tests/test_fixture_drift.py`).

Compute it with:

```python
from clinescope.world_a import load_trace
from clinescope.diff_coherence import (
    diff_coherence_select_apply_patch,
    diff_coherence_read_patch_text,
)
import hashlib

trace = load_trace("examples/apply-patch-trace.json")
call, _ = diff_coherence_select_apply_patch(trace)
text = diff_coherence_read_patch_text(call)
print(hashlib.sha256(text.encode("utf-8")).hexdigest())
```

Leave it `null` while an item is an unlabeled seed; pin it when the item is labeled.

## Labeling protocol (for a human labeler)

The judge is only validated if a human labels **blind to the judge and to the deterministic
score**. Follow this:

1. **Answer one holistic question per item:** *"Is this patch **wasteful** — does it rewrite
   more than the change needs (e.g. retyping whole blocks it could have edited in place)?"*
   Answer `WASTEFUL` or `NOT-WASTEFUL`. This is deliberately the holistic judgment, **not**
   the deterministic `diff_minimality` blind-rewrite shape proxy — the whole point of κ is to
   check whether the automated proxy agrees with a human's holistic call.
2. **Label blind.** Do not look at the `diff_minimality` score or the judge's output for the
   item before you decide. Read the patch text of the **first** apply_patch and decide.
3. **Do not let the machine label for you.** Every `label` in a shipped gold file must be a
   human's own call. A machine-filled label makes the κ judge-vs-machine theater.
4. **Record provenance:** set `labeler`, `labeled_at`, and pin `patch_sha256` for the item.
5. **Prefer genuinely arguable cases.** A gold set of only obvious cases yields a
   near-degenerate κ; the cases that validate a judge are the ones where a reasonable human
   and the proxy could plausibly disagree.

## Loading a gold set

```python
from pathlib import Path
from clinescope.gold import gold_load_resolved

resolved = gold_load_resolved(
    "gold/diff_minimality.gold.jsonl", repo_root=Path(".")
)
for r in resolved:
    print(r.item.item_id, r.item.human_label, r.scored_call.id, r.apply_patch_call_count)
```

`gold_load_items` parses without resolving; `gold_resolve_item` / `gold_load_resolved`
resolve each pointer to its trace and first apply_patch, failing loud on a missing trace, a
trace with no apply_patch, or a `patch_sha256` drift.

## The judge cache (`diff_minimality.judge.jsonl`)

`diff_minimality.judge.jsonl` is the committed **judge-output cache** — one row per gold
item, produced by running the opt-in LLM judge over the gold set:

```
python -m clinescope.judge_run --report        # judge all items, write the cache, print κ
python -m clinescope.judge_run --report-only    # re-print κ from the cache (NO model call)
```

It is committed so κ is reproducible with **no model call and no cost**: the reporter reads
this cache + the human labels above and computes Cohen's κ. Each row is a JSON object:

- `schema_version` (int), `item_id` (str, joins to the gold row), `dimension` (str).
- `outcome` — `"verdict"` (a real judge label), `"unparseable"` (no `VERDICT:` line in the
  model answer), or `"error"` (an endpoint / truncation failure). Only `"verdict"` rows enter
  κ; the others are **excluded and counted** (never silently defaulted to a class).
- `judge_label` — `"WASTEFUL"` / `"NOT-WASTEFUL"`, or `null` for a non-verdict outcome.
- `rationale` — the raw model answer (audit trail for a low-κ disagreement, never scored).
- `model_id` — the exact model that produced the verdict (the free-vs-paid provenance).
- `patch_sha256` — the digest of the lifted patch judged; the reporter fails loud if the gold
  trace drifted between the run and the report.
- `judged_at` — ISO-8601 timestamp.

The cache is written LF-only (`.gitattributes` pins `*.jsonl eol=lf`). The judge is **opt-in**
and the ONLY LLM surface — the core scorers stay deterministic / zero-LLM / keyless.
