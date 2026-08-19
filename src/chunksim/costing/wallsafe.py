"""The Rogues' Den lobby safes, where one click is a run of attempts.

**A safe is not opened once, it is worried at.** Every other Thieving object
this project prices rolls once and you click again; a wall safe keeps going by
itself - "the player will automatically make another attempt to crack the safe
every 4 ticks (2.4 seconds) until they either crack the safe or trigger a
trap". So the thing with a success chance is the *attempt* and the thing that
pays 70 experience is the *run*, and pricing the first as though it were the
second is what left this unpriced: `costing/gathering.py` wants a restock and
a safe has none, because there is nothing to restock.

### Three published numbers and no free parameter

The page states the per-attempt chance twice, as a `{{Skilling success chart}}`
and as prose - "33.2% at level 50, scaling up to a 62.9% chance at level 99" -
and `gathering.success_chance(50, 8, 160)` is 85/256 and `(99, ...)` is 161/256,
which is those two figures exactly.

It then states the trap rule: **"The chance of triggering a trap per attempt
appears to be (100% - success chance) / 2"**. That is the whole model, because
it makes an attempt a three-way roll - crack, trap, or nothing and go again -
so a run ends with probability `(1 + p) / 2` and ends *well* with probability
`2p / (1 + p)`. Against the page's own overall figures:

    level 50   2 x 0.3320 / 1.3320 = 0.4985    published "49%"
    level 99   2 x 0.6289 / 1.6289 = 0.7722    published "77%"

Neither of those was fitted; they fall out of the trap rule applied to the
chart, within a point of both. **That is the check this module rests on**, and
it is the shape `costing/gathering_overhead.py` asks for: two observations, no
parameter. A point is also as close as the page claims to be - the figures are
"estimated", cross-referenced against 4,780 measured attempts, and the trap
rule is stated as what "appears to be" the case.

### The cadence, which the page also states, and its own ceiling

"Without using tick manipulation, the safe can theoretically be looted every 8
ticks, granting up to 52,500 experience per hour, assuming no failures". Eight
ticks at 70 experience is 52,500 an hour to the pound, so the eight is four
ticks of attempt plus **four of re-click** - and that is where `RECLICK_TICKS`
comes from rather than being guessed. The model reduces to the page's own
number when `p` is 1, which is the third check.

Spent honestly it reads **20,925/hr at level 50 and 36,396 at 99**, against the
page's "realistically it is usually significantly less, around 30-40k xp per
hour". The 52,500 is a ceiling assuming no failures and is not carried as a
rate; `MAX_PER_HOUR` is here because a reader comparing the two should not have
to go back to the page.

### What is not spent

The **stethoscope** series, `low2=16 high2=192`, which the page charts beside
the plain one and which would read 24,700 to 44,700. It is bought from Martin
Thwait and his shop needs Agility 50, so it is an item a map may not hold -
the same split `costing/pickpocket.py` makes between what a published figure is
calibrated on and what an estimate here may assume.

And the **trap's cost**, which is nothing: in the lobby a failure "will spawn a
floor trap under the player" and the page says "it is best to ignore the traps
entirely". Ejection is the *maze* safes, which are a different page and a
different object.

Pure: nothing comes in but the valid set.
"""

from __future__ import annotations

from typing import Any, Mapping

from chunksim.costing.gathering import CONFIRMED, CURVE_STEPS, success_chance
from chunksim.costing.heuristics import ComputedMethod

SKILL = "Thieving"

#: What a band calls the activity.
ACTIVITY = "Rogues' Den wall safe"

#: The export's own challenge.
TASK = "Crack a ~|wall safe (lobby)|~ inside the Rogues' Den"

#: Thieving level it opens at, per the export and the infobox alike.
LEVEL = 50

#: Experience for cracking one, off `{{Thieving info}}`.
EXPERIENCE = 70.0

#: The **plain** `Wall safe thieving chance` series - see the module docstring
#: for why the stethoscope's is charted and not spent.
CURVE = (8.0, 160.0)

#: Ticks between one automatic attempt and the next, stated outright.
ATTEMPT_TICKS = 4.0

#: Ticks spent clicking the next safe once a run has ended. **Recovered from
#: the page's own ceiling rather than guessed**: it states a safe "can
#: theoretically be looted every 8 ticks", and one attempt is four of them.
RECLICK_TICKS = 4.0

#: Ticks in an hour.
TICKS_PER_HOUR = 6000.0

#: The page's own ceiling, `EXPERIENCE * TICKS_PER_HOUR / 8`. Carried as the
#: check it is; never spent as a rate, because it assumes no failures.
MAX_PER_HOUR = 52_500.0


def attempt_chance(level: int) -> float:
    """The chance one automatic attempt cracks the safe."""
    return success_chance(level, *CURVE)


def run_chance(level: int) -> float:
    """The chance a run ends in a crack rather than a trap.

    `2p / (1 + p)`, from the page's own trap rule - an attempt cracks with `p`,
    springs the trap with `(1 - p) / 2` and otherwise repeats, so the run is a
    race between the first two. Reproduces the published 49% and 77%.
    """
    chance = attempt_chance(level)
    return 2.0 * chance / (1.0 + chance) if chance > 0 else 0.0


def run_ticks(level: int) -> float:
    """Ticks one run costs, including the click that starts the next.

    A run ends on any attempt with probability `(1 + p) / 2`, so it takes
    `2 / (1 + p)` attempts on average.
    """
    chance = attempt_chance(level)
    if chance <= 0:
        return 0.0
    attempts = 2.0 / (1.0 + chance)
    return RECLICK_TICKS + ATTEMPT_TICKS * attempts


def xp_per_hour(level: int) -> float:
    """Thieving experience an hour cracking lobby safes at `level`."""
    ticks = run_ticks(level)
    if ticks <= 0:
        return 0.0
    return EXPERIENCE * run_chance(level) * TICKS_PER_HOUR / ticks


def methods(
    valid: Mapping[str, Mapping[str, Any]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Thieving": bands}` where the map can reach the lobby.

    Bands rather than one rate: the per-attempt chance climbs with level and so
    does the share of runs that end in a crack rather than a trap, so the rate
    moves twice over - 20,925 at 50 against 36,396 at 99.
    """
    if TASK not in (valid.get(SKILL) or {}):
        return {}
    steps = (LEVEL, *(step for step in CURVE_STEPS if step > LEVEL))
    return {
        SKILL: tuple(
            ComputedMethod(
                method=ACTIVITY,
                xp_per_hour=xp_per_hour(step),
                level=step,
                match=CONFIRMED,
                knob=f"training/{TASK}/{SKILL}",
            )
            for step in steps
        )
    }
