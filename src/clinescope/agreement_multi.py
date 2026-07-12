"""Fleiss' kappa -- N-rater nominal agreement (judge-validation, multi-rater segment).

:mod:`clinescope.agreement` computes Cohen's kappa for exactly TWO raters. When a gold
item is judged by MORE than two raters -- for clinescope, several repeated draws of the
same LLM judge, which flips labels run-to-run even at temperature 0 -- Cohen's kappa no
longer applies. **Fleiss' kappa** is its N-rater generalisation for nominal categories:
it measures how much the raters' agreement on each subject exceeds what independent
raters with the same overall category rates would agree by chance.

    kappa = (P_bar - P_e_bar) / (1 - P_e_bar)

where, over ``n`` subjects each rated by the SAME number ``m`` of raters into ``k``
nominal categories, ``n_ij`` = how many raters put subject ``i`` in category ``j``:

* ``P_i`` (per-subject agreement) ``= (sum_j n_ij^2 - m) / (m * (m - 1))`` -- the
  proportion of rater PAIRS on subject ``i`` that agree.
* ``P_bar = mean_i P_i`` -- observed agreement.
* ``p_j = (sum_i n_ij) / (n * m)`` -- the overall proportion assigned to category ``j``.
* ``P_e_bar = sum_j p_j^2`` -- chance agreement.

Source: Fleiss (1971); the worked example on Wikipedia "Fleiss' kappa" (14 raters, 10
subjects, 5 categories) gives ``kappa = 0.210``, which ``fleiss_kappa`` reproduces (see
``tests/test_agreement_multi.py``) -- the same "validate against a published number"
discipline :mod:`clinescope.agreement` uses for Cohen's kappa.

**Deliberate decisions (each a stated choice, not undefined behaviour):**

* Additive, NOT a rewrite: :func:`clinescope.agreement.cohen_kappa` is untouched. Its
  module reserved multi-rater agreement as "a LATER segment"; this is that segment. For
  m == 2 Fleiss' and Cohen's kappa need not be numerically identical (Fleiss uses the
  pooled category rates as the single chance model, Cohen uses each rater's own
  marginals), so this does NOT supersede Cohen's -- it is the tool for m > 2.
* NOMINAL only, category-agnostic (any hashable label), unweighted. Ordinal weighting
  (weighted kappa / Krippendorff's alpha for a label SCALE) is not built -- clinescope's
  labels are a flat binary {WASTEFUL, NOT-WASTEFUL}, no scale exists to weight
  (two-implementation rule).
* Equal raters-per-subject (``m`` constant) is REQUIRED and checked -- the classic
  Fleiss estimator is only defined for a fixed rater count. A ragged design (different
  m per subject) is a LOUD ValueError, never silently averaged (which would compute a
  wrong number). For clinescope every gold item gets the same number of judge draws, so
  the design is always rectangular.
* Degenerate ``P_e_bar == 1`` (every rater used ONE category, so chance agreement is
  already total) makes ``kappa = 0/0`` UNDEFINED. Mirroring
  :func:`clinescope.agreement.cohen_kappa`: return ``kappa = NaN`` with
  ``defined = False``, never a silent ``0.0``/``1.0`` and never a crash.
* ZERO runtime dependency (the project invariant): a handful of counts, no
  numpy/scipy/sklearn.

The function is pure: no I/O, no LLM, deterministic.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Hashable


@dataclass(frozen=True, slots=True)
class FleissKappaResult:
    """Result of :func:`fleiss_kappa`.

    Invariants:

    * ``n_subjects`` is the number of rated subjects (gold items); ``n_raters`` is the
      constant number of raters per subject (judge draws); ``n_categories`` is the
      number of distinct labels seen across all ratings.
    * ``p_observed`` (``P_bar``) is the mean per-subject pairwise-agreement proportion;
      ``p_expected`` (``P_e_bar``) is the chance-agreement sum of squared category
      rates. Both in ``[0.0, 1.0]``.
    * ``defined`` is ``False`` IFF ``p_expected == 1.0`` (every rating in one category,
      ``kappa = 0/0``). When ``defined`` is ``False``, ``kappa`` is ``NaN`` -- honestly
      undefined, never a silent number.
    * When ``defined`` is ``True``, ``kappa = (p_observed - p_expected) /
      (1 - p_expected)`` in ``[-1.0, 1.0]`` (``1.0`` perfect, ``0.0`` chance, ``< 0``
      worse than chance).
    """

    kappa: float
    defined: bool
    p_observed: float
    p_expected: float
    n_subjects: int
    n_raters: int
    n_categories: int


def fleiss_kappa(ratings: Sequence[Sequence[Hashable]]) -> FleissKappaResult:
    """Fleiss' kappa for ``n`` subjects each rated by the same ``m`` raters (nominal).

    Args:
        ratings: One row per subject; each row is that subject's ``m`` rater labels
            (any hashable, order within a row irrelevant -- only the counts matter).
            Every row must have the SAME length ``m >= 2``.

    Returns:
        A :class:`FleissKappaResult` with the kappa, its components, and the design
        sizes. ``defined = False`` (kappa ``NaN``) for the degenerate one-category case.

    Raises:
        TypeError: ``ratings`` is a ``str``/``bytes`` (would iterate character-wise), or
            a row is a ``str``/``bytes``.
        ValueError: fewer than one subject, a row with fewer than two raters, or rows of
            unequal length (a ragged design is undefined for the classic estimator).
    """
    rows = _fleiss_validated_rows(ratings)
    n_subjects = len(rows)
    n_raters = len(rows[0])

    # Per-subject category counts n_ij.
    counts = [Counter(row) for row in rows]
    categories = sorted({cat for c in counts for cat in c}, key=repr)

    p_observed = _fleiss_p_observed(counts, n_raters)
    p_expected = _fleiss_p_expected(counts, categories, n_subjects, n_raters)

    if p_expected >= 1.0:
        return FleissKappaResult(
            kappa=math.nan,
            defined=False,
            p_observed=p_observed,
            p_expected=p_expected,
            n_subjects=n_subjects,
            n_raters=n_raters,
            n_categories=len(categories),
        )
    kappa = (p_observed - p_expected) / (1.0 - p_expected)
    return FleissKappaResult(
        kappa=kappa,
        defined=True,
        p_observed=p_observed,
        p_expected=p_expected,
        n_subjects=n_subjects,
        n_raters=n_raters,
        n_categories=len(categories),
    )


def _fleiss_validated_rows(
    ratings: Sequence[Sequence[Hashable]],
) -> list[Sequence[Hashable]]:
    """Validate the ragged/scalar/size preconditions and return the rows as a list."""
    if isinstance(ratings, (str, bytes, bytearray, memoryview)):
        raise TypeError(
            "ratings must be a sequence of per-subject rating rows, not a "
            "str/bytes; a bare string iterates character-wise and is meaningless here"
        )
    rows = list(ratings)
    if len(rows) == 0:
        raise ValueError("fleiss_kappa needs at least one subject, got none")
    first_len: int | None = None
    for index, row in enumerate(rows):
        if isinstance(row, (str, bytes, bytearray, memoryview)):
            raise TypeError(
                f"ratings[{index}] must be a sequence of per-rater labels, not a "
                f"str/bytes (which iterates character/byte-wise)"
            )
        row_len = len(row)
        if first_len is None:
            first_len = row_len
        elif row_len != first_len:
            raise ValueError(
                f"every subject must have the same number of raters; row 0 has "
                f"{first_len} but row {index} has {row_len} (a ragged Fleiss design "
                f"is undefined -- give every subject the same rater count)"
            )
    assert first_len is not None  # non-empty rows guaranteed above
    if first_len < 2:
        raise ValueError(
            f"Fleiss' kappa needs at least two raters per subject, got {first_len}"
        )
    return rows


def _fleiss_p_observed(counts: list[Counter[Hashable]], n_raters: int) -> float:
    """Mean per-subject pairwise-agreement proportion ``P_bar``.

    ``P_i = (sum_j n_ij^2 - m) / (m * (m - 1))`` is the fraction of the ``m*(m-1)`` rater
    pairs on subject ``i`` that agree; ``P_bar`` averages it over subjects.
    """
    denom = n_raters * (n_raters - 1)
    per_subject = [
        (sum(count * count for count in c.values()) - n_raters) / denom for c in counts
    ]
    return sum(per_subject) / len(per_subject)


def _fleiss_p_expected(
    counts: list[Counter[Hashable]],
    categories: list[Hashable],
    n_subjects: int,
    n_raters: int,
) -> float:
    """Chance agreement ``P_e_bar = sum_j p_j^2`` over pooled category rates ``p_j``.

    ``sorted(..., key=repr)`` fixes the summation order so the float is bit-identical
    regardless of set-iteration order (the module's determinism guarantee).
    """
    total_ratings = n_subjects * n_raters
    p_expected = 0.0
    for category in categories:
        assigned = sum(c.get(category, 0) for c in counts)
        rate = assigned / total_ratings
        p_expected += rate * rate
    return p_expected
