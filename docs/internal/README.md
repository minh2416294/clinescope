# Internal contract documents

Agent-facing documentation for anyone about to change this repository. It exists so a session
can understand the project by reading, rather than by running a research pass over the tree and
paying for the same knowledge again.

`docs/` at the root is user-facing product documentation and stays that way. This subdirectory
is the other thing: the contracts, boundaries and invariants a contributor needs before
touching code, none of which somebody who ran `pip install clinescope` ever needs.

## Read by situation, not cover to cover

| About to | Read |
|---|---|
| change any code | `docs/internal/INVARIANTS.md` first |
| write a sentence stating a number, a count, or a measured figure | `docs/internal/FACT-OWNERSHIP.md` |
| decide where new code belongs, or why a boundary is where it is | `docs/internal/ARCHITECTURE.md` |
| work out why a check failed, or why the environment is misbehaving | `docs/internal/TESTING-AND-CI.md` |

Reading everything here every time defeats the purpose. The cost this set removes is a research
pass; a habit of reading all of it just relocates that cost instead of removing it.

Escalate to a research pass when these files do not answer the question, not before, and when
that happens the answer belongs back in here.

## The rule every file here follows

**Name the owner. Do not restate what it says.**

`docs/internal/FACT-OWNERSHIP.md` owns that rule: what counts as a restatement, how a pointer has
to be written, which half of it a test can check, and where each recurring fact actually lives.

The rule is repeated here rather than only pointed at because it is the reason this directory
exists, and a reader who takes nothing else from this page should take that line. The wording is
`FACT-OWNERSHIP.md`'s, so if the two ever differ, that file is right and this one is stale.

## Owned elsewhere, referenced not restated

- What a scorer does and does not claim, per scorer: `LIMITATIONS.md`.
- The threat model and the review checklist that goes with it:
  `.claude/claude-security-guidance.md`.
- Review severity calibration for this repository, and what counts as a real finding here:
  `REVIEW.md`.
- Whether a feature should exist at all, and the procedure for killing an idea:
  `.claude/rules/scope.md`.
- Which metrics count, and when a threshold may be revised: `.claude/rules/measurement.md`.
- What may not be claimed about accumulated usage yet:
  `.claude/rules/user-data-instrumentation.md`.
- The honesty rule that governs every word written about this project, the file tree, the
  environment traps, and how a change ships: `CLAUDE.md`.
- Dev setup, the release procedure, and what a pull request should contain: `CONTRIBUTING.md`.
- The gold set's format, its blind labelling protocol, and its drift tripwire: `gold/README.md`.
- How this project was built with an agent, and the frozen-invariant discipline that came with
  that: `docs/building-with-agents.md`.
