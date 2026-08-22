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

### The Farming half is the same lap with something else picked

**"You can only pick one fruit per trip, *or* if you pick herbs instead, you
will always get two clean herbs at once before you are teleported out of the
garden"** - so a herb trip is not a detour, it is the trip. And what it pays
is published without a single caveat: "picking them will always yield **50
Farming experience**, or 25 experience per herb, **regardless of which garden
is chosen**".

So the Farming rate is the lap rate this module already has, times fifty. The
laps come from the same place the Thieving rates do - the *stated* juice an
hour times the sq'irks a juice - so the two halves cannot disagree about how
fast the garden is run, which is `costing/barbarian.py`'s rule.

**Which garden is not a choice, and that is the pleasant part.** The herb
payout is flat, so the best Farming rate is simply the fastest lap - and the
fastest lap is the **winter** garden's, which is also the one with no Thieving
requirement at all. So a map that can enter the garden gets 170 trips an hour
and **8,500 Farming experience**, whatever its Thieving level.

**It does not scale**, which is the shape to expect: 25 experience a herb is
25 at level 99. What it is for is the bottom of a skill that has almost
nothing active below Tithe Farm's 34.

*(Squeezing a sq'irk also pays 5 Cooking, and the export carries no challenge
for it.)*

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

#: The other skill the garden pays, and upstream's own challenge for it.
FARMING_SKILL = "Farming"
HERB_TASK = "Pick herbs or fruit in the ~|Sorceress's Garden|~"

#: What one herb trip pays - two clean herbs at 25 each, "regardless of which
#: garden is chosen".
HERB_EXPERIENCE = 50.0


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


def laps_per_hour(garden: Garden) -> float:
    """Trips into `garden` an hour, from the figures the Thieving side spends.

    The stated juice an hour times the sq'irks a juice, rather than
    `3600 / lap_seconds` - the two agree to within 3% on every garden (that
    agreement is the module's own check) and this is the half the wiki wrote
    down.
    """
    return garden.juice_per_hour * garden.sqirks_per_juice


def farming_rate() -> float:
    """Farming experience an hour picking herbs, in the fastest garden.

    **The garden is not a choice.** The herb payout is flat across all four,
    so the best rate is the most trips an hour - and that is the winter
    garden, which is also the only one with no Thieving requirement. Taken as
    a maximum rather than named, so the code says why winter wins.
    """
    return max(laps_per_hour(garden) for garden in GARDENS.values()) * HERB_EXPERIENCE


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{skill: (...)}` for whichever gardens a map can reach.

    Thieving per garden, and Farming once: upstream carries one challenge for
    the herbs where it carries four for the juice, which matches the game -
    the herbs pay the same in every garden.
    """
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
    found: dict[str, tuple[ComputedMethod, ...]] = {SKILL: bands} if bands else {}
    # **Gated on its own challenge and nothing else.** The winter garden has
    # no Thieving requirement and the herb pick has none of its own, so a map
    # holding the garden can do this at level 1 - which is upstream's `Level`
    # for it exactly.
    if HERB_TASK in (valid.get(FARMING_SKILL) or {}):
        found[FARMING_SKILL] = (
            ComputedMethod(
                method="Sorceress's Garden (herbs)",
                xp_per_hour=farming_rate(),
                level=1,
                match=CONFIRMED,
                knob=f"training/{HERB_TASK}/{FARMING_SKILL}",
            ),
        )
    return found
