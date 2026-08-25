# Judge validation

Clinescope's four core scorers are deterministic -- no LLM is involved, and they are what
`clinescope-gate` gates on. Clinescope also ships one optional LLM judge, asked the same holistic
"is this patch wasteful?" question the human labelers answer. It was built to test whether a cheap
local model could stand in for that human judgement. Measured against them, it cannot: the numbers
below are why it is advisory-only and why nothing gates on it.

## How it's measured

The judge (a free local `gpt-oss:20b` served by Ollama, temperature 0, shown the patch text alone,
blind) is run over a **human-labeled gold set** and scored with **Cohen's κ** -- chance-corrected
inter-rater agreement -- against the human labels, with a bootstrap 95% confidence interval. κ, not raw
accuracy, because raw agreement flatters a judge on an unbalanced set.

## The result (N = 50)

```
cohen_kappa:  0.0433    95% CI: [0.0000, 0.1503]    N = 50

confusion (rows = human, cols = judge):
                       judge WASTEFUL   judge NOT-WASTEFUL
  human WASTEFUL              1                23
  human NOT-WASTEFUL          0                26
```

The confusion matrix tells the story: the free 20B judge is strongly **NOT-WASTEFUL-biased** -- it calls
almost everything "fine," so on a balanced set it catches only **1 of 24** genuinely wasteful patches.
**κ ≈ 0 is far below the 0.5 floor**, so the judge is treated as **advisory-only and kept out of the CI
gate** -- `clinescope-gate` fires on the deterministic scorers, never on a judge that measured at chance
level.

That negative result is the point: Clinescope gates on the signals it trusts and, provably, not on the
one it doesn't.

### Read the interval before you read the point estimate

The lower bound is `0.0000` and the interval no longer runs negative. **That is not the judge getting
better, and it is worth being explicit about because the opposite reading is the easy one.** The judge
answered WASTEFUL exactly once across the whole set. When a rater almost never uses one class, any
bootstrap resample that happens to omit that single item has observed agreement equal to chance
agreement, and its κ is exactly 0. Those resamples are 36% of the pool here, which is what fixes the
2.5th percentile at 0.0000. The bound is an artifact of near-total one-class prediction, not evidence
of a signal.

The practical version: the entire positive agreement rests on one patch. Change that one label and the
number goes to zero or below.

### The previous measurement, for comparison

```
cohen_kappa:  0.0496    95% CI: [-0.1200, 0.2175]    N = 50   (judge prompt unfenced)

confusion (rows = human, cols = judge):
                       judge WASTEFUL   judge NOT-WASTEFUL
  human WASTEFUL              3                21
  human NOT-WASTEFUL          2                24
```

The prompt changed between these two runs: the patch text is now fenced between tagged markers so a
patch cannot address the model directly. That invalidated every cached verdict, so all 50 were
recomputed, and both figures are shown rather than the old one being quietly replaced.

**The difference is not attributable to the fence.** Each figure is a single draw, and this model flips
labels run-to-run at temperature 0 by roughly a third on at least one known item. A gap of 0.0063
between two single draws is well inside that noise. What both runs agree on is the part that matters:
the judge is at chance, and it is heavily biased toward calling patches fine.

## Reproduce it yourself (no model call)

```bash
python -m clinescope.judge_run --report-only         # reads the committed cache; prints κ + CI
python -m clinescope.judge_multidraw --report-only    # how much κ moves across repeated draws
```

## Honest caveats

- **N = 50 is still small** -- the 95% CI is wide and its lower bound sits exactly at zero. Read the
  interval, not the point estimate, and read the note above on why that bound is degenerate rather than
  reassuring.
- **One free local model on small edits.** Robustness across multiple / frontier judge models is on the
  roadmap, not claimed here.
- **A single-draw κ isn't reproducible to the digit** -- `gpt-oss:20b` flips labels run-to-run even at
  temperature 0, which `judge_multidraw` measures directly (per-draw κ spread + Fleiss' self-consistency).
- **Growing the gold set from 26 to 50** harder, balanced, blind-labeled cases *lowered* the measured κ
  (from ≈0.24). That is an honest floor, not a regression -- the earlier, smaller set was
  NOT-WASTEFUL-heavy, which had flattered the biased judge.

The gold set, the blind-labeling protocol, and the judge cache live in [`../gold/`](../gold/).
