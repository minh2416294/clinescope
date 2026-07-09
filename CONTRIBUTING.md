# Contributing to clinescope

Thanks for helping build clinescope. This is a `src`-layout Python package
(`import clinescope`), Python 3.11+.

## Setup

Clone, then install the package **editable, from inside the worktree you are working in**:

```bash
pip install -e .
pip install pytest   # dev-only; not a runtime dependency
```

## The multi-worktree editable-install gotcha (read this)

An editable install (`pip install -e .`) writes a `.pth` file into the active virtualenv that pins
imports to **one** checkout's `src/` directory. If you share a single `.venv` across several git
worktrees of this repo, whichever worktree ran `pip install -e .` **last** wins — the others will
import stale code (or fail with `ModuleNotFoundError`) even though their own source is correct.

Two ways to stay safe:

- **Re-run `pip install -e .` inside the worktree you're currently working in** (repoints the `.pth`
  to that worktree), **or**
- **Skip the editable install and use `PYTHONPATH=src`** for a run, which needs no install at all:

  ```bash
  PYTHONPATH=src pytest -q
  PYTHONPATH=src python -m clinescope <trace.json> --expected read_files
  ```

`pytest` itself is already install-independent here: `pyproject.toml` sets
`[tool.pytest.ini_options] pythonpath = ["src"]`, so plain `pytest -q` finds the package regardless of
what any `.pth` points at. The gotcha only bites `python -m clinescope`, which does not read
`pyproject.toml`.

## Running the tests

```bash
pytest -q
```

## Running the CLI

```bash
python -m clinescope <trace.json> --expected <tool names...>
# e.g.
python -m clinescope path/to/messages.json --expected read_files write_file
```

If `python -m clinescope` reports `No module named clinescope.__main__`, your editable
install is pinned to another worktree — re-run `pip install -e .` here, or prefix with `PYTHONPATH=src`.
