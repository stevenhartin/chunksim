"""Chipping a blessed bone statuette: an hour of somebody else's minigame."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import statuette as st
from chunksim.model.chunkinfo import ChunkInfo


def _valid() -> dict[str, dict[str, object]]:
    return {"Crafting": {st.TASK: {}}, "Thieving": {st.GATE_TASK: {}}}


class TestEveryTermIsPublishedAndNoneIsCraftings:
    def test_a_chip_pays_five(self) -> None:
        """"Players may break them down with a chisel to obtain 125 blessed
        bone shards ... and 5 Crafting experience"."""
        assert st.EXPERIENCE == 5.0

    def test_the_share_is_three_statuettes_at_one_in_five_hundred(self) -> None:
        """Upstream's `Varlamore thieving` table: `3/520.8`, being the eagle,
        fox and buffalo at 1/520.8 each."""
        assert st.STATUETTES_PER_VALUABLE == pytest.approx(3.0 / 520.8)

    def test_the_throughput_is_the_wikis_band(self) -> None:
        """"About 1,600-2,300 valuables from 18-19 houses per hour"."""
        assert st.VALUABLES_PER_HOUR == (1_600.0, 2_300.0)

    def test_the_low_end_is_what_is_carried(self) -> None:
        """`costing/pyramid.py`'s rule for a range the page hedges."""
        assert st.xp_per_hour() == st.xp_per_hour(st.VALUABLES_PER_HOUR[0])
        assert st.xp_per_hour() < st.xp_per_hour(st.VALUABLES_PER_HOUR[1])

    def test_the_band_multiplies_out_to_forty_six(self) -> None:
        assert st.xp_per_hour(1_600.0) == pytest.approx(46.08, abs=0.01)
        assert st.xp_per_hour(2_300.0) == pytest.approx(66.24, abs=0.01)

    def test_the_statuette_count_is_the_middle_step(self) -> None:
        assert st.statuettes_per_hour(1_600.0) == pytest.approx(9.22, abs=0.01)


class TestWhatItDeliberatelyDoesNot:
    def test_it_declares_no_material_cost(self) -> None:
        """The statuettes-an-hour figure already *is* an hour of the minigame,
        so charging the thieving again would bill the same hour twice - the
        trap `costing/gotr.py` fell into."""
        assert not hasattr(st, "material_seconds_per_xp")

    def test_it_is_gated_on_the_thieving_challenge(self) -> None:
        """The Crafting copy carries no chunk and no Thieving 50; upstream
        states both on the minigame's own challenge."""
        assert st.methods({"Crafting": {st.TASK: {}}}) == {}

    def test_nothing_when_the_chip_itself_is_out_of_reach(self) -> None:
        assert st.methods({"Thieving": {st.GATE_TASK: {}}}) == {}
        assert st.methods({}) == {}


class TestTheBand:
    def test_one_band_at_upstreams_level(self) -> None:
        (band,) = st.methods(_valid())["Crafting"]

        assert band.level == st.OPENS_AT == 1
        assert band.knob == f"training/{st.TASK}/Crafting"

    def test_it_is_slow_enough_to_decide_nothing(self) -> None:
        """Carried because every term is published, not because it competes:
        `unpriced` is the wrong word for a method whose rate is known."""
        (band,) = st.methods(_valid())["Crafting"]

        assert band.xp_per_hour < 100.0


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "statuette.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(st.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`statuette.py`" in listing

    @pytest.mark.real_export
    def test_the_share_and_the_roll_unit_are_upstreams_own(
        self, real_export: ChunkInfo
    ) -> None:
        """**The roll unit is one valuable**, which is what makes the wiki's
        valuables-an-hour the right multiplier: `Valuables` is the table's
        `Always` member."""
        table = real_export.data["skillItems"]["Thieving"]["Varlamore thieving"]

        assert table["Blessed bone statuette"] == {"1": "3/520.8"}
        assert table["Valuables"] == {"1": "Always"}

    @pytest.mark.real_export
    def test_both_challenges_exist_and_only_one_states_the_gate(
        self, real_export: ChunkInfo
    ) -> None:
        chip = real_export.challenges["Crafting"].get(st.TASK)
        game = real_export.challenges["Thieving"].get(st.GATE_TASK)

        assert isinstance(chip, dict) and chip.get("Primary") is True
        assert isinstance(game, dict) and game.get("Primary") is True
        assert not chip.get("Chunks")
        assert game.get("Chunks") and game.get("Level") == 50
