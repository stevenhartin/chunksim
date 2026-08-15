"""Herbiboar, which is a puzzle rather than a loop.

**Nothing about it fits the node model and it should not be made to.** There is
no success chance - a trail either gets solved or you misread it - no roll
interval, and no tool tier. What there is, is a *rate of trails per hour* and a
published experience figure that rises with Hunter level, and those two
multiplied are the whole method. So it stays out of `gathering.PROFILES`
entirely and is produced here, the way `costing/implings.py` is: beside the
gathering walk, not inside it.

**The experience half is read and the rate half is stated.** The `Herbiboar`
article tabulates what a catch pays at every level from 74 to 99 - 1,950 at 80,
rising 30 a level to 2,370 at 94, then more slowly to 2,461 at 99 - and that
table is what makes this worth doing at all, because the scraped guide rate is
one number applied flat across a twenty-level stretch over which the experience
moves 26%. `CATCHES_PER_HOUR` is the other half and is a choice rather than a
reading; see it for what that costs.

The reachability gate is upstream's, as it is for Puro-Puro: the challenge
carries `Chunks: ["Herbiboar[+]"]`, so a map without the island never sees it.

Pure: the table and the level come in as arguments.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from chunksim.costing.gathering import CURVE_STEPS, Tables
from chunksim.costing.heuristics import ComputedMethod

#: The export's own name for the method, and its reachability gate.
HERBIBOAR_TASK = "Track a ~|herbiboar|~"

#: Trails solved in an hour.
#:
#: **The one number here that is not read off a page**, and it is a round one.
#: Nothing publishes trails per hour; what the wiki publishes is 137,000
#: experience an hour, which against 2,461 experience at level 99 implies 55.7.
#: Sixty is the figure asked for and is what this ships, so the top of the
#: climb reads about 8% above the guide it is otherwise built from - which is
#: the trade: the level *shape* becomes right, and the anchor moves a little.
#: Setting this to 55.7 would reproduce the guide exactly at 99 instead.
CATCHES_PER_HOUR = 60.0

#: The level the export's challenge opens at, and the first level the table
#: covers that a player can actually be at for this activity.
HERBIBOAR_OPENS = 80


def experience_at(table: Mapping[int, float], level: int) -> float:
    """What one herbiboar pays at `level`, or `0.0` off the end of the table.

    The table is exhaustive between 74 and 99, so this is a lookup rather than
    an interpolation - inventing a value between two published ones would be a
    guess wearing a citation.
    """
    return table.get(int(level), 0.0)


def methods(
    tables: Tables, valid: Mapping[str, Mapping[str, object]]
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Hunter": (...)}` for herbiboar, or `{}` where it is out of reach.

    Emitted as `ComputedMethod`s rather than as `NodeRate`s because there is no
    node: nothing here has a chance, an interval or a tool, and shaping it like
    the things that do would invite a reader to compare them.
    """
    if HERBIBOAR_TASK not in (valid.get("Hunter") or {}):
        return {}
    if not tables.herbiboar_xp:
        return {}
    levels: Sequence[int] = (
        HERBIBOAR_OPENS,
        *(step for step in CURVE_STEPS if step > HERBIBOAR_OPENS),
    )
    found = [
        ComputedMethod(
            method="herbiboar",
            xp_per_hour=experience_at(tables.herbiboar_xp, level) * CATCHES_PER_HOUR,
            level=level,
            match="modelled",
            knob=f"training/{HERBIBOAR_TASK}/Hunter",
        )
        for level in levels
        if experience_at(tables.herbiboar_xp, level) > 0
    ]
    return {"Hunter": tuple(found)} if found else {}
