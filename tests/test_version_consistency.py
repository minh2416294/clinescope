"""Version-consistency guard: ``pyproject.toml`` and ``__version__`` must agree.

The package version lives in two files and, until this test, nothing compared
them. ``src/clinescope/__init__.py`` defines ``__version__``, which is what a
user reads via ``python -c "import clinescope; print(clinescope.__version__)"``
(the check ``docs/quickstart.md`` documents, since there is no ``--version``
flag). ``pyproject.toml`` holds the version hatchling stamps into the sdist and
the wheel, which is what pip and PyPI resolve against.

Bumping one and forgetting the other passed the whole suite, mypy, and CI.
``release.yml`` does not check the version either, and it runs no tests at all.
The result would be a published wheel reporting the previous release as its
``__version__``, with nothing anywhere saying so. This test is the only thing
that catches that.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import clinescope

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_pyproject_version_matches_dunder_version() -> None:
    packaged = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"][
        "version"
    ]

    assert packaged == clinescope.__version__, (
        f"version mismatch: pyproject.toml says {packaged!r} but "
        f"clinescope.__version__ says {clinescope.__version__!r}. A release bumps "
        f"both (see CONTRIBUTING.md, 'Releasing'). Bumping one ships a wheel whose "
        f"reported version is wrong."
    )
