# Clinescope

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg?style=flat-square)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg?style=flat-square)

Clinescope is an AI evaluation tool that lives in your Cline development workflow, reads your logs, and helps you write better prompts by checking tool choices, catching messy code rewrites, and ensuring updates don't break past work.

Clinescope reads a Cline log and scores four things:

- **`tool_selection`**: did the agent call the tools the task needed?
- **`diff_coherence`**: are its code patches valid and well-formed?
- **`diff_minimality`**: are its edits small and focused, not bloated rewrites?
- **`apply_recovery`**: when a patch failed, did the agent fix it?

> Clinescope is an independent, unofficial tool - not affiliated with, endorsed by, or sponsored by Cline or Cline Bot Inc. "Cline" is a trademark of Cline Bot Inc., used only to describe compatibility.

<p align="center"><img src="docs/demo.png" alt="clinescope scoring a failing Cline run and, with --advice, coaching how to fix the agent's prompt for each failing scorer" width="640"></p>

## Why Clinescope (the wedge)

Most eval frameworks score chatbot Q&A. Clinescope scores **coding-agent execution traces** — and it
ships the one thing the incumbents leave to "write your own custom scorer": a **code-diff-quality
scorer**. DeepEval scores tool selection but not code patches or diffs; promptfoo, Langfuse, and
Braintrust hand the diff scorer to you; UK AISI's Inspect *runs* SWE agents but ships no diff-quality
scorer. Clinescope's `diff_coherence` / `diff_minimality` / `apply_recovery` scorers **are** that layer,
run against real captured Cline traces (see the [validation corpus](#validation-corpus)).

## Is the LLM judge any good? (judge validation)

An eval tool that uses an LLM to judge quality has to answer one question honestly: **does the judge
agree with a human?** Clinescope measures this the way a rigorous eval reader expects — chance-corrected
inter-rater agreement (**Cohen's κ**) between the LLM judge and a small **human-labeled** gold set, with
a bootstrap confidence interval. The result on the current gold set (a free local `gpt-oss:20b` judge vs.
26 blind human labels):

```
cohen_kappa:  0.2353    95% CI: [0.0000, 0.5229]    N = 26
confusion (rows = human, cols = judge):
  human WASTEFUL      →  2 agree / 8 missed
  human NOT-WASTEFUL  → 16 agree / 0 missed
```

Because **κ = 0.24 is below the 0.5 floor, the judge is deliberately treated as advisory-only and kept
*out* of the CI gate** — `clinescope-gate` fires only on the deterministic scorers, never on a judge that
measured near chance level. That negative result is the point: Clinescope gates on the signals it trusts
and, provably, not on the one it doesn't. Recompute it yourself with no model call:

```bash
python -m clinescope.judge_run --report-only   # reads the committed cache; prints κ + CI
```

*Honest caveats:* N is small so the CI is wide (its lower bound is literally 0), the judge is one free
local model on small edits, and a single-draw κ isn't reproducible to the digit (the model flips labels
run-to-run even at temperature 0). Robustness across models and a lifted N are on the roadmap — this
number is a floor, stated plainly, not a marketing figure.

## Get Started

1. **Install Clinescope**

    Requires Python 3.11+. Installing into a virtual environment is recommended.

    ```bash
    pip install "git+https://github.com/minh2416294/clinescope.git"
    ```

2. **Use Clinescope**

    **Get the score:**

    Point Clinescope at the Cline log file to score the run. The commands below use a
    bundled sample trace ([`examples/sample-trace.json`](examples/sample-trace.json)) so
    they run as-is after a `git clone` — swap in your own `messages.json` when you have one:
    ```bash
    clinescope examples/sample-trace.json --expected read_files apply_patch
    ```
    After `--expected`, list the tools you think the task needed. Clinescope checks whether the agent actually used them and scores the rest of the run automatically. Not sure which tool names to use? Run `clinescope --list-tools` to print the ones Clinescope knows.

    **Get full breakdown of every scorer:**
    ```bash
    clinescope examples/sample-trace.json --expected read_files apply_patch --verbose
    ```

    **Get advice to improve prompting:**
    ```bash
    clinescope examples/sample-trace.json --expected read_files apply_patch --advice
    ```

    **Compare several runs side by side:**

    Run the same task against different models (or Cline versions) and score them all in one table (again using bundled traces so it runs as-is):
    ```bash
    python -m clinescope.compare examples/sample-trace.json examples/multi-op-trace.json examples/live-gpt-oss-apply-fail.json
    ```
    Each row is one run; the columns are the four scorers. To score `tool_selection` per run (each task expects different tools), pass a `--labels manifest.json` mapping each trace path to its `{"display": "...", "expected_tools": [...]}`.

## Validation Corpus

Clinescope ships a corpus of **real captured Cline runs** in [`examples/corpus/`](examples/corpus/), each hand-labeled in [`corpus.json`](examples/corpus/corpus.json) with its expected score profile, failure taxonomy, and the evidence its advice should name. A runner scores every trace, checks it against its label, prints a summary table, and **exits non-zero if any trace fails its label** — so the corpus is a real regression gate, not a demo:

```bash
python -m clinescope.corpus
```

This is the un-fakeable evidence that Clinescope catches real agent failures (and stays quiet on clean runs): the traces are real, the failures are real, and the runner proves Clinescope reproduces every labeled outcome. Six real traces cover three of the four failure modes; the fourth (`blind_rewrite`) is an honestly-stated gap — see [`examples/corpus/README.md`](examples/corpus/README.md) for the coverage table and why no local model produced it.

## Reporting Bugs

Small, discussed-first changes are welcome -- see [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, tests, and what a scorer change needs. You can file a [GitHub issue](https://github.com/minh2416294/clinescope/issues).

## License

[Apache-2.0](LICENSE). Copyright 2026 Tran Binh Minh.
