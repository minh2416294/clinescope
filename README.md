# clinescope

**clinescope is a test suite for your Cline coding agent.** It scores how well an agent did a coding task — the tools it chose, whether it finished, and whether the diff it produced was any good — straight from the `messages.json` trace Cline already writes. No instrumentation, no rerun.

*Today, judging an agent's coding run means eyeballing the diff and re-reading the trace by hand. Tests passing tells you the code ran — not whether the change was good.*

> **clinescope is an independent, unofficial tool. It is not affiliated with, endorsed by, or sponsored by Cline or Cline Bot Inc. "Cline" is a trademark of Cline Bot Inc., used here only to describe compatibility — clinescope reads the trace format Cline produces.**

[![CI](https://github.com/minh2416294/clinescope/actions/workflows/ci.yml/badge.svg)](https://github.com/minh2416294/clinescope/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)

## What it does

Point it at a Cline trace and it scores the run. `[x]` = works today · `[ ]` = on the [roadmap](#roadmap).

- [x] **Reads Cline's `messages.json` trace directly** — normalizes the run, joins each tool call to its result, fails loud on an unsupported version. Nothing to instrument.
- [x] **Scores tool selection** — did the agent call the tools the task needed? Reported as a recall score with the matched / missing / unexpected tools shown.
- [x] **Emits a plain-text report** you can read at a glance or diff in CI.
- [x] **Never touches your files** — reads the trace read-only, and surfaces anything it can't model instead of silently dropping it.
- [x] **Scores diff coherence** — does the patch the agent produced parse cleanly against Cline's real `apply_patch` grammar, or is it malformed? *(the wedge — see [Why it's different](#why-its-different))*
- [x] **Scores diff minimality** — flags one specific bloat shape: a *blind whole-block rewrite* (delete N lines, retype N lines, keeping no anchor) inside an Update hunk. *(second slice of the wedge — deliberately narrow; see the caveat below)*
- [x] **Scores apply-recovery** — when a patch *failed*, did the agent retry and land a confirmed fix on the same file? Scores the failure→recovery trajectory from the turn sequence. *(third slice of the wedge — the multi-turn dimension a single patch can't show)*
- [ ] **Detects task completion** — did the run actually finish the job?
- [ ] **Validates its own LLM judge** against human labels, so a score you can trust. *(no judge yet — but the chance-corrected agreement math it will report, Cohen's κ + a bootstrap CI, ships today as a standalone, tested module; see the [roadmap](#roadmap))*
- [ ] **Gates CI** — fail the build when an agent version regresses.

## Why it's different

General eval tools — deepeval, promptfoo, Langfuse — score **prompt and output**: did the model's text answer meet an assertion. clinescope scores the **whole coding run**: which tools the agent chose across a task, whether the diff it produced was coherent and minimal, and — when a patch failed — whether the agent recovered. That trajectory-and-diff layer is exactly what those tools leave to *"write your own custom scorer."*

**The bet:** the diff a coding agent produces — not just whether the tests went green — is the signal that actually tells you if the run was good. Almost nobody scores it. That's why clinescope exists.

Three slices of that scorer ship today, all deterministic and zero-LLM, all read from the trace alone:

**Diff coherence** grades the agent's patch against Cline's *real* `apply_patch` grammar (the `*** Begin Patch` / `*** Update File:` / `@@` envelope) — is it well-formed, or a malformed patch that would fail to apply? (Honesty caveat: this scores grammatical coherence, **not** whether the patch's context actually matches your on-disk file — that fuzzy match needs the repo Cline ran against, which a standalone trace doesn't carry.)

**Diff minimality** asks one narrow question about the patch's *shape*: does each edited region keep an anchor, or is it a *blind whole-block rewrite* — delete N lines, retype N lines, keeping nothing (`N ≥ 3`)? It reports the fraction of Update hunks that are **not** blind rewrites. (Honesty caveat — read this: it detects exactly **one** bloat shape and is deliberately **blind** to the other, more common one, dragging large unchanged context. It does *not* threshold on context count, because context is what `apply_patch` needs to anchor a hunk — penalizing it would invert the metric on well-formed patches. A low score means "contains a large rewrite" (which may be *necessary* — read it as *large-block*, not *wasteful*); a high score means "no blind rewrite," **not** "minimal." There is no reference or ideal patch to compare against — a standalone trace carries neither — so this is a structural property of the patch text, never churn-vs-an-ideal.)

**Apply-recovery** is the first *trajectory* scorer, not a single-patch one: of every `apply_patch` that failed, what fraction was later recovered — a strictly-later `apply_patch` that Cline **confirmed** applied and that re-touched the same file? It scores per failed *file* (a multi-file failure fixed on only one file scores 0.5), and surfaces `same_file_refail` so a brute-force "retry until one lands" is visible, not hidden behind a `1.0`. It reads the failure/success **verdict** as its oracle — the one scorer that does — with `is_error` authoritative when present, and a **secondary `"success"`-JSON oracle** for real Cline traces: a genuine `apply_patch` result carries no `is_error` field, encoding the outcome as `{…,"success":true/false}` inside the tool-result content, so the scorer reads that boolean to know whether a call failed or a retry landed. (Honesty caveat — read this: "recovered" means only that a later same-file patch **applied**, *not* that it fixed the defect (no repo to verify against). It is deliberately conservative: a retry with no readable verdict at all (neither `is_error` nor a `"success"` bool — a truncated trace) is **never** counted as recovery, so the number can't be inflated by cutting the log short. It is blind to cross-tool recovery: a failure fixed via `write_to_file` instead of `apply_patch` scores as *un*recovered — so a low score means "not recovered via a same-file confirmed apply_patch," not "not recovered." Paths are matched literally, no normalization.)

Under the hood the scoring engine is framework-agnostic; it ships with the Cline adapter as the first and flagship one. Other adapters come later — only when a real second implementation exists to justify the seam.

## Quickstart

Requires Python 3.11+.

```bash
git clone https://github.com/minh2416294/clinescope
cd clinescope
pip install -e .

# score the bundled example trace
python -m clinescope examples/sample-trace.json --expected read_files apply_patch
```

`--expected` takes the tool names the task should have used (space-separated). The score is recall: how many of those expected tools the trace actually used.

## Example output

```text
=== clinescope report ===
sessionId:      example-two-tool-01
trace.version:  1
turns:          5
tool_calls:     2

[tool_selection]
score:          1.0000
expected:       apply_patch, read_files
used:           apply_patch, read_files
matched:        apply_patch, read_files
missing:        -
unexpected:     -

[diff_coherence]
score:          1.0000
passed_gates:   add_files_all_plus, move_placement_valid, no_stray_triple_star, update_hunks_wellformed
failed_gates:   -
violations:     -
apply_patch_calls: 1
cline_is_error: False

[diff_minimality]
score:          1.0000
applicable:     True
blind_rewrite_hunks: 0
hunks_with_body: 2
context_density: 0.3333
add_file_lines: 0
violations:     -
apply_patch_calls: 1
cline_is_error: False

[apply_recovery]
score:          1.0000
applicable:     True
total_failed_pairs: 1
recovered_pairs: 1
unrecovered_pairs: 0
partially_recovered: 0
same_file_refail: 0
unverified_reattempts: 0
verdict_coverage: 1.0000
failed_files:   src/auth.py
unparseable_failed_calls: 0
violations:     -
apply_patch_calls: 2
cline_is_error: True
```

`context_density` is descriptive only — it is reported so you can eyeball how much unchanged context the
patch drags, but it never enters the `diff_minimality` score. A `score: n/a` with `applicable: False` means
the trace had no `apply_patch` call at all, so there was no patch shape to check (the golden fixture is one
such trace). `apply_recovery` also reports `score: n/a` with `applicable: False` when no `apply_patch` call
*failed* — a recovery rate is undefined when nothing needed recovering; `verdict_coverage` distinguishes a
genuinely clean run from a truncated trace whose verdicts were never joined.

A malformed patch — say an Add File whose lines are missing the `+` prefix — drops the
`diff_coherence` score and names the gate it failed, and a trace with no `apply_patch` call at all
scores `0.0` with `violations: no apply_patch tool call in trace` rather than silently passing.

Ask for a tool the trace didn't use and the score drops, with the gap shown:

```bash
python -m clinescope examples/sample-trace.json --expected read_files apply_patch write_file
# score: 0.6667 ... missing: write_file
```

## How it works

Three stages, one thin path: **load → score → emit**:

1. **Load** (`clinescope.world_a`) parse the World-A trace into typed turns and a flat list of tool calls, each joined to its result.
2. **Score** — four deterministic, zero-LLM scorers today: `clinescope.tool_selection` computes expected-recall against the caller's expected-tool set, `clinescope.diff_coherence` grades the `apply_patch` patch text against Cline's real grammar, `clinescope.diff_minimality` flags blind whole-block rewrites in that patch, and `clinescope.apply_recovery` scores the failure→retry trajectory (did a failed patch get a confirmed same-file fix later?). Each returns its score plus evidence (matched/missing tools; passed/failed gates + violations; blind-rewrite-hunk count; recovered/unrecovered failed-file pairs + refail count).
3. **Emit** (`clinescope.report` + `clinescope.__main__`) render the scores and evidence as a stable plain-text report; the CLI is thin glue over a pure `render_report(...) -> str`.

## Roadmap

- [x] World-A trace loader (version-gated, tool-call join, surfaces unmodeled items)
- [x] Tool-selection correctness scorer (name-based recall)
- [x] Plain-text report emitter + CLI, runs on Cline's golden fixture
- [x] **Diff-coherence scorer** — grades the `apply_patch` patch against Cline's real grammar, on two structurally-different real-format traces (Add File; multi-hunk Update + Move + Delete) — the wedge, first slice
- [x] **Diff-minimality scorer** — flags blind whole-block rewrites (delete ≥3 / retype ≥3) in the `apply_patch` patch, on the same real-format traces — the wedge, second slice
- [x] **Apply-recovery scorer** — of every failed `apply_patch`, the fraction later recovered by a confirmed same-file retry; scored per failed file — the wedge, third slice. Reads the failure/success verdict via `is_error` when present, and via a **secondary `"success"`-JSON oracle** for real Cline traces (whose results carry no `is_error` field).
- [x] **Validated on live captures** — all four scorers run on **four** traces captured from real Cline CLI runs against a local `gpt-oss:20b` model (`examples/live-gpt-oss-*.json`), across distinct shapes (single- and two-hunk Update, Add File, and a genuine `apply_patch` **failure**). The failure capture drives `apply_recovery` to a real numeric score (`0.0`, one failed file never recovered) via the `"success"`-JSON oracle — the first time the recovery scorer scores on live data, not just abstains. (Breadth honesty: still one local model on small edits; a second model would need a paid API key. A live failure→*recovery* trace — a real `success:false` then a same-file `success:true` retry that lands, scoring recovery `> 0` — is not yet captured: gpt-oss:20b either over-thinks past its turn budget before retrying, or Cline's fuzzy matcher applies the mis-anchored patch anyway. The recovery *numerator* stays proven by real-shape unit tests, not yet by a live end-to-end retry.)
- [x] **Golden-fixture drift guard** — a content check (sha256 + size) fails loudly if Cline's ingested `success.messages.json` changes upstream, and skips cleanly when the Cline checkout is absent (CI) — so a drifted ingest point can't silently pass.
- [ ] Task-completion detection (successful `submit_and_exit`)
- [~] **Cohen's κ agreement harness** (`clinescope.agreement.cohen_kappa`) — the chance-corrected agreement statistic + a seeded bootstrap 95% CI, hand-rolled zero-dependency, validated against published textbook κ values. This is the *stats* half of judge-validation; it is a standalone module and is **not yet wired to a judge or a gold set** (there is no LLM judge yet — the label lists it scores are the caller's).
- [~] **Gold-set format + loader + judge seam** (`gold/`, `clinescope.gold`, `clinescope.judge`) — the JSONL gold-set contract (`gold/README.md`), a loader that resolves each item's trace pointer to the same first `apply_patch` the scorer grades (failing loud on a missing trace, a mis-shaped patch, or a `patch_sha256` drift), and a `judge_diff_minimality(trace)` **stub** that raises `NotImplementedError`. This is the *seam* the judge slots into — **the judge itself is not built** and the shipped gold seed is deliberately **unlabeled** (real human labels come later).
- [ ] LLM-judge validation with chance-corrected agreement — feed the κ harness above a small human gold set vs. an LLM judge's labels, report judge↔human κ + CI
- [ ] CI-gateable pass/fail on a seeded regression

## Contributing

Small, discussed-first changes are welcome, see [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, how to run the tests and linters, and what a scorer change needs (a fixture trace + its expected score).

## License

[Apache-2.0](LICENSE). Copyright 2026 Tran Binh Minh.
