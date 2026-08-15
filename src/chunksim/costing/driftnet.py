"""Drift net fishing, which pays two skills and stops paying at 70.

**The wiki costs it as an hourly rate rather than as a loop**, and this reads
it that way rather than re-deriving one. Its table already multiplies the
per-shoal experience by its own assumption of 1,150 shoals an hour, so
computing that again would only give this project a chance to disagree with the
page it is reading.

Three things make it unlike anything else here:

- **it pays Hunter and Fishing at once**, which only aerial fishing also does;
- **it stops scaling at 70** in both skills, so the climb is flat above that
  where every other method here keeps rising - which is a fact about the
  activity and not a gap in the table;
- **the two requirements differ**, 44 Hunter against 47 Fishing, which is why
  the opening row pairs two different numbers and every later one pairs equal
  ones.

The reachability gate is upstream's: the challenge is `Catch a ~|fish shoal|~`,
which carries the drift net in its `Items`.

Pure: the table and the level come in as arguments.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.costing.gathering import CONFIRMED, Tables
from chunksim.costing.heuristics import ComputedMethod

#: The export's own name for it, under both skills.
DRIFT_NET_TASK = "Catch a ~|fish shoal|~"

#: The skills a shoal pays, in the order the scraped pair holds them.
DRIFT_NET_SKILLS = ("Hunter", "Fishing")


def rate_at(tables: Tables, skill: str, level: int) -> float:
    """Experience an hour at `level`, or `0.0` below the requirement.

    **The last row at or below the level**, since the table is a ladder rather
    than a formula - and it tops out at 70, which is where the activity itself
    stops scaling.
    """
    if skill not in DRIFT_NET_SKILLS or not tables.drift_net:
        return 0.0
    column = DRIFT_NET_SKILLS.index(skill)
    found = 0.0
    for step, pair in sorted(tables.drift_net.items()):
        if level >= step:
            found = pair[column]
    return found


def methods(
    tables: Tables, valid: Mapping[str, Mapping[str, object]]
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{skill: (...)}` for each skill a reachable shoal pays."""
    if not tables.drift_net:
        return {}
    found: dict[str, tuple[ComputedMethod, ...]] = {}
    for skill in DRIFT_NET_SKILLS:
        if DRIFT_NET_TASK not in (valid.get(skill) or {}):
            continue
        banded = [
            ComputedMethod(
                method="drift net fishing",
                xp_per_hour=rate_at(tables, skill, step),
                level=step,
                match=CONFIRMED,
                knob=f"training/{DRIFT_NET_TASK}/{skill}",
            )
            for step in sorted(tables.drift_net)
            if rate_at(tables, skill, step) > 0
        ]
        if banded:
            found[skill] = tuple(banded)
    return found
