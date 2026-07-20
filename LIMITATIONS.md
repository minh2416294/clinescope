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

## What Clinescope does NOT claim

- `tool_selection` scores tool NAMES, not tool ARGUMENTS or success.
- `diff_coherence` scores apply_patch GRAMMAR, not whether the patch APPLIES or is CORRECT.
- `diff_minimality` scores ONE bloat shape, not overall edit MINIMALITY.
- `apply_recovery` scores a same-file retry TRAJECTORY, not whether the fix is RIGHT.
- The optional LLM judge is ADVISORY, never a gate signal (see below).

## The diff scorers grade `apply_patch` only

The three diff scorers grade Cline's `apply_patch` grammar. On a trace that edits with `write_to_file` or
`replace_in_file` instead (common in the VS Code extension), `diff_coherence` reports a hard `0/100` and
`diff_minimality` / `apply_recovery` abstain (`n/a`). That is honest, not a bug: a `write_to_file` /
`replace_in_file` diff-grammar scorer is on the roadmap, not shipped. `tool_selection` still scores those
tools (both families are in the pinned vocabulary).

## The LLM judge is advisory-only (kept out of the gate)

Clinescope ships one optional LLM judge (a local `gpt-oss:20b`) as an auxiliary signal for
`diff_minimality`. Validated against a 50-item human-labeled gold set, it agrees with humans only at
chance level: Cohen's kappa = 0.0496, 95% CI [-0.1200, 0.2175], N = 50. Because that is far below the 0.5
floor, the judge is treated as advisory-only and is deliberately kept out of the pass/fail gate
(`clinescope-gate` fires on the deterministic scorers, never the judge). The full measurement, the
confusion matrix, and how to reproduce it with no model call are in
[`docs/judge-validation.md`](docs/judge-validation.md).

## The validation corpus covers 3 of 4 failure modes

The real-trace regression corpus (`clinescope-corpus`) covers 3 of the 4 failure modes with real captured
Cline traces: `malformed_patch`, `missing_tools`, and `no_apply_recovery`. The fourth, `blind_rewrite`, is
a stated gap: the local models available could not emit a valid-but-bloated patch (they fail at the
tool-call stage, or Cline's fuzzy matcher applies a wrong-context patch), so coverage-of-modes with real
traces was chosen over a forced synthetic. See
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
