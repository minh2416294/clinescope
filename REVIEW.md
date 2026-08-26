# Review instructions for clinescope

Read this before ranking anything. It overrides default severity calibration for this
repository.

**Severity vocabulary.** The managed reviewer uses Important / Nit. This repo's local review
skill uses Critical / Important / Minor (`~/.claude/rules/review-severity.md`). Treat Nit and
Minor as the same tier. Reserve Critical for something that reaches a published artifact or a
stranger's machine; everything else below tops out at Important.

## What Important means here

This is a local CLI and a CI gate with no server, no auth and no user data, so the default
production calibration does not fit. Reserve Important for these five:

1. **A claim that cannot be defended with a real number.** This project's central rule is
   honesty about what it measures. A README, docs, docstring or help-text change that overstates
   what a check does is a real defect here, not a wording nit.
2. **A break in the `clinescope-gate` exit-code contract.** 0 means every gated scorer met its
   threshold, 1 means a real regression, 2 means nothing was verified. An abstention must never
   surface as a 1, and a usage error must never surface as 0 or 1.
3. **Trace-derived text reaching output without `render_safety.quote_untrusted_text`.** A trace
   is untrusted input and the bug-report template solicits one from strangers.
4. **A mutable action reference in `.github/workflows/`.** Every `uses:` must be a full commit
   SHA with the readable version in a trailing comment.
5. **Any addition to `dependencies` in `pyproject.toml`.** Zero runtime dependencies is a
   shipped guarantee, not a preference.

## Do not report

- Anything CI already enforces: `ruff check`, `ruff format --check`, `mypy src`, and the
  `--cov-fail-under=90` coverage gate.
- Formatting, line length, import order, or type-annotation style. Same reason.
- `examples/` and `gold/diff_minimality.gold.jsonl`. Both are frozen contracts. Proposing that
  either be regenerated, reformatted or relabelled is out of scope by design.
- `CHANGELOG.md` entries for past releases. Frozen history.
- Operator-supplied values left unescaped, such as `--expected` tool names. `render_safety`
  deliberately does not quote them, and its module docstring says why.
- Missing abstraction, adapter seams, or protocol classes. The two-adapter rule is deliberate
  and `judge.py` states it outright.

## Always check

- The specific deterministic check is named, rather than the scorers being described as judging
  how good a patch is. There are five scorers, not four.
- An abstention is reported as `n/a`, never as a zero.
- `dependencies = []` is unchanged.
- A behaviour change carries its README, CHANGELOG and CLAUDE.md update in the same commit.
  Drift is a latency problem, and same-commit leaves no window for a stale claim to survive.
- A new sink for trace-derived text neutralises at the source, not at the join.

## Verification bar

Every finding must cite a `file:line` that you actually opened. A behaviour claim inferred from
a name, a comment, or a docstring without reading the code is not a finding. If you cannot close
the path end to end, say so and drop it rather than reporting it at a lower severity.

## Cap the nits

Report at most five Nits per review. If there are more, give the count in the summary instead of
listing them. If everything found is a Nit, open the summary with "No blocking issues".
