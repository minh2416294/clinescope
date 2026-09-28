"""The one path-spelling rule both recovery scorers match files with.

A Cline trace can name one Windows file three ways: ``/c/Users/...`` (reached through
Git Bash), ``C:\\Users\\...`` (through PowerShell) and ``c:/Users/...``.
:mod:`clinescope.apply_recovery` and :mod:`clinescope.editor_recovery` both compare
:func:`recovery_path_key` values, so a confirmed retry under another spelling of the
same file counts as a recovery.

Pure string rules, with no :mod:`os.path` and no :mod:`pathlib`, so one trace gets one
score on Windows and on a Linux CI runner:

* every ``\\`` becomes ``/``;
* a leading ``/x/``, where ``x`` is one ASCII letter, becomes ``x:/``;
* the drive letter is lowercased, and nothing else is.

Everything after the drive keeps its case, because two paths that differ only in case
are two files on Linux. Folding case would merge them and raise a score for a failure
that was never fixed.

The rule has one known false match. On Linux ``/c/data/x.py`` is a real top-level
folder named ``c``, and it gets the same key as ``C:\\data\\x.py``. Both spellings have
to appear in one trace for that to matter.
"""

from __future__ import annotations

import re

_GIT_BASH_DRIVE = re.compile(r"^/([A-Za-z])/")
_WINDOWS_DRIVE = re.compile(r"^([A-Za-z]):/")


def recovery_path_key(raw: str) -> str:
    """The key two spellings of one file share. Match on this; display the raw path."""
    path = raw.replace("\\", "/")
    path = _GIT_BASH_DRIVE.sub(lambda m: f"{m.group(1)}:/", path, count=1)
    return _WINDOWS_DRIVE.sub(lambda m: f"{m.group(1).lower()}:/", path, count=1)
