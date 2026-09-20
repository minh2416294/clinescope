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
  Cline rejected it, and the agent retried successfully. It is the first trace
  captured deliberately to exercise an `editor` scorer. It is NOT the first
  editor-bearing trace here: `examples/harness-gap/granite-harness.messages.json`
  has carried `editor` calls since #69 in July, and nobody noticed until now.
- This project's CI now runs `clinescope-gate` on two committed traces, on every
  Python version in the matrix. One trace must pass and one must fail, because a
  step that only ever expects exit 0 would keep passing if the gate stopped failing
  anything at all. To be exact about what this is: it is dogfooding inside the
  maintainer's own repository, not a third party adopting the gate. Nobody else's
  CI runs it.
- `docs/diff-minimality-correlation.md`, a published null. The question of whether a
  reference-free diff score tracks human judgment on real traces cannot be answered
  from the traces shipped here: `diff_minimality` returns a single value on every real
  captured Cline session, so a rank correlation divides by zero and AUC comes back as
  exactly 0.5 by arithmetic, having never read the labels. The page carries the
  distribution it rests on, the command that reproduces it, and a pre-registration
  fixing what has to be true before any such number is published. Nothing was added to
  the package: neither Spearman nor AUC is implemented anywhere here, and the reproduce
  command is the standard library plus the shipped scorers.

### Changed

- `LIMITATIONS.md` no longer keeps its own count of the captured Cline sessions shipped
  here. The figure it carried covered `examples/corpus/` and `examples/harness-gap/` and
  missed the captures sitting elsewhere under `examples/`, so it understated both the
  population and the share of it that abstains. Those counts now belong to
  `docs/diff-minimality-correlation.md` and are not duplicated. What they support is
  unchanged: no threshold makes `--min-diff-minimality` fail a build on a real trace
  shipped with it.
- `clinescope-gate` no longer reports a regression on a trace it never scored. A trace
  with no `apply_patch` is now treated as not applicable to the whole apply_patch
  family, so the gate exits `2` ("nothing was verified") instead of `1` ("a scorer
  regressed"). Previously `diff_coherence` contributed a hard zero reflecting the
  absent patch rather than anything the agent did, so adding `--min-diff-coherence` to
  a configuration converted an honest exit `2` into a build failure. Almost no current
  Cline session emits `apply_patch`, so this was the common case, not an edge one.
  **If you gate CI on `--min-diff-coherence` against a current-format trace, that job
  changes from red to a usage error.** That is the point: it verified nothing either
  way. A malformed patch still fails, because the gate keys on whether a patch was
  present rather than on whether the score was zero.
- The rejected alternative, recorded so it is not silently retried: making
  `DiffCoherenceScore.score` a `float | None` so the scorer itself abstains. It would
  fix the meaning everywhere rather than only at the gate, but it reverses a decision
  the scorer defends deliberately, changes a public dataclass field type on a
  published package, and requires editing the frozen corpus profile, which pins
  `0/100` and a `malformed_patch` label for both no-`apply_patch` traces.
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
  CLI install command and corrects the stated download size.
- The README no longer claims the quickstart "walks you from installing Cline". It
  walks you from installing Clinescope, and now links out to Cline's own docs for
  the Cline CLI itself.
- The "Why Clinescope" paragraph no longer carries three comparative clauses about
  five other eval frameworks. Nobody had opened any of those tools when the clauses
  were written, which made this the largest unverified block in the repository, in
  the most-read paragraph on the front page. All five were chased to first-party
  sources on 2026-09-13 and each finding was then handed to a second reader whose
  only job was to break it. The narrow technical core held: none of DeepEval,
  promptfoo, Langfuse, Braintrust or UK AISI's Inspect ships a built-in scorer for
  patch grammar, for edit minimality, or for apply-failure recovery. That one
  sentence is what the README now says, and `docs/internal/COMPARISONS.md` owns the
  per-tool evidence with the source read and the date.
- **Two of the cut clauses were false, not merely unverified.** "promptfoo hands the
  diff scorer to you" is wrong: promptfoo ships a code-scanning product with a
  diffs-only pull-request scan and severity grading, needing no user-written
  assertion. And "Inspect grades SWE-bench by running the repo's tests against the
  files the agent edited" describes a mechanism the code does not have: it runs a
  fixed per-instance directive list rather than the repo's suite, applies no patch
  because the agent edits the checkout in place, reverts the agent's edits to any
  test file the dataset's test patch touches, and delegates the verdict to the
  upstream `swebench` grader. That scorer also lives in a different repository from
  `inspect_ai`.
- The paragraph now concedes an axis it previously implied it won. Two of the five
  check tool-call arguments and `tool_selection` does not, so the old sentence
  "DeepEval scores tool selection but not code patches or diffs" pointed the
  comparison backwards on the one capability it named.
- `tool_selection`'s docstring no longer describes the scorer as DeepEval's
  `ToolCorrectness` default. Two of the three words it used were wrong against the
  shipped release: the default is not name-only, because it compares tool name and
  `ToolCall.type` as of `python-v4.2.0`, and it is not set-based, because it is
  recall over expected tools and never penalises extra calls. The docstring now
  defines the metric shape as this project's own and cites DeepEval as the prior art
  it diverged from.

### Fixed

- A second audit, run by reading every claim against the code it describes rather
  than by grepping, reconciled nine more contradictions. The ones a reader would have
  acted on: `.claude/claude-security-guidance.md` said there is exactly one outbound
  network call when `judge.py` has two call sites, both to the same opt-in local
  endpoint, and told reviewers not to look further. `docs/internal/ARCHITECTURE.md`
  cited `docs/internal/INVARIANTS.md` as recording a cross-command exit-code
  invariant that file did not contain; the invariant is now written, and the pointer
  no longer restates its reasoning. `CLAUDE.md` named three `python -m` commands where
  four exist (`judge_multidraw` was missing) and its Layout tree listed 15 of 27
  modules, omitting `__main__.py`, which is the `clinescope` console-script target.
  `docs/quickstart.md` showed report headers with an unquoted session id and a
  double-quoted extension title, where the tool prints both quoted by
  `render_safety.quote_untrusted_text`. `docs/internal/INVARIANTS.md` said the
  labelling harness's content half "is not pinned by anything" when
  `tests/test_label_gold.py` does pin it, narrowly. `docs/internal/FACT-OWNERSHIP.md`
  claimed `REVIEW.md` points at the gate's exit-code owner when it restates the
  contract instead; both restatements are now recorded as known copies.
  `docs/usage.md` described `--all` as replacing "only the most recent" when the
  default picker shows the twenty newest.
- `docs/internal/TESTING-AND-CI.md` said the type checker is scoped to the package and
  the scripts directory. The configuration says that, but the build passes an explicit
  path and mypy then ignores its configured paths, so `scripts/` is never
  type-checked. Measured on this tree: 29 source files configured, 27 actually
  checked. The same file's description of the corpus provenance guard was narrowed to
  what the test can detect, since the source field it asserts on is self-declared.
- An internal-consistency audit reconciled 21 places where the repository
  contradicted itself. The ones a reader would have acted on:
  `docs/judge-validation.md` said Clinescope has four core scorers and that all of
  them are what `clinescope-gate` gates on, when five ship and the gate exposes
  three `--min-*` flags. `docs/quickstart.md` showed a four-row
  `clinescope-corpus` scorecard where the command prints six rows plus a verdict
  block, and said the tool reports whether patches were "committed cleanly" when
  `diff_coherence` reads grammar from the patch text and does not prove the patch
  applies. `docs/harness-gap.md` and `examples/harness-gap/README.md` carried no
  `editor_recovery` column, which recorded Granite's harness delta as zero on
  every scorer when the harnessed run in fact scores `editor_recovery 100/100`.
  `CONTRIBUTING.md` claimed 94 percent coverage, called its four commands "exactly
  what CI checks" when CI also dogfoods `clinescope-gate`, and recommended
  `pip install -e .` inside a worktree, which `CLAUDE.md` forbids because it
  repins the shared virtualenv for every other worktree. `CLAUDE.md` itself said
  both recovery scorers abstain and report `n/a` on an empty trace, when
  `editor_recovery` is omitted entirely and prints no line at all, and said the
  three `apply_patch` scorers "go silent" on an `editor` trace when
  `diff_coherence` hard-zeros with its reason. `.claude/claude-security-guidance.md`
  called `release.yml` the only path here that reaches a third party, which stopped
  being true when the two Claude workflows landed. No scorer, exit code, threshold,
  test assertion or published figure changed value.
- `CONTRIBUTING.md` now warns that a pull request from a fork cannot pass the
  required `claude-review` check, because GitHub withholds secrets from fork runs
  on a public repository. The fork path stays documented; it just needs a
  maintainer to land it.
- `docs/judge-validation.md` no longer lists `judge_multidraw --report-only` under
  "Reproduce it yourself (no model call)". Its cache is not committed, so on a
  fresh clone it exits `2`, and building the cache makes live model calls.
- Quickstart step 2 no longer tells the reader to pass `--timeout 120`, and no
  longer claims Cline's default request timeout is 30 seconds. Both were wrong, and
  together they caused the failure the step exists to prevent. `--timeout` defaults
  to `0`, meaning no cap, and it aborts the whole run rather than one request
  (`apps/cli/src/commands/program.ts` line 61 and `apps/cli/src/runtime/run-agent.ts`
  lines 314-325 at cline/cline `4f836ae7d0ed29ece7ef4a2a478deb470fdd056e`). Cline
  raised its Ollama response-start default to five minutes on 2026-08-01 precisely
  because a large model's cold load takes minutes
  (`sdk/packages/llms/src/providers/vendors/ollama.ts` lines 49-65). Capping a 13 GB
  model's whole run at 120 seconds aborts it and leaves an empty trace, which tells
  the reader nothing about their agent.
- The step's verification note now says what was actually checked, the `cline auth`
  flags against CLI 3.0.57, instead of vouching for the whole section.
- Every surviving reference to the 30-second Ollama timeout is now dated as a property
  of the conditions a capture ran under, not as current Cline behaviour:
  `docs/harness-gap.md`, `examples/harness-gap/README.md` (which ships as package data)
  and the `tests/test_harness_gap_capture.py` docstring and comment.
- Four places said an empty or no-tool-call trace scores "0/100 across the board" or
  "on everything". That reports an abstention as a zero, which is the error #89 and
  #91 were written to remove. An empty trace hard-zeros `tool_selection` and
  `diff_coherence` and abstains with `n/a` on `diff_minimality` and `apply_recovery`,
  verified by running it.

### Known limitation

- `editor_recovery` is report-only in this release. It renders in the `clinescope`
  report and feeds `--advice`, but `clinescope-gate`, `python -m clinescope.compare`
  and `clinescope-corpus` do not read it yet, so an editor-only session has no
  gateable signal. Wiring it into the gate is deliberately deferred until someone
  gates CI on one.
- There is no shape scorer for `editor`, only this trajectory one. A candidate
  design exists and was not shipped, because every real `editor` replacement call
  available scores clean under it, so the check would have been unexercised by
  construction. The evidence is exactly TWO such calls, and both are committed here:
  one in `examples/harness-gap/granite-harness.messages.json` and one in
  `examples/live-granite-editor-recovery.json`. Each file is byte-identical to the
  session it was captured from, so counting the sessions and the committed examples
  separately double-counts them.
  The first of the two is the clearest argument for the design's most contested
  choice, not penalising identical lines at the edges of a replacement: it is a plain
  append whose `old_text` and `new_text` share a three-line leading run, so a
  definition that counted edge runs would have flagged a correct edit.

### Security

- Two stderr sinks in the `--vscode` discovery flow printed a trace-derived path
  without neutralising it, against the rule stated in `CLAUDE.md` and
  `.claude/claude-security-guidance.md`: the extension load-error line in
  `__main__.py`, and the two corrupt-file warnings in
  `extension_discovery._read_json_list`. Both take their path from a task directory
  name off disk, and both run before any scorer line exists, which is the position an
  escape sequence needs in order to overwrite the scores. Both now route through
  `render_safety.quote_untrusted_text`, and `tests/test_render_safety.py` covers each
  with a hostile path. The escaping rule was previously documented as universal while
  these two did not follow it.
- `label_gold.py` still prints lifted patch text to the labeller's terminal
  unescaped. That is now written down as a deliberate exception rather than left as an
  undocumented gap: escaping it would make the patch unreadable and defeat the
  labelling task, its items resolve to committed `examples/` traces this repository
  owns, and the blind-render test pins the patch as shown verbatim.
- Every GitHub Action is now referenced by a full 40-character commit SHA instead of
  a mutable tag or branch, with the readable version kept in a trailing comment.
  Seven references moved: five in `release.yml` and two in `ci.yml`. This closes the
  path where an upstream tag is repointed and new code runs inside the release
  workflow. The build job matters as much as the publish job even though only the
  latter holds `id-token: write`: build hands `dist/` to publish through artifact
  upload and download, so a compromised build action can alter the wheel before the
  authenticated upload happens.
- The trade this makes, recorded rather than discovered later: Dependabot continues
  to open version-update PRs for a SHA-pinned action, but it does not raise
  vulnerability alerts for one. Expect more update PRs too, since a moving major tag
  such as `@v7` silently absorbs a patch release while a pinned SHA does not.
- No package behaviour changed. No scorer, score, exit code or public type moved.
- Text taken from a trace is now escaped before it is rendered. A trace is untrusted
  input, and the bug-report template asks a reporter to paste one, so a `sessionId`,
  a file path, a tool name or an extension task title can carry terminal control
  sequences. Those land ahead of the scorer lines, where erase-line and cursor
  movement can overwrite them and show a score the tool never computed. For a tool
  whose whole output is a score, that is an attack on the one thing it exists to do.
  Exit codes and the `clinescope-gate` decision were never affected.
- **Output change to expect:** trace-derived values now render quote-delimited, so a
  header reads `session 'abc-123'` and a Windows path reads `'C:\\work\\calc.py'`.
  Scores, verdicts and exit codes are unchanged. This matches how the recovery
  scorers have always rendered paths inside their violation strings.
- The advisory judge now treats the patch text it is given as untrusted on both sides
  of the model call. Patch text comes from a trace, so whoever wrote the trace chose
  it. On the way out, a `VERDICT:` line is accepted only as the last non-empty line of
  the answer, the one position the judge's own instructions specify; it used to scan
  every line bottom-up, so a sentinel sitting anywhere in the answer counted. On the
  way in, the patch is fenced between a `<<<BEGIN PATCH <tag>>>` line and a
  `<<<END PATCH <tag>>>` line whose tag is a sha256 prefix of the patch itself, and the
  system prompt states that the fenced region is data rather than instruction. The tag
  is derived from the content so that emitting a byte-identical closing marker would
  mean writing the patch's own digest into the patch, which changes the digest: a
  64-bit fixed-point search, not a preimage attack on sha256. Previously the patch was
  interpolated with no delimiter at all. The fence is honoured by the model rather than
  enforced by code, so an unforgeable tag is necessary and not sufficient; it raises
  the cost of steering an advisory label rather than guaranteeing anything.
- **This is a measurement-integrity change, not a security fix.** The judge is
  advisory-only and pinned out of `clinescope-gate` at the AST level, so no pass/fail
  signal was ever reachable this way. What a steered verdict could reach is the
  published agreement figure.
- **The agreement figure moved, and both numbers are published rather than the old one
  being replaced.** Fencing changes what the model is asked, which invalidates every
  cached verdict, so all 50 were recomputed against a live `gpt-oss:20b` in this same
  change. Cohen's kappa went from **0.0496, 95% CI [-0.1200, 0.2175]** to **0.0433,
  95% CI [0.0000, 0.1503]**, N=50 both times, with 0 unparseable and 0 errors. Recall
  of human-WASTEFUL patches fell from 3 of 24 to 1 of 24.
- **Do not read the new interval as an improvement.** It stops at zero instead of going
  negative because the judge answered WASTEFUL exactly once in fifty; a bootstrap
  resample that omits that single item scores exactly zero, and 36% of resamples do.
  The bound reflects the judge answering almost one class, not a signal.
- **The difference is not attributed to the fence.** Each figure is one draw, and this
  model flips labels run-to-run at temperature 0. A gap of 0.0063 sits inside that
  noise. Both runs agree on the finding that matters: the judge is at chance and is
  heavily biased toward calling patches fine, so it stays out of the gate.

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
