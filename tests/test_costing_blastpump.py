"""The Blast Furnace pump: two Strength experience a tick, and nothing else."""

from __future__ import annotations

import pathlib

from chunksim.costing import blastpump as bp
from chunksim.costing.gathering import CONFIRMED

_VALID: dict[str, dict[str, object]] = {"Strength": {bp.TASK: {}}}


class TestThePagesOwnArithmetic:
    def test_two_a_tick_is_the_published_hourly_figure(self) -> None:
        """"Operating the pump yields 2 Strength experience every tick" and it
        "is used to train Strength for 12,000 experience per hour" - the same
        arithmetic stated twice, so there is nothing here to fit."""
        assert bp.EXPERIENCE_PER_TICK * bp.TICKS_PER_HOUR == 12_000.0
        assert bp.xp_per_hour() == 12_000.0

    def test_it_opens_where_the_infobox_says(self) -> None:
        assert bp.LEVEL == 30


class TestItIsFlat:
    def test_one_band_and_no_curve(self) -> None:
        """A hundred minutes between reclicks is a rounding error rather than
        a cadence, and nothing about the pump reads a level - which makes this
        one of very few methods whose rate does not move at all."""
        bands = bp.methods(_VALID)["Strength"]
        assert len(bands) == 1
        assert bands[0].xp_per_hour == 12_000.0

    def test_every_term_is_published(self) -> None:
        # What is unmodelled is a dependency on other players keeping the
        # furnace stoked, not an invented number.
        assert bp.methods(_VALID)["Strength"][0].match == CONFIRMED


class TestReachability:
    def test_nothing_where_the_map_cannot_reach_it(self) -> None:
        assert bp.methods({}) == {}
        assert bp.methods({"Strength": {}}) == {}

    def test_a_band_names_the_task_it_would_be_overridden_through(self) -> None:
        assert bp.methods(_VALID)["Strength"][0].knob == f"training/{bp.TASK}/Strength"


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "blastpump.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(bp.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`blastpump.py`" in listing
