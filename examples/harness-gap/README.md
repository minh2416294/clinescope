# Harness-gap experiment

This folder holds a small A/B experiment: the same coding task, run on the same model,
once WITHOUT a `.clinerules` harness and once WITH one, so the per-scorer difference
measures how much of a failure a prompt-side harness can prevent (the "harness gap") versus
how much is a genuine model-capability ceiling.

The experiment, and the "is this a model gap or a harness gap?" framing behind it, came from
Cline community feedback. The full writeup is in [`docs/harness-gap.md`](../../docs/harness-gap.md).

## The harness

[`clinerules/000-tool-format.md`](clinerules/000-tool-format.md) is the specimen `.clinerules`
file used in the "with harness" runs. It forces the model to edit via `apply_patch`, teaches
the exact `*** Begin Patch` grammar with one worked example (verified to score `diff_coherence`
1.0), steers toward minimal anchored edits, and adds a "verify the file changed after
apply_patch" rule. It is a general tool-format harness; its worked example is illustrative
(`greeter.py`), not the answer to this experiment's task.

Note: the committed gpt-oss harnessed trace below was captured with an earlier version of this
file whose worked example WAS the task's answer (a `sub`/`calc.py` patch), so that run's 100/100
is partly demonstrated-answer copying. The example has since been changed to a neutral one; a
fresh capture would be a cleaner test. The qwen result is unaffected (it never emitted a real
tool call). See the caveats in [`docs/harness-gap.md`](../../docs/harness-gap.md).

It is a SPECIMEN, not an active harness for this repo. To use it, copy it into a Cline
workspace at `.clinerules/000-tool-format.md` (it loads first because rules are sorted by name).

## The task

The same prompt in all runs: "Add a function sub(a, b) that returns a - b to calc.py. Edit the
file using your tools." Each workspace started from an identical `calc.py` containing only
`add`.

## The six captures

All six are real Cline CLI (World-A) traces, scored with `read_files apply_patch` as the
expected tools.

| Trace | Model | Harness | tool_selection | diff_coherence | diff_minimality | apply_recovery |
|---|---|---|---|---|---|---|
| `qwen-bare.messages.json` | qwen2.5-coder:7b | no | 0/100 | 0/100 | n/a | n/a |
| `qwen-harness.messages.json` | qwen2.5-coder:7b | yes | 0/100 | 0/100 | n/a | n/a |
| `granite-bare.messages.json` | granite4.1:8b | no | 50/100 | 0/100 | n/a | n/a |
| `granite-harness.messages.json` | granite4.1:8b | yes | 50/100 | 0/100 | n/a | n/a |
| `gptoss-bare.messages.json` | gpt-oss:20b | no | (empty, see note) | (empty) | (empty) | (empty) |
| `gptoss-harness.messages.json` | gpt-oss:20b | yes | 100/100 | 100/100 | 100/100 | n/a |

What each shows:

- qwen bare: the model chose Cline's default `editor` tool and wrote it as JSON in prose;
  Cline recorded zero real tool calls, so every scorer reports the gap.
- qwen harness: the harness moved the model's tool CHOICE from `editor` to `apply_patch`
  (its prose now names `apply_patch`), but the model still could not emit a real tool call, so
  the scores stay at zero. The harness shifted intent; it could not add tool-calling ability.
  This is the model-capability ceiling.
- granite bare: unlike qwen, Granite emitted a real `read_files` tool call (not prose JSON),
  then returned an empty response before editing. It clears qwen's "can it emit any tool call"
  bar but stalls on the edit. `tool_selection` is 50/100 (it matched `read_files`, never
  `apply_patch`); the diff scorers report the missing `apply_patch`.
- granite harness: Granite made six real tool calls (`read_files`, `run_commands`,
  `read_files`, `editor`, `editor`, `editor`) and edited the file correctly, but it used Cline's
  default `editor` tool instead of `apply_patch`, despite the harness forcing `apply_patch`. So
  the diff scorers still read 0/n-a: they grade `apply_patch` grammar only, and Granite edited
  via `editor`. The zero delta vs bare is real, but for a different reason than qwen: qwen could
  not emit a tool call at all, while Granite emits tool calls and succeeds but keeps its own tool
  preference over the rules file. See the caveats in [`docs/harness-gap.md`](../../docs/harness-gap.md).
- gpt-oss bare: the model did not produce a first token inside Cline's local 30s Ollama
  request timeout, so the assistant turn is empty. This is an infra timeout, not a model
  behavior; it is kept as an honest record, and there is no fair bare baseline for gpt-oss.
- gpt-oss harness: the model made real tool calls (`search_codebase`, `read_files`,
  `run_commands`, `apply_patch`), emitted a grammar-valid `*** Begin Patch` that succeeded,
  and actually edited the file. A clean 100/100/100: the harness path working end to end on a
  capable model.

## Reproduce the scoring

```bash
clinescope examples/harness-gap/qwen-harness.messages.json --expected read_files apply_patch --advice
```

The six traces are pinned by `tests/test_harness_gap_capture.py` (skipif-gated on their
presence), so the measured scores are regression-guarded.
