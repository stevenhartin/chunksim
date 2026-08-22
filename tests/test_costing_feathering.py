"""Attaching feathers, which the wiki times four times and then stops."""

from __future__ import annotations

import pathlib

from chunksim.costing import feathering as fe
from chunksim.remote.recipes import Material, Recipe


def _recipe(output: str, materials: tuple[str, ...], ticks: int | None) -> Recipe:
    return Recipe(
        page=output,
        output=output,
        output_quantity=10.0,
        skill="Fletching",
        level=1,
        experience=10.0,
        ticks=ticks,
        materials=tuple(Material(name=name, quantity=10.0) for name in materials),
        variant="",
    )


class TestItFillsOnlyWhereTheWikiIsBlank:
    def test_an_untimed_feathered_recipe_gets_two(self) -> None:
        found = fe.stated_ticks(
            {"Fletching": (_recipe("Bronze bolts", ("Bronze bolts (unf)", "Feather"), None),)}
        )
        assert found == {"Bronze bolts": 2.0}

    def test_a_timed_one_is_left_alone(self) -> None:
        """A published tick cost is never overwritten - the same rule every
        other `stated_ticks` contributor holds to."""
        found = fe.stated_ticks(
            {"Fletching": (_recipe("Headless arrow", ("Arrow shaft", "Feather"), 2),)}
        )
        assert found == {}

    def test_an_untimed_recipe_with_no_feather_is_left_alone(self) -> None:
        found = fe.stated_ticks(
            {"Fletching": (_recipe("Bone shortbow", ("Yew shortbow", "Scurrius' spine"), None),)}
        )
        assert found == {}

    def test_another_skill_is_not_touched(self) -> None:
        found = fe.stated_ticks(
            {"Crafting": (_recipe("Something", ("Feather",), None),)}
        )
        assert found == {}

    def test_every_coloured_feather_counts(self) -> None:
        """The wiki writes one `{{Recipe}}` per feather against an identical
        output, so a rule reading only the plain one would fill a third of
        them."""
        for feather in fe.FEATHERS:
            found = fe.stated_ticks(
                {"Fletching": (_recipe("Iron bolts", ("Iron bolts (unf)", feather), None),)}
            )
            assert found == {"Iron bolts": 2.0}, feather


class TestTwoTicksIsReadRatherThanChosen:
    def test_it_is_what_the_timed_siblings_carry(self) -> None:
        """`Headless arrow`, `Headless atlatl dart`, `Flighted ogre arrow` and
        `Seeking headless arrow` are the four feathered recipes the corpus
        times, and every one is 2 - which is also what the training page means
        by "two clicks per a set of darts"."""
        assert fe.FEATHER_TICKS == 2


class TestAgainstTheShippedCorpus:
    def _corpus(self) -> dict[str, tuple[Recipe, ...]]:
        from chunksim.costing.inputs import load_reference

        blobs = load_reference(None, None)
        return {skill: tuple(rows) for skill, rows in blobs.recipes.items()}

    def test_the_four_witnesses_are_still_there(self) -> None:
        timed = {
            recipe.output
            for recipe in self._corpus().get("Fletching", ())
            if fe.is_feathered(recipe) and recipe.timed
        }
        assert timed == {
            "Headless arrow",
            "Headless atlatl dart",
            "Flighted ogre arrow",
            "Seeking headless arrow",
        }

    def test_and_all_four_agree_on_two(self) -> None:
        ticks = {
            recipe.ticks
            for recipe in self._corpus().get("Fletching", ())
            if fe.is_feathered(recipe) and recipe.timed
        }
        assert ticks == {fe.FEATHER_TICKS}

    def test_the_rest_say_zero_rather_than_nothing_at_all(self) -> None:
        """**Which is the module's own argument arriving from the wiki.**
        `feathering.py` says the training page files these under *zero time
        methods* because the two clicks are done while running somewhere else;
        the corpus now agrees literally - `ticks = 0`, not a blank - since
        `Recipe.timed` stopped collapsing the two. The stated 2 still wins,
        because it is a duration for the *action* where a zero is a claim
        about the game's delay."""
        rows = self._corpus().get("Fletching", ())
        feathered = [r for r in rows if not r.timed and fe.is_feathered(r)]
        stated_instant = [r for r in feathered if r.ticks == 0.0]

        assert len(stated_instant) == 144
        # The one exception is `Prototype dart`, which carries no `ticks` field
        # at all - a genuine blank, and the reason this counts rather than
        # asserting the set.
        assert len(feathered) - len(stated_instant) == 1

    def test_it_covers_most_of_what_fletching_left_untimed(self) -> None:
        rows = self._corpus().get("Fletching", ())
        untimed = [r for r in rows if not r.timed]
        feathered = [r for r in untimed if fe.is_feathered(r)]
        assert len(untimed) > 100
        assert len(feathered) / len(untimed) > 0.9


class TestItIsWiredIn:
    def test_the_merge_calls_it(self) -> None:
        from chunksim.costing import recipe_rates

        source = pathlib.Path(recipe_rates.__file__).read_text(encoding="utf-8")
        assert "feathering.stated_ticks(recipes)" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(fe.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`feathering.py`" in listing
