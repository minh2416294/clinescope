# What other eval frameworks ship

## Why this file exists

`README.md` used to carry three comparative clauses about five other tools. Nobody had opened
any of those tools. They were written from recollection, they sat in the most-read paragraph on
the front page, and two of them were false in a way a reader could disprove in one fetch.

This file is what replaced them. It owns every claim this project makes about somebody else's
code: what was read, what it said, and the date it said it.

**Every fact here is about a moving target.** These are five actively developed projects. A row
goes stale when a vendor ships, with nobody in this repository touching a file, which is why each
one carries a date rather than a version-free assertion. Treat an undated claim about another
tool as unverified, wherever you find it.

## The method, and the limit that qualifies all of it

Twelve agents ran on 2026-09-13: one to chase each claim to a first-party source, and one per
claim afterwards whose only instruction was to break the first one's finding. Secondary sources
were refused as evidence, so no blog post, comparison listicle or forum answer is cited below.

**All twelve reached those sources through a summarizing fetch layer, not raw bytes, and it
proved unreliable on exactly one class of fact: counts.** It returned three different export
counts for the same file across three fetches, miscounted a twenty-row list as eighteen while
correctly listing all twenty rows, and once returned a plausible, entirely fabricated directory
listing, which was discarded rather than cited.

The consequence is written into how this file is worded. Identifier names, docstrings and code
constants below are corroborated by two or more independent first-party sources agreeing. **Exact
inventory counts are mostly omitted on purpose**, and where one appears it is because the project
under discussion asserts it in its own test. Do not add a count here that you have not seen
asserted by the project itself.

## The single claim `README.md` now rests on

> None of the five ships a built-in scorer for patch grammar, for edit minimality, or for
> apply-failure recovery.

That survived every refutation attempt. It is narrow on purpose, and three narrowings are
load-bearing:

- **"built-in"** excludes what a user writes themselves. All five offer a custom-scorer escape
  hatch, and several document writing one as the expected path.
- **"for patch grammar, for edit minimality, or for apply-failure recovery"** names the three
  checks rather than saying "for diffs". Two of the five do read diff text for other purposes,
  so the broader phrasing would be false.
- **five**, named, rather than "no eval framework". Nobody surveyed the field.

## Per tool

### DeepEval

Ships no metric consuming a patch or a diff. The enumeration rests on the exported metric list in
`deepeval/metrics/__init__.py`, the metric package directory, the classical scorer module
`deepeval/scorer/scorer.py`, the benchmark directory, and the documentation metric index, all
agreeing. Read at branch `main`, release `python-v4.2.0`, on 2026-09-13.

Two corrections the old README sentence needed:

- **It scoped to the wrong thing.** The absence holds for the open-source `deepeval` package. The
  same vendor's sibling package `deepteam` ships a code scanner that does consume a pull-request
  diff, via `git diff --name-only {base}..{head}`, and the vendor's platform ships a managed
  Python grader for writing your own. An unscoped sentence about "DeepEval" is checkable-false.
- **"DeepEval scores tool selection" pointed the comparison backwards.** Tool selection is one
  metric among roughly fifty. Worse, on that exact axis DeepEval is ahead of this project:
  `ToolCorrectnessMetric` can be escalated to match input parameters and outputs via
  `ToolCallParams`, and DeepEval ships a separate `ArgumentCorrectnessMetric`. Clinescope's
  `tool_selection` is name-only and says so in `LIMITATIONS.md`.

DeepEval does score code, by executing generated functions against tests in its HumanEval
benchmark. "Not code patches or diffs" is true; "not code" would be false.

### DeepEval's `ToolCorrectnessMetric`, in detail

`src/clinescope/tool_selection.py` points here, because its own metric shape was taken from this
one and the two have since diverged.

Confirmed at `python-v4.2.0` (released 2026-08-24) and independently re-read at three release
tags plus the TypeScript SDK: the constructor defaults are `should_exact_match=False`,
`should_consider_ordering=False` and `evaluation_params=[]`. So the default is order-insensitive
and matches neither input parameters nor outputs.

The match condition is `expected_tool.name == called_tool.name and expected_tool.type ==
called_tool.type`. Type matching was added on 2026-08-14 and shipped in that release, so
describing the default as name-only is now wrong. In practice `ToolCall.type` defaults to
`ToolCallType.FUNCTION`, so default-constructed calls still compare on name.

Scoring is `total_score / len(self.expected_tools)`: recall over the expected tools, which never
penalises calling extra tools. Describing it as a set comparison is wrong, because that implies a
symmetry the code does not have.

**One unreconciled conflict, recorded because a reader will hit it.** Two DeepEval documentation
pages give the denominator as the total number of tools *called*, while the source divides by the
tools *expected*. The source governs behaviour. Do not cite only the documentation figure, and do
not quietly average the two.

### promptfoo

Ships no assertion that parses patch or diff text. The enumeration rests on the assertion-type
schema in `promptfoo/src/types/index.ts`, the handler registry in
`promptfoo/src/assertions/index.ts`, and the assertion directory listing, cross-checked against
the published assertion documentation. Read at `main` on 2026-09-13.

**The old README clause was false about promptfoo and has been cut.** "promptfoo hands the diff
scorer to you" does not survive: promptfoo ships a code-scanning product with a diffs-only
pull-request scan and severity grading, which requires no user-written assertion. That is a
security scan rather than an edit-quality check, which is why the narrowed claim above names the
three specific checks instead of saying "diffs".

promptfoo is also ahead of this project on tool trajectories: alongside `tool-call-f1` it ships a
trajectory family whose `trajectory:tool-args-match` checks tool-call arguments.

A scoping note for anyone re-checking: the red-team plugin family is a large separate grader
vocabulary that a count of the base assertion types does not cover.

### Langfuse

Ships no evaluator for patches or diffs. The authoritative enumeration is the managed template
catalogue in `langfuse/web/src/features/evals/v2/constants/managedTemplatesCatalog.ts`, whose own
client test asserts exactly twenty templates. The strings "diff" and "patch" do not occur in it.
A hunt for a superseded v1 catalogue found none, and the legacy compatibility service imports
this same catalogue rather than defining a rival list. Read at `main` on 2026-09-13.

**Grouping Langfuse with the scorer-shipping libraries was the mistake.** Saying it "hands the
diff scorer to you" is true and nearly vacuous, because Langfuse hands you essentially every
domain-specific scorer: the product is a tracing and scoring substrate with an LLM-judge gallery
on top. The old phrasing implied a scorer catalogue with a diff-shaped hole in it.

Three details that contradict the obvious over-corrections:

- Three of the twenty templates are deterministic code evaluators rather than LLM judges, proven
  by the catalogue's own test asserting an evaluator type of `CODE`.
- Langfuse ships a first-party bridge to Braintrust's third-party `autoevals` library, so
  "everything deterministic is code you write yourself" is also false.
- The catalogue has a coding-agents category. Those templates classify what an agent was used
  for; they do not score the edit it produced. Do not write that Langfuse has nothing for coding
  agents.

Langfuse also has a continuous-integration gating surface, which is the closest thing here to
`clinescope-gate` and is worth reading before claiming novelty for it.

### Braintrust

The strongest of the five. Braintrust's built-in scorers are the open-source `autoevals` package,
and none takes a code patch or diff as input. The nearest three are `JSONDiff` (structural
comparison of two parsed JSON values), `Levenshtein` (reference-based string edit distance) and
`Sql` (a judge on whole-query equivalence). Read at `main` on 2026-09-13.

Braintrust's own documentation supports the claim rather than merely failing to contradict it: it
directs anyone needing a scorer outside the pre-built set to write custom code.

**No single first-party file lists every scorer**, which is why no count appears above. The
JavaScript manifest omits `Faithfulness`, while the repository's own complete-reference document
omits `Possible`. Anyone citing one of those two as the inventory is citing an incomplete list.

`Sql` means "Braintrust does not grade code" would be false. Its Codex integration also traces a
file-change span, but ships no scorer over it.

### Inspect, by the UK AI Security Institute

Ships no built-in scorer that reads patch text. The complete built-in list is the fifteen entries
under the "Scorers" heading of the published API reference, cross-checked against the scorer
module's exports and its directory listing. Read at `main` on 2026-09-13.

**Do not cite the module's `__all__` for that count.** It holds far more than fifteen names,
because it also exports metrics, reducers, types and decorators. The fifteen is the reference
page's Scorers section. Citing `__all__` makes a correct number look invented to anyone checking.

**The old README clause described a mechanism that does not exist, and has been cut.** It said
Inspect grades SWE-bench by running the repo's tests against the files the agent edited. Reading
`inspect_evals/swe_bench/scorers.py`:

- It does not run the repo's tests. It runs a fixed per-instance directive list derived from the
  dataset's own test patch, with a hardcoded per-repository test command.
- Nothing is applied. The agent edits the checkout in place inside a container. A model patch is
  generated under a comment saying it is for logging purposes, lands only in score metadata, and
  an empty prediction string is passed to the grader.
- It is not run against the files the agent edited, for test files specifically. The script does
  `git checkout {base_commit}` on every file the dataset's test patch touches, then applies that
  test patch, so an agent's edits to a test file are discarded before grading.
- The resolved verdict is delegated to the upstream `swebench` package's grading module, not
  computed by Inspect.

**Two attribution points.** That scorer lives in `inspect_evals`, a different repository from
`inspect_ai`, so attributing it to "Inspect" conflates a framework with one community eval.
And AISI is the AI **Security** Institute, renamed from AI Safety Institute on 2025-02-14;
writing the old expansion is a citation defect. Inspect's documentation home currently credits
Meridian Labs alongside the institute, while its repository README credits the institute alone.

Finally, "its built-in scorers grade answers" was loose. Most of the fifteen compare a model
output to a target, but two read token log probabilities and two compose other scorers, and
`precomputed_scores` grades nothing itself: it attaches a score computed outside Inspect from a
file, which is the documented way to bring in any external score, a patch score included.

## What was not checked, stated so nobody reads this as exhaustive

- **Hosted products versus open-source packages.** For DeepEval, Braintrust and Langfuse the
  enumeration is of the open-source library. Whether a hosted platform offers graders absent from
  the public repository was not established for any of them, and for Langfuse a first-party
  statement on catalogue parity was looked for and not found.
- **promptfoo's red-team plugin family** was enumerated only well enough to confirm no plugin
  parses patch text.
- **Inspect's sibling packages and the rest of its eval catalogue.** Of the evals under its coding
  category, three were opened. The cyber extension ships its own scorer package, checked and
  clean. The reinforcement-learning extension was not opened.
- **Nobody surveyed the field.** Five tools were checked because `README.md` named five.

## When a claim here needs re-checking

Re-run the chase before any release that repeats one of these claims outward, and whenever a
comparative sentence is added anywhere in this repository. `CLAUDE.md` owns the honesty rule that
makes an unverified comparative claim a defect rather than a wording preference, and `REVIEW.md`
owns the severity it carries in review.

A cheap tripwire, short of a full re-run: the claim above is falsified by any one of the five
shipping a scorer that reads patch text. That is the thing to look for, not a general re-read.
