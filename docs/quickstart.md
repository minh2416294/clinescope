# Run Clinescope on your own Cline session

> Clinescope is an independent, unofficial tool - not affiliated with, endorsed by, or sponsored by Cline or Cline Bot Inc. "Cline" is a trademark of Cline Bot Inc., used only to describe compatibility.

Clinescope scores a real Cline run: point it at the `messages.json` Cline writes to disk and it tells you whether the agent picked the right tools, wrote clean patches, and recovered when a patch failed. This guide takes you from zero to scoring your own Cline session.

Clinescope is pure Python and runs on macOS, Linux, and Windows. The `cline` commands below are identical on all three; only the shell differs (examples use PowerShell on Windows).

Everything here runs **on your machine**. On the default path Clinescope makes no network calls and needs no API key. The only part that ever touches the network is the optional LLM judge, and even that talks to a local Ollama, never a remote API. Your Cline trace, your code, and your prompts never leave your computer.

**Today this works with the Cline CLI**, which writes the trace format Clinescope reads. The VS Code extension writes a different on-disk format that Clinescope does not load yet (see [Extension support](#extension-support-roadmap)).

## See it work first (no Cline, no Ollama, no key)

Clinescope ships real captured Cline traces inside the package, so you can watch it score before setting anything up. From any directory:

```bash
pip install clinescope
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

Requires Python 3.11+ (check `python --version`). A virtual environment is recommended. On macOS/Linux you may need `pip3` / `python3 -m pip`.

```bash
pip install clinescope
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

> **Using the VS Code extension?** It stores a task in a different on-disk format that Clinescope cannot load yet. Use the Cline CLI for now (see [Extension support](#extension-support-roadmap)).

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

## Extension support (roadmap)

The Cline VS Code extension stores a task's history as `api_conversation_history.json` and `ui_messages.json` under its global storage, not as the versioned World-A trace (`{version: 1, messages: [...], ...}`) the CLI writes. Clinescope loads the CLI format only, so extension sessions are not scoreable yet. A World-A export from the extension (or a converter) is on the roadmap.

One more honest note: a trace that includes image or file attachment blocks still loads and scores fine, but those blocks are not shown in the report (the four scorers work on tool calls and their results).

## Related

- [Usage guide](usage.md) - every command and flag.
- [Validation corpus](../examples/corpus/README.md) - the six real traces behind `clinescope-corpus` (three of four failure modes covered; `blind_rewrite` is a stated gap).
- [Judge validation](judge-validation.md) - why the optional LLM judge is advisory-only.
