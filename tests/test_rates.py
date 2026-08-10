"""Tests for OSRS-style drop-rate parsing/formatting."""

from __future__ import annotations

import math

import pytest

from fray_claude.model.rates import (
    build_rare_drop_num,
    build_secondary_primary_num,
    find_fraction,
    looks_non_numeric,
    parse_quantity,
    parse_ratio,
    secondary_primary_denominator,
)


def test_parse_ratio_reads_a_plain_fraction() -> None:
    assert parse_ratio("1/128") == 1 / 128


def test_parse_ratio_strips_the_tilde() -> None:
    assert parse_ratio("~1/50") == 1 / 50


def test_parse_ratio_returns_nan_for_a_non_fraction_token() -> None:
    assert math.isnan(parse_ratio("Always"))


def test_looks_non_numeric_is_false_for_an_ordinary_fraction() -> None:
    # '1/128' stripped of '/' and '@' is '1128' - still numeric.
    assert looks_non_numeric("1/128") is False


def test_looks_non_numeric_is_true_for_always() -> None:
    assert looks_non_numeric("Always") is True


def test_looks_non_numeric_treats_a_tilde_as_non_numeric() -> None:
    # Unlike parse_ratio, this check does not strip '~'.
    assert looks_non_numeric("~1/50") is True


def test_build_rare_drop_num_substitutes_a_near_zero_threshold_for_zero() -> None:
    """Read literally `"1/0"` is `Infinity`, but that reading was tried and
    contradicts the map's own oracle - see `build_rare_drop_num`'s docstring.
    An amount of 0 lets every rate through."""
    assert build_rare_drop_num("0") == parse_ratio("1/999999999999999")


def test_build_rare_drop_num_builds_a_plain_fraction() -> None:
    assert build_rare_drop_num("50") == 1 / 50


def test_build_secondary_primary_num() -> None:
    assert build_secondary_primary_num("16") == 1 / 16


def test_secondary_primary_denominator_reads_the_amount() -> None:
    assert secondary_primary_denominator("16") == 16


def test_secondary_primary_denominator_tolerates_a_non_numeric_amount() -> None:
    assert secondary_primary_denominator("not a number") == 0


def test_find_fraction_renders_a_one_in_n_rate() -> None:
    assert find_fraction(1 / 128) == "1/128"


def test_find_fraction_adds_thousands_separators() -> None:
    assert find_fraction(1 / 12345) == "1/12,345"


def test_find_fraction_rounds_half_away_from_zero() -> None:
    # 1/(1/8.005) = 8.005 -> rounds to 8.01, not banker's-rounds to 8.0.
    assert find_fraction(1 / 8.005) == "1/8.01"


def test_find_fraction_floors_when_rounded_denominator_is_set() -> None:
    assert find_fraction(1 / 128.6, rounded_denominator=True) == "1/128"


def test_find_fraction_returns_nan_for_a_nan_input() -> None:
    assert find_fraction(math.nan) == "NaN"


def test_a_zero_denominator_is_infinity_rather_than_an_exception() -> None:
    """**JS never raises here and Python does**, which took down a real map.

    `verf` sets `Secondary Primary Amount` to `0`, which reaches
    `parse_ratio` as `"1/0"` through `build_secondary_primary_num`. In the
    code being ported that is `Infinity`; here it was a `ZeroDivisionError`
    that killed `sections`, `sources`, `tasks`, `neighbours` and `estimate`
    on that map - every command that derives.

    `Infinity` is also the sensible reading of the rule being zero: no rate
    is ever common enough to pass the threshold, so the rate-based branches
    turn off. Measured on `verf`, no reading of that rule changes a single
    derived item, so this follows the source rather than guessing.
    """
    assert parse_ratio("1/0") == math.inf
    assert parse_ratio("-1/0") == -math.inf
    # JS `0/0` is NaN, and so is this.
    assert math.isnan(parse_ratio("0/0"))
    assert build_secondary_primary_num("0") == math.inf


def test_a_zero_denominator_does_not_disturb_ordinary_rates() -> None:
    """The guard is a branch on the denominator, not a rewrite of the parse."""
    assert parse_ratio("1/128") == 1 / 128
    assert parse_ratio("~1/50") == 1 / 50
    assert math.isnan(parse_ratio("Always"))


# --- how many one drop yields ---------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", 1.0),
        ("2", 2.0),
        ("1-2", 1.5),
        ("5-35 (noted)", 20.0),          # a range is its mean
        ("1 (noted)", 1.0),              # a note is the same item
        ("5 (Noted)", 5.0),              # …whatever its capitalisation
        ("5 (noted) (F2P)", 5.0),        # …and whatever else is annotated
        ("200-400", 300.0),
        ("1,000-2,000", 1500.0),         # thousands separators
    ],
)
def test_a_quantity_is_its_mean_and_a_note_is_the_same_item(raw: str, expected: float) -> None:
    assert parse_quantity(raw) == expected


@pytest.mark.parametrize("raw", ["1/26.79", "", "   ", "some", "-"])
def test_a_quantity_that_is_not_a_count_is_refused(raw: str) -> None:
    """One value in the export's 20,742 is a rate that wandered into a quantity
    field. Guessing at it would be worse than pricing the drop as a single
    unit, which is what `None` makes the caller do."""
    assert parse_quantity(raw) is None
