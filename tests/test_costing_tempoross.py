"""Tempoross: the wiki's table, and the guess it replaced."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import tempoross as tp


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
