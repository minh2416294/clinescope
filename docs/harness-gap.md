# The harness gap

Clinescope catches a coding agent's failures after the fact. A fair question, raised by a Cline
community member, is whether those failures are the wrong thing to catch: if a run fails because
Cline's default prompt never told the model how to use its tools, then the real fix is upstream, in
the prompt, not in a post-hoc analyzer. They named it cleanly: is a given failure a **model gap** (a
capability limit an external auditor should catch) or a **harness gap** (something a better prompt
would have prevented)?

They also proposed the test: run the same task, same model, once without a `.clinerules` harness and
once with one; the difference between the two scores is the size of the harness gap. This page is that
experiment.

## What the harness is

The "with harness" runs add one file, [`examples/harness-gap/clinerules/000-tool-format.md`](../examples/harness-gap/clinerules/000-tool-format.md),
to the workspace's `.clinerules/`. It is short and general (a tool-format harness, not tuned to the
task). It does three things Cline's default prompt does not:

1. Tells the model to edit with `apply_patch` and not to answer in prose.
2. Teaches the exact `*** Begin Patch` grammar with one worked example (verified to score
   `diff_coherence` 1.0, so the harness teaches a format the scorer actually rewards).
3. Adds "change only the lines that change" and "verify the file changed after `apply_patch`" rules.

`apply_patch` matters because Clinescope's three diff scorers grade `apply_patch` grammar. Cline's
default edit tool for a local model is `editor` (a plain old-text to new-text replacement); it routes
to `apply_patch` only for OpenAI, Codex, and GPT models. So for a local model, getting onto the
`apply_patch` path at all is itself part of what the harness has to do.

## How it's measured

The same task in every run: "Add a function `sub(a, b)` that returns `a - b` to `calc.py`. Edit the
file using your tools." Each run starts from an identical `calc.py`. Every trace is a real Cline CLI
session, scored with `clinescope ... --expected read_files apply_patch`.

## The result

| Model | Harness | tool_selection | diff_coherence | diff_minimality | apply_recovery |
|---|---|---|---|---|---|
| qwen2.5-coder:7b | no | 0/100 | 0/100 | n/a | n/a |
| qwen2.5-coder:7b | yes | 0/100 | 0/100 | n/a | n/a |
| gpt-oss:20b | no | (empty, see note) | (empty) | (empty) | (empty) |
| gpt-oss:20b | yes | 100/100 | 100/100 | 100/100 | n/a |

On qwen2.5-coder:7b, the community member's exact recipe, the measured delta is **zero on all four
scorers**. But the scores hide the interesting part. Without the harness, qwen reached for the default
`editor` tool. With the harness, it reached for `apply_patch` instead: the harness moved the model's
tool choice. In both runs, though, qwen wrote the tool call as JSON inside its prose rather than
emitting a real tool call, so Cline recorded zero tool calls and every scorer stayed at zero.

That is the honest answer to their question, and it matches their own prediction: for a model this
size, the failure is a **model-capability ceiling**, not a harness gap. A rules file can change what a
model intends to do, but it cannot give a model the ability to emit a valid tool call it cannot emit.

The contrast case is the other half of the answer. gpt-oss:20b with the same harness made real tool
calls, emitted a grammar-valid `apply_patch` that succeeded, and actually edited the file: a clean
100/100/100. So a harness is necessary but not sufficient. It can put a **capable** model onto the
tool path an eval grades; it cannot manufacture tool-calling ability a weak model lacks.

## Honest caveats

- **This is one task per cell, not a benchmark.** It illustrates the mechanism (harness moves intent;
  capability sets the ceiling); it does not prove a population-level effect size. A larger task and
  model matrix is future work.
- **There is no fair gpt-oss:20b bare baseline.** That run did not produce a first token inside Cline's
  local 30-second Ollama request timeout, so its trace is empty. It is kept as an honest record, not
  scored as a model behavior. So the gpt-oss column shows the harness path working, not a within-model
  before-and-after.
- **The harness names `apply_patch` on purpose, which is a confound worth stating.** It is a general
  tool-format harness, but it does steer toward the exact tool the diff scorers grade. That is the
  point (the scorers grade `apply_patch`; the default prompt does not teach it), but it means the
  delta measures "a tool-format harness", not "any prompt improvement".
- **A preflight self-check would be the stronger upstream fix**, as the same community member noted: a
  model that checks "can I name a valid tool call for each step?" before the run, rather than an
  auditor after it. That is an upstream Cline idea, not a Clinescope feature, and it is out of scope
  here.

## Reproduce the scoring

```bash
clinescope examples/harness-gap/qwen-harness.messages.json --expected read_files apply_patch --advice
clinescope examples/harness-gap/gptoss-harness.messages.json --expected read_files apply_patch
```

The four traces and their expected scores are pinned by `tests/test_harness_gap_capture.py`. See
[`examples/harness-gap/README.md`](../examples/harness-gap/README.md) for the full layout.
