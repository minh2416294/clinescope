# Architecture

**This file is an index, not an explanation.** The real architecture documentation in this
project lives in module docstrings, which is the right place for it: a docstring moves in the
same diff as the code it describes, so it cannot drift the way a separate prose file can.

So what follows is the shape of the pipeline, then a pointer per boundary. Where a module
already explains itself, this file says so and stops. What it adds is the cross-module
connective tissue no single module can own, and the consequences a reader who opened only one
file would miss.

The file tree is not repeated here either. `CLAUDE.md`, under "Layout", owns it.

## The pipeline

Load a trace, score it, then either render a report or return a gate verdict. Nothing loops
back: a scorer never reads a report, and a renderer never re-scores.

## Boundaries, and who explains each one

| Boundary | Read this |
|---|---|
| Trace loading, the version gate, and what the loader refuses to coerce | `src/clinescope/world_a.py`, module docstring |
| The second trace format, and why it is an adapter rather than a model | `src/clinescope/cline_extension.py`, module docstring |
| How a tool-call verdict is resolved, and why it fails closed | `src/clinescope/tool_verdict.py`, module docstring |
| The gate's exit contract, and why applicability is decided on a call count | `src/clinescope/gate.py`, module docstring |
| Why the multi-trace scorecard is a sibling command and never a build gate | `src/clinescope/compare.py`, module docstring |
| Neutralising untrusted text: the repr choice, the quotes, the leaf-module rule | `src/clinescope/render_safety.py`, module docstring |
| Locating bundled data so an installed package works | `src/clinescope/_datafiles.py`, module docstring |
| Why the patch text handed to the judge is fenced, and why the tag is a digest | `src/clinescope/judge.py`, at the prompt builder |
| Why there is no second agent adapter and no generic seam | `.claude/rules/scope.md`, "What it deliberately does not do" |
| What each scorer checks, and its caveat | `CLAUDE.md` and `LIMITATIONS.md` |

## What no single module owns

The items below are properties of the whole rather than of any one file, which is why they are
written here rather than pointed at.

**A scorer's outcome is decided at a different layer for each kind of outcome.** This is the
most misread part of the codebase. A hard zero falls out of a type: a scorer whose score is a
plain float has no way to express "not applicable". An abstention is the scorer returning no
score. An omitted report line is not a scorer state at all: `src/clinescope/editor_recovery.py`
always returns a fully formed result, and the decision to leave its line out is taken in
`src/clinescope/__main__.py`, which scores it only when the trace contains a call to the tool
it grades. Somebody looking for the omission inside the scorer will not find it.
`src/clinescope/gate.py`'s docstring owns why the type distinction exists; `CLAUDE.md` owns
what each outcome looks like to a user.

**An extension trace never presents a version of its own.** The adapter supplies the envelope
by injecting the supported version rather than reading one. So tightening or bumping the
version gate covers the command-line format and silently leaves the extension format
untouched, while looking like it covered both. Neither module states this, because it is only
visible from both at once.

**The patch-grammar scorers share one parser.** `src/clinescope/diff_coherence.py` owns the
grammar; `src/clinescope/diff_minimality.py` and `src/clinescope/apply_recovery.py` import it
rather than reimplementing. An edit to that parser therefore moves scores in files the change
never touched, and supporting a different agent's edit format is a new scorer rather than a
configuration value.

**Every entry point splits the same way, and stdout is reserved.** Each command is a run
function that computes, a render function that returns a string, and a `main` taking an
argument vector and returning an integer; no I/O or process exit happens inside the logic.
That is what lets a report be asserted as an exact string rather than through a subprocess.
And stdout carries the report and nothing else: warnings, banners, the interactive picker,
errors and the feedback footer all go to stderr, with the footer additionally checking that
stdout is a terminal.

## Where the exit codes are, and why they differ

`src/clinescope/gate.py` owns the gate's contract, including which confusions between codes
are forbidden. Read it there.

The cross-command fact is that the same integers mean different things in different commands
here, deliberately. `docs/internal/INVARIANTS.md` records it as an invariant, because
unifying them behind a shared constant would change several observable contracts at once,
including the one this project's own build asserts against in both directions.
