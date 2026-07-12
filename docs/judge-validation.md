# Judge validation

Clinescope's four core scorers are **deterministic** — no LLM is involved, and they are what
`clinescope-gate` gates on. Clinescope *also* ships one **optional LLM judge** (used by
`diff_minimality` to catch subtler "wasteful edit" cases that the deterministic heuristic misses).

Any tool that uses an LLM to judge quality owes you one honest answer: **does the judge agree with a
human?** This page is that answer.

## How it's measured

The judge (a free local `gpt-oss:20b` served by Ollama, temperature 0, shown the patch text alone,
blind) is run over a **human-labeled gold set** and scored with **Cohen's κ** — chance-corrected
inter-rater agreement — against the human labels, with a bootstrap 95% confidence interval. κ, not raw
accuracy, because raw agreement flatters a judge on an unbalanced set.

## The result (N = 50)

```
cohen_kappa:  0.0496    95% CI: [-0.1200, 0.2175]    N = 50

confusion (rows = human, cols = judge):
                       judge WASTEFUL   judge NOT-WASTEFUL
  human WASTEFUL              3                21
  human NOT-WASTEFUL          2                24
```

The confusion matrix tells the story: the free 20B judge is strongly **NOT-WASTEFUL-biased** — it calls
almost everything "fine," so on a balanced set it catches only **3 of 24** genuinely wasteful patches.
**κ ≈ 0 is far below the 0.5 floor**, so the judge is treated as **advisory-only and kept out of the CI
gate** — `clinescope-gate` fires on the deterministic scorers, never on a judge that measured at chance
level.

That negative result is the point: Clinescope gates on the signals it trusts and, provably, not on the
one it doesn't.

## Reproduce it yourself (no model call)

```bash
python -m clinescope.judge_run --report-only         # reads the committed cache; prints κ + CI
python -m clinescope.judge_multidraw --report-only    # how much κ moves across repeated draws
```

## Honest caveats

- **N = 50 is still small** — the 95% CI is wide and straddles zero. Read the interval, not the point
  estimate.
- **One free local model on small edits.** Robustness across multiple / frontier judge models is on the
  roadmap, not claimed here.
- **A single-draw κ isn't reproducible to the digit** — `gpt-oss:20b` flips labels run-to-run even at
  temperature 0, which `judge_multidraw` measures directly (per-draw κ spread + Fleiss' self-consistency).
- **Growing the gold set from 26 to 50** harder, balanced, blind-labeled cases *lowered* the measured κ
  (from ≈0.24). That is an honest floor, not a regression — the earlier, smaller set was
  NOT-WASTEFUL-heavy, which had flattered the biased judge.

The gold set, the blind-labeling protocol, and the judge cache live in [`../gold/`](../gold/).
