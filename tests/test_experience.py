"""Tests for the XP curve.

The table values below are the wiki's own published figures. They are the
check that computing the curve was the right call over scraping it: if the
closed form ever disagrees with them, the closed form is what's wrong.
"""

from __future__ import annotations

import pytest

from chunksim.model.experience import (
    MAX_LEVEL,
    level_for_xp,
    xp_between,
    xp_for_level,
)

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


def test_level_for_xp_is_the_exact_inverse() -> None:
    """Every threshold round-trips, at every level the curve defines."""
    assert [level_for_xp(xp_for_level(n)) for n in range(1, MAX_LEVEL + 1)] == list(
        range(1, MAX_LEVEL + 1)
    )


def test_one_xp_short_of_a_threshold_is_the_level_below() -> None:
    """The property the band walk rests on: a quest reward that lands you one
    XP short of 54 has not opened the level-54 method."""
    assert [level_for_xp(xp_for_level(n) - 1) for n in range(2, MAX_LEVEL + 1)] == list(
        range(1, MAX_LEVEL)
    )


def test_a_total_off_the_curve_is_clamped_at_both_ends() -> None:
    """A caller handing this a total is describing a player, and a player
    cannot be off the curve."""
    assert level_for_xp(-5) == 1
    assert level_for_xp(0) == 1
    assert level_for_xp(10**9) == MAX_LEVEL


def test_druidic_ritual_leaves_herblore_at_three() -> None:
    """The export grants `{"Herblore": 250}` for the quest, and 250 XP is
    level 3 - which is the whole reason Herblore has any method open at all."""
    assert level_for_xp(250) == 3
