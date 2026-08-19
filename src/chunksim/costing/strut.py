"""Repairing Motherlode Mine struts, where the rate is the world-hopping.

**A method whose own mechanic is not what limits it, and the wiki's table
proves it by accident.** A strut pays `1.5 x` your Smithing level to repair
and breaks on its own timer - "struts work on rounds of 58 seconds ... a strut
will break between 15 and 31 times an hour, giving an absolute maximum of
4,600 experience an hour at 99". Nobody does that. You repair the two struts
on a world, hop, and repair the next pair: "by hopping worlds ... it is
possible to reach much higher rates, with up to **60,000** Smithing experience
per hour at 99 ... by hopping a rotation of between 18 to 22 worlds".

### The table divides out to one number, which is the finding

`Strut` tabulates experience an hour against level, eight rows from 30 to 99.
Divide each by the published `1.5 x level` a repair pays and what is left is
**repairs an hour** - and it barely moves:

    level   xp/repair    band midpoint   implied repairs/hour
      30       45.0          17,500              388.9
      50       75.0          26,500              353.3
      70      105.0          37,500              357.1
      99      148.5          54,000              363.6

**362.4 an hour, within 4.9% across the whole table**, and the same holds at
either end of the bands (306.5 at the bottom, 418.3 at the top). That
constancy is the model: if the hammering were the constraint the figure would
climb with the success chance, which the page states as **12.11% at level 1
rising to 27.73% at 99** - a factor of 2.3 that leaves no trace at all in the
implied rate. What a player is actually waiting for is the hop.

So `REPAIRS_PER_HOUR` is *read out of* the table rather than fitted to it, and
`1.5 x level` is spent as stated. The midpoint is what this takes, and it is
the only reading that lands inside all eight published bands - the top-end
418.3 overshoots level 90 by 540 an hour.

### What the chart is for, and why nothing spends it

`{{Skilling success chart}}`'s `low=30 high=70` reproduces the page's own two
figures exactly - `success_chance(1, 30, 70)` is 31/256 and `(99, ...)` is
71/256, which are 12.11% and 27.73% to the hundredth. It is carried as
`REPAIR_CURVE` because it is the check that this is the right page's chart,
and **not** spent: the hammering it describes is already inside the table this
model reads, and charging it again would bill the same seconds twice.

### The regime, named

The table is the **rotation** - eighteen to twenty-two worlds in a loop - and
the page says plain hopping gets "about half to two-thirds of the experience",
which is below the table entirely. This prices the rotation for the reason
`costing/wintertodt.py` prices the world-hopped boss and `costing/sepulchre.py`
the unlooted floor: the faster published regime is what an hour of the skill
is worth. What it does not model is the ceiling on the whole activity -
"extensive training is limited by reaching the hop limiter within 90 to 120
minutes of continuous world hopping" - which is a bound on the session rather
than on the rate.

Pure: nothing but the valid set comes in.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.costing.gathering import CURVE_STEPS, GATHERING_MATCH
from chunksim.costing.heuristics import ComputedMethod

SKILL = "Smithing"

#: What a band calls the activity.
ACTIVITY = "Motherlode Mine struts"

#: The export's own challenge, which it gates at level 1 as the infobox does.
TASK = "Repair a broken ~|strut|~ in the Motherlode Mine"

#: Experience a repair pays, as a multiple of the level held. **Stated**:
#: `{{Skill info}}`'s `skill1exp = 1.5 x Smithing level`, and the prose again.
EXPERIENCE_PER_LEVEL = 1.5

#: Repairs an hour. **Read out of the published table** rather than fitted to
#: it - see the module docstring for the division and its 4.9% spread.
REPAIRS_PER_HOUR = 362.4

#: The `Strut repair chance` chart. **Carried as a check, never spent** - it
#: reproduces the page's own 12.11% and 27.73% exactly, and the hammering it
#: describes is already inside the hourly table.
REPAIR_CURVE = (30.0, 70.0)

#: The wiki's own table, as `{level: (low, high)}`. The oracle this model is
#: read out of, kept so `tests/test_costing_strut.py` can pin it.
PUBLISHED: dict[int, tuple[float, float]] = {
    30: (14_000.0, 21_000.0),
    40: (18_000.0, 26_000.0),
    50: (22_000.0, 31_000.0),
    60: (27_000.0, 37_000.0),
    70: (32_000.0, 43_000.0),
    80: (37_000.0, 49_000.0),
    90: (42_000.0, 54_000.0),
    99: (48_000.0, 60_000.0),
}

#: What the struts pay if you simply stand at them, which nobody does. The
#: page's own figure, carried so the gap the hopping buys is visible: a strut
#: breaks 15 to 31 times an hour by itself.
STANDING_MAX_PER_HOUR = 4_600.0


def experience_per_repair(level: int) -> float:
    """`1.5 x level`, the whole of what a repair pays."""
    return EXPERIENCE_PER_LEVEL * level


def xp_per_hour(level: int) -> float:
    """Smithing experience an hour repairing struts on a world rotation."""
    return experience_per_repair(level) * REPAIRS_PER_HOUR


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Smithing": bands}` where the map can reach the Motherlode Mine.

    Bands rather than one rate because the *payout* climbs with level while
    the repairs an hour do not - the third axis a level can move, and the same
    shape `costing/tempoross.py`'s repairs and `costing/library.py`'s tomes
    have.
    """
    if TASK not in (valid.get(SKILL) or {}):
        return {}
    return {
        SKILL: tuple(
            ComputedMethod(
                method=ACTIVITY,
                xp_per_hour=xp_per_hour(step),
                level=step,
                match=GATHERING_MATCH,
                knob=f"training/{TASK}/{SKILL}",
            )
            for step in (1, *CURVE_STEPS)
        )
    }
