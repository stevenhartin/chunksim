"""The Giants' Foundry, from Jagex's own two columns.

**The whole of Smithing's climb above level 15 is this activity**, and the six
figures `wiki:Giants' Foundry` carries for it are not a guide's estimate - they
are Jagex's release patch notes, reproduced on the wiki as an "Alloy tier
comparison" of swords an hour against average experience a sword. Multiplying
the two columns gives the scraped rate exactly, on all five tiers:

    tier      swords/h   xp/sword   product   scraped
    Lowest        20       2,400     48,000    48,000
    Low           17       5,000     85,000    85,000
    Medium        15       9,000    135,000   135,000
    High          13      15,000    195,000   195,000
    Highest       12      23,000    276,000   276,000

So this changes no number at all, and that is the honest description of it. It
is worth having for the reason `costing/courses.py` is: a rate that is two
published columns multiplied can be followed through a game update, where a
figure copied out of a guide has to be noticed. The Colossal Wyrm courses are
the standing evidence that this is not hypothetical - their guide rate was a
year stale and nothing in the project could tell.

**Six challenges, five tiers.** Bronze and iron share the lowest tier, which
is upstream's grouping and Jagex's: the table has five rows and the export has
a preform per metal.

### What this does not touch, and why the number below it looks wrong

`Smelt a ~|gold bar|~` reads about 14,000 an hour where the same wiki page's
training comparison says gold at the Blast Furnace is ~150,000 without
goldsmith gauntlets and ~375,000 with. That is not a missing model. There is
no Blast Furnace *smelting* challenge in the export at all - it carries the
furnace's ancillary jobs, the pedals for Agility and the pump for Strength -
because smelting there is the same `Smelt a ~|X bar|~` task as smelting
anywhere. The difference between the two figures is entirely the one
`costing/__init__.py` describes: a guide quotes the method with its bars to
hand, and `recipe_rates` charges you for getting them. On a chunk-restricted
map the second is usually the truthful half, which is why the layering puts a
recipe *below* a guide rather than above it.

Pure: nothing but the valid set comes in.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.costing.gathering import CONFIRMED
from chunksim.costing.heuristics import ComputedMethod

SKILL = "Smithing"

#: Alloy tier -> `(swords an hour, average experience a sword)`, Jagex's own
#: comparison table as the wiki reproduces it.
TIERS: dict[str, tuple[float, float]] = {
    "Lowest": (20.0, 2_400.0),
    "Low": (17.0, 5_000.0),
    "Medium": (15.0, 9_000.0),
    "High": (13.0, 15_000.0),
    "Highest": (12.0, 23_000.0),
}

#: The export's preform challenge -> `(Smithing level, alloy tier)`. Bronze and
#: iron share the lowest tier, which is Jagex's grouping and upstream's.
PREFORMS: dict[str, tuple[int, str]] = {
    "Forge a bronze ~|preform|~ in the Giants' Foundry": (15, "Lowest"),
    "Forge an iron ~|preform|~ in the Giants' Foundry": (15, "Lowest"),
    "Forge a steel ~|preform|~ in the Giants' Foundry": (30, "Low"),
    "Forge a mithril ~|preform|~ in the Giants' Foundry": (50, "Medium"),
    "Forge an adamant ~|preform|~ in the Giants' Foundry": (70, "High"),
    "Forge a rune ~|preform|~ in the Giants' Foundry": (85, "Highest"),
}


def rate_for(tier: str) -> float:
    """Experience an hour for one alloy tier: swords an hour times what one pays.

    No level in it. What a level buys here is *a better alloy*, which is why
    each preform carries its own opening level instead.
    """
    swords, paid = TIERS.get(tier, (0.0, 0.0))
    return swords * paid


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Smithing": (...)}` for whichever preforms a map can reach."""
    reachable = valid.get(SKILL) or {}
    bands = tuple(
        ComputedMethod(
            method=f"Giants' Foundry ({tier.lower()} alloy)",
            xp_per_hour=rate_for(tier),
            level=level,
            match=CONFIRMED,
            knob=f"training/{task}/{SKILL}",
        )
        for task, (level, tier) in sorted(PREFORMS.items(), key=lambda kv: kv[1][0])
        if task in reachable
    )
    return {SKILL: bands} if bands else {}
