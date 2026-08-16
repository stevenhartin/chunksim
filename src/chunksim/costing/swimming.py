"""Underwater Agility and Thieving: an hour of tears, spent twice.

**Almost none of this activity's experience is earned where it is paid.** You
collect glistening tears underwater, and then hand them to Mairin for
experience that scales *quadratically* with your level - so the rate is a
count of tears times a parabola, and the searching that produced them is a
rounding error at the top and most of the rate at the bottom.

Named for what players call it. The wiki's own calculator is
`Calculator:Swimming`.

### The parabola, read off the wiki's table rather than fitted

`Glistening tear` tabulates experience per tear at five levels, and one
coefficient reproduces every row of each column:

    Agility alone     0.027 * level^2
    Thieving alone    0.099 * level^2
    both at once      two thirds of each: 0.018 and 0.066

Checked against the activity page's own four hourly figures at 99 - 58,200
Agility alone, 213,400 Thieving alone, and 38,800 / 142,300 for both - every
one comes out at **1.0003x** on `TEARS_PER_HOUR`. That is four published
numbers against one, and it is why these rates are `CONFIRMED`.

### Why `both` and not the faster single mode

Mairin offers three exchanges and the single-skill ones pay half again as
much. This module prices **both**, and the reason is not that it is faster -
it is that it is the only one that is *true twice*. An hour spent here is one
hour, and the export carries a challenge for each skill; pricing Thieving at
213,400 and Agility at 58,200 would let the estimate spend that hour in both
columns and call the map shorter than it is. `both` is the mode where an hour
credited to Agility is the same hour credited to Thieving.

The wiki reaches the same conclusion for a different reason - "the most
efficient way of exchanging glistening tears is selecting both skills ... due
to Agility being proportionally slower to train", and its calculator "assumes
you put the experience in both skills, as choosing just one is never
efficient". Where a map needs only one of the two, this understates it by a
third, which is the direction this project errs in everywhere else.

### The searching itself

A search pays 4.5 Agility **and** 4.5 Thieving, and one tear is what a
successful search yields - the page's "1/8.5 chance" for repeat searches and
its `{{Skilling success chart}}` at 30/40 are the same number said twice, 11.8%
against 12-16%. So the tears already count the successful searches, and this
adds `4.5 * TEARS_PER_HOUR` to each skill without needing a second rate.

It is 990 an hour, which is a fifth of a percent of the Thieving figure at 99
and the entire rate at level 1 - the shape a flat term takes under a parabola.
The published hourly figures are the turn-in alone, so this model reads very
slightly above them, which is the correct direction: that experience is real
and the guide simply does not count it.

**Holes and obstacles are not modelled.** Each pays 4.5 Agility, and nothing
published says how many either of them you pass in an hour - it is a fact
about your route, not about the activity. Their absence makes the Agility
figure a floor.

Pure: both levels come in as arguments.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.costing.gathering import CONFIRMED, CURVE_STEPS
from chunksim.costing.heuristics import ComputedMethod

#: Glistening tears an hour. **One number checked four ways**: the activity
#: page quotes 58,200 / 213,400 / 38,800 / 142,300 experience an hour at 99
#: for its three exchange modes, and this is what turns the coefficients below
#: into all four of them. The page's own range is "roughly 170-230 ... per
#: hour, depending on the player's know-how", and its stated rates sit at this
#: point in it; the wiki calculator defaults to 230.
TEARS_PER_HOUR = 220.0

#: Skill -> experience per tear per level *squared*, for the **both** exchange.
#: Two thirds of what the single-skill exchange pays - see the module
#: docstring for why the slower mode is the one priced.
PER_TEAR: dict[str, float] = {"Agility": 0.018, "Thieving": 0.066}

#: What the single-skill exchanges pay, which nothing here spends. Kept
#: because it is the measurement `PER_TEAR` is two thirds *of*, and a test
#: that cannot see the whole table cannot check that.
PER_TEAR_ALONE: dict[str, float] = {"Agility": 0.027, "Thieving": 0.099}

#: "A successful search also rewards 4.5 Agility and Thieving experience", and
#: a successful search is what yields a tear.
SEARCH_EXPERIENCE = 4.5

#: The export's own challenge for each skill. Both are `Primary` and both open
#: at level 1, gated on the `Underwater Fossil Island` area.
TASKS: dict[str, str] = {
    "Agility": "Participate in ~|Underwater Agility and Thieving|~ for Agility xp",
    "Thieving": "Participate in ~|Underwater Agility and Thieving|~ for Thieving xp",
}

#: What the band is called wherever a rate is shown.
METHOD = "Underwater Agility and Thieving"


def experience_per_tear(skill: str, level: int) -> float:
    """What one tear pays `skill` at `level`, exchanged for both skills."""
    return PER_TEAR.get(skill, 0.0) * float(level) * float(level)


def rate_at(skill: str, level: int) -> float:
    """Experience an hour at `level`: the tears handed in, and the searching.

    Each skill reads only its own level, which is what the wiki's calculator
    takes an `agilityLvl` and a `thievingLvl` for.
    """
    if skill not in PER_TEAR:
        return 0.0
    return (experience_per_tear(skill, level) + SEARCH_EXPERIENCE) * TEARS_PER_HOUR


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{skill: (...)}` for whichever of the two a map can reach.

    Banded, because a parabola is the one shape a single figure is worst for:
    the rate is 994 an hour at level 1 and 142,311 at 99.
    """
    found: dict[str, tuple[ComputedMethod, ...]] = {}
    for skill, task in sorted(TASKS.items()):
        if task not in (valid.get(skill) or {}):
            continue
        bands = tuple(
            ComputedMethod(
                method=METHOD,
                xp_per_hour=rate_at(skill, level),
                level=level,
                match=CONFIRMED,
                knob=f"training/{task}/{skill}",
            )
            for level in (1, *CURVE_STEPS)
            if rate_at(skill, level) > 0
        )
        if bands:
            found[skill] = bands
    return found
