"""Tempoross, priced from the wiki's own table rather than from a tier guess.

**This replaces three invented numbers with twenty published ones**, and the
shape of the error is what makes it worth a module. `costing/stated.py` used to
carry Tempoross as one figure per harpoon tier - 100,000 for crystal or
infernal, 85,000 for dragon, 80,000 for a plain one - marked `guess` and flat
across the whole climb. Against the wiki's table that is wrong twice over: a
plain harpoon at level 35 is **30,000**, not 80,000, and crystal and infernal
are 95,000 and 76,000 rather than one number for both.

What the wiki publishes is a rate for each of four harpoons at five levels,
which is what `RATES` carries. Every cell is read; nothing here is fitted or
interpolated between them beyond holding a point until the next one, which is
what `units_at` does everywhere else in this project.

### Why the published table and not the published formulas

The page also gives the experience of every action exactly - a harpoonfish is
`floor(450 + 550 * (level - 35) / 64) / 100` below level 70 and
`floor(890 + 110 * (level - 70) / 29) / 100` above it, with the ammunition
crate ten times that and the spirit pool eleven - so it is tempting to derive
the hourly rate instead. **It does not work, and measuring says why.** Every
action's experience is proportional to one `base`, so if the *count* of actions
were level-free the rate would be too. Dividing the published column by `base`:

    level 35   30,000 / 450  = 66.7
    level 70   62,000 / 890  = 69.7
    level 90   68,000 / 965  = 70.5
    level 99   74,000 / 1000 = 74.0

It climbs, so the catching gets faster as well as richer, and nothing publishes
that second curve. The formulas therefore check the *shape* and cannot produce
the rate, which is why this is a transcription and says so.

### The harpoon

**The best tier the map holds and the level can wield**, which is the reading
`gathering.best_tool` takes of an axe - a crystal harpoon in a reachable chunk
is not a crystal harpoon at level 60. The gates are the items' own: 61 Fishing
for a dragon harpoon, 71 for a crystal one, 75 for an infernal one, and none
for a plain or barb-tail harpoon. They are exactly where the wiki's table goes
`N/A`, which is the check on them.

Best is decided **by rate rather than by tier order**, because the tiers are not
ordered: an infernal harpoon is better than a dragon one and worse than a
crystal one at every level, and a list would have to encode that twice.

### Not cooking

The wiki tabulates two regimes and this prices the faster: "not cooking the
harpoonfish means getting lower amounts of points/loot but significantly more
experience". Cooking pays about a third less Fishing and some Cooking, and the
export carries no Cooking challenge for Tempoross to hang that on.

Pure: the level and the reachable set come in as arguments.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from chunksim.costing.gathering import CONFIRMED, CURVE_STEPS, units_at
from chunksim.costing.heuristics import ComputedMethod

#: The export's own name for the catch, and the level Tempoross opens at.
TASK = "Catch fish at ~|Tempoross|~"
OPENS_AT = 35

SKILL = "Fishing"

#: Harpoon -> the Fishing level it needs, and its `(level, xp/hr)` points from
#: the wiki's **Not cooking** table. The plain and barb-tail harpoons share a
#: row because the page says they do: "the standard harpoon, the barb-tail
#: harpoon, and Barbarian Fishing all have the same experience rates".
RATES: dict[str, tuple[int, tuple[tuple[int, float], ...]]] = {
    "Harpoon": (
        1,
        ((35, 30_000.0), (70, 62_000.0), (80, 65_000.0), (90, 68_000.0), (99, 74_000.0)),
    ),
    "Barb-tail harpoon": (
        1,
        ((35, 30_000.0), (70, 62_000.0), (80, 65_000.0), (90, 68_000.0), (99, 74_000.0)),
    ),
    "Dragon harpoon": (
        61,
        ((70, 66_000.0), (80, 69_000.0), (90, 72_000.0), (99, 74_000.0)),
    ),
    "Crystal harpoon": (
        71,
        ((70, 77_000.0), (80, 85_000.0), (90, 92_000.0), (99, 95_000.0)),
    ),
    "Infernal harpoon": (
        75,
        ((80, 71_000.0), (90, 74_000.0), (99, 76_000.0)),
    ),
}


def harpoon_rate(harpoon: str, level: int) -> float:
    """What one harpoon pays at `level`, or `0.0` if it cannot be used yet."""
    entry = RATES.get(harpoon)
    if entry is None:
        return 0.0
    needs, points = entry
    if level < needs or level < points[0][0]:
        return 0.0
    return units_at(points, level)


def best_harpoon(level: int, available: frozenset[str]) -> tuple[str, float]:
    """The reachable harpoon paying most at `level`, and what it pays.

    By rate rather than by tier, because the tiers are not ordered - see the
    module docstring. `("", 0.0)` where the map holds none, which the caller
    must read as "cannot price" rather than as the worst one.
    """
    best, paid = "", 0.0
    for harpoon in sorted(RATES):
        if harpoon not in available:
            continue
        rate = harpoon_rate(harpoon, level)
        if rate > paid:
            best, paid = harpoon, rate
    return best, paid


def rate_at(level: int, available: frozenset[str]) -> float:
    """Fishing experience an hour at `level` with the best harpoon held."""
    if level < OPENS_AT:
        return 0.0
    return best_harpoon(level, available)[1]


def methods(
    valid: Mapping[str, Mapping[str, object]],
    available: frozenset[str] | None = None,
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Fishing": (...)}` where a map can reach Tempoross and hold a harpoon.

    Banded, and the harpoon is re-chosen at every step for the reason
    `gathering.priced_methods` re-chooses an axe: a map holding a crystal
    harpoon swings a plain one until 71, and that is a real band edge.
    """
    if TASK not in (valid.get(SKILL) or {}):
        return {}
    held = available or frozenset()
    levels: Sequence[int] = (
        OPENS_AT,
        *(step for step in CURVE_STEPS if step > OPENS_AT),
    )
    bands = tuple(
        ComputedMethod(
            method=f"Tempoross ({best_harpoon(level, held)[0].lower()})",
            xp_per_hour=rate_at(level, held),
            level=level,
            match=CONFIRMED,
            knob=f"training/{TASK}/{SKILL}",
        )
        for level in levels
        if rate_at(level, held) > 0
    )
    return {SKILL: bands} if bands else {}
