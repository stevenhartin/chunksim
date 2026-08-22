"""The Crafting half of mining dense essence."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import denserunestone as dr
from chunksim.costing.heuristics import ComputedMethod
from chunksim.model.chunkinfo import ChunkInfo


def _band(level: int, rate: float, knob: str | None = None) -> ComputedMethod:
    return ComputedMethod(
        method="dense essence block",
        xp_per_hour=rate,
        level=level,
        match="modelled",
        knob=knob or f"training/{dr.TASK}/Mining",
    )


def _valid() -> dict[str, dict[str, object]]:
    return {"Crafting": {dr.TASK: {}}}


class TestThePublishedPair:
    def test_the_wiki_states_both_experiences(self) -> None:
        """`{{Skill info}}` on `Dense runestone`: Mining 12, Crafting 8, both
        at level 38, on a 9-tick swing."""
        assert (dr.MINING_EXPERIENCE, dr.CRAFTING_EXPERIENCE) == (12.0, 8.0)
        assert dr.LEVEL == 38
        assert dr.STATED_TICKS == 9

    def test_the_share_is_the_ratio_of_the_two(self) -> None:
        assert dr.share() == pytest.approx(8.0 / 12.0)


class TestItScalesRatherThanRecomputes:
    def test_a_band_is_the_mining_one_times_the_share(self) -> None:
        (found,) = dr.methods([_band(38, 17_788.235294117647)], _valid())["Crafting"]

        assert found.xp_per_hour == pytest.approx(11_858.82, abs=0.01)

    def test_the_whole_curve_comes_through(self) -> None:
        """Which is why this reads the model's answer rather than reproducing
        it: the Mining bands already carry the runestone's persistence chart."""
        bands = dr.methods([_band(38, 10_000.0), _band(70, 20_000.0)], _valid())

        assert [b.level for b in bands["Crafting"]] == [38, 70]
        assert [b.match for b in bands["Crafting"]] == ["modelled", "modelled"]

    def test_nine_ticks_alone_would_be_a_different_answer(self) -> None:
        """8 experience every 9 ticks is 8,000/hr where the model says 11,859,
        because the model knows about the pillar depleting and the tick count
        does not. Recorded so the temptation is visible."""
        from_ticks = dr.CRAFTING_EXPERIENCE * 6000.0 / dr.STATED_TICKS
        (found,) = dr.methods([_band(38, 17_788.235294117647)], _valid())["Crafting"]

        assert from_ticks == pytest.approx(5_333.3, abs=0.1)
        assert found.xp_per_hour > from_ticks

    def test_it_names_its_own_task_and_skill(self) -> None:
        (found,) = dr.methods([_band(38, 1.0)], _valid())["Crafting"]

        assert found.knob == f"training/{dr.TASK}/Crafting"

    def test_only_the_mining_band_for_this_task_is_read(self) -> None:
        other = _band(38, 99.0, knob="training/Mine ~|coal|~/Mining")

        assert dr.methods([other], _valid()) == {}

    def test_nothing_when_the_crafting_copy_is_unreachable(self) -> None:
        assert dr.methods([_band(38, 1.0)], {}) == {}
        assert dr.methods([_band(38, 1.0)], {"Crafting": {}}) == {}

    def test_nothing_when_mining_priced_nothing(self) -> None:
        assert dr.methods([], _valid()) == {}


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "denserunestone.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(dr.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`denserunestone.py`" in listing

    @pytest.mark.real_export
    def test_upstream_carries_the_task_under_both_skills(
        self, real_export: ChunkInfo
    ) -> None:
        """One action, two challenges - and the Crafting one states the same
        38 the wiki does, with `Skills: {"Mining": 38}` beside it."""
        for skill in (dr.SKILL, dr.FROM_SKILL):
            entry = real_export.challenges[skill].get(dr.TASK)
            assert isinstance(entry, dict), skill
            assert entry.get("Primary") is True, skill
            assert entry.get("Level") == dr.LEVEL, skill
