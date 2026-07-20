"""Discover Cline VS Code extension sessions on disk, per-OS, stdlib only.

The Cline VS Code extension stores each task under its per-extension VS Code
global storage:

    <VSCode-User-dir>/globalStorage/saoudrizwan.claude-dev/
      state/taskHistory.json          # HistoryItem[]: {id, ts (epoch ms), task}
      tasks/<taskId>/
        api_conversation_history.json # Anthropic.MessageParam[] (bare array)
        ui_messages.json              # ClineMessage[]

Verified against Cline upstream ``cline/cline`` main (HEAD 1843bc8, 2026-07-16):
the extension resolves its root from VS Code's ``context.globalStorageUri.fsPath``
(``apps/vscode/src/extension.ts``), and ``vscode-to-file-migration.ts`` states
task data + taskHistory are NOT migrated to ``~/.cline/data`` (that root is the
CLI/standalone host). So a real extension user's sessions live under the VS Code
global-storage root; ``~/.cline/data`` (and the ``CLINE_DATA_DIR`` / ``CLINE_DIR``
env overrides) is the fallback for CLI/standalone traces, whose ``tasks/<taskId>/``
layout is identical.

Only ``Code`` and ``Code - Insiders`` are documented VS Code product folders;
VSCodium / Cursor / Windsurf follow the same ``User/globalStorage/`` convention by
fork convention, backstopped by an explicit ``--path`` in the CLI. Nothing here
imports a third-party package: discovery is pure ``os`` / ``pathlib`` / ``json``.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from clinescope.world_a import WorldATraceError

_EXTENSION_ID = "saoudrizwan.claude-dev"

# VS Code and its forks each keep their own ``<Product>/User`` dir; the
# globalStorage tail is identical. Stable release first.
_PRODUCT_FOLDERS = ("Code", "Code - Insiders", "VSCodium", "Cursor", "Windsurf")


class ExtensionStorageNotFound(WorldATraceError):
    """No Cline VS Code extension storage (with sessions) could be located.

    Inherits from ``WorldATraceError`` so a caller that already catches World-A
    load errors keeps working. The message names the paths that were tried and the
    ``--path`` escape hatch, so the failure is actionable, never silent.
    """


@dataclass(frozen=True, slots=True)
class DiscoveredRoot:
    """A located ``.../saoudrizwan.claude-dev`` storage root and its variant."""

    path: Path
    variant: str


@dataclass(frozen=True, slots=True)
class ExtensionSession:
    """One extension task on disk, with a human-readable label when recoverable."""

    task_id: str
    task_dir: Path
    api_history_path: Path
    variant: str
    title: str | None
    timestamp_ms: int | None


def discover_storage_roots(
    *,
    platform: str | None = None,
    env: dict[str, str] | None = None,
    home: Path | None = None,
) -> list[DiscoveredRoot]:
    """Return every existing Cline extension storage root, overrides first.

    ``platform`` / ``env`` / ``home`` are injectable for testing; they default to
    the live ``sys.platform`` / ``os.environ`` / ``Path.home()``. A root is
    included only if it exists and has a ``tasks/`` subdirectory.
    """
    platform = platform if platform is not None else sys.platform
    env = env if env is not None else _live_env()
    home = home if home is not None else Path.home()

    roots: list[DiscoveredRoot] = []
    seen: set[Path] = set()

    for path, variant in _candidate_roots(platform, env, home):
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if (path / "tasks").is_dir():
            roots.append(DiscoveredRoot(path=path, variant=variant))
    return roots


def enumerate_sessions(root: Path) -> list[ExtensionSession]:
    """List valid tasks under ``root``, labeled and sorted newest-first.

    A task dir counts only if it holds an ``api_conversation_history.json`` (the
    file every scorer needs); a dir with only ``ui_messages.json`` (aborted before
    the first API round-trip) is skipped, not failed. Labels come from
    ``state/taskHistory.json`` first, then the ``ui_messages.json`` ``say:"task"``
    text, then none. Ordering uses the history ``ts``, else the folder mtime.
    """
    variant = _variant_for_root(root)
    history = _read_task_history(root)
    sessions: list[ExtensionSession] = []

    tasks_dir = root / "tasks"
    if not tasks_dir.is_dir():
        return sessions

    for task_dir in tasks_dir.iterdir():
        api_history_path = task_dir / "api_conversation_history.json"
        if not task_dir.is_dir() or not api_history_path.is_file():
            continue
        task_id = task_dir.name
        title, ts = _resolve_label(task_id, task_dir, history)
        sessions.append(
            ExtensionSession(
                task_id=task_id,
                task_dir=task_dir,
                api_history_path=api_history_path,
                variant=variant,
                title=title,
                timestamp_ms=ts,
            )
        )

    sessions.sort(key=_session_sort_key, reverse=True)
    return sessions


def discover_sessions(
    *,
    platform: str | None = None,
    env: dict[str, str] | None = None,
    home: Path | None = None,
    variant: str | None = None,
) -> list[ExtensionSession]:
    """Discover and merge every extension session, newest-first across variants.

    ``variant`` narrows discovery to a single product folder (e.g. ``"Cursor"``).
    Raises :class:`ExtensionStorageNotFound` (naming the paths tried) when no
    storage root exists at all, so the caller can surface an actionable error.
    """
    roots = discover_storage_roots(platform=platform, env=env, home=home)
    if variant is not None:
        roots = [r for r in roots if r.variant == variant]
    if not roots:
        raise ExtensionStorageNotFound(_not_found_message(platform, env, home, variant))

    merged: list[ExtensionSession] = []
    for root in roots:
        merged.extend(enumerate_sessions(root.path))
    merged.sort(key=_session_sort_key, reverse=True)
    return merged


# --- candidate roots ----------------------------------------------------------


def _candidate_roots(
    platform: str, env: dict[str, str], home: Path
) -> list[tuple[Path, str]]:
    """Ordered (root, variant) candidates: env overrides first, then per-OS."""
    candidates: list[tuple[Path, str]] = []

    # A CLINE_DATA_DIR / CLINE_DIR override points at a data dir whose tasks/ layout
    # is identical to the extension root (CLI/standalone host). Honor it first.
    data_dir = _cline_data_dir_override(env)
    if data_dir is not None:
        candidates.append((data_dir, "cline-data-dir"))

    for user_dir, variant in _vscode_user_dirs(platform, env, home):
        candidates.append((user_dir / "globalStorage" / _EXTENSION_ID, variant))
    return candidates


def _cline_data_dir_override(env: dict[str, str]) -> Path | None:
    if env.get("CLINE_DATA_DIR"):
        return Path(env["CLINE_DATA_DIR"])
    if env.get("CLINE_DIR"):
        return Path(env["CLINE_DIR"]) / "data"
    return None


def _vscode_user_dirs(
    platform: str, env: dict[str, str], home: Path
) -> list[tuple[Path, str]]:
    """Per-OS ``<base>/<Product>/User`` dirs, one per known product folder."""
    base = _vscode_config_base(platform, env, home)
    return [(base / product / "User", product) for product in _PRODUCT_FOLDERS]


def _vscode_config_base(platform: str, env: dict[str, str], home: Path) -> Path:
    if platform == "win32":
        appdata = env.get("APPDATA")
        return Path(appdata) if appdata else home / "AppData" / "Roaming"
    if platform == "darwin":
        return home / "Library" / "Application Support"
    xdg = env.get("XDG_CONFIG_HOME")
    return Path(xdg) if xdg else home / ".config"


def _variant_for_root(root: Path) -> str:
    """Recover the product-folder name from a root path, for the picker label."""
    for part in root.parts:
        if part in _PRODUCT_FOLDERS:
            return part
    return "cline-data-dir" if root.name != _EXTENSION_ID else "extension"


# --- labels -------------------------------------------------------------------


def _read_task_history(root: Path) -> dict[str, dict[str, object]]:
    """Load ``state/taskHistory.json`` (with a defensive ``tasks/`` fallback).

    Cline's own source is momentarily self-contradictory on the path (a doc-block
    says ``state/taskHistory.json``, a stale comment says ``tasks/taskHistory.json``),
    so probe both. Returns an ``{id: item}`` map; a missing file yields an empty map
    silently, and a present-but-corrupt file yields an empty map after a stderr
    warning (see ``_read_json_list``). Enumeration never crashes either way; it just
    proceeds without labels.
    """
    for candidate in (
        root / "state" / "taskHistory.json",
        root / "tasks" / "taskHistory.json",
    ):
        items = _read_json_list(candidate)
        if items is None:
            continue
        indexed: dict[str, dict[str, object]] = {}
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                indexed[item["id"]] = item
        if indexed:
            return indexed
    return {}


def _resolve_label(
    task_id: str, task_dir: Path, history: dict[str, dict[str, object]]
) -> tuple[str | None, int | None]:
    item = history.get(task_id)
    title = _clean_title(item.get("task")) if item else None
    ts = item.get("ts") if item else None
    timestamp = ts if isinstance(ts, int) and not isinstance(ts, bool) else None

    if title is None:
        title = _title_from_ui_messages(task_dir)
    if timestamp is None:
        timestamp = _timestamp_from_folder(task_id, task_dir)
    return title, timestamp


def _title_from_ui_messages(task_dir: Path) -> str | None:
    messages = _read_json_list(task_dir / "ui_messages.json")
    if not messages:
        return None
    # Defensive: find the say:"task" message, do not assume it is index 0.
    for message in messages:
        if (
            isinstance(message, dict)
            and message.get("type") == "say"
            and message.get("say") == "task"
            and isinstance(message.get("text"), str)
        ):
            return _clean_title(message["text"])
    return None


def _clean_title(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    # The first user message wraps the prompt as <task>...</task>; strip it for
    # display. Cline's own formatter does not strip <task>, so we do it here.
    if text.startswith("<task>") and text.endswith("</task>"):
        text = text[len("<task>") : -len("</task>")].strip()
    return text or None


def _timestamp_from_folder(task_id: str, task_dir: Path) -> int | None:
    # A classic taskId is epoch-ms; use it when numeric, else the folder mtime.
    if task_id.isdigit():
        return int(task_id)
    try:
        return int(task_dir.stat().st_mtime * 1000)
    except OSError:
        return None


def _session_sort_key(session: ExtensionSession) -> int:
    return session.timestamp_ms if session.timestamp_ms is not None else 0


# --- io helpers ---------------------------------------------------------------


def _read_json_list(path: Path) -> list[object] | None:
    """Read a JSON array from ``path``; return None if absent, unreadable, or non-array.

    An ABSENT file (never written) is a normal, expected case and returns None
    silently. A file that EXISTS but cannot be read or parsed (corrupt JSON, wrong
    encoding, permission denied) is a real anomaly the user should know about, so it
    warns to stderr before returning None. Either way the caller still degrades
    gracefully (no crash), but a broken file is never mistaken for an absent one.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        return None
    except (OSError, UnicodeDecodeError) as err:
        print(
            f"warning: could not read {path}: {type(err).__name__}: {err}",
            file=sys.stderr,
        )
        return None
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as err:
        print(
            f"warning: could not parse {path}: {type(err).__name__}: {err}",
            file=sys.stderr,
        )
        return None
    return raw if isinstance(raw, list) else None


def _live_env() -> dict[str, str]:
    import os

    return dict(os.environ)


def _not_found_message(
    platform: str | None,
    env: dict[str, str] | None,
    home: Path | None,
    variant: str | None,
) -> str:
    platform = platform if platform is not None else sys.platform
    env = env if env is not None else _live_env()
    home = home if home is not None else Path.home()
    tried = [str(path) for path, _ in _candidate_roots(platform, env, home)]
    scope = f" for variant '{variant}'" if variant else ""
    return (
        f"No Cline VS Code extension storage found{scope}. Looked in: "
        f"{', '.join(tried)}. If VS Code is installed elsewhere or in portable "
        "mode, or you use a CLI/standalone trace, pass --path <task-dir-or-file>."
    )
