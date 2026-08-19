"""The Chambers of Xeric thieving room, where the roll is every single tick.

**The fastest cadence in the skill, and the only method whose numerator had to
be recovered.** Every other Thieving action rolls once and makes you click
again; this one keeps rolling by itself - "upon clicking the chest, an attempt
to open it will be made **every game tick** until the player succeeds",
sourced on the page to Mod Ash. At one tick a roll and a 60% chance, a chest
opens about every 1.7 ticks, which is why `Thieving training` calls it the
fastest early method in the game and why it covers levels 1 to 45.

### Everything the wiki states, and the one thing it does not

Stated: the cadence above; the success chart, whose `low=99 high=155` plain
series reproduces the page's own prose exactly ("around 39% at level 1,
scaling to about 61% at level 99"); the lockpick's "+21 percentage points",
which is the second series to the point; and the grub yield rule, down to the
rounding ("picks a random integer between 0 and the maximum ... then raises
the outcome up to the minimum").

**Not stated anywhere: what one successful open pays.** There is no
`{{Thieving info}}` on the chest's page, no row in the Thieving page's chest
table, no row in `Module:Skill calc/Thieving`, and nothing in the Module
namespace - searched, not assumed.

### So it is recovered, and two published statements bound it

`Thieving training` says two independent things about this room:

- "It only requires about **one hour of raid time to level from 1-40**".
  Integrating this model over that climb, one hour implies **9.75** experience
  an open; reading "about an hour" as 50 to 70 minutes bounds it to
  **[8.36, 11.70]**.
- "you can expect experience rates of **up to 30,000-50,000** experience an
  hour". Over the levels the method covers that bounds it to
  **[8.67, 12.51]**.

The two intervals overlap on **[8.67, 11.70]**, and `EXPERIENCE` is the round
number inside it. At 10 the guide's hour is **59 minutes** and the whole 1-45
stretch reads 34,607 to 39,957 an hour, inside its band. That is one unknown
against two independent observations rather than `costing/disclaimed.py`'s
"the guide with extra steps", and it is still a **`GUESS`**: a figure the wiki
declines to state is not one this project read.

### Three things the model does spend, and one it will not

**The lockpick series, which is the one place here a tool is assumed.**
Everywhere else - `costing/pickpocket.py`'s gloves, the Hallowed coffins'
lockpick, the wall safe's stethoscope - the plain series is spent because the
item comes from a shop a chunk map may not hold. This one comes from *inside
the raid*: "bring a lockpick (**can obtain from a Scavenger inside the
raid**)". Both observations above assume it, so spending the plain series
would apply a figure recovered under one regime to another.

**The grub cap, which costs about 4%.** You cannot carry more than 28, and the
guide's own instruction is to "drop the grubs, then continue picking locks".
The yield rule is published, so how often that happens is arithmetic rather
than a guess: one grub an open below level 50, so a two-tick drop every 28
opens.

**Not the trough.** Filling it completes the room and "locks you out of
further Thieving experience for the rest of the raid", which is why the guide
says not to - so it is not part of the loop and not charged.

**Above level 49 the yield changes and nothing says the experience follows.**
The recovery is anchored entirely inside 1-40, where a chest always gives
exactly one grub; if the experience scales with grubs rather than with opens,
the bands above 50 are low. Nothing on any page settles it, and the guide
stops recommending the method at 45 anyway.

Pure: nothing but the valid set comes in.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.costing.gathering import CURVE_STEPS, GUESS, success_chance
from chunksim.costing.heuristics import ComputedMethod

SKILL = "Thieving"

#: What a band calls the activity.
ACTIVITY = "Chambers of Xeric chests"

#: The export's own challenge. Upstream gates it at level 1, as the wiki does.
TASK = "Loot ~|cavern grubs|~ in the Chambers of Xeric"

#: Ticks in an hour.
TICKS_PER_HOUR = 6000.0

#: Ticks between one automatic attempt and the next. **Stated**, and the
#: sharpest cadence in the skill.
ATTEMPT_TICKS = 1.0

#: The `Cavern grub chest thieving chance` chart's **lockpick** series - see
#: the module docstring for why this is the one method here that spends a tool.
CURVE = (153.0, 209.0)

#: Its plain series, carried because the page's own prose checks against it
#: and a reader comparing the two should not have to go back to the page.
PLAIN_CURVE = (99.0, 155.0)

#: What one successful open pays. **Recovered rather than read** - the wiki
#: states no figure - and bounded to `[8.67, 11.70]` by two independent
#: published statements. See the module docstring.
EXPERIENCE = 10.0

#: Grubs you can hold before the chest refuses you.
GRUB_CAP = 28.0

#: Ticks to drop the stack and carry on.
DROP_TICKS = 2.0


def grubs_per_open(level: int) -> float:
    """Mean grubs one successful open gives at `level`.

    The wiki's own rule, rounding included: a maximum of `level // 25` extra,
    rolled uniformly from zero, then raised to a minimum of one - or two from
    level 95. So it is exactly one below level 50, which is the whole of the
    stretch the experience figure was recovered over.
    """
    most = max(0, level // 25)
    least = 2.0 if level >= 95 else 1.0
    outcomes = [max(least, float(roll)) for roll in range(most + 1)]
    return sum(outcomes) / len(outcomes)


def open_ticks(level: int, *, curve: tuple[float, float] | None = None) -> float:
    """Ticks one successful open costs, including its share of a grub drop."""
    chance = success_chance(level, *(curve or CURVE))
    if chance <= 0:
        return 0.0
    return ATTEMPT_TICKS / chance + DROP_TICKS * grubs_per_open(level) / GRUB_CAP


def xp_per_hour(level: int, *, curve: tuple[float, float] | None = None) -> float:
    """Thieving experience an hour in the thieving room at `level`."""
    ticks = open_ticks(level, curve=curve)
    return EXPERIENCE * TICKS_PER_HOUR / ticks if ticks > 0 else 0.0


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Thieving": bands}` where the map can reach the raid.

    Bands rather than one rate, because the chance climbs the whole way: 34,607
    an hour at level 1 against 43,486 at 99.
    """
    if TASK not in (valid.get(SKILL) or {}):
        return {}
    return {
        SKILL: tuple(
            ComputedMethod(
                method=ACTIVITY,
                xp_per_hour=xp_per_hour(step),
                level=step,
                match=GUESS,
                knob=f"training/{TASK}/{SKILL}",
            )
            for step in (1, *CURVE_STEPS)
        )
    }
