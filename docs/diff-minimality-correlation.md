# Does the diff score track human judgment? Undefined, and here is why

Clinescope's deterministic scorers are reference-free: they read the patch text and nothing
else. The obvious question to ask of a reference-free score is whether it agrees with a
human looking at the same patch. That question was scheduled to be answered with a rank
correlation (Spearman) or an AUC against blind human labels on real traces.

It cannot be answered here today. Not because the labels are missing, but because
`diff_minimality` returns the same value on every real captured Cline session shipped in
this repository. A correlation needs two things that vary. Only one of them does.

This page is that null result, the distribution it rests on, and a pre-registration that
makes the real experiment runnable once the corpus can support it.

## How it's measured

Every `*.json` under `examples/` is loaded and scored, using the shipped loaders and the
shipped scorers. Three rules decide what counts.

**The population is deduplicated by `sessionId`, never by file hash.** Four sessions ship
twice, once at the top of `examples/` and once under `examples/corpus/`. The two copies are
byte-different and score identically, so a file count reports 73 traces where the honest
answer is 69 distinct sessions. Counting files would inflate the real-capture population by
a third.

**Real captures and authored fixtures are counted separately**, because mixing them is the
mistake that would make this whole page look like a measurement. The split is mechanical: a
trace written by the Cline CLI carries `agent`, `system_prompt` and `updated_at` alongside
its `sessionId`; a fixture authored for this repository carries only `version` and
`sessionId`. That rule is stated here rather than hidden so a reader can check it against
any file in the tree.

**An abstention is not a zero.** On a trace with no `apply_patch` call, `diff_minimality`
returns `applicable=False` and no score at all. Those sessions are reported as `n/a` below
and are excluded from the scored population, because reporting them as zeros would
manufacture the variance this page exists to say does not exist.

## The result

| Population | Distinct sessions | `diff_minimality` | `diff_coherence` |
|---|---|---|---|
| **Real captures** | **15** | 5 scored, **all 1.0**; 10 abstain (`n/a`) | 5 at 1.0; 10 hard-zero |
| Authored fixtures | 54 | 46 at 1.0, 1 at 0.5, 7 at 0.0; 0 abstain | 53 at 1.0, 1 at 0.75 |

The real-capture row has one distinct `diff_minimality` value and no session below 1.0. The
authored row has three distinct values and eight below 1.0.

## Why that makes the keystone undefined

Spearman's rho is the Pearson correlation of the ranks, `cov(Rx, Ry) / (sd(Rx) * sd(Ry))`;
five real sessions score and all five score 1.0, so every rank ties, `sd(Rx)` is exactly
zero, and rho is `0/0`. AUC does not fail as loudly: scored as the probability of ranking a
positive above a negative with ties at half credit, a constant score makes every pair a tie,
so AUC is exactly 0.5 for every possible assignment of labels.

That asymmetry is the part worth keeping. Rho at least raises a division by zero. AUC hands
back 0.5, which looks like a measured result meaning "no better than chance" and is in fact
an arithmetic identity that never touched the labels. A broken instrument returns a
plausible number rather than an error, and 0.5 here is that number.

There is a second, independent blocker underneath the first. Ten of the fifteen sessions
abstain, so even if the remaining five varied, the correlation would be computed over n = 5.

**`diff_coherence` does not rescue this, despite not being constant.** The keystone names both
scorers, and the table above shows `diff_coherence` taking two values on real captures where
`diff_minimality` takes one, which looks at first like a usable spread. It is not. Those two
values separate the five sessions that contain a patch from the ten that contain none: every
capture with an `apply_patch` call scores 1.0, and every capture without one hard-zeros. The
variance is therefore entirely "did this trace contain a patch at all", which is not a question
any human labeler is being asked, and across the five traces that do have a patch to judge the
score is again a single value. Correlating all fifteen would measure the presence of the
artifact rather than agreement about its content.

## Pre-registration

Locked 2026-09-20, before any correlation data exists.

GATE. No correlation between a diff score and a human label will be computed or
published until at least 20 distinct real captured Cline sessions, deduplicated
by sessionId, score below 1.0 on diff_minimality. Reason for 20: below roughly
that, a rank correlation's confidence interval is too wide to separate rho = 0
from rho = 0.6, so a number computed there would not be able to answer the
question it was computed to answer.

THRESHOLD, applying once the gate is met. Spearman rho below 0.3 means the
score does not track human judgment, and that result gets published unchanged.

Reason 0.3 and not 0.5: the 0.5 figure in this repository is defined in the
judge modules only, as an advisory tripwire for an LLM signal. LIMITATIONS.md
states it has never been a project-wide validity bar for a deterministic
scorer. Adopting it here would be a new claim rather than an inherited one.

This block may not be revised after the data it judges has been seen, per the
hard rule in .claude/rules/measurement.md.

Against that gate, the current count of real captured sessions scoring below 1.0 is **zero**.

## What this says about the scorer, not about the experiment

`diff_minimality` is not broken. It fires on all eight authored fixtures that sit below 1.0,
and its unit tests exercise the detection directly. What the flat distribution measures is
the corpus: the one shape this scorer detects, a run of three or more deleted lines
immediately retyped with no anchor kept, does not occur in any real captured session
shipped here.

That is a product finding, and `.claude/rules/measurement.md` already says so. It ranks
abstention rate over real traces second among the things worth measuring, ahead of the
scores themselves, on the grounds that a scorer which abstains on most traces people
actually have is aimed at the wrong format. Its thresholds table puts the suspicion line at
above 50 percent. `diff_minimality` abstains on 10 of 15 real captured sessions, which is
67 percent.

The gate flag says the same thing from the other end. Running `clinescope-gate` over the 13
real captured CLI sessions at `--min-diff-minimality 1.0`, the strictest value the flag
accepts, returns exit 0 five times and exit 2 eight times. Exit 1, the build-failing code,
does not occur. There is no threshold a user can choose that makes this flag fail a build on
a real trace shipped with it, which is the already-published fact this distribution
re-derives from the scores directly.

None of that is an adoption signal. Clinescope has **0 users and 0 revenue**, and every
trace counted above was captured by the author against a local model. A corpus that varies
is something this project has to go and collect, not something a user is about to supply.

## Why the existing kappa figure is not this measurement

There is a published agreement number for `diff_minimality` against human labels. It is not
the keystone, and reading it as the keystone is the specific error this section exists to
prevent.

It was measured against the gold set in `gold/`, which is authored end to end for this
repository and contains no captured Cline trace. One person labeled it. So it answers "does
this scorer agree with a human on patches written to test it", over a population built to
contain the shape the scorer looks for. The keystone asks whether the score tracks human
judgment on traces real agents actually produced, which is a different question over a
population that, as the table above shows, contains none of that shape at all.

The figure, its interval, its recall and its cut live in the help text for the gate's
minimality flag in `src/clinescope/gate.py`, with the reader-facing discussion under
"The gated `diff_minimality` flag is weaker than it looks" in `LIMITATIONS.md`. They are not
repeated here. The separate measurement of the optional LLM judge lives in
[`judge-validation.md`](judge-validation.md); that is a third distinct number and is not
comparable to either of the other two.

## Reproduce it yourself (no model call, no new dependency)

From the root of a source checkout, so `examples/` resolves:

```bash
python -c "
import json, pathlib, collections
from clinescope.world_a import load_trace
from clinescope.cline_extension import load_extension_trace
from clinescope.diff_minimality import score_diff_minimality
from clinescope.diff_coherence import score_diff_coherence
seen, dist = {}, collections.defaultdict(collections.Counter)
for p in sorted(pathlib.Path('examples').rglob('*.json')):
    raw = json.loads(p.read_text(encoding='utf-8'))
    if isinstance(raw, dict) and 'messages' in raw:
        trace, sid = load_trace(p), raw['sessionId']
        kind = 'capture' if {'agent','system_prompt','updated_at'} <= set(raw) else 'authored'
    elif isinstance(raw, list) and p.name.startswith('api_conversation_history'):
        trace, sid = load_extension_trace(p), p.stem
        kind = 'authored' if 'constructed' in p.name else 'capture'
    else:
        continue
    if sid in seen: continue
    seen[sid] = kind
    dm, dc = score_diff_minimality(trace), score_diff_coherence(trace)
    dist[(kind,'diff_minimality')][dm.score if dm.applicable else 'n/a'] += 1
    dist[(kind,'diff_coherence')][dc.score] += 1
for kind in ('capture','authored'):
    print(f'{kind}: {sum(1 for k in seen.values() if k==kind)} distinct sessionIds')
    for scorer in ('diff_minimality','diff_coherence'):
        print(f'  {scorer}: ' + '  '.join(f'{v}={n}' for v,n in sorted(dist[(kind,scorer)].items(), key=lambda x: str(x[0]))))
"
```

It prints the table above. It uses only the shipped package and the standard library, so it
adds no statistic to the codebase and installs nothing. Neither Spearman nor AUC is
implemented anywhere in this repository, deliberately: writing one before the gate above is
met would produce a number with nothing behind it.

The gate figures are a separate command, one trace at a time:

```bash
clinescope-gate examples/corpus/live-gpt-oss-trace.json --min-diff-minimality 1.0 ; echo $?
```

## Honest caveats

- **N = 15 is small, and none of it is user data.** Every capture is the author's own, run
  against local Ollama models. A different model, a different task mix, or somebody else's
  work would plausibly produce a different distribution. This measures the traces shipped
  here and makes no claim beyond them.
- **The real-versus-authored split is a key-presence rule, not a provenance proof.** It
  matches how the Cline CLI writes a session today. A fixture authored to carry those three
  keys would be counted as a capture.
- **The two VS Code extension captures have no on-disk session id.** That format is a bare
  JSON array, so `cline_extension.py` synthesizes an id from the filename. Deduplicating
  them by `sessionId` is therefore nominal; it happens to be correct here because the two
  files are two different tasks, but it would not catch the same extension task shipped
  twice under two names.
- **`diff_coherence` is reported for context.** Its 10 hard-zeros are the documented
  no-`apply_patch` case, not 10 malformed patches. Why its two values still cannot carry the
  keystone is above, under "Why that makes the keystone undefined".
- **One distinct value is the finding, not a sample-size problem.** Collecting 50 more
  sessions of the same kind would not fix it. What the gate above asks for is specifically
  sessions that score below 1.0, which is a different collection problem and may need
  traces from somebody else's work.
