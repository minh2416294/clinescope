"""Tests for the `clinescope --vscode` CLI flow (extension session scoring).

The `clinescope <trace>` path is unchanged (World-A only). `--vscode` adds
per-OS discovery + a session picker (or `--path` / `--latest`), scores the chosen
extension session through the existing load_extension_trace + the four scorers,
and prints a report with an honest "extension session" header. These tests build
fake extension storage trees under tmp_path and inject env / home / input, so
nothing touches a real machine.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinescope.__main__ import main


def _list_content(text: str) -> list[dict]:
    return [{"role": "user", "content": [{"type": "text", "text": text}]}]


def _apply_patch_history() -> list[dict]:
    # A minimal bare-array extension trace with a read + a valid apply_patch, so
    # the four scorers all produce numbers end to end.
    patch = "*** Begin Patch\n*** Add File: a.txt\n+hello\n*** End Patch"
    return [
        {
            "role": "user",
            "content": [{"type": "text", "text": "<task>\nFix it\n</task>"}],
        },
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "t1", "name": "read_files", "input": {}},
                {
                    "type": "tool_use",
                    "id": "t2",
                    "name": "apply_patch",
                    "input": {"input": patch},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
                {
                    "type": "tool_result",
                    "tool_use_id": "t2",
                    "content": "ok",
                    "is_error": False,
                },
            ],
        },
    ]


def _make_ext_tree(
    tmp_path: Path,
    task_id: str,
    *,
    title: str = "Fix it",
    history: list[dict] | None = None,
) -> tuple[Path, dict]:
    """Build a Linux-style extension tree; return (home, env) for --vscode."""
    home = tmp_path / "home"
    ext = (
        home / ".config" / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev"
    )
    task_dir = ext / "tasks" / task_id
    task_dir.mkdir(parents=True)
    (task_dir / "api_conversation_history.json").write_text(
        json.dumps(history if history is not None else _apply_patch_history()),
        encoding="utf-8",
    )
    state = ext / "state"
    state.mkdir()
    (state / "taskHistory.json").write_text(
        json.dumps([{"id": task_id, "ts": int(task_id), "task": title}]),
        encoding="utf-8",
    )
    return home, {}


# --- the CLI-unchanged guard --------------------------------------------------


def test_plain_cli_path_is_unchanged(capsys: pytest.CaptureFixture[str]) -> None:
    # A World-A trace with no --vscode still scores exactly as before.
    example = (
        Path(__file__).resolve().parent.parent / "examples" / "apply-patch-trace.json"
    )
    exit_code = main([str(example), "--expected", "apply_patch"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "clinescope report - session" in out
    assert "extension session" not in out


# --- --vscode --path (explicit) -----------------------------------------------


def test_vscode_path_to_task_dir_scores(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home, _ = _make_ext_tree(tmp_path, "1000")
    task_dir = (
        home
        / ".config"
        / "Code"
        / "User"
        / "globalStorage"
        / "saoudrizwan.claude-dev"
        / "tasks"
        / "1000"
    )
    exit_code = main(["--vscode", "--path", str(task_dir), "--expected", "apply_patch"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "extension session" in out
    assert "1000" in out
    assert "diff_coherence" in out


def test_vscode_path_to_raw_api_history_file_scores(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home, _ = _make_ext_tree(tmp_path, "2000")
    api_file = (
        home
        / ".config"
        / "Code"
        / "User"
        / "globalStorage"
        / "saoudrizwan.claude-dev"
        / "tasks"
        / "2000"
        / "api_conversation_history.json"
    )
    exit_code = main(["--vscode", "--path", str(api_file)])
    assert exit_code == 0
    assert "extension session" in capsys.readouterr().out


def test_vscode_bad_path_exits_2_with_clean_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A --path pointing at nothing is a USAGE problem (the user gave a bad path),
    # so it exits 2 like the other --vscode usage errors -- with a clean one-line
    # error, never a raw traceback.
    exit_code = main(["--vscode", "--path", str(tmp_path / "nope")])
    err = capsys.readouterr().err
    assert exit_code == 2
    assert "error:" in err
    assert "Traceback" not in err


# --- --vscode --latest + discovery --------------------------------------------


def test_vscode_latest_picks_newest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    home, env = _make_ext_tree(tmp_path, "1000", title="Older")
    # Add a newer task in the same tree.
    ext = (
        home / ".config" / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev"
    )
    newer = ext / "tasks" / "9000"
    newer.mkdir()
    (newer / "api_conversation_history.json").write_text(
        json.dumps(_apply_patch_history()), encoding="utf-8"
    )
    (ext / "state" / "taskHistory.json").write_text(
        json.dumps(
            [
                {"id": "1000", "ts": 1000, "task": "Older"},
                {"id": "9000", "ts": 9000, "task": "Newer"},
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("HOME", str(home))

    exit_code = main(["--vscode", "--latest", "--home", str(home)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "9000" in out
    assert "Newer" in out


def test_vscode_non_tty_without_selection_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_ext_tree(tmp_path, "1000")
    home = tmp_path / "home"
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    exit_code = main(["--vscode", "--home", str(home), "--platform", "linux"])
    err = capsys.readouterr().err
    assert exit_code == 2
    assert "--latest" in err or "--path" in err


def test_vscode_nothing_found_exits_2_naming_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "--vscode",
            "--latest",
            "--home",
            str(tmp_path / "empty"),
            "--platform",
            "linux",
        ]
    )
    err = capsys.readouterr().err
    assert exit_code == 2
    assert "globalStorage" in err or "--path" in err


# --- interactive picker (injected input) --------------------------------------


def test_vscode_interactive_picker_selects_by_number(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _ = _make_ext_tree(tmp_path, "1000", title="Older")
    ext = (
        home / ".config" / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev"
    )
    newer = ext / "tasks" / "9000"
    newer.mkdir()
    (newer / "api_conversation_history.json").write_text(
        json.dumps(_apply_patch_history()), encoding="utf-8"
    )
    (ext / "state" / "taskHistory.json").write_text(
        json.dumps(
            [
                {"id": "1000", "ts": 1000, "task": "Older"},
                {"id": "9000", "ts": 9000, "task": "Newer"},
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    # Row 1 is newest (9000/Newer), row 2 is 1000/Older. Pick 2.
    exit_code = main(
        ["--vscode", "--home", str(home), "--platform", "linux"],
        input_fn=lambda _prompt: "2",
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "1000" in out  # the older one, chosen by index 2


def test_vscode_interactive_picker_enter_selects_newest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _ = _make_ext_tree(tmp_path, "5555", title="One")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    exit_code = main(
        ["--vscode", "--home", str(home), "--platform", "linux"],
        input_fn=lambda _prompt: "",  # bare Enter -> newest
    )
    assert exit_code == 0
    assert "5555" in capsys.readouterr().out


def test_vscode_interactive_picker_quit_exits_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_ext_tree(tmp_path, "1", title="One")
    home = tmp_path / "home"
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    exit_code = main(
        ["--vscode", "--home", str(home), "--platform", "linux"],
        input_fn=lambda _prompt: "q",
    )
    assert exit_code == 0  # a clean, user-initiated quit is not an error
