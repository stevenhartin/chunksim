"""Stealing valuables: a published curve, and four ways of checking it.

**This module is a transcription, and saying so is the point.** Nothing about
the burgling loop is charted - not the chest, the wardrobe or the jewellery
case - so there is no success curve to build a rate out of the way
`costing/pyramid_plunder.py` does. What the wiki publishes instead is the
answer directly, as a level-to-experience table, and the honest thing is to
carry it rather than to dress a fit up as a derivation.

What makes it worth carrying is that the same page states the activity four
other ways and every one of them agrees with the table:

- **45 experience a valuable**, off each object's own infobox. The table's
  72,000 at level 50 is 1,600 valuables an hour and its 105,000 at 99 is
  2,333, against a stated "about 1,600-2,300 valuables".
- **18-19 houses an hour**, which the house cycle gives independently: the
  owner returns "180-190 seconds after they left", so 3,600 over that is
  18.9 to 20.
- **One house key a house.** The page says a key is worth "around 3900xp at
  level 50 and 5700xp at level 99"; the table over 18.5 houses is 3,892 and
  5,676.
- and the range the prose quotes for the whole activity, "roughly
  70,000-105,000", which is the table's own ends.

So the numbers are not one measurement repeated, they are four measurements
of one activity that happen to agree - which is the most a transcription can
offer and is why these bands are `CONFIRMED`.

**What the table does *not* include is the pickpocketing**, and the page is
explicit: the figures are "exclusively from the burgling portion". Getting the
keys means pickpocketing wealthy citizens, which the export prices separately
and the node walk already models at 137,501/hr. Both are Thieving and the band
walk takes the better of the two rather than their sum, so nothing here
double-counts the hour - but the two are the same hour, and a reader comparing
them should know they are alternatives rather than a total.

The flashing-arrow bonus - 630 experience and fourteen valuables, "at random"
- is inside the published table rather than added on top of it, because the
table is measured with it: "as long as very few to no flashing arrows are
missed".

Pure: the level comes in as an argument.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.costing.gathering import CONFIRMED, units_at
from chunksim.costing.heuristics import ComputedMethod

#: The wiki's own chart, "the overall experience per hour for burgling
#: houses". Six points, and the activity opens at 50 so there is nothing below
#: it to state.
EXPERIENCE_PER_HOUR: tuple[tuple[int, float], ...] = (
    (50, 72_000.0),
    (60, 80_000.0),
    (70, 93_000.0),
    (80, 95_000.0),
    (90, 100_000.0),
    (99, 105_000.0),
)

#: What one stolen valuable pays, from each object's `{{Thieving info}}`. Not
#: spent - the table above already contains it - but it is one of the four
#: checks on that table and the tests assert it.
VALUABLE_EXPERIENCE = 45.0

#: The one-time bonus for the flashing arrow, from the same infoboxes. Also
#: inside the table rather than on top of it.
SHINY_EXPERIENCE = 630.0

#: Houses an hour, from "the homeowner will return 180-190 seconds after they
#: left" and stated outright as "18-19 houses per hour". One house key each.
HOUSES_PER_HOUR = 18.5

#: The level the activity opens at, which every object's infobox also states.
OPENS_AT = 50

#: The export's own challenge. Upstream calls it by the region rather than by
#: the activity's name, which is why it takes some finding: the wiki article
#: is `Stealing valuables`.
TASK = "Participate in ~|Varlamore thieving|~"

SKILL = "Thieving"


def rate_at(level: int) -> float:
    """Thieving experience an hour at `level`, or `0.0` below the gate."""
    if level < OPENS_AT:
        return 0.0
    return units_at(EXPERIENCE_PER_HOUR, level)


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Thieving": (...)}` where a map can reach the activity.

    One band per published point, which is what the table is: a curve somebody
    measured at six levels rather than a formula to evaluate anywhere.
    """
    if TASK not in (valid.get(SKILL) or {}):
        return {}
    return {
        SKILL: tuple(
            ComputedMethod(
                method="Stealing valuables",
                xp_per_hour=paid,
                level=level,
                match=CONFIRMED,
                knob=f"training/{TASK}/{SKILL}",
            )
            for level, paid in EXPERIENCE_PER_HOUR
        )
    }
