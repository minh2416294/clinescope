# Fact ownership

## Why this file exists

An audit of this repository found that where two parts of it disagreed about what is true,
the cause was almost always the same: a fact had been copied into many places and no file
declared which copy was authoritative. Correcting the copies fixes the symptom. Naming an
owner is the only thing that fixes the cause.

This file is that naming. It carries no values, on purpose. A document that restates a
figure in order to say where the figure lives has become another place for that figure to
drift, which would make this file part of the problem it was written to solve.

## The rule

**Name the owner. Do not restate what it says.**

- Every recurring fact has exactly one owning file.
- Everywhere else points at that file by name plus a stable heading or symbol. Never by line
  number: a line number is itself a copied value, and it moves whenever anything above it is
  edited, including in a change that touches no code at all.
- What must not be restated is more than a figure. The owner's reasoning counts as well: writing
  out why a rule exists, in a sentence that also names the file owning that rule, is a copy with a
  citation attached to it. That is spelled out rather than left implied because it is the form the
  rule was first broken in, one commit after it was written.
- A second statement of a fact is allowed only when it is deliberate, has a reason, and is
  listed under "Deliberate second statements" below. Anything else is a copy.

`tests/test_docs_internal_contract.py` enforces the mechanical half: it rejects a line-number
pointer anywhere in this directory and asserts that every repository path named here still
resolves.

The other half cannot be a grep, and that is worth knowing before trusting a green check. A
restated reason carries no figure, no percentage and no positional pointer, so every mechanical
check passes on it. `CLAUDE.md` makes the same point about the limits of its own honesty grep, in
the paragraph directly after the grep command. What caught it here was comparing this directory's
phrasing against the owner files and looking for shared runs of words. That is a read, and it
stays a read.

## Who owns what

| Fact | Owner | Note |
|---|---|---|
| The judge's agreement with the human labels, its interval, its sample size, and its confusion matrix | `docs/judge-validation.md` | The full measurement. `LIMITATIONS.md` carries the reader-facing summary and points here. |
| The superseded judge measurement taken before the prompt was fenced | `docs/judge-validation.md`, under "The previous measurement, for comparison" | A separate fact from the current one. They must never be conflated or averaged. |
| The gated proxy scorer's agreement with the same labels, and its recall | `src/clinescope/gate.py`, in the help text for its minimality threshold flag | Deliberately mirrored in a test. See below. |
| What each scorer checks, and the caveat on each | `CLAUDE.md`, at the scorer table (heading quoted verbatim below) | `LIMITATIONS.md` owns the long form, one subsection per scorer. |
| The named required checks on the default branch | `CLAUDE.md`, under "Shipping a change" | Undercounted elsewhere in this project's history more than once. |
| The gate's exit-code contract, and which confusions between codes are forbidden | `src/clinescope/gate.py`, module docstring | `REVIEW.md` and `.claude/claude-security-guidance.md` both treat a break in it as a real finding, and both point here. |
| The line-coverage floor that fails the build | `pyproject.toml`, coverage report settings | A different fact from the one below, despite sharing a word. |
| The coverage figure the suite currently measures | `pyproject.toml`, in the comment beside the floor it justifies | See "Known copies, not yet collapsed" below. |
| Which failure modes the committed corpus covers, and which is a stated gap | `examples/corpus/README.md`, under "Coverage" and "Known gap" | The composition, not a count, is what the suite asserts. |
| The gold set's size and how many items carry a human label | `gold/README.md` | `CLAUDE.md`, under "Layout", owns why those labels may never be machine-written. |
| The gate's threshold flags | `src/clinescope/gate.py` | There is no flag for the trajectory scorer added most recently; `LIMITATIONS.md` says so. |
| The advice taxonomy's label set | `src/clinescope/advice.py` | Enumerated once, at the enum. |
| The released package version | `pyproject.toml` | Deliberately mirrored in the package. See below. |
| The pinned upstream Cline commit, and the tool-name vocabularies taken at it | `src/clinescope/tool_vocab.py` | Goes stale when Cline moves, with nobody here touching a file. |
| The pinned commit for each workflow action | the `uses:` line in each file under `.github/workflows/` | Rewritten on a schedule by the dependency updater, so no prose should quote one. |
| The digest and size pinning Cline's ingested fixture | `tests/test_fixture_drift.py` | Bumped only as a reviewed response to a deliberate upstream change, never to clear a red test. |
| The run length at which a retyped block counts as a blind rewrite | `src/clinescope/diff_minimality.py` | Also interpolated into the violation message, so a second copy would contradict what a user reads. |
| The interpreter versions the build is tested against | `.github/workflows/ci.yml`, the matrix | `pyproject.toml` declares a floor, which is a different fact. |
| The expected surviving hit count for the honesty grep | `CLAUDE.md`, in the honesty rule | Notable for having no copies anywhere. It is structurally safe, and worth leaving that way. |

The heading quoted verbatim, so the pointer above resolves by search: **"The five scorers, and
the honest caveat on each"**. It is reproduced exactly because a paraphrased heading is not a
locator.

**Quoting a heading is not a restatement, and that holds wherever one appears in this directory.**
The rule above asks for a file plus a stable heading, so a quoted heading is a locator, and it is
quoted rather than paraphrased because a paraphrase does not resolve. What the rule forbids is
carrying across what the owner *says* under that heading. If you are checking this directory for
copies, judge the sentences around a quoted heading rather than the heading itself.

**A pointer may quote only the front of a heading, when the rest of it carries a fact somebody
else owns.** The pointer to "Known gap" in `examples/corpus/README.md` is that case: the remainder
of that heading names which failure mode the gap is, and naming it here would be the copy this
file exists to prevent. So quote as much of a heading as finds it by search, and stop early when
going further would carry a fact across.

## Deliberate second statements

Each of these states a fact in a second place on purpose. What makes them pins rather than
copies is that a test fails when the two disagree, or the comment beside them says why the
duplication is load-bearing.

- **The gated proxy's agreement figure and its layout-dependence sentence** appear in
  `src/clinescope/gate.py`'s help text and are asserted by `tests/test_gate.py`. The reason the
  duplication is load-bearing is written above those tests. The test is what stops it being
  quietly dropped.
- **The canonical rule line above** appears again in `docs/internal/README.md`, because a router
  a reader abandons after the first screen still has to carry the one rule this directory exists
  for. `tests/test_docs_internal_contract.py` compares the two verbatim. Before it did, the two
  disagreed for three merged pull requests: this file widened the rule and the README kept the
  older wording, which is the drift this whole directory is meant to prevent, occurring in the
  statement of the rule against it.
- **The package version** appears in `pyproject.toml` and in `src/clinescope/__init__.py`,
  and `tests/test_version_consistency.py` is the only thing comparing them. Its docstring
  explains what bumping one and forgetting the other would ship.

## Known copies, not yet collapsed

Recorded rather than fixed, because collapsing them is a separate change with its own reasons
to weigh.

- The **measured coverage figure** appears both in `pyproject.toml`, beside the floor it
  justifies, and in `CONTRIBUTING.md`, where a contributor reads it. The second is a copy
  rather than a pin: nothing compares them, and they have already disagreed once.

## Terms this repository uses that no file in it defines

A real finding, recorded here rather than resolved, because resolving it means editing
docstrings across the package and the suite.

Several modules explain a decision by referring to **"the charter"**, including its
"criterion 3", its "GOAL-2 spec", and a phrase about scores being glued to the setup. Nothing
in this repository is called the charter, and searching for a definition finds none. The files
that cite it are `src/clinescope/advice.py`, `src/clinescope/agreement.py`,
`src/clinescope/corpus.py`, `src/clinescope/diff_coherence.py`,
`src/clinescope/diff_minimality.py`, `src/clinescope/gate.py` and `src/clinescope/judge.py`.

Several others cite rule identifiers of the form R followed by a digit, again with no
definition anywhere in the tree: `src/clinescope/gold.py`, `src/clinescope/world_a.py`,
`tests/test_apply_recovery.py`, `tests/test_fixture_drift.py`, `tests/test_live_capture.py`
and `tests/test_loader.py`.

And `REVIEW.md` cites a review-severity file by an absolute path outside the repository,
which a fresh clone cannot resolve.

**What to do when you hit one.** Treat the reference as unresolvable and read the surrounding
docstring instead. In every case checked, the docstring states the actual design reason on its
own, and the citation is a provenance note rather than the substance. Do not go looking for
the charter, and do not infer its contents from the citation.
