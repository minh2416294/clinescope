# Validation corpus

Real captured Cline runs that pin clinescope's behaviour to ground truth. Each
trace here is a genuine Cline World-A `messages.json` (v1) from a local run against
an Ollama model — not authored, not synthetic. `corpus.json` hand-labels every
trace with its expected per-scorer cell, its failure taxonomy, and the evidence its
advice must name. The runner scores every trace and asserts clinescope reproduces
each label, exiting non-zero on any mismatch:

```bash
python -m clinescope.corpus
```

This is clinescope's un-fakeable evidence layer: the traces are real, the failures
are real, and the runner proves clinescope catches each one (and stays quiet on
clean runs).

## Coverage

Six real traces cover **three of the four** failure modes in the taxonomy
(`clinescope.advice.FailureLabel`):

| Failure mode | Covered? | Trace(s) |
|---|---|---|
| `missing_tools` | ✅ | `qwen-missing-tools.json`, `llama-code-dump.json` |
| `malformed_patch` | ✅ | `qwen-missing-tools.json`, `llama-code-dump.json` |
| `no_apply_recovery` | ✅ | `live-gpt-oss-apply-fail.json` |
| `blind_rewrite` | ❌ (stated gap) | — see below |

Plus three clean `gpt-oss:20b` runs (`live-gpt-oss-trace.json`,
`live-gpt-oss-add-file.json`, `live-gpt-oss-update-2hunk.json`) as the
false-positive check — a corpus is only evidence if it also proves clinescope
does *not* cry wolf on a good run.

## Known gap: `blind_rewrite` is not yet covered by a real trace

`blind_rewrite` is the `diff_minimality` failure — an `apply_patch` whose Update
hunk deletes a whole block and retypes it wholesale instead of a surgical edit. It
requires a trace that is **both** things at once:

1. a **valid** `apply_patch` (so `diff_coherence` passes and `diff_minimality`
   applies), **and**
2. **bloated** enough that a hunk is a blind whole-block rewrite.

No local Ollama model in the tested set produced such a trace:

- **Weak coders** (`qwen2.5-coder:1.5b`, `llama3.1:8b`) fail at the tool-call stage
  — they hallucinate a JSON tool or dump plain-text code and never emit a real Cline
  `apply_patch`, so their patches are `malformed_patch`, never valid-but-bloated.
- **`qwen2.5-coder:7b`** emits a hallucinated JSON tool blob (`{"name":
  "apply_patch", ...}`) rather than Cline's `*** Begin Patch` envelope — again a
  tool-call-stage failure, not a patch-quality one.
- **`gpt-oss:20b`** *does* emit valid patches and, when asked to rewrite a whole
  function, reasons out the whole-block rewrite in its thinking — but stalls before
  emitting the `apply_patch` tool call, so no valid bloated patch lands in the trace.
- **`deepseek-coder-v2:16b`** rejects tool use entirely (`does not support tools`).

So the corpus honestly ships **6 real / 0 authored** traces covering 3 of 4 modes.
`blind_rewrite` is left as a **stated gap rather than filled with an authored
trace** — coverage of modes with real evidence is worth more than a round number
with a synthetic. Capturing it needs a model that reliably emits a
valid-but-bloated Cline patch (a stronger hosted model, or a local model that both
emits real tool calls and over-rewrites). The `diff_minimality` scorer and its
`blind_rewrite` advice are still exercised by the unit tests
(`tests/test_diff_minimality.py`) against authored patch bodies; what is missing is
a *real captured trace* of the mode, which is what this corpus is for.
