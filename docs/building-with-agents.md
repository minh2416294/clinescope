# Building Clinescope with agentic tooling

Clinescope was built with an AI coding agent (Claude Code) doing much of the typing. That is worth
stating plainly, because Clinescope is itself a tool for catching where coding agents go wrong: a patch
that does not apply, a "done" with no tool call behind it, a whole-file rewrite where a two-line edit was
asked for. Building a correctness tool with an agent that makes exactly those mistakes only works if the
process assumes the agent will be wrong sometimes and is built to catch it.

This page documents that process: the guardrails, the checks, and the decisions that stayed with a human.
Every claim below points to something you can open in this repo and verify. Where a technique is a
personal working habit rather than a repo artifact, it is described as a habit, not dressed up as
evidence.

## What the agent did, and what it did not

The agent drafted code, wrote first-pass tests, ran searches across the tree, and produced draft prose. A
human set every scorer's definition and its honest boundary, decided what was in scope for each change,
owned every merge, and owned the reader-facing docs (this page included): reviewing an agent's draft,
correcting it, and deciding the published wording, rather than letting a draft ship unread.

The split is the whole point. An agent is good at the mechanical middle of a change: given a clear spec
and a failing test, it fills in the code. It is not the right owner of the decisions that are expensive to
get wrong: what a scorer is allowed to claim, whether a signal can be trusted, what ships. Knowing which
side of that line a task falls on is the skill; the rest of this page is how that line is drawn in
practice.

## Frozen invariants: the parts an agent may not touch

A small set of files are treated as frozen. The four scorers (`tool_selection`, `diff_coherence`,
`diff_minimality`, `apply_recovery`), the trace loader (`world_a.py`), the tool vocabulary
(`tool_vocab.py`), and the ingested golden fixture are held byte-identical from one change to the next
unless a change is specifically about them. An agent may draft new code around these files, add scorers,
or extend the CLI, but it does not get to quietly alter the definition of a score while doing something
else.

The core package also carries zero runtime dependencies: `dependencies = []` in
[`pyproject.toml`](../pyproject.toml). That is an invariant too. A convenient library an agent reaches for
mid-task is exactly the kind of change that looks harmless in a diff and quietly widens the install and
the supply chain, so a new runtime dependency is a decision that stops and gets made deliberately, not one
that rides along inside an unrelated change.

Verifying an invariant held is mechanical. Each frozen file's committed content is compared against `main`
by its git object hash (`git hash-object <file>` against `git rev-parse origin/main:<file>`), which is
exact and immune to the line-ending differences that make a raw checksum unreliable across checkouts. If
the hash matches, the file is untouched; if a change was meant to be docs-only, the scorer files not
appearing in the diff is the proof.

## The golden fixture is ingested, never edited

Clinescope validates its loader against a real Cline fixture. That fixture is ingested from a Cline
checkout; it is never copied into this repo and never edited. [`CONTRIBUTING.md`](../CONTRIBUTING.md) says
so directly: "Never edit or copy in Cline's own golden fixture; add your own small synthetic trace." The
reason is that a fixture you can edit is a test you can quietly make pass. If a loader change breaks the
fixture, the fix belongs in the loader, not in the fixture. Keeping it read-only and external removes the
temptation entirely, which matters most when an agent is the one proposing the change.

## Verification comes before the code

A change starts from a check, not from the code. For a scorer, the check is a trace plus the exact score
it should produce; the code exists to make that assertion pass. [`CONTRIBUTING.md`](../CONTRIBUTING.md)
states the rule for any contribution: "A scorer change needs a trace + its expected score ... a scorer
without a test proving its output isn't reviewable."

The expected value is pinned to what the specification says the score should be, never copied from what
the code happens to print. Copying the observed output turns a test into a mirror: it passes no matter
what the code does, including when the code is wrong. A test is only worth keeping if it can fail, so each
new behavior test is confirmed to fail before the code makes it pass. That is a habit, not a repo file,
but its result is visible: the tests exist, and they assert specific numbers.

Two public gates back this up. The real-trace corpus ([`examples/corpus/`](../examples/corpus/README.md))
scores six real captured Cline runs against hand-labeled expected scores and exits non-zero on any
mismatch, so a scorer change that shifts a real score is caught rather than merged. And CI runs the suite
under a coverage floor: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) fails the build if line
coverage drops below 90 percent, across Python 3.11, 3.12, and 3.13, alongside lint, format, and type
checks.

## The centerpiece: an AI signal, measured and then distrusted

The clearest example of a decision that stayed with a human is the LLM judge.

Clinescope ships one optional LLM judge as an auxiliary signal for `diff_minimality`. The tempting move is
to trust it: an LLM reading a patch feels like it should be able to tell a wasteful edit from a tidy one.
Instead the judge was measured against a human-labeled gold set using Cohen's kappa, chance-corrected
agreement. It agreed with the human labels only at chance level. So it is kept out of the pass/fail gate
entirely: `clinescope-gate` fires on the deterministic scorers and never on the judge.

The full measurement, the confusion matrix, and how to reproduce the number with no model call are in
[`docs/judge-validation.md`](judge-validation.md); the boundary is restated in
[`LIMITATIONS.md`](../LIMITATIONS.md). What matters here is the shape of the decision. An LLM produced a
signal that looked plausible; it was checked against ground truth; it failed the check; it was excluded
from anything that gates a result. That is the same discipline applied to the agent that writes the code:
a plausible-looking output is not a trusted one until something independent has confirmed it.

Growing the gold set from a smaller, easier set to a larger, balanced, blind-labeled one actually lowered
the measured agreement. That result was kept and published rather than quietly reverted to the flattering
earlier number, because the point of measuring a signal is to learn what it is worth, not to defend a
figure.

## A human owns every merge and every release

Nothing merges or ships on its own. Every change lands through a pull request that runs CI before it can
merge; [`CONTRIBUTING.md`](../CONTRIBUTING.md) describes the flow (branch, open a PR against `main`, CI
runs on the PR), and CI itself is [`.github/workflows/ci.yml`](../.github/workflows/ci.yml). Merging is a
human step, so a change does not skip review.

Releases are the same. [`.github/workflows/release.yml`](../.github/workflows/release.yml) publishes to
PyPI only when a human publishes a GitHub Release; a push, a PR, or a tag alone does nothing. It uses
Trusted Publishing over OIDC, so there is no PyPI token stored in the repo to leak, and the upload runs in
a protected `pypi` environment where a required-reviewer approval can gate it. The consequential,
hard-to-reverse action, putting a version in front of every user, is deliberately the one a person has to
take.

## Adversarial review and non-vacuous tests

Before a change is called done, it is reviewed against itself: a separate pass that tries to find what is
wrong with the diff rather than confirm it is fine, checking that the scope is what was claimed, that the
frozen files were not touched, and that the honest caveats were not softened for readability. Reviewing
for what a change breaks, not for reasons to approve it, is a different job from writing it, which is why
it is a distinct step.

Tests get the same adversarial treatment: a behavior test that cannot fail is worse than no test, because
it reports safety that is not there. Each one is checked to actually fail when the behavior it guards is
broken, so that a green suite means the checks ran, not merely that they exist.

## What this page is not claiming

It is not claiming the agent built Clinescope on its own; a human owns the design, the invariants, the
merges, and the published words. It is not claiming a productivity multiplier; no such number is measured
here, so none is offered. And it is not claiming the scorers are more than they are: each one is
deliberately narrow, and exactly what it does and does not measure is spelled out in
[`LIMITATIONS.md`](../LIMITATIONS.md).

The claim is narrower and, hopefully, more useful: a correctness tool can be built largely with a coding
agent if the process assumes the agent will sometimes be wrong and is built to catch it, and if the
decisions that are expensive to get wrong stay with a human. The evidence for that is the repo itself.
