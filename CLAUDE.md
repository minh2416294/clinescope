# CLAUDE.md — agent-eval-harness

Project-local instructions for any Claude Code session opened in this repo.

> **This file is a local pointer + copy of the operating protocol.** The single source of truth is
> in the user's memory files — read them FIRST every session:
> - **Charter (WHAT):** `~/.claude/memory/project_agent_eval_harness.md`
> - **Operating protocol (HOW — canonical):** `~/.claude/memory/project_agent_eval_harness_protocol.md`
>
> The Charter holds current state only. The dated build history lives in
> `~/.claude/memory/project_agent_eval_harness.ARCHIVE.md` (append-only, relocation only). A
> session's own close-out notes go in the git-excluded `writing-content/`; only a decision a future
> session could not re-derive graduates into the Charter, and only on a major update, a major fix,
> or a release (operating protocol, section 5.9). Read the Charter plus the last session note before
> doing any work, so sessions never conflict.

## What this project is (one line)

A **Cline eval harness**: scores `apply_patch` grammar, patch shape, and tool trajectory from a real
Cline `messages.json` v1 trace. Framework-agnostic core; Cline World-A adapter is the flagship + first
adapter. Purpose = hireability + reputation, NOT paid users.

**Hard floor (v1 is "done" only when BOTH are true):**
1. Runs against Cline's golden fixture — ingests `sdk/packages/core/fixtures/messages/success.messages.json`,
   emits a scored report (`tool_selection` plus the three `apply_patch` scorers, which abstain on a
   trace with no patch).
2. Ships the diff-coherence / minimal-diff / apply-recovery scorer the incumbents don't, on ≥1 real trace.

## Standing rules (check every session — from the protocol)

1. **WIP = 1.** One task in flight. One task per Claude Code session.
2. **No task without a CHECK.** The verifying command/test is written BEFORE any code. No check =
   task doesn't enter the log.
3. **Every task serves hard-floor criterion 1 or 2**, or it's tagged `~` (roadmap, dropped by default).
4. **Never modify the golden fixture** at `**/fixtures/messages/success.messages.json`. The harness
   INGESTS it from the Cline checkout; it is never copied or edited. (Hook-enforced.)
5. **No demos disconnected from Cline's real trace.**
6. **Max 2 weeks without a public artifact.** Silence is the #1 OSS death signal.
7. **Tooling-config urges = procrastination.** Log the urge, return to the CHECK.
8. **Log is append-only.** Decisions are immutable; to change one, write a NEW entry that supersedes
   and links the old (ADR discipline). Never edit past Living-Log entries.
9. **R6 honesty check: run this exact grep, it covers BOTH banned words.** R6 bans calling a scorer
   a *quality* scorer OR a *correctness* scorer. A grep for only the first word passes while a
   module titled with the second sits in shipped source, which is exactly what happened and shipped
   in 1.2.1 (`tool_selection.py`, caught by a Gate-4 audit on 2026-08-21, not by the release check):

   ```bash
   grep -rn -i -E "diff[- ]quality|quality of (the )?(diff|patch)|[a-z-]*(quality|correctness)[- ]scorer" \
     --exclude-dir=.git --exclude-dir=.venv --exclude-dir=htmlcov --exclude-dir=__pycache__ --exclude-dir=dist .
   ```

   It deliberately does NOT match legitimate disclaimers ("not argument correctness", "does not
   verify semantic correctness") or DeepEval's `ToolCorrectness` API name. Surviving hits should be
   only frozen CHANGELOG history. **The grep is the mechanical half; it cannot catch a quality
   judgement phrased in ordinary words** (1.2.1 also shipped "catching messy code rewrites" on the
   PyPI front page). Read the prose too.

## Sequencing law — walking skeleton

Until the thin path **load World-A trace → score → emit report** runs against the golden fixture,
EVERY build task is a skeleton segment. Keep it ugly and runnable. After the skeleton runs, every
task FILLS it (a new scorer, a new metric — deterministic zero-LLM gates first). Never a disconnected
module. No second adapter before a real one exists (two-adapter rule).

## Task types (only three exist)

| Type | Rule |
|---|---|
| **BUILD** | Fills the skeleton. Verification-first, sized to one session, machine-checkable. |
| **SPIKE** | One question, hard timebox (2–3h), throwaway code, MUST end with a written decision. Timebox expiry IS the answer. Only for genuine unknowns. |
| **PUBLISH** | Triggered by artifact milestones, never by calendar. Raw material mined from the Living Log + commits → `writing-content/`. |

## Session close-out template (append to a dated note in the git-excluded `writing-content/`)

```
## YYYY-MM-DD — <session goal, one sentence, ends in a verifiable state>
- TYPE: BUILD | SPIKE (timebox: Xh) | PUBLISH
- CHECK: <exact command/test + expected output that proves done — written first>
- APPETITE: ≤ N sessions
- CONTEXT: <files, fixture paths, relevant log entries>
- EVIDENCE: <pasted actual output — never an assertion>
- DECISIONS: <immutable; supersede-don't-edit>
- OPEN QUESTIONS: <what you now don't know>
- NEXT ACTION: <the first thing next session does>
```

## Session gates (from the user's global CLAUDE.md)

- Set a `/goal` with a measurable success criterion; match `/effort` (feature work = xhigh); Plan Mode
  for anything multi-step.
- Demand EVIDENCE (pasted output), never assertions of "done".
- The paper trail (`writing-content/`, `artifacts/`) is git-excluded and feeds `/public-writing`.

## Layout

```
src/clinescope/           # the package (import clinescope)
pyproject.toml            # metadata, no deps yet
.venv/                    # local venv (git-ignored)
writing-content/          # git-excluded build paper trail (created when a build phase runs)
artifacts/                # git-excluded keeper artifacts
```
