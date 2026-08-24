# Scope: what this is, what it is not, and how to kill an idea

This is the file that says no. It exists because the failure mode for a solo-built tool is not
building too little, it is building interesting things nobody asked for.

It does not invent a new approval system. It operationalises the two gates already stated in
[`CLAUDE.md`](../../CLAUDE.md): **every feature must be required by a real user's feedback**, and
**all seven feature-gate questions must be answerable**. This file is how you actually run them.

## What clinescope does

Scores a coding agent's edits and tool trajectory from a **real Cline execution trace**, using
deterministic zero-LLM scorers, in the two trace formats Cline actually writes.

That sentence is the boundary. Each clause is load-bearing:

- **Real execution trace.** Not a synthetic benchmark, not a prompt-response pair.
- **Cline.** One agent, in its own formats. Not "any coding agent".
- **Deterministic, zero-LLM.** The scorers that produce a pass or fail signal never call a model.
- **Edits and trajectory.** Patch grammar, one bloat shape, and retry patterns. Not correctness.

## What it deliberately does not do

Each of these is a decision, not a gap waiting to be filled. Reopening one needs the amendment
procedure below, not a good afternoon.

| Not doing | Why |
|---|---|
| A hosted service or SaaS | The tool is a local CLI and a CI gate. A service is a different product with different obligations. |
| A second, non-Cline adapter | No abstraction for adapters that do not exist. The loader would port cheaply, but the diff scorers are welded to Cline's grammar, so each new agent needs a **new scorer**, not a config flag. There is no generic seam, and inventing one before a second real case exists is guessing. |
| A gate-able LLM judge | Out by design, not by schedule. The judge measures chance-level agreement. A signal that cannot beat chance cannot gate a build. |
| Generic framework adapters (LangGraph, CrewAI, and similar) | Same reason as the second adapter, plus it dissolves the one thing that makes this tool distinct. |
| Rebuilding a static-benchmark runner | Different problem, already solved elsewhere. Orthogonal to trace scoring. |
| Statistical significance machinery on the gate | Version 1 is a simple threshold, deliberately. Sophistication in the gate before anyone runs the gate is decoration. |
| Positioning as a general "AI eval platform" | That phrase describes other people's products. The defensible thing here is narrow: Cline-native, real-execution-trace, per-format diff and trajectory. |

**Known gaps that are real, and still are not licences to build.** A shape scorer for the
`editor` tool does not exist. A `write_to_file` / `replace_in_file` grammar scorer does not
exist. Task-completion detection does not exist. These are honestly disclosed in
`LIMITATIONS.md`. A gap being real does not answer question 1 below; someone still has to want
it filled.

## The amendment procedure

Run it in order. Stop at the first failure. Write the result down; an idea killed silently comes
back next month wearing a different name.

### Step 1. Produce the user, in their own words

Paste the actual request: the issue, the message, the comment, with a link. Verbatim, not your
summary of it.

**No quote means no user. Stop here.** Not "stop and think harder", stop. This step fails far
more often than it looks like it will, and that is the point of putting it first.

One clarification, because it is the most common way this step gets faked: **you are not a
user.** You wrote the tool. Your own frustration while developing it is a maintainer's itch, and
it belongs in the backlog, not through this gate.

### Step 2. Run the enthusiasm check

You now have a real quote. That is necessary and not sufficient, because a real quote can still
be the hook you hang your own idea on. Count how many of these are true:

1. The idea arrived while you were reading your own code, not while watching or reading about
   someone using the tool.
2. You can describe the feature in detail but cannot name the person who gets it.
3. The user's actual words are much smaller than what you are proposing to build.
4. It generalises the tool. Any sentence containing "and then it would also work for" is this.
5. It is more fun to build than the least glamorous thing currently on the list.
6. You went looking for something to build, and found this.
7. The pain you can articulate best is yours, not theirs.

**Three or more true: the idea is your enthusiasm wearing the user's quote as a hat.** Kill it
or shrink it to the size of what was actually asked for, then re-run from step 1.

Zero to two: continue.

### Step 3. Answer all seven feature-gate questions

They are listed in [`CLAUDE.md`](../../CLAUDE.md) under "Scope rules that gate new work". Answer
every one in writing. An unanswered question is a failed gate, not a to-do.

Question 4 is the one that does the most work and gets skipped the most: **what breaks if this is
not built?** If the honest answer is "nothing, it would just be nicer", you have a vitamin. The
tool has a fixed budget of attention and vitamins spend it.

### Step 4. Check it against the boundary

Look at the four clauses under "What clinescope does". Does the feature stay inside all four?

Anything that broadens past Cline, past real traces, or into correctness claims does not get in
through this procedure. It needs the boundary itself changed first, deliberately and on the
record, which is a bigger conversation than a feature.

### Step 5. Write the disposition

One line, into the commit or the issue:

```
SCOPE: <build | shrink | park | kill> - <the one sentence that decided it>
```

A parked idea gets a date. Re-running the procedure on a parked idea is cheap. Letting it drift
back in without re-running it is how the boundary erodes.

## When the procedure says build

Build the smallest version that resolves the quote from step 1. Not the version that anticipates
the next three requests. If a second user asks for the extension later, that is a second run of
this procedure, and it will be a better-informed one.

## The honest limit of this document

This procedure is written by the person it is meant to constrain, which is a real weakness and
worth naming rather than hiding. It works to the extent that step 1 is run honestly, and step 1
is exactly the step that is easiest to fake by writing a plausible user into existence.

The mitigation is that step 1 demands a **link**. A link either resolves or it does not.
