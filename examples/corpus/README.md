# Validation corpus

Real captured Cline runs that pin clinescope's behaviour to ground truth. Each trace here is a genuine Cline World-A `messages.json` (v1) from a local run against an Ollama model -- not authored, not synthetic. `corpus.json` hand-labels every trace with its expected per-scorer cell, its failure taxonomy, and the evidence its advice must name. The runner scores every trace and asserts clinescope reproduces each label, exiting non-zero on any mismatch:

```bash
python -m clinescope.corpus
```

The traces are declared real captures of local Cline runs, and the runner asserts
every labelled cell on each one, so a change that stops clinescope catching one of
these failures, or makes it flag a clean run, fails the corpus. What the suite cannot
check is the declaration itself: a trace written by hand and declared real would
pass. [Provenance](#provenance) below says what each item records about its capture
and what checking that proves.

## What kind of eval this is

Every row here is a **regression case**. The system under test is clinescope itself: its scorers
and its advice. The Cline agent is not under test.

Agent evals come in two kinds, and they read the same score in opposite ways. A capability eval asks
whether a system can do something it may not manage yet, so it starts at a low pass rate and leaves
room to climb. A regression eval asks whether a change broke something that already worked, so it
should sit at or near 100 percent. The kind is written down here, before any score is read, because
100 percent means "healthy" for one kind and "no longer measuring anything" for the other.

Take `live-gpt-oss-apply-fail.json`. Its label says `apply_recovery` scores `0/100` and the advice
names `no_apply_recovery`. If a change to clinescope makes that row score `100/100`, clinescope
regressed: it stopped catching a failure it used to catch. The three clean rows guard the other
direction. If clinescope starts giving advice on one of them, it started flagging a good run.

**6/6 is the expected state, and it is not evidence of detection power.** A regression set at 100
percent is doing its job. What 6/6 shows is narrow: clinescope reproduces labels the author wrote, on
6 traces the author captured. It says nothing about how often clinescope catches a failure on a trace
it has not seen, nothing about users, and nothing about what the Cline agent can do.

**No capability eval exists here, of clinescope or of the Cline agent.**

- *Not of Cline.* The rows are frozen traces. clinescope reads a finished session and cannot re-run
  an agent, so there is no trial loop and no Cline pass rate to measure. Each trace records what
  Cline did once, on a task chosen to exercise clinescope's scorers, not to measure Cline. Calling these rows capability or
  regression cases for Cline would be a category error. A real capability eval of Cline would need a
  trial runner, which this project does not have and nobody has asked for.
- *Not of clinescope.* `tests/test_corpus.py::test_corpus_asserts_a_failing_editor_cell` is the one
  corpus check that is an expected failure today, so it can look like a capability case. It is not
  one. It waits on evidence, not on clinescope getting better: the scorer already catches an
  unrecovered `editor` failure in unit tests. What is missing is a real Cline session that fails an
  `editor` call without recovering. That row lands together with a small runner change, because
  `_SCORER_COLUMNS` in `src/clinescope/corpus.py` does not compare an `editor_recovery` cell yet.
  With both in place the test is a strict expected failure that passes, so it goes red and its
  marker has to come off. It marks a coverage gap, described
  under [Known gap: `no_editor_recovery`](#known-gap-no_editor_recovery-is-not-yet-covered-by-a-real-trace)
  below.

**Why this is written here and not as a field in `corpus.json`.** A per-row field was considered and
not added. Every row would carry the same value, the runner would ignore it as it ignores the
provenance fields, and a test pinning it could only change on the day a capability case exists. A
field that holds one value on every row is documentation shaped like data, so it stays
documentation. If a capability case is ever added, that is when a per-row field starts to carry
information.

**Why "regression set" and not "regression suite".** In this repository "suite" means the pytest
suite under `tests/`, as it does throughout `docs/internal/`. Calling the corpus a set keeps the two
apart, and keeps `"kind": "failing"` on a row reading as "a real failure clinescope must catch",
never as a broken test.

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

## Provenance

Every item in `corpus.json` records three facts about its capture. `clinescope-corpus` does not read
them. `tests/test_corpus.py::test_every_item_declares_provenance` checks that all six items carry all
three, and that the first two equal the trace file's own fields.

| Field | Where the value came from |
|---|---|
| `session_id` | The trace's own `sessionId`, copied exactly. |
| `captured_at` | The trace's own `updated_at`, copied exactly. |
| `cline_version` | Nowhere. It is `"unknown"` on all six, for the reason below. |

**`captured_at` is when the session was last saved, not when it started.** Cline rewrites `updated_at`
each time it saves the messages file. In all six traces it lands within 25 milliseconds of the last
message, and 7 to 95 seconds after the session began. Two other dates were considered and not used. The
digits before the underscore in a session id are the start time in epoch milliseconds, but that is a
detail of how Cline builds the id, a caller can supply its own, and a date read out of `session_id`
would repeat what the `session_id` check already covers. The date of the commit that added these files
(#40) records when a trace entered this repository: about 20 minutes after capture for the
`qwen2.5-coder:1.5b` and `llama3.1:8b` traces, and 28 to 32 hours after for the four `gpt-oss:20b`
traces.

**`cline_version` is `"unknown"`, written down rather than guessed.** No trace records it. The
`"version": 1` inside each trace is the version of the messages file format, not of Cline. None of the
six sessions is still in the author's local Cline session store, and no commit message or note from
July 2026 names the Cline version that ran them. An explicit unknown is different from a missing field:
it records that the question was asked and had no answer. The `no_editor_recovery` runs below do name
their version, because it was written down on the day they ran.

**What the check proves, and what it does not.** When `session_id` and `captured_at` match, the manifest
item and the trace file under its key name the same Cline session and the same last save. That catches a
trace file swapped for a different capture, or for a later save of the same session, while its manifest
entry stays the same. It does not prove the trace is a real capture: any file can carry any `sessionId`
and `updated_at`, and the original sessions are gone, so nothing outside this repository is left to
compare against. It does not prove the messages are unedited either: a change that leaves both fields
alone still passes. Whether a trace is real still rests on its `source` field and on whoever declared it,
as it did before these fields existed.

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
