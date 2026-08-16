"""Stealing artefacts: eleven published rows, reproduced with no residual."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import artefacts as af


class TestItReproducesThePublishedTable:
    """**The whole case for this module, and it is exact.**

    The wiki's `Base rate` column at eleven levels, against two prose figures
    and a table of six run times. Not "within a few percent" - equal.
    """

    PUBLISHED = {
        49: 130_080.0, 55: 141_600.0, 60: 151_200.0, 65: 160_800.0,
        70: 170_400.0, 75: 180_000.0, 80: 189_600.0, 85: 199_200.0,
        90: 208_800.0, 95: 218_400.0, 99: 226_080.0,
    }

    @pytest.mark.parametrize("level,published", sorted(PUBLISHED.items()))
    def test_a_row_comes_out_exactly(self, level: int, published: float) -> None:
        assert af.rate_at(level) == pytest.approx(published)

    def test_every_row_and_not_just_the_ends(self) -> None:
        # A linear model can be made to hit two points; hitting eleven is the
        # claim being made here.
        assert len(self.PUBLISHED) == 11
        assert all(
            af.rate_at(level) == pytest.approx(paid)
            for level, paid in self.PUBLISHED.items()
        )


class TestTheTwoHalvesOfAnArtefact:
    def test_the_lock_and_the_hand_in(self) -> None:
        # "Successfully picking the lock grants 750 Thieving experience" and
        # "additional ... equal to 40 times the current Thieving level".
        assert af.experience_per_artefact(49) == 750.0 + 40.0 * 49
        assert af.experience_per_artefact(99) == 4_710.0

    def test_the_level_enters_nowhere_else(self) -> None:
        # The lock does not get easier and the run does not get shorter, so
        # the rate is linear and the run count is level-free.
        assert af.artefacts_per_hour() == af.artefacts_per_hour()
        doubled = af.experience_per_artefact(99) / af.experience_per_artefact(49)
        assert af.rate_at(99) / af.rate_at(49) == pytest.approx(doubled)


class TestTheRunCount:
    def test_the_six_house_times_give_the_stated_forty_eight(self) -> None:
        # 1:00 to 1:30, averaging 75 seconds, against "approximately 48".
        assert af.artefacts_per_hour() == pytest.approx(48.0)

    def test_the_teleported_times_give_the_stated_fifty_five(self) -> None:
        # The other end of the page's "approximately 48 to 55", from the same
        # table with the Book of the Dead column.
        assert af.artefacts_per_hour(af.HOUSE_SECONDS_TELEPORTED) == pytest.approx(
            55.4, abs=0.1
        )

    def test_it_is_the_mean_and_not_the_best_house(self) -> None:
        # **You are told which house to rob.** Taking the quickest would read
        # 60 an hour and miss the published column by a quarter.
        best = af.artefacts_per_hour([min(af.HOUSE_SECONDS)])
        assert best > af.artefacts_per_hour()
        assert best == pytest.approx(60.0)

    def test_the_teleported_regime_is_not_the_one_priced(self) -> None:
        # It needs `The Queen of Thieves`, which the export's challenge does
        # not require, so pricing it would charge every map for a quest it may
        # not have done.
        assert af.rate_at(99) < af.rate_at(99, af.HOUSE_SECONDS_TELEPORTED)
        assert af.rate_at(99) == pytest.approx(226_080.0)


class TestTheGate:
    def test_it_opens_at_forty_nine(self) -> None:
        # "requiring level 49 Thieving to participate", and the export agrees.
        assert af.OPENS_AT == 49
        assert af.rate_at(48) == 0.0
        assert af.rate_at(49) > 0.0


class TestReachability:
    _VALID: dict[str, dict[str, object]] = {"Thieving": {af.TASK: {}}}

    def test_it_is_offered_where_the_task_is_valid(self) -> None:
        bands = af.methods(self._VALID)["Thieving"]
        levels = [band.level for band in bands]
        assert levels[0] == 49
        assert all(level is not None and level >= 49 for level in levels)

    def test_the_bands_climb(self) -> None:
        rates = [b.xp_per_hour for b in af.methods(self._VALID)["Thieving"]]
        assert rates == sorted(rates)
        assert len(rates) > 4

    def test_nothing_when_it_is_not(self) -> None:
        assert af.methods({}) == {}
        assert af.methods({"Thieving": {}}) == {}

    def test_a_band_names_the_task_it_would_be_overridden_through(self) -> None:
        for band in af.methods(self._VALID)["Thieving"]:
            assert band.knob == f"training/{af.TASK}/Thieving"


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "artefacts.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(af.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`artefacts.py`" in listing
