"""Fleiss' kappa tests -- validated against a PUBLISHED number, plus edge cases.

The load-bearing test reproduces the worked example on Wikipedia "Fleiss' kappa"
(14 raters, 10 subjects, 5 categories -> kappa = 0.210) so the estimator is proven
against an external source, not asserted. The rest pin the degenerate / guard / small
cases the same way ``tests/test_agreement.py`` pins Cohen's kappa.
"""

from __future__ import annotations

import math

import pytest

from clinescope.agreement_multi import FleissKappaResult, fleiss_kappa


def _wikipedia_fleiss_ratings() -> list[list[int]]:
    """The Wikipedia "Fleiss' kappa" worked example as per-subject rating rows.

    The article gives a 10x5 table of n_ij (subject x category counts, categories
    1..5, 14 raters each). Expand each row's counts into a flat list of 14 category
    labels so fleiss_kappa (which recounts) sees the same design.
    """
    # rows of [c1, c2, c3, c4, c5] counts, summing to 14 each (from the article table).
    count_table = [
        [0, 0, 0, 0, 14],
        [0, 2, 6, 4, 2],
        [0, 0, 3, 5, 6],
        [0, 3, 9, 2, 0],
        [2, 2, 8, 1, 1],
        [7, 7, 0, 0, 0],
        [3, 2, 6, 3, 0],
        [2, 5, 3, 2, 2],
        [6, 5, 2, 1, 0],
        [0, 2, 2, 3, 7],
    ]
    rows: list[list[int]] = []
    for counts in count_table:
        row: list[int] = []
        for category, count in enumerate(counts, start=1):
            row.extend([category] * count)
        assert len(row) == 14
        rows.append(row)
    return rows


def test_fleiss_kappa_matches_the_wikipedia_worked_example() -> None:
    result = fleiss_kappa(_wikipedia_fleiss_ratings())
    assert result.defined
    assert result.n_subjects == 10
    assert result.n_raters == 14
    assert result.n_categories == 5
    # The article reports kappa = 0.210 (and P_bar = 0.378, P_e_bar = 0.213).
    assert round(result.kappa, 3) == 0.210
    assert round(result.p_observed, 3) == 0.378
    assert round(result.p_expected, 3) == 0.213


def test_fleiss_kappa_perfect_agreement_is_one() -> None:
    # Every rater agrees on every subject, with more than one category used overall.
    ratings = [["A", "A", "A"], ["B", "B", "B"], ["A", "A", "A"]]
    result = fleiss_kappa(ratings)
    assert result.defined
    assert result.kappa == 1.0
    assert result.p_observed == 1.0


def test_fleiss_kappa_one_category_everywhere_is_undefined_not_a_number() -> None:
    # All raters, all subjects -> the same single category: P_e_bar == 1, kappa = 0/0.
    result = fleiss_kappa([["X", "X", "X"], ["X", "X", "X"]])
    assert not result.defined
    assert math.isnan(result.kappa)
    assert result.p_expected == 1.0
    assert result.n_categories == 1


def test_fleiss_kappa_worse_than_chance_is_negative() -> None:
    # Two subjects, three raters, maximal within-subject disagreement across two
    # categories balanced overall -> observed agreement below chance.
    result = fleiss_kappa([["A", "A", "B"], ["B", "B", "A"]])
    assert result.defined
    assert result.kappa < 0.0


def test_fleiss_kappa_two_raters_is_allowed() -> None:
    # m == 2 is the minimum legal design (it does NOT have to equal Cohen's kappa).
    result = fleiss_kappa([["A", "B"], ["A", "A"], ["B", "B"]])
    assert isinstance(result, FleissKappaResult)
    assert result.n_raters == 2


def test_fleiss_kappa_rejects_a_ragged_design() -> None:
    with pytest.raises(ValueError, match="same number of raters"):
        fleiss_kappa([["A", "A", "B"], ["A", "B"]])


def test_fleiss_kappa_rejects_one_rater() -> None:
    with pytest.raises(ValueError, match="at least two raters"):
        fleiss_kappa([["A"], ["B"]])


def test_fleiss_kappa_rejects_no_subjects() -> None:
    with pytest.raises(ValueError, match="at least one subject"):
        fleiss_kappa([])


def test_fleiss_kappa_rejects_a_bare_string_as_ratings() -> None:
    with pytest.raises(TypeError, match="not a "):
        fleiss_kappa("AB")  # type: ignore[arg-type]


def test_fleiss_kappa_rejects_a_string_row() -> None:
    with pytest.raises(TypeError, match="not a "):
        fleiss_kappa(["AB", "AB"])  # type: ignore[list-item]


def test_fleiss_kappa_is_category_agnostic_and_order_insensitive() -> None:
    # Labels are any hashable; only the per-subject counts matter, not their order.
    a = fleiss_kappa([["WASTEFUL", "NOT-WASTEFUL", "WASTEFUL"]])
    b = fleiss_kappa([["WASTEFUL", "WASTEFUL", "NOT-WASTEFUL"]])
    assert a.p_observed == b.p_observed
