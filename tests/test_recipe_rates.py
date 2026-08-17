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
    material_candidates,
    names_variant,
    stocks,
    rate_for,
    challenge_experience,
    join_keys,
    refuse_dropped,
    unjoined_outputs,
    with_aliases,
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


def test_a_slow_computed_rate_is_kept_rather_than_refused() -> None:
    """**A method slower than the floor is slow, not unpriced**, and conflating
    the two was the cost of the guard this replaced.

    The floor is a stand-in for "nothing has priced this". A computed rate
    below it used to be dropped on the argument that the model was more likely
    missing something than the method was genuinely glacial - Supercompost at
    173 xp/hr, the one Farming method the recipes reached, having priced
    Farming 1 -> 99 at 75,353 hours.

    **What made that safe to remove is that the surrounding models caught up.**
    The band walk takes a running *maximum*, so a slow method can only decide a
    climb where it is the only one - and Tithe Farm now covers Farming from 34,
    so Supercompost is bounded to the stretch below it: 236.4h rather than
    75,353h. Measured across both cached maps, removing the guard priced 218
    more methods, moved 37 off a guide, and changed exactly one climb by 5.5h.
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

    assert merged["Make ~|supercompost|~"]["Farming"].value == 173.0
    assert merged["Make ~|supercompost|~"]["Farming"].match == COMPUTED_MATCH
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


def test_two_inputs_to_one_output_are_not_ambiguous_either() -> None:
    """**The same defect one axis over.** The wiki labels a variant only where
    the *method* differs; where the difference is what goes in, every recipe
    carries an empty label. Ten fish make `Fine fish offcuts`, so four cut-up
    tasks that had each correctly chosen their own fish still read as one
    recipe describing four methods - and the guard then held a money-making
    guide about *cooking* a marlin over the recipe for the knife."""
    def rate(task: str, fish: str, xp_per_hour: float) -> ActionRate:
        return ActionRate(
            task=task, skill="Cooking", xp_per_hour=xp_per_hour, experience=2.0,
            ticks=3, input_seconds=0.0, output="Fine fish offcuts",
            materials=(fish,),
        )

    marlin, yellowfin = "Cut up a ~|raw marlin|~", "Cut up a ~|raw yellowfin|~"
    computed = {
        marlin: rate(marlin, "Raw marlin", 718.0),
        yellowfin: rate(yellowfin, "Raw yellowfin", 1_009.0),
    }
    guide = {"Cooking": Rate(292_500.0, "mmg:Cooking raw marlin", "exact")}

    merged = apply({marlin: guide, yellowfin: guide}, computed)

    assert merged[marlin]["Cooking"].value == 718.0
    assert merged[marlin]["Cooking"].match == COMPUTED_MATCH
    assert merged[yellowfin]["Cooking"].value == 1_009.0


def test_an_alt_twin_is_not_a_second_method() -> None:
    """Measured over the whole export there are 20 `(alt)` tasks, every one has
    a non-alt twin, and every difference between a pair is a flag or a second
    route into the same action - never a different thing made. Counting the
    pair as two methods was the other half of what held the marlin's guide."""
    base = "Cut up a ~|raw marlin|~"
    alt = f"{base} (alt)"

    def rate(task: str) -> ActionRate:
        return ActionRate(
            task=task, skill="Cooking", xp_per_hour=718.0, experience=2.0,
            ticks=3, input_seconds=0.0, output="Fine fish offcuts",
            materials=("Raw marlin",),
        )

    guide = {"Cooking": Rate(292_500.0, "mmg:Cooking raw marlin", "exact")}

    merged = apply({base: guide, alt: guide}, {base: rate(base), alt: rate(alt)})

    assert merged[base]["Cooking"].value == 718.0
    assert merged[alt]["Cooking"].value == 718.0


def test_a_task_takes_the_recipe_whose_materials_it_lists() -> None:
    """**The field that resolved the other nineteen groups.** Every altar rune
    shared a key with its Guardians of the Rift twin, because `rate_for`
    maximises and pure essence is the fastest thing that prices - so the twin
    took the pure-essence recipe too, and `apply`'s guard then held six runes
    on a money-making guide over a collision that was never real. Upstream
    states the essence: `Items: ["Pure essence*"]` on the altar task, and
    nothing at all on the minigame one."""
    def rune(essence: str, experience: float) -> Recipe:
        return Recipe(
            page="Nature rune", output="Nature rune", output_quantity=1.0,
            skill="Runecraft", level=44, experience=experience, ticks=1,
            materials=(Material(name=essence, quantity=1.0),),
        )

    pure, guardian = rune("Pure essence", 9.0), rune("Guardian essence", 9.0)
    altar = {"Items": ["Pure essence*"], "Primary": True}
    minigame = {"Category": ["Minigame"], "Primary": True}

    assert material_candidates(altar, [pure, guardian], [minigame]) == (pure,)
    assert material_candidates(minigame, [pure, guardian], [altar]) == (guardian,)


def test_the_items_list_beats_the_tasks_words() -> None:
    """**A word-subset test over the name is not enough**, and Fletching is
    where it shows: every `Fletch ~|X logs|~ into shafts` task contains the
    word `logs`, so the magic one reads as describing the plain-log recipe
    too - `names_variant`'s "must not match a task that merely says furnace"
    arriving through a different door. The `Items` list says `Magic logs` and
    stops there."""
    def shaft(log: str, made: float) -> Recipe:
        return Recipe(
            page="Arrow shaft", output="Arrow shaft", output_quantity=made,
            skill="Fletching", level=1, experience=made / 3.0, ticks=2,
            materials=(Material(name=log, quantity=1.0),),
        )

    plain, magic = shaft("Logs", 15.0), shaft("Magic logs", 90.0)
    magic_task = {"Items": ["Magic logs*", "Fletching knife[+]"], "Primary": True}

    assert material_candidates(magic_task, [plain, magic], []) == (magic,)


def test_a_group_the_variant_already_resolved_is_not_widened() -> None:
    """Applied after the variant partition and only where that left more than
    one candidate, so the twelve bar pairs keep what `variant_candidates` gave
    them."""
    one = Recipe(
        page="Bronze bar", output="Bronze bar", output_quantity=1.0, skill="Smithing",
        level=1, experience=6.2, ticks=3, materials=(), variant="Superheat",
    )

    assert material_candidates({"Items": []}, [one], []) == (one,)


def test_the_markers_are_stripped_before_comparing() -> None:
    """`Magic logs*` says the action consumes it and `Fire rune[+]` says any
    member of a family will do - the same two markers `estimate` strips."""
    assert stocks({"Items": ["Magic logs*", "Fire rune[+]", " "]}) == frozenset(
        {"magic logs", "fire rune"}
    )


def test_an_alias_registers_beside_the_name_the_wiki_renamed() -> None:
    """`Bronze javelin heads` became `Bronze javelin tips` on 5 November 2025;
    upstream's export still says `heads`, so the exact join found nothing until
    the wiki's own redirect was consulted."""
    by_output = {"bronze javelin tips": _BRONZE[:1]}

    merged = with_aliases(by_output, {"Bronze javelin heads": "Bronze javelin tips"})

    assert merged["bronze javelin heads"] == _BRONZE[:1]
    assert merged["bronze javelin tips"] == _BRONZE[:1]


def test_an_alias_never_displaces_a_real_recipe() -> None:
    """The wiki redirecting `X` to `Y` says nothing about a recipe whose own
    output is `X`. Letting the redirect win there would trade a real join for a
    guessed one, so this is additive only."""
    by_output = {"bronze bar": _BRONZE, "runite bar": ()}

    merged = with_aliases(by_output, {"Bronze bar": "Runite bar"})

    assert merged["bronze bar"] == _BRONZE


def test_an_alias_pointing_nowhere_is_dropped() -> None:
    """A redirect whose target has no recipe is not a join, and keeping it
    would grow the index without ever changing an answer."""
    assert with_aliases({"bronze bar": _BRONZE}, {"Old name": "Something else"}) == {
        "bronze bar": _BRONZE
    }


def test_unjoined_outputs_asks_only_about_names_a_recipe_could_answer() -> None:
    """**Output names, never the task's own words.** `join_keys`' third key is
    a sentence with the verb stripped, and handing those to the wiki asks
    thousands of questions whose answer is always no."""
    info = ChunkInfo(
        {
            "challenges": {
                "Smithing": {
                    "Smith ~|bronze javelin heads|~": {
                        "Primary": True,
                        "Output": "Bronze javelin heads",
                    },
                    "Smelt a ~|bronze bar|~": {"Primary": True, "Output": "Bronze bar"},
                    "Repair a broken ~|strut|~ in the Motherlode Mine": {"Primary": True},
                    "Smith a ~|secondary|~": {"Primary": False, "Output": "Secondary"},
                }
            }
        }
    )

    wanted = unjoined_outputs(info, {"Smithing": _BRONZE})

    # `Bronze bar` joined, the strut offers no `Output` and the non-primary row
    # is not a training method - so exactly one name is worth asking about.
    assert wanted == ("Bronze javelin heads",)


def test_the_credit_is_per_unit_of_output_not_per_action() -> None:
    """**Superglass Make pays 180 experience and returns 28.8 molten glass.**
    Taking the action's experience credited nine times what a piece is worth
    and made glassblowing the entire Crafting climb - 146.3h to 101.9h off one
    bad number. The walk charges the challenge once per *item*, so the credit
    has to be per item too.

    Where the variants disagree the smallest is taken: this number makes a
    method look faster, and the walk cannot say which variant it used.
    """
    info = ChunkInfo(
        {
            "challenges": {
                "Crafting": {
                    "Craft ~|molten glass|~": {"Primary": True, "Output": "Molten glass"},
                }
            }
        }
    )
    furnace = Recipe(
        page="Molten glass", output="Molten glass", output_quantity=1.0,
        skill="Crafting", level=1, experience=20.0, ticks=2,
        materials=(Material(name="Bucket of sand", quantity=1.0),),
    )
    superglass = Recipe(
        page="Molten glass", output="Molten glass", output_quantity=28.8,
        skill="Crafting", level=77, experience=180.0, ticks=6,
        materials=(Material(name="Bucket of sand", quantity=18.0),),
        variant="Superglass Make - giant seaweed",
    )

    found = challenge_experience(info, {"Crafting": [furnace, superglass]})

    skill, paid = found["Craft ~|molten glass|~"]
    assert skill == "Crafting"
    assert paid == pytest.approx(180.0 / 28.8), "per piece, and the lower of the two"


def test_an_untimed_recipe_offers_no_credit() -> None:
    """`rate_for` refuses an untimed recipe, so crediting one would pay
    experience for a route the walk never took."""
    info = ChunkInfo(
        {"challenges": {"Herblore": {"Clean a ~|grimy x|~": {"Primary": True, "Output": "X"}}}}
    )
    untimed = Recipe(
        page="X", output="X", output_quantity=1.0, skill="Herblore",
        level=1, experience=10.0, ticks=None,
        materials=(Material(name="Grimy x", quantity=1.0),),
    )

    assert challenge_experience(info, {"Herblore": [untimed]}) == {}
    assert challenge_experience(info, {"Herblore": [untimed]}, stated_ticks={"X": 0.6})


def test_a_method_whose_inputs_have_no_route_keeps_no_scraped_rate() -> None:
    """**A dropped method used to keep its guide rate and pay nothing for
    materials.** `rate_for` returns `None` when an input has no route - rightly
    - but it is also the only source of `material_seconds_per_xp`, so the
    scrape then ranked as though the ingredients were free, and the
    ingredients in question are precisely the ones too hard to price.

    `Mix an ~|ancient mix|~` needs an `Ancient brew(2)` the map cannot route,
    so `wiki:herblore`'s 522,500/hr stood against recipe-priced neighbours at
    30,546 and took the top four bands of the skill.
    """
    training = {
        "Mix an ~|ancient mix|~": {"Herblore": Rate(522_500.0, "wiki:herblore", "exact")},
        "Mix a ~|super restore|~": {"Herblore": Rate(30_546.0, "recipe", "computed")},
        "Catch a ~|leaping trout|~": {"Fishing": Rate(3_841.0, "computed:gathering", "modelled")},
    }

    kept = refuse_dropped(training, ["Mix an ~|ancient mix|~", "Catch a ~|leaping trout|~"])

    assert "Mix an ~|ancient mix|~" not in kept
    assert kept["Mix a ~|super restore|~"]["Herblore"].value == 30_546.0
    # **A modelled rate survives**: a model answering for a whole activity is
    # not a claim about a recipe's inputs.
    assert kept["Catch a ~|leaping trout|~"]["Fishing"].value == 3_841.0


def test_a_hand_pin_survives_being_dropped() -> None:
    """As everywhere else: someone wrote that number down deliberately."""
    training = {"Mix a ~|thing|~": {"Herblore": Rate(1.0, "hand: measured", "exact")}}

    assert refuse_dropped(training, ["Mix a ~|thing|~"], pinned={"Mix a ~|thing|~"})


def test_a_dose_is_a_fallback_join_not_a_first_choice() -> None:
    """**A potion's dose is a vocabulary difference as often as a real one.**
    Upstream calls a challenge's output `Super combat potion(3)` where the only
    recipe makes a `(4)`. But a challenge whose own dose *is* made must keep
    it - an attack potion is not a four-dose recipe."""
    keys = join_keys({"Output": "Attack potion(3)"}, "Mix an ~|attack potion|~")

    assert keys[0] == "Attack potion(3)", "the exact output comes first"
    assert "Attack potion(4)" in keys
    assert keys.index("Attack potion(3)") < keys.index("Attack potion(4)")


def test_a_bare_name_is_offered_each_dose() -> None:
    """`join_keys`' verb-stripped key carries no dose, which is what kept
    `Extreme potion(3)` from reaching `Extreme energy potion(3)`."""
    keys = join_keys({}, "Mix an ~|extreme energy potion|~")

    assert "extreme energy potion" in keys
    assert "extreme energy potion(3)" in keys
