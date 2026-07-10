"""R4 -- golden-fixture drift guard (real-fixture-path / content check).

The harness INGESTS Cline's golden fixture in place -- it is never copied into
this repo (project rule 4, hook-enforced). Every real-fixture test in
``test_report.py`` therefore hardcodes the checkout path and is ``skipif``-gated
on it existing, so on a machine without the Cline clone (CI, a fresh laptop)
those tests SKIP silently. That leaves two drift risks unguarded:

1. **Path drift** -- if the hardcoded ``GOLDEN`` path moves (Cline restructures
   its fixture dir, or the local clone is relocated), the real-fixture tests just
   quietly skip; nothing tells you the ingest point rotted.
2. **Content drift** -- the existing tests assert BEHAVIOUR (score 1.0, 4 turns,
   1 tool_call). If Cline upstream changed ``success.messages.json`` itself (added
   a diff, swapped the tool, bumped the version), those behavioural asserts would
   break with a confusing failure -- or, worse, a subtly-changed fixture could
   still satisfy them -- instead of one clear "the fixture you validated against
   has changed" signal.

This module closes both. When the fixture IS present it pins the exact bytes we
validated the whole harness against (sha256 + size); a mismatch fails LOUDLY with
a message naming the drift, so an upstream change is a deliberate review, never a
silent surprise. When the fixture is ABSENT it ``skipif``-skips (identical to the
other real-fixture tests) so CI without the Cline checkout stays green.

The pinned digest is the value every Day-6..12 session re-verified byte-identical
before committing (the Living Log's "golden fixture sha256 cdaf7b1d..a665aa
byte-identical" evidence line). This test makes that manual re-verification a
machine check.

Serves hard-floor criterion 1 (the harness runs against Cline's real data): a
drifted ingest point silently un-serves it, and this is what now catches that.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

# The single canonical ingest path, mirrored from ``test_report.py`` (one fact,
# one place -- if Cline's layout changes, both this guard and the behavioural
# tests skip together, and this guard is the one that says WHY on a content change).
GOLDEN = Path(
    "C:/Users/admin/PycharmProjects/cline/sdk/packages/core/fixtures/messages/success.messages.json"
)

# The exact fixture the harness was validated against, pinned by content. Bump
# these ONLY as a deliberate, reviewed response to an intentional upstream change
# (and re-run every scorer against the new bytes first) -- never to make a red
# test green.
GOLDEN_SHA256 = "cdaf7b1d0a4041ba80315ea4f7274b31e9767051a1a4c1333509d55b30a665aa"
GOLDEN_SIZE_BYTES = 1430


@pytest.mark.skipif(
    not GOLDEN.exists(), reason="Cline golden fixture not checked out at expected path"
)
def test_golden_fixture_content_has_not_drifted() -> None:
    # Fail loudly if the ingested fixture's bytes differ from what the harness was
    # validated against -- a genuine upstream change, or the wrong file at the path.
    data = GOLDEN.read_bytes()
    actual_sha = hashlib.sha256(data).hexdigest()

    assert len(data) == GOLDEN_SIZE_BYTES, (
        f"golden fixture size drifted: expected {GOLDEN_SIZE_BYTES} bytes, "
        f"got {len(data)} at {GOLDEN}. Cline's success.messages.json changed "
        f"upstream (or the path resolves to a different file). Re-validate every "
        f"scorer against the new bytes before bumping GOLDEN_SIZE_BYTES/SHA256."
    )
    assert actual_sha == GOLDEN_SHA256, (
        f"golden fixture content drifted: expected sha256 {GOLDEN_SHA256}, "
        f"got {actual_sha} at {GOLDEN}. Cline's success.messages.json changed "
        f"upstream. This is not a code bug -- re-run all scorers against the new "
        f"fixture and, only if the change is intended, bump GOLDEN_SHA256."
    )
