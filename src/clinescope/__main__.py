"""Thin CLI for the walking skeleton: load -> score -> EMIT.

Usage:
    python -m clinescope <trace.json> --expected read_files [write_file ...] [--verbose]
    python -m clinescope --vscode [--path DIR | --latest] [--expected ...]

Two input sources, one scoring path. Without ``--vscode`` it loads a Cline CLI
World-A trace (``{version:1, messages:[...]}``). With ``--vscode`` it reads a
Cline VS Code *extension* session instead: it auto-discovers the extension's
per-OS global storage, lists recent sessions with a picker (or takes ``--path`` /
``--latest``), and scores the chosen one through the same four scorers. Both
paths render via :func:`clinescope.report.render_report` (a pure ``str``-returning
function) so the report is testable WITHOUT a subprocess; this module is only
argument parsing plus glue.

The trace ``sessionId`` is not modelled on
:class:`clinescope.world_a.Trace` (the loader discards it), so it is
lifted here with one cheap read and passed through to the emitter.

A trace that cannot be loaded (missing path, unsupported version, malformed or
non-object JSON) prints a single ``error: ...`` line to stderr and exits 1 --
never a raw Python traceback. A ``--vscode`` usage problem (no session selected
in a non-TTY, or no extension storage found) exits 2.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

from clinescope._datafiles import DataFilesNotFound, datafiles_root
from clinescope.apply_recovery import ApplyRecoveryScore, score_apply_recovery
from clinescope.cline_extension import load_extension_trace
from clinescope.diff_coherence import DiffCoherenceScore, score_diff_coherence
from clinescope.diff_minimality import DiffMinimalityScore, score_diff_minimality
from clinescope.extension_discovery import (
    ExtensionSession,
    ExtensionStorageNotFound,
    discover_sessions,
    enumerate_sessions,
)
from clinescope.report import render_report
from clinescope.tool_selection import score_tool_selection
from clinescope.tool_vocab import CLINE_KNOWN_TOOLS, tool_vocab_check
from clinescope.world_a import Trace, load_trace

# Exit codes: 0 = report emitted; 1 = a trace could not be loaded; 2 = a --vscode
# usage problem (no session selected in a non-TTY, or no extension storage found).
_EXIT_OK = 0
_EXIT_LOAD_ERROR = 1
_EXIT_USAGE = 2

_PICKER_DEFAULT_LIMIT = 20


class _ListToolsAction(argparse.Action):
    """--list-tools: print the known Cline tool vocabulary and exit 0.

    A user should never have to GUESS what goes after --expected. This prints the
    same pinned vocabulary --expected is validated against, and short-circuits
    before ``trace`` is required (so ``clinescope --list-tools`` needs no trace).
    """

    def __call__(self, parser, namespace, values, option_string=None):  # type: ignore[no-untyped-def]
        for name in sorted(CLINE_KNOWN_TOOLS):
            print(name)
        parser.exit(0)


def _read_session_id(path: Path) -> str | None:
    raw = json.loads(path.read_text(encoding="utf-8"))
    session_id = raw.get("sessionId")
    return session_id if isinstance(session_id, str) else None


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="clinescope")
    parser.add_argument(
        "trace",
        type=Path,
        nargs="?",
        default=None,
        help="Path to a Cline World-A messages.json trace (omit with --vscode)",
    )
    parser.add_argument(
        "--expected",
        nargs="+",
        default=None,
        metavar="TOOL",
        help=(
            "Expected tool name(s), space-separated (e.g. --expected read_files "
            "apply_patch). Omit to skip tool-selection scoring; run --list-tools "
            "to see valid names."
        ),
    )
    parser.add_argument(
        "--list-tools",
        action=_ListToolsAction,
        nargs=0,
        help="Print the known Cline tool names (for --expected) and exit",
    )
    parser.add_argument(
        "--advice",
        action="store_true",
        help="Append per-failing-scorer coaching (what to change) to the summary",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Emit the full per-scorer debug dump instead of the one-line summary",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help=(
            "Score a bundled example trace with advice on and exit -- zero args, "
            "zero local files. The one-liner proof-of-work."
        ),
    )

    vscode = parser.add_argument_group("VS Code extension sessions")
    vscode.add_argument(
        "--vscode",
        "--extension",
        dest="vscode",
        action="store_true",
        help="Score a Cline VS Code extension session (auto-discover + pick)",
    )
    vscode.add_argument(
        "--path",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "With --vscode: an explicit task dir, its api_conversation_history.json, "
            "or a globalStorage root, instead of auto-discovery"
        ),
    )
    vscode.add_argument(
        "--latest",
        action="store_true",
        help="With --vscode: score the newest session without prompting",
    )
    vscode.add_argument(
        "--variant",
        default=None,
        metavar="NAME",
        help="With --vscode: limit discovery to one product (Code, Cursor, ...)",
    )
    vscode.add_argument(
        "--all",
        action="store_true",
        help="With --vscode: list every session in the picker, not just the newest few",
    )
    # Test hooks: inject the OS/home so discovery can run against a fake tree.
    vscode.add_argument("--home", type=Path, default=None, help=argparse.SUPPRESS)
    vscode.add_argument("--platform", default=None, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def _warn_unknown_expected(expected: list[str]) -> None:
    # A misspelled --expected name would silently score as a MISSING tool -- a
    # false negative that blames the agent for the user's typo. Warn (don't abort:
    # a genuinely custom tool is legal) with a nearest-match suggestion.
    for name, suggestion in tool_vocab_check(expected):
        hint = f" - did you mean '{suggestion}'?" if suggestion else ""
        print(f"warning: unknown tool '{name}'{hint}", file=sys.stderr)


_FEEDBACK_URL = "https://github.com/minh2416294/clinescope/issues/new/choose"


def _maybe_print_feedback_footer() -> None:
    # A one-line, zero-egress nudge shown only to a human at a terminal. It fires
    # right after someone scored their OWN trace (the highest-intent moment to
    # ask). To stderr so it never pollutes a piped/redirected stdout report, and
    # only when stdout is a TTY so pipes, CI, and tool consumers never see it --
    # the same convention the typo warnings above already use (file=sys.stderr).
    if not sys.stdout.isatty():
        return
    print(
        f"\nRan this on your own Cline trace? Tell me how it went: {_FEEDBACK_URL}",
        file=sys.stderr,
    )


def main(
    argv: list[str] | None = None, *, input_fn: Callable[[str], str] = input
) -> int:
    args = _parse_args(argv)
    if args.demo:
        return _emit_bundled_demo_report()
    expected_provided = args.expected is not None
    expected = args.expected if expected_provided else []
    if expected_provided:
        _warn_unknown_expected(expected)

    if args.vscode:
        return _run_extension_flow(args, expected, expected_provided, input_fn)
    return _run_world_a_flow(args, expected, expected_provided)


# --- `clinescope --demo`: the zero-args proof-of-work -------------------------
# One command a stranger runs (`uvx clinescope@latest --demo`) with no trace and
# no local file: it scores a REAL bundled trace with advice ON, so the top-of-
# README demo shows the tool CATCHING a failure (the PASS+FAIL mix on
# live-gpt-oss-apply-fail.json), not a canned all-green screenshot. The inputs are
# fixed (a curated, deterministic experience), so it reads NOTHING off the user's
# args -- any --expected / --advice / --vscode / positional trace is cleanly
# ignored (last mode wins). Resolves the trace via the same datafiles resolver the
# corpus/gold features use, so it works from a pip/uvx install with no clone.

_DEMO_TRACE_NAME = "live-gpt-oss-apply-fail.json"
_DEMO_EXPECTED = ["read_files", "apply_patch"]


def _emit_bundled_demo_report() -> int:
    try:
        trace_path = datafiles_root() / "examples" / _DEMO_TRACE_NAME
        trace = load_trace(trace_path)
        session_id = _read_session_id(trace_path)
    except DataFilesNotFound as err:
        print(f"error: {err}", file=sys.stderr)
        return _EXIT_USAGE
    except Exception as err:  # noqa: BLE001 -- same deliberate load boundary as the World-A flow
        print(
            f"error: could not load bundled demo trace: {type(err).__name__}: {err}",
            file=sys.stderr,
        )
        return _EXIT_LOAD_ERROR

    print(
        f"# clinescope --demo: scoring bundled trace 'examples/{_DEMO_TRACE_NAME}' "
        "(run `clinescope <your-trace.json> --expected ...` on your own)",
        file=sys.stderr,
    )
    print(
        _score_and_render(
            trace,
            _DEMO_EXPECTED,
            True,
            argparse.Namespace(advice=True, verbose=False),
            session_id=session_id,
        )
    )
    return _EXIT_OK


# --- World-A (Cline CLI) flow: unchanged output -------------------------------


def _run_world_a_flow(
    args: argparse.Namespace, expected: list[str], expected_provided: bool
) -> int:
    if args.trace is None:
        print("error: a trace path is required (or use --vscode)", file=sys.stderr)
        return _EXIT_USAGE
    # Load boundary: a bad path / bad version / malformed or non-object JSON must
    # print a clean one-line error, NOT a raw Python traceback. Catch broadly so
    # every load failure normalizes to the same clean stderr line + exit 1 -- the
    # deliberate load boundary (the sibling `clinescope.gate` CLI does the same).
    try:
        trace = load_trace(args.trace)
        session_id = _read_session_id(args.trace)
    except Exception as err:  # noqa: BLE001 -- deliberate load-failure boundary (see above)
        print(
            f"error: could not load trace {args.trace}: {type(err).__name__}: {err}",
            file=sys.stderr,
        )
        return _EXIT_LOAD_ERROR

    print(
        _score_and_render(
            trace, expected, expected_provided, args, session_id=session_id
        )
    )
    _maybe_print_feedback_footer()
    return _EXIT_OK


# --- VS Code extension flow ---------------------------------------------------


def _run_extension_flow(
    args: argparse.Namespace,
    expected: list[str],
    expected_provided: bool,
    input_fn: Callable[[str], str],
) -> int:
    try:
        session = _select_extension_session(args, input_fn)
    except ExtensionStorageNotFound as err:
        print(f"error: {err}", file=sys.stderr)
        return _EXIT_USAGE
    except _NoSelection as err:
        print(f"error: {err}", file=sys.stderr)
        return _EXIT_USAGE
    if session is None:
        return _EXIT_OK  # the user quit the picker -- a clean, deliberate exit

    try:
        trace = load_extension_trace(session.api_history_path)
    except Exception as err:  # noqa: BLE001 -- same deliberate load boundary as above
        print(
            f"error: could not load extension session {session.api_history_path}: "
            f"{type(err).__name__}: {err}",
            file=sys.stderr,
        )
        return _EXIT_LOAD_ERROR

    print(
        _score_and_render(
            trace,
            expected,
            expected_provided,
            args,
            session_label=_extension_label(session),
        )
    )
    _maybe_print_feedback_footer()
    return _EXIT_OK


class _NoSelection(Exception):
    """A --vscode run reached a state where no session could be chosen."""


def _select_extension_session(
    args: argparse.Namespace, input_fn: Callable[[str], str]
) -> ExtensionSession | None:
    if args.path is not None:
        return _session_from_explicit_path(args.path)

    sessions = discover_sessions(
        platform=args.platform,
        home=args.home,
        variant=args.variant,
    )
    if not sessions:
        raise _NoSelection(
            "No Cline extension sessions found. Run a Cline task first, or pass "
            "--path <task-dir-or-file>."
        )
    if args.latest:
        return sessions[0]
    if not sys.stdin.isatty():
        raise _NoSelection(
            "No TTY and no session selected. Pass --latest for the newest session, "
            "or --path <dir> to point at one explicitly."
        )
    return _prompt_for_session(sessions, show_all=args.all, input_fn=input_fn)


def _session_from_explicit_path(path: Path) -> ExtensionSession:
    """Resolve --path (a raw api file, a task dir, or a globalStorage root)."""
    if path.is_file():
        return _session_for_task_dir(path.parent, path)
    api_file = path / "api_conversation_history.json"
    if api_file.is_file():
        return _session_for_task_dir(path, api_file)
    # A globalStorage / extension root: enumerate and take the newest.
    sessions = enumerate_sessions(path)
    if sessions:
        return sessions[0]
    raise _NoSelection(
        f"No Cline extension session at {path}. Expected a task dir with an "
        "api_conversation_history.json, that file itself, or a globalStorage root."
    )


def _session_for_task_dir(task_dir: Path, api_file: Path) -> ExtensionSession:
    return ExtensionSession(
        task_id=task_dir.name,
        task_dir=task_dir,
        api_history_path=api_file,
        variant="path",
        title=None,
        timestamp_ms=None,
    )


def _prompt_for_session(
    sessions: list[ExtensionSession],
    *,
    show_all: bool,
    input_fn: Callable[[str], str],
) -> ExtensionSession | None:
    shown = sessions if show_all else sessions[:_PICKER_DEFAULT_LIMIT]
    print(f"Found {len(sessions)} Cline extension session(s):\n", file=sys.stderr)
    for i, session in enumerate(shown, start=1):
        print(f"  {i:>3}  {_picker_line(session)}", file=sys.stderr)
    if len(shown) < len(sessions):
        print(
            f"  ... {len(sessions) - len(shown)} older (use --all or --path)",
            file=sys.stderr,
        )
    print("  [Enter = 1 (newest), q = quit]", file=sys.stderr)

    while True:
        try:
            raw = input_fn("Select a session: ").strip()
        except EOFError:
            return None
        if raw in ("q", "quit"):
            return None
        if raw == "":
            return shown[0]
        if raw.isdigit() and 1 <= int(raw) <= len(shown):
            return shown[int(raw) - 1]
        print("Enter a number from the list, or q to quit.", file=sys.stderr)


def _picker_line(session: ExtensionSession) -> str:
    when = _format_ts(session.timestamp_ms)
    title = session.title or "(no title)"
    if len(title) > 48:
        title = title[:47] + "…"
    return f"{when}  {title:<48}  [{session.variant}] {session.task_id}"


def _format_ts(timestamp_ms: int | None) -> str:
    if timestamp_ms is None:
        return "(no date)        "
    from datetime import datetime

    return datetime.fromtimestamp(timestamp_ms / 1000).strftime("%Y-%m-%d %H:%M")


def _extension_label(session: ExtensionSession) -> str:
    # Honest header: the real folder taskId, the human title when known, and the
    # variant tag, clearly marked "extension session" so it is never mistaken for a
    # World-A sessionId (which an extension trace does not have).
    title = f' "{session.title}"' if session.title else ""
    return f"extension session {session.task_id}{title} [{session.variant}]"


# --- shared scoring + rendering -----------------------------------------------


def _score_and_render(
    trace: Trace,
    expected: list[str],
    expected_provided: bool,
    args: argparse.Namespace,
    *,
    session_id: str | None = None,
    session_label: str | None = None,
) -> str:
    score = score_tool_selection(trace, set(expected))
    diff_score: DiffCoherenceScore = score_diff_coherence(trace)
    minimality_score: DiffMinimalityScore = score_diff_minimality(trace)
    recovery_score: ApplyRecoveryScore = score_apply_recovery(trace)
    return render_report(
        trace,
        score,
        session_id=session_id,
        session_label=session_label,
        diff_coherence=diff_score,
        diff_minimality=minimality_score,
        apply_recovery=recovery_score,
        expected_provided=expected_provided,
        advice=args.advice,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    sys.exit(main())
