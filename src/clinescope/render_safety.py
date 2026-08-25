"""Neutralize trace-derived text before it is rendered to a terminal.

A trace is UNTRUSTED INPUT. ``.github/ISSUE_TEMPLATE/bug_report.yml`` asks a reporter
to paste a ``messages.json`` snippet, so scoring somebody else's trace is a documented
workflow here rather than a hypothetical. Every string clinescope lifts out of a trace
-- a ``sessionId``, an ``apply_patch`` target path, an ``editor`` path, a tool name, an
extension task title -- is therefore chosen by whoever wrote the trace.

**The damage this prevents is specific, not generic terminal mischief.** Terminal
escape sequences land AHEAD of the scorer lines in the report, so erase-line and
cursor-movement can overwrite them and display a score the tool never computed. For a
tool whose entire output is a score, that is an attack on the one property it exists to
provide. Exit codes and the ``clinescope-gate`` decision are unaffected, so the damage
is confined to what a human reads -- which is exactly the part that matters here.

**Deliberate decisions (each a stated choice):**

* **``repr``, not a hand-written escape table.** Python escapes exactly the
  non-printable set, so ESC, CR, LF, TAB, DEL and separators like ``U+2028`` all
  escape, while ordinary text and printable non-ASCII (``café.py``) survive intact. A
  hand-built control-character map would be reasoning scaffolding for a job the stdlib
  already does correctly, and it would drift from Python's definition of printable.
* **The surrounding quotes are a feature, not a side effect.** They delimit where
  untrusted text starts and ends, so a path cannot blend into the label beside it.
* **This module imports nothing from clinescope.** It is a leaf so that both
  :mod:`clinescope.report` and :mod:`clinescope.advice` can use it: ``report`` already
  imports ``advice``, so the helper could not live in ``report`` without a cycle.
* **Applied at the SOURCE of untrusted data, never at the join.** ``violations``
  strings built by the scorers already interpolate with ``!r``
  (``apply_recovery.py``, ``editor_recovery.py``), so neutralizing a joined line would
  double-escape them. The raw values are the paths, ids, names and titles themselves.

Operator-supplied values are deliberately NOT routed through here. ``--expected`` tool
names come from the caller's own command line, and quoting them would change the most
read line of the summary for no reduction in risk.
"""

from __future__ import annotations


def quote_untrusted_text(value: str) -> str:
    """Return ``value`` quoted, with every non-printable character escaped.

    The one neutralizing helper for trace-derived text. A sink added later inherits the
    guarantee by calling this rather than by re-deriving the reasoning above.

    Args:
        value: A string lifted out of a trace or an extension session on disk.

    Returns:
        A single-line, quote-delimited rendering containing no raw control character.
    """
    return repr(value)
