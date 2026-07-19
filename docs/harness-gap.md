# The harness gap

Clinescope watches coding agents' failures after the fact. A fair question, raised by a Cline community member, is whether those are the wrong failures to be watching: if a run fails because Cline's default prompt never taught the model how to use its tools, then the real fix is upstream, in the prompt, not in a post-hoc analyzer. They named it cleanly: is a given failure a model gap (a capability limit an external auditor should catch) or a harness gap (something a better prompt would have prevented)?

They also proposed the test: run the same task, same model, once without a `.clinerules` harness and once with one; the difference between the two scores is the size of the harness gap. This page is that test.

## What the harness is

The "with harness" runs add one specimen file, [`examples/harness-gap/clinerules/000-tool-format.md`](../examples/harness-gap/clinerules/000-tool-format.md),
to the workspace's `.clinerules/` (an experiment artifact you copy into a Cline workspace, not something Clinescope ships or runs). It is short and general (a tool-format harness, with a worked example that is illustrative, not the answer to this task). It does three things Cline's default prompt does not:

1. Tells the model to edit with `apply_patch` and not to answer in prose.
2. Teaches the exact `*** Begin Patch` grammar with one worked example (verified to score
   `diff_coherence` 1.0, so the harness teaches a format the scorer actually rewards).
3. Adds "change only the lines that change" and "verify the file changed after `apply_patch`" rules.

`apply_patch` matters because Clinescope's three diff scorers grade `apply_patch` grammar. Cline's
default edit tool for a local model is `editor` (a plain old-text to new-text replacement); it routes
to `apply_patch` only for OpenAI, Codex, and GPT models. So for a local model, getting onto the
`apply_patch` path at all is itself part of what the harness has to do.

One thing to know when reading the traces: Cline does not serialize the `.clinerules` file into the
captured trace, so the harness's presence is not visible inside a trace's JSON. The bare and harnessed
runs are told apart by the capture directory each was run in (the harnessed workspace has the specimen
in its `.clinerules/`) and by the behavioral difference between them. The `.clinerules` content only
appears in a trace if the model reads it with a tool, as gpt-oss did with `search_codebase`.

## How it's measured

The same task in every run: "Add a function `sub(a, b)` that returns `a - b` to `calc.py`. Edit the
file using your tools." Each run starts from an identical `calc.py`. Every trace is a real Cline CLI
session, scored with `clinescope ... --expected read_files apply_patch`.

## The result

| Model | Harness | tool_selection | diff_coherence | diff_minimality | apply_recovery |
|---|---|---|---|---|---|
| qwen2.5-coder:7b | no | 0/100 | 0/100 | n/a | n/a |
| qwen2.5-coder:7b | yes | 0/100 | 0/100 | n/a | n/a |
| granite4.1:8b | no | 50/100 | 0/100 | n/a | n/a |
| granite4.1:8b | yes | 50/100 | 0/100 | n/a | n/a |
| gpt-oss:20b | no | (empty, see note) | (empty) | (empty) | (empty) |
| gpt-oss:20b | yes | 100/100 | 100/100 | 100/100 | n/a |

On qwen2.5-coder:7b, the community member's exact recipe, the measured delta is zero on all four
scorers. But the scores hide the interesting part. Without the harness, qwen reached for the default
`editor` tool. With the harness, it reached for `apply_patch` instead: the harness moved the model's
tool choice. In both runs, though, qwen wrote the tool call as JSON inside its prose rather than emitting a real tool call, so Cline recorded zero tool calls and every scorer stayed at zero.

That is the honest answer to their question, and it matches what they predicted for a small model: at
the 7B class, the failure is a model-capability ceiling, not a harness gap. A rules file can change
what a model intends to do, but it cannot give a model the ability to emit a valid tool call it cannot
emit.

The contrast case is the other half of the answer. gpt-oss:20b with the same harness made real tool
calls, emitted a grammar-valid `apply_patch` that succeeded, and actually edited the file: a clean
100/100/100. So a harness is necessary but not sufficient. It can put a capable model onto the
tool path an eval grades; it cannot manufacture tool-calling ability a weak model lacks.

The third model, `granite4.1:8b`, was suggested by the same community member on the theory that a
model built with a curated, task-designed data mix might behave differently from a general model of
the same size. It does, and the difference is the most interesting part of the result. Granite's
per-scorer delta is also zero on all four scorers, the same headline as qwen, but for the
opposite reason. Where qwen could not emit a single real tool call in either run (it wrote its edit
as prose JSON), Granite emitted real tool calls in both runs: one `read_files` call bare (then an
empty response before it edited), and six calls harnessed (`read_files`, `run_commands`, three
`editor` calls) that actually edited the file correctly. Granite clears the "can this model emit
a valid tool call at all" bar that stopped qwen.

What it did not do is switch onto `apply_patch`. The harness tells the model, in plain words, to edit
with `apply_patch` and never to answer in prose. Granite (which posts a high instruction-following
score on its own card) followed the spirit, a real edit tool, no prose code, but reached for Cline's
capable default `editor` tool three times and finished the task with it. So the diff scorers still
read `0` and `n/a`: not because Granite failed the task (harnessed, it succeeded), but because those
three scorers grade `apply_patch` grammar only, and Granite edited via `editor`. Its `tool_selection`
sits at `50/100` in both runs, matching `read_files` but never `apply_patch`.

So across three models the same zero delta hides three different stories. qwen stops at "can it emit
any tool call". Granite emits tool calls and edits successfully, but stops at "will it follow a
rules-file instruction to prefer one specific tool over Cline's capable default". gpt-oss does both.
The ceiling a harness runs into is not always tool-calling ability; on a competent instruction-follower
it can be the model's own preference for a tool that works. And Granite's zero is partly a
scorer-coverage limit, not a task failure: the same gap the diff scorers show on a `write_to_file`
extension trace, a non-`apply_patch` edit the grammar scorers abstain on, shows up here a second time
from a different angle.

## Honest caveats

- **This is one task per cell, not a benchmark.** It illustrates the mechanism (harness moves intent;
  capability sets the ceiling); it does not prove a population-level effect size. A larger task and
  model matrix is future work.
- **There is no fair gpt-oss:20b bare baseline.** That run did not produce a first token inside Cline's
  local 30-second Ollama request timeout, so its trace is empty. It is kept as an honest record, not
  scored as a model behavior. So the gpt-oss column shows the harness path working, not a within-model
  before-and-after. (Scoring the empty trace prints 0/100 across the board, the same all-zero shape any
  no-tool-call trace produces; the table marks it "(empty)" because the run never started, not because
  the model scored zero.)
- **The harness names `apply_patch` on purpose, which is a confound worth stating.** It is a general
  tool-format harness, but it does steer toward the exact tool the diff scorers grade. That is the
  point (the scorers grade `apply_patch`; the default prompt does not teach it), but it means the
  delta measures "a tool-format harness", not "any prompt improvement".
- **The captured gpt-oss:20b harnessed run used an earlier version of the harness whose worked example
  was the task's own answer** (a patch adding `sub` to `calc.py`). So that run's 100/100 is partly
  demonstrated-answer copying, not purely general grammar competence. The shipped specimen here has
  since been changed to a neutral example (`greeter.py`), so a fresh capture would be a cleaner test;
  the committed gpt-oss trace should be read as "the harness path can work end to end", not as a clean
  measure of general apply_patch skill. The qwen result is unaffected, because qwen never emitted a
  real tool call either way.
- **Granite's zero delta is partly a scorer-coverage limit, not a task failure.** Harnessed, Granite
  edited `calc.py` correctly, just via the `editor` tool rather than `apply_patch`. Clinescope's three
  diff scorers grade `apply_patch` grammar only, so they abstain on an `editor` edit and the run scores
  `0` and `n/a` even though the file was edited right. A `write_to_file` / `replace_in_file` / `editor`
  diff-grammar scorer is a stated roadmap item, and the Granite result is a second, independent nudge
  toward it.
- **"Curated corpus" is the community member's framing, not a claim from the model card.** The Granite
  card describes its curated data as one of three supervised-finetuning sources (public, synthetic, and
  a select human-curated set) and credits tool calling to post-training (finetuning plus reinforcement
  learning), not to corpus curation. What the card does support for the `granite4.1:8b` variant is that
  it is a dense classical transformer with a high instruction-following score, which is consistent with
  what we saw: it follows instructions well enough to use a real edit tool, but not to override its
  preference for the tool that already works.
- **A preflight self-check would be a stronger upstream fix than a post-hoc auditor**: a model that
  checks "can I name a valid tool call for each step?" before the run rather than after it. That is an
  upstream Cline idea, not a Clinescope feature, and it is out of scope here.

## Reproduce the scoring

```bash
clinescope examples/harness-gap/qwen-harness.messages.json --expected read_files apply_patch --advice
clinescope examples/harness-gap/granite-harness.messages.json --expected read_files apply_patch
clinescope examples/harness-gap/gptoss-harness.messages.json --expected read_files apply_patch
```

The six traces and their expected scores are pinned by `tests/test_harness_gap_capture.py`. See
[`examples/harness-gap/README.md`](../examples/harness-gap/README.md) for the full layout.
