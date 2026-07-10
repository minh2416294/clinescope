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
- [ ] **Detects task completion** — did the run actually finish the job?
- [ ] **Validates its own LLM judge** against human labels, so a score you can trust.
- [ ] **Gates CI** — fail the build when an agent version regresses.

## Why it's different

General eval tools — deepeval, promptfoo, Langfuse — score **prompt and output**: did the model's text answer meet an assertion. clinescope scores the **whole coding run**: which tools the agent chose across a task, whether it finished, and whether the diff it produced was coherent and minimal. That trajectory-and-diff layer is exactly what those tools leave to *"write your own custom scorer."*

**The bet:** the diff a coding agent produces — not just whether the tests went green — is the signal that actually tells you if the run was good. Almost nobody scores it. That's why clinescope exists.

Two slices of that scorer ship today, both deterministic and zero-LLM, both read from the trace text alone:

**Diff coherence** grades the agent's patch against Cline's *real* `apply_patch` grammar (the `*** Begin Patch` / `*** Update File:` / `@@` envelope) — is it well-formed, or a malformed patch that would fail to apply? (Honesty caveat: this scores grammatical coherence, **not** whether the patch's context actually matches your on-disk file — that fuzzy match needs the repo Cline ran against, which a standalone trace doesn't carry.)

**Diff minimality** asks one narrow question about the patch's *shape*: does each edited region keep an anchor, or is it a *blind whole-block rewrite* — delete N lines, retype N lines, keeping nothing (`N ≥ 3`)? It reports the fraction of Update hunks that are **not** blind rewrites. (Honesty caveat — read this: it detects exactly **one** bloat shape and is deliberately **blind** to the other, more common one, dragging large unchanged context. It does *not* threshold on context count, because context is what `apply_patch` needs to anchor a hunk — penalizing it would invert the metric on well-formed patches. A low score means "contains a large rewrite" (which may be *necessary* — read it as *large-block*, not *wasteful*); a high score means "no blind rewrite," **not** "minimal." There is no reference or ideal patch to compare against — a standalone trace carries neither — so this is a structural property of the patch text, never churn-vs-an-ideal.)

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
```

`context_density` is descriptive only — it is reported so you can eyeball how much unchanged context the
patch drags, but it never enters the `diff_minimality` score. A `score: n/a` with `applicable: False` means
the trace had no `apply_patch` call at all, so there was no patch shape to check (the golden fixture is one
such trace).

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
2. **Score** — three deterministic, zero-LLM scorers today: `clinescope.tool_selection` computes expected-recall against the caller's expected-tool set, `clinescope.diff_coherence` grades the `apply_patch` patch text against Cline's real grammar, and `clinescope.diff_minimality` flags blind whole-block rewrites in that patch. Each returns its score plus evidence (matched/missing tools; passed/failed gates + violations; blind-rewrite-hunk count + a descriptive context-density number).
3. **Emit** (`clinescope.report` + `clinescope.__main__`) render the scores and evidence as a stable plain-text report; the CLI is thin glue over a pure `render_report(...) -> str`.

## Roadmap

- [x] World-A trace loader (version-gated, tool-call join, surfaces unmodeled items)
- [x] Tool-selection correctness scorer (name-based recall)
- [x] Plain-text report emitter + CLI, runs on Cline's golden fixture
- [x] **Diff-coherence scorer** — grades the `apply_patch` patch against Cline's real grammar, on two structurally-different real-format traces (Add File; multi-hunk Update + Move + Delete) — the wedge, first slice
- [x] **Diff-minimality scorer** — flags blind whole-block rewrites (delete ≥3 / retype ≥3) in the `apply_patch` patch, on the same real-format traces — the wedge, second slice
- [ ] Apply-recovery scorer (did a failed `apply_patch` get retried and fixed?) — the rest of the diff-quality wedge
- [ ] Task-completion detection (successful `submit_and_exit`)
- [ ] LLM-judge validation with chance-corrected agreement (Cohen's κ) against human labels
- [ ] CI-gateable pass/fail on a seeded regression

## Contributing

Small, discussed-first changes are welcome, see [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, how to run the tests and linters, and what a scorer change needs (a fixture trace + its expected score).

## License

[Apache-2.0](LICENSE). Copyright 2026 Tran Binh Minh.
