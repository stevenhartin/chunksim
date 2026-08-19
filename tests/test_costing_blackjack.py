"""Blackjacking, where one knockout buys two pickpockets and no stun at all."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import blackjack as bj
from chunksim.costing.gathering import CONFIRMED

#: `Thieving training`'s brews column, which is this model's oracle.
PUBLISHED: dict[int, float] = {
    45: 99_000.0,
    50: 103_000.0,
    55: 136_000.0,
    60: 140_000.0,
    65: 230_000.0,
    70: 236_000.0,
    75: 242_000.0,
    80: 247_000.0,
    85: 252_000.0,
    90: 257_000.0,
    95: 261_000.0,
    99: 265_000.0,
}

_ALL: dict[str, dict[str, object]] = {
    "Thieving": {target.task: {} for target in bj.TARGETS}
}


def _for(level: int) -> bj.Target:
    """The NPC `Thieving training` says to use at `level`."""
    return [target for target in bj.TARGETS if target.opens <= level][-1]


class TestTheCycleIsTheStatedOne:
    def test_every_action_is_two_ticks(self) -> None:
        # "The timing is right when the player receives experience drops every
        # two ticks."
        assert bj.ACTION_TICKS == 2.0
        assert bj.POCKETS_PER_KNOCKOUT == 2.0

    def test_a_missed_swing_costs_a_swing_and_nothing_else(self) -> None:
        """The page's own advice - "keep trying to knock them out again" - is
        what avoids the stun an awake pickpocket would take."""
        thug = bj.TARGETS[-1]
        certain = bj.ACTION_TICKS * (1.0 + bj.POCKETS_PER_KNOCKOUT)
        assert bj.cycle_ticks(thug, 99) > certain
        assert bj.cycle_ticks(thug, 99) < certain + bj.ACTION_TICKS

    def test_only_the_bandits_are_paid_for_the_knockout(self) -> None:
        """"Knocking out either bandit rewards 10 Thieving experience" - and
        the thug's page states nothing, which the ceiling confirms."""
        assert [target.knockout for target in bj.TARGETS] == [10.0, 10.0, 0.0]


class TestItLandsOnThePagesOwnCeiling:
    def test_a_thug_that_never_misses_is_the_stated_maximum(self) -> None:
        """"At maximum efficiency, it is possible to gain up to
        270,000-275,000 experience per hour at level 99" - two pickpockets at
        137.5 over six ticks, exactly."""
        assert bj.ceiling(bj.TARGETS[-1]) == 275_000.0

    def test_a_knockout_bonus_would_break_that(self) -> None:
        # Which is the reading that settles the thug's silent page: with 10
        # experience a knockout it would be 285,000 at perfect play.
        with_bonus = bj.TARGETS[-1]._replace(knockout=10.0)
        assert bj.ceiling(with_bonus) > 280_000.0


class TestThePublishedColumnIsTheOracle:
    """The model runs above it and tightens as the level climbs, which is what
    the page's own hidden comment says the shape should be: "lower levels scale
    down more to factor in that you fail more often and likely make more
    mistakes"."""

    @pytest.mark.parametrize("level", sorted(PUBLISHED))
    def test_it_is_never_under_and_never_wildly_over(self, level: int) -> None:
        ratio = bj.xp_per_hour(_for(level), level) / PUBLISHED[level]
        assert 1.0 <= ratio <= 1.2, level

    def test_the_residual_shrinks_with_the_level(self) -> None:
        ratios = [
            bj.xp_per_hour(_for(level), level) / PUBLISHED[level]
            for level in sorted(PUBLISHED)
        ]
        assert ratios == sorted(ratios, reverse=True)

    def test_the_top_is_within_two_percent(self) -> None:
        assert bj.xp_per_hour(_for(99), 99) / PUBLISHED[99] == pytest.approx(
            1.017, abs=0.005
        )

    def test_nothing_could_have_been_fitted_to_close_it(self) -> None:
        """**Why no fudge factor is carried.** A constant multiplier cannot
        produce a residual that shrinks from 16% to 2%, and neither can a
        constant overhead: solving the published column for extra ticks per
        cycle gives 1.14 at level 45 down to 0.10 at 99."""
        extra = []
        for level in sorted(PUBLISHED):
            target = _for(level)
            paid = bj.cycle_experience(target)
            extra.append(paid * bj.TICKS_PER_HOUR / PUBLISHED[level] - bj.cycle_ticks(target, level))
        assert max(extra) / min(extra) > 5.0


class TestItBeatsTheAwakeMethodEverywhere:
    """Which is the whole point: `costing/pickpocket.py` prices the awake
    pickpocket and nobody does that to these three."""

    def test_the_thug_is_worth_more_than_twice_its_awake_rate(self) -> None:
        from chunksim.costing import pickpocket

        awake = pickpocket.xp_per_hour(137.5, 99, 50.0, 160.0)
        assert bj.xp_per_hour(bj.TARGETS[-1], 99) > 2 * awake


class TestBands:
    def test_each_target_opens_where_upstream_gates_it(self) -> None:
        bands = bj.methods(_ALL)["Thieving"]
        opens = sorted({band.level for band in bands if band.level in (45, 55, 65)})
        assert opens == [45, 55, 65]

    def test_only_what_the_map_reaches(self) -> None:
        one: dict[str, dict[str, object]] = {"Thieving": {bj.TARGETS[0].task: {}}}
        knobs = {band.knob for band in bj.methods(one)["Thieving"]}
        assert knobs == {f"training/{bj.TARGETS[0].task}/Thieving"}

    def test_nothing_where_it_reaches_none(self) -> None:
        assert bj.methods({}) == {}
        assert bj.methods({"Thieving": {}}) == {}

    def test_every_term_is_published(self) -> None:
        for band in bj.methods(_ALL)["Thieving"]:
            assert band.match == CONFIRMED


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "blackjack.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(bj.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`blackjack.py`" in listing
