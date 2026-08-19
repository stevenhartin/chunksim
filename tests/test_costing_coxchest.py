"""The Chambers of Xeric thieving room, where the roll is every single tick."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import coxchest as cx
from chunksim.costing.gathering import GUESS, success_chance
from chunksim.model.experience import xp_for_level

_VALID: dict[str, dict[str, object]] = {"Thieving": {cx.TASK: {}}}


class TestTheChartIsThePagesOwnProse:
    """"The chance of successfully opening the chest without a lockpick is
    around 39% at level 1, scaling to about 61% at level 99" - and the plain
    series says exactly that, which is what makes the chart the right read."""

    def test_the_two_stated_points(self) -> None:
        assert success_chance(1, *cx.PLAIN_CURVE) == pytest.approx(0.39, abs=0.005)
        assert success_chance(99, *cx.PLAIN_CURVE) == pytest.approx(0.61, abs=0.005)

    def test_the_lockpick_is_a_constant_twenty_one_points(self) -> None:
        # "With a lockpick, these odds increase by a constant 21 percentage
        # points" - Mod Ash, and the second series to the point.
        for level in (1, 50, 99):
            gap = success_chance(level, *cx.CURVE) - success_chance(level, *cx.PLAIN_CURVE)
            assert gap == pytest.approx(0.21, abs=0.005), level


class TestTheCadence:
    def test_it_rolls_every_tick(self) -> None:
        """"Upon clicking the chest, an attempt to open it will be made every
        game tick until the player succeeds" - the sharpest cadence in the
        skill, and why the guide calls this the fastest early method."""
        assert cx.ATTEMPT_TICKS == 1.0

    def test_a_grub_drop_costs_about_four_percent(self) -> None:
        bare = cx.ATTEMPT_TICKS / success_chance(1, *cx.CURVE)
        assert cx.open_ticks(1) / bare == pytest.approx(1.043, abs=0.005)


class TestTheGrubYieldIsThePublishedRule:
    """"A minimum of one cavern grub is awarded, with a chance to add an
    additional one for every 25 levels" - and the rounding is stated too:
    "picks a random integer between 0 and the maximum ... then raises the
    outcome up to the minimum"."""

    @pytest.mark.parametrize("level,mean", [(1, 1.0), (49, 1.0), (50, 4 / 3), (75, 7 / 4)])
    def test_the_mean_at_each_step(self, level: int, mean: float) -> None:
        assert cx.grubs_per_open(level) == pytest.approx(mean)

    def test_the_minimum_rises_at_ninety_five(self) -> None:
        # "Quantity is at least 1, or at least 2 if your level is 95+."
        assert cx.grubs_per_open(95) == pytest.approx(9 / 4)

    def test_it_is_exactly_one_where_the_recovery_was_made(self) -> None:
        # The 1-40 climb is entirely inside the flat stretch, which is what
        # makes the experience recovery independent of the yield rule.
        assert all(cx.grubs_per_open(level) == 1.0 for level in range(1, 50))


class TestTheExperienceIsRecoveredAndBounded:
    """**The wiki states no figure**, so it is recovered - and two independent
    published statements bound it to `[8.67, 11.70]` with `EXPERIENCE` the
    round number inside."""

    def _hours_to_forty(self, paid: float) -> float:
        return sum(
            (xp_for_level(level + 1) - xp_for_level(level))
            / (paid * cx.TICKS_PER_HOUR / cx.open_ticks(level))
            for level in range(1, 40)
        )

    def test_the_guides_hour_comes_out_as_about_an_hour(self) -> None:
        """"It only requires about one hour of raid time to level from 1-40."
        At 10 an open that is 59 minutes."""
        assert self._hours_to_forty(cx.EXPERIENCE) == pytest.approx(0.98, abs=0.03)

    def test_and_the_rate_band_is_the_independent_check(self) -> None:
        """"You can expect experience rates of up to 30,000-50,000 experience
        an hour" - said of the levels the method covers."""
        for level in (1, 20, 45):
            assert 30_000 <= cx.xp_per_hour(level) <= 50_000, level

    def test_the_two_statements_agree_rather_than_being_one(self) -> None:
        # Their intervals overlap on [8.67, 11.70]; a figure outside either is
        # refused by the other, which is what makes this a recovery and not a
        # fit to a single number.
        assert 8.67 < cx.EXPERIENCE < 11.70

    def test_it_stays_a_guess(self) -> None:
        # A figure the wiki declines to state is not one this project read.
        for band in cx.methods(_VALID)["Thieving"]:
            assert band.match == GUESS


class TestTheLockpickIsTheOneToolThisProjectAssumes:
    """Everywhere else the plain series is spent, because the item comes from
    a shop a chunk map may not hold. This one comes from inside the raid."""

    def test_the_curve_spent_is_the_lockpick_one(self) -> None:
        assert cx.CURVE == (153.0, 209.0)
        assert cx.xp_per_hour(1) > cx.xp_per_hour(1, curve=cx.PLAIN_CURVE)

    def test_the_plain_series_would_fall_out_of_the_published_band(self) -> None:
        # Which is why spending it would apply a figure recovered under one
        # regime to another.
        assert cx.xp_per_hour(1, curve=cx.PLAIN_CURVE) < 30_000


class TestBands:
    def test_it_opens_at_level_one(self) -> None:
        # "Picklocking the chest has no level requirement", and upstream agrees.
        assert cx.methods(_VALID)["Thieving"][0].level == 1

    def test_nothing_where_the_map_cannot_reach_it(self) -> None:
        assert cx.methods({}) == {}
        assert cx.methods({"Thieving": {}}) == {}

    def test_a_band_names_the_task_it_would_be_overridden_through(self) -> None:
        for band in cx.methods(_VALID)["Thieving"]:
            assert band.knob == f"training/{cx.TASK}/Thieving"


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "coxchest.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(cx.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`coxchest.py`" in listing
