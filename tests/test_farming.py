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
from chunksim.costing import farming
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



def test_a_herb_patch_yields_more_than_one_herb() -> None:
    """**One seed, 8.8 herbs** - the wiki's own empirical figure for a standard
    patch. Without it the item walk charged a whole ranarr seed, 163s, against
    every single herb, which put a grimy ranarr weed at 168.9s and left every
    potion consuming one under the 1,000/hr floor. The guide that never paid
    for its herbs won instead."""
    assert farming.HERBS_PER_SEED > 1.0


def test_only_ordinary_farmed_herbs_get_a_yield() -> None:
    """**Both of upstream's markers, because either alone is wrong.**
    `Category` catches the allotments and trees too; `Objects` would catch
    anything else standing at a herb patch. The Chambers of Xeric herbs carry
    neither - they are found rather than farmed - and must not be priced as a
    patch."""
    challenges = {
        "Grow a ~|grimy ranarr weed|~": {
            "Primary": True,
            "Category": ["Normal Farming"],
            "Objects": ["Herb patch"],
        },
        "Grow a ~|grimy golpar|~": {"Primary": True, "Category": ["CoX"]},
        "Grow a ~|potato|~": {
            "Primary": True,
            "Category": ["Normal Farming"],
            "Objects": ["Allotment patch"],
        },
        "Grow a ~|secondary|~": {
            "Primary": False,
            "Category": ["Normal Farming"],
            "Objects": ["Herb patch"],
        },
    }

    found = farming.harvest_yields(challenges, dict.fromkeys(challenges, {}))

    assert found == {"Grow a ~|grimy ranarr weed|~": farming.HERBS_PER_SEED}


def _crop(name: str, patch: str, level: int = 1, xp: float = 10.0) -> Crop:
    return Crop(
        name=name,
        level=level,
        experience=xp,
        plant_experience=0.0,
        patch=patch,
        seed="",
    )


class TestTheCropAChallengeIsAbout:
    """Joined on upstream's own marked span, which is what `~|...|~` is for -
    a `Grow a ...` challenge states no `Output` and its verb-stripped words are
    a sentence."""

    _CROPS = [
        _crop("Torstol", "Herb", 85),
        _crop("Marigolds", "Flower"),
        _crop("Oak (Farming)", "Tree", 15),
        _crop("Calquat fruit", "Special", 72),
    ]

    def test_a_plain_name_joins(self) -> None:
        found = farming.crop_for("Grow a ~|torstol|~", self._CROPS)

        assert found is not None and found.name == "Torstol"

    def test_the_grimy_prefix_is_stripped(self) -> None:
        found = farming.crop_for("Grow a ~|grimy torstol|~", self._CROPS)

        assert found is not None and found.name == "Torstol"

    def test_a_plural_the_calculator_writes(self) -> None:
        found = farming.crop_for("Grow a ~|marigold|~", self._CROPS)

        assert found is not None and found.name == "Marigolds"

    def test_a_disambiguator_the_calculator_carries(self) -> None:
        found = farming.crop_for("Grow an ~|oak tree|~", self._CROPS)

        assert found is not None and found.name == "Oak (Farming)"

    def test_the_calculator_naming_the_product(self) -> None:
        found = farming.crop_for("Grow a ~|calquat tree|~", self._CROPS)

        assert found is not None and found.name == "Calquat fruit"

    def test_a_name_nothing_answers_to_is_none(self) -> None:
        assert farming.crop_for("Grow ~|flax|~", self._CROPS) is None
        assert farming.crop_for("Do a thing", self._CROPS) is None

    def test_every_alias_names_a_crop_the_shipped_tables_carry(self) -> None:
        """**A typo in an alias is a silent miss**: the row goes back to
        reading `unpriced` with nothing to say it was meant to be explained."""
        from chunksim.costing.inputs import load_reference
        from chunksim.model.chunkinfo import ChunkInfo
        from chunksim.costing.inputs import load_heuristics

        blobs = load_reference(None, None)
        heuristics, _ = load_heuristics(ChunkInfo({}), None, blobs)
        names = {crop.name for crop in heuristics.crops}

        assert names, "no crop table shipped"
        for span, crop in farming.CROP_ALIASES.items():
            assert crop in names, (span, crop)


class TestTheScheduleAnswersForTheCrops:
    """**The report was contradicting the estimate.** `plan_for` picks one
    crop a line and the estimate's whole Farming answer *is* those picks, so
    the schedule's own herb printed `unpriced`."""

    _CROPS = [
        _crop("Torstol", "Herb", 85, 20.0),
        _crop("Guam leaf", "Herb", 9, 1.0),
        _crop("Marigolds", "Flower"),
    ]
    _VALID = {
        "Farming": {
            "Grow a ~|grimy torstol|~": True,
            "Grow a ~|grimy guam leaf|~": True,
            "Grow a ~|marigold|~": True,
            "Grow ~|flax|~": True,
        }
    }

    def _found(self) -> dict[str, str]:
        return farming.refused(self._VALID, self._CROPS)

    def test_the_schedules_own_pick_says_so(self) -> None:
        why = self._found()["Grow a ~|grimy torstol|~"]

        assert "schedule's Herb crop" in why
        assert "days" in why

    def test_an_outranked_crop_names_the_winner(self) -> None:
        why = self._found()["Grow a ~|grimy guam leaf|~"]

        assert "outranked on the Herb line" in why
        assert "Torstol" in why

    def test_a_crop_the_schedule_excludes_says_that_instead(self) -> None:
        """Flowers are absent from `DEFAULT_HARVESTS_PER_DAY` on purpose -
        "nobody trains on them", this module's own docstring says."""
        why = self._found()["Grow a ~|marigold|~"]

        assert "deliberately not in the growing schedule" in why

    def test_a_crop_it_cannot_join_keeps_unpriced(self) -> None:
        """Honest: the join is what says which sentence applies."""
        assert "Grow ~|flax|~" not in self._found()

    def test_nothing_where_farming_is_unreachable(self) -> None:
        assert farming.refused({}, self._CROPS) == {}
        assert farming.refused({"Farming": {}}, self._CROPS) == {}

    def test_nothing_without_a_crop_table(self) -> None:
        assert farming.refused(self._VALID, []) == {}

    def test_an_emptied_schedule_refuses_everything_as_excluded(self) -> None:
        """"Someone who farms nothing farms nothing" - `plan_for`'s rule, and
        the sentences have to follow it."""
        found = farming.refused(self._VALID, self._CROPS, harvests_per_day={})

        assert all("deliberately not" in why for why in found.values())
    def test_it_invents_no_rate(self) -> None:
        """The one thing that must not happen: a herb harvest is a hundred
        experience for a few seconds of clicking, so a per-crop rate reads
        enormous and would win every band - `estimate._farming_bands`' error."""
        assert all(isinstance(why, str) for why in self._found().values())
        assert not hasattr(farming, "crop_rate")


class TestUpstreamsOwnPatchIsTheOtherWayIn:
    """**The better half of the join.** A crop challenge states its patch
    whether or not the calculator's table has heard of the crop, so `flax`,
    `hemp` and `cotton` classify with the hops they are planted beside
    despite `Module:Skill calc/Farming` carrying none of the three."""

    _VALID = {"Farming": {"Grow ~|flax|~": True, "Grow ~|barley|~": True}}
    _CHALLENGES = {
        "Grow ~|flax|~": {"Objects": ["Hops Patch"]},
        "Grow ~|barley|~": {"Objects": ["Hops Patch"]},
    }

    def test_a_patch_name_reads_as_its_schedule_line(self) -> None:
        assert farming.patch_key({"Objects": ["Hops Patch"]}) == "Hops"
        assert farming.patch_key({"Objects": ["Herb patch"]}) == "Herb"
        assert farming.patch_key({"Objects": ["Fruit Tree Patch"]}) == "Fruit tree"

    def test_a_patch_nothing_answers_to_is_none(self) -> None:
        assert farming.patch_key({"Objects": ["Belladonna patch"]}) is None
        assert farming.patch_key({}) is None

    def test_the_three_fibres_read_as_the_hops_they_grow_beside(self) -> None:
        found = farming.refused(self._VALID, [], self._CHALLENGES)

        assert set(found) == {"Grow ~|flax|~", "Grow ~|barley|~"}
        assert len(set(found.values())) == 1
        assert "deliberately not in the growing schedule" in found["Grow ~|flax|~"]

    def test_the_calculators_row_still_wins_where_there_is_one(self) -> None:
        """`crop_for` is tried first, so a crop the table knows keeps the
        sentence its own row earns rather than its patch's."""
        crops = [_crop("Torstol", "Herb", 85, 20.0), _crop("Guam leaf", "Herb", 9, 1.0)]
        found = farming.refused(
            {"Farming": {"Grow a ~|grimy guam leaf|~": True}},
            crops,
            {"Grow a ~|grimy guam leaf|~": {"Objects": ["Herb patch"]}},
        )

        assert "outranked on the Herb line" in found["Grow a ~|grimy guam leaf|~"]

    def test_a_challenge_naming_no_patch_keeps_unpriced(self) -> None:
        """Which is what the two Chambers of Xeric herbs and the Sorceress's
        Garden get: they name no patch because they are not farmed."""
        found = farming.refused(
            {"Farming": {"Grow a ~|grimy buchu|~": True}},
            [],
            {"Grow a ~|grimy buchu|~": {"Category": ["CoX"]}},
        )

        assert found == {}

    def test_a_patch_line_the_schedule_does_farm_reads_as_outranked(self) -> None:
        """A future crop the calculator has no row for still classifies: it is
        not the winner, because the winner comes from the table."""
        crops = [_crop("Torstol", "Herb", 85, 20.0)]
        found = farming.refused(
            {"Farming": {"Grow a ~|grimy newherb|~": True}},
            crops,
            {"Grow a ~|grimy newherb|~": {"Objects": ["Herb patch"]}},
        )

        assert "outranked on the Herb line" in found["Grow a ~|grimy newherb|~"]
