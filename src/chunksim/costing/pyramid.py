"""The Agility Pyramid, which the guide priced flat from level one.

**Two defects in one scraped figure.** `mmg:Money making guide/Agility
Pyramid` gave 34,380 an hour to all three of the export's pyramid challenges,
and one of them - `Climb the upper climbing rocks by the entrance` - opens at
Agility **1**, where the pyramid itself needs 30. So a money-making rate for
an activity you cannot enter was winning the entire climb from level 1 to 50,
against courses paying 10,000 at the bottom.

And the rate is not flat. The page publishes it against level, because you
fail obstacles until you stop:

    level 55-60    25,000-30,000
    level 67-70    33,000-37,000
    level 75            42,100
    level 88-99         44,700

with a stated ceiling of 26 laps an hour and "at level 75 Agility, it is
impossible to fail any obstacle".

**The low end of each published range is what this carries**, which is the
conservative reading of a figure the page itself hedges - "depending on luck
with failures, sample rates can vary".

**Nothing is offered below level 55, and that is the wiki's own limit rather
than a gap here.** It says so outright: "due to not knowing the exact fail
rates of obstacles for other Agility levels, it is hard to predict the
experience rates for players with lower Agility levels." The pyramid opens at
30 and this declines to guess the twenty-five levels above it - the courses
cover them, and inventing a curve to fill a stretch the wiki refuses to would
be the opposite of what the rest of this directory does.

All three challenges name this activity, so all three take these bands. That
is what stops the level-1 one claiming a rate for a pyramid it cannot enter:
the bands open at 55 whichever challenge asked.

Pure: nothing but the valid set comes in.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.costing.gathering import CONFIRMED
from chunksim.costing.heuristics import ComputedMethod

SKILL = "Agility"

#: The pyramid's own requirement, stated on the page. Recorded because the
#: export gives one of the three challenges level 1 and that is what made the
#: scraped join wrong.
OPENS_AT = 30

#: `(level, experience an hour)`, the low end of each published band.
EXPERIENCE_PER_HOUR: tuple[tuple[int, float], ...] = (
    (55, 25_000.0),
    (67, 33_000.0),
    (75, 42_100.0),
    (88, 44_700.0),
)

#: The level the page's own table starts at. Below this the wiki declines to
#: say and so does this.
RATED_FROM = EXPERIENCE_PER_HOUR[0][0]

#: Laps an hour at best, stated: "a maximum of 26 laps can be completed per
#: hour, however, this asks for high concentration." Not spent - the rates
#: above already contain it - and kept because it is what they are built on.
LAPS_PER_HOUR = 26.0

#: Every challenge the export files under this activity. The two climbing-rock
#: ones are how you reach the course, not a separate method.
TASKS: tuple[str, ...] = (
    "Access the ~|Agility Pyramid|~",
    "Climb the lower climbing rocks by the entrance to the ~|Agility Pyramid|~",
    "Climb the upper climbing rocks by the entrance to the ~|Agility Pyramid|~",
)


def rate_at(level: int) -> float:
    """Agility experience an hour at `level`, or `0.0` where nothing is stated."""
    if level < RATED_FROM:
        return 0.0
    paid = 0.0
    for opens, rate in EXPERIENCE_PER_HOUR:
        if level >= opens:
            paid = rate
    return paid


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Agility": (...)}` where a map can reach the pyramid."""
    reachable = valid.get(SKILL) or {}
    found = [
        ComputedMethod(
            method="Agility Pyramid",
            xp_per_hour=rate,
            level=level,
            match=CONFIRMED,
            knob=f"training/{task}/{SKILL}",
        )
        for task in TASKS
        if task in reachable
        for level, rate in EXPERIENCE_PER_HOUR
    ]
    return {SKILL: tuple(found)} if found else {}
