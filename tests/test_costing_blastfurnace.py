"""The Blast Furnace's two treadmills: a flat experience a tick, no curve."""

from __future__ import annotations

import pathlib

from chunksim.costing import blastfurnace as bf
from chunksim.costing.gathering import CONFIRMED

_PUMP, _PEDALS = bf.TREADMILLS
_VALID: dict[str, dict[str, object]] = {
    "Strength": {_PUMP.task: {}},
    "Agility": {_PEDALS.task: {}},
}


class TestEachPagesOwnArithmetic:
    def test_the_per_tick_figure_is_the_published_hourly_one(self) -> None:
        """Each page states the same arithmetic twice - "2 Strength experience
        every tick" and "12,000 experience per hour"; "1 xp" a tick and "up to
        6,000 Agility experience ... per hour". So `published_per_hour` is a
        check rather than a source, and this is what notices if the wiki ever
        rebalances one half without the other."""
        for mill in bf.TREADMILLS:
            assert mill.xp_per_hour == mill.published_per_hour

    def test_both_open_where_the_infoboxes_say(self) -> None:
        assert [mill.level for mill in bf.TREADMILLS] == [30, 30]

    def test_the_pedals_are_half_the_pump(self) -> None:
        """One experience a tick against two - the only thing separating them."""
        assert _PEDALS.xp_per_hour * 2 == _PUMP.xp_per_hour


class TestTheyAreFlat:
    def test_one_band_each_and_no_curve(self) -> None:
        """A hundred minutes between reclicks is a rounding error rather than a
        cadence, and neither object reads a level."""
        found = bf.methods(_VALID)
        assert [b.xp_per_hour for b in found["Strength"]] == [12_000.0]
        assert [b.xp_per_hour for b in found["Agility"]] == [6_000.0]

    def test_every_term_is_published(self) -> None:
        """Each is a ceiling - the pump on other players keeping the furnace
        stoked, the pedals on energy restoration items - but neither has an
        invented number in it."""
        found = bf.methods(_VALID)
        assert {b.match for bands in found.values() for b in bands} == {CONFIRMED}


class TestReachability:
    def test_nothing_where_the_map_cannot_reach_them(self) -> None:
        assert bf.methods({}) == {}
        assert bf.methods({"Strength": {}, "Agility": {}}) == {}

    def test_each_is_gated_on_its_own_challenge(self) -> None:
        """Upstream files the pump under Strength and the pedals under
        Agility, so a map can have derived one valid without the other."""
        only_pump = bf.methods({"Strength": {_PUMP.task: {}}})

        assert set(only_pump) == {"Strength"}

    def test_a_band_names_the_task_it_would_be_overridden_through(self) -> None:
        found = bf.methods(_VALID)
        assert found["Agility"][0].knob == f"training/{_PEDALS.task}/Agility"


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "blastfurnace.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(bf.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`blastfurnace.py`" in listing
