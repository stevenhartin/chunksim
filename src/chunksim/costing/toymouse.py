"""Catching a wound-up toy mouse, where only the cadence is unpublished.

**A clockwork toy is a training method the game deliberately made bad.** Wind
the mouse, release it, and "if the player can catch it before it stops moving,
they will gain 3 Agility experience". It used to pay 15 *whether you caught it
or not*, which is what made it fast - the 21 March 2013 change note says so
outright: "since players with low Agility levels would frequently fail to
catch the mouse, they could repeatedly attempt to pick them up and gain very
fast experience". So a failure pays nothing now, and `{{Agility info}}` states
no `failxp` to the contrary.

### Two of the three terms are published, and one of them is checked

- **3 experience a catch**, from the toy's own `{{Agility info}}`.
- **The catch chance is charted** - `low1 = 60`, `high1 = 250` from level 1 -
  and it is one of the few charts on the wiki with a *developer* statement
  beside it. Mod Ash: "Mouse: 24% - 98%.... Those figures are for level 1 and
  level 99; interpolate linearly between them." Through the same
  `gathering.success_chance` every other chart here uses, that reads **23.83%
  and 98.05%** - the chart reproducing Jagex's own numbers rather than this
  project reproducing the chart.

**What nothing anywhere states is how long one wind-release-catch cycle
takes**, and the family is no help: `Clockwork suit` (3 xp, charted from 30),
`Toy doll` (2.5 xp) and `Toy soldier` (0 xp) are the same `type = Clockwork
toy` and not one of them carries a duration. `CATCH_TICKS` is this module's
one invented number, and one invented factor makes the product invented
(`costing/tempoross.py`'s rule), so every band is `GUESS`.

### Why the guess is safe here, which is the opposite argument to Skullball's

`costing/skullball.py` guesses at a term that cannot move the answer far
because the published lap dominates. Here the invented term is the *whole*
denominator, so the rate is directly proportional to it - five ticks reads
3,530/hr at level 99 and fifteen reads 1,177. What makes it safe instead is
the magnitude: at **every** value in that range this is the slowest Agility
method on every cached map, against opening bands of 15,000/hr on the
every-rollable-chunk map and 10,835 on the second. The guess cannot decide a
band, so it buys coverage without buying an answer.

**Ten ticks is six seconds for three interactions** - wind the toy, release
it, and catch a thing that is moving away from you - which is the middle of
what the loop plausibly costs rather than either end. It reads **429/hr at
level 1 rising to 1,765 at 99**.

**A tempting reading and why it is wrong**: 3 experience is so small that a
plausible-sounding 5,000/hr needs 1,667 catches an hour, or one every 2.2
seconds *including* winding and releasing. Nothing about the loop supports
that, which is worth saying because the number looks low enough to be a bug.

### What is deliberately not charged

The mouse is not consumed - only a cat eats one - so there is no material
cost per catch, and upstream agrees: it writes `Items: ["Toy mouse"]`
**unmarked**, which is its own notation for a thing held rather than spent.
Making one is a separate priced Crafting challenge.

Pure: nothing but the valid set comes in.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.costing.gathering import CURVE_STEPS, GUESS, success_chance
from chunksim.costing.heuristics import ComputedMethod

SKILL = "Agility"

TICKS_PER_HOUR = 6000.0

#: What one successful catch pays. A failure pays nothing - see the 2013
#: change note in the module docstring.
EXPERIENCE = 3.0

#: `{{Skilling success chart}}` on `Toy mouse`, which reproduces Mod Ash's own
#: "24% - 98%" for levels 1 and 99.
CHART_LOW = 60.0
CHART_HIGH = 250.0

#: **The one invented number in this module.** Six seconds for a wind, a
#: release and a catch. Nothing on the toy's page, on its three clockwork
#: siblings, or anywhere else states a duration.
CATCH_TICKS = 10.0

#: Upstream's own challenge and the level it gates it at.
TASK = "Catch a ~|toy mouse|~"
OPENS_AT = 1

#: What the toy is called in a report.
ACTIVITY = "Toy mouse"


def catch_chance(level: int) -> float:
    """The charted chance of catching it before it stops moving."""
    return success_chance(level, CHART_LOW, CHART_HIGH)


def xp_per_hour(level: int, *, ticks: float = CATCH_TICKS) -> float:
    """Agility experience an hour at `level`, on a cycle of `ticks`."""
    if ticks <= 0:
        return 0.0
    return EXPERIENCE * catch_chance(level) * TICKS_PER_HOUR / ticks


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Agility": bands}` where a map can reach a toy mouse.

    Banded because the chance climbs fourfold across the climb while the cycle
    does not - the same shape `costing/shortcuts.py` has, and the reason a
    single figure would be the error `costing/training.py` was written to
    remove.
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
            for step in (OPENS_AT, *CURVE_STEPS)
        )
    }
