"""Thin CLI for the walking skeleton: load -> score -> EMIT.

Usage:
    python -m clinescope <trace.json> --expected read_files [write_file ...]

Loads a Cline World-A trace, scores tool selection against the expected tool
names, renders the report, and prints it. The heavy lifting lives in
:func:`clinescope.report.render_report` (a pure ``str``-returning
function) so the report is testable WITHOUT a subprocess; this module is only
argument parsing plus glue.

The trace ``sessionId`` is not modelled on
:class:`clinescope.world_a.Trace` (the loader discards it), so it is
lifted here with one cheap read and passed through to the emitter.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from clinescope.diff_coherence import score_diff_coherence
from clinescope.diff_minimality import score_diff_minimality
from clinescope.report import render_report
from clinescope.tool_selection import score_tool_selection
from clinescope.world_a import load_trace


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
        default=[],
        metavar="TOOL",
        help="Expected tool name(s), space-separated (e.g. --expected read_files write_file)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    trace = load_trace(args.trace)
    score = score_tool_selection(trace, set(args.expected))
    diff_score = score_diff_coherence(trace)
    minimality_score = score_diff_minimality(trace)
    session_id = _read_session_id(args.trace)
    print(
        render_report(
            trace,
            score,
            session_id=session_id,
            diff_coherence=diff_score,
            diff_minimality=minimality_score,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
