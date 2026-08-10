"""Tests for `costing/recipe_rates.py`: a recipe turned into an hourly rate.

The pricing callable is a plain dict lookup here rather than the real item
walk - that is the whole point of the seam, and it keeps these tests to
milliseconds without a `ChunkInfo` anywhere near them.
"""

from __future__ import annotations

import pytest

from fray_claude.costing.heuristics import Rate
from fray_claude.costing.recipe_rates import (
    ACTION_OVERHEAD_SECONDS,
    COMPUTED_MATCH,
    TICK_SECONDS,
    ActionRate,
    action_seconds,
    apply,
    computed_rates,
    index_recipes,
    rate_for,
)
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.remote.recipes import Material, Recipe


def _recipe(output: str, **kwargs: object) -> Recipe:
    defaults: dict[str, object] = {
        "page": output,
        "output": output,
        "output_quantity": 1.0,
        "skill": "Herblore",
        "level": 3,
        "experience": 25.0,
        "ticks": 2,
        "materials": (),
        "variant": "",
    }
    return Recipe(**{**defaults, **kwargs})  # type: ignore[arg-type]


def _free(item: str, quantity: float) -> float | None:
    return 0.0


def test_a_rate_is_experience_over_the_whole_cycle() -> None:
    """Ticks, materials and the fitted overhead - all three, or the number is
    a ceiling rather than a rate."""
    recipe = _recipe("Attack potion(3)", materials=(Material("Eye of newt", 1.0),))

    seconds = action_seconds(recipe, lambda item, quantity: 3.0)

    assert seconds == pytest.approx(TICK_SECONDS * 2 + ACTION_OVERHEAD_SECONDS + 3.0)


def test_a_material_with_no_route_drops_the_method() -> None:
    """**The rule the whole module turns on.** Treating an unobtainable input
    as free makes the method the fastest thing on the map and opens a band at
    whatever level it sits at - which is worse than not pricing it."""
    recipe = _recipe("Attack potion(3)", materials=(Material("Eye of newt", 1.0),))

    assert action_seconds(recipe, lambda item, quantity: None) is None
    assert rate_for([recipe], lambda item, quantity: None) is None


def test_an_unknown_tick_cost_drops_the_method_too() -> None:
    """`"ticks": ""` from the wiki means it does not say. Zero would be
    instant."""
    assert action_seconds(_recipe("Mystery", ticks=None), _free) is None


def test_the_fastest_priceable_variant_wins() -> None:
    """`Bronze bar` smelts in 5 ticks at a furnace and 2 at the Blast Furnace,
    and nothing in the export says which this map reaches. The faster wins, as
    the item walk already picks the cheapest route."""
    slow = _recipe("Bronze bar", ticks=5, variant="Normal furnace")
    fast = _recipe("Bronze bar", ticks=2, variant="Blast Furnace")

    chosen = rate_for([slow, fast], _free)

    assert chosen is not None and chosen[0].variant == "Blast Furnace"


def test_a_variant_that_prices_beats_a_faster_one_that_does_not() -> None:
    """Dropping an unpriceable method must not drop the *output* - the other
    way of making it is still a method."""
    unpriceable = _recipe("Bronze bar", ticks=1, materials=(Material("Nowhere", 1.0),))
    priceable = _recipe("Bronze bar", ticks=5)

    def prices(item: str, quantity: float) -> float | None:
        return None if item == "Nowhere" else 0.0

    chosen = rate_for([unpriceable, priceable], prices)

    assert chosen is not None and chosen[0].ticks == 5


def test_material_seconds_are_summed_not_recovered_by_subtraction() -> None:
    """A shop-bought material must be *exactly* zero seconds. Recovering it as
    `total - ticks - overhead` left 4.4e-16 behind, and every caller asking
    "did the materials cost anything" got the wrong answer for seventeen of
    twenty-one real methods.
    """
    recipe = _recipe("Cooked thing", ticks=4, materials=(Material("Raw thing", 1.0),))

    chosen = rate_for([recipe], _free)

    assert chosen is not None
    assert chosen[2] == 0.0


def test_only_valid_primary_methods_are_priced() -> None:
    """Reachability is the derivation's answer, not a second one invented
    here."""
    info = ChunkInfo(
        {
            "challenges": {
                "Herblore": {
                    "Mix an ~|attack potion|~": {"Primary": True, "Output": "Attack potion(3)"},
                    "Mix a ~|strength potion|~": {"Primary": True, "Output": "Strength potion(3)"},
                    "Drink a ~|potion|~": {"Output": "Attack potion(3)"},
                }
            }
        }
    )
    recipes = {
        "Herblore": (_recipe("Attack potion(3)"), _recipe("Strength potion(3)")),
    }
    valid = {"Herblore": {"Mix an ~|attack potion|~": True, "Drink a ~|potion|~": True}}

    priced, coverage = computed_rates(info, valid, recipes, _free)

    assert set(priced) == {"Mix an ~|attack potion|~"}
    assert coverage.skills["Herblore"] == (1, 1)


def test_a_computed_rate_fills_a_gap_but_never_beats_a_guide() -> None:
    """**The layering, and the measured reason for it.** A recipe and a money
    -making guide answer different questions - see the module docstring - so
    the guide keeps the method and the 1,000/hr floor does not."""
    computed = {
        "Cook a ~|shark|~": ActionRate(
            task="Cook a ~|shark|~", skill="Cooking", xp_per_hour=999_000.0,
            experience=210.0, ticks=4, input_seconds=0.0, output="Shark",
        ),
        "Cook a ~|manta ray|~": ActionRate(
            task="Cook a ~|manta ray|~", skill="Cooking", xp_per_hour=500_000.0,
            experience=216.3, ticks=1, input_seconds=0.0, output="Manta ray",
        ),
    }
    training = {
        "Cook a ~|shark|~": {"Cooking": Rate(273_000.0, "mmg", "exact")},
        "Cook a ~|manta ray|~": {"Cooking": Rate(1_000.0, "default", "default")},
    }

    merged = apply(training, computed)

    assert merged["Cook a ~|shark|~"]["Cooking"].value == 273_000.0
    assert merged["Cook a ~|manta ray|~"]["Cooking"].value == 500_000.0
    assert merged["Cook a ~|manta ray|~"]["Cooking"].match == COMPUTED_MATCH


def test_a_pinned_method_is_left_alone() -> None:
    """A hand override outranks everything, here as everywhere else."""
    computed = {
        "Cook a ~|shark|~": ActionRate(
            task="Cook a ~|shark|~", skill="Cooking", xp_per_hour=999_000.0,
            experience=210.0, ticks=4, input_seconds=0.0, output="Shark",
        )
    }

    merged = apply({}, computed, pinned=frozenset({"Cook a ~|shark|~"}))

    assert merged == {}


def test_several_recipes_for_one_output_are_kept_together() -> None:
    grouped = index_recipes(
        [_recipe("Bronze bar", variant="a"), _recipe("Bronze bar", variant="b"), _recipe("Tin")]
    )

    assert {output: len(found) for output, found in grouped.items()} == {
        "Bronze bar": 2,
        "Tin": 1,
    }


def test_construction_joins_on_the_task_name_where_output_fails() -> None:
    """**Construction names the furniture in `Output Object`, not `Output`.**
    So the `Output` join reached 28 of its 602 methods while the recipe's own
    output *is* the furniture, and the task says so: `Build a ~|mahogany
    table|~`. Still an exact match on a full string - the verb is removed
    mechanically and the remainder compared whole."""
    info = ChunkInfo(
        {
            "challenges": {
                "Construction": {
                    "Build a ~|mahogany table|~": {
                        "Primary": True,
                        "Level": 52,
                        "Output Object": "Mahogany table (built)",
                    }
                }
            }
        }
    )
    recipes = {
        "Construction": (
            _recipe("Mahogany table", skill="Construction", level=52, experience=840.0),
        )
    }
    valid = {"Construction": {"Build a ~|mahogany table|~": True}}

    priced, _ = computed_rates(info, valid, recipes, _free)

    assert "Build a ~|mahogany table|~" in priced
    assert priced["Build a ~|mahogany table|~"].experience == 840.0


def test_a_recipe_priced_in_coins_costs_the_time_to_earn_them() -> None:
    """**Money is time, and it used to be free.** `Coins` has a ground spawn,
    so the item walk found one lying about and priced ten million of them at
    nothing - making a steel dragon in the menagerie the fastest training in
    the game at 3,348,000 xp/hr. Now the caller's pricing decides, and at
    500,000 gp an hour ten million coins is twenty hours."""
    recipe = _recipe(
        "Steel dragon (Construction)",
        skill="Construction",
        materials=(Material("Coins", 10_000_000.0),),
    )

    def earns(item: str, quantity: float) -> float | None:
        return quantity / 500_000.0 * 3600.0 if item == "Coins" else 0.0

    chosen = rate_for([recipe], earns)

    assert chosen is not None
    assert chosen[2] == pytest.approx(20 * 3600)
