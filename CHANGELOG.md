# Changelog

All notable changes to Clinescope are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-07-18

Score a Cline VS Code extension session directly from the command line.

### Added

- `clinescope --vscode`: auto-discover the Cline VS Code extension's per-OS global
  storage, list recent sessions with a title and timestamp, and score the one you
  pick. Flags: `--path` (a task dir, its `api_conversation_history.json`, or a
  `globalStorage` root), `--latest` (newest, no prompt), `--variant` (limit to one
  editor: Code, Cursor, VSCodium, Windsurf, ...), `--all` (show every session in
  the picker). Non-interactive safe: it never prompts without a terminal.
- `extension_discovery` module (pure stdlib) for the per-OS discovery, session
  enumeration, and label recovery (from `state/taskHistory.json`, falling back to
  `ui_messages.json` and the folder name).
- The VS Code extension tool family in the pinned tool vocabulary
  (`write_to_file`, `replace_in_file`, `read_file`, ...), so `--expected` accepts
  extension tool names without a spurious typo warning and `--list-tools` shows
  both the CLI and extension names.
- Two real captured extension traces as `skipif`-gated test fixtures: a run that
  claimed to edit but never called an edit tool, and a real `write_to_file` edit.

### Changed

- The trace loader now tolerates a bare-string message `content` (a valid Anthropic
  shape) instead of crashing on it; any other non-list content is surfaced on
  `dropped_items` rather than swallowed. The list-content path is unchanged.
- Reports for an extension session use an `extension session <taskId> "<title>"
  [<variant>]` header, so a CLI run and an extension run are never confused.

### Notes

- The diff scorers (`diff_coherence`, `diff_minimality`, `apply_recovery`) grade
  `apply_patch` grammar. When an extension session edits with `write_to_file` or
  `replace_in_file`, `tool_selection` still scores and those three abstain (`n/a`)
  rather than guess. A diff-quality scorer for `write_to_file` grammar is on the
  roadmap.
- No runtime dependencies were added: `dependencies` is still empty (pure stdlib).
  The four scorers, the World-A loader internals, and the golden fixture are
  unchanged.

## [1.0.1] - 2026-07-12

First public release on PyPI (`pip install clinescope`). Cline-native eval harness
with four deterministic scorers (`tool_selection`, `diff_coherence`,
`diff_minimality`, `apply_recovery`), an advisory LLM judge validated at
chance-level and kept out of the gate, a real-trace validation corpus, a CI gate,
and `--advice` / `--compare`.

[1.1.0]: https://github.com/minh2416294/clinescope/releases/tag/v1.1.0
[1.0.1]: https://github.com/minh2416294/clinescope/releases/tag/v1.0.1
