"""The one gnome crunchy the wiki forgot to time.

**Three of four siblings are published and one is blank.** A crunchy is
finished by using its last ingredient on the unfinished sheet, and the
`{{Recipe}}` for each states the same one tick:

    Toad crunchies       1 tick   <- Unfinished crunchy (toad), Equa leaves
    Spicy crunchies      1 tick   <- Unfinished crunchy (spicy)
    Chocchip crunchies   1 tick   <- Unfinished crunchy (chocchip), Chocolate dust
    Worm crunchies       -        <- Unfinished crunchy (worm)

so `recipe_rates.rate_for` refused the fourth and `Bake ~|worm crunchies|~`
read `unpriced` beside three identical methods that did not.

**Named rather than ruled**, for `costing/chisel.py`'s reason: 650 of the
corpus's 4,043 recipes carry no stated duration and resemblance is not
evidence. What makes this one safe is that the family is small, closed and
uniform - four crunchies on one page, one action, and the three that are timed
agree - which is exactly the argument `costing/yewtree.py` makes for the yew
tree against its five POH siblings, and `costing/greenman.py` makes in reverse
for a carving whose sibling is published and whose own figure was measured.

**It fills only where the wiki is blank**, so a published figure can never be
overwritten - see `stated_ticks`, which is where this is merged with the other
contributors.

Pure: the recipes come in as an argument.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from chunksim.remote.recipes import Recipe

SKILL = "Cooking"

#: What every timed crunchy in the corpus states.
CRUNCHY_TICKS = 1.0

#: The one output this applies to, spelled as the wiki spells it.
CRUNCHY_OUTPUT = "Worm crunchies"

#: The three that carry the figure this borrows. Named so a reader can check
#: them, and so a game update that retimes the family shows up as a test
#: failure rather than as a silent inheritance.
TIMED_SIBLINGS: tuple[str, ...] = (
    "Toad crunchies",
    "Spicy crunchies",
    "Chocchip crunchies",
)


def stated_ticks(recipes: Mapping[str, Sequence[Recipe]]) -> dict[str, float]:
    """`{output: ticks}` for the worm crunchy, when the wiki left it untimed.

    Only the untimed one: a recipe that states a tick cost keeps it, so this
    can never overwrite a published figure with a borrowed one.
    """
    for recipe in recipes.get(SKILL, ()):
        if recipe.output == CRUNCHY_OUTPUT and not recipe.timed:
            return {CRUNCHY_OUTPUT: CRUNCHY_TICKS}
    return {}
