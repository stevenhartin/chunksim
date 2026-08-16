"""The Sorceress's Garden: four gardens, and the level picks which.

**The simplest activity in this directory, and the only one where the wiki
publishes both the rate and the arithmetic behind it.** You run a lap to the
tree at the centre, pick a sq'irk, squeeze several into a juice and hand the
juice to Osman for a flat lump of Thieving experience. There is no success
chance anywhere in it, nothing scales with level, and the four gardens are
strictly ordered - so a level does not make you faster, it opens a better
garden.

Each garden page states its lap time and what an hour of it yields, and the
two agree through a mechanic neither states outright: **one sq'irk a lap, and
a fixed number of sq'irks to a juice.**

    garden  level  lap     sq'irks   3600/lap/n   the page says
    winter      1  21.0s         5         34.3              34
    spring     25  36.0s         4         25.0              25
    autumn     45  48.5s         3         24.7              24
    summer     65  36.0s         2         50.0              50

Three land on the stated figure and spring lands inside the "between 35 to 40
seconds" its page gives. That is the check; what this module actually spends
is the stated juice an hour, because it is the number the wiki wrote down.

The experience per juice is the calculator's - 350, 1,350, 2,350 and 3,000 -
and two garden pages check it independently: spring's says 21 juice an hour is
"about 28,350 xp/h", which is 21 x 1,350, and summer's says "the maximum
experience possible per hour is 150,000", which is 50 x 3,000. So both halves
of every row are published and nothing here is fitted.

    winter   34 x   350 =  11,900/hr
    spring   25 x 1,350 =  33,750/hr
    autumn   24 x 2,350 =  56,400/hr
    summer   50 x 3,000 = 150,000/hr

**Upstream's level for the autumn turn-in is wrong and this uses the wiki's.**
The export gates `Turn-in ~|autumn sq'irkjuice|~ to Osman` at 25, where the
Autumn Garden page says "available starting at level 45 Thieving" - and the
other three agree exactly, which is what makes this a slip rather than a
different question. Opening a 56,400/hr band twenty levels early would be the
worst kind of error here, since the band walk would spend the whole of 25-45
on a garden the player cannot enter. Upstream still owns *reachability*: a
garden is offered only where its challenge is valid.

**Only Thieving.** Squeezing the juice pays a little Cooking and the fruit and
herbs pay some Farming - summer's page puts an inventory at 110 and 2,760
against its 69,000 Thieving - but the export carries no challenge for either,
and picking the fruit is a detour rather than part of the lap.

Pure: nothing but the valid set comes in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from chunksim.costing.gathering import CONFIRMED
from chunksim.costing.heuristics import ComputedMethod


@dataclass(frozen=True)
class Garden:
    """One of the four, as its own page describes it."""

    #: Thieving level the *garden* opens at, per the wiki rather than the
    #: export. See the module docstring for the one place they disagree.
    level: int
    #: Seconds to reach the tree at the centre, "near perfect laps and
    #: constant running".
    lap_seconds: float
    #: Sq'irks to a juice. Not stated anywhere as a number - it is what makes
    #: the lap time and the stated yield agree.
    sqirks_per_juice: int
    #: Juice an hour, as the page states it.
    juice_per_hour: float
    #: Thieving experience for handing one to Osman.
    experience: float
    #: The export's own challenge.
    task: str


GARDENS: dict[str, Garden] = {
    "winter": Garden(
        level=1,
        lap_seconds=21.0,
        sqirks_per_juice=5,
        juice_per_hour=34.0,
        experience=350.0,
        task="Turn-in ~|winter sq'irkjuice|~ to Osman",
    ),
    "spring": Garden(
        # "between 35 to 40 seconds", and 36 is where its own stated yield of
        # 25 juice an hour puts it.
        level=25,
        lap_seconds=36.0,
        sqirks_per_juice=4,
        juice_per_hour=25.0,
        experience=1350.0,
        task="Turn-in ~|spring sq'irkjuice|~ to Osman",
    ),
    "autumn": Garden(
        level=45,
        lap_seconds=48.5,
        sqirks_per_juice=3,
        juice_per_hour=24.0,
        experience=2350.0,
        task="Turn-in ~|autumn sq'irkjuice|~ to Osman",
    ),
    "summer": Garden(
        level=65,
        lap_seconds=36.0,
        sqirks_per_juice=2,
        juice_per_hour=50.0,
        experience=3000.0,
        task="Turn-in ~|summer sq'irkjuice|~ to Osman",
    ),
}

SKILL = "Thieving"


def derived_juice_per_hour(garden: Garden) -> float:
    """What the lap time says the yield should be: one sq'irk a lap.

    Not used to price anything - `Garden.juice_per_hour` is the wiki's own
    figure and that is what is spent. This is the arithmetic that says the two
    halves of each page agree, and it is asserted in the tests rather than
    trusted here.
    """
    return 3600.0 / garden.lap_seconds / garden.sqirks_per_juice


def rate_at(garden: Garden) -> float:
    """Thieving experience an hour from running this garden.

    No level in it: what a level buys is a *better garden*, not a faster lap
    or a better chance, which is the whole shape of this activity.
    """
    return garden.juice_per_hour * garden.experience


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Thieving": (...)}` for whichever gardens a map can reach."""
    reachable = valid.get(SKILL) or {}
    bands = tuple(
        ComputedMethod(
            method=f"Sorceress's Garden ({name})",
            xp_per_hour=rate_at(garden),
            level=garden.level,
            match=CONFIRMED,
            knob=f"training/{garden.task}/{SKILL}",
        )
        for name, garden in sorted(GARDENS.items(), key=lambda kv: kv[1].level)
        if garden.task in reachable
    )
    return {SKILL: bands} if bands else {}
