"""Wintertodt: one game, three skills, and the whole rate is a multiplier.

**The rarest shape in this directory - an activity with no chance in it at
all.** Every other computed method here spends a success curve or a published
figure; Wintertodt's experience is stated as arithmetic on the wiki's own
table, so a rate is a count of games multiplied out:

| Activity | Skill | Multiplier |
|---|---|---|
| Cutting a bruma root | Woodcutting | 0.3x |
| Fletching a bruma root | Fletching | 0.6x |
| Feeding a bruma kindling | Firemaking | 3.8x |
| Subduing with 500+ points | Firemaking | 100x |

Four of the eight rows; the table also prices lighting a brazier (6x
Firemaking), feeding an unfletched root (3x), repairing a brazier (4x
Construction) and mixing a rejuvenation potion (0.1x Herblore). Those are not
in the loop below, which is the point of writing the loop down rather than the
table.

**The loop, and why it is this one.** The fast regime is world-hopped: earn
the 500 points that cap the reward, leave, and start again somewhere the game
is already running, so no part of the hour is spent waiting for one to begin.
Twenty bruma kindling is exactly 500 points, and the round trip is chop
twenty roots, fletch twenty, burn twenty. `GAMES_PER_HOUR` is what that comes
to.

At 99 in all three, one game pays 594 Woodcutting, 1,188 Fletching and 7,524 +
9,900 = 17,424 Firemaking - so the hour is 14,256, 28,512 and 418,176.

**Each skill reads only its own level**, which is what makes this three
independent curves rather than one method with three outputs, and why nothing
here needs to be told what else the player has trained. Firemaking's is not a
straight line either: the 100x subdual bonus is per *game* rather than per
kindling, so it is 9,900 of the 17,424 at 99 and the reason world-hopping
beats staying - a longer game earns the same bonus.

**This replaces a hand-written 400,000/hr.** That figure was a single number
for a method whose rate is a function of level, and it was close at the top
(418,176) and wrong everywhere below it - Firemaking opens the boss at 50,
where the real figure is half that. Nothing is fitted here; every number is
the wiki's table or the count of actions in the regime.

The reachability gate is upstream's: each skill's own challenge has to be
valid, so a map that cannot reach the boss is never offered any of the three.

Pure: the levels come in as arguments.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.costing.gathering import CONFIRMED, CURVE_STEPS
from chunksim.costing.heuristics import ComputedMethod

#: Games an hour under the world-hopped regime. **The one number here that is
#: not a multiplier off the wiki's table**, and it scales all three skills
#: together: it is how many times you can reach 500 points and leave, which is
#: what the method is.
GAMES_PER_HOUR = 24.0

#: Bruma kindling burnt per game. 25 points each, so twenty is the 500 that
#: caps the reward - and taking more would earn the same bonus for a longer
#: game, which is exactly what the regime refuses to do.
KINDLING_PER_GAME = 20.0

#: `{skill: (task, multiplier per action)}`, one row of the wiki's table each.
#: The action is a bruma root's whole journey, so all three are counted
#: `KINDLING_PER_GAME` times.
ACTIONS: dict[str, tuple[str, float]] = {
    "Woodcutting": ("Chop ~|bruma roots|~", 0.3),
    "Fletching": ("Fletch ~|bruma kindling|~", 0.6),
    "Firemaking": ("Burn wood at ~|Wintertodt|~", 3.8),
}

#: The skill the 500-point subdual pays, and what it pays: `level * 100`. Per
#: game rather than per action, which is the whole argument for hopping.
SUBDUAL_SKILL = "Firemaking"
SUBDUAL_MULTIPLIER = 100.0

#: What the band is called wherever a rate is shown.
METHOD = "Wintertodt (world-hopped)"


def experience_per_game(skill: str, level: int) -> float:
    """What one game pays `skill` at `level`, or `0.0`.

    Firemaking is the only one with two terms: twenty kindling fed, and the
    subdual bonus once.
    """
    action = ACTIONS.get(skill)
    paid = KINDLING_PER_GAME * action[1] * level if action else 0.0
    if skill == SUBDUAL_SKILL:
        paid += SUBDUAL_MULTIPLIER * level
    return paid


def rate_at(skill: str, level: int) -> float:
    """Experience an hour of world-hopped Wintertodt pays `skill` at `level`."""
    return experience_per_game(skill, level) * GAMES_PER_HOUR


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{skill: (...)}` for whichever of the three a map can reach.

    One band per level step, because the rate is linear in the level and a
    single figure for it was the defect this module was written to fix.
    """
    found: dict[str, tuple[ComputedMethod, ...]] = {}
    for skill, (task, _multiplier) in sorted(ACTIONS.items()):
        if task not in (valid.get(skill) or {}):
            continue
        banded = tuple(
            ComputedMethod(
                method=METHOD,
                xp_per_hour=rate_at(skill, level),
                level=level,
                match=CONFIRMED,
                knob=f"training/{task}/{skill}",
            )
            for level in (1, *CURVE_STEPS)
            if rate_at(skill, level) > 0
        )
        if banded:
            found[skill] = banded
    return found
