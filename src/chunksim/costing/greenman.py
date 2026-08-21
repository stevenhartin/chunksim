"""A tick cost the wiki leaves blank on one page of a two-page family.

**`Greenman carving`'s `{{Recipe}}` carries no `ticks` parameter**, while
`Greenman statue` - the same action one tier down, an `Ent branch` and a
`Greenman mask` fletched onto a log - states `ticks = 4`. The two differ only
in the log (maple against yew) and the level (53 against 79), and nothing about
a yew log makes a knife slower.

**The figure here is measured rather than inferred**, which is the stronger of
the two and worth saying so: it was timed in game at **4 ticks**, and the
statue's published 4 is then a check on that rather than its source. That is
the relationship `costing/barracuda.py` describes and the opposite of the
inference `costing/yewtree.py` had to settle for, where every sibling was
published and the subject was not.

**A single named output, not a rule over the family.** Matching "recipes whose
sibling states a duration" would need a definition of *sibling*, and 650 of the
corpus's 4,043 recipes state no ticks at all - the net `chisel.py` and
`yewtree.py` both declined to cast, for the reason `heuristics.
SHORTCUT_ALIASES`' word-overlap scorer was refused.

It also has to be Fletching's. `Greenman carving (Construction)` is a different
recipe on a different page - mounting the finished carving in a house - and it
already states 5.

Pure: the recipes come in as an argument.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from chunksim.remote.recipes import Recipe

#: Ticks a greenman carving costs. **Measured in game**, and equal to the
#: `Greenman statue` recipe's published figure for the same action.
GREENMAN_CARVING_TICKS = 4

#: The one output this applies to, spelled as the wiki spells it. Not the
#: `(Construction)` page of the same name, which states its own duration.
GREENMAN_CARVING_OUTPUT = "Greenman carving"


def stated_ticks(recipes: Mapping[str, Sequence[Recipe]]) -> dict[str, float]:
    """`{output: ticks}` for the greenman carving, when the wiki left it blank.

    Keyed by output, matching `chisel.stated_ticks`, `yewtree.stated_ticks` and
    `herblore.stated_ticks`, so they merge in `recipe_rates.stated_ticks`.
    Fletching only, and only where the recipe states no duration of its own: a
    published tick cost is never overwritten by a stated one.
    """
    found: dict[str, float] = {}
    for recipe in recipes.get("Fletching") or ():
        if recipe.ticks is not None:
            continue
        if recipe.output != GREENMAN_CARVING_OUTPUT:
            continue
        found[recipe.output] = float(GREENMAN_CARVING_TICKS)
    return found
