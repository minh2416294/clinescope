# clinescope

**A Cline eval harness — it scores the quality of a coding agent's diff and tool-trajectory from a real Cline execution trace.**

Built for **agentic-coding traces, not chatbot Q&A**: point it at a Cline `messages.json` task
trace and it emits a scored report — tool-selection correctness, code-diff quality, and task
completion — the layer generic eval frameworks leave to a "write your own custom scorer."

Under the hood the scoring engine is **framework-agnostic** (an ingestion + scoring core); v1 ships
with the **Cline World-A trace adapter** as the flagship and first adapter. Other adapters
(LangGraph / CrewAI / your-own-loop) come later, only when a real second implementation exists.

> **Status:** Day 1 — project skeleton. No features yet. The walking skeleton
> (load World-A trace → score → emit report against Cline's golden fixture) is the next step.

## What makes it different

None of the mainstream eval frameworks ship a first-class **code-diff-quality scorer** or replay a
real coding-agent trace. This does — starting with Cline, whose community it's built to serve.

## Working title

`agent-eval-harness` is a working title; the public name is a later decision.
