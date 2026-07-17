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

## Stated gap: a real captured extension trace

Following the same "real over synthetic" discipline as the validation corpus
(`examples/corpus/README.md`), a **real** captured
`api_conversation_history.json` from an actual VS Code extension task is the
stronger evidence and is queued. It is not committed yet because capturing one
requires running the extension on a real repo and locating its global-storage
file. When captured, drop it in here and add it to
`tests/test_cline_extension.py` as a `skipif`-gated end-to-end pin, exactly like
the live-capture corpus traces. The adapter logic is identical for the real and
constructed shapes, since the delta from the CLI format is only the missing
envelope.
