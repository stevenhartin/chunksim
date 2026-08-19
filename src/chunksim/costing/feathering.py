"""Attaching feathers, which the wiki times four times and then stops.

**145 of Fletching's 158 untimed recipes are the same action.** Every dart and
every unfinished bolt is finished by putting a stack of feathers onto a stack
of tips or shafts, and the `{{Recipe}}` for each states a level, an
experience, an output of ten - and no `ticks` at all. So `recipe_rates.
rate_for` refused the lot, and twenty of Fletching's thirty-one unpriced
methods were this one gap wearing twenty names.

### The wiki times the same action elsewhere, four times, identically

Four feathered recipes in the corpus *do* carry a duration, and every one of
them is **2 ticks**:

    Headless arrow          2   Headless atlatl dart    2
    Flighted ogre arrow     2   Seeking headless arrow  2

Those are feathers onto shafts, which is the same interface as feathers onto
bolts: two stacks, one click, ten or twenty made. **`Headless atlatl dart` is
the decisive one** - it is `Atlatl dart shaft x20 + Feather x20` for 20, timed
at 2, and its sibling `Atlatl dart` (tips onto the headless darts) is timed at
2 as well.

Widening the question past feathers says the same thing: of the 267 Fletching
recipes that combine two stacks into ten or more, **107 state 2 ticks, 16
state 1, and 144 state nothing**. The 16 one-tick rows are javelins, which the
wiki times differently and which are left alone - this fills only where the
page is blank.

### And the training page states the interface in words

`Pay-to-play Fletching training` calls darts "arguably the most feasible
option for zero-time training" because "fletching them only requires **two
clicks per a set of darts**", and says of bolts that they "give experience
every two clicks". Two clicks a set at one tick a click is the same two ticks
the four timed siblings carry.

### What this deliberately does not decide

**The rate that comes out is the action's, and it is enormous** - a dragon
dart is 250 experience for ten and 2 ticks is 750,000 an hour. Nothing here
pretends that is an hour anyone spends: `training.effective_xp_per_hour`
charges a method for the time to obtain what it consumes, and ten dragon dart
tips is a Smithing bill that dwarfs the fletching. The wiki files the whole
family under **zero time methods** for exactly that reason - the two clicks
are done while running somewhere else - and publishes no hourly figure at all,
which is why this is a duration rather than a rate.

**Only where the wiki is blank**, like every other `stated_ticks` contributor,
so a published tick cost is never overwritten - and only for Fletching, where
the four witnesses are.

Pure: takes the recipe corpus and returns a `{output: ticks}` map.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from chunksim.remote.recipes import Recipe

SKILL = "Fletching"

#: Ticks one feathering action costs. **Read off the four feathered recipes
#: the wiki does time**, which agree exactly - see the module docstring.
FEATHER_TICKS = 2

#: Every feather the corpus pairs with ammunition. The plain one and seven
#: coloured or creature variants, all of which the wiki writes as separate
#: `{{Recipe}}` rows against an identical output.
FEATHERS: frozenset[str] = frozenset({
    "Feather",
    "Yellow feather",
    "Orange feather",
    "Red feather",
    "Blue feather",
    "Stripy feather",
    "Gryphon feather",
    "Stymphike feather",
})


def is_feathered(recipe: Recipe) -> bool:
    """Whether `recipe` finishes ammunition with a stack of feathers."""
    return any(material.name in FEATHERS for material in recipe.materials)


def stated_ticks(recipes: Mapping[str, Sequence[Recipe]]) -> dict[str, float]:
    """`{output: ticks}` for feathered ammunition the wiki left untimed.

    Keyed by output, matching `chisel.stated_ticks`, `herblore.stated_ticks`
    and `yewtree.stated_ticks`, so they all merge in
    `recipe_rates.stated_ticks`. Fletching only, and only where the recipe
    states no duration of its own.
    """
    found: dict[str, float] = {}
    for recipe in recipes.get(SKILL) or ():
        if recipe.ticks is not None:
            continue
        if not is_feathered(recipe):
            continue
        found[recipe.output] = float(FEATHER_TICKS)
    return found
