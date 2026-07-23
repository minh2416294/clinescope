# Run Clinescope on your own Cline session

> Clinescope is an independent, unofficial tool - not affiliated with, endorsed by, or sponsored by Cline or Cline Bot Inc. "Cline" is a trademark of Cline Bot Inc., used only to describe compatibility.

Use the `clinescope` tool to score your last Cline run by pointing it to the `messages.json` file that Cline saves to disk. Then, it will tell you if you used the right tools, committed patches cleanly, and recovered from failed patches successfully!

Clinescope is pure Python and runs on macOS, Linux, and Windows. The `cline` commands below are identical on all three; only the shell differs (examples use PowerShell on Windows).

All processing takes place in your local environment. On the default deployment, there are no outbound API requests at all, and no API keys needed. The only possible connection to an external service is the optional LLM judge, which by default connects to a local Ollama instance, not an API. Your Cline trace, code, and prompts are never sent to a remote server.

**The `clinescope` command works with both the Cline CLI and the VS Code extension.** The two store sessions in different on-disk formats; Clinescope reads both. This guide uses the CLI. On the extension, run `clinescope --vscode` instead (see [Score a VS Code extension session](#score-a-vs-code-extension-session)).

## See it work first (no Cline, no Ollama, no key)

Clinescope ships real captured Cline traces inside the package, so you can watch it score before setting anything up. The fastest look is `clinescope --demo`, which scores one bundled trace (a real run whose patch failed and was never retried) with advice on:

```bash
python -m pip install clinescope
clinescope --demo
```

To run it without installing anything first, use [uv](https://docs.astral.sh/uv/) or [pipx](https://pipx.pypa.io/) (each fetches Clinescope into a throwaway environment):

```bash
uvx clinescope@latest --demo    # or: pipx run clinescope --demo
```

For the fuller picture, `clinescope-corpus` scores all six bundled traces at once:

```bash
clinescope-corpus
```

`clinescope-corpus` scores six real Cline runs and prints a scorecard:

```
trace                                                  tool_selection  diff_coherence  diff_minimality  apply_recovery
-----------------------------------------------------  --------------  --------------  ---------------  --------------
gpt-oss:20b update-1hunk (clean)                       100/100 PASS    100/100 PASS    100/100 PASS     n/a
gpt-oss:20b apply-fail (no recovery)                   100/100 PASS    100/100 PASS    100/100 PASS     0/100 FAIL
qwen2.5-coder:1.5b hallucinated-tool (no apply_patch)  0/100           0/100 FAIL      n/a              n/a
llama3.1:8b code-dump (no apply_patch)                 0/100           0/100 FAIL      n/a              n/a
```

Clean runs pass; a run whose patch failed and was never retried shows `apply_recovery 0/100 FAIL`; a run where a weak model never emitted a real tool call shows `tool_selection 0/100`. That is the whole idea, on real data. Now score your own run.

## 1. Install Clinescope

**Check your Python.** Clinescope needs Python 3.11 or newer.

```bash
python --version        # expect 3.11 or higher
```

On Windows the `py` launcher is the reliable check when several Pythons are installed: `py --version`, or `py --list` to see them all (use `py -3.11` to select one). On macOS and Linux the command is often `python3` (`python3 --version`). If the version is below 3.11, see [Install troubleshooting](#install-troubleshooting).

**Create and activate a virtual environment.** A venv keeps Clinescope and its (zero) dependencies isolated from your system Python. Pick your shell:

```powershell
# Windows PowerShell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell blocks the activation script ("running scripts is disabled on this system"), allow local scripts for your user once, then activate again:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

```bat
:: Windows CMD
python -m venv .venv
.venv\Scripts\activate.bat
```

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

**Install Clinescope.** Install it as a module of your interpreter (`python -m pip`), which always targets the Python you just checked, rather than a bare `pip` that can point at a different or broken one:

```bash
python -m pip install clinescope
```

On Windows you can also use `py -m pip install clinescope`. If this prints `Fatal error in launcher` or `pip` is not found, see [Install troubleshooting](#install-troubleshooting).

## Install troubleshooting

A few things a first install can hit. These are environment issues, not Clinescope bugs; the fixes are standard Python packaging steps.

- **`Fatal error in launcher: Unable to create process using ...pip.exe ...: The system cannot find the file specified`.** Your `pip.exe` launcher hardcodes the path of the Python it was installed with, and that Python has since moved or been removed. Bypass the broken launcher by running pip as a module: `python -m pip install clinescope` (or `py -m pip install clinescope` on Windows). If it persists, the venv's launcher shims are stale: delete the `.venv` folder and recreate it (step 1). If the `clinescope` command itself is broken the same way, run it as a module: `python -m clinescope --demo`.

- **`clinescope: command not found` (or `'clinescope' is not recognized`) after installing.** The install landed in a different interpreter, or your venv is not activated. Activate the venv (step 1), or run Clinescope as a module: `python -m clinescope --demo`.

- **Python is older than 3.11.** Check with `python --version` (Windows: `py --version`, or `py --list` to see every installed version). Install or select a 3.11+ interpreter; on Windows, `py -3.11 -m venv .venv` creates the venv with a specific version.

- **`error: externally-managed-environment` (Debian, Ubuntu, and some Homebrew setups).** Your system Python refuses direct installs. The fix is to install into a virtual environment (step 1), not to pass `--break-system-packages`.

- **Nothing installs cleanly.** You can skip installing entirely and run Clinescope in a throwaway environment: `uvx clinescope@latest --demo` (with [uv](https://docs.astral.sh/uv/)) or `pipx run clinescope --demo` (with [pipx](https://pipx.pypa.io/)).

Still stuck? Open a [bug report](https://github.com/minh2416294/clinescope/issues/new/choose) with your OS, `python --version`, and the exact command and error.

## Verify your install

Confirm the install works before you produce a real Cline session. These commands need no Cline session, no Ollama, and no API key; they score traces bundled inside the package.

```bash
clinescope --demo                              # scores a bundled trace; exit 0
clinescope --list-tools                        # prints the known Cline tool names; exit 0
clinescope-corpus                              # scores six bundled traces: "6/6 items match their labels"; exit 0
python -m clinescope.judge_run --report-only   # recomputes the judge agreement from a cached run, no model call; exit 0
clinescope --help                              # usage text; exit 0
```

Check the installed version (there is no `clinescope --version` flag):

```bash
pip show clinescope                                          # or:
python -c "import clinescope; print(clinescope.__version__)"
```

## 2. Produce a Cline session

If you already have a Cline CLI session on disk, skip to step 3. Otherwise, generate one against a local model (no API key, no cost).

Prerequisites: install [Ollama](https://ollama.com) and pull a small, fast coding model (about 4-5 GB):

```bash
ollama pull qwen2.5-coder:7b
```

Point the Cline CLI at it:

```bash
cline auth -p ollama -m qwen2.5-coder:7b -k ollama
```

Ollama needs no API key, but the CLI's quick setup requires the flag, so pass any placeholder (`-k ollama` here). A small model responds quickly; a larger model (for example `gpt-oss:20b`) may need `cline --timeout 120 "..."` to beat the default 30-second request timeout.

Run a task in any project directory:

```bash
cline "Fix the bug in calc.py using apply_patch, then stop."
```

(Verified against the Cline CLI as of 2026-07-17. If `cline auth` rejects these flags, run `cline auth --help`.)

## 3. Find your session's trace

Ask Cline where it just wrote the session, rather than guessing a path:

```bash
cline history --json
```

Each entry has a `messagesPath` field pointing straight at the trace. Copy the one for the run you just did; that is the file you pass to Clinescope.

> **Using the VS Code extension?** It stores a task in a different on-disk format, and `clinescope --vscode` reads it directly (auto-discovery + a session picker), so you can skip the CLI steps below (see [Score a VS Code extension session](#score-a-vs-code-extension-session)).

For reference, the CLI writes each session to `~/.cline/data/sessions/<sessionId>/<sessionId>.messages.json` (on Windows, `C:\Users\<you>\.cline\data\sessions\...`). If you set `CLINE_DATA_DIR` or ran `cline --data-dir <path>`, it lives under that directory instead.

## 4. Score it

Point Clinescope at the trace. After `--expected`, list the tools the task needed (in any order; order does not matter). Run `clinescope --list-tools` to see valid names.

```bash
clinescope path/to/messages.json --expected apply_patch read_files
```

You get one line per scorer:

- **`tool_selection`**: did the agent call the tools the task needed?
- **`diff_coherence`**: are its code patches valid and well-formed?
- **`diff_minimality`**: are its edits small and focused, not bloated rewrites?
- **`apply_recovery`**: when a patch failed, did the agent fix it?

Here is a real run of a small local model asked to fix a bug. It answered in fluent prose ("the fix is complete, a patch was applied") but never actually called a tool, and the file was never touched. Clinescope caught it (your session id will be a timestamp Cline assigned, like `1783823285576_8f1km`):

```
clinescope report - session 1783823285576_8f1km (0 tool calls)
tool_selection    0/100   (missing: apply_patch, read_files)
diff_coherence    0/100  FAIL   (no apply_patch tool call in trace)
diff_minimality     n/a  n/a   (no apply_patch - nothing to check)
apply_recovery      n/a  n/a   (no apply_patch - nothing to recover)
```

Reading it: the agent claimed it fixed the bug, but the trace records zero tool calls, so no file was touched. `tool_selection 0/100` means it never called the tools; `diff_coherence FAIL` means there was no patch to check; the two `n/a` lines mean there was no patch to measure (not an error). That gap between "the agent said it succeeded" and "the agent did nothing" is what Clinescope exists to catch.

## 5. Improve the agent

Add `--advice` to turn a failing scorer into a concrete fix for your prompt:

```bash
clinescope path/to/messages.json --expected apply_patch read_files --advice
```

```
advice (how to improve the agent):
  [tool_selection] missing_tools
    - The agent never called: apply_patch, read_files.
    - Add to your prompt an instruction to use the right tool for the task.
  [diff_coherence] malformed_patch
    - The model is emitting invalid apply_patch grammar. Add a few-shot example of a
      correct '*** Begin Patch' block to your prompt, or try a stronger model.
```

Then edit your prompt per the advice, re-run the Cline task, and score again. A clean run (every applicable scorer passing) is the goal.

## Score a VS Code extension session

Most Cline users are on the VS Code extension, which stores each task as `api_conversation_history.json` (a bare JSON array of messages) plus `ui_messages.json` under its global storage, not as the versioned World-A trace (`{version: 1, messages: [...], ...}`) the CLI writes. `clinescope --vscode` reads that format for you: it finds the extension's storage on your OS, lists your recent sessions with a title and timestamp, and scores the one you pick.

```bash
clinescope --vscode --expected apply_patch read_file
```

That opens an interactive picker (newest first; press Enter for the newest, `q` to quit). To skip the picker:

- `clinescope --vscode --latest` scores the newest session without prompting (also the right choice in a script or CI, where there is no terminal to prompt).
- `clinescope --vscode --path <task-dir>` points at one session explicitly (a task directory, its `api_conversation_history.json`, or the extension's `globalStorage` root).
- `clinescope --vscode --variant Cursor` limits discovery to one editor when you have several (Code, Cursor, VSCodium, ...).

The report header reads `extension session <taskId> "<title>" [<variant>]`, so it is clear you are looking at an extension run, not a CLI one.

**One tool-name difference to know.** The CLI uses `apply_patch` / `read_files`; the extension often uses `write_to_file` / `replace_in_file` / `read_file` instead (it depends on your Cline and model). Run `clinescope --list-tools` to see the full set for `--expected` (both the CLI and extension names). The diff scorers grade `apply_patch` grammar, so on a `write_to_file` session `tool_selection` still scores; `diff_coherence` reports a hard `0/100` (it found no `apply_patch` to grade), and `diff_minimality` / `apply_recovery` abstain (`n/a`). That `0/100` means "no `apply_patch` to grade here," not "your agent wrote a broken patch." A diff-quality scorer for `write_to_file` grammar is on the roadmap.

## Related

- [Usage guide](usage.md) - every command and flag.
- [Validation corpus](../examples/corpus/README.md) - the six real traces behind `clinescope-corpus` (three of four failure modes covered; `blind_rewrite` is a stated gap).
- [Judge validation](judge-validation.md) - why the optional LLM judge is advisory-only.
- [The harness gap](harness-gap.md) - an A/B experiment: does a `.clinerules` harness prevent a failure, or is it a model-capability ceiling?
- [Share feedback](https://github.com/minh2416294/clinescope/issues/new/choose) - you ran it on your own trace; tell me what broke or confused you.
