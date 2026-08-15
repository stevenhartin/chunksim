"""Methods whose rate is stated rather than derived, and says so.

Two activities live here and they have one thing in common: **nothing about
them can be computed from the tables**, so the number is somebody's statement
and the only honest thing to do is carry it with a provenance that says which
part was measured and which was chosen.

- **Moss lizard.** The experience is a formula - nine tenths of your Hunter
  level, floored, and capped at ninety - so it climbs exactly and needs no
  fitting. The *pace* is not published: catching three takes about half a
  minute, so ten seconds each, and that is a guess. Every band is marked
  `GUESS` for it.
- **Trouble Brewing.** A whole minigame with six skills' worth of challenges
  and nothing tabulated anywhere. Fifteen thousand an hour is a stated
  estimate, applied to each skill the export lists a challenge for, and it is
  a guess twice over: in the figure, and in giving every skill the same one.

**Why they are not in `gathering.PROFILES`.** Neither has a node, a chance or
an interval, and a moss lizard's experience is a function rather than a table
entry - shaping either like the things that do have those would invite a
comparison that does not hold.

Pure: the level and the reachable set come in as arguments.
"""

from __future__ import annotations

import math
from typing import Mapping

from chunksim.costing.gathering import CURVE_STEPS, GUESS
from chunksim.costing.heuristics import ComputedMethod
from chunksim.derive.other_tasks import CATEGORIES as OTHER_CATEGORIES

#: The export's own name for the moss lizard trap.
MOSS_LIZARD_TASK = "Trap a ~|moss lizard|~"

#: Share of the Hunter level a moss lizard pays, and the cap on it.
MOSS_LIZARD_SHARE = 0.9
MOSS_LIZARD_CAP = 90.0

#: Moss lizards caught in an hour. **A guess**: three in about thirty seconds
#: is ten seconds each, which is where this comes from and why every rate it
#: produces is marked as invented.
MOSS_LIZARD_PER_HOUR = 360.0

#: The category upstream tags a minigame challenge with, and the minigame this
#: module has a figure for.
MINIGAME_CATEGORY = "Minigame"
TROUBLE_BREWING = "Trouble Brewing"

#: The challenge branches that are not skills, so a minigame listed under one
#: does not become a training rate for it. `derive/other_tasks.CATEGORIES` owns
#: the first three; `Combat` and `Nonskill` are the export's other two
#: non-skill groupings, and `Combat` in particular carries challenges that
#: belong to six real skills at once.
NOT_SKILLS = frozenset({*OTHER_CATEGORIES, "Combat", "Nonskill"})

#: Experience an hour from Trouble Brewing, in **each** skill it pays. A guess
#: in the figure and a guess again in applying one figure to six skills; the
#: secondary ones are the more likely to be overstated.
TROUBLE_BREWING_PER_HOUR = 15_000.0


def moss_lizard_experience(level: int) -> float:
    """`floor(0.9 x level)`, capped at ninety. Exact, not fitted."""
    return min(math.floor(MOSS_LIZARD_SHARE * level), MOSS_LIZARD_CAP)


def methods(
    chunk_info: object, valid: Mapping[str, Mapping[str, object]]
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{skill: (...)}` for whichever of the two a map can reach."""
    found: dict[str, list[ComputedMethod]] = {}
    if MOSS_LIZARD_TASK in (valid.get("Hunter") or {}):
        for level in (20, *(step for step in CURVE_STEPS if step > 20)):
            paid = moss_lizard_experience(level)
            if paid <= 0:
                continue
            found.setdefault("Hunter", []).append(
                ComputedMethod(
                    method="moss lizard",
                    xp_per_hour=paid * MOSS_LIZARD_PER_HOUR,
                    level=level,
                    match=GUESS,
                    knob=f"training/{MOSS_LIZARD_TASK}/Hunter",
                )
            )
    for skill, tasks in valid.items():
        if skill in NOT_SKILLS:
            continue
        for task in tasks:
            if TROUBLE_BREWING not in task:
                continue
            found.setdefault(skill, []).append(
                ComputedMethod(
                    method="Trouble Brewing",
                    xp_per_hour=TROUBLE_BREWING_PER_HOUR,
                    level=1,
                    match=GUESS,
                    knob=f"training/{task}/{skill}",
                )
            )
            break
    return {skill: tuple(methods) for skill, methods in found.items()}
