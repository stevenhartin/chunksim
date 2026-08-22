"""The two Chambers of Xeric methods the ordinary layers cannot reach.

**Almost all of the raid is priced without this module.** Its seven bats and
eight fish go through the node walk, its sixteen cooks through recipes, its
kindling chop through the node walk again and its grubs through
`costing/coxchest.py`. What is left is the raid's **herb patches**, which no
`{{Recipe}}` describes because growing a herb is not a production, and its
**braziers**, which are refused here for a reason worth writing down.

### The herb patches, where every term is published

`Chambers of Xeric` states the mechanic in one sentence - "there are **two
farming plots** in each resource room for players to grow herbs. Due to the
magic of the chambers, herbs grow faster and are fully grown in **30
seconds**" - and each plant's own `{{Farming info}}` states what a cycle pays:

    plant     level   plant xp   harvest xp   total
    Golpar       27          4           10      14
    Buchu        39          6           15      21
    Noxifer      55         12           30      42

Two plots grow at once, so a 30-second cycle yields two of whatever is
planted: **240 an hour**, and 3,360 / 5,040 / 10,080 experience.

**A ceiling rather than a rate**, in `costing/trawler.py`'s sense, and for two
reasons stated rather than hidden. The 30 seconds is the *growing* time and
the four clicks a cycle costs - two harvests and two plants - are not added,
which is worth perhaps five seconds in thirty. And the **seeds are not
charged**: they come from boss drops and from raking weeds, and nothing
anywhere states how fast either supplies them. A player short of seeds gets
less than this and there is no published figure for how much less.

**It is small enough that the ceiling costs nothing.** Golpar's 3,360/hr is
below the Sorceress's Garden at 8,500 and a quarter of Tithe Farm's opening
band, so no climb turns on it either way.

### The braziers, and why 48 experience is not enough

`Burn ~|kindling (Chambers of Xeric)|~` has its payout published exactly -
`{{Firemaking info}}` on the kindling states level 1 and **48 experience** -
and **nothing anywhere states how fast one burns**. The infobox carries no
`time`, the brazier's page states only the chance of *lighting* one (8% at
level 1 rising to 78% at 99) and the kindling's own page times the *chopping*
instead.

**That gap decides bands here, which is what makes it a refusal rather than a
guess.** The chop is modelled at 38,398 Woodcutting an hour, and at the
experience the wiki's own table implies per kindling that is on the order of
two thousand kindling an hour - so 48 experience each is a six-figure
Firemaking rate before any cadence is charged at all. `costing/toymouse.py`
carries an invented cadence precisely because its whole plausible range loses
to everything; this one would win outright on an invented number, which is the
opposite case. See `coverage.REFUSED`: a refusal says the decision was made,
where `unpriced` says nobody looked.

Pure: nothing but the valid set comes in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from chunksim.costing.gathering import CONFIRMED
from chunksim.costing.heuristics import ComputedMethod

SKILL = "Farming"

SECONDS_PER_HOUR = 3600.0

#: "There are two farming plots in each resource room for players to grow
#: herbs." One resource room, which is the conservative reading.
PLOTS = 2

#: "Due to the magic of the chambers, herbs grow faster and are fully grown in
#: 30 seconds."
GROW_SECONDS = 30.0


@dataclass(frozen=True)
class Herb:
    """One of the raid's three herbs, as its `{{Farming info}}` states it."""

    task: str
    name: str
    level: int
    plant_experience: float
    harvest_experience: float

    @property
    def experience(self) -> float:
        """What one seed pays end to end - planting it and picking it."""
        return self.plant_experience + self.harvest_experience


HERBS: tuple[Herb, ...] = (
    Herb("Grow a ~|grimy golpar|~", "golpar", 27, 4.0, 10.0),
    Herb("Grow a ~|grimy buchu|~", "buchu", 39, 6.0, 15.0),
    # Upstream does not mark this one `Primary`, so it is carried for
    # completeness rather than because the report shows it.
    Herb("Grow a ~|grimy noxifer|~", "noxifer", 55, 12.0, 30.0),
)

#: The brazier, which is refused - see the module docstring.
KINDLING_TASK = "Burn ~|kindling (Chambers of Xeric)|~"
KINDLING_SKILL = "Firemaking"
KINDLING_EXPERIENCE = 48.0
KINDLING_REASON = (
    "48 experience a kindling is published and nothing states how fast one"
    " burns - and a guessed cadence here would decide bands"
)


def cycles_per_hour() -> float:
    """Grows an hour: both plots, one 30-second cycle at a time."""
    return SECONDS_PER_HOUR / GROW_SECONDS * PLOTS


def rate_for(herb: Herb) -> float:
    """Farming an hour growing `herb`, seeds permitting."""
    return cycles_per_hour() * herb.experience


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Farming": (...)}` for whichever of the three a map can reach."""
    reachable = valid.get(SKILL) or {}
    found = tuple(
        ComputedMethod(
            method=f"Chambers of Xeric ({herb.name})",
            xp_per_hour=rate_for(herb),
            level=herb.level,
            match=CONFIRMED,
            knob=f"training/{herb.task}/{SKILL}",
        )
        for herb in HERBS
        if herb.task in reachable
    )
    return {SKILL: found} if found else {}


def refused(valid: Mapping[str, Mapping[str, object]]) -> dict[str, str]:
    """`{task: why}` for the brazier, which this declines to price."""
    if KINDLING_TASK not in (valid.get(KINDLING_SKILL) or {}):
        return {}
    return {KINDLING_TASK: KINDLING_REASON}
