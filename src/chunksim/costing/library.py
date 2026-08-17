"""The Arceuus library, which pays a multiple of the level you already have.

**A minigame with no rate to publish, because the rate is the player.** You
are asked for a book, you find it, you hand it in, and you are given a *book
of arcane knowledge* - and what that tome pays is a straight multiple of your
current level in whichever skill you spend it on. Nothing about the activity
gets faster as you climb; the reward does.

    Magic       15 x level
    Runecraft    5 x level

both stated outright on the page, and both raised at the same update ("Magic
experience has been increased from 11x the player's level to 15x. Runecraft
experience has been increased from 4x the player's level to 5x").

**One book is one tome** - "for finding and delivering the correct book,
players will be given a book of arcane knowledge" - so the only thing left to
know is how many books an hour, and that the wiki does not say. 110 is a
measured figure, the middle of a 100-120 range, and it is the single stated
number here.

**So the curve is a straight line and it matters most where the map is
poorest.** On the reference map's second cache the whole of Runecraft above 77
was blood runes at 11,118/hr, because that map reaches no Guardians of the
Rift and no lavas; the library pays `5 x 77 x 110` = **42,350/hr** at the same
level, and more above it. It was sitting in the export unpriced the whole
time, under a name no rate table would ever join: `Turn in books at the
~|Arceuus Library|~ for Runecraft xp`.

**It is one activity paying two skills**, like barbarian fishing, and the
export carries a challenge for each - so which one you train is a choice
rather than a split, and each is priced as though you spent every tome on it.

Pure: the challenges and the levels come in as arguments.
"""

from __future__ import annotations

from typing import Any, Mapping

from chunksim.costing.gathering import CURVE_STEPS
from chunksim.costing.heuristics import ComputedMethod

#: Books found, delivered and redeemed in an hour. **The one measured figure
#: here**, and the middle of an observed 100-120.
BOOKS_PER_HOUR = 110.0

#: Skill -> what one tome pays, as a multiple of the level held. Both are the
#: page's own, post-buff.
EXPERIENCE_PER_LEVEL: dict[str, float] = {"Magic": 15.0, "Runecraft": 5.0}

#: What a band calls it.
ACTIVITY = "Arceuus library"

#: What this labels its rates.
LIBRARY_MATCH = "modelled"

#: The words upstream gives the two challenges.
LIBRARY_PHRASE = "at the ~|Arceuus Library|~ for "


def xp_per_hour(skill: str, level: int) -> float:
    """Experience an hour at `level`, spending every tome on `skill`."""
    per_level = EXPERIENCE_PER_LEVEL.get(skill)
    if per_level is None or level <= 0:
        return 0.0
    return per_level * level * BOOKS_PER_HOUR


def methods(
    challenges: Mapping[str, Mapping[str, Any]], valid: Mapping[str, Any]
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{skill: bands}` for whichever library challenges a map can reach.

    Banded rather than one rate, because the reward is a multiple of the level
    and so the curve is a straight line through it - a level-1 player is paid
    5 experience a tome and a level-99 player 495.
    """
    found: dict[str, list[ComputedMethod]] = {}
    for skill, per_level in EXPERIENCE_PER_LEVEL.items():
        for task in (valid.get(skill) or {}):
            challenge = challenges.get(skill, {}).get(task)
            if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
                continue
            if LIBRARY_PHRASE not in task or not task.endswith(f"{skill} xp"):
                continue
            found.setdefault(skill, []).extend(
                ComputedMethod(
                    method=ACTIVITY,
                    xp_per_hour=xp_per_hour(skill, level),
                    level=level,
                    match=LIBRARY_MATCH,
                    knob=f"training/{task}/{skill}",
                )
                for level in (1, *CURVE_STEPS)
            )
    return {skill: tuple(bands) for skill, bands in found.items() if bands}
