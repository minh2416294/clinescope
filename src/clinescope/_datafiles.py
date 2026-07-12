"""Locate clinescope's bundled data (``examples/`` + ``gold/``) from anywhere.

The default-data features -- the real-trace corpus (:mod:`clinescope.corpus`), the gold
set + judge cache (:mod:`clinescope.gold`, :mod:`clinescope.judge_run`) -- read committed
files by a repo-relative path. From a source checkout that is the repo root (cwd). But a
``pip install`` user has no repo: the files ship inside the wheel (via
``[tool.hatch.build.targets.wheel.force-include]``), so a cwd-relative default resolves to
nothing and the feature crashes.

This module resolves the DATA ROOT -- the directory that contains ``examples/`` and
``gold/`` -- independent of the current working directory, so those defaults work from a
source checkout AND from an installed wheel. It does NOT change the public
``repo_root=`` parameters (a caller may still point at any tree); it only supplies the
DEFAULT base when the caller does not.

**How it resolves (first hit wins):**

1. The current working directory, if it already contains ``examples/`` + ``gold/`` --
   preserves the historical "run from the repo root" behaviour byte-for-byte.
2. The directory that ships alongside the installed package. With force-include the data
   lands next to the ``clinescope`` package dir (``site-packages/examples``,
   ``site-packages/gold``); in the src-layout dev tree it is two levels above the package
   (``<repo>/examples``). Both candidates are probed via ``importlib.resources`` on the
   package's anchor, falling back to ``__file__`` walking.

If none contains the data, the resolver raises a clear :class:`DataFilesNotFound` naming
what it looked for -- never a bare ``FileNotFoundError`` deep inside a loader.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

# The two directories that together mark a valid clinescope data root.
_DATA_MARKERS = ("examples", "gold")


class DataFilesNotFound(RuntimeError):
    """The bundled ``examples/`` + ``gold/`` data root could not be located."""


def datafiles_root() -> Path:
    """Return the directory that contains clinescope's ``examples/`` + ``gold/`` data.

    Tries the current working directory first (a source checkout), then the location the
    data ships at alongside the installed package. Raises :class:`DataFilesNotFound` if
    neither has the data.
    """
    for candidate in _datafiles_candidate_roots():
        if _datafiles_is_root(candidate):
            return candidate
    tried = ", ".join(str(c) for c in _datafiles_candidate_roots())
    raise DataFilesNotFound(
        "could not locate clinescope's bundled data (an 'examples/' and 'gold/' "
        f"directory). Looked in: {tried}. Run from a source checkout, or pass an "
        "explicit path (e.g. `clinescope-corpus <manifest>`)."
    )


def datafiles_path(*parts: str) -> Path:
    """Resolve a data-relative path (e.g. ``"gold", "diff_minimality.gold.jsonl"``).

    Joins ``parts`` onto :func:`datafiles_root`. The returned path is NOT required to
    exist (a caller may build a default that a loader then checks); it is only anchored to
    the located data root.
    """
    return datafiles_root().joinpath(*parts)


def _datafiles_candidate_roots() -> tuple[Path, ...]:
    """Ordered candidate data roots: cwd first, then package-adjacent locations."""
    candidates: list[Path] = [Path.cwd()]
    candidates.extend(_datafiles_package_adjacent_roots())
    # De-dupe while preserving order (cwd may coincide with a package root in dev).
    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return tuple(unique)


def _datafiles_package_adjacent_roots() -> list[Path]:
    """Candidate roots derived from where the ``clinescope`` package is installed.

    force-include lands the data at ``site-packages/`` (one level ABOVE the package dir);
    the src-layout dev tree keeps it two levels above (``<repo>/examples`` vs
    ``<repo>/src/clinescope``). Probe both, via ``importlib.resources`` then ``__file__``.
    """
    roots: list[Path] = []
    try:
        anchor = resources.files("clinescope")
        pkg_dir = Path(str(anchor))
    except (
        ModuleNotFoundError,
        TypeError,
    ):  # pragma: no cover - clinescope is importable
        pkg_dir = Path(__file__).resolve().parent
    # site-packages/clinescope -> site-packages (wheel force-include target)
    roots.append(pkg_dir.parent)
    # <repo>/src/clinescope -> <repo> (src-layout dev checkout)
    roots.append(pkg_dir.parent.parent)
    return roots


def _datafiles_is_root(candidate: Path) -> bool:
    """True iff ``candidate`` contains every data marker directory."""
    return all((candidate / marker).is_dir() for marker in _DATA_MARKERS)
