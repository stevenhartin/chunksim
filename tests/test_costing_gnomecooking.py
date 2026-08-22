"""The one gnome crunchy the wiki leaves untimed."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import gnomecooking as gc
from chunksim.remote.recipes import Material, Recipe


def _recipe(output: str, ticks: float | None) -> Recipe:
    return Recipe(
        page=output,
        output=output,
        output_quantity=1.0,
        skill="Cooking",
        level=14,
        experience=44.0,
        ticks=ticks,
        materials=(Material("Unfinished crunchy (worm)", 1.0),),
    )


class TestItFillsOnlyTheBlank:
    def test_an_untimed_worm_crunchy_gets_the_family_figure(self) -> None:
        found = gc.stated_ticks({"Cooking": (_recipe(gc.CRUNCHY_OUTPUT, None),)})

        assert found == {gc.CRUNCHY_OUTPUT: gc.CRUNCHY_TICKS}

    def test_a_published_figure_is_never_overwritten(self) -> None:
        assert gc.stated_ticks({"Cooking": (_recipe(gc.CRUNCHY_OUTPUT, 7.0),)}) == {}

    def test_a_stated_zero_is_not_a_published_figure(self) -> None:
        """`Recipe.timed`: `ticks = 0` is the wiki calling the action instant,
        which is a different claim from timing it - see `remote/recipes.py`."""
        assert gc.stated_ticks({"Cooking": (_recipe(gc.CRUNCHY_OUTPUT, 0.0),)}) == {
            gc.CRUNCHY_OUTPUT: gc.CRUNCHY_TICKS
        }

    def test_nothing_else_is_touched(self) -> None:
        assert gc.stated_ticks({"Cooking": (_recipe("Toad crunchies", None),)}) == {}

    def test_no_recipes_at_all_is_no_entry(self) -> None:
        assert gc.stated_ticks({}) == {}


class TestAgainstTheShippedCorpus:
    def _cooking(self) -> tuple[Recipe, ...]:
        from chunksim.costing.inputs import load_reference

        return tuple(load_reference(None, None).recipes.get("Cooking", ()))

    def test_the_three_witnesses_all_state_one_tick(self) -> None:
        """The whole of the argument. If a game update retimes the family this
        fails rather than letting the fourth quietly inherit a stale figure."""
        found = {
            recipe.output: recipe.ticks
            for recipe in self._cooking()
            if recipe.output in gc.TIMED_SIBLINGS
        }

        assert set(found) == set(gc.TIMED_SIBLINGS)
        assert set(found.values()) == {gc.CRUNCHY_TICKS}

    def test_the_fourth_is_still_the_blank_one(self) -> None:
        untimed = {
            recipe.output for recipe in self._cooking() if not recipe.timed
        }

        assert gc.CRUNCHY_OUTPUT in untimed

    def test_the_family_is_four_and_no_wider(self) -> None:
        """Named rather than ruled: `costing/chisel.py`'s reason. A rule over
        untimed Cooking recipes would reach far past these."""
        crunchies = {
            recipe.output
            for recipe in self._cooking()
            if recipe.output.endswith("crunchies") and not recipe.output.startswith("Burnt")
        }

        assert crunchies == {gc.CRUNCHY_OUTPUT, *gc.TIMED_SIBLINGS}


class TestItIsWiredIn:
    def test_the_merge_calls_it(self) -> None:
        from chunksim.costing import recipe_rates

        source = pathlib.Path(recipe_rates.__file__).read_text(encoding="utf-8")
        assert "gnomecooking.stated_ticks(recipes)" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(gc.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`gnomecooking.py`" in listing
