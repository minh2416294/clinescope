"""``recovery_path_key``: the one spelling rule both recovery scorers match paths with.

Pure string rules, so one trace scores the same on Windows and on a Linux CI runner.
Only the separator and the drive prefix are folded. Everything after the drive keeps
its case, because two paths that differ only in case are two files on Linux.
"""

from __future__ import annotations

import pytest

from clinescope.recovery_path import recovery_path_key


@pytest.mark.parametrize(
    ("raw", "key"),
    [
        # The three spellings of one Windows file a Cline trace can carry.
        ("/c/Users/m/app.py", "c:/Users/m/app.py"),
        ("C:\\Users\\m\\app.py", "c:/Users/m/app.py"),
        ("c:/Users/m/app.py", "c:/Users/m/app.py"),
        ("/C/Users/m/app.py", "c:/Users/m/app.py"),
        # Case after the drive is kept: still a different key.
        ("C:\\Users\\M\\app.py", "c:/Users/M/app.py"),
        # Relative paths only fold the separator.
        ("src\\app.py", "src/app.py"),
        ("src/app.py", "src/app.py"),
        # Not a drive prefix: a longer first segment, or no slash after the letter.
        ("/cdrive/x.py", "/cdrive/x.py"),
        ("/c", "/c"),
        ("/home/m/app.py", "/home/m/app.py"),
    ],
)
def test_recovery_path_key(raw: str, key: str) -> None:
    assert recovery_path_key(raw) == key
