# Changelog

All notable changes to Clinescope are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `editor_recovery`, a trajectory scorer for Cline's `editor` tool. Of every
  `editor` call Cline marked failed, it scores the fraction later recovered by a
  strictly-later `editor` call Cline confirmed non-failing on the same path. It
  exists because almost no current Cline session emits `apply_patch`: all five
  tool presets set `enableApplyPatch: false`, and only two routing rules flip a
  session back to it (an `openai-native` provider, or a model id containing
  `codex` or `gpt`), both of which also require `act` mode. On every other session
  the three `apply_patch` scorers produce one hard zero and two blanks.
- `examples/live-granite-editor-recovery.json`, a real captured Cline CLI session
  (granite4.1:8b via Ollama) in which the agent called `editor` without `old_text`,
  Cline rejected it, and the agent retried successfully. It is the first
  editor-bearing trace in this repository.

### Changed

- The `"success"`-JSON verdict oracle moved out of `apply_recovery` into a shared
  `clinescope.tool_verdict`, because `editor_recovery` resolves a verdict the same
  way. Behaviour is unchanged; the existing `apply_recovery` tests pass against the
  shared implementation without modification.
- A trace containing no `editor` call renders exactly as before: the CLI scores
  editor recovery only when the tool is actually present, so no existing report
  gains a line.
- Quickstart step 2 now recommends `gpt-oss:20b` instead of `qwen2.5-coder:7b`, and
  says why: in this repository's own harness-gap A/B, `qwen2.5-coder:7b` wrote its
  tool call as JSON inside its prose, so Cline recorded zero tool calls and a
  first-time reader saw nothing but zeros and blanks. The step also adds the Cline
  CLI install command, corrects the download size, and moves the `--timeout 120`
  advice above the command it applies to instead of below it.
- The README no longer claims the quickstart "walks you from installing Cline". It
  walks you from installing Clinescope, and now links out to Cline's own docs for
  the Cline CLI itself.

### Known limitation

- `editor_recovery` is report-only in this release. It renders in the `clinescope`
  report and feeds `--advice`, but `clinescope-gate`, `python -m clinescope.compare`
  and `clinescope-corpus` do not read it yet, so an editor-only session has no
  gateable signal. Wiring it into the gate is deliberately deferred until someone
  gates CI on one.
- There is no shape scorer for `editor`, only this trajectory one. A candidate
  design exists and was not shipped: across every Cline session on the development
  machine there were exactly two real `editor` replacement calls, and every
  candidate definition scored both of them clean, so the check would have been
  unexercised by construction.

## [1.2.1] - 2026-08-20

Corrections to what this tool claims to measure, and the disclosures that were
already in `LIMITATIONS.md` moved to where the decision is actually made.

### Changed

- `clinescope-gate --help`: `--min-diff-minimality` now carries its own measured
  agreement with human labels (Cohen's kappa 0.2599, 7 of 24 recalled, N=50), the
  fact that it has never failed a build on any real captured trace shipped here,
  and that the same edit can score 1.0 or 0.0 depending on how many lines sit
  between an anchor and the change in the file being edited. Someone wiring this
  into CI reads `--help` and never opens the repo.
- The CLI feedback footer now asks whether any score disagreed with your own read
  of the run, and its link goes to the feedback form instead of the template
  picker. It is still written to stderr, and still only when stdout is a terminal,
  so pipes, redirects, and CI never see it.
- The judge report names the kappa advisory tripwire without a section number,
  which pointed into a document this repository does not control.
- The `dev` extra is pinned to exact versions (`pytest==9.1.1`,
  `pytest-cov==7.1.0`, `ruff==0.15.22`, `mypy==2.3.0`) so an unpinned linter
  release cannot turn every open pull request red. **This is the only change here
  that can break an install:** `pip install clinescope[dev]` will now conflict with
  a different pinned version of any of those four in the same environment. The
  runtime `dependencies` list is untouched and still empty. Two printed strings
  also changed, the feedback footer and the judge report line above, so anything
  matching on their old wording needs updating. The footer goes to stderr, and only
  when stdout is a terminal. The judge report, including the line that changed, goes
  to **stdout**, so a CI job grepping it for the old `protocol section 7` wording
  will stop matching.

### Fixed

- The package summary, and the four scorer bullets in `README.md` and
  `docs/quickstart.md`, name the specific deterministic check each scorer runs
  instead of calling them diff-quality scorers. The scorers parse `apply_patch`
  text against Cline's `*** Begin Patch` grammar, flag one bloat shape, and read
  Cline's own failed and applied verdicts. None of them judges whether a change is
  correct.
- Three statements about what the scorers measure, caught by an adversarial
  re-verification: `apply_recovery` is not a structural check on patch text (two
  traces with byte-identical patches score differently when only Cline's
  `is_error` flips), its denominator counts failed file pairs rather than failed
  patches, and `diff_minimality` does not require the deleted and added runs to be
  adjacent.
- The front page no longer calls Clinescope an AI evaluation tool, and no longer
  says it ensures updates do not break past work. `apply_recovery` scores whether
  a failed patch was retried later in the same session; it does not verify any fix
  is correct.
- `LIMITATIONS.md` no longer presents the layout comparison as controlled: the two
  patches differ by more than the one comment line the text claimed. The corpus
  README gives the real reason `blind_rewrite` is uncovered, which is that the task
  was built to elicit the shape, not that no local model could produce one.

### Added

- `LIMITATIONS.md` records that `diff_minimality`'s score depends on the layout of
  the file being edited, with both patches printed so a reader can check it.
- `diff_minimality`'s measured agreement against the same 50 human labels used for
  the judge, and the fact that `diff_coherence` and `apply_recovery` have no
  agreement number at all. Read their silence as unmeasured, not as validated.
- An install-troubleshooting section and a verify-your-install section in the
  quickstart, for machines where a bare `pip install` does not work.
- A paragraph naming what happens if Cline ships trace evaluation itself, and the
  specific reason it would hurt: the three diff scorers are welded to the
  `apply_patch` grammar and do not port without a rewrite.
- A test asserting that `pyproject.toml` and `clinescope.__version__` agree, so a
  half-finished version bump cannot ship a wheel whose `__version__` is wrong.

### Notes

- **No scoring logic changed.** `git diff v1.2.0..v1.2.1 -- src/clinescope/diff_minimality.py
  src/clinescope/apply_recovery.py src/clinescope/tool_selection.py src/clinescope/world_a.py`
  is empty: those four files are byte-identical to 1.2.0. The fifth,
  `src/clinescope/diff_coherence.py`, changed by three added and two removed lines,
  all of them prose inside the module docstring, where it stopped calling itself a
  diff-quality scorer. No executable line moved, so no score moves on any trace
  that scored under 1.2.0.
- No runtime dependencies were added: `dependencies` is still empty (pure stdlib).
- **Corrected 2026-08-21, after 1.2.1 was published.** This entry originally said that
  neither changed string is on stdout. That is wrong for the judge report line, which
  `judge_run.py` prints to stdout. The bullet above now says so. The copy of this file
  inside the published 1.2.1 sdist still carries the original wording, because a
  released artifact cannot be edited.

## [1.2.0] - 2026-07-23

The one-command live demo, plus a typing and hygiene pass.

This entry was written on 2026-08-20, four weeks after the release, and
reconstructed from `git log v1.1.0..v1.2.0`. The 1.2.0 bump commit (`8bf45a0`)
changed only `pyproject.toml` and `src/clinescope/__init__.py`, so no entry was
recorded at the time.

### Added

- `clinescope --demo`: score a bundled real trace with no arguments, no API key,
  and no network. Three scorers pass and `apply_recovery` fails, with advice, so a
  stranger can watch it catch a real failure on their own machine.
- A PEP 561 `py.typed` marker, so a downstream importer sees Clinescope's inline
  type annotations instead of ignoring them.
- `LIMITATIONS.md` at the repository root, linked from the README.
- `docs/building-with-agents.md`, on how a correctness tool stayed correct while an
  agent wrote much of the code.
- `docs/harness-gap.md` and the harness-gap A/B: real captured Cline traces for
  three local models, run with and without a `.clinerules` harness, as
  `skipif`-gated test fixtures.

### Changed

- A corrupt but present VS Code extension JSON file now warns to stderr instead of
  being skipped silently. An absent file stays silent.
- The reader-facing prose docs were rewritten in a plainer voice, with every
  command, flag, score, and caveat unchanged.

### Notes

- No scorer, loader, or dependency change. `dependencies` stayed empty and the
  golden fixture stayed byte-identical.

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

[1.2.1]: https://github.com/minh2416294/clinescope/releases/tag/v1.2.1
[1.2.0]: https://github.com/minh2416294/clinescope/releases/tag/v1.2.0
[1.1.0]: https://github.com/minh2416294/clinescope/releases/tag/v1.1.0
[1.0.1]: https://github.com/minh2416294/clinescope/releases/tag/v1.0.1
