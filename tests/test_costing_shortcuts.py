"""Agility shortcuts: the attempt, the failure, and the curve."""

from __future__ import annotations

import pytest

from chunksim.costing.shortcuts import (
    ATTEMPT_SECONDS,
    SHORTCUT_TICKS,
    expected_experience,
    xp_per_hour,
)
from chunksim.remote.skill_tables import ShortcutInfo, parse_agility_info


def _info(**kwargs: object) -> ShortcutInfo:
    base: dict[str, object] = {"name": "Rocks", "level": 1, "experience": 10.0}
    return ShortcutInfo(**{**base, **kwargs})  # type: ignore[arg-type]


def test_a_shortcut_with_no_curve_cannot_fail() -> None:
    """**Absence means certainty, not ignorance.** The wiki charts a shortcut
    precisely where there is a chance to miss, so a page with no chart is one
    that always works - which is why this pays the full experience rather than
    falling back to some assumed chance."""
    assert expected_experience(_info(experience=25.0), 99) == 25.0
    assert xp_per_hour(_info(experience=25.0), 99) == pytest.approx(
        25.0 * 3600.0 / ATTEMPT_SECONDS
    )


def test_a_failure_still_pays_and_is_weighted_in() -> None:
    """The Cosmic altar narrow walkway pays 9.9 on a success and 6 on a
    failure. Counting only successes would be wrong in the safe direction, but
    wrong - so both outcomes are weighted by the published curve."""
    info = _info(experience=9.9, fail_experience=6.0, low=51.0, high=252.0)

    low_level = expected_experience(info, 1)
    high_level = expected_experience(info, 99)

    assert 6.0 < low_level < high_level < 9.9, "between the two outcomes, rising"


def test_the_attempt_is_eight_ticks() -> None:
    """**The one stated number here.** Shortcuts differ - a wall climb is
    quicker than a stepping-stone chain - and eight ticks is the average. It
    replaced an 18-second cycle whose own comment called it a target rather
    than a measurement, which is why every shortcut got 3.75x faster."""
    assert SHORTCUT_TICKS == 8.0
    assert ATTEMPT_SECONDS == pytest.approx(4.8)


def test_a_versioned_page_yields_one_entry_per_version() -> None:
    """**One page often holds several shortcuts.** `Rocks (Vampyrium)` has a
    27.5-xp slide at level 78 and a 0-xp climb at 61, written as `xp1`/`xp2`.
    Read as one row each, named the way the export writes them when it
    disambiguates - `<page>#<version>`."""
    page = """
{{Agility info
|version1 = Slide
|version2 = Climb
|name = Rocks
|level1 = 78
|level2 = 61
|xp1 = 27.5
|xp2 = 0
|type = Shortcut
}}
"""
    found = parse_agility_info(page, "Rocks (Vampyrium)")

    assert [(f.name, f.level, f.experience) for f in found] == [
        ("Rocks (Vampyrium)#Slide", 78, 27.5),
        ("Rocks (Vampyrium)#Climb", 61, 0.0),
    ]


def test_an_unversioned_page_joins_on_its_bare_name() -> None:
    """The single-shortcut form, which is most of them, and the failure
    experience and curve are read alongside."""
    page = """
{{Agility info
|name = Stepping stone
|level = 1
|xp = 3
|failxp = 1
|type = Shortcut
}}
{{Skilling success chart|label=Crossing
|low1=51|high1=252|req1=1
}}
"""
    (found,) = parse_agility_info(page, "Stepping stone (Lumbridge Swamp Caves)")

    assert found.name == "Stepping stone (Lumbridge Swamp Caves)"
    assert (found.experience, found.fail_experience) == (3.0, 1.0)
    assert (found.low, found.high) == (51.0, 252.0)
    # 20% success at level 1, so barely above the failure experience.
    assert xp_per_hour(found, 1) < 3.0 * 3600.0 / ATTEMPT_SECONDS


def test_a_page_with_no_agility_info_yields_nothing() -> None:
    """Four of the linked pages carry no box at all. Nothing is a better
    answer than a shortcut priced off the list's level alone."""
    assert parse_agility_info("Just prose about a wall.", "Wall") == ()
