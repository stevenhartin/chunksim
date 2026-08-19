"""The Blast Furnace pump: two Strength experience a tick, and nothing else.

**The simplest mechanic this project prices, and the only one with no roll, no
material and no level curve at all.** `Pump (Blast Furnace)` states the whole
of it: "operating the pump yields **2 Strength experience every tick**", it
"can be operated for up to 100 minutes before automatically stopping", and it
"is used to train Strength for **12,000 experience per hour** without gaining
any Hitpoints experience". Six thousand ticks an hour times two is that figure
exactly, so the page's own rate and its own mechanic are the same arithmetic
and there is nothing here to fit.

**The hundred minutes is why it stays flat.** One reclick every hour and forty
minutes is not a cadence, it is a rounding error - which is what makes this
one of the few methods in the game whose rate does not move with level, gear,
or how hard you concentrate. `{{Skill info}}` states the level as 30 and
upstream agrees.

### The one thing that can stop it, named rather than modelled

"In order to receive experience, the Blast Furnace must be filled with
[[Coke]]. In the event that the Blast Furnace is empty, experience gains will
be halted until it is filled" - and the page draws its own conclusion,
"achieving the maximum theoretical experience rate is unlikely". So 12,000 is
a **ceiling**, in `costing/trawler.py`'s sense: every term in it is published
and the assumption on top - that somebody keeps the furnace stoked - is not
checkable from anything the wiki states. It is carried as `CONFIRMED` rather
than `GUESS` because nothing here is invented; what is unmodelled is a
dependency on other players, which is the same assumption
`costing/wintertodt.py` makes about a world with people in it.

**No Hitpoints experience**, which the page names as the point of the method
and which this project has no way to represent - `costing/combat_xp.py`'s
rates carry a Hitpoints share and this one would carry none. Worth knowing
before comparing the two.

Pure: nothing but the valid set comes in.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.costing.gathering import CONFIRMED
from chunksim.costing.heuristics import ComputedMethod

SKILL = "Strength"

#: What a band calls the activity.
ACTIVITY = "Blast Furnace pump"

#: The export's own challenge.
TASK = "Operate the pump at the ~|Blast Furnace|~"

#: Strength level it opens at, per `{{Skill info}}` and upstream alike.
LEVEL = 30

#: Experience a tick. **Stated**, and the whole model.
EXPERIENCE_PER_TICK = 2.0

#: Ticks in an hour.
TICKS_PER_HOUR = 6000.0


def xp_per_hour() -> float:
    """Strength experience an hour on the pump - flat, at every level."""
    return EXPERIENCE_PER_TICK * TICKS_PER_HOUR


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Strength": (one band,)}` where the map can reach the furnace."""
    if TASK not in (valid.get(SKILL) or {}):
        return {}
    return {
        SKILL: (
            ComputedMethod(
                method=ACTIVITY,
                xp_per_hour=xp_per_hour(),
                level=LEVEL,
                match=CONFIRMED,
                knob=f"training/{TASK}/{SKILL}",
            ),
        )
    }
