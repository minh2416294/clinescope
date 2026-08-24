# Measurement: what counts, what does not, and when a number may be changed

**State on 2026-08-24: 0 users, 0 revenue, 0 traces scored that the author did not generate.**

This file is written *before* the data arrives, on purpose. Every metric framework written after
the numbers show up is a framework built to make those numbers look good.

## The structure of this file, and why

Two classes of statement live here and they are governed differently.

- **Definitions are LOCKED.** What counts as activation, a repeat user, or a false positive does
  not change because circumstances changed. They are written once and are hard to revise.
- **Thresholds are DATED and REVISABLE.** Every number carries the date it was set and one line
  saying why that number. Numbers rot; the reasoning is what you argue with later.

### The hard rule

> **A threshold may not be revised after I have seen the data it would judge.**
>
> Revising it *before* new data arrives is calibration.
> Revising it *after* is moving the goalposts.
>
> That phrase sits on one line, unbroken and unformatted, so a grep can find it. A rule you
> cannot mechanically check for is a rule that quietly stops applying.

If a threshold looks wrong once the data is in, the honest move is to record that it was wrong,
report the result against it anyway, and set the next one before the next measurement window
opens.

## Locked definitions

**Activation.** A person who is not the author has run clinescope to completion on a trace, and
the run produced a score or an explicit abstention. Not an install. Not a `--help`. Not a
crash.

**Repeat user.** An activated person who has done it again on a **different** trace, on a
**different day**. The different-trace clause matters because re-running on the same trace is
usually troubleshooting the tool rather than using it. The different-day clause matters because
one sitting is one decision.

**False positive.** Any number that rises without a trace being scored by someone who is not the
author. This is the definition that does the most work in this file, and it is deliberately
aggressive: for this product, a metric that can move while zero traces are scored is not a weak
signal, it is a **wrong** one.

These three are the locked set. Everything below is a threshold or a procedure.

## What is actually worth measuring here

Ranked by information per unit of effort. The first two need no network and no telemetry.

1. **Repeat users**, as defined above. The whole ballgame.
2. **Abstention rate across real traces.** If a scorer abstains on most traces people actually
   have, it is aimed at the wrong format. This is a product signal disguised as a statistic, and
   it has already fired once (see `user-data-instrumentation.md`).
3. **The gate entering someone else's CI config.** Publicly visible, no instrumentation needed,
   and it is the largest commitment this product can be handed.
4. **What happens after the gate goes red.** Threshold adjusted or issue fixed means the signal
   is trusted. Gate deleted means it is not. The most valuable single datum available.

## The four named false positives

Each is a signal this project will plausibly be offered first, and each is disqualified.

### Installs without a second run

An install is free and reversible, so it carries almost no information. Under the locked
definitions, an install is not activation and a thousand of them are not a thousand users.

**No conversion ratio from downloads to people exists.** The research behind this file went
looking and found none for PyPI. Do not invent one, and do not import one from another registry.

**Do not treat `mirrors=false` as human traffic.** This was assumed during the drafting of this
file and it is wrong. `pypistats` excluding known mirrors does not mean the remainder is people;
nothing published supports that reading, and the pypistats FAQ points the other way regarding
CI and CD traffic. The filtered series is *less mirror traffic*, not *more human*.

### Stars without a scored trace

In a survey of 791 developers (Borges and Valente, *Journal of Systems and Software*, 2018,
sampling error about 3.15 percent at 95 percent confidence), the reported reasons for starring
were:

> "GitHub developers star repositories mainly to show appreciation to the projects (52.5%), to
> bookmark projects for later retrieval (51.1%), and because they used or are using the projects
> (36.7%)."

Respondents could give more than one reason, so **36.7 percent is a ceiling on "has ever used",
not a conversion rate.** Never present it as one.

Bessemer, who invest in open-source companies, state their own position plainly:

> "This is part of the reason why we tend to pay little attention to numbers like Github Stars,
> which is a bit of a vanity metric that often tends to spike in correlation with big press
> releases but does not reflect continual engagement."

**No source names a star count that signals traction.** No investor threshold, no accelerator
threshold. If you find yourself reaching for one, you are about to make it up.

Stars are also purchasable. Dagster bought them from two vendors and measured the decay:

> "A month later, all 100 GitHub24 stars still stood, but only three-quarters of the fake Baddhi
> Shop stars remained."

### Downloads spiking around a release

**The measured fact for this project:** on 2026-08-20 the non-mirror download series shows 76,
against 1 on 2026-08-19 and 2 on 2026-08-21. That is the day 1.2.1 was published.

**What that fact does and does not license.** The temporal correlation is real and was measured.
The *mechanism* is not established: the mirror-driven publish-burst effect is documented on npm,
which does not filter mirrors, and it does not transfer to a series that already excludes them.
Stating a cause here would be exactly the kind of plausible unverified claim this repo has
shipped before.

So the rule is about shape, not cause: **a single-day spike that reverts to baseline within 48
hours is not adoption**, whatever produced it. Adoption does not arrive and leave in a day.

Assume nobody upstream will clean the counter for you. npm's own stated position:

> "bot filtering is really hard, and never totally accurate, and requires constant manual
> intervention or crazy machine learning to get right"

That post is from 2014 and should be re-dated before it is quoted anywhere outward-facing, but
the standing assumption it supports is safe: any adoption question you actually care about has
to be answerable from instrumentation you control.

### Enthusiasm without repeat usage

The hardest one, because it arrives as genuine goodwill from people being kind. Segment ran on
this misreading for a year and a half:

> "When he said he understood a concept was valuable, and saw that it was technically cool, he
> didn't actually mean 'We have this problem and need a solution.'"

The same source gives the inverted test worth more than any metric:

> "The customer always ends up pulling ... it out of your hands when you hit a real pain point."

**Ban-list, scoring exactly zero as evidence:** "this is cool", "valuable", "interesting", "I'll
check it out", a star, an upvote, a supportive comment, a retweet, a follow.

And the scale disclaimer: Kite reached roughly 500,000 monthly active users and never converted
that into a business. Volume is not fit.

## Decision procedures, not constants

Each says how to tell a number is **wrong**. That is worth more than a number that is right this
week.

**1. The subtraction test.** Before writing or saying any traction claim, delete every ban-list
item from the evidence. If nothing remains, the claim was counting kindness. Re-run this every
time this file is edited, not once.

**2. Direction of force.** For each conversation, record one binary before it ends: did they ask
for the repo or the install command *before* you offered it, or did you offer first. Never fill
this in from memory. On a 14-day timer, downgrade anyone classified as pulling who never sent an
unprompted follow-up. A ratio that only survives if you skip the downgrade is a vanity ratio.

**3. Concrete-action validation.** Words validate nothing. The unit is whether they ran the
thing. Track nudges separately and recompute using only the zero-nudge rows; if the headline
ratio needs the nudged rows, it was measuring your chasing, not their intent.

**4. The 60-day hold on any spike.** Mark the spike date. Check at day 60 whether an independent
usage series moved. Compare the slope in the quiet window before the spike to the slope 14 days
after. Back to baseline means the spike bought attention that did not convert. Note that the
measured promotional effect of purchased stars lasts under two months and becomes a liability
after.

**5. The effort-asymmetry filter.** For any metric, ask what it costs a scheduled script to
increment versus what it costs a human. If a cron job could produce your number, it is not
adoption evidence. Stars and downloads both fail this. Contributors pass it, though Bessemer's
caveat applies: contributors "only represent a small subset of users, but they are much easier to
measure".

**6. Never convert between stars and installs, in either direction.** The measured relationship
is weak and language-dependent, ranging from 0.47 for PHP down to 0.14 for JavaScript, and **no
Python coefficient is published at all**. There is no conversion factor available for a
pip-installed tool. Report the two series as separate lines and never reconcile them into one
adoption figure.

**7. Retention curves: heterogeneity is the null hypothesis.** A flattening or rising cohort
retention curve is the *expected* consequence of survivor sorting alone, with no individual
becoming stickier over time (Fader and Hardie). So a flattening curve is not evidence of fit
until it beats that null. Any retention criterion here compares a cohort against itself, never
against an imported benchmark, because no sourced retention benchmark for developer tools exists.

## Thresholds (dated, revisable, and subject to the hard rule)

Set 2026-08-24. Each carries its reasoning so a future revision has something to argue against.

| Threshold | Value | Why this number |
|---|---|---|
| Repeat users before any adoption claim may be written | 5 | Small enough to reach by talking to people directly; large enough that one enthusiastic acquaintance cannot produce it alone. Matches the unlock trigger in `user-data-instrumentation.md`. |
| Spike hold before it may be cited | 60 days | The measured promotional effect of purchased stars runs under two months, so a shorter hold cannot distinguish promotion from adoption. |
| Pull-classification downgrade timer | 14 days | Long enough for a busy person to come back unprompted, short enough that the classification does not drift on optimism. |
| Abstention rate that makes a scorer suspect | above 50 percent of real traces | Past half, the scorer is silent more often than not on what people actually have, which is the condition that produced `editor_recovery`. |

**None of these has ever been evaluated against real data**, because there is no real data. That
is the condition under which they are legitimately settable. Once a measurement window opens,
the hard rule applies.

## The adversarial move: skeptic first

**When numbers arrive, the skeptic's case gets written before the bull case.** Not after, not
alongside. First, in writing.

The order is the whole mechanism. A bull case written first becomes the thing the skeptic's case
has to argue against, and it wins by default because you wrote it.

The skeptic's case must answer all six:

1. Which of the four named false positives explains this number, if you assume the least
   flattering reading?
2. Could a scheduled script have produced it?
3. How many *traces* were scored by someone who is not the author? If the answer is zero, the
   number is a false positive by the locked definition, whatever else is true.
4. What did I do in the 7 days before the number moved? Check the post log before crediting the
   product.
5. Does it survive the subtraction test?
6. What number would have made me say this failed? If none was written down beforehand, this is
   not a measurement, it is a story.

Only after all six are answered in writing does the bull case get written.

## What the evidence does not support

Named here so none of it gets written as fact later. Each was looked for and not found.

- Any downloads-to-users conversion ratio for PyPI.
- A downloads-per-day noise floor below which a number is meaningless.
- A bot or automation percentage of PyPI traffic.
- That `mirrors=false`, or any pypistats filter, approximates human traffic.
- That a consumer of the download API can subtract automation after the fact.
- A star count that signals real traction, or any star threshold used by investors or
  accelerators.
- A conversion rate from stars, Hacker News points, or a Show HN placement to installs or users.
- Retention benchmarks for developer tools: no week-1 to week-4 percentage, no healthy
  runs-per-user figure, no churn rate. The widely circulated 6-month retention "good" and "great"
  figures are an aggregation of what about 20 practitioners personally consider good, not a
  measured study, and must carry that label if cited at all.
- A realistic telemetry opt-in rate for a developer tool.
- That stars predict contributor growth, maintenance survival, or project success.
- Any measured baseline for how much of a Cline-adjacent tool's traffic is agent-invoked rather
  than human. That has to be measured locally, never assumed.

## Related

- [`scope.md`](scope.md) for whether a thing should be built at all.
- [`user-data-instrumentation.md`](user-data-instrumentation.md) for what would be instrumented
  and the gate on claiming anything about accumulated data.
- [`CLAUDE.md`](../../CLAUDE.md) for the honesty rule that governs every claim written anywhere.
