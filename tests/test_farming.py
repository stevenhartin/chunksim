"""Tests for the two farming modules: the crop table, and the schedule.

`remote/farming.py` parses the wiki calculator's Lua; `costing/farming.py`
turns it into a day's work. The fixtures are trimmed from the real module,
keeping the shape that broke the first parser - a `materials` table with a
`name` of its own, sitting between the crop's `xp` and its `type`.
"""

from __future__ import annotations

import pytest

from chunksim.costing.farming import (
    DEFAULT_HARVESTS_PER_DAY,
    HARVEST_SECONDS,
    harvest_experience,
    plan_for,
    schedule_key,
)
from chunksim.remote.farming import Crop, parse_crops

_LUA = """
return {
	{
    	name = 'Potato',
        level = 1,
        xp = 9,
        plantXp = 8,
        materials = {
        	{ name = 'Potato seed', quantity = 3 }
        },
        members = 'Yes',
        type = 'Allotment'
    }, {
    	name = 'Magic tree',
        level = 75,
        xp = 13913.8,
        materials = {
        	{ name = 'Magic seed', quantity = 1 }
        },
        members = 'Yes',
        type = 'Tree'
    }, {
    	name = 'Redwood tree',
        level = 90,
        xp = 22680,
        materials = {
        	{ name = 'Redwood tree seed', quantity = 1 }
        },
        members = 'Yes',
        type = 'Special'
    }
}
"""


def test_a_crop_keeps_its_own_name_and_its_seeds() -> None:
    """**The first parser returned nothing.** Splitting on `name =` gives 152
    fragments for 76 crops, because every crop's `materials` has a name too -
    and worse, each fragment then ends at its own materials, before the `type`
    that says which patch it goes in. Brace matching is the fix."""
    crops = {crop.name: crop for crop in parse_crops(_LUA)}

    assert set(crops) == {"Potato", "Magic tree", "Redwood tree"}
    assert crops["Potato"].seed == "Potato seed"
    assert crops["Potato"].seeds_per_patch == 3.0
    assert crops["Potato"].patch == "Allotment"
    assert crops["Magic tree"].experience == pytest.approx(13913.8)


def test_a_harvest_pays_planting_once_and_the_crop_per_item() -> None:
    """A tree is checked once for all of it; an allotment pays per potato.
    That is why a banana tree reads 1,841 and a potato 9."""
    tree = Crop(name="Magic tree", patch="Tree", level=75, experience=13913.8)
    potato = Crop(
        name="Potato", patch="Allotment", level=1, experience=9.0, plant_experience=8.0
    )

    assert harvest_experience(tree) == pytest.approx(13913.8)
    # Six items an allotment, the stated assumption.
    assert harvest_experience(potato) == pytest.approx(8.0 + 9.0 * 6)


def test_the_special_patch_is_split_by_crop_name() -> None:
    """The module calls redwood, teak and cactus all `Special`, and they are
    farmed at wildly different frequencies - weekly against three a day."""
    assert schedule_key(Crop("Redwood tree", "Special", 90, 22680.0)) == "Redwood"
    assert schedule_key(Crop("Teak tree", "Special", 35, 7325.0)) == "Hardwood"
    assert schedule_key(Crop("Cactus spine", "Special", 55, 25.0)) == "Cactus"


def test_what_is_not_farmed_is_absent_rather_than_zero() -> None:
    """Hops, flowers, belladonna, spirit trees and celastrus are left out of
    the schedule, so putting one back is a line in the overrides file."""
    assert schedule_key(Crop("Barley", "Hops", 3, 9.5)) is None
    assert schedule_key(Crop("Marigolds", "Flower", 2, 55.5)) is None
    assert schedule_key(Crop("Spirit tree", "Special", 83, 19500.3)) is None
    assert schedule_key(Crop("Cave nightshade", "Special", 63, 603.0)) is None


def test_a_plan_takes_the_best_crop_each_patch_can_grow() -> None:
    crops = parse_crops(_LUA)

    plan = plan_for(crops, level=75)

    assert {run.key: run.crop for run in plan.runs} == {
        "Allotment": "Potato",
        "Tree": "Magic tree",
    }
    # Redwood needs 90 and is left out at 75.
    assert plan.xp_per_day == pytest.approx(
        62.0 * DEFAULT_HARVESTS_PER_DAY["Allotment"]
        + 13913.8 * DEFAULT_HARVESTS_PER_DAY["Tree"]
    )


def test_days_and_hours_measure_different_things() -> None:
    """**The point of the module.** The hours are clicking and go in the
    bucket; the days are calendar and are reported beside them, because a day
    of waiting is not a day of playing. Priced as a rate, Farming 1 -> 99 came
    out at 75,353 hours."""
    crops = parse_crops(_LUA)
    plan = plan_for(crops, level=99)

    days = plan.days_for(1_000_000)
    hours = plan.hours_for(1_000_000)

    assert days == pytest.approx(1_000_000 / plan.xp_per_day)
    assert hours == pytest.approx(days * plan.harvests_per_day * HARVEST_SECONDS / 3600)
    # Far more calendar than clicking, which is the whole shape of the skill.
    assert days > hours


def test_a_schedule_with_nothing_in_it_costs_nothing_rather_than_dividing_by_zero() -> None:
    plan = plan_for(parse_crops(_LUA), level=1, harvests_per_day={})

    assert plan.runs == ()
    assert plan.days_for(1_000_000) == 0.0
