"""Rummaging vale offerings, where the totem you built decides the loot rate.

**A reward table whose action this project already prices.** `Vale offerings`
states its own mechanic in one sentence - "rummaging the offerings consumes
**100** of them for one Vale Research Point and **one roll of the loot
table**" - and `Vale Totems/Strategies` states how many offerings a totem
leaves, per log tier: 20 for oak up to 105 for redwood. So the cost of one
`Ent branch` is a chain of published numbers ending in something
`costing/valetotems.py` already computes: what a totem costs once its five
logs are charged.

    seconds per item = totem seconds  x  100 / offerings per totem  /  share

### Why this is a flat cost and not a route

`Ent branch` has three routes in the export and the walk can take none of
them. The reward table is `65/399` - a non-`Always` member, which
`estimate._route_hours`' certainty gate refuses by design, and rightly: it is
the gate that stopped a defaulted pace being multiplied by a real drop chance.
And the `Vale Research Exchange` route is a shop priced in `points`, a
currency `DEFAULT_CURRENCY_PER_HOUR` deliberately refuses to invent a rate
for.

So this is priced the way `costing/yields.py` and `costing/herbs.py` are - a
flat `{item: seconds}` the walk reads before it tries any route - and for the
same reason those are: the pace behind it is real and computed, and routing a
fractional share is what put 2.5 million calls into the fixpoint.

**The pace here is better than a gathering curve, which is what makes the
flat treatment safe.** `valetotems.seconds_per_totem` is not a default: it is
the minigame's own 104 totems an hour plus the *item walk's own* cost of five
logs, so a map that must chop redwood pays for chopping redwood.

### The tier is chosen by what an Ent branch costs, not by what a totem pays

Offerings rise with the log - 20 to 105 - and so does the chopping, so which
tier is cheapest per branch is a property of the map. `costing/valetotems.
fletching_rate` makes the same choice for experience and can land somewhere
else entirely; both are `max`/`min` over the same `affordable` list, which is
why that helper is shared rather than duplicated.

### The shop is the same price and is not modelled

A rummage pays one research point as well as one roll, and the exchange sells
an `Ent branch` for **20** points - twenty rummages, against the roll's
`399/65` = **6.14**. So the drop is 3.3x cheaper and a `points` rate could
never be spent on a branch. The mask is the interesting one: 500 points is 500
rummages and the pre-roll gives one every 500, so the wiki has priced the two
routes identically and this takes the roll for both.

### Two items, hand-picked, because two is what the export needs

`Ent branch` blocks four Fletching methods and `Greenman mask` two of the same
four. The rest of the table - dirty arrowtips, bales of flax, blessed bone
shards, feathers, roots, nests, seeds - is either already routable or wanted
by nothing, and every one carries a *quantity range* (26-32, 400-500) where
these two are flat singles. Adding one is a line; a rule over the table would
be inventing a mean for eleven ranges nobody asked about.

Pure: the valid set, the levels and the item walk come in as arguments.
"""

from __future__ import annotations

from typing import Callable, Mapping

from chunksim.costing import valetotems

#: Offerings one rummage consumes. **Stated**: "rummaging the offerings
#: consumes 100 of them for one Vale Research Point and one roll".
OFFERINGS_PER_RUMMAGE = 100.0

#: `{item: rolls per rummage}` off `Vale offerings`' own tables. Both are
#: quantity-1 rows, which is why only these two are here - see the module
#: docstring.
SHARES: dict[str, float] = {
    # The Resources table, whose six rows are stated out of 399.
    "Ent branch": 65.0 / 399.0,
    # The pre-roll, whose three rows sum to the 1/100 the page names.
    "Greenman mask": 2.0 / 1000.0,
}


def rummages_for(item: str) -> float | None:
    """Rummages one `item` costs on average, or `None` if it is not a reward."""
    share = SHARES.get(item)
    return None if not share else 1.0 / share


def seconds_for(
    item: str,
    level: int,
    material_seconds: Callable[[str, float], float | None] | None,
) -> float | None:
    """Seconds one `item` costs, on the cheapest tier the map can build.

    `None` where the item is not a reward, where no tier is affordable, or
    where nothing routes the logs - the last of which is the ordinary state of
    a map that cannot reach the trees.
    """
    rummages = rummages_for(item)
    if rummages is None:
        return None
    costs = [
        seconds * OFFERINGS_PER_RUMMAGE * rummages / totem.offerings
        for totem, seconds in valetotems.affordable(level, material_seconds)
        if totem.offerings > 0
    ]
    return min(costs) if costs else None


def costs(
    valid: Mapping[str, Mapping[str, object]],
    levels: Mapping[str, int],
    material_seconds: Callable[[str, float], float | None] | None = None,
) -> dict[str, float]:
    """`{item: seconds}` for the rewards a map can actually rummage for.

    **Gated on upstream's own Fletching challenge**, exactly as
    `valetotems.methods` is: what opens the minigame is Fletching 20 and the
    miniquest, and the derivation has already decided whether this map has
    them.
    """
    if valetotems.TASKS["Fletching"] not in (valid.get("Fletching") or {}):
        return {}
    # **Floored at the minigame's own opening level rather than refused below
    # it**, which is `costing/wintertodt.solo_methods`' rule and for its
    # reason: upstream's challenge being valid *is* the statement that this
    # map can play, and a map that can play can build oak totems by
    # definition - oak is the tier the minigame opens at. The export census
    # `chunksim training` runs infers no Fletching level at all, so comparing
    # `1 < 20` there reported a routable material as unroutable.
    level = max(levels.get("Fletching", 1), valetotems.OPENS_AT)
    found: dict[str, float] = {}
    for item in SHARES:
        seconds = seconds_for(item, level, material_seconds)
        if seconds is not None and seconds > 0:
            found[item] = seconds
    return found
