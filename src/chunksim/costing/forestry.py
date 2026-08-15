"""Forestry events: nine of them, and you do not choose which.

**An hour of forestry is a share of all nine**, so no single event is a
training method and pricing them separately would be the wrong shape twice
over - it would let a reader pick the best one, and it would understate every
skill that only one event pays.

The arithmetic is three published numbers and one stated one:

- *how many events an hour*, which is the stated one. Force-spawning is the
  fastest way to meet them and `EVENTS_PER_HOUR` is what that is worth.
- *how often each event comes up*, which is evenly: all nine are equally
  likely, so each occurs `EVENTS_PER_HOUR / 9` times an hour.
- *how many actions an event holds*, from `Forestry/Strategies`.
- *what an action pays*, from the same table's formulas - which carry the
  player's level, so the whole thing is a curve rather than a number.

`remote/gathering.py` does the reading and the summing, because the level is
written into each formula and evaluating wikitext is not this layer's job. What
arrives here is `skill -> level -> experience from one of each event`, and all
this module does is divide by nine and multiply by thirty.

**It pays six skills at once**, which is what makes it worth modelling at all:
Woodcutting reaches 110,794/hr at 99 and is the headline, but the same hour
pays Construction, Thieving, Hunter, Fletching and Farming - none of them large,
all of them otherwise invisible.

The reachability gate is upstream's: every event challenge carries
`Category: ["ForestryXp"]` and the export lists them per skill, so a map that
cannot reach one never offers it.

Pure: the table and the level come in as arguments.
"""

from __future__ import annotations

from typing import Any, Mapping

from chunksim.costing.gathering import CONFIRMED, CURVE_STEPS, Tables
from chunksim.costing.heuristics import ComputedMethod
from chunksim.model.summary import _mapping

#: Events met in an hour, by force-spawning them - the fastest way there is.
#:
#: **The one number here that is not read off a page.** Everything else is the
#: wiki's own arithmetic; this is what a player can actually make happen, and
#: it scales every skill's rate linearly.
EVENTS_PER_HOUR = 30.0

#: The category upstream tags an event challenge with.
FORESTRY_CATEGORY = "ForestryXp"

#: Only the challenges that are about *gaining experience* in an event, rather
#: than the felling axes that share the category.
FORESTRY_PREFIX = "Gain xp in the "


def experience_at(tables: Tables, skill: str, level: int) -> float:
    """Experience one of each event pays `skill` at `level`, or `0.0`."""
    by_level = tables.forestry.get(skill) or {}
    return by_level.get(int(level), 0.0)


def rate_at(tables: Tables, skill: str, level: int) -> float:
    """Experience an hour of forestry events pays `skill` at `level`.

    Each of the nine comes up `EVENTS_PER_HOUR / 9` times, so the sum over all
    nine is scaled once rather than each event being counted separately.
    """
    if tables.forestry_events <= 0:
        return 0.0
    share = EVENTS_PER_HOUR / tables.forestry_events
    return experience_at(tables, skill, level) * share


def event_tasks(chunk_info: Any, valid: Mapping[str, Mapping[str, object]]) -> dict[str, list[str]]:
    """`{skill: tasks}` for every reachable `Gain xp in the ...` challenge."""
    found: dict[str, list[str]] = {}
    for skill, tasks in valid.items():
        challenges = _mapping(chunk_info.challenges, skill)
        for task in tasks:
            challenge = challenges.get(task)
            if not isinstance(challenge, dict):
                continue
            if FORESTRY_CATEGORY not in (challenge.get("Category") or ()):
                continue
            if not task.startswith(FORESTRY_PREFIX):
                continue
            found.setdefault(skill, []).append(task)
    return found


def methods(
    tables: Tables, chunk_info: Any, valid: Mapping[str, Mapping[str, object]]
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{skill: (...)}` for every skill a reachable event pays.

    One rate per skill, named for the activity rather than for whichever event
    the challenge happens to be about - a reader picking `Poacher` out of a
    tooltip would be picking an hour of all nine.
    """
    if not tables.forestry:
        return {}
    found: dict[str, tuple[ComputedMethod, ...]] = {}
    for skill, tasks in event_tasks(chunk_info, valid).items():
        if skill not in tables.forestry or not tasks:
            continue
        banded = [
            ComputedMethod(
                method="Forestry events",
                xp_per_hour=rate_at(tables, skill, level),
                level=level,
                match=CONFIRMED,
                knob=f"training/{sorted(tasks)[0]}/{skill}",
            )
            for level in (1, *CURVE_STEPS)
            if rate_at(tables, skill, level) > 0
        ]
        if banded:
            found[skill] = tuple(banded)
    return found
