"""Two Herblore actions the wiki left untimed in families that publish the rest.

Both are one cell blank on a page whose siblings are filled in -
`costing/gnomecooking.py`'s shape, and `costing/greenman.py`'s before it - and
neither is a guess about a mechanic. What separates them is how many siblings
speak, so they are stated apart rather than under one rule.

### The barbarian potion mix

Adding a fish to a two-dose potion is one action repeated across a family of
**29 recipes, and 28 of them state a duration**: twenty-six at one tick, two at
two, and `Magic essence mix(2)` alone at none. The page's own `{{Recipe}}` has
no `ticks` parameter at all, so this is the wiki being silent rather than this
project failing to read it.

`MIX_TICKS` is the family's one tick. The two outliers are worth naming rather
than averaging away: `Anti-poison supermix(2)` and `Superattack mix(2)` say
two, and nothing about a superantipoison makes a fish slower to add - they read
as transcription noise on a page nobody re-times, and taking the modal 26
rather than the mean of 29 is the conservative reading of that. The figure only
decides `Magic essence mix(2)`, whose 93.6 seconds of materials dwarf either
answer, so the choice moves the rate by under a percent.

### The sanfew serum's two middle steps

A sanfew serum is three combines - a super restore takes unicorn horn dust,
then snake weed, then nail beast nails - and the wiki publishes the last at
**two ticks** while leaving `Mixture - step 1` and `Mixture - step 2` blank.
That the three are one chain is checked by their own experience: 47.5 + 52.5 +
60 is exactly the 160 the collapsed four-material recipe states for the same
serum, on every dose.

**Two recipes describe the serum and each held what the other lacked**: the
stepwise one states two ticks and asks for `Mixture - step 2`, an intermediate
the item walk could not price, while a collapsed one lists all four real
materials and states no duration at all. So the method was dropped either way.

**The collapsed recipe is the one that has to be timed**, because it is the one
the join picks: `_joined` prefers the recipe whose materials agree with the
challenge's own `Items`, and upstream lists the four real ingredients. Its
duration is `SERUM_TICKS`, three combines of `STEP_TICKS` - and three is not an
assumption either, since the steps' experience adds to the collapsed recipe's
exactly: 47.5 + 52.5 + 60 is 160 on every dose.

The two middle steps are timed as well, at the same published two. That does
not price this method - nothing joins them to a challenge - but it makes the
chain walkable, so a sanfew serum can be *bought into* another recipe as a
material rather than reading as unobtainable.

`STEP_TICKS` is the third step's published two. The three combines are the same
action on the same vial, which is the whole of the inference.

Pure: the recipes come in as an argument.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from chunksim.remote.recipes import Recipe

SKILL = "Herblore"

#: Ticks a barbarian potion mix costs. **The modal figure of 26 published
#: siblings** - see the module docstring on the two that say otherwise.
MIX_TICKS = 1

#: The one mix the wiki leaves blank, spelled as the recipe spells it.
UNTIMED_MIX = "Magic essence mix(2)"

#: Ticks one combine of the sanfew serum chain costs, **published** on its
#: third step and stated here for the first two.
STEP_TICKS = 2

#: The two intermediates, without their dose suffix. Every dose of each is
#: untimed, and the third step - the serum itself - states two.
STEP_PREFIXES: tuple[str, ...] = ("Mixture - step 1(", "Mixture - step 2(")

#: How many combines the collapsed recipe rolls into one row. Checked by the
#: steps' experience summing to its own, not assumed from the material count.
SERUM_STEPS = 3

#: Ticks the collapsed sanfew serum recipe costs: three combines of
#: `STEP_TICKS`.
SERUM_TICKS = SERUM_STEPS * STEP_TICKS

#: The collapsed recipe's output, without its dose suffix.
SERUM_PREFIX = "Sanfew serum("


def stated_ticks(recipes: Mapping[str, Sequence[Recipe]]) -> dict[str, float]:
    """`{output: ticks}` for both, where the wiki states no duration.

    Keyed by output, matching the other contributors so they merge in
    `recipe_rates.stated_ticks`. Herblore only, and only untimed recipes: a
    published tick cost is never overwritten by a stated one.
    """
    found: dict[str, float] = {}
    for recipe in recipes.get(SKILL) or ():
        # **A stated `0` is not a published duration** - `Recipe.timed` is the
        # test, not `ticks is not None`.
        if recipe.timed:
            continue
        output = recipe.output
        if output == UNTIMED_MIX:
            found[output] = float(MIX_TICKS)
        elif output.startswith(STEP_PREFIXES):
            found[output] = float(STEP_TICKS)
        elif output.startswith(SERUM_PREFIX):
            # Only the collapsed row reaches here: the stepwise recipe for the
            # same output states its two ticks and is `timed`, so it is
            # skipped above and keeps its published figure.
            found[output] = float(SERUM_TICKS)
    return found
