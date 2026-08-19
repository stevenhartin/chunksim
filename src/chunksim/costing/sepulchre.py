"""The Hallowed Sepulchre, counted in ticks rather than quoted in rates.

**One activity, two skills and two regimes.** A lap runs floors 1 to N in
order - you cannot start on floor 5 - so what an hour of it pays is decided by
the *lap*, and the two regimes differ only in whether you stop to loot:

- **No looting** is the Agility answer. `Hallowed Sepulchre/Strategies`
  publishes a tick-perfect time for every entrance of every floor, "assuming no
  looting and no mistakes made", and the main page publishes the experience a
  floor pays.
- **Looting** is the Thieving answer, and it is the whole reason this module
  stopped quoting the published column. A coffin pays 200 Thieving experience
  and the export carries two challenges for them, and no rate table anywhere
  states an hourly figure for *Thieving* here - the wiki's rates are all
  Agility. Priced off the same lap, a coffin costs the detour to reach it and
  pays what the wiki says it pays.

### What is published and what is not

Published: every floor time in `FLOOR_TIMES`, every floor's experience in
`FLOORS`, the coffin's 200 experience, and its `{{Skilling success chart}}`.

Not published, and therefore what makes every rate here a `GUESS`:
`BETWEEN_FLOORS_TICKS`, the six ticks spent recharging run and clicking the
staircase, and - for the looting regime - `COFFIN_DETOUR_TICKS` and
`COFFINS_PER_FLOOR`, one coffin a floor at fifteen ticks to reach it, open it
and get back on route. That is `costing/tempoross.py`'s rule: one invented
factor makes the product invented, however many of the others are read off a
page.

### The check, and what it says about the size of the answer

The main page tabulates a "Realistic No looting XP/hour" per floor, and this
model runs **1.16x to 1.54x** above it - which is the expected direction and
not a disagreement: that column is realistic and this is tick-perfect, and the
page says so in its own note, "It is possible to reach rates above 100,000
XP/hr at maximum efficiency without mistakes". Floor 5 here is 118,769, which
is the only quantitative check the page offers and the model clears it.

**So the published column is kept as `LOOTING_PER_HOUR`/`NO_LOOTING_PER_HOUR`
and is the oracle rather than the source**, the relationship
`costing/barracuda.py` describes: `tests/test_costing_sepulchre.py` pins the
ratios, so the day the wiki's figures move the next run fails a test instead of
letting the two drift silently.

**Floor 5's published pair moved under this project and nobody noticed**,
which is the reason that test exists. This module used to carry 90,000 and
98,500; the page now states 75,800 and 88,500, and the 90,000 is a *footnote*
about looting only the Grand Hallowed Coffin. Read into the table it made the
fastest Agility method in the game 11% quick.

### Two things the level axis has to get right

**A floor is gated on Agility and a coffin on Thieving**, so the looting rate
is a function of both: which floors you can run decides how many coffins a lap
holds, and your Thieving level decides how often one opens. The bands carry the
*Thieving* level, because that is what upstream gates the challenge on, and the
Agility level is handed in - the same split `costing/wintertodt.py` makes for
its solo regime and `costing/sacredeel.py` for its Fishing.

**A lap always runs to the deepest floor the map holds**, which is the
activity every guide describes and is *not* the best Thieving rate a player
could get: floor 1 is 33.6 seconds for one coffin where a full lap is 399.6
for five, so shallow laps open more coffins an hour. What that reading needs
and this does not have is the cost of getting back to the lobby and starting
again - the timer runs out and teleports you, and no page states how long a
fresh entry takes. Charging nothing for it would make the shallowest lap win
by default, so the depth is taken rather than maximised over, and the
consequence is stated rather than hidden: a map holding all five floors reads
a *lower* coffin rate than one holding the first, and the truth is somewhere
above both.

**And the looting lap pays Agility too, more slowly.** It is deliberately not
offered as an Agility method: `training_bands` takes a running maximum, so the
no-looting lap wins everywhere and a second, slower Agility band for the same
activity would be noise. The wiki agrees from the other side - "generally not
worth looting anything on Floors 1 and 2".

Pure: the valid set and one level come in.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.costing.gathering import CURVE_STEPS, GUESS, success_chance
from chunksim.costing.heuristics import ComputedMethod

SKILL = "Agility"
THIEVING = "Thieving"

TICK_SECONDS = 0.6

#: Floor -> `(Agility level, experience for the floor, looting xp/hr,
#: no-looting xp/hr)`, off the main page's `Experience rates` table. **The two
#: hourly columns are the oracle, not the source** - see the module docstring.
FLOORS: dict[int, tuple[int, float, float, float]] = {
    1: (52, 575.0, 30_000.0, 40_000.0),
    2: (62, 925.0, 40_000.0, 50_000.0),
    3: (72, 1_600.0, 63_000.0, 71_700.0),
    4: (77, 2_875.0, 73_000.0, 81_000.0),
    5: (87, 5_725.0, 75_800.0, 88_500.0),
}

#: Floor -> every tick-perfect time `Hallowed Sepulchre/Strategies` states for
#: it, in seconds, one per entrance-and-pattern row. The mean is what this
#: spends: which entrance a run gets is not the player's choice, so an hour is
#: a mix of them and the fastest row would be a claim about luck.
#:
#: **Floor 4 states ranges rather than times** - `1:22 - 1:34` from the north
#: and `1:30 - 1:38` from the south - so each contributes its midpoint, which
#: is the same reading of a range the rest of this file takes of a mean.
FLOOR_TIMES: dict[int, tuple[float, ...]] = {
    1: (31.8, 27.6, 28.8, 29.4, 32.4),
    2: (38.4, 39.6, 43.8, 33.6, 39.6),
    3: (51.0, 54.0, 54.6, 60.6, 51.0),
    4: ((82.0 + 94.0) / 2, (90.0 + 98.0) / 2),
    5: (122.4,),
}

#: Ticks between one floor and the next: recharge run, click the staircase.
#: **Invented**, and the reason every rate here is a `GUESS`.
BETWEEN_FLOORS_TICKS = 6.0

#: Ticks to leave the route for a coffin, open it and get back on it.
#: **Invented**, like the figure above.
COFFIN_DETOUR_TICKS = 15.0

#: How many coffins a lap actually stops at, per floor. **Invented**: the
#: Strategies page lists where the coffins are and does not say how many a run
#: takes, which depends on the route the entrance gives you.
COFFINS_PER_FLOOR = 1.0

#: Experience for opening a coffin, stated on both coffin pages and again in
#: the Strategies page's skill-challenge note: "Each skill challenge awards 200
#: Thieving experience for opening the coffin".
COFFIN_XP = 200.0

#: The `Coffin opening success chance` chart's **plain** series - no lockpick.
#: The page charts two better ones, a lockpick and the strange old lockpick,
#: and neither is an item this project may assume a map holds. Same split
#: `costing/pickpocket.py` makes between what a published figure is calibrated
#: on and what an estimate here is allowed to spend.
COFFIN_CURVE = (-60.0, 190.0)

#: The export's own challenge per floor. Upstream spells the ordinal out.
TASKS: dict[int, str] = {
    1: "Access the first floor of the ~|Hallowed Sepulchre|~",
    2: "Access the second floor of the ~|Hallowed Sepulchre|~",
    3: "Access the third floor of the ~|Hallowed Sepulchre|~",
    4: "Access the fourth floor of the ~|Hallowed Sepulchre|~",
    5: "Access the fifth floor of the ~|Hallowed Sepulchre|~",
}

#: The coffin challenges, and the Thieving level upstream gates each on. The
#: Grand Hallowed Coffin sits at the end of floor 5 and is one per lap; the
#: ordinary coffins are on every floor.
COFFIN_TASK = "Steal from a ~|coffin (Hallowed Sepulchre)|~"
GRAND_TASK = "Steal from the ~|Grand Hallowed Coffin|~"
COFFIN_LEVEL = 66
GRAND_LEVEL = 84


def level_for(floor: int) -> int:
    """The Agility level a floor opens at."""
    return FLOORS[floor][0]


def floor_seconds(floor: int) -> float:
    """The mean tick-perfect time for one floor, in seconds."""
    times = FLOOR_TIMES[floor]
    return sum(times) / len(times)


def deepest_floor(reachable: Mapping[str, object]) -> int:
    """The last floor the map can reach, or `0` for none.

    **Read off upstream's own `Access the Nth floor` challenges rather than
    off an Agility level**, for `costing/wintertodt.py`'s reason: the export
    census `chunksim training` runs with no map infers no level at all, and a
    model comparing `1 < 52` there reports a genuinely priced method as
    unpriced. Upstream already states the gate, once, per floor.
    """
    return max(
        (floor for floor in FLOORS if TASKS[floor] in reachable), default=0
    )


def lap_seconds(floors: int, *, looting: bool = False) -> float:
    """One lap through floors 1 to `floors`, in seconds.

    Every floor carries `BETWEEN_FLOORS_TICKS` including the first, which is
    the descent into it; `looting` adds the coffin detour on each.
    """
    overhead = BETWEEN_FLOORS_TICKS + (
        COFFIN_DETOUR_TICKS * COFFINS_PER_FLOOR if looting else 0.0
    )
    return sum(
        floor_seconds(floor) + overhead * TICK_SECONDS
        for floor in range(1, floors + 1)
    )


def agility_xp(floors: int) -> float:
    """What a lap through floors 1 to `floors` pays in Agility."""
    return sum(FLOORS[floor][1] for floor in range(1, floors + 1))


def agility_rate(floors: int) -> float:
    """Agility experience an hour, running laps that end on `floors`."""
    seconds = lap_seconds(floors)
    return agility_xp(floors) * 3600.0 / seconds if seconds > 0 else 0.0


def coffin_xp(level: int) -> float:
    """Expected Thieving experience from one coffin attempt at `level`."""
    return COFFIN_XP * success_chance(level, *COFFIN_CURVE)


def thieving_rate(
    level: int, floors: int, *, coffins: float | None = None
) -> float:
    """Thieving experience an hour looting coffins on a lap of `floors`.

    `coffins` is how many a lap opens, defaulting to one per floor reached -
    the Grand Hallowed Coffin passes `1.0`, being one per lap however deep the
    lap goes.
    """
    if floors <= 0:
        return 0.0
    taken = floors * COFFINS_PER_FLOOR if coffins is None else coffins
    seconds = lap_seconds(floors, looting=True)
    return taken * coffin_xp(level) * 3600.0 / seconds if seconds > 0 else 0.0


def _banded(
    task: str, opens: int, floors: int, *, coffins: float | None = None
) -> tuple[ComputedMethod, ...]:
    """One band per level the coffin's own curve is worth re-reading at."""
    steps = (opens, *(step for step in CURVE_STEPS if step > opens))
    found = tuple(
        ComputedMethod(
            method="Hallowed Sepulchre (coffins)",
            xp_per_hour=thieving_rate(step, floors, coffins=coffins),
            level=step,
            match=GUESS,
            knob=f"training/{task}/{THIEVING}",
        )
        for step in steps
    )
    return tuple(band for band in found if band.xp_per_hour > 0)


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{skill: bands}` for whichever floors and coffins a map can reach.

    How deep a lap goes is read off the `Access the Nth floor` challenges the
    map holds, which is what a coffin's rate is a function of - see
    `deepest_floor` for why that is upstream's gate rather than a level.
    """
    found: dict[str, tuple[ComputedMethod, ...]] = {}
    reachable = valid.get(SKILL) or {}
    floors = deepest_floor(reachable)
    bands = tuple(
        ComputedMethod(
            method=f"Hallowed Sepulchre (floor {floor})",
            xp_per_hour=agility_rate(floor),
            level=level_for(floor),
            match=GUESS,
            knob=f"training/{TASKS[floor]}/{SKILL}",
        )
        for floor in sorted(FLOORS)
        if TASKS[floor] in reachable
    )
    if bands:
        found[SKILL] = bands

    thieved = valid.get(THIEVING) or {}
    coffins: list[ComputedMethod] = []
    if COFFIN_TASK in thieved:
        coffins.extend(_banded(COFFIN_TASK, COFFIN_LEVEL, floors))
    if GRAND_TASK in thieved and floors >= 5:
        # **One per lap, not one per floor**, and it is at the end of floor 5 -
        # so a map that cannot reach the fifth floor gets nothing at all rather
        # than a share of a shallower lap.
        coffins.extend(_banded(GRAND_TASK, GRAND_LEVEL, floors, coffins=1.0))
    if coffins:
        found[THIEVING] = tuple(coffins)
    return found
