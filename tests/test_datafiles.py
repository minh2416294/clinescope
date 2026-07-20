"""Tests for the bundled-data resolver (_datafiles) + corpus base-dir threading.

These pin the behaviour that makes `clinescope-corpus` / `judge_run` work from a pip
install: the resolver finds the data root by MARKER directories (examples/ + gold/),
independent of cwd, and the corpus resolves its manifest's trace keys against a base dir.
A real wheel-install smoke test lives outside the suite (it needs `python -m build`); here
we simulate the two roots with tmp dirs so the logic is unit-tested deterministically.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clinescope._datafiles import (
    DataFilesNotFound,
    datafiles_path,
    datafiles_root,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_datafiles_root_finds_the_source_checkout_from_its_cwd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Running from the repo root: cwd itself is a valid data root (has examples/ + gold/).
    monkeypatch.chdir(_REPO_ROOT)
    root = datafiles_root()
    assert (root / "examples").is_dir()
    assert (root / "gold").is_dir()


def test_datafiles_root_finds_data_from_a_neutral_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # From a directory with NO data dirs, the resolver must still find the packaged data
    # via the package-adjacent fallback (this is the pip-install path).
    monkeypatch.chdir(tmp_path)
    root = datafiles_root()
    assert (root / "examples").is_dir()
    assert (root / "gold").is_dir()


def test_datafiles_path_joins_onto_the_root() -> None:
    p = datafiles_path("gold", "diff_minimality.gold.jsonl")
    assert p.name == "diff_minimality.gold.jsonl"
    assert p.parent.name == "gold"


def test_datafiles_root_raises_a_clear_error_when_nothing_has_the_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Force BOTH resolution avenues to miss: cwd is empty and the package-adjacent probe
    # is redirected to an empty tree. The resolver must raise DataFilesNotFound, not a
    # bare FileNotFoundError deep in a loader.
    monkeypatch.chdir(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(
        "clinescope._datafiles._datafiles_package_adjacent_roots",
        lambda: [empty],
    )
    with pytest.raises(DataFilesNotFound, match="examples/' and 'gold/'"):
        datafiles_root()


def test_corpus_default_runs_from_a_neutral_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The corpus CLI with no manifest arg must resolve the bundled corpus + its trace
    # keys from a directory that has no examples/ or gold/ (the pip-install scenario,
    # simulated here by chdir-ing away from the repo root).
    from clinescope.corpus import main

    monkeypatch.chdir(tmp_path)
    exit_code = main([])
    assert exit_code == 0  # the committed corpus is 6/6 by label


def test_corpus_run_resolves_keys_against_base_dir(tmp_path: Path) -> None:
    # A manifest whose single key is a plain filename resolves against base_dir, so a
    # caller can point the corpus at data anywhere (this is what makes the packaged path
    # work). Reuse a real committed trace by copying it under a temp base dir.
    import json
    import shutil

    from clinescope.corpus import run_corpus

    src = _REPO_ROOT / "examples" / "sample-trace.json"
    shutil.copy(src, tmp_path / "sample-trace.json")
    manifest = tmp_path / "m.json"
    manifest.write_bytes(
        json.dumps(
            {"sample-trace.json": {"display": "s", "expected_tools": ["read_files"]}}
        ).encode("utf-8")
    )
    report = run_corpus(manifest, base_dir=tmp_path)
    assert len(report.items) == 1
    assert report.items[0].loaded  # resolved via base_dir / key, not cwd / key


def test_demo_trace_is_reachable_via_datafiles_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # `clinescope --demo` hardcodes this filename and resolves it via datafiles_root().
    # From a neutral cwd (the pip-install scenario) it must resolve, else the demo
    # silently breaks for a stranger. Renaming/dropping the example turns this red.
    monkeypatch.chdir(tmp_path)
    demo = datafiles_root() / "examples" / "live-gpt-oss-apply-fail.json"
    assert demo.is_file()


def test_package_ships_a_pep561_py_typed_marker() -> None:
    # clinescope is a library others import; without a py.typed marker (PEP 561) a
    # downstream mypy/pyright IGNORES all of its inline annotations. This asserts the
    # marker is resolvable as package data (the same way a type-checker discovers it),
    # so a build that dropped it turns red.
    import importlib.resources as resources

    marker = resources.files("clinescope").joinpath("py.typed")
    assert marker.is_file()
