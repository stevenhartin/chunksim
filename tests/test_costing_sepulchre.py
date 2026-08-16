"""The Hallowed Sepulchre: five floors, and the one rate that stood for all."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import sepulchre as sp


class TestThePublishedTable:
    @pytest.mark.parametrize(
        "floor,level,no_loot,loot",
        [
            (1, 52, 40_000.0, 30_000.0),
            (2, 62, 50_000.0, 40_000.0),
            (3, 72, 71_700.0, 63_000.0),
            (4, 77, 81_000.0, 73_000.0),
            (5, 87, 98_500.0, 90_000.0),
        ],
    )
    def test_a_row_is_the_wikis(
        self, floor: int, level: int, no_loot: float, loot: float
    ) -> None:
        assert sp.level_for(floor) == level
        assert sp.rate_at(floor) == no_loot
        assert sp.rate_at(floor, looting=True) == loot

    def test_the_levels_are_the_exports_own(self) -> None:
        # 52, 62, 72, 77, 87 in both, which is what makes the floor-to-challenge
        # join structural rather than a guess at which one means which.
        assert [sp.level_for(f) for f in sorted(sp.FLOORS)] == [52, 62, 72, 77, 87]

    def test_looting_is_always_the_slower_column(self) -> None:
        for floor in sp.FLOORS:
            assert sp.rate_at(floor, looting=True) < sp.rate_at(floor)

    def test_every_floor_beats_the_one_below(self) -> None:
        rates = [sp.rate_at(f) for f in sorted(sp.FLOORS)]
        assert rates == sorted(rates)


class TestTheFlatRateItReplaced:
    """**Wrong in both directions, and the top one was the expensive half.**"""

    SCRAPED = 58_425.0

    def test_the_first_floor_was_over_by_half(self) -> None:
        assert self.SCRAPED / sp.rate_at(1) > 1.4

    def test_the_last_floor_was_under_by_two_thirds(self) -> None:
        # The fifth floor is the fastest Agility in the game from 87, and a
        # rate a third too low kept it out of the band walk entirely.
        assert sp.rate_at(5) / self.SCRAPED > 1.6

    def test_the_top_floor_beats_the_best_rooftop(self) -> None:
        # Ardougne is 70,000; if this ever stops being true the walk has
        # changed, not the wiki.
        assert sp.rate_at(5) > 70_000.0


class TestAFloorIsARateNotAStage:
    def test_the_floors_are_not_summed(self) -> None:
        # `Cumulative Exp` in the same table is what a run through all five
        # pays; the challenges are `Access the Nth floor`, each gated on its
        # own level, so the band walk wants the best rate open at each level.
        assert sp.rate_at(5) < sum(sp.rate_at(f) for f in sp.FLOORS)
        bands = sp.methods({"Agility": {t: {} for t in sp.TASKS.values()}})["Agility"]
        assert [b.xp_per_hour for b in bands] == [sp.rate_at(f) for f in sorted(sp.FLOORS)]


class TestReachability:
    _ALL: dict[str, dict[str, object]] = {
        "Agility": {task: {} for task in sp.TASKS.values()}
    }

    def test_every_floor_a_map_reaches(self) -> None:
        bands = sp.methods(self._ALL)["Agility"]
        assert [b.level for b in bands] == [52, 62, 72, 77, 87]

    def test_only_the_floors_it_reaches(self) -> None:
        one: dict[str, dict[str, object]] = {"Agility": {sp.TASKS[3]: {}}}
        bands = sp.methods(one)["Agility"]
        assert len(bands) == 1 and bands[0].level == 72

    def test_nothing_when_it_reaches_none(self) -> None:
        assert sp.methods({}) == {}
        assert sp.methods({"Agility": {}}) == {}

    def test_a_band_names_the_task_it_would_be_overridden_through(self) -> None:
        for band in sp.methods(self._ALL)["Agility"]:
            assert band.knob.startswith("training/Access the ")
            assert band.knob.endswith("/Agility")


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "sepulchre.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(sp.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`sepulchre.py`" in listing
