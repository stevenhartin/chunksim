"""Sulphurous essence: a Runecraft rate whose whole clock is somebody's DPS.

**A skill paid as a by-product of melee training.** Sulphur nagua drop
sulphurous essence in Neypotzli and Eyatlalli exchanges each for 50 Runecraft
experience; nothing about the exchange has a cadence, because the hour is spent
killing. `Sulphurous essence`'s `{{Skill info}}` states the 50 and the page
states the other half - "on average, players killing sulphur nagua can expect
to receive 31,250 Runecraft experience worth of sulphurous essence for every
1,000,000 combat experience gained, or **12.5 Runecraft experience per kill**".

**The two published figures check each other**: 12.5 against 50 is one essence
every four kills, which is what a drop share should look like written twice.

    xp an hour = 12.5 x kills an hour

so the rate is not a property of this method at all - it is a property of how
fast the map can kill, which is why `methods` takes
`Heuristics.kills_per_hour` rather than a constant.

### Where the kill rate comes from, and the one substitution

`kills_per_hour` answers from a money-making guide, from `costing/
dps_bridge.py`, or - failing both - from `DEFAULT_KPH`, which for a Slayer
monster is a flat 60. Nobody has measured the nagua: on all three cached maps
the answer is that default, and 60 kills an hour is **750** Runecraft an hour
against the page's own "roughly 2,500 to 3,400 Runecraft experience per hour".
A default is not a measurement, and quoting one as a model would be the worst
of both.

So where the rate is only a default, the page's own figure is used instead -
**recovered rather than stated**, `costing/strut.py`'s move: 2,500 experience
an hour at 12.5 a kill is `PUBLISHED_KILLS_PER_HOUR`, 200, and the top of the
band divides out to 272. That is this project's own layering applied to one
number - `defaults < scraped < computed` - and it means the moment either a
guide or the DPS model covers the nagua, the map's own gear takes over with
nothing here edited.

The **low end** of the published band is spent, for `costing/pyramid.py`'s
reason: it is quoted as a range over "mid-game stats and utilising the boosts
from moonlight potions", and the bottom of a hedged range is the honest read.
The provenance says which happened - `CONFIRMED` off a measured kill rate,
`INFERRED` off the recovered one, since a figure divided out of a published
rate is this project computing rather than reading.

### What is deliberately not charged, and what is not credited

**No material cost.** The essence is what the kills drop, so the hour is
already fully spent - charging the killing again would bill it twice,
`costing/gotr.py`'s trap. And no combat experience is credited either: it is
enormous (80,000-110,000 an hour, the page's real subject) but
`training.effective_xp_per_hour` credits gathering only into the **same**
skill, and combat experience does nothing for a Runecraft climb.

**The level is upstream's and the wiki disagrees.** `{{Skill info}}` states
`skill1lvl = 1` where upstream writes `Level: 20`. Upstream's is taken - it is
the gate the derivation applied and the number the report prints - and it is
the conservative direction, opening the method later rather than earlier.
`STATED_LEVEL` is the fallback and the record of the disagreement.

Pure: the valid set and a kill-rate lookup, both handed in.
"""

from __future__ import annotations

from typing import Callable, Mapping

from chunksim.costing.gathering import CONFIRMED, INFERRED
from chunksim.costing.heuristics import ComputedMethod, Rate

SKILL = "Runecraft"

#: Upstream's one challenge.
TASK = "Turn in ~|sulphurous essence|~ to Eyatlalli"

#: What a band calls the activity.
METHOD = "sulphurous essence"

#: The drop's source, and therefore the whole clock. Upstream's spelling, which
#: is the one `Heuristics.kills_per_hour` is keyed by.
MONSTER = "Sulphur Nagua"

#: **Published**: `{{Skill info}}`'s `skill1exp`, and the page's prose.
XP_PER_ESSENCE = 50.0

#: **Published**, in the same sentence as the 31,250-per-million figure. With
#: `XP_PER_ESSENCE` it says one essence every four kills.
XP_PER_KILL = 12.5

#: The page's own hourly band, "roughly 2,500 to 3,400 Runecraft experience per
#: hour" with mid-game stats and moonlight potions. The low end is what
#: `PUBLISHED_KILLS_PER_HOUR` is recovered from; the high end is carried so a
#: test can check the division both ways.
PUBLISHED_XP_PER_HOUR = (2_500.0, 3_400.0)

#: `2,500 / 12.5`. **Recovered, not stated** - see the module docstring on why
#: it displaces a bare `DEFAULT_KPH` and yields to anything measured.
PUBLISHED_KILLS_PER_HOUR = PUBLISHED_XP_PER_HOUR[0] / XP_PER_KILL

#: `{{Skill info}}`'s `skill1lvl`. Upstream says 20 and wins; this is the
#: fallback and the record of the disagreement.
STATED_LEVEL = 1


def kills_for(rate: Rate) -> tuple[float, str]:
    """The kill rate to spend, and the provenance that comes with it.

    A `Rate` still carrying `match == "default"` is `DEFAULT_KPH` standing in
    for a measurement nobody made, which the page beats. Anything else is a
    guide or the DPS model looking at this map's gear, which beats the page.
    """
    if rate.match == "default":
        return PUBLISHED_KILLS_PER_HOUR, INFERRED
    return rate.value, CONFIRMED


def methods(
    valid: Mapping[str, Mapping[str, object]],
    kills_per_hour: Callable[[str], Rate],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Runecraft": (one band,)}` if the map can reach Eyatlalli.

    One band and no curve: a nagua drops what it drops at every level, and
    what moves the rate is the gear rather than the Runecraft.
    """
    challenge = (valid.get(SKILL) or {}).get(TASK)
    if challenge is None:
        return {}
    kills, match = kills_for(kills_per_hour(MONSTER))
    if kills <= 0:
        return {}
    level = STATED_LEVEL
    if isinstance(challenge, Mapping):
        stated = challenge.get("Level")
        if isinstance(stated, int) and stated > 0:
            level = stated
    return {
        SKILL: (
            ComputedMethod(
                method=METHOD,
                xp_per_hour=XP_PER_KILL * kills,
                level=level,
                match=match,
                knob=f"training/{TASK}/{SKILL}",
            ),
        )
    }
