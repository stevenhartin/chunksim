"""Hunters' loot sacks, where the export's share is *per roll* and a sack is
several.

**One rumour is one sack, and opening a sack rolls the table many times.** The
count is published per tier and it is not a detail:

| Sack | Rolls | Wiki's own sentence |
|---|---|---|
| basic | 5 | "Opening them rolls 5 times on the loot table" |
| adept | 7 | "Opening them rolls 7 times for resources" |
| expert | 9 | "Opening them rolls 9 times for resources" |
| master | 11 | "Opening them rolls 11 times for resources" |

The export records the share of **one roll** - `Hunter spear tips` is `1/7` in
the basic sack - and the wiki's own rarity column writes the pair out as
`5 x 1/7`, which is how the two are known to be the same number seen twice.
Read as a per-open chance the export's figure undercounts a sack by five to
eleven times.

    seconds per item = seconds per rumour / (rolls x share x mean quantity)

### Why this is a flat cost and not a route

`Hunter spear tips` has one route in the export and the walk cannot take it.
Upstream models the chain properly - `Complete a novice ~|Hunters' Rumour|~`
outputs a `Hunters' loot sack (basic)`, and `Hunters' loot sack (basic) loot*`
consumes that sack and outputs the *table* - so `estimate._route_hours` meets
its `task:` branch with `made != item` and refuses twice over: nothing states
how long opening a sack takes, and `1/7` is not `Always`. Both refusals are
right, and both are the ones `costing/valeoffering.py` and `costing/yields.py`
already stand in for. So this is the same flat `{item: seconds}` the walk reads
before it tries any route, for the same reason: the pace behind the share is
computed rather than defaulted, and routing a fractional quantity is what put
2.5 million calls into the fixpoint.

### The pace is inherited, and it is the one number here that is invented

`costing/rumours.py` prices the *experience* of a rumour exactly - the payout
is a stated formula - and admits that `RUMOURS_PER_HOUR` is a guess, because no
page tabulates assignment, travel, catch or return. This module spends that
guess and adds nothing to it: every other term is published. **The one number
to change is still `rumours.RUMOURS_PER_HOUR`**, and changing it scales these
costs inversely and nothing else.

That is a weaker footing than the two modules beside it, whose paces are the
wiki's own - so it is worth knowing what it can decide. Today: nothing.
`Make a ~|hunter's spear|~` is 9.5 experience for five tips, five jerboa tails
and a teak log, which lands three orders of magnitude below every Fletching
climb on all three maps. A `yield_seconds` entry is a *material* cost rather
than a rate, so it has no provenance channel to carry the guess on; naming it
here is the whole of the disclosure.

### One item, because one is what the export needs

Measured over all four sacks: 31 distinct members, and exactly **one** is
consumed by a `Primary` training method anywhere in the export. The other ten
unrouted members feed only non-primary challenges - the four `Guild hunter`
armour pieces, the two quetzal whistle blueprints, the huntsman's kit, the
`Quetzin` pet, `Quetzal feed` and an empty bird nest - which no costing layer
ever asks about. The remaining twenty already route (logs, herbs, raw meat,
blessed bone shards, coins). This is `valeoffering.py`'s "two items,
hand-picked, because two is what the export needs" arriving a second time, and
it is a measurement rather than a preference: widening it would price ten
things nobody asks for and change nothing.

**The rows this multiplies are the resource rows and only those.** A sack's
uniques sit outside the roll loop - the wiki writes the armour as a flat
`1/50` where a resource carries the `N x` prefix - so `rolls` is applied only
where the export's share matches the tier's own resource share, which is what
`_resource_share` reads off the table rather than hard-coding.

### Charging the whole rumour is the pessimistic reading, deliberately

A player running rumours for Hunter experience gets the tips for nothing. The
walk bills the entire rumour against them anyway, because a Fletching climb has
no reason to assume a Hunter one is happening - and `training.
effective_xp_per_hour` credits a material's experience back only when it pays
**the same skill**, which a rumour does not.

Pure: the valid set comes in as an argument, the shares off the export.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from chunksim.costing import rumours
from chunksim.model.rates import parse_quantity, parse_ratio
from chunksim.model.summary import _mapping

#: The item this exists for. See the docstring: it is the only member of any
#: sack that a `Primary` training method consumes.
ITEM = "Hunter spear tips"

#: `(rumour task, sack loot table, rolls per open)`, worst tier last. The task
#: is upstream's own and gates the tier: a map that cannot complete a master
#: rumour cannot open a master sack.
SACKS: tuple[tuple[str, str, float], ...] = (
    ("Complete a novice ~|Hunters' Rumour|~", "Hunters' loot sack (basic) loot", 5.0),
    ("Complete an adept ~|Hunters' Rumour|~", "Hunters' loot sack (adept) loot", 7.0),
    ("Complete an expert ~|Hunters' Rumour|~", "Hunters' loot sack (expert) loot", 9.0),
    ("Complete a master ~|Hunters' Rumour|~", "Hunters' loot sack (master) loot", 11.0),
)


def _resource_share(table: Mapping[str, Any]) -> float:
    """The share one roll gives a resource row of `table`.

    **Read rather than stated**, so a re-fetched export keeps working. A sack's
    resource rows all carry the same share - it is `1/N` over the N things a
    roll can produce - and its uniques carry their own flat rarities outside
    the roll loop, so the *most common* share in the table is the resource one.
    Ties cannot happen: a tier has more resource rows than uniques on all four.
    """
    counts: dict[float, int] = {}
    for quantities in table.values():
        if not isinstance(quantities, dict):
            continue
        for raw in quantities.values():
            share = parse_ratio(str(raw))
            if share == share and 0 < share <= 1:  # not NaN
                counts[share] = counts.get(share, 0) + 1
    return max(counts, key=lambda share: counts[share]) if counts else 0.0


def seconds_for(chunk_info: Any, valid: Mapping[str, Mapping[str, Any]]) -> float | None:
    """Seconds per `ITEM`, over the cheapest rumour tier this map can run."""
    reachable = valid.get("Hunter") or {}
    tables = _mapping(chunk_info.skill_items, "Nonskill")
    per_rumour = 3600.0 / rumours.RUMOURS_PER_HOUR
    best: float | None = None
    for task, name, rolls in SACKS:
        if task not in reachable:
            continue
        table = _mapping(tables, name)
        quantities = table.get(ITEM)
        if not isinstance(quantities, dict):
            continue
        resource = _resource_share(table)
        for count, raw in quantities.items():
            share = parse_ratio(str(raw))
            yielded = parse_quantity(str(count))
            # **Only a resource row is multiplied.** A unique's rarity is
            # already the per-open figure; scaling it by the roll count would
            # claim a 1/50 hat drops one open in ten.
            if share != resource or yielded is None or yielded <= 0:
                continue
            per_open = rolls * share * yielded
            if per_open <= 0:
                continue
            seconds = per_rumour / per_open
            if best is None or seconds < best:
                best = seconds
    return best


def costs(chunk_info: Any, valid: Mapping[str, Mapping[str, Any]]) -> dict[str, float]:
    """`{item: seconds}` to merge into `_Walk.yield_seconds`, or empty."""
    seconds = seconds_for(chunk_info, valid)
    return {ITEM: seconds} if seconds is not None else {}
