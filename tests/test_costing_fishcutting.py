"""Cutting a fish up with a knife, which upstream and the wiki name differently."""

from __future__ import annotations

from chunksim.costing import fishcutting
from chunksim.remote.recipes import Material, Recipe


def _recipe(
    output: str, materials: tuple[str, ...], ticks: float | None, experience: float = 2.0
) -> Recipe:
    return Recipe(
        page=output, output=output, output_quantity=1.0, skill="Cooking",
        level=1, experience=experience, ticks=ticks,
        materials=tuple(Material(name=name, quantity=1.0) for name in materials),
    )


#: The three recipes a raw marlin appears in, which is the whole reason the
#: join runs on the input *and* the output rather than on the input alone.
_MARLIN = _recipe("Fine fish offcuts", ("Raw marlin",), 3)
_COOKED = _recipe("Marlin", ("Raw marlin",), 4, experience=225.0)
_BURNT = _recipe("Burnt marlin", ("Raw marlin",), 4, experience=0.0)

_CHALLENGES = {
    "Cut up a ~|raw marlin|~": {
        "Items": ["Knife", "Raw marlin*"],
        "Output": "Marlin loot",
        "Level": 1,
        "Primary": True,
    },
    "Cook a ~|marlin|~": {
        "Items": ["Raw marlin*"],
        "Output": "Marlin",
        "Level": 91,
        "Primary": True,
    },
}


def test_the_knife_joins_the_fish_going_in() -> None:
    """Upstream names the output `Marlin loot`, a bundle the wiki has no page
    for, so nothing joined - and a money-making guide about *cooking* the fish
    kept the level-1, two-experience knife action at 292,500/hr."""
    found = fishcutting.cut_recipes(_CHALLENGES, [_MARLIN, _COOKED, _BURNT])

    assert found == {"Cut up a ~|raw marlin|~": (_MARLIN,)}


def test_the_output_is_the_other_half_of_the_key() -> None:
    """Joined on the fish alone this would reach `Marlin` at 225 experience and
    `Burnt marlin` at none - the same input and a different action. Only the
    recipes whose output the knife actually makes are candidates."""
    found = fishcutting.cut_recipes(_CHALLENGES, [_COOKED, _BURNT])

    assert found == {}, "no offcuts recipe means no rate, not the cooked one"


def test_a_cook_is_not_a_cut() -> None:
    """The `Knife` in `Items` is what separates them, and it has to: both
    challenges name the same fish."""
    assert "Cook a ~|marlin|~" not in fishcutting.cut_recipes(
        _CHALLENGES, [_MARLIN, _COOKED]
    )


def test_a_species_the_wiki_does_not_describe_stays_unpriced() -> None:
    """`Cut up a ~|leechfin|~` has no `{{Recipe}}` at all. Absent from the
    result means no rate rather than a sibling's - the species differ in what
    the bundle contains, and the experience is the one thing this join is for."""
    challenges = {
        "Cut up a ~|leechfin|~": {
            "Items": ["Knife", "Leechfin*"],
            "Output": "Leechfin loot",
            "Primary": True,
        }
    }

    assert fishcutting.cut_recipes(challenges, [_MARLIN]) == {}


def test_the_family_task_takes_what_no_species_named() -> None:
    """`variant_candidates`' rule on the other axis. Upstream lists the knife
    twice over - once per fish and once for the family - and both join
    `Fine fish offcuts`, so `rate_for` gave the family task whichever species
    was cheapest and the recipe then read as describing two methods."""
    shark = _recipe("Fine fish offcuts", ("Raw shark",), 3)
    cuts = {"Cut up a ~|raw marlin|~": (_MARLIN,)}

    assert fishcutting.unclaimed([_MARLIN, shark], cuts) == (shark,)


def test_subtracting_everything_leaves_the_candidates_alone() -> None:
    """A task with no candidates is worse informed than one sharing them."""
    cuts = {"Cut up a ~|raw marlin|~": (_MARLIN,)}

    assert fishcutting.unclaimed([_MARLIN], cuts) == (_MARLIN,)


def test_a_knife_the_wiki_never_times_costs_what_its_siblings_do() -> None:
    """Three crabs, over the whole export. Their `{{Recipe}}` carries
    `ticks = ""`, and `rate_for` refuses that rather than reading it as zero -
    but the *same knife* is timed elsewhere, at three ticks per raw fish."""
    crab = _recipe("Raw red crab meat", ("Red crab",), None, experience=5.0)
    challenges = {
        "Cut a red crab into ~|raw red crab meat|~": {
            "Items": ["Knife", "Red crab*"],
            "Output": "Raw red crab meat",
            "Primary": True,
        }
    }

    found = fishcutting.stated_ticks(challenges, [crab])

    assert found == {"Raw red crab meat": fishcutting.CUT_TICKS}


def test_a_published_tick_cost_is_never_overwritten() -> None:
    """Filled only where *every* recipe for that output is untimed."""
    timed = _recipe("Raw red crab meat", ("Red crab",), 2, experience=5.0)
    challenges = {
        "Cut a red crab into ~|raw red crab meat|~": {
            "Items": ["Knife", "Red crab*"],
            "Output": "Raw red crab meat",
            "Primary": True,
        }
    }

    assert fishcutting.stated_ticks(challenges, [timed]) == {}
