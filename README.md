# Clinescope

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg?style=flat-square)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg?style=flat-square)
![Coverage 93%](https://img.shields.io/badge/coverage-93%25-brightgreen.svg?style=flat-square)

> Clinescope is an independent, unofficial tool - not affiliated with, endorsed by, or sponsored by Cline or Cline Bot Inc. "Cline" is a trademark of Cline Bot Inc., used only to describe compatibility.

Clinescope is an AI evaluation tool that lives in your Cline development workflow, reads your logs, and helps you write better prompts by checking tool choices, catching messy code rewrites, and ensuring updates don't break past work. Clinescope reads a Cline log and scores four things:

- **`tool_selection`**: did the agent call the tools the task needed?
- **`diff_coherence`**: are its code patches valid and well-formed?
- **`diff_minimality`**: are its edits small and focused, not bloated rewrites?
- **`apply_recovery`**: when a patch failed, did the agent fix it?

<p align="center"><img src="https://raw.githubusercontent.com/minh2416294/clinescope/main/docs/demo.png" alt="clinescope scoring a failing Cline run and, with --advice, coaching how to fix the agent's prompt for each failing scorer" width="640"></p>

## Why Clinescope

Clinescope scores **coding-agent execution traces** and ships a **code-diff-quality scorer**. DeepEval scores tool selection but not code patches or diffs; promptfoo, Langfuse, and Braintrust hand the diff scorer to you; UK AISI's Inspect runs SWE agents but ships no diff-quality scorer. Clinescope's `diff_coherence` / `diff_minimality` / `apply_recovery` scorers are that layer, run against real captured Cline traces (see the [validation corpus](#validation-corpus)).

Clinescope validates its own optional LLM judge against human labels and, finding it agrees only at chance level, deliberately keeps it out of the pass/fail gate. See [`docs/judge-validation.md`](docs/judge-validation.md).

## Get Started

1. **Install Clinescope**

    Requires Python 3.11+. Installing into a virtual environment is recommended.

    ```bash
    pip install clinescope
    ```

2. **Use Clinescope**

    **Get the score:**

    Point Clinescope at a Cline log file (a `messages.json` trace) to score the run - replace `path/to/messages.json` below with your own.

    ```bash
    clinescope path/to/messages.json --expected read_files apply_patch
    ```

    After `--expected`, list the tools you think the task needed. Run `clinescope --list-tools` to print the tools in Clinescope.

    **Improve your prompt:**

    ```bash
    clinescope path/to/messages.json --expected read_files apply_patch --advice
    ```

Learn more in the [usage guide](docs/usage.md).

New to this? The [quickstart](docs/quickstart.md) walks you from installing Cline to scoring your own session.

## Validation Corpus

Clinescope ships a corpus of **real captured Cline runs** in [`examples/corpus/`](examples/corpus/), each hand-labeled in [`corpus.json`](examples/corpus/corpus.json) with its expected score profile, failure taxonomy, and the evidence its advice should name. The runner scores every trace and exits non-zero if any trace misses its label, so the corpus is a regression gate.

**See Clinescope corpus:**

```bash
clinescope-corpus
```

See coverage, the failure taxonomy, and the one honestly-stated gap in [`examples/corpus/README.md`](examples/corpus/README.md).

## Feedback

Ran Clinescope on your own Cline trace? Tell me how it went, what worked, or what was confusing: open a [feedback issue](https://github.com/minh2416294/clinescope/issues/new/choose) and pick "Share feedback". First-run impressions on a real trace are the single most useful thing you can send.

For a reproducible scorer or CLI bug, the [Bug report](https://github.com/minh2416294/clinescope/issues/new/choose) form is a better fit. To contribute a change, see [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, tests, and what a scorer change needs.

## License

[Apache-2.0](LICENSE). Copyright 2026 Tran Binh Minh.
