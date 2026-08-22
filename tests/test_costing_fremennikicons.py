"""Three Fremennik icons the wiki leaves untimed, against the one it does not."""

from __future__ import annotations

import pathlib

from chunksim.costing import fremennikicons as fi
from chunksim.remote.recipes import Material, Recipe


def _recipe(output: str, ticks: float | None) -> Recipe:
    return Recipe(
        page=output,
        output=output,
        output_quantity=1.0,
        skill="Crafting",
        level=80,
        experience=400.0,
        ticks=ticks,
        materials=(Material("Archers ring", 1.0),),
    )


class TestItFillsOnlyTheBlanks:
    def test_each_untimed_icon_gets_the_published_figure(self) -> None:
        rows = tuple(_recipe(name, None) for name in fi.UNTIMED_ICONS)

        assert fi.stated_ticks({"Crafting": rows}) == {
            name: fi.ICON_TICKS for name in fi.UNTIMED_ICONS
        }

    def test_the_published_sibling_is_not_touched(self) -> None:
        assert fi.stated_ticks({"Crafting": (_recipe(fi.TIMED_SIBLING, 4.0),)}) == {}
        assert fi.TIMED_SIBLING not in fi.UNTIMED_ICONS

    def test_a_published_figure_is_never_overwritten(self) -> None:
        assert fi.stated_ticks({"Crafting": (_recipe("Archer icon", 9.0),)}) == {}

    def test_nothing_else_is_touched(self) -> None:
        assert fi.stated_ticks({"Crafting": (_recipe("Gold ring", None),)}) == {}


class TestAgainstTheShippedCorpus:
    def _crafting(self) -> tuple[Recipe, ...]:
        from chunksim.costing.inputs import load_reference

        return tuple(load_reference(None, None).recipes.get("Crafting", ()))

    def test_the_witness_still_states_four(self) -> None:
        """If a game update retimes the family this fails rather than letting
        the other three quietly inherit a stale figure."""
        found = [r for r in self._crafting() if r.output == fi.TIMED_SIBLING]

        assert found and {r.ticks for r in found} == {fi.ICON_TICKS}

    def test_the_family_is_uniform_in_everything_a_rate_reads(self) -> None:
        """Which is what makes the borrow safe: four rings, one chisel, the
        same level and the same experience."""
        family = [
            r
            for r in self._crafting()
            if r.output in (fi.TIMED_SIBLING, *fi.UNTIMED_ICONS)
        ]

        assert len(family) == 4
        assert {r.level for r in family} == {80}
        assert {r.experience for r in family} == {400.0}

    def test_the_other_three_are_still_the_blanks(self) -> None:
        untimed = {r.output for r in self._crafting() if not r.timed}

        assert set(fi.UNTIMED_ICONS) <= untimed


class TestItIsWiredIn:
    def test_the_merge_calls_it(self) -> None:
        from chunksim.costing import recipe_rates

        source = pathlib.Path(recipe_rates.__file__).read_text(encoding="utf-8")
        assert "fremennikicons.stated_ticks(recipes)" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(fi.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`fremennikicons.py`" in listing
