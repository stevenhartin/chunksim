"""Hunters' Rumours, where the experience is exact and the pace is not.

**The payout is a formula, not a table**, and it is stated outright:

    experience = (Hunter level + 5) x modifier

with the modifier 50 for a Novice or Adept rumour, 55 for an Expert one and 60
for a Master one, and the level being the one held *after* the turn-in. That
reproduces the wiki's own reward table exactly at both ends - a Master rumour
is quoted as 5,760-6,240, which is `(91 + 5) x 60` and `(99 + 5) x 60` - so
nothing here is fitted and nothing is approximated.

**What no page states is how many rumours an hour**, and that is the whole
difference between this module and `costing/herbiboar.py`, where a published
137,000/hr anchored the pace. Here the throughput is the entire answer and
nothing constrains it: a rumour is assigned, travelled to, caught and returned,
and none of those four is tabulated anywhere.

So `RUMOURS_PER_HOUR` is a **guess**, it is marked as one on every rate this
produces, and it is deliberately conservative. It is the one number to change,
and changing it scales every tier linearly - there is no other moving part.

Pure: the level and the tier come in as arguments.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.costing.gathering import CURVE_STEPS, GUESS
from chunksim.costing.heuristics import ComputedMethod

#: `(task, modifier)` per tier, and the level the export opens each at.
TIERS: tuple[tuple[str, float, int], ...] = (
    ("Complete a novice ~|Hunters' Rumour|~", 50.0, 46),
    ("Complete an adept ~|Hunters' Rumour|~", 50.0, 57),
    ("Complete an expert ~|Hunters' Rumour|~", 55.0, 72),
    ("Complete a master ~|Hunters' Rumour|~", 60.0, 91),
)

#: Added to the Hunter level before the modifier multiplies it.
LEVEL_BONUS = 5

#: Rumours turned in per hour.
#:
#: **The only invented number in this module, and it decides everything.** A
#: rumour is assigned, travelled to, caught and returned, and no page tabulates
#: any of those four - so unlike herbiboar, where a published hourly figure
#: pinned the pace, there is nothing here to check against. Twelve is a
#: deliberately cautious reading of a five-minute round trip; every rate this
#: module produces is marked `GUESS` because of it, and doubling this doubles
#: them all.
RUMOURS_PER_HOUR = 12.0


def experience_at(level: int, modifier: float) -> float:
    """What one rumour of this tier pays at `level`. Exact, not fitted."""
    return (level + LEVEL_BONUS) * modifier


def methods(
    valid: Mapping[str, Mapping[str, object]]
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Hunter": (...)}` for every rumour tier a map can reach.

    Emitted as `ComputedMethod`s rather than `NodeRate`s, as herbiboar is:
    there is no node, no chance and no interval, so shaping it like the things
    that have all three would invite a comparison that does not hold.
    """
    reachable = valid.get("Hunter") or {}
    found: list[ComputedMethod] = []
    for task, modifier, opens in TIERS:
        if task not in reachable:
            continue
        for level in (opens, *(step for step in CURVE_STEPS if step > opens)):
            found.append(
                ComputedMethod(
                    method=f"{task.split()[2]} rumour",
                    xp_per_hour=experience_at(level, modifier) * RUMOURS_PER_HOUR,
                    level=level,
                    match=GUESS,
                    knob=f"training/{task}/Hunter",
                )
            )
    return {"Hunter": tuple(found)} if found else {}
