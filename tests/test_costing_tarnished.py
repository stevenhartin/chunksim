"""Polishing a tarnished item: one tick, 200 experience, and a very slow drop."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import tarnished as ta
from chunksim.model.chunkinfo import ChunkInfo


def _valid() -> dict[str, dict[str, object]]:
    return {"Crafting": {task: {} for task in ta.TASKS}}


def _challenges() -> dict[str, object]:
    return {
        task: {"Items": [f"{task.partition('~|')[2].rpartition('|~')[0].capitalize()}*"]}
        for task in ta.TASKS
    }


class TestThePublishedTerms:
    def test_one_tick_a_polish(self) -> None:
        """"Tarnished items now take 1 tick to polish, down from 3 ticks" -
        the 15 July 2026 change note, on all nine pages."""
        assert ta.POLISH_TICKS == 1.0

    def test_the_low_end_of_the_stated_range(self) -> None:
        """`skill1exp = 200-250`, and nothing states the distribution - so the
        conservative end, `costing/pyramid.py`'s rule. The high end is carried
        so a reader can see what it would cost."""
        assert (ta.EXPERIENCE, ta.EXPERIENCE_HIGH) == (200.0, 250.0)
        assert ta.EXPERIENCE_HIGH / ta.EXPERIENCE == pytest.approx(1.25)

    def test_the_level_is_upstreams_own(self) -> None:
        assert ta.LEVEL == 64

    def test_the_headline_is_absurd_and_that_is_the_point(self) -> None:
        """One tick for 200 experience. Carried as a name because it is
        exactly what `material_seconds_per_xp` exists to correct."""
        assert ta.POLISH_XP_PER_HOUR == pytest.approx(1_200_000.0)


class TestTheItemIsReadRatherThanDerived:
    """Upstream lowercases the marked span and capitalises its `Items` entry,
    and the item walk is keyed on the latter."""

    def test_it_takes_the_starred_tarnished_item(self) -> None:
        assert ta.consumed({"Items": ["Tarnished ring*"]}) == "Tarnished ring"

    def test_it_ignores_anything_else_the_challenge_lists(self) -> None:
        assert ta.consumed({"Items": ["Chisel", "Tarnished spear*"]}) == "Tarnished spear"

    def test_nothing_where_there_is_nothing(self) -> None:
        assert ta.consumed({}) == ""
        assert ta.consumed({"Items": ["Chisel"]}) == ""


class TestTheDropIsWhatMakesItSlow:
    def test_the_cost_is_declared_per_experience(self) -> None:
        found = ta.material_seconds_per_xp(
            _challenges(), _valid(), lambda item, quantity: 2000.0
        )

        assert set(found) == set(ta.TASKS)
        assert found[ta.TASKS[0]] == pytest.approx(2000.0 / ta.EXPERIENCE)

    def test_an_unroutable_drop_declares_nothing(self) -> None:
        """Which leaves the method reading its headline - so the pair has to
        be wired together, and `TestItIsWiredIn` checks both halves."""
        assert ta.material_seconds_per_xp(
            _challenges(), _valid(), lambda item, quantity: None
        ) == {}

    def test_it_turns_the_headline_into_something_believable(self) -> None:
        """Half an hour of killing for one tarnished item is the whole content
        of the method: the polish is free and the drop is not."""
        per_xp = ta.material_seconds_per_xp(
            _challenges(), _valid(), lambda item, quantity: 1965.0
        )[ta.TASKS[0]]
        effective = 3600.0 / (3600.0 / ta.POLISH_XP_PER_HOUR + per_xp)

        assert effective == pytest.approx(366.0, abs=1.0)


class TestTheBands:
    def test_one_band_each_at_upstreams_level(self) -> None:
        found = ta.methods(_valid())["Crafting"]

        assert len(found) == len(ta.TASKS)
        assert {b.level for b in found} == {ta.LEVEL}

    def test_nothing_when_unreachable(self) -> None:
        assert ta.methods({}) == {}
        assert ta.methods({"Crafting": {}}) == {}

    def test_one_challenge_alone_still_works(self) -> None:
        one: dict[str, dict[str, object]] = {"Crafting": {ta.TASKS[0]: {}}}

        assert len(ta.methods(one)["Crafting"]) == 1

    def test_each_band_names_its_own_task(self) -> None:
        knobs = {b.knob for b in ta.methods(_valid())["Crafting"]}

        assert knobs == {f"training/{task}/Crafting" for task in ta.TASKS}


class TestItIsWiredIn:
    def test_inputs_calls_both_halves(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "tarnished.methods(" in source
        assert "tarnished.material_seconds_per_xp(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(ta.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`tarnished.py`" in listing

    @pytest.mark.real_export
    def test_the_nine_are_upstreams_own_and_each_consumes_its_item(
        self, real_export: ChunkInfo
    ) -> None:
        """**A key that matches nothing is silently inert.** Upstream must
        also still mark the item consumed, since charging a drop it does not
        eat would be the mistake `costing/spells.py`'s quest-reward exemption
        describes."""
        crafting = real_export.challenges["Crafting"]
        for task in ta.TASKS:
            entry = crafting.get(task)
            assert isinstance(entry, dict), task
            assert entry.get("Primary") is True, task
            assert entry.get("Level") == ta.LEVEL, task
            assert ta.consumed(entry), task
            assert any(
                isinstance(item, str) and item.endswith("*")
                for item in entry.get("Items") or ()
            ), task

    @pytest.mark.real_export
    def test_upstream_states_a_loot_table_which_is_why_no_recipe_joins(
        self, real_export: ChunkInfo
    ) -> None:
        """The reason this module exists rather than a `HAND_ALIASES` entry:
        `Tarnished ring loot` is a bundle the wiki has no page for."""
        crafting = real_export.challenges["Crafting"]
        for task in ta.TASKS:
            entry = crafting[task]
            assert str(entry.get("Output") or "").endswith(" loot"), task
