# Usage guide

The [README](../README.md) covers installing Clinescope and the two commands you'll reach for most.
This guide covers the rest.

## Score a run

Point Clinescope at a Cline log file (a `messages.json` trace) to score the run:

```bash
clinescope path/to/messages.json --expected read_files apply_patch
```

After `--expected`, list the tools you think the task needed. Run `clinescope --list-tools` to print
the tools Clinescope knows (both the CLI and the VS Code extension tool names).

## Score a VS Code extension session

The Cline VS Code extension stores sessions in a different on-disk format from the CLI. `--vscode` reads
it: it auto-discovers the extension's per-OS storage, lists your recent sessions, and scores the one you
pick.

```bash
clinescope --vscode --expected apply_patch read_file
```

Flags for `--vscode`:

- `--latest` scores the newest session without prompting (use this in scripts or CI, where there is no
  terminal to prompt).
- `--path <task-dir>` points at one session explicitly: a task directory, its
  `api_conversation_history.json`, or the extension's `globalStorage` root.
- `--variant <name>` limits discovery to one editor (`Code`, `Cursor`, `VSCodium`, `Windsurf`, ...) when
  several are installed.
- `--all` shows every session in the picker instead of only the most recent.

The diff scorers grade `apply_patch` grammar. When an extension session edits with `write_to_file` or
`replace_in_file`, `tool_selection` still scores and the three diff scorers abstain (`n/a`). Exit codes:
`0` a report printed, `1` a session could not load, `2` a usage problem (no session found, or a non-TTY
with no `--latest` / `--path`).

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

- [Validation corpus](../examples/corpus/README.md): the real-trace regression suite.
- [Judge validation](judge-validation.md): how the optional LLM judge is measured (and why it's advisory-only).
- [Share feedback](https://github.com/minh2416294/clinescope/issues/new/choose) - you ran it on your own trace; tell me what broke or confused you.
