"""Durations somebody timed in game, where the wiki states none.

**The last resort before a method stays unpriced, and the honest one.** A
recipe with no `ticks` is refused rather than read as instant
(`recipe_rates.ticks_for`), and every other module that fills one has an
argument from published data - `costing/yewtree.py` borrows from five
siblings that all state the same figure, `costing/feathering.py` from four,
`costing/gnomecooking.py` from three, `costing/herblore.py` counts a bank
cycle out of its parts. This module has none of that. What it has is a
stopwatch.

**`costing/greenman.py` is the same shape and predates it**, and the
difference is what a sibling had to say:

    output        ticks   experience   nearest published sibling
    Nettle tea      4         52.0      `Damiana tea`, 3 ticks
    Swamp paste     4          2.0      none - it has no family at all

**The tea's sibling disagrees by a tick, and the measurement still wins.**
`Damiana tea` is the same shape of action - a flavoured water heated into a
tea - and its `{{Recipe}}` states 3. What decides it is that the measurement
is of *this* action and the sibling's figure is of another one; a one-tick
difference between two similar cooks is ordinary, and borrowing across pages
is what `costing/yewtree.py` does only where every sibling agrees. The
disagreement is recorded rather than smoothed over, because it is the first
thing to look at if anyone re-times either.

**A measurement is evidence and it is one person's**, so it is worth saying
what would overturn it: a `{{Recipe}}` gaining a `ticks` field. `stated_ticks`
fills only where the wiki is blank, so the day either page is timed upstream
the published figure wins and this entry goes quiet with nothing edited -
which is the same promise `costing/disclaimed.py` makes about its own.

**Both are slow and that is the answer rather than a worry.** Priced end to
end the tea reads about 24,800/hr and the paste about 820, because the paste
pays 2 experience for an action that eats a pot of flour and a swamp tar.

Pure: the recipes come in as an argument.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from chunksim.remote.recipes import Recipe

SKILL = "Cooking"

#: `{output: ticks}`, each timed in game. See the module docstring for why
#: neither could be filled from a sibling.
MEASURED_TICKS: dict[str, float] = {
    "Nettle tea": 4.0,
    "Swamp paste": 4.0,
}


def stated_ticks(recipes: Mapping[str, Sequence[Recipe]]) -> dict[str, float]:
    """`{output: ticks}` for the outputs above the wiki left untimed.

    Only the untimed ones: a recipe that states a tick cost keeps it, so a
    measurement can never overwrite a published figure.
    """
    found: dict[str, float] = {}
    for recipe in recipes.get(SKILL, ()):
        ticks = MEASURED_TICKS.get(recipe.output)
        if ticks is not None and not recipe.timed:
            found[recipe.output] = ticks
    return found
