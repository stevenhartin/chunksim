"""Chipping a blessed bone statuette, whose rate is an hour of somebody else's
minigame.

**Everything is published and none of it is a Crafting figure.** Upstream
carries `Chip a ~|blessed bone statuette|~ into blessed bone shards` as a
`Primary` Crafting method, and the statuette's own page states what one chip
pays: "players may break them down with a chisel to obtain 125 blessed bone
shards ... and **5 Crafting experience**". The chip itself is instant - the
`{{Recipe}}` states `ticks = 0` - so nothing about the *action* bounds the
rate. What bounds it is how many statuettes an hour of Stealing valuables
hands over, and that is two numbers neither of which is Crafting's:

- **upstream's own share**: `3/520.8` on the `Varlamore thieving` loot table,
  which is the three statuettes - eagle, fox and buffalo - at 1/520.8 each.
  The table's other `Always` member is `Valuables`, so the roll unit is one
  valuable rather than one house or one search.
- **the wiki's throughput**: "players can expect to obtain about **1,600-2,300
  valuables** from 18-19 houses per hour".

Multiplied out that is 9.2 to 13.2 statuettes an hour and **46 to 66 Crafting
experience**. The low end is carried, which is `costing/pyramid.py`'s rule for
a range the page hedges.

### Two things it deliberately does not do

**No material cost.** The statuettes/hour figure already *is* an hour of the
minigame, so the thieving is inside the rate rather than beside it - charging
it again through `Heuristics.material_seconds_per_xp` would bill the same hour
twice, which is the trap `costing/gotr.py` fell into. That also means the
number is the same under either reading: an hour of stealing valuables pays
its Thieving *and* about 46 Crafting, and the chip costs no time at all.

**No item walk.** `estimate._route_hours`' certainty gate refuses a
non-`Always` table member by design and would leave this `unpriced` for ever;
the share is spent directly here instead, the way `costing/yields.py` spends a
weight tier rather than routing it.

### Worth stating even though it decides nothing

46/hr is the slowest Crafting method there is and cannot win a band anywhere.
It is carried because every term in it is published and because `unpriced` is
the wrong word for a method whose rate is known - the same reason this project
removed the floor that used to hide `steel dragon (Construction)` at 3/hr.

Pure: nothing but the valid set comes in.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.costing.gathering import CONFIRMED
from chunksim.costing.heuristics import ComputedMethod

SKILL = "Crafting"

#: Upstream's own challenge, and the Thieving one that supplies it.
TASK = "Chip a ~|blessed bone statuette|~ into blessed bone shards"
GATE_TASK = "Participate in ~|Varlamore thieving|~"
GATE_SKILL = "Thieving"

#: What one chip pays, from the statuette's own page. The 125 shards it also
#: makes are Prayer's and are priced nowhere here.
EXPERIENCE = 5.0

#: Upstream's share on the `Varlamore thieving` table: three statuettes at
#: 1/520.8 each, rolled once per valuable.
STATUETTES_PER_VALUABLE = 3.0 / 520.8

#: "About 1,600-2,300 valuables from 18-19 houses per hour." The low end is
#: what this carries.
VALUABLES_PER_HOUR = (1_600.0, 2_300.0)

#: The level upstream gates the chip at - the minigame's Thieving 50 is
#: enforced by `GATE_TASK` being valid rather than compared here, which is
#: `costing/wintertodt.py`'s rule.
OPENS_AT = 1

ACTIVITY = "blessed bone statuette"


def statuettes_per_hour(valuables: float) -> float:
    """How many statuettes `valuables` an hour of burgling hands over."""
    return valuables * STATUETTES_PER_VALUABLE


def xp_per_hour(valuables: float | None = None) -> float:
    """Crafting experience an hour, at the low end of the published band."""
    return statuettes_per_hour(VALUABLES_PER_HOUR[0] if valuables is None else valuables) * (
        EXPERIENCE
    )


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Crafting": (band,)}` where a map can play the minigame.

    **Gated on the Thieving challenge**, which is where upstream states the
    Fortis chunks and the Thieving 50; the Crafting copy carries neither, and
    a rate written against it alone would offer statuettes to a map that
    cannot reach a house.
    """
    if TASK not in (valid.get(SKILL) or {}):
        return {}
    if GATE_TASK not in (valid.get(GATE_SKILL) or {}):
        return {}
    return {
        SKILL: (
            ComputedMethod(
                method=ACTIVITY,
                xp_per_hour=xp_per_hour(),
                level=OPENS_AT,
                match=CONFIRMED,
                knob=f"training/{TASK}/{SKILL}",
            ),
        )
    }
