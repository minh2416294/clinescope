# Invariants

Things that must stay true, what breaks when they do not, and which of them an agent must
not decide alone. Ordered by blast radius.

Each entry names the file that owns the detail and does not restate it. That covers the owner's
reasoning, not only its figures: writing out the reason a rule exists, in a sentence that also
names the file owning that rule, is a copy with a citation attached to it. Where an entry has
nothing to add beyond the pointer, it says so and stops.

**No-agent zone** marks an invariant where the right move on finding a reason to change it is
to stop and ask a person, not to weigh it up and proceed. The label is about who decides, not
about how hard the change is: most of these are one-line edits, which is exactly why they are
dangerous.

## Zero runtime dependencies

`CLAUDE.md` states this in its opening Precedence list, `pyproject.toml` is where it is declared,
and `REVIEW.md` and `.claude/claude-security-guidance.md` both rest on it.

What this entry adds is the blast radius. Adding a dependency falsifies all of those at once, and
nothing would catch it: the dependency updater watches workflow actions only, precisely because
the runtime list is empty.

**No-agent zone.**

## An unresolved tool verdict is a third state, never a success

Cline's own pass or fail verdict on a tool call can be absent or explicitly null. The loader
only accepts a real boolean as a verdict, the shared verdict helper returns nothing when it
cannot resolve one, and the recovery scorers require a confirmed non-failing call rather than
merely the absence of a failure.

The obvious tidy-up is to default the missing case to false so the field becomes a plain
boolean. That reads as type hygiene and is the exact change that breaks what the recovery
scorers are sold on: with it, truncating a trace immediately after any retry would read as a
confirmed recovery, so a perfect recovery score could be manufactured by cutting the log
short. Every test that uses a complete trace would still pass.

Owners: `src/clinescope/world_a.py` for the loader's handling, `src/clinescope/tool_verdict.py`
for the resolution helper and its fail-closed rule.

**No-agent zone.**

## Whether a scorer can abstain is a property of its type

Each scorer's result declares its score either as a plain float or as an optional one, and
that declaration is the whole mechanism: a plain float cannot express "not applicable", so
the scorer reports a loud zero instead. The strict type checker configured in
`pyproject.toml` is what enforces it.

"Make this scorer abstain like the others" is therefore not a one-line change. It is a public
type change that rewrites the report contract and removes the loudness the zero exists to
provide. Going the other way forces a fabricated number where the metric is genuinely
undefined, which is the abstention-reported-as-zero error `CLAUDE.md` warns about by name.

Owner: each scorer module in `src/clinescope/`, at its result dataclass.

**No-agent zone.**

## The gate decides applicability on a call count, not on a score

Because one scorer cannot abstain, something else has to carry "this did not apply to this
trace". That signal is a call count published on each result in the patch-grammar family,
and `src/clinescope/gate.py` keys its not-applicable verdict on the count rather than on the
score. This is what keeps a malformed patch that really is present failing the build, instead
of being excused along with the traces that contain no patch at all.

The field looks like an incidental counter surfaced for the report, so dropping or renaming
it on one result reads as safe cleanup. It is load-bearing for the gate's exit behaviour.

Owner: `src/clinescope/gate.py`.

## Position in the loaded tool-call sequence is time

Both recovery scorers implement "a strictly later call" as a comparison of positions in the
loaded sequence. Nothing in the loader or in either scorer asserts that this sequence is
chronological; it is a property of the order the loader joins results to calls.

Sorting, filtering, grouping or de-duplicating that sequence looks like a local improvement
to a collection carrying no documented promise. It silently redefines what "recovered" means,
and both scorers keep returning plausible numbers computed against the wrong notion of later,
with nothing failing.

Owners: `src/clinescope/world_a.py` for the join, `src/clinescope/apply_recovery.py` and
`src/clinescope/editor_recovery.py` for the comparisons that depend on it.

**No-agent zone.**

## The gate imports nothing from the judge

`tests/test_gate.py` parses `src/clinescope/gate.py`'s source and rejects a forbidden set of
import names. `.claude/rules/scope.md` owns why a model-backed judge is excluded by design
rather than by schedule.

**Know the shape of that pin before relying on it, because it is narrower than it sounds.**
It parses the gate module alone, so importing a judge module into the default report path
breaks nothing mechanically. And the forbidden set is a hardcoded list of module names rather
than a rule about the judge region, so a judge-arc module whose name is not in the list escapes
it silently. That is not hypothetical: modules in that region already exist outside the list.
Adding one is therefore two steps, the module and the list, and only the first is obvious.

## The labelling harness cannot see the thing it is validating

An agreement number is only meaningful if the human label was formed without sight of the
automated score or the judge's answer. `tests/test_label_gold.py` enforces the structural
half by parsing `src/clinescope/label_gold.py` and rejecting an import of the proxy scorer or
the judge.

The content half is not pinned by anything. A leak through the rendered text that a labeller
reads would fail no test and would invalidate every label collected afterwards.

Owner: `gold/README.md`, under "Labeling protocol (for a human labeler)".

## The human labels are frozen; the judge cache is regenerable

Both files live side by side in `gold/` and are governed oppositely, which an earlier version
of this project's own documentation flattened into one rule and got wrong. `CLAUDE.md`, under
"Layout", owns the split; `gold/README.md` owns the format and the protocol.

What this entry adds is the asymmetry that makes the rule bite. Each cached row carries a digest
of the patch it judged, so a drifting trace is caught loudly, but nothing pins the prompt.
Rewording the judge's prompt therefore invalidates every cached verdict with no mechanical
detector anywhere. `CLAUDE.md`, under "Layout", states what must happen when it does.

**No-agent zone**, because the recompute needs live model calls and moves a published figure.

## `examples/` and `gold/` are shipped payload, not test fixtures

`pyproject.toml` force-includes both into the wheel and the sdist, so they are part of what a
user installs. Renaming or deleting a file there breaks an installed command, not just a
test, and the local suite and continuous integration can both stay green while it does,
because nothing in the build installs a wheel and runs from it.

They are also a frozen contract in the ordinary sense: `CLAUDE.md` and `REVIEW.md` both put
regenerating or reformatting them out of scope by design.

## The upstream fixture is read in place, never copied in

The tests that validate the loader against Cline's own captured fixture read it from a
checkout outside this repository and pin its content, so an upstream change fails loudly.
Those tests skip wherever that checkout is absent, which includes continuous integration, so
a green build does not mean that check ran.

The two wrong fixes are worth naming, since both look reasonable. Copying the fixture in to
make the build exercise it creates a second copy that silently diverges from upstream and a
test that can be edited into passing. Bumping the pinned content to clear a failure
re-baselines the harness against a fixture nobody re-validated.

Owners: `tests/test_fixture_drift.py`, and `docs/building-with-agents.md` under "The golden
fixture is ingested, never edited".

## Every workflow action is pinned to a full commit

`CLAUDE.md`, under "Shipping a change", owns this rule in full: why a mutable reference is the
risk, the requirement to keep the readable version in a trailing comment, and the alerting trade
that pinning makes. `.claude/claude-security-guidance.md` carries it again as a review checklist
item.

What this entry adds is where it bites hardest. Read `.github/workflows/release.yml` for how the
privilege is split there, with the job that executes project code holding no publishing rights.

## The default branch takes no direct pushes, and the review check must keep reporting

`CLAUDE.md`, under "Shipping a change", owns all of it: the named required checks, why the review
workflow must keep triggering on a push to a pull request, and what happens to the pull request if
it stops. `CONTRIBUTING.md`, under "Fork, branch, PR", owns the accepted consequence for a pull
request opened from a fork.

This entry adds nothing to either, and is listed only because both are invariants an agent can
break with a one-line edit to a workflow file.

## A joined output line is never neutralised twice

Violation strings built by the scorers already escape the paths they interpolate. Passing
such a line through the neutralising helper again double-escapes it, which is why
`.claude/claude-security-guidance.md` states the rule as neutralise at the source rather than
at the join, and explicitly tells a reviewer not to flag the reverse.

That file owns the checklist, and `src/clinescope/render_safety.py`'s own module docstring owns
why the helper is a leaf module and why it neutralises the way it does.
