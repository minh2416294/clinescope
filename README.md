# clinescope

**A Cline eval harness — it scores the quality of a coding agent's diff and tool-trajectory from a real Cline execution trace.**

Built for **agentic-coding traces, not chatbot Q&A**: point it at a Cline `messages.json` task
trace and it emits a scored report — tool-selection correctness, code-diff quality, and task
completion — the layer generic eval frameworks leave to a "write your own custom scorer."

Under the hood the scoring engine is **framework-agnostic** (an ingestion + scoring core); v1 ships
with the **Cline World-A trace adapter** as the flagship and first adapter. Other adapters
(LangGraph / CrewAI / your-own-loop) come later, only when a real second implementation exists.

> **Status:** walking skeleton runs end-to-end. `python -m agent_eval_harness` loads a Cline World-A
> trace, scores tool selection, and emits a report against Cline's golden fixture. Next up: the
> code-diff-quality scorer (the wedge).

## What makes it different

None of the mainstream eval frameworks ship a first-class **code-diff-quality scorer** or replay a
real coding-agent trace. This does — starting with Cline, whose community it's built to serve.

## Development

`src`-layout package (`import agent_eval_harness`), Python 3.11+.

```bash
pip install -e .        # editable install, from inside this worktree
pip install pytest      # dev-only
pytest -q               # run the tests
python -m agent_eval_harness <trace.json> --expected read_files
```

Tests are install-independent (`pyproject.toml` sets `pythonpath = ["src"]`), so `pytest -q` works
even without an install. `python -m agent_eval_harness` does need the package importable — install it
in the current worktree or prefix with `PYTHONPATH=src`. See [CONTRIBUTING.md](CONTRIBUTING.md) for the
multi-worktree editable-install gotcha.
