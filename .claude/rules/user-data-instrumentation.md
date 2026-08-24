# User data: what to instrument, and what may not be claimed yet

**State on 2026-08-24: zero users, zero revenue, zero external traces.** Nothing in this file
describes a system that is running. It describes one that is not built, and sets the gate that
has to be met before anyone writes a word about accumulated usage.

This exists because the question that produced it ("audit my interaction data, describe how long
the flywheel has been spinning") has no honest answer today. The honest version is this document.

## Rule zero

**No claim about accumulated user data, network effects, or a data advantage may be written
until the gate at the bottom of this file is met.** Not in a README, not in a pitch, not in a
post, not in an issue reply. There is no data. Saying otherwise is the specific thing
[`CLAUDE.md`](../../CLAUDE.md)'s honesty rule bans.

## Instrumentation that would be built, and what each signal would actually tell you

None of this exists. Building any of it is itself a feature and must pass
[`scope.md`](scope.md) first, including step 1. That is not a formality: a local CLI with
`dependencies = []` that starts phoning home is a different product, and the person most likely
to want the telemetry is the author, which is exactly the case step 1 is designed to catch.

Listed cheapest-first. The ordering matters more than the list, because the first two need no
network at all.

| Signal | How it would be captured | What it would actually tell you | What it would not |
|---|---|---|---|
| Run count and distinct trace hashes, local only | A local counter file the user can read and delete | Whether the tool was run more than once, and on more than one trace | Nothing about who, and nothing you can see unless they tell you |
| Which scorers abstained | Already computed at runtime; would need recording, not new logic | Whether the scorers match the traces people really have | Whether the scores were believed |
| Gate exit codes over time | The CI system already has this; the user would have to share it | Whether the gate ever fires, and whether it fires usefully | Whether a red gate changed any behaviour |
| Threshold values in committed config | Visible in any public repo that adopts the gate | What the community thinks a reasonable bar is | Anything about private repos, which is most of them |
| Opt-in ping, explicit and off by default | A network call, a dependency, and a privacy policy | Aggregate adoption | Whether adoption is repeat use, unless designed for it specifically |

**The honest ranking:** the first two are worth building and cost almost nothing. The last one is
the one that feels like "real" instrumentation and is the least informative per unit of trust
spent. A developer tool that adds a phone-home before it has users is optimising the wrong thing
and spending goodwill it has not earned.

## The three behavioural patterns most worth capturing

Three, not ten, because these are the three that each answer a different question, and no other
candidate answers a question these leave open.

### 1. A second run, on a different trace

**Question it answers: did this produce anything worth coming back for?**

Installing is free and reversible, so it carries almost no information. Running the tool a second
time, on a trace that is not the first one, is the smallest action that cannot be explained by
curiosity. It is the boundary between someone who looked and someone who used.

The "different trace" clause is load-bearing. Re-running on the same trace is usually
troubleshooting the tool, not using it.

### 2. The gate entering a CI configuration

**Question it answers: did someone accept a cost to keep this in their life?**

Running a CLI costs one command. Wiring `clinescope-gate` into a pipeline means accepting that
this tool can now block their build. That is the largest commitment this product can be given,
and it is the only one that generates repeat runs without any further intent.

It is also the only pattern here that is visible from outside, in a public repository, without
asking anyone anything.

### 3. What happens after the gate goes red

**Question it answers: is the score believed?**

This is the one that is easy to leave out and hardest to replace. The other two measure use. This
measures trust, and they are not the same thing.

When the gate fails a build, exactly one of three things happens:

- the threshold is adjusted, which means the signal is trusted and the bar was wrong;
- the underlying issue is fixed, which means the signal is trusted and correct;
- the gate is removed, which means the signal is not trusted.

The third outcome is the most valuable data this product could ever receive, and it is the one a
naive install-and-usage metric would record as churn with no reason attached.

## The feedback loop, designed but not running

The loop that turns a scored trace into a product improvement:

```
real trace -> scored -> a scorer produces a number OR abstains
                              |
                              +-- high abstention rate on real traces
                                       -> the scorer measures a format people do not use
                                       -> build the scorer for the format that appears
```

**Abstention rate is the product signal, not the score.** A scorer that abstains on most real
traces is not a weak scorer, it is a scorer aimed at the wrong thing.

**This loop has run exactly once, and not on user data.** The three `apply_patch` scorers abstain
on nearly every current Cline session, because almost no session emits `apply_patch` any more.
That was noticed on the maintainer's own traces, and `editor_recovery` was built in response.

One instance, from one person's own traces, is not a flywheel and is not described as one here.
It is written down because it is evidence the loop design is sound, and because a loop that has
run once is a materially different claim from a loop that has never run.

## Moat narrative: TEMPLATE, gated, do not fill in

The section below stays empty. It is not a draft to be tightened later. It may not be filled in,
in whole or in part, until the trigger beneath it is met.

```
<!-- LOCKED. Do not complete any line in this block. See the trigger below. -->

Distinct external users to date:            [LOCKED]
Traces scored that we did not generate:     [LOCKED]
Period over which they accumulated:         [LOCKED]
What the accumulated data makes possible
that a competitor could not replicate:      [LOCKED]
Evidence for that claim:                    [LOCKED]
```

### The trigger

The template unlocks when, and only when:

> **Five people who are not the author have each run clinescope on a trace they generated
> themselves, on at least two separate days, and this is evidenced by something durable: a
> message, an issue, a commit in a public repository, or a shared report.**

**What this trigger deliberately does not accept:** downloads, stars, forks, installs, package
mirror traffic, CI re-installs, page views, an expression of interest, or anyone's stated
intention to try it. None of those involve a real trace, and the trace is the entire point.

Per [`measurement.md`](measurement.md), the **definitions** in that trigger are locked and hard to
revise. The **number five** is a threshold: it carries the date it was set (2026-08-24) and is
revisable, but only before the data that would judge it arrives. Revising it after seeing who
showed up is moving the goalposts.

Reasoning for five, so a future revision has something to argue with: it is small enough to be
reachable by talking to people directly, and large enough that no single enthusiastic
acquaintance can produce it alone.

## What may be said today

That the tool exists, that it is published, what it deterministically checks, and what it
honestly does not. Every one of those is verifiable by a stranger in under a minute.

That is a complete and defensible position for a tool at this stage. It does not need to be
supplemented with a story about data.
