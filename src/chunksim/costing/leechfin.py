"""Cutting a leechfin, which the wiki times in prose and never in a recipe.

**A knife action whose output upstream names as a loot table.** `Cut up a
~|leechfin|~` states `Output: "Leechfin loot"` - a bundle the wiki has no page
for - so `recipe_rates`' `Output` join cannot land, which is the shape
`costing/fishcutting.py` describes for a marlin. Unlike the marlin there is no
`{{Recipe}}` to fall back to either: cutting a leechfin makes a *chance* of a
blood sac rather than a product, so the wiki files it as prose on the fish's
own page.

That prose states both halves outright: "after initiating the cutting,
subsequent leechfins will be automatically cut **once per tick** (which cannot
be sped up), providing **20 Cooking experience** each".

### The fish is the whole cost, and it is charged in full

A leechfin is a level-78 big-net catch that `costing/gathering.py` already
models, and `derive/search.build_world_index` routes it properly because
upstream states `Output: "Leechfin"` on the Fishing challenge - which is the
difference from the bream beside it (`search.HAND_TASK_SOURCES`). So the cut
is declared through `Heuristics.material_seconds_per_xp` and the walk answers
for the catch, `costing/tarnished.py`'s arrangement.

**Charged in full, which is the conservative reading.** The page says cutting
"interrupts the fishing and reduces experience rates by about 40% when fishing
and cutting a full inventory", so a player doing both loses part of a catch
rather than all of one - and modelling that would need to know how the two
activities interleave, which nothing states. Billing the whole catch is the
same call `costing/stated.py` makes for the moss lizard's cook.

**The headline is 120,000/hr and is not the answer**: one tick for 20
experience. What a leechfin costs to catch is what decides this.

Pure: the valid set and an item-walk callable come in.
"""

from __future__ import annotations

from typing import Callable, Mapping

from chunksim.costing.gathering import CONFIRMED
from chunksim.costing.heuristics import ComputedMethod

SKILL = "Cooking"

TICK_SECONDS = 0.6
SECONDS_PER_HOUR = 3600.0

#: "Providing 20 Cooking experience each."
EXPERIENCE = 20.0

#: "Automatically cut once per tick (which cannot be sped up)."
CUT_TICKS = 1.0

#: Upstream's own challenge, and the item it eats.
TASK = "Cut up a ~|leechfin|~"
FISH = "Leechfin"

#: Upstream states `Level: 1` - the fish is what gates this, not a Cooking
#: level, and holding one means having reached Fishing 78 already.
OPENS_AT = 1


def xp_per_hour() -> float:
    """The cut alone, before the fish is charged."""
    return EXPERIENCE * SECONDS_PER_HOUR / (CUT_TICKS * TICK_SECONDS)


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Cooking": (band,)}` where a map can reach the fish."""
    if TASK not in (valid.get(SKILL) or {}):
        return {}
    return {
        SKILL: (
            ComputedMethod(
                method="leechfin",
                xp_per_hour=xp_per_hour(),
                level=OPENS_AT,
                match=CONFIRMED,
                knob=f"training/{TASK}/{SKILL}",
            ),
        )
    }


def material_seconds_per_xp(
    valid: Mapping[str, Mapping[str, object]],
    input_seconds: Callable[[str, float], float | None],
) -> dict[str, float]:
    """`{task: seconds of fishing per experience}` for the cut.

    Nothing else fills this in: there is no `{{Recipe}}` for the cut, so
    `inputs.recipe_priced` never sees it - the same gap `costing/salvage.py`
    and `costing/tarnished.py` fill for their own families.
    """
    if TASK not in (valid.get(SKILL) or {}):
        return {}
    seconds = input_seconds(FISH, 1.0)
    if seconds is None or seconds <= 0:
        return {}
    return {TASK: seconds / EXPERIENCE}
