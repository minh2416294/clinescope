# Usage guide

The [README](../README.md) covers installing Clinescope and the two commands you'll reach for most.
This guide covers the rest.

## Score a run

Point Clinescope at a Cline log file (a `messages.json` trace) to score the run:

```bash
clinescope path/to/messages.json --expected read_files apply_patch
```

After `--expected`, list the tools you think the task needed. Run `clinescope --list-tools` to print
the tools Clinescope knows.

## Improve your prompt

`--advice` coaches you on how to fix the agent's prompt for each failing scorer:

```bash
clinescope path/to/messages.json --expected read_files apply_patch --advice
```

## Get the full per-scorer breakdown

`--verbose` prints every scorer's score and the evidence behind it:

```bash
clinescope path/to/messages.json --expected read_files apply_patch --verbose
```

## Compare several runs side by side

Run the same task against different models (or Cline versions) and score them all in one table:

```bash
python -m clinescope.compare run-a.json run-b.json run-c.json
```

## Gate a run in CI

Exit non-zero when a score falls below a threshold, so a bad run fails your pipeline:

```bash
clinescope-gate path/to/messages.json --min-diff-coherence 0.8
```

## Related

- [Validation corpus](../examples/corpus/README.md) — the real-trace regression suite.
- [Judge validation](judge-validation.md) — how the optional LLM judge is measured (and why it's advisory-only).
- [Share feedback](https://github.com/minh2416294/clinescope/issues/new/choose) - you ran it on your own trace; tell me what broke or confused you.
