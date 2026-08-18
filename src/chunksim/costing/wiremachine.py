"""The Dorgesh-Kaan wire machine, which is a stall that can fail.

**The last money-making guide in Thieving, and the page it is about publishes
the whole thing.** `Wire machine` states the level (44), the experience (22 a
steal), the cycle - "After 8 ticks, 5 seconds, the wire respawns and can be
grabbed again (**a total of 10 ticks per wire stolen**)" - and a
`{{Skilling success chart}}` fitted to 23,848 logged attempts. There is nothing
left to estimate, so:

    experience an hour = 6000 / 10 ticks x success chance x 22

### Why a failure costs a whole cycle and not part of one

Failing does not consume the wire, so you can grab again immediately - except
that failing also stuns you, and the Thieving stun is the published **8 ticks**
`costing/pickpocket.py` already spends. Eight ticks of stun and eight ticks of
respawn are the same wait, so a failed attempt costs one machine cycle just as
a successful one does. Both readings agree to within a tick, which is why this
is `13,200 x p` and not a two-term expression pretending to more precision.

### Three checks, and the model is fitted to none of them

    level 99 success chance      98.05%    the change of 8 May 2024 states 98.0%
    level 99 experience an hour  12,943    the page states "around 13,000"
    around 9,000 an hour         level 62  the page calls ~9,000 "more realistic"

The first is the sharp one. That change note - "Thieving success rates have been
increased slightly, from 94.1% at level 99 to 98.0%" - is what says the chart
being read is the *current* one, since the pre-rebalance curve is still quoted
in a hidden comment on the same page and would give 94%.

### What it displaces

`mmg:Money making guide/Stealing cave goblin wire` at a flat 9,240/hr, which is
the last published Thieving rate on any cached map. It is not a bad number - the
page's own prose calls ~9,000 realistic - but it is one number for a method
whose rate nearly doubles across the climb: **7,167/hr where it opens at 44**
against 12,943 at 99. A guide quotes the middle of a curve; this is the curve.

### The general rule, and why one object is the whole of it

A `{{Thieving info}}` box says which of three things its `time` is, in its own
`type` field: a `Pickpocket`'s is the stun timer, a `Stall`'s the restock, and a
`Chest`'s the cycle. Measured over the wiki - 256 pages carry the box, 139 also
carry a success chart, and **34 of those state a `time`** - almost all of the 34
are pickpockets (already `costing/pickpocket.py`'s) or stalls (already the
stalls table's, and 100% success by the skill's own rules). What is left is two
`Chest` rows: this one, and the Aldarin Villas chest, whose `time` is the
picklock action rather than the cycle - failing there teleports you across town,
which is why its own page says 400 an hour at level 60 where 1.8 seconds an
attempt would say 711. That one is priced elsewhere and is not this module's.

Pure: the level comes in as an argument and everything else is stated.
"""

from __future__ import annotations

from typing import Any, Mapping

from chunksim.costing.gathering import CURVE_STEPS, success_chance
from chunksim.costing.heuristics import ComputedMethod

#: What a band calls the activity.
ACTIVITY = "the wire machine"

#: What this labels its rate.
WIRE_MATCH = "modelled"

#: The skill it pays.
SKILL = "Thieving"

#: **The export's own `Objects` entry, which is also the wiki's page title.**
#: `Steal a ~|cave goblin wire|~` names `Wire machine`, so the join is a string
#: equality rather than a read of the task's words.
OBJECT = "Wire machine"

#: The Thieving level it opens at, from the page's `{{Thieving info}}`.
LEVEL = 44

#: Experience one successful steal pays, from the same box.
EXPERIENCE = 22.0

#: Ticks one steal costs, successful or not. **Published**: "After 8 ticks, 5
#: seconds, the wire respawns and can be grabbed again (a total of 10 ticks per
#: wire stolen)". See the module docstring for why a failure costs the same.
CYCLE_TICKS = 10.0

#: The page's own `{{Skilling success chart}}`, `low1`/`high1`, fitted to
#: 23,848 logged attempts. There is only one series: no tool, diary or garment
#: changes this one.
CURVE = (50.0, 250.0)

#: Ticks in an hour.
TICKS_PER_HOUR = 6000.0


def steal_chance(level: int) -> float:
    """The chance one grab succeeds at `level`."""
    return success_chance(level, *CURVE)


def xp_per_hour(level: int) -> float:
    """Thieving experience an hour at the machine, at `level`."""
    return TICKS_PER_HOUR / CYCLE_TICKS * steal_chance(level) * EXPERIENCE


def steps_for(level: int = LEVEL) -> tuple[int, ...]:
    """The levels the rate changes at: its own, and every curve step above.

    No saturation point, because this curve does not reach one - 98.05% at 99
    is where it ends, which is the figure the rebalance note names.
    """
    return (level, *(step for step in CURVE_STEPS if step > level))


def methods(
    challenges: Mapping[str, Any], valid: Mapping[str, Any]
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{skill: bands}` if the map can reach the machine, else `{}`."""
    found: list[ComputedMethod] = []
    for task in sorted(valid or {}):
        challenge = challenges.get(task)
        if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
            continue
        if OBJECT not in (challenge.get("Objects") or ()):
            continue
        found.extend(
            ComputedMethod(
                method=ACTIVITY,
                xp_per_hour=xp_per_hour(step),
                level=step,
                match=WIRE_MATCH,
                knob=f"training/{task}/{SKILL}",
            )
            for step in steps_for()
        )
    return {SKILL: tuple(found)} if found else {}
