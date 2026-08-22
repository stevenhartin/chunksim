"""Three Fremennik icons the wiki leaves untimed, and the fourth that is not.

**One of four is published and three are blank** - the mirror of
`costing/gnomecooking.py`, where three of four are. Chiselling a Fremennik
ring into an icon is one action with four rings:

    Seers icon        4 ticks   400 xp   <- Seers ring
    Archer icon       -         400 xp   <- Archers ring
    Warrior icon      -         400 xp   <- Warrior ring
    Berserker icon    -         400 xp   <- Berserker ring

so `recipe_rates.rate_for` refused three and priced the fourth, which is the
accident of wiki coverage `costing/oneoff.py` describes deciding which of
several identical challenges counts as a method.

**Named rather than ruled**, for `costing/chisel.py`'s reason: resemblance is
not evidence across a corpus where hundreds of recipes are untimed. What makes
this family safe is that it is closed and exactly uniform - four rings, one
chisel, the same Crafting 80 and the same 400 experience, and upstream carries
all four as `Create a ~|... icon|~` with `Items: ["Chisel", "<X> ring*"]`.

**It fills only where the wiki is blank**, so a published figure can never be
overwritten - see `recipe_rates.stated_ticks`, which is where this is merged.

*(The rate is not the point and is barely a number: a Fremennik ring is a
Dagannoth King drop, so the icons price at what killing one costs. What this
buys is three rows reading the same as their fourth sibling instead of
`unpriced` beside it.)*

Pure: the recipes come in as an argument.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from chunksim.remote.recipes import Recipe

SKILL = "Crafting"

#: What `Seers icon` states, and the only published figure in the family.
ICON_TICKS = 4.0

#: The one that carries it. Named so a game update that retimes the family
#: shows up as a test failure rather than as a silent inheritance.
TIMED_SIBLING = "Seers icon"

#: The three it is lent to.
UNTIMED_ICONS: tuple[str, ...] = ("Archer icon", "Warrior icon", "Berserker icon")


def stated_ticks(recipes: Mapping[str, Sequence[Recipe]]) -> dict[str, float]:
    """`{output: ticks}` for the three icons the wiki left untimed.

    Only the untimed ones: a recipe that states a tick cost keeps it, so this
    can never overwrite a published figure with a borrowed one.
    """
    found: dict[str, float] = {}
    for recipe in recipes.get(SKILL, ()):
        if recipe.output in UNTIMED_ICONS and not recipe.timed:
            found[recipe.output] = ICON_TICKS
    return found
