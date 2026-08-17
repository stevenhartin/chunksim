"""Tests for `costing/recipe_rates.py`: a recipe turned into an hourly rate.

The pricing callable is a plain dict lookup here rather than the real item
walk - that is the whole point of the seam, and it keeps these tests to
milliseconds without a `ChunkInfo` anywhere near them.
"""

from __future__ import annotations

import pytest

from chunksim.costing.heuristics import Rate
from chunksim.costing.recipe_rates import (
    ACTION_OVERHEAD_SECONDS,
    COMPUTED_MATCH,
    TICK_SECONDS,
    ActionRate,
    action_seconds,
    apply,
    computed_rates,
    index_recipes,
    names_variant,
    rate_for,
    variant_candidates,
)
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.remote.recipes import Material, Recipe


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


def test_a_computed_rate_beats_a_guide_and_fills_a_gap() -> None:
    """**The layering, and the reason it was flipped.** A number this project
    computed outranks a number somebody published - see the module docstring -
    so the recipe takes the guide's method as well as the 1,000/hr floor."""
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

    assert merged["Cook a ~|shark|~"]["Cooking"].value == 999_000.0
    assert merged["Cook a ~|shark|~"]["Cooking"].match == COMPUTED_MATCH
    assert merged["Cook a ~|manta ray|~"]["Cooking"].value == 500_000.0
    assert merged["Cook a ~|manta ray|~"]["Cooking"].match == COMPUTED_MATCH


def test_a_modelled_rate_outranks_a_computed_one() -> None:
    """`gathering.py` sits above this module, and `REPLACEABLE` is what says
    so: a whitelist, so a tier nobody named here keeps its rate."""
    computed = {
        "Chop ~|teak logs|~": ActionRate(
            task="Chop ~|teak logs|~", skill="Woodcutting", xp_per_hour=999_000.0,
            experience=85.0, ticks=4, input_seconds=0.0, output="Teak logs",
        )
    }
    training = {"Chop ~|teak logs|~": {"Woodcutting": Rate(48_000.0, "computed:gathering", "modelled")}}

    merged = apply(training, computed)

    assert merged["Chop ~|teak logs|~"]["Woodcutting"].value == 48_000.0
    assert merged["Chop ~|teak logs|~"]["Woodcutting"].match == "modelled"


def test_an_ambiguous_join_may_fill_the_floor_but_not_replace_the_scrape() -> None:
    """**One recipe reaching two tasks is not evidence about either of them.**
    `Craft a ~|nature rune|~` and `... with guardian essence` share an `Output`
    and are the altar loop and a minigame; the scraped rate names one of them
    and this cannot say which it describes. Measured on the real export that is
    32 outputs over 71 tasks - see `apply`."""
    def nature(task: str) -> ActionRate:
        return ActionRate(
            task=task, skill="Runecraft", xp_per_hour=9_529.0, experience=9.0,
            ticks=3, input_seconds=0.0, output="Nature rune",
        )

    computed = {
        task: nature(task)
        for task in (
            "Craft a ~|nature rune|~",
            "Craft a ~|nature rune|~ with guardian essence",
            "Craft a ~|nature rune|~ at the false altar",
        )
    }
    training = {
        "Craft a ~|nature rune|~": {"Runecraft": Rate(26_730.0, "mmg", "contained")},
        "Craft a ~|nature rune|~ with guardian essence": {
            "Runecraft": Rate(25_000.0, "wiki:gotr", "exact")
        },
    }

    merged = apply(training, computed)

    # Both scraped rates survive - neither `exact` nor `contained` is safe here.
    assert merged["Craft a ~|nature rune|~"]["Runecraft"].value == 26_730.0
    assert merged["Craft a ~|nature rune|~ with guardian essence"]["Runecraft"].value == 25_000.0
    # ...but the task with no rate at all still takes one, because there the
    # alternative is the 1,000/hr floor rather than a measurement.
    filled = merged["Craft a ~|nature rune|~ at the false altar"]["Runecraft"]
    assert filled.value == 9_529.0
    assert filled.match == COMPUTED_MATCH


def test_an_unambiguous_join_still_replaces_the_scrape() -> None:
    """The guard above is about *ambiguity*, not about the scrape - a lone
    recipe takes the method as `apply`'s ordering says it should."""
    computed = {
        "Craft a ~|law tiara|~": ActionRate(
            task="Craft a ~|law tiara|~", skill="Runecraft", xp_per_hour=16_728.0,
            experience=95.0, ticks=3, input_seconds=0.0, output="Law tiara",
        )
    }
    training = {"Craft a ~|law tiara|~": {"Runecraft": Rate(9_000.0, "mmg", "contained")}}

    merged = apply(training, computed)

    assert merged["Craft a ~|law tiara|~"]["Runecraft"].value == 16_728.0


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


def test_a_computed_rate_slower_than_the_floor_is_refused() -> None:
    """**The floor is a stand-in for ignorance, not a speed.** A computed rate
    *below* it says this model is missing something about the method far more
    often than it says the method is that slow - and the band walk applies the
    best available rate to a whole climb, so one bad low-level number prices
    everything above it.

    Supercompost is the case: 8.5 xp for an action that gathers 15 watermelons,
    priced at 173 xp/hr, and the only Farming method the recipe data reaches on
    the benchmark map. It made **Farming 1 -> 99 cost 75,353 hours**.
    """
    computed = {
        "Make ~|supercompost|~": ActionRate(
            task="Make ~|supercompost|~", skill="Farming", xp_per_hour=173.0,
            experience=8.5, ticks=60, input_seconds=140.0, output="Supercompost",
        ),
        "Cook a ~|shark|~": ActionRate(
            task="Cook a ~|shark|~", skill="Cooking", xp_per_hour=250_000.0,
            experience=210.0, ticks=4, input_seconds=0.0, output="Shark",
        ),
    }

    merged = apply({}, computed)

    assert "Make ~|supercompost|~" not in merged
    assert merged["Cook a ~|shark|~"]["Cooking"].value == 250_000.0


def _bar(variant: str, ticks: int, materials: tuple[str, ...]) -> Recipe:
    return Recipe(
        page="Bronze bar", output="Bronze bar", output_quantity=1.0,
        skill="Smithing", level=1, experience=6.2, ticks=ticks,
        materials=tuple(Material(name=name, quantity=1.0) for name in materials),
        variant=variant,
    )


#: The real `Bronze bar` recipes, which are the case that motivated all of this.
_BRONZE = (
    _bar("Normal furnace", 5, ("Copper ore", "Tin ore")),
    _bar("Blast Furnace", 11, ("Copper ore", "Tin ore")),
    _bar("Superheat", 3, ("Copper ore", "Tin ore", "Nature rune", "Fire rune")),
)
_SMELT = "Smelt a ~|bronze bar|~"
_SUPERHEAT = "Smelt a ~|bronze bar|~ with superheat item"


def test_a_variant_is_named_by_whole_words() -> None:
    """`Superheat` is claimed by a task saying "with superheat item", but
    `Blast Furnace` must not be claimed by one that merely says "furnace" -
    which is why this is a subset test over words rather than a substring."""
    assert names_variant("Superheat", _SUPERHEAT)
    assert not names_variant("Superheat", _SMELT)
    assert not names_variant("Blast Furnace", "Smelt a ~|bronze bar|~ at a furnace")
    assert names_variant("Ogre spit-roast", "Cook a ~|cooked chompy|~ on an ogre spit-roast")


def test_an_unlabelled_variant_is_claimed_by_nobody() -> None:
    """Every Runecraft recipe has an empty `variant`, so nothing there can be
    told apart this way and the altar groups stay ambiguous on purpose."""
    assert not names_variant("", _SUPERHEAT)
    assert not names_variant("   ", _SUPERHEAT)


def test_a_task_takes_the_variant_it_names_and_leaves_the_rest() -> None:
    """The partition that stopped one recipe from describing two tasks. The
    qualified task takes `Superheat` alone - not the faster furnace recipe it
    does not describe - and the plain one takes what no sibling claimed."""
    siblings = (_SMELT, _SUPERHEAT)

    assert variant_candidates(_SUPERHEAT, _BRONZE, siblings) == (_BRONZE[2],)
    assert variant_candidates(_SMELT, _BRONZE, siblings) == (_BRONZE[0], _BRONZE[1])


def test_a_lone_task_still_sees_every_variant() -> None:
    """No sibling claims anything, so nothing is held back: an output offered
    by one task keeps the old "fastest variant wins" behaviour exactly."""
    assert variant_candidates(_SMELT, _BRONZE, (_SMELT,)) == _BRONZE


def test_a_partition_that_would_empty_a_task_falls_back() -> None:
    """Fails open rather than dropping a method. If every variant were spoken
    for by a sibling, the unqualified task would have nothing to price - and a
    vocabulary this does not understand should cost a method its precision,
    not its rate."""
    only_superheat = (_BRONZE[2],)

    assert variant_candidates(_SMELT, only_superheat, (_SMELT, _SUPERHEAT)) == only_superheat


def test_two_variants_of_one_output_are_not_ambiguous() -> None:
    """**The join defect the ambiguity guard was covering for.** Both tasks
    make a `Bronze bar`, so keyed on the output they read as one answer given
    twice and neither could replace its guide. Keyed on the recipe they are
    two answers, and both do."""
    def rate(task: str, variant: str, xp_per_hour: float) -> ActionRate:
        return ActionRate(
            task=task, skill="Smithing", xp_per_hour=xp_per_hour, experience=6.2,
            ticks=3, input_seconds=0.0, output="Bronze bar", variant=variant,
        )

    computed = {
        _SMELT: rate(_SMELT, "Normal furnace", 3_680.0),
        _SUPERHEAT: rate(_SUPERHEAT, "Superheat", 1_614.0),
    }
    guide = {"Smithing": Rate(4_960.0, "mmg:Smelting bronze bars", "contained")}
    training = {_SMELT: guide, _SUPERHEAT: guide}

    merged = apply(training, computed)

    assert merged[_SMELT]["Smithing"].value == 3_680.0
    assert merged[_SMELT]["Smithing"].match == COMPUTED_MATCH
    assert merged[_SUPERHEAT]["Smithing"].value == 1_614.0
    assert merged[_SUPERHEAT]["Smithing"].match == COMPUTED_MATCH


def test_one_recipe_reaching_two_tasks_is_still_ambiguous() -> None:
    """The guard is unchanged where the variant cannot tell them apart: two
    tasks landing on the *same* recipe still share a key."""
    def rate(task: str) -> ActionRate:
        return ActionRate(
            task=task, skill="Smithing", xp_per_hour=3_680.0, experience=6.2,
            ticks=5, input_seconds=0.0, output="Bronze bar", variant="Normal furnace",
        )

    computed = {_SMELT: rate(_SMELT), _SUPERHEAT: rate(_SUPERHEAT)}
    guide = {"Smithing": Rate(4_960.0, "mmg:Smelting bronze bars", "contained")}

    merged = apply({_SMELT: guide, _SUPERHEAT: guide}, computed)

    assert merged[_SMELT]["Smithing"].value == 4_960.0
    assert merged[_SUPERHEAT]["Smithing"].value == 4_960.0
