"""Thin CLI for the walking skeleton: load -> score -> EMIT.

Usage:
    python -m clinescope <trace.json> --expected read_files [write_file ...] [--verbose]

Loads a Cline World-A trace, scores tool selection against the expected tool
names, renders the report, and prints it. The default is a one-line-per-scorer
summary; ``--verbose`` emits the full per-scorer debug dump instead. The heavy
lifting lives in
:func:`clinescope.report.render_report` (a pure ``str``-returning
function) so the report is testable WITHOUT a subprocess; this module is only
argument parsing plus glue.

The trace ``sessionId`` is not modelled on
:class:`clinescope.world_a.Trace` (the loader discards it), so it is
lifted here with one cheap read and passed through to the emitter.

A trace that cannot be loaded (missing path, unsupported version, malformed or
non-object JSON) prints a single ``error: ...`` line to stderr and exits 1 --
never a raw Python traceback.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from clinescope.apply_recovery import score_apply_recovery
from clinescope.diff_coherence import score_diff_coherence
from clinescope.diff_minimality import score_diff_minimality
from clinescope.report import render_report
from clinescope.tool_selection import score_tool_selection
from clinescope.tool_vocab import CLINE_WORLD_A_TOOLS, tool_vocab_check
from clinescope.world_a import load_trace


class _ListToolsAction(argparse.Action):
    """--list-tools: print the known Cline tool vocabulary and exit 0.

    A user should never have to GUESS what goes after --expected. This prints the
    same pinned vocabulary --expected is validated against, and short-circuits
    before ``trace`` is required (so ``clinescope --list-tools`` needs no trace).
    """

    def __call__(self, parser, namespace, values, option_string=None):  # type: ignore[no-untyped-def]
        for name in sorted(CLINE_WORLD_A_TOOLS):
            print(name)
        parser.exit(0)


def _read_session_id(path: Path) -> str | None:
    raw = json.loads(path.read_text(encoding="utf-8"))
    session_id = raw.get("sessionId")
    return session_id if isinstance(session_id, str) else None


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="clinescope")
    parser.add_argument(
        "trace", type=Path, help="Path to a Cline World-A messages.json trace"
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
        "--verbose",
        action="store_true",
        help="Emit the full per-scorer debug dump instead of the one-line summary",
    )
    return parser.parse_args(argv)


def _warn_unknown_expected(expected: list[str]) -> None:
    # A misspelled --expected name would silently score as a MISSING tool -- a
    # false negative that blames the agent for the user's typo. Warn (don't abort:
    # a genuinely custom tool is legal) with a nearest-match suggestion.
    for name, suggestion in tool_vocab_check(expected):
        hint = f" - did you mean '{suggestion}'?" if suggestion else ""
        print(f"warning: unknown tool '{name}'{hint}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    # Opt-in tool_selection: distinguish "--expected was omitted" (None -> skip
    # scoring it, show n/a) from "--expected with no names" so an omitted flag no
    # longer prints a vacuous 100/100 PASS. Validate the given names for typos.
    expected_provided = args.expected is not None
    expected = args.expected if expected_provided else []
    if expected_provided:
        _warn_unknown_expected(expected)

    # Load boundary: a bad path / bad version / malformed or non-object JSON must
    # print a clean one-line error, NOT a raw Python traceback. The loader raises
    # a whole family of failures beyond its own WorldATraceError: OSError from a
    # missing/unreadable file, json.JSONDecodeError from bad JSON, and even an
    # AttributeError/TypeError when JSON-parseable-but-structurally-invalid input
    # trips the parser. Catch broadly here so every load failure normalizes to the
    # same clean stderr line + exit 1 -- this is the deliberate load boundary (the
    # sibling `clinescope.gate` CLI does the same), not swallowed application logic.
    try:
        trace = load_trace(args.trace)
        session_id = _read_session_id(args.trace)
    except Exception as err:  # noqa: BLE001 -- deliberate load-failure boundary (see above)
        print(
            f"error: could not load trace {args.trace}: {type(err).__name__}: {err}",
            file=sys.stderr,
        )
        return 1

    score = score_tool_selection(trace, set(expected))
    diff_score = score_diff_coherence(trace)
    minimality_score = score_diff_minimality(trace)
    recovery_score = score_apply_recovery(trace)
    print(
        render_report(
            trace,
            score,
            session_id=session_id,
            diff_coherence=diff_score,
            diff_minimality=minimality_score,
            apply_recovery=recovery_score,
            expected_provided=expected_provided,
            verbose=args.verbose,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
