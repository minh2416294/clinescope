"""Guard the ``docs/internal/`` contract set against the two ways it rots silently.

``docs/internal/`` is agent-facing documentation whose entire value is that a later
session can trust its pointers instead of re-deriving them. Nothing else in this suite
reads a markdown file, and mypy covers only ``src`` and ``scripts``, so both failures
below are invisible to every other check in the build.

1. A pointer names a path that no longer exists. A rename anywhere in the tree leaves
   the pointer wrong and the whole build green, which is worse than having no document:
   a later session confidently re-derives a layout the code already abandoned.
2. A pointer locates a fact by line number. Line numbers move. The commit before this
   directory existed changed documentation only, and still shifted four of the five line
   numbers the honesty rule in ``CLAUDE.md`` tracks, because it added lines above them.
   So this set locates a fact by file plus a stable heading or symbol name, and this test
   is what stops that decision decaying into a convention nobody remembers.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DOCS_INTERNAL = _REPO_ROOT / "docs" / "internal"

# A backticked token counts as a repo path claim when its first segment is one of these.
# Anything else in backticks is prose, a symbol name, or a command, and is not checked.
_KNOWN_ROOTS = frozenset(
    {".claude", ".github", "docs", "examples", "gold", "scripts", "src", "tests"}
)

# Root-level files carry no slash, so they are recognised by name instead.
_KNOWN_ROOT_FILES = frozenset(
    {
        "CHANGELOG.md",
        "CLAUDE.md",
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
        "LIMITATIONS.md",
        "README.md",
        "REVIEW.md",
        "pyproject.toml",
    }
)

_BACKTICKED = re.compile(r"`([^`\n]+)`")
_MARKDOWN_LINK = re.compile(r"\]\(([^)\s]+)\)")
_POSITIONAL_POINTER = re.compile(
    r"[\w./-]+\.(?:py|md|yml|yaml|toml|json|jsonl|svg):\d+"
)


def _internal_docs() -> list[Path]:
    return sorted(_DOCS_INTERNAL.glob("*.md"))


def _claimed_repo_paths(text: str) -> set[str]:
    claimed: set[str] = set()
    for token in _BACKTICKED.findall(text):
        candidate = token.rstrip("/")
        if "/" in candidate and candidate.split("/", 1)[0] in _KNOWN_ROOTS:
            claimed.add(candidate)
        elif candidate in _KNOWN_ROOT_FILES:
            claimed.add(candidate)
    return claimed


def test_docs_internal_is_present_and_not_empty() -> None:
    assert _internal_docs(), (
        f"no markdown found under {_DOCS_INTERNAL}. CLAUDE.md tells every session to "
        f"read this directory before working here, so an empty one is a broken promise."
    )


def test_every_repo_path_named_in_docs_internal_resolves() -> None:
    missing: list[str] = []
    for doc in _internal_docs():
        text = doc.read_text(encoding="utf-8")
        for claimed in sorted(_claimed_repo_paths(text)):
            if not (_REPO_ROOT / claimed).exists():
                missing.append(f"{doc.name} names {claimed}")
        for target in _MARKDOWN_LINK.findall(text):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            if not (doc.parent / target.split("#", 1)[0]).exists():
                missing.append(f"{doc.name} links {target}")

    assert not missing, (
        "docs/internal/ points at paths that do not exist: "
        + "; ".join(missing)
        + ". Update the pointer in the same commit that moved the file."
    )


def test_docs_internal_uses_no_line_number_pointers() -> None:
    offenders: list[str] = []
    for doc in _internal_docs():
        for hit in _POSITIONAL_POINTER.findall(doc.read_text(encoding="utf-8")):
            offenders.append(f"{doc.name}: {hit}")

    assert not offenders, (
        "docs/internal/ locates a fact by line number: "
        + "; ".join(offenders)
        + ". Line numbers move on any edit above them. Point at the file plus a stable "
        "heading or symbol name instead."
    )
