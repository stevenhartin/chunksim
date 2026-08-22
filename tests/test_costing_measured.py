"""Durations somebody timed in game, where the wiki states none."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import measured
from chunksim.remote.recipes import Material, Recipe


def _recipe(output: str, ticks: float | None) -> Recipe:
    return Recipe(
        page=output,
        output=output,
        output_quantity=1.0,
        skill="Cooking",
        level=20,
        experience=52.0,
        ticks=ticks,
        materials=(Material("Nettle-water", 1.0),),
    )


class TestItFillsOnlyTheBlank:
    @pytest.mark.parametrize("output", sorted(measured.MEASURED_TICKS))
    def test_an_untimed_recipe_gets_its_measurement(self, output: str) -> None:
        found = measured.stated_ticks({"Cooking": (_recipe(output, None),)})

        assert found == {output: measured.MEASURED_TICKS[output]}

    def test_a_published_figure_wins(self) -> None:
        """**What would overturn a measurement**: the wiki timing the page.
        `stated_ticks` fills only where it is blank, so that day the published
        figure wins and this entry goes quiet with nothing edited."""
        assert measured.stated_ticks({"Cooking": (_recipe("Nettle tea", 9.0),)}) == {}

    def test_a_stated_zero_is_not_a_published_figure(self) -> None:
        assert measured.stated_ticks({"Cooking": (_recipe("Nettle tea", 0.0),)}) == {
            "Nettle tea": 4.0
        }

    def test_nothing_else_is_touched(self) -> None:
        assert measured.stated_ticks({"Cooking": (_recipe("Bread", None),)}) == {}

    def test_every_entry_is_a_real_duration(self) -> None:
        assert measured.MEASURED_TICKS
        assert all(ticks > 0 for ticks in measured.MEASURED_TICKS.values())


class TestAgainstTheShippedCorpus:
    def _cooking(self) -> tuple[Recipe, ...]:
        from chunksim.costing.inputs import load_reference

        return tuple(load_reference(None, None).recipes.get("Cooking", ()))

    def test_each_named_output_is_still_untimed_upstream(self) -> None:
        """An entry that stopped being needed is worse than inert - it would
        shadow the wiki finally publishing a figure."""
        rows = [
            recipe
            for recipe in self._cooking()
            if recipe.output in measured.MEASURED_TICKS
        ]

        assert {recipe.output for recipe in rows} == set(measured.MEASURED_TICKS)
        assert not any(recipe.timed for recipe in rows)

    def test_the_teas_nearest_sibling_disagrees_by_a_tick(self) -> None:
        """**Recorded rather than smoothed over.** `Damiana tea` is the same
        shape of action - a flavoured water heated into a tea - and states 3
        where this measures 4. The measurement wins because it is of *this*
        action, and borrowing across pages is what `costing/yewtree.py` does
        only where every sibling agrees; the gap is the first thing to look at
        if anyone re-times either."""
        damiana = [
            recipe for recipe in self._cooking() if recipe.output == "Damiana tea"
        ]

        assert damiana and {recipe.ticks for recipe in damiana} == {3.0}
        assert measured.MEASURED_TICKS["Nettle tea"] == 4.0

    def test_the_paste_has_no_sibling_at_all(self) -> None:
        pastes = {
            recipe.output
            for recipe in self._cooking()
            if "paste" in recipe.output.lower() and recipe.timed
        }

        assert pastes == set()


class TestItIsWiredIn:
    def test_the_merge_calls_it(self) -> None:
        from chunksim.costing import recipe_rates

        source = pathlib.Path(recipe_rates.__file__).read_text(encoding="utf-8")
        assert "measured.stated_ticks(recipes)" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(measured.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`measured.py`" in listing
