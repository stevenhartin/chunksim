"""Dissecting a sacred eel, whose whole cost is the catching.

**A Cooking method with no Cooking time in it.** You catch a sacred eel, you
cut it with a knife, and the knife pays Cooking - but the cut is not
tick-gated at all (`Zulrah's scales` states `0 (0s)`, the same spammable shape
as `heuristics.DART_CYCLE_SECONDS`), so an hour of this is an hour of
*fishing*. That makes the rate a product of two things measured on two
different level axes, and getting the axes the right way round is the whole
of this module.

    throughput   catches an hour     depends on **Fishing**
    pay          experience a catch  depends on **Cooking**

**Throughput is the Fishing model's own roll, read a second time**, exactly as
`costing/barbarian.py` reads the barbarian cascade. The gathering tables carry
a `Sacred eel` curve (`low` 0, `high` 60, `confirmed`), and
`gathering.success_chance` at level 87 gives **21.09%** and at 99 **23.83%** -
which is the wiki's own published pair to two decimal places. At Fishing's
five-tick roll that is 253.1 catches an hour rising to 285.9, so nothing new is
modelled here and the Fishing figure cannot drift from the node walk's.

**The pay is a step function of Cooking level**, because the number of scales
a dissection yields is. The page gives 100 base experience plus 3 a scale, and
the scale count rises in eight-level intervals:

    Cooking  72-79    4 scales    112 xp
             80-87    5           115
             88-95    6           118
             96-103   7           121
            104+      8           124   (needs a boost; a climb never sees it)

which reproduces the production template's stated `109-127` range at its ends
(3 scales and 9).

**So the bands are Cooking's and the Fishing level is handed in.** That is the
opposite assignment to `barbarian.py`, where which fish you catch depends on
Fishing and the rate is therefore flat in Strength - and it is the same
question answered from the other side. Fishing enters only as a scale factor
and is worth **13% across its entire range**, so a map whose Fishing is
unusually low is not badly served by this; below the requirement the method is
not available at all, which is what `FISHING_REQUIREMENT` floors.

**The rate this replaces was double-counted.** `mmg:Money making guide/
Catching sacred eels` published 26,620/hr for the Cooking, and the item walk
then charged the eel *again* - because a guide quotes a method with its
materials to hand and this one does not have them - which read 13,002. Both
halves were wrong in the same direction: the guide's figure is the catching
and the walk's charge is the catching. Removing the material cost is therefore
part of this model rather than a tweak to it, exactly as it is for Guardians
of the Rift, and `inputs.priced_heuristics` drops the entry.

Pure: the tables, the challenges and the levels all come in as arguments.
"""

from __future__ import annotations

from typing import Any, Mapping

from chunksim.costing.gathering import Tables, success_chance
from chunksim.costing.heuristics import ComputedMethod

#: The task upstream gives the dissection, and the one skill it pays.
TASK = "Dissect a ~|sacred eel|~"
SKILL = "Cooking"

#: What a band calls it, and what its rates are labelled.
ACTIVITY = "Sacred eel"
SACRED_EEL_MATCH = "modelled"

#: The curve's own key in `Tables.curves`, which is the fish rather than the
#: spot - the same name the node walk looks it up under.
CURVE = "sacred eel"

#: Fishing level the eel opens at. Floors the level handed in, since a player
#: below it has no eels to cut.
FISHING_REQUIREMENT = 87

#: Ticks between rolls at a fishing spot - Fishing's own figure, repeated
#: rather than imported for the reason `barbarian.ROLL_TICKS` is.
ROLL_TICKS = 5.0

#: One game tick, in seconds.
TICK_SECONDS = 0.6

#: Cooking experience a dissection pays before the scales: the page's own
#: "100 base xp".
BASE_EXPERIENCE = 100.0

#: And what each scale adds.
EXPERIENCE_PER_SCALE = 3.0

#: `(Cooking level the tier opens at, scales it averages)`, off the sacred
#: eel page's own table. **The average rather than the range**, which is what
#: the table publishes beside each: 3-5 averages 4, 4-6 averages 5, and so on
#: in eight-level steps.
SCALE_TIERS: tuple[tuple[int, int], ...] = (
    (72, 4),
    (80, 5),
    (88, 6),
    (96, 7),
    (104, 8),
)

#: The highest level a climb can reach unaided, so the 104 tier is data rather
#: than a band.
MAX_LEVEL = 99


def scales(cooking_level: int) -> int:
    """Scales one dissection averages at `cooking_level`, or 0 below the first tier."""
    found = 0
    for opens, count in SCALE_TIERS:
        if cooking_level >= opens:
            found = count
    return found


def experience(cooking_level: int) -> float:
    """Cooking experience one dissection pays at `cooking_level`."""
    count = scales(cooking_level)
    return 0.0 if count == 0 else BASE_EXPERIENCE + EXPERIENCE_PER_SCALE * count


def catches_per_hour(tables: Tables, fishing_level: int) -> float:
    """Sacred eels landed in an hour at `fishing_level`.

    `0.0` when the tables carry no curve for the fish, which is the same
    refusal the node walk makes rather than a stand-in.
    """
    curves = tables.curves.get(CURVE)
    if not curves:
        return 0.0
    level = max(fishing_level, FISHING_REQUIREMENT)
    chance = success_chance(level, curves[0][1], curves[0][2])
    return chance * 3600.0 / (ROLL_TICKS * TICK_SECONDS)


def xp_per_hour(tables: Tables, fishing_level: int, cooking_level: int) -> float:
    """Cooking experience an hour, dissecting everything you catch."""
    return catches_per_hour(tables, fishing_level) * experience(cooking_level)


def methods(
    tables: Tables,
    challenges: Mapping[str, Any],
    valid: Mapping[str, Any],
    fishing_level: int,
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{skill: bands}` for the dissection, or empty where the map cannot reach it.

    One band per scale tier, since that is the only thing about the activity
    that moves as a Cooking climb goes on. The 104 tier is skipped: it needs a
    boost, and a band that can never open is noise in a climb.
    """
    challenge = challenges.get(TASK)
    if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
        return {}
    if TASK not in (valid.get(SKILL) or {}):
        return {}
    bands = [
        ComputedMethod(
            method=ACTIVITY,
            xp_per_hour=xp_per_hour(tables, fishing_level, opens),
            level=opens,
            match=SACRED_EEL_MATCH,
            knob=f"training/{TASK}/{SKILL}",
        )
        for opens, _ in SCALE_TIERS
        if opens <= MAX_LEVEL
    ]
    bands = [band for band in bands if band.xp_per_hour > 0]
    return {SKILL: tuple(bands)} if bands else {}
