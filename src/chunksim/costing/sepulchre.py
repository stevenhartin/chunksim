"""The Hallowed Sepulchre: five floors, five rates, one number until now.

**The export models this as five challenges and the scrape priced all five the
same.** `wiki:courses` gave every floor 58,425 an hour, from the first at level
52 to the fifth at 87 - where the wiki's own table says 40,000 and 98,500. So
the flat figure was 1.46x optimistic at the bottom of the activity and 1.69x
pessimistic at the top, which is the worst place to be wrong: the fifth floor
opens at 87 and is the fastest Agility in the game from there, and a rate a
third too low kept it out of the band walk entirely.

The table is published outright, one row per floor:

    floor  level  floor xp   looting   no looting
      1      52       575     30,000       40,000
      2      62       925     40,000       50,000
      3      72     1,600     63,000       71,700
      4      77     2,875     73,000       81,000
      5      87     5,725     90,000       98,500

The export's own five levels are 52, 62, 72, 77 and 87, which is the table's
column exactly - so the join is structural rather than a guess at which
challenge means which floor.

**The no-looting column is the one priced**, for the reason
`costing/tempoross.py` prices "not cooking" and `costing/wintertodt.py` prices
the world-hopped regime: this project costs *training*, and where the wiki
tabulates a faster experience regime beside a slower one that collects more
loot, the faster one is what an hour of the skill is worth. The wiki agrees
from the other side - "experience rates will be higher if you ignore
opportunities to loot coffins", and its own notes say it is "generally not
worth looting anything on Floors 1 and 2". `LOOTING_PER_HOUR` is carried
beside it because it is the measurement the other column is, and a reader
comparing the two should not have to go back to the page.

**A floor is a rate, not a stage of one climb.** `Cumulative Exp` in the same
table is what a *run* through all five pays, and is deliberately not used: the
challenges are `Access the Nth floor`, each gated at its own level, and the
band walk wants the best rate open at each level rather than the sum of a lap.

Pure: nothing but the valid set comes in.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.costing.gathering import CONFIRMED
from chunksim.costing.heuristics import ComputedMethod

SKILL = "Agility"

#: Floor -> `(Agility level, experience for the floor, looting xp/hr,
#: no-looting xp/hr)`, off the wiki's `Experience rates` table.
FLOORS: dict[int, tuple[int, float, float, float]] = {
    1: (52, 575.0, 30_000.0, 40_000.0),
    2: (62, 925.0, 40_000.0, 50_000.0),
    3: (72, 1_600.0, 63_000.0, 71_700.0),
    4: (77, 2_875.0, 73_000.0, 81_000.0),
    5: (87, 5_725.0, 90_000.0, 98_500.0),
}

#: The export's own challenge per floor. Upstream spells the ordinal out.
TASKS: dict[int, str] = {
    1: "Access the first floor of the ~|Hallowed Sepulchre|~",
    2: "Access the second floor of the ~|Hallowed Sepulchre|~",
    3: "Access the third floor of the ~|Hallowed Sepulchre|~",
    4: "Access the fourth floor of the ~|Hallowed Sepulchre|~",
    5: "Access the fifth floor of the ~|Hallowed Sepulchre|~",
}


def level_for(floor: int) -> int:
    """The Agility level a floor opens at."""
    return FLOORS[floor][0]


def rate_at(floor: int, *, looting: bool = False) -> float:
    """Agility experience an hour on one floor.

    `looting` picks the slower published column, which collects hallowed marks
    on the way. Nothing calls it that way today - see the module docstring -
    and it is here so the choice is visible rather than buried.
    """
    _level, _floor_xp, loot, no_loot = FLOORS[floor]
    return loot if looting else no_loot


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Agility": (...)}` for whichever floors a map can reach."""
    reachable = valid.get(SKILL) or {}
    bands = tuple(
        ComputedMethod(
            method=f"Hallowed Sepulchre (floor {floor})",
            xp_per_hour=rate_at(floor),
            level=level_for(floor),
            match=CONFIRMED,
            knob=f"training/{TASKS[floor]}/{SKILL}",
        )
        for floor in sorted(FLOORS)
        if TASKS[floor] in reachable
    )
    return {SKILL: bands} if bands else {}
