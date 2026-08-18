"""A tick cost the wiki states on every sibling page and leaves off this one.

**`Yew tree (Construction)`'s `{{Recipe}}` carries no `ticks` parameter at
all**, while every other garden tree it sits beside on the same POH page
does: `Oak`/`Willow`/`Maple`/`Magic`/`Spirit tree (Construction)` are all
`ticks = 5`, and the mechanic is identical across the family - plant a
bagged tree grown elsewhere, same object, same action. There is nothing
about yew that would make it slower or faster than magic; the wiki has
simply left one cell blank on one page in a family it fills everywhere
else.

**A single hand entry, not a rule over the family**, for the same reason
`chisel.py` names one output rather than a verb: matching "recipes whose
sibling states a duration" as a general pattern would need to define what a
sibling *is*, and 650 of the corpus's 4,043 recipes carry no stated ticks -
far too broad a net to trust without checking each one, which is exactly
the shape of guess `heuristics.SHORTCUT_ALIASES`' rejected word-overlap
scorer was refused for.

Pure: the recipes come in as an argument.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from chunksim.remote.recipes import Recipe

#: Ticks a yew tree costs, read off every sibling recipe on the same page.
#: See the module docstring - `Magic_tree_(Construction)` is the one checked.
YEW_TREE_TICKS = 5

#: The one output this applies to, spelled as the wiki spells it.
YEW_TREE_OUTPUT = "Yew tree (Construction)"


def stated_ticks(recipes: Mapping[str, Sequence[Recipe]]) -> dict[str, float]:
    """`{output: ticks}` for the yew tree, when the wiki left it untimed.

    Keyed by output, matching `chisel.stated_ticks` and `herblore.
    stated_ticks`, so the three merge in `recipe_rates.stated_ticks`.
    Construction only, and only where the recipe states no duration of its
    own: a published tick cost is never overwritten by a stated one.
    """
    found: dict[str, float] = {}
    for recipe in recipes.get("Construction") or ():
        if recipe.ticks is not None:
            continue
        if recipe.output != YEW_TREE_OUTPUT:
            continue
        found[recipe.output] = float(YEW_TREE_TICKS)
    return found
