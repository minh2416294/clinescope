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
- [ ] **Scores diff quality** — is the patch the agent produced coherent and minimal, or a sprawling mess? *(the wedge — see [Why it's different](#why-its-different))*
- [ ] **Detects task completion** — did the run actually finish the job?
- [ ] **Validates its own LLM judge** against human labels, so a score you can trust.
- [ ] **Gates CI** — fail the build when an agent version regresses.

## Why it's different

General eval tools — deepeval, promptfoo, Langfuse — score **prompt and output**: did the model's text answer meet an assertion. clinescope scores the **whole coding run**: which tools the agent chose across a task, whether it finished, and whether the diff it produced was coherent and minimal. That trajectory-and-diff layer is exactly what those tools leave to *"write your own custom scorer."*

**The bet:** the diff a coding agent produces — not just whether the tests went green — is the signal that actually tells you if the run was good. Almost nobody scores it. That's why clinescope exists.

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
```

Ask for a tool the trace didn't use and the score drops, with the gap shown:

```bash
python -m clinescope examples/sample-trace.json --expected read_files apply_patch write_file
# score: 0.6667 ... missing: write_file
```

## How it works

Three stages, one thin path: **load → score → emit**:

1. **Load** (`clinescope.world_a`) parse the World-A trace into typed turns and a flat list of tool calls, each joined to its result.
2. **Score** (`clinescope.tool_selection`) compute expected-recall against the caller's expected-tool set, returning the score plus the matched / missing / unexpected sets as evidence.
3. **Emit** (`clinescope.report` + `clinescope.__main__`) render the score and evidence as a stable plain-text report; the CLI is thin glue over a pure `render_report(...) -> str`.

## Roadmap

- [x] World-A trace loader (version-gated, tool-call join, surfaces unmodeled items)
- [x] Tool-selection correctness scorer (name-based recall)
- [x] Plain-text report emitter + CLI, runs on Cline's golden fixture
- [ ] **Code-diff-quality scorer** — diff coherence / minimal-diff / apply-recovery on a real diff-bearing trace (the wedge)
- [ ] Task-completion detection (successful `submit_and_exit`)
- [ ] LLM-judge validation with chance-corrected agreement (Cohen's κ) against human labels
- [ ] CI-gateable pass/fail on a seeded regression

## Contributing

Small, discussed-first changes are welcome, see [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, how to run the tests and linters, and what a scorer change needs (a fixture trace + its expected score).

## License

[Apache-2.0](LICENSE). Copyright 2026 Tran Binh Minh.
