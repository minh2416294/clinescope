# Cline VS Code extension trace fixtures

The Cline VS Code extension stores a task's API history as a bare JSON array of
messages in `api_conversation_history.json` (no `{version, messages}` envelope),
under the extension's global storage. This is a different on-disk shape from the
`{version: 1, messages: [...]}` World-A trace the Cline CLI writes, which is what
Clinescope's loader (`world_a.py`) reads directly.

`clinescope.cline_extension.load_extension_trace` bridges that gap: it wraps the
bare array in the World-A envelope and feeds the existing loader unchanged.

## `api_conversation_history.constructed.json`

A **constructed** fixture, not a real capture. It mirrors the extension's
on-disk shape verified against Cline source
(`apps/vscode/src/core/storage/disk.ts::saveApiConversationHistory` writes
`JSON.stringify(apiConversationHistory)` where the param is
`Anthropic.MessageParam[]`; `apps/vscode/src/shared/messages/content.ts`
defines `ClineStorageMessage extends Anthropic.MessageParam` with extra optional
fields `id`, `ts`, `modelInfo`, `metrics`). The extra Cline-specific fields
(`id`, `ts`, `modelInfo`) are included on purpose: the adapter and loader must
ignore them, and this fixture proves they do.

## Real captured extension traces

Following the "real over synthetic" discipline of the validation corpus
(`examples/corpus/README.md`), two traces here are **real** captures from actual
Cline VS Code extension (`saoudrizwan.claude-dev` 4.0.9) tasks against a local
Ollama model, pinned by `skipif`-gated tests in
`tests/test_extension_real_capture.py`:

- `api_conversation_history.real.json` (+ its `ui_messages.real.json`): the model
  said it would create `calc.py` but only emitted `plan_mode_respond` and never
  called an edit tool. The "said done, did nothing" catch on a real extension
  session: zero tool calls, every scorer reports the gap.
- `api_conversation_history.write-file.json` (+ `ui_messages.write-file.json`): the
  model actually created `calc.py`, via `write_to_file`. A real successful edit.

### Finding: the extension's edit tool differs from the CLI's

The CLI emits `apply_patch` (World-A grammar), which Clinescope's `diff_coherence`
/ `diff_minimality` / `apply_recovery` scorers grade. This extension build (with a
local Ollama model) reported `apply_patch` unavailable and used `write_to_file`
instead. Clinescope handles that honestly: `tool_selection` scores the extension's
own tools (both `write_to_file` and `read_file` are in the pinned vocab), and the
three `apply_patch`-based diff scorers **abstain** (`n/a` / a hard zero) rather than
crash. A diff-quality scorer for `write_to_file` / `replace_in_file` grammar is a
roadmap item, not shipped.

## `api_conversation_history.constructed.json`

An always-on **constructed** fixture (list-content messages), so the core adapter
tests run even without the real captures present.
