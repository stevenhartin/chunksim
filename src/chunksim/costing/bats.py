"""Chambers of Xeric bats: whichever one your two levels allow.

**You do not choose a bat, you are given the best one you qualify for**, and
the qualification is on *two* skills at once. Every bat states its requirement
twice - "a Hunter level of 90 to catch" and "requiring a Cooking level of 90" -
and the two numbers are the same on all six pages that state both, so the gate
is `min(Hunter, Cooking) >= requirement`. A player with 99 Hunter and 89
Cooking is a level-89 bat hunter.

That makes it one method whose payout steps with level, the shape Puro-Puro and
aerial fishing already have, rather than seven methods competing - which is why
it is here and not in `gathering.PROFILES`. Seven `Catch a ~|... bat|~`
challenges exist, but at most one of them describes what you would actually be
doing.

**No success roll and no supply limit**: they are caught continuously with a
butterfly net at a fixed four ticks each, so the rate is the tier's experience
times 1,500 catches an hour and nothing else. The experience and the
requirement both come from the creature's own `{{Hunter info}}`, which
`remote/gathering.py` already reads for every huntable thing.

The reachability gate is upstream's, as everywhere else here: the challenges
carry `Chunks: ["Chambers of Xeric"]`.

Pure: the table and the two levels come in as arguments.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.costing.gathering import CONFIRMED, CURVE_STEPS, Tables
from chunksim.costing.heuristics import ComputedMethod

#: The seven, worst first. Named rather than discovered because `hunter_info`
#: is keyed by the *item* page - `Raw psykk bat (6)` - and a name is the only
#: thing tying the challenge to it.
BATS: tuple[tuple[str, str], ...] = (
    ("guanic bat", "raw guanic bat (0)"),
    ("prael bat", "raw prael bat (1)"),
    ("giral bat", "raw giral bat (2)"),
    ("phluxia bat", "raw phluxia bat (3)"),
    ("kryket bat", "raw kryket bat (4)"),
    ("murng bat", "raw murng bat (5)"),
    ("psykk bat", "raw psykk bat (6)"),
)

#: Ticks to catch one. Fixed, and there is no roll to fail.
CATCH_TICKS = 4.0

#: The other skill the requirement is stated in. Its *level* gates which bat
#: appears; its experience is a separate action and is not counted here.
GATING_SKILL = "Cooking"


def catches_per_hour() -> float:
    """1,500 - four ticks each, continuously."""
    return 3600.0 / (CATCH_TICKS * 0.6)


def best_bat(
    tables: Tables, hunter: int, cooking: int
) -> tuple[str, float] | None:
    """`(bat, experience)` for the best one both levels allow, or `None`.

    **The lower of the two levels decides it**, which is the whole point: 99
    Hunter with 89 Cooking gets what 89 of each would.
    """
    held = min(hunter, cooking)
    found: tuple[str, float] | None = None
    for name, page in BATS:
        entry = tables.hunter_info.get(page)
        if entry is None:
            continue
        requirement, paid = entry
        if held >= requirement and paid > 0:
            found = (name, paid)
    return found


def methods(
    tables: Tables, valid: Mapping[str, Mapping[str, object]], cooking: int
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Hunter": (...)}` stepping through the tiers this map can reach."""
    reachable = {
        name for name, _page in BATS if f"Catch a ~|{name}|~" in (valid.get("Hunter") or {})
    }
    if not reachable or not tables.hunter_info:
        return {}
    found: list[ComputedMethod] = []
    seen: set[str] = set()
    for level in (1, *CURVE_STEPS):
        chosen = best_bat(tables, level, cooking)
        if chosen is None or chosen[0] not in reachable:
            continue
        name, paid = chosen
        found.append(
            ComputedMethod(
                method=name,
                xp_per_hour=paid * catches_per_hour(),
                level=level,
                match=CONFIRMED,
                knob=f"training/Catch a ~|{name}|~/Hunter",
            )
        )
        seen.add(name)
    return {"Hunter": tuple(found)} if found else {}
