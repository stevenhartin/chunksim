"""Mining dense essence, which pays Crafting as well and only one was spent.

**One action, two skills, and upstream carries both.** `Mine a ~|dense
essence block|~` appears under Mining *and* under Crafting - the block is
quarried with a pickaxe and chiselled loose in the same nine ticks - and
`{{Skill info}}` on `Dense runestone` states the pair outright:

    skill1name = Mining      skill1lvl = 38   skill1exp = 12
    skill2name = Crafting    skill2lvl = 38   skill2exp = 8
    time = 9 ticks

`costing/gathering.py` models the Mining side properly, with the runestone's
own persistence chart deciding how often the pillar survives a swing. The
Crafting side read `unpriced`: there is no `{{Recipe}}` for a mining action,
so `recipe_rates` was never going to reach it, and the gathering tables carry
no Crafting rows at all.

### The ratio rather than a second model

**Nothing here recomputes the loop.** The two experiences come off the same
swing, so Crafting is exactly `8/12` of whatever Mining earns - and taking the
Mining bands and scaling them is what makes the two unable to drift, which is
`costing/barbarian.py`'s rule for an action that pays several skills.
Recomputing from the nine ticks would give 8,000/hr where the model says
11,859, because the model knows about the pillar depleting and nine ticks
alone does not.

**The level axis stays Mining's**, for `barbarian.py`'s reason: how fast the
blocks come is decided by the Mining level and the persistence chart, so the
Crafting rate is flat in Crafting. Upstream agrees - it gates its Crafting
copy at `Level: 38` with `Skills: {"Mining": 38}` beside it, which is the same
38 the wiki states for both.

Pure: the Mining bands and the valid set come in as arguments.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from chunksim.costing.heuristics import ComputedMethod

TASK = "Mine a ~|dense essence block|~"
FROM_SKILL = "Mining"
SKILL = "Crafting"

#: `{{Skill info}}` on `Dense runestone`. Both are stated on one line each and
#: neither is derived here.
MINING_EXPERIENCE = 12.0
CRAFTING_EXPERIENCE = 8.0

#: What the wiki states the swing costs. **Recorded and not spent** - see the
#: module docstring on why the Mining model's own figure is the one scaled.
STATED_TICKS = 9

#: The level both sides open at, stated by the wiki and by upstream alike.
LEVEL = 38

#: What a report calls it.
ACTIVITY = "dense essence block"


def share() -> float:
    """Crafting experience per Mining experience on one swing."""
    return CRAFTING_EXPERIENCE / MINING_EXPERIENCE


def methods(
    mining: Sequence[ComputedMethod],
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Crafting": bands}` scaled off whatever Mining earns on the same swing.

    `mining` is the bands the gathering model has already produced, so this
    reads its answer rather than reproducing it - and inherits its curve, its
    `match` and its level points unchanged.
    """
    if TASK not in (valid.get(SKILL) or {}):
        return {}
    knob = f"training/{TASK}/{FROM_SKILL}"
    found = tuple(
        ComputedMethod(
            method=ACTIVITY,
            xp_per_hour=band.xp_per_hour * share(),
            level=band.level,
            match=band.match,
            knob=f"training/{TASK}/{SKILL}",
        )
        for band in mining
        if band.knob == knob and band.xp_per_hour > 0
    )
    return {SKILL: found} if found else {}
