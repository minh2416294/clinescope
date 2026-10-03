# Testing and CI

**An index, not an explanation.** What the build runs, how to reproduce it, and the setup traps
are each already owned:

- `CLAUDE.md`, under "Development", owns the command list; under "Environment traps" it owns
  the editable-install pin, the line-ending trap, and verifying a frozen artifact with git's
  own object hash.
- `.github/workflows/ci.yml` is the executable version of the command list, including the step
  that runs this project's own gate against committed traces in both directions.
- `CONTRIBUTING.md` owns dev setup, the coverage reproduction, the multi-worktree
  editable-install gotcha, and the full release procedure.
- `pyproject.toml` comments own why the coverage flags sit on the command line rather than in
  the defaults. Its type-checker block declares a scope but carries no comment explaining one,
  and what the build actually checks is narrower than that declaration; see "What a green build
  does not tell you" below before trusting it.

What this file adds is the part nothing else collects: which tests are load-bearing in a way
their names do not reveal, and what a green build is silent about.

## The structural guards

Most of `tests/` checks behaviour and reads fine from its names. A smaller set asserts a
property of the repository rather than of a function. Each is the only thing standing between a
plausible edit and a silent regression, and none is obvious from its filename.

| Guard | What it prevents |
|---|---|
| `tests/test_gate.py`, the import pin | A chance-level advisory signal reaching a build verdict. Parses the gate's source rather than trusting a convention. |
| `tests/test_gate.py`, the help-text pins | The gate shipping without disclosing the weak measured agreement of the scorer it gates on, its catch rate without its false-alarm rate, either rate without its Wilson interval, or the sentence about that score depending on file layout. The honesty rule, made mechanical where a person setting a threshold will actually read it. The two rates are recomputed from the frozen gold set and each interval from those counts, so a published rate that stops matching the labels fails too, and so does a mistyped interval or one computed another way. |
| `tests/test_judge_run.py`, the prompt pin | The published judge agreement being printed from verdicts that answered a different request from the one the judge sends today. Compares every committed cache row's prompt digest with the live one, so a prompt edit fails the build until the cache is re-judged live in the same change. |
| `tests/test_label_gold.py`, the import pin | A human labeller being shown the automated answer they are meant to be an independent check on. |
| `tests/test_version_consistency.py` | Publishing a package whose reported version is not the one that was built. The only thing comparing the two. |
| `tests/test_fixture_drift.py` | An upstream change to Cline's own captured fixture passing as a local behaviour change. Pins content and size. |
| `tests/test_corpus.py` | The evidence corpus degrading to all-clean or all-failing, a trace DECLARED authored being used as a failing item, and a trace file replaced by a different capture, or a later save of the same session, under an unchanged manifest key. Asserts composition, not a count, except that the capture-provenance test pins the number of items, so adding or dropping one means editing that test. `source` (real or authored) is a self-declared manifest field, so the suite cannot catch a trace that is authored but declared real; that one rests on the contributor, and the capture-provenance check does not change it. That check is the only one on the provenance keys: the runner ignores them, on purpose, because on the committed manifest a runner check would catch nothing this test does not, and nobody has asked for one on their own manifest. `examples/corpus/README.md`, under "Provenance", owns what the check proves. `examples/corpus/README.md`, under "What kind of eval this is", owns which kind of eval each corpus row is, and what kind the strict expected failure below is. One test in it is a strict expected failure standing for the `no_editor_recovery` gap in `examples/corpus/README.md`. It goes red the day a real failing `editor` row lands, which means remove the marker, not that something regressed. |
| `tests/test_render_demo_svg.py` | The committed hero image drifting from its generator. Byte identity, because a weaker check would pass on a spacing change. And the generator's report lines drifting from what `clinescope` prints: it re-runs each scene's command and compares, once the generator's two stated width edits are undone. Byte identity alone missed that drift: the hero still matched its generator after the session id gained quotes and the advice was reworded. |
| `tests/test_editor_recovery_report.py` | The report's existing output shifting when a newer scorer is not in play. Byte identity, for the same reason. |
| `tests/test_docs_internal_contract.py` | This directory pointing at a path that no longer exists, or locating a fact by line number. |

## What a green build does not tell you

Recorded here because the natural reading of a passing build is the wrong one.

**Whole test families self-skip when their external prerequisite is missing, and the build
provides none of those prerequisites.** The tests that validate against Cline's own captured
fixture are gated on
that file existing at an absolute path in another checkout on the author's machine. The tests
that exercise the judge against a live model are gated on a local endpoint answering. Both skip
quietly. So a change to how the judge sends or parses a request can pass every required check
without executing once, and the same is true of the upstream fixture comparison. A change to the
request it builds is the exception: it moves the prompt digest, so the committed cache fails the
prompt pin above, although the new request is still never sent.

**The suite assumes the working directory is the repository root.** There is no `conftest.py`
anywhere. Most modules recompute the root from their own location, but some hold
repository-relative path constants and the corpus runner resolves manifest keys against the
process working directory. Run it from elsewhere and the failures read exactly like a real
regression, which is the most expensive kind of false alarm for somebody new here.

**The type checker covers less than the configuration says.** `pyproject.toml` names both the
package and the scripts directory, but the build passes an explicit path on the command line,
and mypy ignores its configured paths whenever it is given one. So the build type-checks the
package ONLY: `tests/` is out, which is the widely-known half, and `scripts/` is out too, which
is not. Measured on this tree: the configured invocation reports 29 source files and the one
the build runs reports 27, and the two missing files are the two in `scripts/`.

Two consequences worth separating. A type-ignore inside a test is unvalidated, and a test
helper can drift out of step with the value object it constructs with no type-level signal.
And a committed generator under `scripts/` gets no type-checking at all despite appearing in
the configuration, which is the more surprising of the two because reading `pyproject.toml`
alone tells you the opposite. The linter and formatter do cover both directories, which makes
the whole gap easy to misjudge.

**A local pass says nothing about the tested interpreter range.**
`.github/workflows/ci.yml` owns the matrix and `pyproject.toml` owns the supported floor. A
local interpreter can sit outside both.
