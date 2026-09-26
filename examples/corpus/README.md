# Validation corpus

Real captured Cline runs that pin clinescope's behaviour to ground truth. Each trace here is a genuine Cline World-A `messages.json` (v1) from a local run against an Ollama model -- not authored, not synthetic. `corpus.json` hand-labels every trace with its expected per-scorer cell, its failure taxonomy, and the evidence its advice must name. The runner scores every trace and asserts clinescope reproduces each label, exiting non-zero on any mismatch:

```bash
python -m clinescope.corpus
```

This is clinescope's un-fakeable evidence layer: the traces are real, the failures
are real, and the runner proves clinescope catches each one (and stays quiet on
clean runs).

## Coverage

Six real traces cover three of the five failure modes in the taxonomy (`clinescope.advice.FailureLabel`):

| Failure mode | Covered? | Trace(s) |
|---|---|---|
| `missing_tools` | ✅ | `qwen-missing-tools.json`, `llama-code-dump.json` |
| `malformed_patch` | ✅ | `qwen-missing-tools.json`, `llama-code-dump.json` |
| `no_apply_recovery` | ✅ | `live-gpt-oss-apply-fail.json` |
| `blind_rewrite` | ❌ (stated gap) | -- see below |
| `no_editor_recovery` | ❌ (stated gap) | -- see below |

Plus three clean `gpt-oss:20b` runs (`live-gpt-oss-trace.json`,
`live-gpt-oss-add-file.json`, `live-gpt-oss-update-2hunk.json`) as the
false-positive check -- a corpus is only evidence if it also proves clinescope
does *not* cry wolf on a good run.

## Known gap: `blind_rewrite` is not yet covered by a real trace

`blind_rewrite` is the `diff_minimality` failure -- an `apply_patch` whose Update hunk deletes a whole block and retypes it wholesale instead of a surgical edit. It requires a trace that is **both** things at once:

1. a valid `apply_patch` (so `diff_coherence` passes and `diff_minimality` applies), and
2. bloated enough that a hunk is a blind whole-block rewrite.

In the 2026-07-12 sweep, no local Ollama model in the tested set produced such a trace. Each failed at
a different stage:

- Weak coders (`qwen2.5-coder:1.5b`, `llama3.1:8b`) fail at the tool-call stage -- they hallucinate a JSON tool or dump plain-text code and never emit a real Cline `apply_patch`, so their patches are `malformed_patch`, never valid-but-bloated.
- `qwen2.5-coder:7b` emits a hallucinated JSON tool blob (`{"name":
  "apply_patch", ...}`) rather than Cline's `*** Begin Patch` envelope -- again a tool-call-stage failure, not a patch-quality one.
- `gpt-oss:20b` does emit valid patches and, when asked to rewrite a whole function, reasons out the whole-block rewrite in its thinking -- but stalls before emitting the `apply_patch` tool call, so no valid bloated patch lands in the trace.
- `deepseek-coder-v2:16b` rejects tool use entirely (`does not support tools`).

**That conclusion was overturned on 2026-08-20, and the reason the mode is still uncovered has changed.**
The sweep above asked models to rewrite a whole function, which put the shape in the instruction. Given
an ordinary one-line task instead, `gpt-oss:20b` emitted a valid `apply_patch` that scored 0.0 and failed
`clinescope-gate --min-diff-minimality 0.75` with exit 1. So a local model can produce this, and no
stronger hosted model is required. What it took is written up in
[`LIMITATIONS.md`](../../LIMITATIONS.md).

That trace is deliberately **not** shipped here. The task was built to make the shape likely, two of four
runs were discarded because the model's tool call failed to parse, and the target file was widened by one
line after watching the model's behaviour on the narrower version. It would be evidence that the scorer
fires, not evidence about how often agents do this, and those are different claims. So the corpus still
ships 6 real / 0 authored traces covering 3 of 5 modes, and `blind_rewrite` stays an honestly-stated gap
rather than a number rounded up with a trace hunted until it fired. The `diff_minimality` scorer and its
`blind_rewrite` advice remain exercised by the unit tests (`tests/test_diff_minimality.py`) against
authored patch bodies.

## Known gap: `no_editor_recovery` is not yet covered by a real trace

`no_editor_recovery` is the `editor_recovery` failure: an `editor` call Cline marked failed, with no
strictly-later `editor` call Cline confirmed non-failing on the same path. A corpus row for it needs a
real Cline session in which that happens on an ordinary editing task.

On 2026-09-27 five ordinary tasks were written down before any run, together with the rule for
stopping: stop at the first run whose `editor_recovery` scores below 100/100, and if none does, stop
after the fifth. Each task ran once on `granite4.1:8b` (Cline CLI 3.0.65, Ollama, act mode, launched
from PowerShell, no `--timeout`) against the same small Python file, restored before every run.

| Task | Failed `editor` calls | Recovered |
|---|---|---|
| Add a docstring to every function | 1 | 1 |
| Rename a function and update every caller | 1 | 1 |
| Make a function raise `ValueError` on a bad argument | 1 | 1 |
| Add type hints to every function | 3 | 3 |
| Add a new function | 1 | 1 |

Every run scored `editor_recovery 100/100`. Six of the seven failures were the same one: an `editor`
call that left out `old_text` on a file that already existed, which Cline rejected with an error
naming the missing field. The seventh was a replacement whose `old_text` was not in the file. Every
failure was followed by a confirmed `editor` call on the same path. The two `editor` traces already
committed here show the same pattern: `examples/live-granite-editor-recovery.json` recovers 1 of 1
failed call and `examples/harness-gap/granite-harness.messages.json` recovers 2 of 2.

"Recovered" is the scorer's trajectory pattern, not a working file, and the first run shows the gap
between the two. Its confirmed call replaced the whole file with one line carrying 78 literal `\n`
sequences, which Python rejects with a syntax error on line 1, and the scorer still counts that
failure as recovered, exactly as its caveat in `LIMITATIONS.md` says it will.

So on ordinary tasks with this model, the failure the scorer looks for did not happen. That is a
finding about one local model on one small file. It is not a claim that agents always recover.

No trace ships for this mode. A sixth run, a longer task list chosen after seeing these five, or a task
shaped to make an edit fail would be the hunting the `blind_rewrite` section above describes: evidence
that the scorer fires, not evidence about how often agents give up. The scorer's unrecovered path stays
exercised by unit tests against authored traces (`tests/test_editor_recovery.py`,
`tests/test_editor_recovery_report.py`). `tests/test_corpus.py::test_corpus_asserts_a_failing_editor_cell`
holds the check a real row would have to pass. It is a strict expected failure until that row exists,
so the day one lands it turns red and its marker has to come off.
