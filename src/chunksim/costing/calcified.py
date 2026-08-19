"""Smashing a calcified deposit, the Smithing third of Cam Torum mining.

**One activity pays three skills and this module is only the middle one.**
Mining calcified rocks in the Cam Torum mine yields blessed bone shards and,
rarely, a calcified deposit; the deposit is crushed on an anvil for Smithing;
the shards are offered at the libation bowl for Prayer. Where the three stand:

- **Mining is already modelled**, through `gathering.SkillProfile.
  stated_curves`' `calcified rocks` entry - a curve recovered from
  `Pay-to-play Mining training`'s own table, which reads 50,344/hr against its
  published 49,000 at level 99.
- **Smithing is this module**, and every term is published.
- **Prayer is blocked upstream, not here.** `Offer a ~|blessed bone shards|~
  at the libation bowl` is one of only six `Primary` Prayer challenges in the
  whole export, and the ceiling cannot make the `Blessed wine[+]` it asks for:
  a jug is blessed at the Teomat's exposed altar, and that challenge is not
  valid there either. Nothing about it is a rate this project is missing.

### What the deposit's own page states

"This process provides **1 Smithing experience** and takes **3 ticks** per
deposit", with a `{{Skill info}}` saying the same in fields - level 1, an
anvil, a hammer, `time = 3 ticks`. Two thousand of them an hour is 2,000
experience, which is the whole model and is why there is nothing here to fit.

### Why the headline rate is not the interesting number

A deposit is a **1/75** roll off a successful mine, so an hour of smashing is
not an hour anyone can have: at level 99 the Mining model gives about 1,524
successful mines an hour, which is roughly twenty deposits. The rate this
module states is the *action's*, and `training.effective_xp_per_hour` is what
turns that into an honest figure - it charges a method for the time to obtain
what it consumes, and `costing/yields.py` already prices a calcified deposit
as a weighted yield off the rock rather than refusing it as a random drop.

So 2,000/hr is the ceiling of a method whose real cost is the mining behind
it, and the machinery that says so already exists. **What this module adds is
the numerator**, without which the walk had nothing to charge against.

**The shards are deliberately not credited here.** A deposit also gives "on
average 7.5 shards", and those pay *Prayer* rather than Smithing -
`training.effective_xp_per_hour` credits only the same skill, for the reason
its own docstring gives: a log chopped for a bow pays Woodcutting, which does
nothing for a Fletching climb.

Pure: nothing but the valid set comes in.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.costing.gathering import CONFIRMED
from chunksim.costing.heuristics import ComputedMethod

SKILL = "Smithing"

#: What a band calls the activity.
ACTIVITY = "calcified deposits"

#: The export's own challenge.
TASK = "Smash open a ~|calcified deposit|~"

#: Smithing level it opens at, per `{{Skill info}}` and upstream alike.
LEVEL = 1

#: Experience for crushing one. **Stated**, in prose and in the infobox.
EXPERIENCE = 1.0

#: Ticks one deposit takes. **Stated** the same two ways.
TICKS = 3.0

#: Ticks in an hour.
TICKS_PER_HOUR = 6000.0

#: Shards a deposit yields on average, stated on its own page. Carried because
#: it is the reason anybody smashes one; nothing here spends it, since they
#: pay Prayer rather than Smithing.
SHARDS_PER_DEPOSIT = 7.5


def xp_per_hour() -> float:
    """Smithing experience an hour smashing deposits, supply aside."""
    return EXPERIENCE * TICKS_PER_HOUR / TICKS


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Smithing": (one band,)}` where the map can reach the deposits."""
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
