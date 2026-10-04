# Usage guide

Install with `python -m pip install clinescope` (Python 3.11+). The [quickstart](quickstart.md#1-install-clinescope) covers virtual-environment setup and [install troubleshooting](quickstart.md#install-troubleshooting).

## See it work first

`--demo` scores a bundled real trace (a run whose patch failed and was never retried) and says what went wrong, what to do about it, and why, so you can watch Clinescope work with no Cline session, no setup, and no arguments:

```bash
clinescope --demo
```

To run it without installing first, use [uv](https://docs.astral.sh/uv/) or [pipx](https://pipx.pypa.io/):

```bash
uvx clinescope@latest --demo    # or: pipx run clinescope --demo
```

`clinescope --version` prints `clinescope` and the installed version.

## Score a run

Point Clinescope at a Cline log file (a `messages.json` trace) to score the run:

```bash
clinescope path/to/messages.json --expected read_files apply_patch
```

After `--expected`, list the tools you think the task needed. Run `clinescope --list-tools` to print
the tools Clinescope knows (both the CLI and the VS Code extension tool names).

The report is in plain English. Each problem comes first, with what to do about it and why the check
could be wrong. Then come the checks that went well, and any check that did not apply to this run.
`--details` prints the technical report instead: one line per check with its score, and the same
advice under them.

In `--details`, if the run used `apply_patch`, the line under `diff_coherence` is `cline_verdict`: what Cline itself
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
matches the full path Cline recorded. Other keys match as exact text. A missing input is reported as a
problem. In `--details`, the `tool_input` line shows the share of your inputs that some `editor` call
carried and lists the missing ones. It does not check
whether that call worked. A tool other than `editor`, or a pair with no `=`, exits `2`.

## Check that a command ran after the last edit

To see whether the agent ran your tests after its last change, give part of the command:

```bash
clinescope path/to/messages.json --test-cmd pytest
```

A `not run`, or a run Cline marked failed, is reported as a problem. In `--details`, the `test_cmd`
line reads `ran`, with what Cline recorded (`Cline: success` or Cline's own error text),
or `not run` when no command containing your text came after the last edit. It shows `n/a` when the run
made no edit, when every edit failed, or when it used the extension's `execute_command`. The last edit is
the last edit to any file, including a helper script the agent wrote for itself, so a `not run` can
mean the agent tested first and then wrote that helper. The text is matched as written, case included. Cline keeps one flag for a whole command line, so `pytest; echo done`
can read `success` after pytest failed. The line is not a score and does not prove the fix works. An
empty `--test-cmd` exits `2`.

## When an edit flattened line breaks

No flag is needed. If an `editor` call that Cline accepted replaced text that had real line breaks with
one line holding literal `\n`, the report names that edit as a problem. In `--details` the line reads:

```text
editor_newlines 1 editor call wrote literal \n where the old text had line breaks (call 3: 'C:\\cs-day65-capture\\inventory.py')
```

`call 3` is the position of that call in the trace. Open the file it names and check that it still
parses: the check reads the call, never the file.

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
`replace_in_file`, `tool_selection` still scores. The report says the agent made no edit that
Clinescope can check; in `--details`, `diff_coherence` shows a hard `0/100` (it found no `apply_patch`
to grade), and `diff_minimality` / `apply_recovery` abstain (`n/a`). Exit codes: `0` a
report printed, `1` a session could not load, `2` a usage problem (no session found, or a non-TTY with
no `--latest` / `--path`).

## Improve your prompt

The report already says what to do about each problem, often as an instruction you can add to your
prompt or your Cline rules. `--advice` is no longer needed; older commands that pass it still work.

## Get the full per-scorer breakdown

`--details` prints one line per check with its score, then the advice:

```bash
clinescope path/to/messages.json --expected read_files apply_patch --details
```

`--verbose` prints every scorer's score and the evidence behind it:

```bash
clinescope path/to/messages.json --expected read_files apply_patch --verbose
```

## Compare several runs side by side

Run the same task against different models (or Cline versions) and score them all at once:

```bash
python -m clinescope.compare run-a.json run-b.json run-c.json
```

Each run gets one line: how many problems it has, and how many checks went well or did not apply. Its problems are listed under that line. After the runs, each kind of problem gets one "What to do" and one "Why", naming the runs it applies to. A run with no problems gets no advice.

`--details` prints a table instead, with one column per check except `tool_input`, which it does not show. In the `editor_recovery` column, `n/a` means the run used `editor` and no edit failed, and `-` means the run made no `editor` call at all (the single-run report prints no line for it then).

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
