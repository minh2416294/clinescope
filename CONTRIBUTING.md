# Contributing to clinescope

Thanks for helping build clinescope. Small, discussed-first changes are the norm here — for anything
larger than a bug fix or a doc tweak, please open an issue first so we can agree on the shape before
you write code.

This is a `src`-layout Python package (`import clinescope`), Python 3.11+.

## Dev setup

Fork and clone, then install the package **editable, with the dev extras**, from inside your checkout:

```bash
git clone https://github.com/<you>/clinescope
cd clinescope
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash; use bin/activate on macOS/Linux
pip install -e ".[dev]"
```

The `[dev]` extra pulls in `pytest`, `ruff`, and `mypy` — the same tools CI runs.

## Running the tests and linters

Run these before you push; they are exactly what CI checks:

```bash
pytest -q                 # tests
ruff check .              # lint
ruff format --check .     # formatting (drop --check to auto-format)
mypy src                  # type-check
```

`pytest` is install-independent — `pyproject.toml` sets `[tool.pytest.ini_options] pythonpath = ["src"]`,
so `pytest -q` finds the package whether or not it's installed.

## The multi-worktree editable-install gotcha (read this if you use git worktrees)

An editable install (`pip install -e .`) writes a `.pth` into the active virtualenv that pins imports to
**one** checkout's `src/`. If you share a single `.venv` across several git worktrees of this repo,
whichever worktree ran `pip install -e .` **last** wins — the others import stale code, or fail with
`No module named clinescope`, even though their own source is correct.

Two ways to stay safe:

- **Re-run `pip install -e .` inside the worktree you're working in** (repoints the `.pth`), **or**
- **Use `PYTHONPATH=src`** for a one-off run, which needs no install:

  ```bash
  PYTHONPATH=src python -m clinescope examples/sample-trace.json --expected read_files apply_patch
  ```

The gotcha only bites `python -m clinescope` (and editor type-checkers), which don't read
`pyproject.toml`; `pytest` is already immune via the setting above.

## Fork, branch, PR

1. Fork the repo and create a branch off `main` (`fix/…`, `feat/…`, `chore/…`).
2. Make the change; keep the diff focused on one thing.
3. Run the tests + linters above until they're all green.
4. Push to your fork and open a PR against `minh2416294/clinescope:main`. CI runs on the PR.

## What a PR should include

- **A scorer change needs a trace + its expected score.** Add (or extend) a fixture trace and assert
  the number the scorer should produce on it — a scorer without a test proving its output isn't
  reviewable. Never edit or copy in Cline's own golden fixture; add your own small synthetic trace
  (see `examples/sample-trace.json` for the World-A v1 shape).
- **Open an issue first for anything large** — a new scorer, a new adapter, a format change. A quick
  agreement on the approach saves a rewrite.
- Keep behavior changes and refactors in separate commits where you can; explain *why* in the PR body,
  not just *what*.
