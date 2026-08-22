"""The toy mouse: a charted chance, a published payout, an invented cadence."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import toymouse as tm
from chunksim.model.chunkinfo import ChunkInfo


class TestTheChartReproducesJagexsOwnFigures:
    """**One of the few charts on the wiki with a developer statement beside
    it.** Mod Ash: "Mouse: 24% - 98%.... Those figures are for level 1 and
    level 99; interpolate linearly between them." So this is the chart being
    checked against its source rather than this project being checked against
    the chart - the shape `costing/wallsafe.py` has."""

    def test_level_one_is_twenty_four_percent(self) -> None:
        assert tm.catch_chance(1) == pytest.approx(0.24, abs=0.005)

    def test_level_ninety_nine_is_ninety_eight_percent(self) -> None:
        assert tm.catch_chance(99) == pytest.approx(0.98, abs=0.005)

    def test_it_interpolates_between_them(self) -> None:
        chances = [tm.catch_chance(level) for level in range(1, 100)]
        assert chances == sorted(chances)
        assert chances[0] < chances[49] < chances[-1]


class TestThePayout:
    def test_a_catch_pays_three(self) -> None:
        assert tm.EXPERIENCE == 3.0

    def test_a_failure_pays_nothing(self) -> None:
        """**The 2013 change is why this is a bad method rather than a good
        one.** It used to pay 15 "whether you caught it or not", which is what
        made spamming it fast; `{{Agility info}}` states no `failxp` now, so
        the chance multiplies the whole rate."""
        assert tm.xp_per_hour(1) == pytest.approx(
            tm.EXPERIENCE * tm.catch_chance(1) * tm.TICKS_PER_HOUR / tm.CATCH_TICKS
        )
        # If failures paid, the level-1 and level-99 rates would be closer
        # together than fourfold.
        assert tm.xp_per_hour(99) / tm.xp_per_hour(1) > 4.0


class TestTheOneInventedNumber:
    """**The whole denominator**, which is the opposite of
    `costing/skullball.py` - there the published lap dominates and the guess
    moves the answer by a quarter, here the rate is directly proportional to
    it."""

    def test_the_rate_is_proportional_to_it(self) -> None:
        assert tm.xp_per_hour(99, ticks=5.0) == pytest.approx(
            2.0 * tm.xp_per_hour(99, ticks=10.0)
        )

    def test_the_plausible_range_is_threefold(self) -> None:
        fast = tm.xp_per_hour(99, ticks=5.0)
        slow = tm.xp_per_hour(99, ticks=15.0)
        assert fast == pytest.approx(3_530.0, abs=1.0)
        assert slow == pytest.approx(1_177.0, abs=1.0)

    def test_the_whole_range_still_loses_to_every_opening_band(self) -> None:
        """**Why the guess is safe anyway.** The every-rollable-chunk map
        opens Agility at 15,000/hr and the second cache at 10,835, so nothing
        in the plausible range can decide a band - which is what buys coverage
        without buying an answer."""
        worst_opening_band = 10_000.0
        for ticks in (5.0, 8.0, 10.0, 12.0, 15.0):
            assert tm.xp_per_hour(99, ticks=ticks) < worst_opening_band

    def test_a_zero_cycle_is_not_infinite(self) -> None:
        assert tm.xp_per_hour(99, ticks=0.0) == 0.0

    def test_what_a_plausible_looking_figure_would_need(self) -> None:
        """Recorded because 429/hr looks low enough to read as a bug: 5,000/hr
        at 3 experience a catch is 1,667 catches an hour, or one every 2.2
        seconds including the wind and the release."""
        catches = 5_000.0 / tm.EXPERIENCE
        assert 3_600.0 / catches == pytest.approx(2.16, abs=0.02)


class TestTheBands:
    _VALID: dict[str, dict[str, object]] = {"Agility": {tm.TASK: {}}}

    def test_it_opens_at_level_one(self) -> None:
        bands = tm.methods(self._VALID)["Agility"]
        assert min(b.level for b in bands if b.level is not None) == 1

    def test_it_is_banded_because_the_chance_climbs_fourfold(self) -> None:
        bands = tm.methods(self._VALID)["Agility"]
        rates = [b.xp_per_hour for b in bands]
        assert rates == sorted(rates)
        assert len(rates) > 1
        assert rates[-1] / rates[0] > 4.0

    def test_every_band_is_a_guess(self) -> None:
        from chunksim.costing.gathering import GUESS

        assert {b.match for b in tm.methods(self._VALID)["Agility"]} == {GUESS}

    def test_nothing_when_unreachable(self) -> None:
        assert tm.methods({}) == {}
        assert tm.methods({"Agility": {}}) == {}

    def test_the_bands_name_their_own_task(self) -> None:
        knobs = {b.knob for b in tm.methods(self._VALID)["Agility"]}
        assert knobs == {f"training/{tm.TASK}/Agility"}


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "toymouse.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(tm.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`toymouse.py`" in listing

    @pytest.mark.real_export
    def test_upstream_holds_the_toy_rather_than_spending_it(
        self, real_export: ChunkInfo
    ) -> None:
        """**No material cost, and upstream says so in its own notation.** A
        `*` marks what an action consumes; `Toy mouse` carries none, which
        agrees with the page - only a cat eats one."""
        entry = real_export.challenges["Agility"].get(tm.TASK)
        assert isinstance(entry, dict)
        assert entry.get("Primary") is True
        assert entry.get("Level") == tm.OPENS_AT
        assert list(entry.get("Items") or ()) == ["Toy mouse"]

    def test_it_was_agilitys_last_unpriced_method(self) -> None:
        """**The end of a long stretch**, and the reason to pin it by name:
        the export census reads `Agility 96 modelled, 1 pinned, 9 guessed, 0
        unpriced, 4 refused, 1 one-off, 10 uncompletable` of 121, from
        72/1/0/28/0/0 when it started. A rate here at all is what closes it,
        whatever the cadence turns out to be."""
        assert tm.methods({"Agility": {tm.TASK: {}}})["Agility"]
