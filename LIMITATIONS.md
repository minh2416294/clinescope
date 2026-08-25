# Limitations

Read this before you act on a Clinescope score. Every scorer here is deliberately narrow: it measures
one concrete, checkable property and states exactly what it does NOT measure. The point of listing the
boundaries is so a score is only read in the context it was built for, never as a verdict it cannot
support. Each caveat below mirrors the honesty caveat in that scorer's own docstring; if the two ever
disagree, the docstring is the source of truth.

## Per-scorer boundaries

### `tool_selection` measures name-only recall, not argument correctness

It scores `|used names intersect expected| / |expected|`: did the run call the tools the task needed, by
name? It does NOT check tool arguments, call order, or whether a call succeeded (an errored call still
counts as "used", because selection is judged by invocation, not success). Extra tools never lower the
score (that is recall, not precision); they are surfaced separately so you can still see them. An empty
`expected` set scores 1.0 (nothing was required, so nothing was missed).

What to do instead: if you need argument-level or ordered checking, this scorer is the wrong tool; pair
it with your own argument assertions.

### `diff_coherence` measures apply_patch grammar, not apply-against-a-real-file success

It grades the coherence of the first `apply_patch` patch text against Cline's real `*** Begin Patch`
grammar. It does NOT prove the patch applies. Cline's real executor also fuzzy-matches each hunk's
context against the on-disk file, which a standalone trace cannot reproduce (there is no repo checkout to
match against), so a patch can score 100/100 here and still fail Cline's executor because its context
does not locate in the target file. The report labels this `[diff_coherence]`, never `apply_success`.
Cline's own applied/failed verdict is read as context only; it never enters the score.

What to do instead: grammar validity does not prove apply success. To confirm the edit lands, apply the
patch against the actual file.

### `diff_minimality` detects one bloat shape, not all over-editing

It detects EXACTLY ONE shape: a blind whole-block rewrite inside an `*** Update File` hunk (delete a run
of lines, retype them, keeping no anchor). It is BLIND to the more common bloat of dragging large
unchanged context, and deliberately does NOT threshold on context-line count (a design study showed every
context-count / line-similarity signal inverts on real patches; only run-length blind-rewrite detection
survived). So a heavily context-padded patch can still score 100/100. A LOW score means "contains a large
blind rewrite" (which may be necessary; read it as large-block, not wasteful); a HIGH score means "no
blind rewrite", NOT "minimal". The `mean_context_density` figure is descriptive evidence only, never
scored.

What to do instead: read the score as one structural property of the patch text, not a standalone
minimality verdict; read `mean_context_density` alongside it.

Its measured agreement with human labels, what its CI gate flag has and has not fired on, and why
an identical edit can score 1.0 or 0.0 depending on the layout of the file, are in "The gated
`diff_minimality` flag is weaker than it looks" below.

### `apply_recovery` measures a trajectory pattern, not fix-correctness

Of every `apply_patch` Cline marked failed, it scores the fraction later recovered by a strictly-later
`apply_patch` that Cline confirmed non-failing and that re-touches the same file. "Recovered" means only
that: it does NOT verify the retry fixed the original defect, does NOT verify semantic correctness, and
matches at FILE granularity (a later unrelated edit to the same file counts). It is BLIND to cross-tool
recovery: an agent that abandons `apply_patch` and correctly fixes the file via `write_to_file` /
`replace_in_file` scores that failure as unrecovered (a disclosed false negative). Path matching is
literal, so the same file spelled differently is a false miss. It abstains (`n/a`) when nothing failed.

What to do instead: read a LOW score as "did not recover via a same-file confirmed apply_patch", not "did
not recover at all"; confirm real fixes by inspecting the trajectory.

### `editor_recovery` measures the same trajectory pattern, for the `editor` tool

Of every `editor` call Cline marked failed, it scores the fraction later recovered by a strictly-later
`editor` call Cline confirmed non-failing on the same path. Every caveat on `apply_recovery` above applies
unchanged: it does NOT verify the retry fixed anything, does NOT verify semantic correctness, and matches
at FILE granularity. It is BLIND to cross-tool recovery, so an agent that abandons `editor` and fixes the
file with `run_commands` scores that failure as unrecovered. Path matching is LITERAL, and on Windows that
is a live risk rather than a theoretical one: the same file reached through Git Bash arrives as
`/c/Users/...` and through PowerShell as `C:\Users\...`, and those will not match each other. It abstains
(`n/a`) when nothing failed.

Unlike its sibling it has no `partially_recovered_failures` counter, because one `editor` call touches
exactly one path and so can never be half-recovered.

What to do instead: read a LOW score as "did not recover via a same-path confirmed editor call", not "did
not recover at all".

### `diff_coherence` has no `editor` analogue, and one is not planned

There is no `editor_coherence`. `apply_patch` carries a freeform patch string with a grammar that a model
can get wrong, which is what `diff_coherence` grades. An `editor` call carries structured fields (`path`,
`old_text`, `new_text`, `insert_line`) instead of a freeform payload, so there is no grammar to parse.

A mis-shaped `editor` call is not rejected by the schema. At cline/cline commit
`4f836ae7d0ed29ece7ef4a2a478deb470fdd056e`, `old_text` is declared optional and nullable
(`sdk/packages/core/src/extensions/tools/schemas.ts` lines 200-206), so omitting it passes validation and
the call fails later inside the executor, at
`sdk/packages/core/src/extensions/tools/executors/editor.ts` line 259, when the target file already
exists. Cline reports that as `success: false`, which is exactly the verdict `editor_recovery` already
reads; the capture at `examples/live-granite-editor-recovery.json` is one such call. So a shape scorer
would largely restate a verdict this repository already surfaces.

## What Clinescope does NOT claim

- `tool_selection` scores tool NAMES, not tool ARGUMENTS or success.
- `diff_coherence` scores apply_patch GRAMMAR, not whether the patch APPLIES or is CORRECT.
- `diff_minimality` scores ONE bloat shape, not overall edit MINIMALITY.
- `apply_recovery` scores a same-file retry TRAJECTORY, not whether the fix is RIGHT.
- `editor_recovery` scores a same-path retry TRAJECTORY for the `editor` tool, not whether the fix is
  RIGHT. There is no shape or quality scorer for `editor` at all.
- The optional LLM judge is ADVISORY, never a gate signal (see below).
- `--min-diff-minimality` has never produced a build-failing verdict on any real captured trace
  shipped in this repository, at any threshold.

## The diff scorers grade `apply_patch` only, and most sessions no longer use it

The three diff scorers grade Cline's `apply_patch` grammar. On a trace that edits with `editor`,
`write_to_file` or `replace_in_file` instead, `diff_coherence` reports a hard `0/100` and
`diff_minimality` / `apply_recovery` abstain (`n/a`). That is honest, not a bug, but it is now the common
case rather than the exception. Verified at cline/cline commit
`4f836ae7d0ed29ece7ef4a2a478deb470fdd056e`: all five tool presets set `enableApplyPatch: false`
(`sdk/packages/core/src/extensions/tools/presets.ts` lines 30, 50, 68, 85, 103), and only two routing
rules flip a session back to `apply_patch` (`model-tool-routing.ts` lines 60-75), both requiring `act`
mode plus either an `openai-native` provider or a model id containing `codex` or `gpt`. Everything else
gets `editor`, and the two tools are mutually exclusive (`definitions.ts` lines 935-939).

`editor_recovery` covers the trajectory half of that gap. A `write_to_file` / `replace_in_file`
diff-grammar scorer, and any shape scorer for `editor`, are on the roadmap and not shipped.
`tool_selection` still scores all these tools (every family is in the pinned vocabulary).

**`editor_recovery` is report-only in this release.** It renders in the `clinescope` report and feeds
`--advice`, but `clinescope-gate`, `python -m clinescope.compare` and `clinescope-corpus` do not read it
yet: the gate still exposes only `--min-diff-coherence`, `--min-diff-minimality` and
`--min-apply-recovery`. So on an editor-only session the gate has no usable signal at all, because all
three of those scorers grade `apply_patch` and the trace contains none.

**The gate now says that honestly instead of failing the build.** It exits `2`, the "nothing was
verified" code, rather than `1`, "a scorer regressed". Previously `diff_coherence` contributed a hard
zero reflecting the absent `apply_patch` rather than anything the agent did, and adding
`--min-diff-coherence` to a configuration turned an honest exit `2` into a build failure. The gate now
reads `apply_patch_call_count` and treats a trace with no `apply_patch` as not applicable to the whole
apply_patch family. A malformed patch still fails: the check is on whether a patch was present, not on
whether the score was zero.

The report is unchanged and still shows `diff_coherence 0/100` on such a trace, with the reason beside
it. That is the honest reading for a report, where a missing artifact should be loud rather than
silent, and the gate is the place where the distinction had to be made. **Gating CI on an editor-only
trace still verifies nothing**; the difference is that it now tells you so instead of blaming the agent.

## The LLM judge is advisory-only (kept out of the gate)

Clinescope ships one optional LLM judge (a local `gpt-oss:20b`) as an auxiliary signal for
`diff_minimality`. Validated against a 50-item human-labeled gold set, it agrees with humans only at
chance level: Cohen's kappa = 0.0496, 95% CI [-0.1200, 0.2175], N = 50. Because that is far below the 0.5
floor, the judge is treated as advisory-only and is deliberately kept out of the pass/fail gate
(`clinescope-gate` fires on the deterministic scorers, never the judge). The full measurement, the
confusion matrix, and how to reproduce it with no model call are in
[`docs/judge-validation.md`](docs/judge-validation.md).

That is only half the picture. The next section covers the scorer that stayed in the gate.

## The gated `diff_minimality` flag is weaker than it looks

The judge above estimates the same thing `diff_minimality` estimates, and both were measured
against the same 50 human labels. `diff_minimality` agrees with them at Cohen's kappa = 0.2599,
95% CI [0.0574, 0.4777], N = 50. Comparing a graded score to a binary label needs a cut; this one
uses the scorer's own invariant, that a score of 1.0 means zero blind rewrites, so 1.0 maps to
NOT-WASTEFUL and anything below it maps to WASTEFUL. The stricter available cut, below 0.5, gives
kappa 0.2175 and does not change any conclusion here.

So both estimators of "is this patch wasteful?" fall below the 0.5 figure the judge section cites,
the judge at 0.0496 and the gated scorer at 0.2599. Two qualifications, both cutting in different
directions. The judge's interval includes zero and the scorer's does not, which is a real
difference between them; note that a bootstrap interval excluding zero is not a hypothesis test,
and none was run. And that 0.5 figure is defined in the judge modules only, as an advisory
tripwire for an LLM signal. It has never been a project-wide validity bar for a deterministic
scorer, so read the comparison as one estimator against the other rather than as a rule being
broken. Both intervals are seeded percentile bootstraps whose full 2000 resamples were usable
(`n_boot_effective` 2000 of 2000 for each), so neither rests on a thin resample pool and both can
be read as written.

If you are deciding whether to gate on this, recall matters more than kappa. `diff_minimality`
flagged 7 of 24 patches a human called WASTEFUL, which is 29 percent. It scored a clean 1.0 on
the other 17.

**The gate flag has never fired on a real trace shipped here.** Twelve distinct captured Cline sessions ship in
this repository, across the corpus and the harness-gap experiment. Five score 1.0, seven abstain,
and none scores below 1.0. Running `clinescope-gate --min-diff-minimality` over the six corpus
traces at thresholds 0.0, 0.25, 0.5, 0.75, 0.99 and 1.0 gives no build-failing exit 1 in any of
the 36 runs. Every `diff_minimality` score below 1.0 anywhere in this repository comes from an
authored `examples/gold` fixture. The scorer itself is not broken, and it fires on all eight of
those. The gate is unexercised. This is the corpus gap described in the next section, stated as
its consequence: because no captured trace here contains a blind whole-block rewrite, there is no
threshold you can pass that makes this flag fail a build on the real traces shipped with it.

**It has now fired once, on a captured trace that is not shipped here, and what that took is the
finding.** On 2026-08-20 a `gpt-oss:20b` run through the Cline CLI produced a patch scoring 0.0 that
exits 1. How it was obtained matters more than that it exists: the task was chosen to make the shape
likely, two of four runs were discarded because the model's tool call failed to parse, and the target
file's branch was widened from two lines to three after watching what the model did to the two-line
version.

**The score depends on where `FLOOR` falls, not only on the agent's behaviour.**
Two runs, same model and same task. Both times the model anchored on the `if` line, retyped every
line through to the one it was changing, and kept no context line. On a two-line branch that is a run
of two, which is under `FLOOR` and scores 1.0:

```
-    if metric == "dlq_depth":
-        return 500
+    if metric == "dlq_depth":
+        return 2000
```

On a three-line branch the same approach produces a run of three, and scores 0.0:

```
-    if metric == "dlq_depth":
-        # dead-letter growth is bursty, so page late rather than early
-        return 500
+    if metric == "dlq_depth":
+        # dead-letter growth is bursty, so page late rather than early.
+        # Threshold increased to reduce noise from frequent paging.
+        return 2000
```

These two runs are not a controlled experiment and should not be read as one. In the second the model
also appended a period to the existing comment and wrote a new comment line, so the patches are two
deleted and two added against three deleted and four added. What stayed constant is the approach,
anchor on the `if` and retype through the change. What changed is the file, and with it whether the
retyped run reached three.

That threshold is the whole effect. Sweeping the retyped-run length and asking whether removing one
line from the file changes the verdict:

```
run of 2 -> 1.0     one line shorter, run of 1 -> 1.0     no change
run of 3 -> 0.0     one line shorter, run of 2 -> 1.0     verdict flips
run of 4 -> 0.0     one line shorter, run of 3 -> 0.0     no change
run of 5 -> 0.0     one line shorter, run of 4 -> 0.0     no change
```

So this is not a property of commented code. It is a threshold at three: one line of difference
changes the verdict only when it moves the retyped run across `FLOOR`, and at every other length it
changes nothing. How long that run is depends on the file being edited, not on how wasteful the agent
was. Read a score below 1.0 as "a run of at least three lines was retyped here", never as "this agent
wasted more effort than one that scored 1.0".

**The gold set is authored end to end.** All 50 items point at constructed patches. None is a
captured Cline trace. One person wrote every label, so there is no inter-rater reliability number,
and nothing in the data separates "the scorer missed it" from "one labeler's idea of wasteful is
idiosyncratic". The 24-to-26 class balance is a design choice rather than an observed rate, so
nothing here calibrates a false-positive rate or generalizes to real traces. What it does support
is a lower bound on recall for the bloat shapes its author chose to build, and the judge-to-scorer
comparison above, since both were measured on identical items by identical code.

**The other two gated scorers have no agreement number at all.** `diff_coherence` and
`apply_recovery` are gated the same way and have never been measured against a human label. Read
their silence as unmeasured, not as validated.

What to do instead: treat `--min-diff-minimality` as a regression tripwire for a shape you have
confirmed appears in your own traces, not as a general bloat filter. Score your own traces first.
If none of them scores below 1.0, this flag will not fail your build whatever threshold you pass.

## The validation corpus covers 3 of 4 failure modes

The real-trace regression corpus (`clinescope-corpus`) covers 3 of the 4 failure modes with real captured
Cline traces: `malformed_patch`, `missing_tools`, and `no_apply_recovery`. The fourth, `blind_rewrite`, is
still uncovered here, but the reason has changed. It used to be that no local model could emit a
valid-but-bloated patch at all. That is no longer true: on 2026-08-20 `gpt-oss:20b` emitted one, and the
capture is described above. It is not shipped in the corpus because the task was built to elicit it, so
it would be evidence that the scorer fires, not evidence about how often agents do this. See
[`examples/corpus/README.md`](examples/corpus/README.md).

## Not intended for

- A substitute for running the patch: a `diff_coherence` pass does not mean the edit applies.
- A model-ranking leaderboard: scores are trace-relative and scaffold-dependent, so a score is meaningful
  only alongside the exact setup that produced it. Do not compare bare scores across different harnesses.
- A hiring, promotion, or production-deploy gate on its own: these are narrow deterministic signals plus
  one chance-level advisory judge, not a measure of an agent's overall quality. Use them as one input,
  reviewed by a human.

## Scope

Clinescope reads Cline traces only: the CLI World-A `messages.json` v1 format and the VS Code extension's
`api_conversation_history.json` (via `--vscode`). Non-Cline frameworks are not handled. Validation used
one local model (`gpt-oss:20b`) on small edits; robustness across models is not claimed.
