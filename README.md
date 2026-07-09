# clinescope

**A Cline eval harness  it scores the quality of a coding agent's diff and tool-trajectory from a real Cline execution trace.**

> **clinescope is an independent, unofficial tool. It is not affiliated with, endorsed by, or sponsored by Cline or Cline Bot Inc. "Cline" is a trademark of Cline Bot Inc., used here only to describe compatibility, clinescope reads the trace format Cline produces.**

[![CI](https://github.com/minh2416294/clinescope/actions/workflows/ci.yml/badge.svg)](https://github.com/minh2416294/clinescope/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)

**Status:** walking skeleton, runs end-to-end. It loads a Cline World-A `messages.json` trace, scores tool selection, and emits a report against Cline's golden fixture. The code-diff-quality scorer, the reason this exists, is next.

## What it does

- Loads a Cline **World-A `messages.json` v1** trace: normalizes turns, joins each tool call to its result on `tool_use_id`, and version-gates the format (fails loud on an unsupported version).
- Scores **tool-selection correctness**, did the agent call the tools the task expected?, as name-based recall over the trace.
- Emits a **plain-text scored report** you can read or diff in CI.
- Surfaces what it can't model instead of dropping it: unmodeled content items are collected on the trace, never silently discarded.
- Reads the trace **read-only**, it never writes to or mutates the file it scores.

## Why it's different

Tool-selection and diff quality on a *coding-agent trace* are not what general eval frameworks score. Tools like deepeval and promptfoo focus on **prompt/output** evals — did the model's text answer meet an assertion. clinescope scores the **trajectory and the diff**: which tools the agent chose over a whole task, and (next) whether the patch it produced is coherent and minimal. That's the layer those frameworks leave to "write your own custom scorer."

Under the hood the scoring engine is framework-agnostic; v1 ships with the Cline World-A adapter as the first and flagship adapter. Other adapters come later, only when a real second implementation exists.

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

Three stages, one thin path — **load → score → emit**:

1. **Load** (`clinescope.world_a`) — parse the World-A trace into typed turns and a flat list of tool calls, each joined to its result.
2. **Score** (`clinescope.tool_selection`) — compute expected-recall against the caller's expected-tool set, returning the score plus the matched / missing / unexpected sets as evidence.
3. **Emit** (`clinescope.report` + `clinescope.__main__`) — render the score and evidence as a stable plain-text report; the CLI is thin glue over a pure `render_report(...) -> str`.

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
