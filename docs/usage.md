# Usage guide

Install with `python -m pip install clinescope` (Python 3.11+). The [quickstart](quickstart.md#1-install-clinescope) covers virtual-environment setup and [install troubleshooting](quickstart.md#install-troubleshooting).

## See it work first

`--demo` scores a bundled real trace (a run whose patch failed and was never retried) with advice on, so you can watch Clinescope work with no Cline session, no setup, and no arguments:

```bash
clinescope --demo
```

To run it without installing first, use [uv](https://docs.astral.sh/uv/) or [pipx](https://pipx.pypa.io/):

```bash
uvx clinescope@latest --demo    # or: pipx run clinescope --demo
```

## Score a run

Point Clinescope at a Cline log file (a `messages.json` trace) to score the run:

```bash
clinescope path/to/messages.json --expected read_files apply_patch
```

After `--expected`, list the tools you think the task needed. Run `clinescope --list-tools` to print
the tools Clinescope knows (both the CLI and the VS Code extension tool names).

If the run used `apply_patch`, the line under `diff_coherence` is `cline_verdict`: what Cline itself
recorded for the patch `diff_coherence` graded. It reads `applied`, `rejected` followed by Cline's own
reason, or `no verdict`. A `100/100` next to `rejected` means the patch text was well formed but did not
fit your file. The line is not a score, and the gate ignores it.

## Check the inputs the agent sent

`tool_selection` checks tool names only. To check that an `editor` call carried a value you expect,
name it after `--expected-input`:

```bash
clinescope path/to/messages.json --expected-input editor path=src/app.py
```

The flag takes a tool and a `KEY=VALUE` pair, and you can repeat it. Only `editor` is supported; its keys
are `path`, `old_text`, `new_text` and `insert_line`. A `path` matches on its ending, so `src/app.py`
matches the full path Cline recorded. Other keys match as exact text. The `tool_input` line shows the
share of your inputs that some `editor` call carried and lists the missing ones. It does not check
whether that call worked. A tool other than `editor`, or a pair with no `=`, exits `2`.

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
- `--all` shows every session in the picker. Without it the picker lists the twenty newest and
  says how many older ones it left out.

The diff scorers grade `apply_patch` grammar. When an extension session edits with `write_to_file` or
`replace_in_file`, `tool_selection` still scores; `diff_coherence` reports a hard `0/100` (it found no
`apply_patch` to grade), and `diff_minimality` / `apply_recovery` abstain (`n/a`). Exit codes: `0` a
report printed, `1` a session could not load, `2` a usage problem (no session found, or a non-TTY with
no `--latest` / `--path`).

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

The table has one column per check. In the `editor_recovery` column, `n/a` means the run used `editor` and no edit failed, and `-` means the run made no `editor` call at all (the single-run report prints no line for it then).

## Gate a run in CI

Exit non-zero when a score falls below a threshold, so a bad run fails your pipeline:

```bash
clinescope-gate path/to/messages.json --min-diff-coherence 0.8
```

Most Cline sessions today edit with `editor`, not `apply_patch`. Gate those on the editor scorer and on tool selection:

```bash
clinescope-gate path/to/messages.json --min-editor-recovery 1.0 --min-tool-selection 1.0 --expected read_files editor
```

`--min-editor-recovery` has nothing to score when no edit failed, so on its own a clean run exits `2` ("nothing was verified"). `--min-tool-selection` checks that each tool after `--expected` was called, by name only, and gives a number on every run. The numbers above are examples, not recommended bars.

## Related

- [Validation corpus](../examples/corpus/README.md): the real-trace regression set.
- [Judge validation](judge-validation.md): how the optional LLM judge is measured (and why it's advisory-only).
- [The harness gap](harness-gap.md): an A/B experiment on whether a `.clinerules` harness prevents a failure or hits a model ceiling.
- [Share feedback](https://github.com/minh2416294/clinescope/issues/new/choose) - you ran it on your own trace; tell me what broke or confused you.
