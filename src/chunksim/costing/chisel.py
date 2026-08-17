"""Chiselling a dark essence block, which the wiki does not time and which costs nothing.

**The `{{Recipe}}` for `Dark essence fragments` carries `ticks = ""`**, and the
item walk's last resort (`estimate._recipe_hours`) stood `DEFAULT_ACTION_SECONDS`
in its place - 2.4 seconds a chisel, 0.6 a fragment, since one block yields
four. That is the right default for an untimed action in general and the wrong
one here, because this action is not performed at a bank: you chisel the blocks
**while running** from the Dark Altar to the blood or soul altar, on a trip the
rune's own recipe is already paying for. The chisel therefore adds no time at
all, and the honest figure is zero.

**Zero is a claim about this activity's geography, not about chiselling.** A gem
cut into bolt tips is a bank action, tick-gated and emphatically not free; so is
every other chisel recipe in the corpus. What makes this one different is that
the route it sits on has dead time in it and the chisel fits inside. That is why
this module names the output rather than reaching for a structural rule over
"recipes whose verb is chisel" - there is no such rule, and inventing one would
hand a bank action the same zero.

**Nothing but the item walk can spend it.** The export carries no challenge whose
`Output` is `Dark essence fragments` - chiselling pays *Crafting*, and upstream
lists only what pays experience in the skill owning the challenge - so a stated
zero can never become a training rate of its own, let alone an infinite one. It
is only ever read while pricing what the fragments are *for*, which is
`Craft a ~|blood rune|~ at the false altar on Zeah` and `Craft a ~|soul rune|~`.

Measured over both cached maps and the uber one, this moves exactly two methods
and no climb at all. On the second cache, where the Dark Altar is the whole
Runecraft story above the low levels, blood runes go 25,802/hr -> 31,316 and
soul runes 32,035 -> 38,880; on the uber map 26,121 -> 31,786 and 32,430 ->
39,464. Both remain a close second to the Arceuus library, which scales with
level and still owns the climb - which is why no band moves, and why this is
coverage for a map holding the altar and not the library rather than a
different answer for the maps that hold both.

Pure: the recipes come in as an argument.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from chunksim.remote.recipes import Recipe

#: Ticks a chisel costs on a run that is already being paid for. See the module
#: docstring for why this one action is free and no other chisel is.
CHISEL_TICKS = 0

#: The one output this applies to, spelled as both upstream and the wiki spell it.
FRAGMENT_OUTPUT = "Dark essence fragments"


def stated_ticks(recipes: Mapping[str, Sequence[Recipe]]) -> dict[str, float]:
    """`{output: ticks}` for the dark essence chisel, when the wiki left it untimed.

    Keyed by output, matching `herblore.stated_ticks`, so the two merge. Crafting
    only, and only where the recipe states no duration of its own: a published
    tick cost is never overwritten by a stated one.
    """
    found: dict[str, float] = {}
    for recipe in recipes.get("Crafting") or ():
        if recipe.ticks is not None:
            continue
        if recipe.output != FRAGMENT_OUTPUT:
            continue
        found[recipe.output] = float(CHISEL_TICKS)
    return found
