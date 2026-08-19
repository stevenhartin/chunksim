"""Smashing a calcified deposit, the Smithing third of Cam Torum mining."""

from __future__ import annotations

import pathlib

from chunksim.costing import calcified as ca
from chunksim.costing.gathering import CONFIRMED

_VALID: dict[str, dict[str, object]] = {"Smithing": {ca.TASK: {}}}


class TestThePagesOwnFigures:
    def test_one_experience_in_three_ticks(self) -> None:
        """"This process provides 1 Smithing experience and takes 3 ticks per
        deposit", and the `{{Skill info}}` says the same in fields."""
        assert (ca.EXPERIENCE, ca.TICKS, ca.LEVEL) == (1.0, 3.0, 1)
        assert ca.xp_per_hour() == 2_000.0

    def test_the_shard_yield_is_carried_and_not_spent(self) -> None:
        """"On average, each deposit gives 7.5 shards" - the reason anybody
        smashes one, and Prayer experience rather than Smithing, which
        `effective_xp_per_hour` will not credit across skills."""
        assert ca.SHARDS_PER_DEPOSIT == 7.5


class TestItIsTheActionsRateNotTheSupplys:
    def test_the_headline_ignores_how_rare_a_deposit_is(self) -> None:
        """A deposit is a 1/75 roll off a successful mine, so 2,000/hr is a
        ceiling - and the machinery that charges the mining behind it already
        exists (`yields.py` prices the deposit, `effective_xp_per_hour` spends
        it). What this module adds is the numerator."""
        assert ca.xp_per_hour() == ca.EXPERIENCE * ca.TICKS_PER_HOUR / ca.TICKS

    def test_it_is_flat(self) -> None:
        bands = ca.methods(_VALID)["Smithing"]
        assert len(bands) == 1 and bands[0].level == 1

    def test_every_term_is_published(self) -> None:
        assert ca.methods(_VALID)["Smithing"][0].match == CONFIRMED


class TestReachability:
    def test_nothing_where_the_map_cannot_reach_it(self) -> None:
        assert ca.methods({}) == {}
        assert ca.methods({"Smithing": {}}) == {}

    def test_a_band_names_the_task_it_would_be_overridden_through(self) -> None:
        assert ca.methods(_VALID)["Smithing"][0].knob == f"training/{ca.TASK}/Smithing"


class TestTheMiningThirdIsAlreadyModelled:
    def test_the_rocks_carry_a_recovered_curve(self) -> None:
        """`Pay-to-play Mining training`'s own table, read through the model -
        50,344/hr against its published 49,000 at level 99."""
        from chunksim.costing.gathering import PROFILES

        assert "calcified rocks" in PROFILES["Mining"].stated_curves


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "calcified.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(ca.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`calcified.py`" in listing
