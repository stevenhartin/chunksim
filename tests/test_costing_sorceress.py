"""The Sorceress's Garden: two published halves that check each other."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import sorceress as sg
from chunksim.model.chunkinfo import ChunkInfo


class TestTheLapTimeAgreesWithTheYield:
    """**The check that makes this a model rather than four numbers.**

    Neither the lap time nor the juice an hour states the mechanic joining
    them - one sq'irk a lap, and a fixed count of sq'irks to a juice - but
    every garden's two figures agree through it.
    """

    @pytest.mark.parametrize("name", sorted(sg.GARDENS))
    def test_one_sqirk_a_lap_reproduces_the_stated_yield(self, name: str) -> None:
        garden = sg.GARDENS[name]
        assert sg.derived_juice_per_hour(garden) == pytest.approx(
            garden.juice_per_hour, abs=0.8
        )

    def test_the_sqirks_a_juice_count_down_by_one(self) -> None:
        # Winter 5, spring 4, autumn 3, summer 2 - which is the whole of why a
        # deeper garden is better despite a slower lap.
        by_level = sorted(sg.GARDENS.values(), key=lambda g: g.level)
        assert [g.sqirks_per_juice for g in by_level] == [5, 4, 3, 2]

    def test_the_slowest_lap_is_not_the_worst_garden(self) -> None:
        # Autumn has the longest lap of the four and pays five times winter.
        autumn, winter = sg.GARDENS["autumn"], sg.GARDENS["winter"]
        assert autumn.lap_seconds > winter.lap_seconds
        assert sg.rate_at(autumn) > sg.rate_at(winter)


class TestAgainstThePublishedRates:
    """Two garden pages state an hourly figure, and both come out."""

    def test_spring_matches_its_own_worked_example(self) -> None:
        # "Players can expect around 21 spring sq'irkjuice per hour equalling
        # about 28,350 xp/h."
        assert 21.0 * sg.GARDENS["spring"].experience == pytest.approx(28_350.0)

    def test_summer_matches_its_stated_maximum(self) -> None:
        # "The maximum experience possible per hour is 150,000."
        assert sg.rate_at(sg.GARDENS["summer"]) == pytest.approx(150_000.0)

    @pytest.mark.parametrize(
        "name,experience",
        [("winter", 350.0), ("spring", 1350.0), ("autumn", 2350.0), ("summer", 3000.0)],
    )
    def test_the_experience_per_juice_is_the_calculators(
        self, name: str, experience: float
    ) -> None:
        assert sg.GARDENS[name].experience == experience


class TestTheGardensAreOrdered:
    def test_a_deeper_garden_is_always_better(self) -> None:
        by_level = sorted(sg.GARDENS.values(), key=lambda g: g.level)
        rates = [sg.rate_at(g) for g in by_level]
        assert rates == sorted(rates)

    def test_no_rate_reads_a_level(self) -> None:
        # What a level buys is a better garden, not a faster lap. Nothing here
        # takes one.
        assert sg.rate_at(sg.GARDENS["summer"]) == 150_000.0


class TestTheAutumnLevel:
    """**Upstream's level for this one is wrong and the model uses the wiki's.**

    The export gates the autumn turn-in at 25 where its garden page says 45,
    and the other three agree exactly - which is what makes it a slip. Twenty
    levels of a 56,400/hr band that cannot be entered is the worst error this
    module could make, so it is pinned.
    """

    def test_autumn_opens_where_the_wiki_says(self) -> None:
        assert sg.GARDENS["autumn"].level == 45

    def test_the_other_three_are_upstreams_too(self) -> None:
        assert sg.GARDENS["winter"].level == 1
        assert sg.GARDENS["spring"].level == 25
        assert sg.GARDENS["summer"].level == 65

    def test_a_band_opens_at_the_gardens_level_not_the_tasks(self) -> None:
        valid: dict[str, dict[str, object]] = {
            "Thieving": {sg.GARDENS["autumn"].task: {}}
        }
        bands = sg.methods(valid)["Thieving"]
        assert [band.level for band in bands] == [45]


class TestReachability:
    _VALID: dict[str, dict[str, object]] = {
        "Thieving": {garden.task: {} for garden in sg.GARDENS.values()}
    }

    def test_every_garden_a_map_reaches(self) -> None:
        bands = sg.methods(self._VALID)["Thieving"]
        assert len(bands) == 4
        assert [band.level for band in bands] == [1, 25, 45, 65]

    def test_nothing_when_none_are_reachable(self) -> None:
        assert sg.methods({}) == {}
        assert sg.methods({"Thieving": {}}) == {}

    def test_upstream_still_owns_reachability(self) -> None:
        # The wiki decides the level; the export decides whether it is offered.
        one: dict[str, dict[str, object]] = {
            "Thieving": {sg.GARDENS["summer"].task: {}}
        }
        assert len(sg.methods(one)["Thieving"]) == 1

    def test_a_band_names_the_task_it_would_be_overridden_through(self) -> None:
        for band in sg.methods(self._VALID)["Thieving"]:
            assert band.knob.startswith("training/Turn-in ~|")
            assert band.knob.endswith("/Thieving")


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "sorceress.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(sg.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`sorceress.py`" in listing


class TestTheFarmingHalfIsTheSameLap:
    """**"You can only pick one fruit per trip, *or* if you pick herbs
    instead"** - so a herb trip is not a detour, it is the trip. And the
    payout is published without a caveat: 50 Farming experience, "regardless
    of which garden is chosen"."""

    _VALID: dict[str, dict[str, object]] = {
        "Farming": {sg.HERB_TASK: {}},
    }

    def test_the_payout_is_flat_across_the_gardens(self) -> None:
        assert sg.HERB_EXPERIENCE == 50.0

    def test_the_laps_come_from_the_figures_the_thieving_side_spends(self) -> None:
        """The stated juice an hour times the sq'irks a juice - so the two
        halves cannot disagree about how fast the garden is run."""
        for garden in sg.GARDENS.values():
            assert sg.laps_per_hour(garden) == (
                garden.juice_per_hour * garden.sqirks_per_juice
            )

    def test_they_agree_with_the_lap_times_within_a_few_percent(self) -> None:
        """Which is the module's own check, read a second time."""
        for garden in sg.GARDENS.values():
            implied = 3600.0 / garden.lap_seconds
            assert 0.95 < sg.laps_per_hour(garden) / implied < 1.05

    def test_the_winter_garden_wins_and_needs_nothing(self) -> None:
        """**The garden is not a choice.** The payout is flat, so the best
        rate is the most trips an hour - and that is winter's, which is also
        the only garden with no Thieving requirement."""
        best = max(sg.GARDENS.values(), key=sg.laps_per_hour)

        assert best is sg.GARDENS["winter"]
        assert best.level == 1

    def test_the_rate_is_eighty_five_hundred(self) -> None:
        assert sg.farming_rate() == 8_500.0

    def test_it_opens_at_level_one(self) -> None:
        (band,) = sg.methods(self._VALID)["Farming"]

        assert band.level == 1
        assert band.knob == f"training/{sg.HERB_TASK}/Farming"

    def test_it_does_not_scale(self) -> None:
        """25 experience a herb is 25 at level 99 - the shape to expect, and
        why this is for the bottom of a skill with almost nothing active
        below Tithe Farm's 34."""
        assert len(sg.methods(self._VALID)["Farming"]) == 1

    def test_nothing_when_the_herb_challenge_is_out_of_reach(self) -> None:
        assert "Farming" not in sg.methods({})
        assert "Farming" not in sg.methods({"Farming": {}})

    def test_the_thieving_side_is_unaffected(self) -> None:
        """The herbs are a different pick on the same trip, not a share of
        the juice - so a map with only the Farming challenge gets no Thieving
        bands and vice versa."""
        assert "Thieving" not in sg.methods(self._VALID)

        thieving: dict[str, dict[str, object]] = {
            "Thieving": {garden.task: {} for garden in sg.GARDENS.values()}
        }
        assert "Farming" not in sg.methods(thieving)


class TestTheFarmingHalfIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "sorceress.methods(" in source

    @pytest.mark.real_export
    def test_upstream_carries_one_herb_challenge_at_level_one(
        self, real_export: ChunkInfo
    ) -> None:
        """One challenge for the herbs where there are four for the juice,
        which matches the game: the herbs pay the same in every garden."""
        entry = real_export.challenges["Farming"].get(sg.HERB_TASK)

        assert isinstance(entry, dict)
        assert entry.get("Primary") is True
        assert entry.get("Level") == 1
