"""Two Herblore durations the wiki leaves blank in families that publish them."""

from __future__ import annotations

import pytest

from chunksim.costing import potionsteps, recipe_rates
from chunksim.remote.recipes import Material, Recipe


def _recipe(output: str, ticks: int | None, *materials: str) -> Recipe:
    return Recipe(
        page=output, output=output, output_quantity=1.0, skill="Herblore",
        level=1, experience=10.0, ticks=ticks,
        materials=tuple(Material(name=m, quantity=1.0) for m in materials),
        variant="",
    )


class TestTheBarbarianMix:
    def test_the_one_untimed_mix_is_filled(self) -> None:
        found = potionsteps.stated_ticks(
            {"Herblore": [_recipe("Magic essence mix(2)", None, "Caviar")]}
        )
        assert found == {"Magic essence mix(2)": 1.0}

    def test_a_mix_the_wiki_timed_keeps_its_own_figure(self) -> None:
        """A published tick cost is never overwritten by a stated one."""
        assert potionsteps.stated_ticks(
            {"Herblore": [_recipe("Agility mix(2)", 1, "Caviar")]}
        ) == {}

    def test_the_modal_family_figure_is_what_is_spent(self) -> None:
        """Twenty-six of the twenty-eight timed siblings say one tick; the two
        that say two read as transcription noise, and the mean would be
        neither number."""
        assert potionsteps.MIX_TICKS == 1


class TestTheSanfewChain:
    def test_the_collapsed_recipe_is_three_combines(self) -> None:
        """**Checked by experience, not counted from materials.** The three
        steps pay 47.5 + 52.5 + 60, which is exactly the 160 the collapsed
        recipe states for the same serum."""
        assert potionsteps.SERUM_STEPS == 3
        assert potionsteps.SERUM_TICKS == 3 * potionsteps.STEP_TICKS
        assert pytest.approx(47.5 + 52.5 + 60.0) == 160.0

    def test_the_collapsed_recipe_is_timed_and_the_stepwise_one_is_not(self) -> None:
        """The stepwise recipe publishes its two ticks, so it is skipped; the
        collapsed one is what the join picks and what has to be filled."""
        found = potionsteps.stated_ticks(
            {"Herblore": [
                _recipe("Sanfew serum(3)", 2, "Mixture - step 2(3)"),
                _recipe("Sanfew serum(3)", None, "Super restore(3)", "Snake weed"),
            ]}
        )
        assert found == {"Sanfew serum(3)": 6.0}

    def test_the_middle_steps_take_the_published_two(self) -> None:
        found = potionsteps.stated_ticks(
            {"Herblore": [
                _recipe("Mixture - step 1(3)", None, "Super restore(3)"),
                _recipe("Mixture - step 2(3)", None, "Mixture - step 1(3)"),
            ]}
        )
        assert found == {"Mixture - step 1(3)": 2.0, "Mixture - step 2(3)": 2.0}

    def test_another_skills_recipes_are_left_alone(self) -> None:
        assert potionsteps.stated_ticks(
            {"Cooking": [_recipe("Magic essence mix(2)", None, "Caviar")]}
        ) == {}


class TestItIsMergedIn:
    def test_recipe_rates_calls_it(self) -> None:
        import pathlib

        source = pathlib.Path(recipe_rates.__file__).read_text(encoding="utf-8")
        assert "potionsteps.stated_ticks(recipes)" in source


@pytest.mark.real_export
class TestAgainstTheRealCorpus:
    def test_the_mix_family_still_leaves_exactly_this_one_blank(self) -> None:
        """**The argument, not the magnitude.** If the wiki fills the cell in,
        `Recipe.timed` keeps its figure and this module goes quiet on its own -
        but if a *second* mix loses its duration, the modal claim needs
        re-checking rather than silently covering two."""
        from chunksim.costing import inputs

        blobs = inputs.load_reference()
        mixes = [
            r for r in (blobs.recipes.get("Herblore") or ())
            if "mix(" in r.output.lower()
        ]
        assert len(mixes) > 20
        blank = [r.output for r in mixes if not r.timed]
        assert blank in ([], [potionsteps.UNTIMED_MIX]), blank

    def test_the_serum_still_has_a_timed_and_an_untimed_recipe(self) -> None:
        from chunksim.costing import inputs

        blobs = inputs.load_reference()
        rows = [
            r for r in (blobs.recipes.get("Herblore") or ())
            if r.output == "Sanfew serum(3)"
        ]
        assert len(rows) == 2
        assert sorted(r.timed for r in rows) == [False, True]


@pytest.mark.real_export
class TestTheLilyRename:
    def test_the_export_and_the_wiki_spell_it_differently(self) -> None:
        """**The alias names a real mismatch that a second blocker masks.**
        `Lily of the sands` became `Lily of the Sands` on 19 August 2026 and
        the export has not followed, so `Menaphite remedy(3)`'s recipe asks
        for a material the item graph has under another spelling. It still
        prices at nothing, because the only source is Tombs of Amascut loot
        and this project does not price a raid's table - but the name half is
        fixed and testable, and the drop half is not this entry's to fix."""
        from chunksim.store import cache

        raw = cache.read_chunkinfo()
        challenge = raw["challenges"]["Herblore"]["Mix a ~|menaphite remedy|~"]
        assert "Lily of the sands*" in challenge["Items"]
        assert (
            recipe_rates.MATERIAL_ALIASES["Lily of the Sands"] == "Lily of the sands"
        )
