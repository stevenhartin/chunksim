"""Stealing artefacts: the one activity here that derives completely.

**No fitted number, no borrowed curve, and no transcription** - every figure
below is stated in prose on the wiki, and the eleven-row experience table it
also publishes comes out of them exactly, to the coin, at every row. That is
rare enough to be the reason this is a module rather than a copied table.

The prose states both halves of what an artefact pays:

    "Successfully picking the lock grants 750 Thieving experience."
    "Delivering the artefact to Captain Khaled yields additional Thieving
     experience equal to 40 times the current Thieving level."

So an artefact is `750 + 40 * level`, which is the only place a level enters:
the lock does not get easier and the run does not get shorter.

And the page tabulates how long a run takes from each of the six houses -
1:00 to 1:30 - which averages to 75 seconds and so **48 artefacts an hour**,
against its own "approximately 48". The same table with the Book of the Dead
teleport averages 65 seconds and gives 55.4, against its "to 55". Both fall
out of assuming the house is assigned uniformly, which is what the activity
does.

Multiplying those two reproduces the published `Base rate` column at all
eleven of its levels with **zero residual**:

    level 49    (750 + 1,960) * 48 = 130,080   published 130,080
    level 75    (750 + 3,000) * 48 = 180,000   published 180,000
    level 99    (750 + 3,960) * 48 = 226,080   published 226,080

**The base rate is the one priced, not the teleported one.** Kharedst's
memoirs and the Book of the Dead both need `The Queen of Thieves`, which the
export's challenge does not require - so pricing 55 an hour would charge every
map for a quest it may not have done. It is 15% and it is the conservative
direction. `artefacts_per_hour` takes the run times as an argument so the
faster regime is one call away if a quest gate is ever wired in.

Pure: the level comes in as an argument.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from chunksim.costing.gathering import CONFIRMED, CURVE_STEPS
from chunksim.costing.heuristics import ComputedMethod

#: Seconds to steal from each of the six houses and get back to Khaled, "using
#: guard lures and stamina potions". North, south-east, south, west,
#: north-west, south-west - the page's own order, slowest last.
HOUSE_SECONDS: tuple[float, ...] = (60.0, 65.0, 70.0, 80.0, 85.0, 90.0)

#: The same six with the Piscarilius teleport after each hand-in. Not spent -
#: see the module docstring - but it is what checks the page's "48 to 55".
HOUSE_SECONDS_TELEPORTED: tuple[float, ...] = (50.0, 55.0, 60.0, 70.0, 75.0, 80.0)

#: "Successfully picking the lock grants 750 Thieving experience."
LOCKPICK_EXPERIENCE = 750.0

#: "...additional Thieving experience equal to 40 times the current Thieving
#: level." The only place a level enters this activity.
DELIVERY_PER_LEVEL = 40.0

#: "requiring level 49 Thieving to participate", which the export agrees with.
OPENS_AT = 49

TASK = "Steal artefacts for ~|Captain Khaled|~"
SKILL = "Thieving"


def artefacts_per_hour(house_seconds: Sequence[float] = HOUSE_SECONDS) -> float:
    """Runs an hour, over a house assigned uniformly at random.

    The mean of the six rather than the best of them: you are told which house
    to rob. That is the whole reason this reproduces the published column - a
    model that let you pick the north house every time would read 60 an hour.
    """
    if not house_seconds:
        return 0.0
    return 3600.0 / (sum(house_seconds) / len(house_seconds))


def experience_per_artefact(level: int) -> float:
    """What one artefact pays end to end: the lock, then the hand-in."""
    return LOCKPICK_EXPERIENCE + DELIVERY_PER_LEVEL * float(level)


def rate_at(level: int, house_seconds: Sequence[float] = HOUSE_SECONDS) -> float:
    """Thieving experience an hour at `level`, or `0.0` below the gate."""
    if level < OPENS_AT:
        return 0.0
    return experience_per_artefact(level) * artefacts_per_hour(house_seconds)


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Thieving": (...)}` where a map can reach Captain Khaled.

    Banded, because the rate is linear in the level and rises by three
    quarters across the span this covers.
    """
    if TASK not in (valid.get(SKILL) or {}):
        return {}
    bands = tuple(
        ComputedMethod(
            method="Stealing artefacts",
            xp_per_hour=rate_at(level),
            level=level,
            match=CONFIRMED,
            knob=f"training/{TASK}/{SKILL}",
        )
        for level in (OPENS_AT, *(step for step in CURVE_STEPS if step > OPENS_AT))
    )
    return {SKILL: bands}
