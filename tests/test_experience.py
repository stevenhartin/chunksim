"""Tests for the XP curve.

The table values below are the wiki's own published figures. They are the
check that computing the curve was the right call over scraping it: if the
closed form ever disagrees with them, the closed form is what's wrong.
"""

from __future__ import annotations

import pytest

from fray_claude.experience import MAX_LEVEL, xp_between, xp_for_level

#: (level, cumulative XP), from the wiki's experience table.
_PUBLISHED = [
    (1, 0),
    (2, 83),
    (10, 1_154),
    (26, 8_740),
    (51, 111_945),
    (76, 1_336_443),
    (92, 6_517_253),
    (99, 13_034_431),
]


@pytest.mark.parametrize(("level", "expected"), _PUBLISHED)
def test_matches_the_published_table(level: int, expected: int) -> None:
    assert xp_for_level(level) == expected


def test_the_curve_is_strictly_increasing() -> None:
    values = [xp_for_level(level) for level in range(1, MAX_LEVEL + 1)]

    assert all(later > earlier for earlier, later in zip(values, values[1:]))


@pytest.mark.parametrize("level", [0, -1, MAX_LEVEL + 1])
def test_a_level_off_the_curve_is_rejected(level: int) -> None:
    with pytest.raises(ValueError, match="level out of range"):
        xp_for_level(level)


def test_xp_between_is_the_difference() -> None:
    assert xp_between(92, 99) == 13_034_431 - 6_517_253


def test_a_target_already_reached_costs_nothing() -> None:
    assert xp_between(99, 92) == 0
    assert xp_between(50, 50) == 0


def test_a_level_above_the_curve_is_clamped_rather_than_raising() -> None:
    # `max_skill` comes from the map payload, so a nonsense current level must
    # not stop an estimate - see the module docstring.
    assert xp_between(999, 99) == 0
    assert xp_between(0, 2) == 83
