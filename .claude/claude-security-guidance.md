# Security guidance for clinescope

Additional context for the model-backed security reviews. Every rule below exists because
something real was missed or found here, not because it is generally good advice.

## Threat model

clinescope is a local command-line tool and a CI gate. The realistic adversary is a **hostile
trace file**, and that is not hypothetical: `.github/ISSUE_TEMPLATE/bug_report.yml:50-52` asks a
reporter to "Paste the smallest trace that triggers it". Scoring a stranger's trace is a
documented workflow. So every string lifted out of a trace is attacker-chosen: a `sessionId`, an
`apply_patch` target path, an `editor` path, a tool name, an extension task title.

The second adversary is the **supply chain into `.github/workflows/release.yml`**, the only path
here that reaches a third party. That workflow holds `id-token: write` and publishes to PyPI over
Trusted Publishing, and its build job hands `dist/` to the publish job, so a compromised action in
either job can poison a wheel before it is uploaded.

Damage from the first adversary is specific rather than generic: terminal escape sequences land
ahead of the scorer lines in the report and can overwrite them, displaying a score the tool never
computed. For a tool whose entire output is a score, that attacks the one property it exists to
provide.

## What this project does not have

Do not spend review effort looking for these. None exist, and a finding that assumes one is a
false positive:

- No server, no network listener, no request handling, no routes.
- No database, no ORM, no queries.
- No authentication, no sessions, no accounts, no roles, no multi-tenancy.
- No user data, no PII, no telemetry, no analytics.
- No runtime dependencies at all (`pyproject.toml`, `dependencies = []`), so no transitive
  supply chain in the shipped package.
- Exactly one outbound network call, to `http://localhost:11434`, in an opt-in advisory path.

## Checklist

**1. Trace-derived text is neutralised at the source, never at the join.** Anything lifted from a
trace passes through `render_safety.quote_untrusted_text` at the point it is read. Existing call
sites: `report.py:409,429,539,559,573`, `advice.py:115,141`, `__main__.py:449,452,475,476`. A new
sink that interpolates a path, id, tool name or title into output without it is a real finding.

Do **not** flag the reverse. Scorer-built violation strings already escape their own paths with
`!r` in `apply_recovery.py` and `editor_recovery.py`, so neutralising a joined line double-escapes
it. And operator-supplied values, such as `--expected` tool names, are deliberately left alone;
`render_safety.py` says why in its module docstring.

**2. Patch text reaching the judge stays inside its fence.** `judge_user_prompt` wraps patch text
between `<<<BEGIN PATCH <tag>>>` and `<<<END PATCH <tag>>>` where the tag is a sha256 prefix of the
patch itself (`judge.py:263-300`, `judge.py:310-315`), so a patch cannot close its own fence. Flag
any change that interpolates trace text into a prompt outside that fence.

Read `judge.py:282-286` before rating this: the fence is honoured by the model, not enforced by
code. It raises the cost of steering a verdict; it does not make it impossible. The judge is
advisory and is pinned out of the gate at the AST level by `tests/test_gate.py`, so the blast
radius is a published agreement figure, never a build verdict. Rate it accordingly.

**3. The gate's exit-code contract holds.** `clinescope-gate` returns 0 when every gated scorer met
its threshold, 1 when one genuinely regressed, and 2 when nothing was verified. An abstention must
never become a 1, and a usage error must never become a 0 or a 1. The decision that a trace with no
`apply_patch` is not applicable is made on `apply_patch_call_count`, not on the score
(`gate.py:203`), so a malformed patch that really is present still fails the build. A change that
lets a scorer's placeholder zero reach the gate as a regression verdict is a real finding.

**4. Every action reference is a full commit SHA.** In `.github/workflows/`, a `uses:` line pinned
to a tag or a branch is a finding, because both are mutable and an upstream repoint would run new
code inside the release path. The readable version belongs in a trailing comment, as in
`ci.yml:24-25`. This rule has already regressed once and was fixed; do not let a newly added
workflow reintroduce it.

**5. `dependencies = []` is a shipped guarantee.** Any addition to the runtime dependency list is a
finding regardless of how small the package is. Development dependencies under
`[project.optional-dependencies]` are not shipped and are out of scope.

## Treat contracts as security-relevant, not only flows

This is the most important instruction in this file, and it comes from a measured blind spot.

A prior multi-agent scan of this repository built components covering the workflows, the gate and
the judge, threat-modelled all three, and **returned nothing on any of them**. It found the taint
chain into the terminal, which is a flow, and missed the mutable action pins, the exit-code
contract and the unfenced judge prompt, which are contracts. All three were real and all three
were fixed.

So when reviewing here, do not require a finding to look like a classic exploit before reporting
it. A misleading CI exit code, a mutable dependency reference, and a broken invariant that a
docstring promises are all security-relevant in this repository, even though none of them is an
injection, an auth bypass, a memory error or a leaked secret.

The corollary keeps the noise down: a finding still needs a `file:line` you actually opened, and
an argument that closes end to end. Report the broken contract and name what it breaks. Do not
report a hypothetical that requires an attacker capability this project does not expose.
