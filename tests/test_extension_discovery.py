"""Tests for per-OS Cline VS Code extension storage discovery.

The extension stores each task under
``<VSCode-User-dir>/globalStorage/saoudrizwan.claude-dev/tasks/<taskId>/``, with a
sibling ``state/taskHistory.json`` (HistoryItem[]: id, ts, task) for labels. These
tests build FAKE storage trees under ``tmp_path`` and inject the platform / env /
home, so nothing touches a real machine path. Layout + label sources are verified
against Cline upstream source (see the module docstring of
``clinescope.extension_discovery``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinescope.extension_discovery import (
    ExtensionSession,
    ExtensionStorageNotFound,
    discover_sessions,
    discover_storage_roots,
    enumerate_sessions,
)

_EXT_ID = "saoudrizwan.claude-dev"


def _make_task(
    tasks_dir: Path,
    task_id: str,
    *,
    api_history: object = None,
    ui_messages: object = None,
) -> Path:
    task_dir = tasks_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    if api_history is not None:
        (task_dir / "api_conversation_history.json").write_text(
            json.dumps(api_history), encoding="utf-8"
        )
    if ui_messages is not None:
        (task_dir / "ui_messages.json").write_text(
            json.dumps(ui_messages), encoding="utf-8"
        )
    return task_dir


def _list_content(text: str) -> list[dict]:
    # A minimal valid api_conversation_history.json (bare array, list content).
    return [{"role": "user", "content": [{"type": "text", "text": text}]}]


def _ext_root(user_dir: Path) -> Path:
    return user_dir / "globalStorage" / _EXT_ID


def _write_history(ext_root: Path, items: list[dict]) -> None:
    state = ext_root / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "taskHistory.json").write_text(json.dumps(items), encoding="utf-8")


# --- discover_storage_roots (per-OS candidate roots) --------------------------


def test_discovers_windows_appdata_code_root(tmp_path: Path) -> None:
    appdata = tmp_path / "Roaming"
    ext = _ext_root(appdata / "Code" / "User")
    (ext / "tasks").mkdir(parents=True)

    roots = discover_storage_roots(
        platform="win32",
        env={"APPDATA": str(appdata)},
        home=tmp_path / "home",
    )

    assert [r.path for r in roots] == [ext]
    assert roots[0].variant == "Code"


def test_discovers_macos_code_root(tmp_path: Path) -> None:
    home = tmp_path / "home"
    ext = _ext_root(home / "Library" / "Application Support" / "Code" / "User")
    (ext / "tasks").mkdir(parents=True)

    roots = discover_storage_roots(platform="darwin", env={}, home=home)

    assert [r.path for r in roots] == [ext]


def test_discovers_linux_xdg_and_default_config(tmp_path: Path) -> None:
    home = tmp_path / "home"
    ext = _ext_root(home / ".config" / "Code" / "User")
    (ext / "tasks").mkdir(parents=True)

    roots = discover_storage_roots(platform="linux", env={}, home=home)

    assert [r.path for r in roots] == [ext]


def test_windows_appdata_falls_back_to_home_roaming(tmp_path: Path) -> None:
    # APPDATA unset (stripped service account) -> ~/AppData/Roaming.
    home = tmp_path / "home"
    ext = _ext_root(home / "AppData" / "Roaming" / "Code" / "User")
    (ext / "tasks").mkdir(parents=True)

    roots = discover_storage_roots(platform="win32", env={}, home=home)

    assert [r.path for r in roots] == [ext]


def test_multiple_variants_are_all_discovered(tmp_path: Path) -> None:
    home = tmp_path / "home"
    code = _ext_root(home / ".config" / "Code" / "User")
    cursor = _ext_root(home / ".config" / "Cursor" / "User")
    (code / "tasks").mkdir(parents=True)
    (cursor / "tasks").mkdir(parents=True)

    roots = discover_storage_roots(platform="linux", env={}, home=home)

    variants = {r.variant for r in roots}
    assert variants == {"Code", "Cursor"}


def test_cline_data_dir_override_is_honored(tmp_path: Path) -> None:
    # CLINE_DATA_DIR points straight at a data dir whose tasks/ layout is identical.
    data_dir = tmp_path / "custom-cline-data"
    (data_dir / "tasks").mkdir(parents=True)

    roots = discover_storage_roots(
        platform="linux", env={"CLINE_DATA_DIR": str(data_dir)}, home=tmp_path / "home"
    )

    assert data_dir in [r.path for r in roots]


def test_no_storage_found_returns_empty(tmp_path: Path) -> None:
    roots = discover_storage_roots(
        platform="linux", env={}, home=tmp_path / "empty-home"
    )
    assert roots == []


# --- enumerate_sessions (list + label + order) --------------------------------


def test_enumerate_reads_title_and_ts_from_task_history(tmp_path: Path) -> None:
    ext = _ext_root(tmp_path / "User")
    tasks = ext / "tasks"
    _make_task(tasks, "1000", api_history=_list_content("older"))
    _make_task(tasks, "2000", api_history=_list_content("newer"))
    _write_history(
        ext,
        [
            {"id": "1000", "ts": 1000, "task": "Older task"},
            {"id": "2000", "ts": 2000, "task": "Newer task"},
        ],
    )

    sessions = enumerate_sessions(ext)

    # Newest first.
    assert [s.task_id for s in sessions] == ["2000", "1000"]
    assert sessions[0].title == "Newer task"
    assert sessions[0].timestamp_ms == 2000
    assert sessions[1].title == "Older task"


def test_enumerate_skips_subdir_without_api_history(tmp_path: Path) -> None:
    ext = _ext_root(tmp_path / "User")
    tasks = ext / "tasks"
    _make_task(tasks, "good", api_history=_list_content("x"))
    # A subdir with only ui_messages.json (aborted before the first API round-trip).
    _make_task(tasks, "aborted", ui_messages=[{"ts": 1, "type": "say", "say": "task"}])

    sessions = enumerate_sessions(ext)

    assert [s.task_id for s in sessions] == ["good"]


def test_enumerate_falls_back_to_ui_messages_task_say_for_title(tmp_path: Path) -> None:
    # No taskHistory.json: recover the title from the ui_messages say:"task" text.
    ext = _ext_root(tmp_path / "User")
    tasks = ext / "tasks"
    _make_task(
        tasks,
        "42",
        api_history=_list_content("x"),
        ui_messages=[
            {"ts": 5, "type": "say", "say": "api_req_started", "text": "{}"},
            {
                "ts": 3,
                "type": "say",
                "say": "task",
                "text": "<task>\nDo the thing\n</task>",
            },
        ],
    )

    sessions = enumerate_sessions(ext)

    assert len(sessions) == 1
    # The <task> wrapper is stripped for display.
    assert sessions[0].title == "Do the thing"


def test_enumerate_title_none_when_no_label_source(tmp_path: Path) -> None:
    ext = _ext_root(tmp_path / "User")
    tasks = ext / "tasks"
    _make_task(tasks, "77", api_history=_list_content("x"))

    sessions = enumerate_sessions(ext)

    assert sessions[0].task_id == "77"
    assert sessions[0].title is None


def test_enumerate_tolerates_corrupt_task_history(tmp_path: Path) -> None:
    ext = _ext_root(tmp_path / "User")
    tasks = ext / "tasks"
    _make_task(tasks, "9", api_history=_list_content("x"))
    (ext / "state").mkdir(parents=True)
    (ext / "state" / "taskHistory.json").write_text("not json", encoding="utf-8")

    # Corrupt history must not crash enumeration; it just yields no label.
    sessions = enumerate_sessions(ext)
    assert [s.task_id for s in sessions] == ["9"]


def test_enumerate_empty_tasks_dir_returns_empty(tmp_path: Path) -> None:
    ext = _ext_root(tmp_path / "User")
    (ext / "tasks").mkdir(parents=True)
    assert enumerate_sessions(ext) == []


def test_session_is_a_frozen_value_object(tmp_path: Path) -> None:
    ext = _ext_root(tmp_path / "User")
    tasks = ext / "tasks"
    _make_task(tasks, "1", api_history=_list_content("x"))

    session = enumerate_sessions(ext)[0]

    assert isinstance(session, ExtensionSession)
    with pytest.raises((AttributeError, TypeError)):
        session.task_id = "mutated"  # type: ignore[misc]


# --- discover_sessions (top-level, merges variants) ---------------------------


def test_discover_sessions_merges_variants_newest_first(tmp_path: Path) -> None:
    home = tmp_path / "home"
    code = _ext_root(home / ".config" / "Code" / "User")
    cursor = _ext_root(home / ".config" / "Cursor" / "User")
    _make_task(code / "tasks", "1000", api_history=_list_content("code"))
    _make_task(cursor / "tasks", "3000", api_history=_list_content("cursor"))
    _write_history(code, [{"id": "1000", "ts": 1000, "task": "Code task"}])
    _write_history(cursor, [{"id": "3000", "ts": 3000, "task": "Cursor task"}])

    sessions = discover_sessions(platform="linux", env={}, home=home)

    assert [s.task_id for s in sessions] == ["3000", "1000"]
    assert sessions[0].variant == "Cursor"
    assert sessions[1].variant == "Code"


def test_discover_sessions_variant_filter(tmp_path: Path) -> None:
    home = tmp_path / "home"
    code = _ext_root(home / ".config" / "Code" / "User")
    cursor = _ext_root(home / ".config" / "Cursor" / "User")
    _make_task(code / "tasks", "1000", api_history=_list_content("code"))
    _make_task(cursor / "tasks", "3000", api_history=_list_content("cursor"))

    sessions = discover_sessions(platform="linux", env={}, home=home, variant="Cursor")

    assert [s.variant for s in sessions] == ["Cursor"]


def test_discover_sessions_raises_when_nothing_found(tmp_path: Path) -> None:
    with pytest.raises(ExtensionStorageNotFound) as excinfo:
        discover_sessions(platform="linux", env={}, home=tmp_path / "empty")
    # The error names at least one path it looked in, so the user can act.
    assert "globalStorage" in str(excinfo.value) or "Code" in str(excinfo.value)
