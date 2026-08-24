# CLAUDE.md - clinescope

Project instructions for any Claude Code session opened in this repo. Written to be read
standalone: you need no other machine, account or file to follow it.

## Precedence

This file **supplements** a contributor's own global Claude Code configuration. It never
contradicts one. Where a project rule and a global rule would collide, this file says so
explicitly and defers to the global one.

Three things bind inside this repo regardless of your global config, because they are
properties of the project rather than of a workstation:

1. **The honesty rule** below. It governs every word written about this tool.
2. **`dependencies = []`.** Zero runtime dependencies is a shipped guarantee, not a preference.
3. **Integration is by pull request.** `main` takes no direct pushes and needs three green
   checks. See "Shipping a change".

## What this is

**A Cline eval harness.** It scores a coding agent's edits and tool trajectory from a real
Cline execution trace, using deterministic zero-LLM scorers.

What it deliberately does not do, and the procedure for changing that, live in
[`.claude/rules/scope.md`](.claude/rules/scope.md). Read that before proposing a feature.

Two more rule files govern work here:

- [`.claude/rules/measurement.md`](.claude/rules/measurement.md): which metrics count, what a
  false positive looks like, and the rule against moving a threshold after seeing the data.
- [`.claude/rules/user-data-instrumentation.md`](.claude/rules/user-data-instrumentation.md):
  what to instrument, and the gate on claiming anything about accumulated usage.

## The five scorers, and the honest caveat on each

All are deterministic and use no LLM. Each names what it actually checks, because the gap
between the check and the thing you might assume it checks is where every false claim starts.

| Scorer | What it computes | The caveat |
|---|---|---|
| `tool_selection` | Name-only recall of a caller-supplied expected set. | Name-only. It does **not** check tool arguments. |
| `diff_coherence` | Grammar coherence of the first `apply_patch` against Cline's `*** Begin Patch` grammar. | Grammar read from the patch **text alone**. It is **not** apply-against-a-real-file success. |
| `diff_minimality` | Flags blind whole-block rewrites: 3 or more deleted lines immediately retyped with no anchor. | Reference-free, and detects **one** bloat shape. Its score also depends on file layout. |
| `apply_recovery` | Of every `apply_patch` Cline marked failed, the fraction recovered by a strictly-later confirmed one. | Trajectory recovery, **not** fix-correctness. |
| `editor_recovery` | The same, ported to Cline's `editor` tool: of every failed `editor` call, the fraction re-touched by a strictly-later confirmed `editor` call on the same path. | Trajectory pattern only. Blind to cross-tool recovery, and path matching is literal, so one file spelled two ways is a false miss. A low score means "did not recover via a same-path confirmed editor call", not "did not recover". |

**Which scorers fire depends on the trace.** The three `apply_patch` scorers grade
`apply_patch` grammar only. Almost no current Cline session emits `apply_patch`: all five tool
presets set `enableApplyPatch: false`, and only two routing rules flip a session back to it (an
`openai-native` provider, or a model id containing `codex` or `gpt`), both of which also
require `act` mode. Everything else emits `editor`, where the three `apply_patch` scorers go
silent and `editor_recovery` is the one that produces a number.

**An empty or no-tool-call trace does not score 0 across the board.** `tool_selection` and
`diff_coherence` hard-zero. `diff_minimality` and the two recovery scorers **abstain** and
report `n/a`. Reporting an abstention as a zero is a specific, recurring error in this repo's
history. Before writing any sentence about what a trace scores, run the tool on it.

## The honesty rule (binds every word written about this project)

Never describe clinescope as having users, traction, or a working judge it does not have.
**Today: 0 users, 0 revenue.** The optional LLM judge is chance-level (Cohen's kappa 0.0496,
N=50, 95 percent CI -0.1200 to 0.2175, which crosses zero) and stays **out** of any pass/fail
claim.

**Banned lines:**

- "our grader agrees with human reviewers"
- calling the scorers diff **quality** or **correctness** scorers

They check `apply_patch` grammar, one bloat shape, and Cline's own error verdict. Name the
specific deterministic check instead. Warn the moment a claim is written that cannot be
defended with a real number.

**The mechanical half of this rule is a grep. Run it before any release or docs change:**

```bash
grep -rn -i -E "diff[- ]quality|quality of (the )?(diff|patch)|[a-z-]*(quality|correctness)[- ]scorer" \
  --exclude-dir=.git --exclude-dir=.venv --exclude-dir=htmlcov --exclude-dir=__pycache__ --exclude-dir=dist .
```

It deliberately does not match most legitimate disclaimers ("not argument correctness", "does
not verify semantic correctness") or DeepEval's `ToolCorrectness` API name.

**Expected surviving hits, as of 2026-08-24: five.** Three in `CHANGELOG.md` (frozen history).
One in `LIMITATIONS.md`, under the heading "What Clinescope does NOT claim", stating that no
shape or quality scorer exists for the `editor` tool. That one **denies** a capability rather
than claiming one, so it is correct and stays. And one in this file, in the paragraph you are
reading, because describing the pattern necessarily contains it.

Anything beyond those five is a real hit: read it. If you edit this paragraph, re-count.

**The grep is only the mechanical half.** It cannot catch a quality judgement phrased in
ordinary words: version 1.2.1 shipped "catching messy code rewrites" on the PyPI front page and
the grep passed. Read the prose too.

**A claim of repo-wide completeness needs a repo-wide `git grep`,** not a grep of the folders
you happened to think of. Two false claims shipped from exactly that mistake, because the check
covered `docs/`, `README.md`, `LIMITATIONS.md` and `CHANGELOG.md` while stale text survived in
`examples/` and `tests/`.

## Scope rules that gate new work

The full procedure is in [`.claude/rules/scope.md`](.claude/rules/scope.md). Two of its gates
are quoted here because they fire before any code is written.

**Every new feature must be required by a real user's feedback.** A feature proposed without a
named specific reason (it supports a user, it gets a user, or it is something a user will pay
for) gets challenged, not built.

**Answer all seven before building. Cannot answer all seven means do not build it:**

1. Who wants this, named, or is it the author wanting to overcomplicate?
2. Why build it: easier to use, better output, gets or keeps a user, or someone pays for it?
3. What pain does it kill? Cannot name one means it is a vitamin.
4. What breaks if it is not built? Nothing means do not build it.
5. Is it the smallest thing that solves the pain, or is it gold-plating?
6. Does it serve the narrow Cline-native wedge, or quietly broaden it?
7. Can you name the user who will notice it shipped? Nobody means nobody wanted it.

Four further standing rules, in short form:

- **Go narrow first.** Stay Cline-native. "Eval for any AI coding agent" is a direction, not
  today's product.
- **Solve a real pain,** not a nice-to-have.
- **Prefer starting from a real user's words.** A prompt, not a veto.
- **Never position this as a generic AI eval platform.** The defensible thing is Cline-native,
  real-execution-trace, per-format diff and trajectory scoring.

## Commands

```bash
pip install clinescope

clinescope --demo                                        # score a bundled real trace, zero args
clinescope <trace.json> --expected read_files apply_patch --advice
clinescope --vscode                                      # find and score a VS Code extension session
clinescope-gate <trace.json> --min-diff-coherence 0.75   # CI gate: exit 0 pass, 1 fail, 2 usage error
clinescope-corpus                                        # the real-trace regression corpus
python -m clinescope.compare A.json B.json               # multi-trace scorecard
python -m clinescope.judge_run --report-only             # recompute kappa, no model call
```

Three console scripts exist: `clinescope`, `clinescope-gate`, `clinescope-corpus`. `compare`,
`judge_run` and `label_gold` are `python -m clinescope.<module>` only.

**Where a trace comes from.** The Cline CLI writes
`~/.cline/data/sessions/<id>/<id>.messages.json`, and `cline history --json` lists each session
with its `messagesPath`. The VS Code extension instead writes `api_conversation_history.json`
under its per-OS globalStorage, which `--vscode` discovers automatically.

## Development

```bash
pip install -e ".[dev]"

ruff check .
ruff format --check .
mypy src
pytest -q --cov=clinescope --cov-report=term-missing --cov-fail-under=90
```

Those four are exactly what CI runs, on Python 3.11, 3.12 and 3.13. Coverage below 90 percent
fails the build. `mypy` runs strict and rejects a bare `# type: ignore`: every suppression must
name its error code.

## Environment traps

Each of these cost real time. They are written in the narrow form that was actually verified,
not the broad form that sounds scarier.

**The editable install pins to one checkout, and a worktree does not get its own.**
`pip install -e .` writes `_editable_impl_clinescope.pth` into the shared `.venv` pointing at
whichever tree ran it. That pin is global to the venv.

The failure mode is **silent**, which is worse than a crash. From inside a git worktree,
`python -m clinescope` run with the main checkout's interpreter exits 0 and prints a perfectly
plausible report, having imported the **main checkout's** source rather than the worktree's. You
can edit code in a worktree, run the CLI, watch it pass, and have tested the wrong tree.

```bash
# Confirm which tree you are actually running:
python -c "import clinescope; print(clinescope.__file__)"

# In a worktree, force the local source:
PYTHONPATH=<worktree>/src python -m clinescope ...
```

`pytest` is safe either way, because `pyproject.toml` sets `pythonpath = ["src"]` and resolves
to the tree it runs in. **Do not run `pip install -e .` inside a worktree** to fix this: it
repins the shared venv, and removing that worktree later leaves the pin aimed at a directory
that no longer exists, silently breaking `python -m clinescope` for every later session. If that
has already happened, repair it with a single `pip install -e .` in the main checkout.

**A fresh worktree has no `.venv` and no `.claude/`.** Both are ignored, so neither is copied.

**Line endings.** `.gitattributes` pins the working tree to LF (`* text=auto eol=lf`), because
the gold set and example traces are a versioned contract read by a byte-preserving writer
(`src/clinescope/label_gold.py`). Git for Windows sets `core.autocrlf=true` at system level and
the attribute overrides it. But Python's `Path.write_text` still emits CRLF on Windows, so a
script that reads a source file, edits it and writes it back leaves the whole file dirty in
`git status` even when `git diff` shows nothing. Restore with `git checkout -- <file>` before
staging, or write bytes, or pass `newline=""`.

**Verify a frozen fixture with `git hash-object`, never a raw sha256** taken across two working
trees. The same committed blob can render differently on disk, and a raw hash then false-fails.

**Some harnesses block writes while you are on `main`.** If a write is refused for that reason,
open a worktree on a feature branch rather than working around it. That is the right shape here
anyway, since `main` takes no direct pushes.

## Shipping a change

`main` is protected: no direct pushes, and a pull request needs three green checks
(`test (3.11)`, `test (3.12)`, `test (3.13)`). A red check blocks the merge. Do not merge past
one.

Conventional commit subjects. Branches are short kebab-case, for example
`fix/abstention-not-zero`.

**The docs update rides the same commit as the code.** Never let a behaviour change and its
README, CHANGELOG or CLAUDE.md update land separately. Drift is a latency problem, and
same-commit leaves no window for a stale claim to survive in.

## Layout

```
src/clinescope/        the package
  world_a.py           trace loading (Cline CLI messages.json v1)
  cline_extension.py   VS Code extension trace loading
  tool_selection.py    scorer
  diff_coherence.py    scorer
  diff_minimality.py   scorer
  apply_recovery.py    scorer
  editor_recovery.py   scorer
  report.py            rendering
  advice.py            rule-based zero-LLM coach
  gate.py              clinescope-gate CLI
  corpus.py            clinescope-corpus CLI
  judge*.py            opt-in advisory judge, kept out of the gate
examples/              committed real traces (frozen test artifacts)
gold/                  human-labeled gold set (frozen)
tests/
.claude/rules/         project rule files, committed
```

`examples/` and `gold/` are **frozen contracts**. Do not regenerate or reformat them.

## Known limits

`LIMITATIONS.md` at the repo root is the canonical, shipped version. In short: Cline only, in
two trace formats; each scorer's caveat above; the judge advisory-only; the regression corpus
covers 3 of the 4 failure modes, with `blind_rewrite` a stated gap; and the judge was validated
on one local model on small edits, so robustness across models is not claimed.
