"""Tests for OSRS-style drop-rate parsing/formatting."""

from __future__ import annotations

import math

from fray_claude.rates import (
    build_rare_drop_num,
    build_secondary_primary_num,
    find_fraction,
    looks_non_numeric,
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
