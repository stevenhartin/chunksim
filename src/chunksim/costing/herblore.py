"""Cleaning a grimy herb, which the wiki does not time.

**The `{{Recipe}}` for every clean herb carries `ticks = 0`**, which is the
wiki saying the *game* imposes no delay rather than saying nobody has timed
it - and `recipe_rates.rate_for` is right to refuse reading that as no time at
all, since an action priced at zero is the fastest method in the game. But the
refusal cost Herblore eighteen methods: `Clean a ~|grimy ranarr weed|~` and its
seventeen siblings joined a recipe, priced their input, and were dropped for
want of a duration.

**This module answers a different question from `ZERO_TICK_TICKS`, and that is
why it still wins.** The floor charges one tick because two actions cannot
resolve in one; this counts the *cycle* a clean herb sits inside, which is a
bank trip and a click, and comes out **faster** than the floor. `ticks_for`
asks `stated_ticks` before it reaches the floor, so counting the cycle beats
bounding the action wherever a module has done the counting.

**It is untimed for the same reason dart fletching is** - see
`heuristics.DART_CYCLE_SECONDS`, the precedent this follows. Cleaning is not
gated by the tick system: you can clean as many herbs in a tick as you can
click, so no page publishes an hourly figure and none could. What bounds it is
the bank trip and a human's click speed, and those *can* be counted:

    1 tick   open the bank
    1 tick   deposit the inventory
    1 tick   withdraw 28 grimy herbs
    1 tick   close the bank
   14 ticks  clean 28 herbs, two a tick
   --------
   18 ticks  per inventory of 28

so `CLEAN_TICKS` is 18/28 of a tick a herb - 0.386 seconds. A stated figure
rather than a measured one, like the dart cycle, and the conservative end of
it: two herbs a tick is a fair sustained pace rather than the ceiling.

**Detected from the recipes rather than listed.** A Herblore recipe whose only
material is a `Grimy ...` item *is* a cleaning action, which keeps this
working when a game update adds a herb and keeps it away from the `Degrime`
variants - those consume runes as well, are the Arceuus spell rather than the
click, and are a different action with its own cost.

Pure: the recipes come in as an argument.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from chunksim.remote.recipes import Recipe

#: Ticks one herb costs to clean, banking included. See the module docstring
#: for the eighteen this is 28 of.
CLEAN_TICKS = 18.0 / 28.0

#: The prefix upstream and the wiki both give an uncleaned herb.
GRIMY_PREFIX = "grimy "


def cleaning_ticks(recipes: Sequence[Recipe]) -> dict[str, float]:
    """`{output: ticks}` for every herb-cleaning recipe the wiki left untimed.

    Only the untimed ones: a recipe that states a tick cost keeps it, so this
    can never overwrite a published figure with a stated one.
    """
    found: dict[str, float] = {}
    for recipe in recipes:
        # **A stated `0` is not a published duration**, which is what
        # `Recipe.timed` says and `ticks is not None` did not: every
        # recipe this module fills carries `ticks = 0`, and reading
        # that as "already timed" would silently retire the module.
        if recipe.timed:
            continue
        if len(recipe.materials) != 1:
            continue
        if not recipe.materials[0].name.lower().startswith(GRIMY_PREFIX):
            continue
        found[recipe.output] = CLEAN_TICKS
    return found


def stated_ticks(recipes: Mapping[str, Sequence[Recipe]]) -> dict[str, float]:
    """`cleaning_ticks` over the whole recipe corpus, Herblore only.

    Keyed by output, which is what `recipe_rates.rate_for` has to hand. Other
    skills are deliberately absent: an untimed recipe elsewhere is a gap to
    look at, not one to fill with a Herblore constant.
    """
    return cleaning_ticks(list(recipes.get("Herblore") or ()))
