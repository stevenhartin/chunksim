"""Tempoross: the wiki's table, and the guess it replaced."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import tempoross as tp
from chunksim.costing.gathering import GUESS


class TestThePublishedTable:
    """Twenty cells, `Not cooking`, read rather than invented."""

    @pytest.mark.parametrize(
        "harpoon,level,paid",
        [
            ("Harpoon", 35, 30_000.0),
            ("Harpoon", 70, 62_000.0),
            ("Harpoon", 99, 74_000.0),
            ("Dragon harpoon", 70, 66_000.0),
            ("Dragon harpoon", 99, 74_000.0),
            ("Crystal harpoon", 71, 77_000.0),
            ("Crystal harpoon", 99, 95_000.0),
            ("Infernal harpoon", 80, 71_000.0),
            ("Infernal harpoon", 99, 76_000.0),
        ],
    )
    def test_a_cell_is_the_wikis(
        self, harpoon: str, level: int, paid: float
    ) -> None:
        assert tp.harpoon_rate(harpoon, level) == paid

    def test_the_barb_tail_shares_the_plain_row(self) -> None:
        # "the standard harpoon, the barb-tail harpoon, and Barbarian Fishing
        # all have the same experience rates".
        assert tp.RATES["Barb-tail harpoon"] == tp.RATES["Harpoon"]

    def test_a_point_holds_until_the_next(self) -> None:
        assert tp.harpoon_rate("Harpoon", 69) == 30_000.0
        assert tp.harpoon_rate("Harpoon", 70) == 62_000.0


class TestTheHarpoonGates:
    """The items' own requirements, and the table's `N/A` cells check them."""

    @pytest.mark.parametrize(
        "harpoon,needs",
        [
            ("Harpoon", 1),
            ("Barb-tail harpoon", 1),
            ("Dragon harpoon", 61),
            ("Crystal harpoon", 71),
            ("Infernal harpoon", 75),
        ],
    )
    def test_a_gate_is_the_items(self, harpoon: str, needs: int) -> None:
        assert tp.RATES[harpoon][0] == needs

    def test_a_harpoon_pays_nothing_below_its_level(self) -> None:
        # Which is exactly where the wiki's table goes N/A.
        assert tp.harpoon_rate("Dragon harpoon", 35) == 0.0
        assert tp.harpoon_rate("Infernal harpoon", 70) == 0.0
        assert tp.harpoon_rate("Crystal harpoon", 35) == 0.0


class TestBestByRateNotByTier:
    """The tiers are not ordered, so a tier list would encode it twice."""

    ALL = frozenset(tp.RATES)

    def test_infernal_beats_dragon_and_loses_to_crystal(self) -> None:
        assert tp.harpoon_rate("Dragon harpoon", 99) < tp.harpoon_rate(
            "Infernal harpoon", 99
        )
        assert tp.harpoon_rate("Infernal harpoon", 99) < tp.harpoon_rate(
            "Crystal harpoon", 99
        )

    def test_the_best_held_is_chosen(self) -> None:
        assert tp.best_harpoon(99, self.ALL) == ("Crystal harpoon", 95_000.0)
        assert tp.best_harpoon(
            99, frozenset({"Harpoon", "Dragon harpoon"})
        ) == ("Dragon harpoon", 74_000.0)

    def test_a_lesser_harpoon_is_not_upgraded(self) -> None:
        # The best tier *held*, the reading `gathering.best_tool` takes.
        assert tp.best_harpoon(99, frozenset({"Harpoon"})) == ("Harpoon", 74_000.0)

    def test_a_harpoon_it_cannot_wield_yet_is_skipped(self) -> None:
        # A crystal harpoon in a reachable chunk is not one at level 60.
        assert tp.best_harpoon(60, self.ALL)[0] in {"Harpoon", "Barb-tail harpoon"}
        assert tp.rate_at(60, self.ALL) == 30_000.0

    def test_no_harpoon_prices_nothing(self) -> None:
        assert tp.rate_at(99, frozenset()) == 0.0
        assert tp.best_harpoon(99, frozenset()) == ("", 0.0)


class TestTheGuessItReplaced:
    """**Both directions of the error, so neither can come back quietly.**"""

    def test_a_plain_harpoon_at_the_bottom_was_nearly_three_times_over(self) -> None:
        # `stated.py` said 80,000 flat for a plain harpoon at every level.
        assert tp.harpoon_rate("Harpoon", 35) == 30_000.0
        assert 80_000.0 / tp.harpoon_rate("Harpoon", 35) > 2.5

    def test_crystal_and_infernal_are_not_one_number(self) -> None:
        # They were lumped together at 100,000.
        assert tp.harpoon_rate("Crystal harpoon", 99) != tp.harpoon_rate(
            "Infernal harpoon", 99
        )
        assert tp.harpoon_rate("Crystal harpoon", 99) > tp.harpoon_rate(
            "Infernal harpoon", 99
        )

    def test_nothing_reaches_the_old_top_figure(self) -> None:
        assert max(
            tp.harpoon_rate(harpoon, 99) for harpoon in tp.RATES
        ) < 100_000.0

    def test_it_is_no_longer_a_guess(self) -> None:
        from chunksim.costing import stated

        assert not hasattr(stated, "tempoross_rate")
        found = tp.methods({"Fishing": {tp.TASK: {}}}, frozenset({"Harpoon"}))
        assert {band.match for band in found["Fishing"]} == {"confirmed"}


class TestWhyItIsNotDerived:
    """The formulas check the shape and cannot produce the rate."""

    @staticmethod
    def _base(level: int) -> int:
        import math

        if level < 70:
            return math.floor(450 + 550 * (level - 35) / 64)
        return math.floor(890 + 110 * (level - 70) / 29)

    def test_the_action_formulas_are_exact_at_both_ends(self) -> None:
        assert self._base(35) == 450
        assert self._base(70) == 890
        assert self._base(99) == 1000

    def test_the_rate_is_not_proportional_to_them(self) -> None:
        # If the count of actions were level-free the ratio would be flat. It
        # climbs, so the catching gets faster too and nothing publishes that.
        ratios = [
            tp.harpoon_rate("Harpoon", level) / self._base(level)
            for level in (35, 70, 90, 99)
        ]
        assert ratios == sorted(ratios)
        assert ratios[-1] / ratios[0] > 1.05


class TestReachability:
    _VALID: dict[str, dict[str, object]] = {"Fishing": {tp.TASK: {}}}
    ALL = frozenset(tp.RATES)

    def test_it_is_offered_where_the_task_is_valid(self) -> None:
        bands = tp.methods(self._VALID, self.ALL)["Fishing"]
        assert bands[0].level == tp.OPENS_AT == 35

    def test_the_harpoon_is_rechosen_at_every_band(self) -> None:
        # A map holding a crystal harpoon swings a plain one until 71, which is
        # a real band edge rather than a rounding.
        bands = tp.methods(self._VALID, self.ALL)["Fishing"]
        named = {band.level: band.method for band in bands}
        assert "harpoon)" in named[40]
        assert "crystal" in named[80]

    def test_nothing_when_it_is_not_reachable(self) -> None:
        assert tp.methods({}, self.ALL) == {}
        assert tp.methods(self._VALID, frozenset()) == {}


class TestItIsWiredIn:
    def test_inputs_calls_it_with_the_reachable_set(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "tempoross.methods(" in source
        call = source.split("tempoross.methods(", 1)[1].split(").items()", 1)[0]
        assert "available_items" in call

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(tp.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`tempoross.py`" in listing


class TestTheCookingRegime:
    """The other half of the wiki's two tables, counted rather than tabulated."""

    _VALID = {tp.COOKING_SKILL: {tp.COOKING_TASK: 1}}

    def test_the_fish_are_counted_out_of_the_walkthrough(self) -> None:
        """17 then 19 to finish phase one - the page calls that "the 36 needed
        for the first phase" - and 19 in phase two. Phase three cooks none; it
        is spent dousing fires."""
        assert tp.FISH_PER_GAME == 55

    def test_five_games_an_hour_is_the_pages_own_permit_arithmetic(self) -> None:
        """A game is "around 12 minutes" and yields 14-18 permits, "an average
        game yields 15-16", for "roughly 75-80 permits per hour" - so 15.5 into
        77.5 is exactly five, and the twelve already includes the wait."""
        assert tp.GAMES_PER_HOUR == pytest.approx(77.5 / 15.5)

    def test_the_rate_is_the_product_of_three_published_numbers(self) -> None:
        assert tp.cooking_xp_per_hour() == pytest.approx(5 * 55 * 10)

    def test_it_is_flat_because_the_shrine_cannot_burn(self) -> None:
        """One band, at upstream's own level. What gates this is reaching
        Tempoross, which is Fishing's business rather than Cooking's."""
        (band,) = tp.cooking_methods(self._VALID)[tp.COOKING_SKILL]

        assert band.level == tp.COOKING_OPENS_AT == 1
        assert band.xp_per_hour == tp.cooking_xp_per_hour()

    def test_the_two_challenges_are_two_choices(self) -> None:
        """A player cooking gets less Fishing than the not-cooking table says,
        but the export has one challenge for each skill and a climb takes the
        best it is offered - so pricing the cooking regime's Fishing as well
        would only offer a worse number for a skill that already has one."""
        assert tp.SKILL not in tp.cooking_methods(self._VALID)

    def test_a_map_that_cannot_reach_it_gets_nothing(self) -> None:
        assert tp.cooking_methods({"Cooking": {}}) == {}


class TestTheRepairsAreAGuessAroundPublishedTerms:
    """The one regime in this module resting on an invented number, and the
    only one whose bands are `GUESS` because of it."""

    _VALID = {"Construction": {tp.CONSTRUCTION_TASK: True}}

    def test_the_experience_is_four_times_the_level_not_the_forty_points(self) -> None:
        """The reward table's 40 is under a column headed `Points` - dousing a
        fire pays the same 40 and no experience at all. `Mast (Tempoross)`
        states the experience twice: in prose and in its `{{Skill info}}`."""
        assert tp.REPAIR_XP_PER_LEVEL == 4.0

    def test_the_rate_is_twenty_times_the_level(self) -> None:
        """`4 x level` a repair, one repair a game, five games an hour."""
        assert tp.construction_xp_per_hour(99) == pytest.approx(1_980.0)
        assert tp.construction_xp_per_hour(1) == pytest.approx(20.0)

    def test_it_scales_with_construction_where_cooking_is_flat(self) -> None:
        """A repair pays `4 x level` whoever swings the hammer, so unlike the
        cooking regime beside it this is a curve rather than one number."""
        assert tp.construction_xp_per_hour(80) == pytest.approx(
            2 * tp.construction_xp_per_hour(40)
        )

    def test_the_bands_are_marked_a_guess(self) -> None:
        """One invented factor makes the product invented, however published
        the other two are."""
        bands = tp.construction_methods(self._VALID)["Construction"]

        assert bands
        assert {band.match for band in bands} == {GUESS}

    def test_nothing_where_the_challenge_is_unreachable(self) -> None:
        """Upstream's own challenge carries the house the wiki requires."""
        assert tp.construction_methods({}) == {}


class TestTinyTemporLoot:
    """The Tiny Tempor pet - see the module docstring's own "Tiny tempor"
    section for the citations behind each figure."""

    def test_the_per_roll_chance_is_published(self) -> None:
        assert tp.TINY_TEMPOR_CHANCE_PER_ROLL == pytest.approx(1.0 / 8000.0)

    def test_permits_per_game_matches_the_pages_own_figure(self) -> None:
        assert tp.PERMITS_PER_GAME == pytest.approx(15.5)

    def test_item_seconds_reuses_the_max_permits_games_per_hour(self) -> None:
        priced = tp.item_seconds()
        assert set(priced) == {"Tiny tempor"}
        expected_chance = tp.PERMITS_PER_GAME * tp.TINY_TEMPOR_CHANCE_PER_ROLL
        expected_seconds = 3600.0 / (tp.GAMES_PER_HOUR * expected_chance)
        assert priced["Tiny tempor"] == pytest.approx(expected_seconds)

    def test_the_wait_is_tens_to_hundreds_of_hours(self) -> None:
        hours = tp.item_seconds()["Tiny tempor"] / 3600.0
        assert 10.0 < hours < 1000.0, hours
