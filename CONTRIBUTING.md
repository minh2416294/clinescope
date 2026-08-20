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

The `[dev]` extra pulls in `pytest`, `pytest-cov`, `ruff`, and `mypy` — the same tools CI runs.

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

CI additionally runs the suite under coverage and **fails if line coverage drops below 90%**
(measured at 94%). To reproduce that gate locally:

```bash
pytest -q --cov=clinescope --cov-report=term-missing --cov-fail-under=90
```

A bare `pytest -q` still works without the coverage plugin — the `--cov` flags live on the CI command
line, not in `addopts`, so base pytest isn't required to run the tests.

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

## Releasing (maintainer only)

Releases publish to PyPI automatically via **Trusted Publishing** (OIDC) — there is no PyPI API token
stored in the repo. `.github/workflows/release.yml` builds the sdist + wheel and uploads them when a
**GitHub Release is published** (not on a tag alone, and never on a PR).

**A published version is permanent.** PyPI does not allow a filename to be reused, even after the
release is deleted, so a wrong upload cannot be replaced: it can only be yanked and superseded by the
next version number. Every step below is free to abort except the last one.

To cut a release:

1. Bump the version in **both** places, on a branch:
   - `pyproject.toml`, `[project] version`
   - `src/clinescope/__init__.py`, `__version__`

   `tests/test_version_consistency.py` fails if they disagree. Bumping only one used to be silent.
2. **Add a `CHANGELOG.md` entry** for the new version: a `## [x.y.z] - YYYY-MM-DD` heading, the
   Added / Changed / Fixed / Notes sections, and a matching link reference at the bottom of the file.
   This step is easy to skip and nothing enforces it. 1.2.0 shipped without an entry and it had to be
   reconstructed from `git log` four weeks later.
3. Open a PR and land it on `main`.
4. Wait for the push-to-main CI run to go green **on the merge commit itself**, not just on the PR
   head. `release.yml` runs no tests at all, so this is the only gate between a broken `main` and PyPI.
5. Pre-tag checks, on a clean checkout of merged `main`. Any failure here is free to fix:
   - local `main` matches `git ls-remote origin refs/heads/main`
   - both version strings agree and the value is new
   - `https://pypi.org/pypi/clinescope/<version>/json` returns 404
   - `python -m build` emits exactly `clinescope-<version>.tar.gz` and
     `clinescope-<version>-py3-none-any.whl` and nothing else (this is the same command the workflow
     runs, so it predicts the upload)
   - that wheel installs into a throwaway venv and `clinescope-corpus` exits 0
6. **Create and push the tag first**, before opening the Release form:
   `git tag -a v<version> -m "clinescope <version>"` then `git push origin v<version>`. Pushing a tag
   triggers nothing.
7. On GitHub, **Releases → Draft a new release**, and **select the existing tag** from the dropdown.
   If the dropdown offers to create the tag on publish, stop: the push in step 6 did not reach origin.
   Letting the form create the tag is how a release gets built from the wrong commit, and a wrong
   build that succeeds is unrecoverable. `gh release create --verify-tag` enforces the same thing.
8. **Publish.** This is the irreversible step. The `Release` workflow runs and uploads to PyPI.
9. Verify the new version renders at <https://pypi.org/project/clinescope/> with **both** files under
   Download files, and installs cleanly into a fresh venv (`pip install clinescope` →
   `clinescope-corpus` exits 0).

If the publish job fails before anything uploads (build error, OIDC error, or a pending environment
review), nothing is burned: fix it and re-run the failed job, keeping the same version number. If it
uploads and the result is wrong, yank that version and ship the next patch. Do not delete it, because
deletion is permanent, does not free the filename, and cannot be undone.

One-time setup (already configured; documented here for the record) — on PyPI, **Account → Publishing →
Add a pending publisher** with: PyPI Project Name `clinescope`, Owner `minh2416294`, Repository name
`clinescope`, Workflow name `release.yml`, Environment name `pypi`; and a GitHub repo Environment named
`pypi` (Settings → Environments), where an optional required-reviewer gate can be added.
