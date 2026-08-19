"""Repairing Motherlode Mine struts, where the rate is the world-hopping."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import strut as st
from chunksim.costing.gathering import GATHERING_MATCH, success_chance

_VALID: dict[str, dict[str, object]] = {"Smithing": {st.TASK: {}}}


class TestTheTableDividesOutToOneNumber:
    """**The finding, and the reason a level-independent constant is honest.**
    Dividing each published hourly figure by the published `1.5 x level` a
    repair pays leaves repairs an hour, and it barely moves - because what a
    player waits for is the hop, not the hammer."""

    def _implied(self, end: int) -> list[float]:
        return [
            band[end] / st.experience_per_repair(level)
            for level, band in sorted(st.PUBLISHED.items())
        ]

    def test_the_midpoints_agree_within_five_percent(self) -> None:
        implied = [
            (lo + hi) / 2 / st.experience_per_repair(level)
            for level, (lo, hi) in sorted(st.PUBLISHED.items())
        ]
        mean = sum(implied) / len(implied)
        assert (max(implied) - min(implied)) / 2 / mean < 0.05
        assert st.REPAIRS_PER_HOUR == pytest.approx(mean, abs=0.5)

    def test_and_so_do_both_ends_of_the_bands(self) -> None:
        for end in (0, 1):
            implied = self._implied(end)
            mean = sum(implied) / len(implied)
            assert (max(implied) - min(implied)) / 2 / mean < 0.09, end

    def test_the_midpoint_is_the_only_reading_that_fits_every_band(self) -> None:
        """The top-end mean overshoots level 90 - 418.3 repairs an hour is
        56,470 against a band that stops at 54,000."""
        top = self._implied(1)
        mean = sum(top) / len(top)
        assert not all(
            lo <= st.experience_per_repair(level) * mean <= hi
            for level, (lo, hi) in st.PUBLISHED.items()
        )


class TestItReproducesEveryPublishedBand:
    @pytest.mark.parametrize("level", sorted(st.PUBLISHED))
    def test_a_row(self, level: int) -> None:
        low, high = st.PUBLISHED[level]
        assert low <= st.xp_per_hour(level) <= high


class TestTheChartIsACheckAndNotASpend:
    def test_it_reproduces_the_pages_own_two_figures(self) -> None:
        """"12.11% at level 1 Smithing and 27.73% at level 99" - which is what
        says this is the right page's chart."""
        assert success_chance(1, *st.REPAIR_CURVE) == pytest.approx(0.1211, abs=0.0005)
        assert success_chance(99, *st.REPAIR_CURVE) == pytest.approx(0.2773, abs=0.0005)

    def test_the_rate_does_not_read_it(self) -> None:
        """A factor of 2.3 in success chance leaves no trace in the implied
        repairs an hour, because the hammering is already inside the table -
        charging it again would bill the same seconds twice."""
        assert st.xp_per_hour(99) / st.xp_per_hour(1) == pytest.approx(99.0)


class TestTheRegimeIsTheRotation:
    def test_standing_at_the_struts_is_an_order_of_magnitude_worse(self) -> None:
        """"A strut will break between 15 and 31 times an hour, giving an
        absolute maximum of 4,600 experience an hour at 99" - which is what
        the hopping buys."""
        assert st.STANDING_MAX_PER_HOUR == 4_600.0
        assert st.xp_per_hour(99) > 10 * st.STANDING_MAX_PER_HOUR


class TestBands:
    def test_it_opens_at_level_one(self) -> None:
        assert st.methods(_VALID)["Smithing"][0].level == 1

    def test_the_payout_climbs_and_the_repairs_do_not(self) -> None:
        bands = st.methods(_VALID)["Smithing"]
        rates = [band.xp_per_hour for band in bands]
        assert rates == sorted(rates)
        assert bands[-1].xp_per_hour / bands[0].xp_per_hour == pytest.approx(99.0)

    def test_nothing_where_the_map_cannot_reach_it(self) -> None:
        assert st.methods({}) == {}
        assert st.methods({"Smithing": {}}) == {}

    def test_a_borrowed_constant_is_not_claimed_as_measured(self) -> None:
        for band in st.methods(_VALID)["Smithing"]:
            assert band.match == GATHERING_MATCH

    def test_a_band_names_the_task_it_would_be_overridden_through(self) -> None:
        for band in st.methods(_VALID)["Smithing"]:
            assert band.knob == f"training/{st.TASK}/Smithing"


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "strut.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(st.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`strut.py`" in listing
