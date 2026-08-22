"""Cutting a leechfin: a knife action the wiki times in prose."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import leechfin
from chunksim.model.chunkinfo import ChunkInfo


def _valid() -> dict[str, dict[str, object]]:
    return {"Cooking": {leechfin.TASK: {}}}


class TestThePublishedTerms:
    def test_one_tick_and_twenty_experience(self) -> None:
        """"Subsequent leechfins will be automatically cut once per tick
        (which cannot be sped up), providing 20 Cooking experience each"."""
        assert (leechfin.CUT_TICKS, leechfin.EXPERIENCE) == (1.0, 20.0)

    def test_the_headline_is_not_the_answer(self) -> None:
        assert leechfin.xp_per_hour() == pytest.approx(120_000.0)


class TestTheFishIsTheWholeCost:
    def test_it_is_declared_per_experience(self) -> None:
        found = leechfin.material_seconds_per_xp(_valid(), lambda item, qty: 66.0)

        assert found == {leechfin.TASK: pytest.approx(66.0 / leechfin.EXPERIENCE)}

    def test_it_asks_for_the_fish_by_name(self) -> None:
        asked: list[str] = []

        def seconds(item: str, quantity: float) -> float:
            asked.append(item)
            return 1.0

        leechfin.material_seconds_per_xp(_valid(), seconds)

        assert asked == [leechfin.FISH]

    def test_an_unroutable_fish_declares_nothing(self) -> None:
        assert leechfin.material_seconds_per_xp(_valid(), lambda i, q: None) == {}

    def test_nothing_where_the_challenge_is_out_of_reach(self) -> None:
        assert leechfin.material_seconds_per_xp({}, lambda i, q: 1.0) == {}
        assert leechfin.methods({}) == {}
        assert leechfin.methods({"Cooking": {}}) == {}

    def test_it_is_charged_in_full_rather_than_at_the_stated_interruption(
        self,
    ) -> None:
        """The page says cutting "reduces experience rates by about 40% when
        fishing and cutting a full inventory", so a player doing both loses
        part of a catch rather than all of one - and nothing states how the
        two interleave. Billing the whole catch is the conservative reading,
        the same call `costing/stated.py` makes for the moss lizard's cook."""
        whole = leechfin.material_seconds_per_xp(_valid(), lambda i, q: 100.0)
        assert whole[leechfin.TASK] == pytest.approx(100.0 / leechfin.EXPERIENCE)


class TestTheBand:
    def test_one_band_at_upstreams_level(self) -> None:
        (band,) = leechfin.methods(_valid())["Cooking"]

        assert band.level == leechfin.OPENS_AT
        assert band.knob == f"training/{leechfin.TASK}/Cooking"


class TestItIsWiredIn:
    def test_inputs_calls_both_halves(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "leechfin.methods(" in source
        assert "leechfin.material_seconds_per_xp(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(leechfin.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`leechfin.py`" in listing

    @pytest.mark.real_export
    def test_upstream_names_a_loot_table_and_eats_the_fish(
        self, real_export: ChunkInfo
    ) -> None:
        """Why no recipe joins: `Leechfin loot` is a bundle the wiki has no
        page for - `costing/fishcutting.py`'s shape without its fallback."""
        entry = real_export.challenges["Cooking"].get(leechfin.TASK)

        assert isinstance(entry, dict)
        assert entry.get("Primary") is True
        assert entry.get("Level") == leechfin.OPENS_AT
        assert str(entry.get("Output") or "").endswith(" loot")
        assert f"{leechfin.FISH}*" in (entry.get("Items") or ())
