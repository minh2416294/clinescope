"""Cohen's-kappa agreement harness -- judge-validation, segment 1 (zero-LLM stats).

The credibility layer for the charter's criterion 3: once an LLM judge and a small
HUMAN gold set label the same items, this reports their chance-corrected agreement
as Cohen's kappa WITH a confidence interval -- the "prove the evaluator is correct"
number an eval reader looks for. This module is the pure statistics ONLY: it takes
two aligned label lists and returns kappa + a CI. The judge, the gold set, and the
end-to-end wiring are LATER segments; nothing here calls an LLM, reads a file, or
imports a scorer.

    kappa = (p_o - p_e) / (1 - p_e)

where ``p_o`` is observed agreement (fraction of items both raters labeled the same)
and ``p_e`` is expected/chance agreement (sum over each category ``k`` of
``P(rater_a = k) * P(rater_b = k)``, i.e. the product of the two marginals). Source:
Wikipedia "Cohen's kappa"; scikit-learn ``cohen_kappa_score`` (identical definition).

**Deliberate decisions (each a stated choice, not undefined behaviour):**

* Two raters, one nominal label per item (binary is the segment-1 case, but the
  kappa itself is category-agnostic: it works for any hashable label set). Weighted
  kappa / Krippendorff's alpha (for ORDINAL labels) are a LATER segment -- not built
  for a label scale that does not exist yet (two-implementation rule).
* Degenerate ``p_e == 1`` (both raters put every item in ONE category, so chance
  agreement is already total) makes ``kappa = 0/0`` mathematically UNDEFINED. We
  follow scikit-learn: return ``kappa = NaN`` with ``defined = False`` (and NaN CI
  bounds), NEVER a silent ``0.0`` or ``1.0`` and never a crash. "Perfect raw
  agreement but kappa undefined" is a real signal (degenerate marginals -- the
  base-rate paradox), so it is surfaced honestly, not laundered into a number. This
  IS the current clinescope corpus (every minimality score is 1.0 -> one class).
* The CI is a BOOTSTRAP PERCENTILE interval, NOT the asymptotic (Wald) ``kappa +/-
  1.96*SE``. For the small gold sets this targets (N ~ 20-50), the sampling
  distribution of kappa is skewed and the symmetric Wald interval is a poor fit that
  can even spill past +/-1 (Fleiss & Cicchetti 1978); the percentile bootstrap
  respects the ``[-1, 1]`` bounds and the asymmetry. Honest caveat: at small N the
  interval is WIDE (McHugh 2012: N < 30 gives an interval so wide "no agreement" can
  fall inside it) -- that width is a feature, it tells the reader not to over-trust
  a point estimate from few items.
* The bootstrap is SEEDED (``seed`` param, default fixed) and uses stdlib
  ``random.Random`` so the CI is fully DETERMINISTIC and reproducible: same inputs +
  same seed -> byte-identical bounds, which every clinescope test and the whole
  repo's determinism posture rely on. ``n_boot`` (resample count) is also a param.
* ZERO runtime dependency (the project invariant): kappa is a handful of counts and
  the bootstrap is stdlib ``random`` + a percentile pick -- no numpy/scipy/sklearn.

Primary sources: Wikipedia "Cohen's kappa" (formula, the 0.4 worked example, the
p_e=1 undefined case); McHugh ML (2012) Biochem Med 22(3):276-282, PMC3900052 (SE/CI
worked example, N>=30 guidance); scikit-learn ``cohen_kappa_score`` (NaN convention).

The functions are pure: no I/O, no LLM, deterministic under a fixed seed.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Hashable

# Percentile bounds for the 95% bootstrap CI (2.5th and 97.5th).
_CI_LOW_PCT = 2.5
_CI_HIGH_PCT = 97.5


@dataclass(frozen=True, slots=True)
class CohenKappaResult:
    """Result of :func:`cohen_kappa`.

    Invariants:

    * ``n`` is the number of paired items (``len(labels_a) == len(labels_b)``).
    * ``p_observed`` is the fraction of items both raters labeled identically;
      ``p_expected`` is the chance-agreement sum of marginal products. Both in
      ``[0.0, 1.0]``.
    * ``defined`` is ``False`` IFF ``p_expected == 1.0`` (the degenerate one-class
      case, ``kappa = 0/0``). When ``defined`` is ``False``, ``kappa``, ``ci_low``
      and ``ci_high`` are all ``NaN`` -- honestly undefined, never a silent number.
    * When ``defined`` is ``True``, ``kappa = (p_observed - p_expected) /
      (1 - p_expected)`` in ``[-1.0, 1.0]`` (``1.0`` = perfect, ``0.0`` = chance,
      ``< 0`` = worse than chance).
    * ``ci_low <= kappa <= ci_high`` is the 95% BOOTSTRAP PERCENTILE interval
      (``_CI_LOW_PCT`` / ``_CI_HIGH_PCT``), computed by resampling the ``n`` paired
      items with replacement ``n_boot`` times under ``seed``. Deterministic for a
      fixed ``(inputs, seed)``. Wider at smaller ``n`` (it reflects sample size).
      A bootstrap resample that is itself degenerate contributes a ``NaN`` kappa and
      is dropped from the percentile pool (only defined resamples form the interval).
    * ``n_boot`` echoes the requested resample count. ``n_boot_effective`` is how many
      resamples were actually NON-degenerate and thus formed the percentile pool --
      it is ``<= n_boot`` and drops sharply on a near-degenerate (skewed base-rate)
      input, where many resamples collapse to one class. A large gap between the two
      means the interval rests on a THIN, conditionally-biased pool (only resamples
      that happened to retain both classes) -- read it as a "trust the CI less" flag,
      surfaced rather than hidden. ``0`` (with ``defined`` still ``True``) means every
      resample was degenerate and the CI bounds are ``NaN`` despite a defined point
      estimate. Both are ``0`` when the point estimate itself is undefined.
    """

    kappa: float
    defined: bool
    p_observed: float
    p_expected: float
    ci_low: float
    ci_high: float
    n: int
    n_boot: int
    n_boot_effective: int


def cohen_kappa(
    labels_a: Sequence[Hashable],
    labels_b: Sequence[Hashable],
    *,
    n_boot: int = 2000,
    seed: int = 12345,
) -> CohenKappaResult:
    """Cohen's kappa + a seeded bootstrap 95% CI for two raters over paired labels.

    Args:
        labels_a: Rater A's label per item.
        labels_b: Rater B's label per item, aligned 1:1 with ``labels_a``.
        n_boot: Bootstrap resample count for the CI (default 2000).
        seed: Seed for the bootstrap RNG, so the CI is reproducible (default fixed).

    Raises:
        TypeError: If either argument is a ``str`` -- a bare string would be iterated
            character-by-character as if each char were an item's label and return a
            plausible-but-wrong kappa, so this one silent-wrong-answer case is guarded.
        ValueError: If the two label lists differ in length, or are empty (kappa is
            undefined with no items to agree on).
    """
    _agreement_guard_inputs(labels_a, labels_b)

    a = list(labels_a)
    b = list(labels_b)
    n = len(a)

    p_observed, p_expected, kappa = _agreement_kappa(a, b)
    if math.isnan(kappa):
        nan = math.nan
        return CohenKappaResult(
            kappa=nan,
            defined=False,
            p_observed=p_observed,
            p_expected=p_expected,
            ci_low=nan,
            ci_high=nan,
            n=n,
            n_boot=n_boot,
            n_boot_effective=0,
        )

    ci_low, ci_high, n_boot_effective = _agreement_bootstrap_ci(
        a, b, n_boot=n_boot, seed=seed
    )
    return CohenKappaResult(
        kappa=kappa,
        defined=True,
        p_observed=p_observed,
        p_expected=p_expected,
        ci_low=ci_low,
        ci_high=ci_high,
        n=n,
        n_boot=n_boot,
        n_boot_effective=n_boot_effective,
    )


def _agreement_guard_inputs(
    labels_a: Sequence[Hashable], labels_b: Sequence[Hashable]
) -> None:
    # str AND the bytes-like siblings are all "scalar sequences": iterating them
    # yields per-CHARACTER / per-BYTE items, not per-item labels, so a caller who
    # passes one gets a plausible-but-wrong kappa with no error (e.g. b"YY" vs
    # ["Y","Y"] scores perfect agreement as total DISagreement, because list(b"YY")
    # is [89, 89] ints that never equal the strings). Reject all of them loudly.
    if isinstance(labels_a, (str, bytes, bytearray, memoryview)) or isinstance(
        labels_b, (str, bytes, bytearray, memoryview)
    ):
        raise TypeError(
            "labels_a/labels_b must be sequences of per-item labels, not a "
            "str/bytes/bytearray/memoryview; those iterate character/byte-wise and "
            "score wrongly -- pass a list/tuple of one label per item"
        )
    if len(labels_a) != len(labels_b):
        raise ValueError(
            f"labels_a and labels_b must have equal length "
            f"({len(labels_a)} != {len(labels_b)})"
        )
    if len(labels_a) == 0:
        raise ValueError("cohen_kappa needs at least one paired item, got none")


def _agreement_kappa(
    a: list[Hashable], b: list[Hashable]
) -> tuple[float, float, float]:
    """Return ``(p_observed, p_expected, kappa)`` for aligned label lists.

    ``kappa`` is ``NaN`` when ``p_expected == 1`` (the degenerate one-class case;
    ``0/0``). Nominal / category-agnostic: works for any hashable label set.
    """
    n = len(a)
    agree = sum(1 for la, lb in zip(a, b) if la == lb)
    p_observed = agree / n

    count_a = Counter(a)
    count_b = Counter(b)
    # sorted(..., key=repr) fixes the summation order so the float p_expected is
    # bit-identical regardless of set-iteration order (the module's whole selling
    # point is determinism); key=repr keeps it total-orderable for any hashable label.
    categories = sorted(set(count_a) | set(count_b), key=repr)
    p_expected = sum((count_a[k] / n) * (count_b[k] / n) for k in categories)

    if p_expected >= 1.0:
        return p_observed, p_expected, math.nan
    kappa = (p_observed - p_expected) / (1.0 - p_expected)
    return p_observed, p_expected, kappa


def _agreement_bootstrap_ci(
    a: list[Hashable], b: list[Hashable], *, n_boot: int, seed: int
) -> tuple[float, float, int]:
    """Seeded percentile bootstrap 95% CI for kappa over the paired items.

    Resamples the ``n`` item INDICES with replacement ``n_boot`` times, recomputes
    kappa on each resample, drops resamples whose kappa is undefined (a degenerate
    resample -- all-one-class), and returns the 2.5/97.5 percentiles of the rest.

    Returns ``(ci_low, ci_high, n_boot_effective)`` where ``n_boot_effective`` is the
    number of NON-degenerate resamples that formed the percentile pool (``<= n_boot``);
    it is surfaced so a caller can see when the interval rests on a thin/biased pool.
    A ``0`` effective count (every resample degenerate) yields ``NaN`` bounds.
    """
    n = len(a)
    rng = random.Random(seed)
    kappas: list[float] = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        ra = [a[i] for i in idx]
        rb = [b[i] for i in idx]
        _, _, k = _agreement_kappa(ra, rb)
        if not math.isnan(k):
            kappas.append(k)

    if not kappas:
        return math.nan, math.nan, 0
    kappas.sort()
    return (
        _agreement_percentile(kappas, _CI_LOW_PCT),
        _agreement_percentile(kappas, _CI_HIGH_PCT),
        len(kappas),
    )


def _agreement_percentile(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolated percentile of an already-sorted list (``pct`` in 0..100).

    Matches the common ``numpy.percentile`` 'linear' method so the interval is a
    standard percentile bootstrap, implemented in stdlib to keep zero dependencies.
    """
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return sorted_values[lower]
    frac = rank - lower
    return sorted_values[lower] * (1.0 - frac) + sorted_values[upper] * frac
