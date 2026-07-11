"""LLM-judge for diff_minimality -- judge-validation, segment 4 (the live judge).

This is the FIRST live model call in an otherwise pure/deterministic/keyless
codebase. :func:`judge_diff_minimality` selects the FIRST apply_patch in a trace
(the same call the deterministic scorer and the gold loader grade), lifts its patch
text, and asks a local model the SAME holistic question a human gold labeler answered
-- *"is this patch WASTEFUL -- does it rewrite more than the change needs?"* -- then
returns a :class:`JudgeLabel`. The judge label and the human label are then fed to
:func:`clinescope.agreement.cohen_kappa` (in :mod:`clinescope.judge_run`) for the κ
number that is the charter's criterion 3.

**Deliberate decisions (each a stated choice, not undefined behaviour):**

* ``judge_diff_minimality`` takes a :class:`~clinescope.world_a.Trace`, NOT patch
  text -- exactly parallel to the four deterministic scorers. It re-selects the first
  apply_patch internally via ``diff_coherence_select_apply_patch`` and lifts the text
  via ``diff_coherence_read_patch_text`` -- the SAME functions the scorer and the gold
  loader use, so all three agree on which call is judged and read it identically.
* The model is reached over **stdlib ``urllib``** (Ollama's HTTP ``/api/generate``),
  NOT a client library -- the project's ``dependencies=[]`` invariant (and its
  keyless-core identity) is preserved; a single POST does not earn a third-party dep.
  The default free model is ``gpt-oss:20b`` served locally by Ollama; ``base_url`` and
  ``model_id`` are parameters so a paid model is a param change, not a code fork.
* **Temp 0** (plus ``top_p=1`` and a fixed ``seed``) to make the model AS deterministic
  as it can be -- but note this is NOT fully deterministic in practice: ``gpt-oss:20b``
  via Ollama still flips labels run-to-run (GPU/batch/KV-cache nondeterminism that temp 0
  + a fixed seed do not suppress; disproved by a Gate-4 probe on ``dm-hc-13``). So a
  cached verdict is a SINGLE-DRAW SNAPSHOT, and the κ built on it is reported as such,
  not as a reproducible constant. A low ``num_predict`` cap (gpt-oss:20b over-thinks and
  can run out of turn) and a hard ``timeout`` (a stuck call fails LOUD, not hangs) back it.
* The judge is **BLIND**: the prompt is built ONLY from the lifted patch text. It never
  sees the human label, the deterministic ``diff_minimality`` score, or the item's
  authored ``notes``. If any of those leaked in, the κ would be theater.
* The model's answer is parsed for a trailing ``VERDICT: WASTEFUL`` /
  ``VERDICT: NOT-WASTEFUL`` sentinel. An answer with no parseable verdict raises
  :class:`JudgeUnparseableError` -- it NEVER silently defaults to a class (a silent
  default biases κ). ``JudgeLabel.label`` is a strict ``Literal`` of the two verdicts,
  so "unparseable" lives in the exception channel, and the runner (which owns the κ
  input lists) decides to drop-and-surface it.
* ``JudgeLabel.model_id`` is load-bearing, not decorative: the free-vs-paid story
  (which model produced this verdict) rides with every label, per the charter's
  "scores are glued to the exact setup" caveat.
* NO ``Protocol`` / ABC and NO separate HTTP-client module. Exactly one judge and one
  endpoint exist; a seam earns an abstraction only when a SECOND implementation
  justifies it (two-implementation rule). The ``judge_*`` helpers are plain
  module-level functions in this one module, mirroring the scorers.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Literal

from clinescope.diff_coherence import (
    diff_coherence_read_patch_text,
    diff_coherence_select_apply_patch,
)
from clinescope.world_a import Trace

# The holistic binary a human gold labeler and the judge both answer. This is the
# same vocabulary the gold loader validates human labels against (clinescope.gold
# GOLD_LABELS); keep the two in sync -- judge and human answer ONE shared question.
JudgeVerdict = Literal["WASTEFUL", "NOT-WASTEFUL"]

# Ollama defaults. Overridable as function params so a paid model / remote endpoint is
# a call-site change, never a code fork (two-implementation rule -- no abstraction yet).
_JUDGE_DEFAULT_MODEL = "gpt-oss:20b"
_JUDGE_BASE_URL = "http://localhost:11434"

# gpt-oss:20b writes its reasoning inline before the VERDICT line. The tightest caps
# truncated the verdict off the reasoning-heavy blind-rewrite cases (dm-hc-13/17/19,
# 293-617 output tokens) -- and those were exactly the WASTEFUL detections, so a low cap
# systematically dropped WASTEFUL verdicts and biased κ toward 0. That truncation is a
# LOUD JudgeTruncatedError (never a silent NOT-WASTEFUL default), and the fix is a cap
# that fits the model's real answer length: 1024 clears the observed 617-token max with
# margin while still bounding a runaway generation (past 1024 fails loud). This is a
# correctness cap on the model's completion, NOT prompt/rubric tuning against the labels.
# A hard wall timeout backs it up.
_JUDGE_NUM_PREDICT = 1024
_JUDGE_TIMEOUT_S = 120.0
_JUDGE_PROBE_TIMEOUT_S = 2.0

# The one holistic question -- verbatim-aligned with the human labeler's prompt
# (clinescope.label_gold.LABEL_PROMPT) so judge and human answer the SAME thing. The
# trailing VERDICT sentinel is the machine anchor the parser reads (bottom-up).
_JUDGE_SYSTEM_PROMPT = (
    "You are a strict code-review judge. You are shown the TEXT of a single Cline "
    "apply_patch patch in the '*** Begin Patch' envelope format. Decide ONE thing: is "
    "the patch WASTEFUL?\n\n"
    "WASTEFUL means it rewrites more than the change needs -- for example it deletes "
    "and retypes whole blocks or lines it could have edited in place, or restates "
    "unchanged content. NOT-WASTEFUL means the edit is about as small as the change "
    "requires.\n\n"
    "Judge ONLY from the patch text shown; do not assume anything not visible in it. "
    "Give at most two sentences of reasoning, then a final line EXACTLY of the form:\n"
    "VERDICT: WASTEFUL\n"
    "or\n"
    "VERDICT: NOT-WASTEFUL\n"
    "Output nothing after that line."
)

# Anchored, case-insensitive; NOT-WASTEFUL is an alternative BEFORE WASTEFUL so the
# WASTEFUL substring inside NOT-WASTEFUL cannot shadow the negative verdict.
_JUDGE_VERDICT_RE = re.compile(
    r"^\s*VERDICT:\s*(NOT-WASTEFUL|WASTEFUL)\s*$", re.IGNORECASE
)

# Cap on how much raw model text an error message echoes (readability; no secrets here).
_JUDGE_SNIPPET_LEN = 200


class JudgeError(Exception):
    """Base for all judge errors (mirrors WorldATraceError / GoldError discipline)."""


class JudgeUnreachableError(JudgeError):
    """The Ollama endpoint could not be reached (connection refused / DNS / timeout)."""


class JudgeCallError(JudgeError):
    """The endpoint answered but the HTTP/JSON response was not a usable completion."""


class JudgeTruncatedError(JudgeError):
    """The model hit the ``num_predict`` cap (``done_reason == "length"``).

    A truncated answer must NOT be parsed for a verdict -- the sentinel may have been
    cut off, so a truncated completion is a loud error, never a guessed class.
    """


class JudgeUnparseableError(JudgeError):
    """The model answered but no ``VERDICT: WASTEFUL/NOT-WASTEFUL`` line was found.

    Raised instead of silently defaulting to a class -- a silent default would bias κ.
    The runner catches this and records the item as an explicit ``unparseable`` outcome
    excluded from the κ input lists.
    """


@dataclass(frozen=True, slots=True)
class JudgeLabel:
    """One judge verdict on a trace's first apply_patch.

    Invariants:

    * ``label`` is the holistic binary the human gold set also uses -- ``"WASTEFUL"``
      or ``"NOT-WASTEFUL"`` -- so a judge label and a human label are directly
      comparable inputs to :func:`clinescope.agreement.cohen_kappa`.
    * ``rationale`` is the judge's free-text justification (the raw model answer),
      kept for auditing a low-κ disagreement, never scored.
    * ``model_id`` identifies the exact model that produced the verdict (load-bearing
      for the free-vs-paid claim; see the module docstring).
    """

    label: JudgeVerdict
    rationale: str
    model_id: str


def judge_diff_minimality(
    trace: Trace,
    *,
    model_id: str = _JUDGE_DEFAULT_MODEL,
    base_url: str = _JUDGE_BASE_URL,
    timeout: float = _JUDGE_TIMEOUT_S,
) -> JudgeLabel:
    """Judge whether the first apply_patch in ``trace`` is wastefully written.

    Selects the FIRST apply_patch (the same call the scorer and gold loader grade),
    lifts its patch text, asks the model the holistic "is this WASTEFUL?" question from
    that text ALONE (blind to any label/score), and returns a :class:`JudgeLabel`.

    Args:
        trace: A loaded World-A trace; only its first apply_patch is read.
        model_id: The model to ask (default: the free local ``gpt-oss:20b``).
        base_url: The Ollama base URL (default: local).
        timeout: Hard wall for the HTTP call, in seconds.

    Raises:
        TypeError: If ``trace`` is not a :class:`~clinescope.world_a.Trace`.
        JudgeError: No apply_patch / bad patch shape (``JudgeCallError``), endpoint
            unreachable (``JudgeUnreachableError``), truncated completion
            (``JudgeTruncatedError``), or an unparseable answer
            (``JudgeUnparseableError``). Never returns a silently-defaulted label.
    """
    if not isinstance(trace, Trace):
        raise TypeError(
            f"judge_diff_minimality takes a Trace, not {type(trace).__name__}; "
            f"pass a loaded trace"
        )
    patch_text = _judge_lift_patch_text(trace)
    body = judge_build_request_body(patch_text, model_id=model_id)
    payload = judge_post_generate(body, base_url=base_url, timeout=timeout)
    answer = judge_extract_response_text(payload)
    verdict = judge_parse_verdict(answer)
    return JudgeLabel(label=verdict, rationale=answer.strip(), model_id=model_id)


def _judge_lift_patch_text(trace: Trace) -> str:
    """Return the first apply_patch's patch text, or fail loud (no call / bad shape)."""
    call, _count = diff_coherence_select_apply_patch(trace)
    if call is None:
        raise JudgeCallError("trace has no apply_patch call to judge")
    text = diff_coherence_read_patch_text(call)
    if text is None:
        raise JudgeCallError(
            'first apply_patch has no str patch text under key "input" (bad shape)'
        )
    return text


def judge_build_request_body(patch_text: str, *, model_id: str) -> dict[str, object]:
    """Build the Ollama ``/api/generate`` request body (pure; no I/O).

    Temp 0 + ``top_p=1`` + a fixed ``seed`` for determinism; ``num_predict`` caps the
    completion; ``stream=false`` returns one JSON object.
    """
    return {
        "model": model_id,
        "system": _JUDGE_SYSTEM_PROMPT,
        "prompt": judge_user_prompt(patch_text),
        "stream": False,
        "options": {
            "temperature": 0,
            "top_p": 1,
            "seed": 0,
            "num_predict": _JUDGE_NUM_PREDICT,
        },
    }


def judge_user_prompt(patch_text: str) -> str:
    """Frame the lifted patch text as the user turn -- patch text ALONE, nothing else."""
    return (
        "Here is the patch:\n\n"
        f"{patch_text}\n\n"
        "Is this patch WASTEFUL? Give at most two sentences, then the VERDICT line."
    )


def judge_post_generate(
    body: dict[str, object], *, base_url: str, timeout: float
) -> dict[str, object]:
    """POST the body to ``<base_url>/api/generate`` and return the parsed JSON object.

    Raises:
        JudgeUnreachableError: The endpoint could not be reached (URLError/OSError).
        JudgeCallError: An HTTP error status, or a non-object / unparseable JSON body.
    """
    url = f"{base_url}/api/generate"
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as err:
        raise JudgeCallError(
            f"Ollama /api/generate returned HTTP {err.code}: {err.reason}"
        ) from err
    except (urllib.error.URLError, OSError) as err:
        raise JudgeUnreachableError(
            f"could not reach Ollama at {url} ({err}); is `ollama serve` running?"
        ) from err
    return _judge_parse_payload(raw)


def _judge_parse_payload(raw: bytes) -> dict[str, object]:
    """Parse the response body into a JSON object, or fail loud."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as err:
        raise JudgeCallError(
            f"Ollama /api/generate did not return valid JSON ({err})"
        ) from err
    if not isinstance(payload, dict):
        raise JudgeCallError(
            f"Ollama /api/generate returned a {type(payload).__name__}, not an object"
        )
    return payload


def judge_extract_response_text(payload: dict[str, object]) -> str:
    """Pull the completion ``response`` string out of an Ollama generate payload.

    A ``done_reason == "length"`` means the ``num_predict`` cap truncated the answer,
    so the VERDICT sentinel may be missing -- that is a loud :class:`JudgeTruncatedError`,
    never a parse of a half-answer.

    Raises:
        JudgeTruncatedError: The completion was truncated by the token cap.
        JudgeCallError: The payload has no ``str`` ``response`` field.
    """
    if payload.get("done_reason") == "length":
        raise JudgeTruncatedError(
            f"model answer truncated at the {_JUDGE_NUM_PREDICT}-token num_predict cap; "
            f"raise the cap or shorten the prompt"
        )
    response = payload.get("response")
    if not isinstance(response, str):
        raise JudgeCallError(
            f"Ollama payload has no str 'response' field (got "
            f"{type(response).__name__})"
        )
    return response


def judge_parse_verdict(text: str) -> JudgeVerdict:
    """Extract WASTEFUL / NOT-WASTEFUL from a model answer; raise if none is present.

    Scans lines BOTTOM-UP (the directive puts the verdict last, and the model may
    restate the word mid-reasoning) for a ``VERDICT: <LABEL>`` sentinel. There is NO
    fallback to a default class -- an answer with no sentinel is a
    :class:`JudgeUnparseableError`, so a rambly answer can never silently bias κ.
    """
    for line in reversed(text.splitlines()):
        match = _JUDGE_VERDICT_RE.match(line)
        if match is not None:
            return _judge_canonical_verdict(match.group(1))
    snippet = text.strip()[:_JUDGE_SNIPPET_LEN]
    raise JudgeUnparseableError(
        f"no 'VERDICT: WASTEFUL/NOT-WASTEFUL' line in the model answer: {snippet!r}"
    )


def _judge_canonical_verdict(raw: str) -> JudgeVerdict:
    """Map a case-insensitive captured verdict to its canonical literal."""
    return "NOT-WASTEFUL" if raw.upper() == "NOT-WASTEFUL" else "WASTEFUL"


def judge_ollama_reachable(
    base_url: str = _JUDGE_BASE_URL, *, timeout: float = _JUDGE_PROBE_TIMEOUT_S
) -> bool:
    """Return True iff Ollama answers a ``GET /api/tags`` at ``base_url``.

    A cheap reachability probe for the live test's ``skipif`` gate: no model is invoked,
    only the tags listing. Any connection problem returns False (test skips), so CI
    without Ollama stays green.
    """
    url = f"{base_url}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return bool(200 <= response.status < 300)
    except (urllib.error.URLError, OSError):
        return False
