"""Dissecting a sacred eel, whose whole cost is the catching."""

from __future__ import annotations

import pytest

from chunksim.costing import sacredeel
from chunksim.costing.gathering import Tables

#: The wiki's own curve for the fish, as `chunksim gather-tables` records it.
_TABLES = Tables(curves={"sacred eel": (("Sacred eel", 0.0, 60.0, 87, "confirmed"),)})

_CHALLENGES = {
    sacredeel.TASK: {
        "Items": ["Knife", "Sacred eel*"],
        "Level": 72,
        "Output": "Zulrah's scales",
        "Primary": True,
    }
}
_VALID = {sacredeel.SKILL: {sacredeel.TASK: 72}}


@pytest.mark.parametrize(
    "level,count,paid",
    [(71, 0, 0.0), (72, 4, 112.0), (79, 4, 112.0), (80, 5, 115.0), (88, 6, 118.0),
     (96, 7, 121.0), (104, 8, 124.0)],
)
def test_the_scale_tiers_are_eight_levels_apart(
    level: int, count: int, paid: float
) -> None:
    """The page's own table, and the average it publishes beside each range:
    3-5 averages 4, 4-6 averages 5, and so on. 100 base experience plus 3 a
    scale, which reproduces the production template's stated `109-127` at its
    ends."""
    assert sacredeel.scales(level) == count
    assert sacredeel.experience(level) == paid


def test_the_throughput_is_the_fishing_models_own_roll() -> None:
    """**Nothing new is modelled here.** `success_chance` on the tables'
    `Sacred eel` curve gives 21.09% at level 87 and 23.83% at 99, which is the
    wiki's own published pair - so the Fishing side cannot drift from the node
    walk's, and a five-tick roll turns it into catches."""
    assert sacredeel.catches_per_hour(_TABLES, 87) == pytest.approx(253.1, abs=0.1)
    assert sacredeel.catches_per_hour(_TABLES, 99) == pytest.approx(285.9, abs=0.1)


def test_a_fishing_level_below_the_requirement_is_floored() -> None:
    """You cannot dissect an eel you cannot catch, so the rate below 87 is the
    rate at 87 rather than a smaller one."""
    assert sacredeel.catches_per_hour(_TABLES, 1) == sacredeel.catches_per_hour(
        _TABLES, sacredeel.FISHING_REQUIREMENT
    )


def test_the_bands_are_cookings_and_the_fishing_level_is_handed_in() -> None:
    """**The opposite assignment to `barbarian.py`**, and the same question
    from the other side: which fish you catch there depends on Fishing, so the
    rate is flat in Strength. Here the *scales* depend on Cooking, so that is
    the axis, and Fishing enters only as a scale factor."""
    found = sacredeel.methods(_TABLES, _CHALLENGES, _VALID, 87)[sacredeel.SKILL]

    assert [band.level for band in found] == [72, 80, 88, 96]
    assert found[0].xp_per_hour == pytest.approx(253.1 * 112.0, abs=20)


def test_the_boosted_tier_is_never_a_band() -> None:
    """104 needs a boost and a climb tops out at 99, so a band there could
    never open."""
    found = sacredeel.methods(_TABLES, _CHALLENGES, _VALID, 87)[sacredeel.SKILL]

    assert max(band.level or 0 for band in found) <= sacredeel.MAX_LEVEL


def test_fishing_moves_it_by_thirteen_percent_across_its_whole_range() -> None:
    """Which is why handing in the level is worth doing and why getting it
    slightly wrong is not serious."""
    low = sacredeel.xp_per_hour(_TABLES, 87, 72)
    high = sacredeel.xp_per_hour(_TABLES, 99, 72)

    assert high / low == pytest.approx(1.13, abs=0.01)


def test_no_curve_prices_nothing() -> None:
    """The same refusal the node walk makes, rather than a stand-in."""
    assert sacredeel.catches_per_hour(Tables(), 99) == 0.0
    assert sacredeel.methods(Tables(), _CHALLENGES, _VALID, 87) == {}


def test_a_map_that_cannot_reach_it_gets_nothing() -> None:
    assert sacredeel.methods(_TABLES, _CHALLENGES, {"Cooking": {}}, 87) == {}
