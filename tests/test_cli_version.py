"""``clinescope --version`` prints the package name and the version pyproject.toml declares.

The expected value is read from ``pyproject.toml``, the file that owns the released version,
rather than from ``clinescope.__version__``, so this test cannot pass by echoing the mirror.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from clinescope.__main__ import main

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_version_flag_prints_name_and_pyproject_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    declared = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"][
        "version"
    ]

    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f"clinescope {declared}\n"
