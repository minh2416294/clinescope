"""Thin CLI for the walking skeleton: load -> score -> EMIT.

Usage:
    python -m clinescope <trace.json> --expected read_files [write_file ...] [--verbose]
    python -m clinescope --vscode [--path DIR | --latest] [--expected ...]

Two input sources, one scoring path. Without ``--vscode`` it loads a Cline CLI
World-A trace (``{version:1, messages:[...]}``). With ``--vscode`` it reads a
Cline VS Code *extension* session instead: it auto-discovers the extension's
per-OS global storage, lists recent sessions with a picker (or takes ``--path`` /
``--latest``), and scores the chosen one through the same scorers. Both
paths render via :func:`clinescope.report.render_report` (a pure ``str``-returning
function) so the report is testable WITHOUT a subprocess; this module is only
argument parsing plus glue.

The trace ``sessionId`` is not modelled on
:class:`clinescope.world_a.Trace` (the loader discards it), so it is
lifted here with one cheap read and passed through to the emitter.

A trace that cannot be loaded (missing path, unsupported version, malformed or
non-object JSON) prints a single ``error: ...`` line to stderr and exits 1 --
never a raw Python traceback. A usage problem exits 2: an ``--expected-input``
naming a tool other than ``editor`` or lacking ``KEY=VALUE``, an empty
``--test-cmd``, or a ``--vscode`` problem (no session selected in a non-TTY, or no
extension storage found).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from clinescope import __version__
from clinescope._datafiles import DataFilesNotFound, datafiles_root
from clinescope.apply_recovery import ApplyRecoveryScore, score_apply_recovery
from clinescope.cline_extension import load_extension_trace
from clinescope.cmd_after_edit import CmdAfterEditCheck, cmd_after_edit_check
from clinescope.diff_coherence import DiffCoherenceScore, score_diff_coherence
from clinescope.diff_minimality import DiffMinimalityScore, score_diff_minimality
from clinescope.editor_recovery import EditorRecoveryScore, score_editor_recovery
from clinescope.extension_discovery import (
    ExtensionSession,
    ExtensionStorageNotFound,
    discover_sessions,
    enumerate_sessions,
)
from clinescope.render_safety import quote_untrusted_text
from clinescope.report import render_report
from clinescope.tool_input import (
    TOOL_INPUT_EDITOR_KEYS,
    ExpectedInput,
    ToolInputScore,
    score_tool_input,
    tool_input_parse,
)
from clinescope.tool_selection import score_tool_selection
from clinescope.tool_vocab import CLINE_KNOWN_TOOLS, tool_vocab_check
from clinescope.world_a import Trace, load_trace

# Exit codes: 0 = report emitted; 1 = a trace could not be loaded; 2 = a usage
# problem (a malformed --expected-input, an empty --test-cmd, no session selected
# in a non-TTY, or no extension storage found).
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

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        for name in sorted(CLINE_KNOWN_TOOLS):
            print(name)
        parser.exit(0)


def _read_session_id(path: Path) -> str | None:
    """Lift the World-A ``sessionId`` from the trace for the report header.

    The World-A spec types ``sessionId`` as a string. An absent or non-string value
    (a malformed trace) intentionally yields ``None`` so the header degrades to
    ``session <unknown>`` rather than rendering a wrong-typed id; the score is
    unaffected. Callers guard the surrounding load in a try/except, so a non-object
    JSON here surfaces at that boundary as a clean error, not a traceback.
    """
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
        "--expected-input",
        nargs=2,
        action="append",
        default=None,
        metavar=("TOOL", "KEY=VALUE"),
        help=(
            "An input you expect some call to carry, e.g. --expected-input editor "
            "path=src/app.py. Repeatable. editor only; a path matches on its ending. "
            "Omit to skip tool-input scoring."
        ),
    )
    parser.add_argument(
        "--test-cmd",
        default=None,
        metavar="TEXT",
        help=(
            "Text your test command contains, e.g. --test-cmd pytest. Reports whether "
            "a run_commands entry containing it ran after the last edit, and what "
            "Cline recorded for it. Not a score, and not proof the fix works."
        ),
    )
    parser.add_argument(
        "--list-tools",
        action=_ListToolsAction,
        nargs=0,
        help="Print the known Cline tool names (for --expected) and exit",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"clinescope {__version__}",
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


def _parse_expected_inputs(
    raw: list[list[str]] | None,
) -> frozenset[ExpectedInput] | None:
    # None when --expected-input was not given, so the report gets no tool_input
    # line. A tool the scorer cannot read raises ValueError (the caller exits 2);
    # an unknown key only warns, for the same reason an unknown --expected name does.
    if raw is None:
        return None
    parsed = frozenset(tool_input_parse(tool, pair) for tool, pair in raw)
    known = ", ".join(sorted(TOOL_INPUT_EDITOR_KEYS))
    for item in sorted(parsed):
        if item.key not in TOOL_INPUT_EDITOR_KEYS:
            print(
                f"warning: unknown {item.tool} input key '{item.key}' - "
                f"{item.tool} takes {known}",
                file=sys.stderr,
            )
    return parsed


# Links straight at the feedback form rather than the template picker: one
# fewer click between "I have something to say" and a text box.
_FEEDBACK_URL = (
    "https://github.com/minh2416294/clinescope/issues/new?template=feedback.yml"
)


def _maybe_print_feedback_footer() -> None:
    # A one-line, zero-egress nudge shown only to a human at a terminal. It fires
    # right after someone scored their OWN trace (the highest-intent moment to
    # ask). To stderr so it never pollutes a piped/redirected stdout report, and
    # only when stdout is a TTY so pipes, CI, and tool consumers never see it --
    # the same convention the typo warnings above already use (file=sys.stderr).
    #
    # It asks for DISAGREEMENT, not agreement. diff_minimality returns 1.0 on
    # every real captured trace shipped here (see LIMITATIONS.md), so "did it
    # match?" collects a yes whose mechanism is already known. A score the reader
    # thinks is wrong is the only answer that carries information.
    if not sys.stdout.isatty():
        return
    print(
        "\nRan this on your own Cline trace? One question: did any score above "
        "disagree with your own read of the run?"
        f"\nTell me which one: {_FEEDBACK_URL}",
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
    try:
        expected_inputs = _parse_expected_inputs(args.expected_input)
    except ValueError as err:
        print(f"error: {err}", file=sys.stderr)
        return _EXIT_USAGE
    if args.test_cmd is not None and not args.test_cmd.strip():
        # Every command contains the empty string, so an empty text would report
        # "ran" for any command at all.
        print("error: --test-cmd needs a non-empty command text", file=sys.stderr)
        return _EXIT_USAGE

    if args.vscode:
        return _run_extension_flow(
            args,
            expected,
            expected_provided,
            input_fn,
            expected_inputs=expected_inputs,
            test_cmd=args.test_cmd,
        )
    return _run_world_a_flow(
        args,
        expected,
        expected_provided,
        expected_inputs=expected_inputs,
        test_cmd=args.test_cmd,
    )


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
    args: argparse.Namespace,
    expected: list[str],
    expected_provided: bool,
    *,
    expected_inputs: frozenset[ExpectedInput] | None = None,
    test_cmd: str | None = None,
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
            trace,
            expected,
            expected_provided,
            args,
            session_id=session_id,
            expected_inputs=expected_inputs,
            test_cmd=test_cmd,
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
    *,
    expected_inputs: frozenset[ExpectedInput] | None = None,
    test_cmd: str | None = None,
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
        # The path embeds the task DIRECTORY NAME off disk, which on a POSIX host may
        # contain anything, and this line prints before any scorer line exists -- the
        # same overwrite position render_safety describes. Neutralized at the source
        # like the taskId is in _extension_label / _picker_line below.
        print(
            f"error: could not load extension session "
            f"{quote_untrusted_text(str(session.api_history_path))}: "
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
            expected_inputs=expected_inputs,
            test_cmd=test_cmd,
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
    # The title is read out of the extension's taskHistory.json, so it is untrusted and
    # is neutralized BEFORE truncation: truncating first could split an escape sequence
    # and leave a raw byte behind.
    when = _format_ts(session.timestamp_ms)
    title = quote_untrusted_text(session.title) if session.title else "(no title)"
    if len(title) > 48:
        title = title[:47] + "…"
    task_id = quote_untrusted_text(session.task_id)
    return f"{when}  {title:<48}  [{session.variant}] {task_id}"


def _format_ts(timestamp_ms: int | None) -> str:
    if timestamp_ms is None:
        return "(no date)        "
    from datetime import datetime

    return datetime.fromtimestamp(timestamp_ms / 1000).strftime("%Y-%m-%d %H:%M")


def _extension_label(session: ExtensionSession) -> str:
    # Honest header: the real folder taskId, the human title when known, and the
    # variant tag, clearly marked "extension session" so it is never mistaken for a
    # World-A sessionId (which an extension trace does not have).
    # Both the title and the taskId are untrusted: the title is taskHistory.json
    # content, and the taskId is a directory name off disk, which on a POSIX host may
    # contain anything. This string becomes the report header, the FIRST line printed
    # and so the strongest position for an escape sequence to overwrite what follows.
    # quote_untrusted_text supplies its own delimiters, so the hand-written quotes that
    # used to wrap the title are gone. `variant` is not neutralized: it is always drawn
    # from the pinned product-folder list or a literal, never from disk.
    title = f" {quote_untrusted_text(session.title)}" if session.title else ""
    task_id = quote_untrusted_text(session.task_id)
    return f"extension session {task_id}{title} [{session.variant}]"


# --- shared scoring + rendering -----------------------------------------------


def _score_and_render(
    trace: Trace,
    expected: list[str],
    expected_provided: bool,
    args: argparse.Namespace,
    *,
    session_id: str | None = None,
    session_label: str | None = None,
    expected_inputs: frozenset[ExpectedInput] | None = None,
    test_cmd: str | None = None,
) -> str:
    score = score_tool_selection(trace, set(expected))
    # Scored ONLY when --expected-input was given, so a run without the flag keeps
    # its exact report. Same omit-in-the-caller split as editor_recovery below.
    input_score: ToolInputScore | None = (
        score_tool_input(trace, expected_inputs)
        if expected_inputs is not None
        else None
    )
    diff_score: DiffCoherenceScore = score_diff_coherence(trace)
    minimality_score: DiffMinimalityScore = score_diff_minimality(trace)
    recovery_score: ApplyRecoveryScore = score_apply_recovery(trace)
    # Scored and rendered ONLY when the trace actually contains an editor call.
    # Almost every current Cline session uses editor rather than apply_patch, but a
    # trace that does not touch it gains no line, so every existing apply_patch
    # report stays byte-identical to before this scorer shipped.
    editor_score: EditorRecoveryScore | None = (
        score_editor_recovery(trace)
        if any(call.name == "editor" for call in trace.tool_calls)
        else None
    )
    # Checked ONLY when --test-cmd was given; the same omit-in-the-caller split.
    test_cmd_check: CmdAfterEditCheck | None = (
        cmd_after_edit_check(trace, test_cmd) if test_cmd is not None else None
    )
    return render_report(
        trace,
        score,
        session_id=session_id,
        session_label=session_label,
        diff_coherence=diff_score,
        diff_minimality=minimality_score,
        apply_recovery=recovery_score,
        editor_recovery=editor_score,
        tool_input=input_score,
        test_cmd=test_cmd_check,
        expected_provided=expected_provided,
        advice=args.advice,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    sys.exit(main())
