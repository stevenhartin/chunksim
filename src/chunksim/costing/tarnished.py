"""Polishing a tarnished item, which no `{{Recipe}}` describes.

**A published method the recipe layer cannot see.** Nine tarnished items drop
in Vampyrium - from venators and the Maggot King - and each is polished into a
random weapon or piece of jewellery for Crafting experience. Upstream files all
nine as `Primary` Crafting challenges and states their output as `Tarnished X
loot`, a **loot-table name** the wiki has no page for, so `recipe_rates`'
`Output` join can never land: the same shape `costing/fishcutting.py` describes
for a knife on a marlin.

The wiki does not use `{{Recipe}}` for them either - a polish is a roll on a
drop table, not a production - so the two numbers a rate needs are in two other
places, and both are stated outright:

- **`{{Skill info}}` on each item**: `skill1name = Crafting`,
  `skill1lvl = 64`, `skill1exp = 200-250`. All nine are identical, and the
  disambiguation page says the same thing once for the family: items "which
  can be polished to receive weapons/jewellery and 200-250 Crafting
  experience".
- **A change note, also on all nine**: "Tarnished items now take **1 tick** to
  polish, down from 3 ticks" (15 July 2026).

### The two readings taken, and the third that is refused

**The low end of the experience range.** Nothing states the distribution, so
200 is the conservative reading of a hedged figure - `costing/pyramid.py`'s
rule. A uniform roll would average 225, which is 11% more; the difference is
invisible next to what the material costs.

**No bank trip.** Every other single-input action is charged a share of one
(`recipe_rates.ACTION_OVERHEAD_SECONDS`), and this one is not, because a
tarnished item is polished where it is picked up - the page's own message is
"you rub the tarnished ring on your clothes". Its travel is inside the kill the
item walk has already timed.

**And the headline is not the answer.** One tick for 200 experience is
1,200,000 an hour, which would own the Crafting climb outright - so the drop is
declared through `Heuristics.material_seconds_per_xp` rather than hidden, the
arrangement `costing/salvage.py` uses for a family the recipe corpus cannot
reach. Priced end to end on the every-rollable-chunk map the cheapest of the
nine is the ring at **366/hr** and the dearest the 2h sword at **92**, because
one tarnished item is half an hour of killing. That is the whole content of
the method: the polish is free and the drop is not.

Upstream marks each `Items` entry with a `*`, so the item really is consumed
and charging it is right rather than the quest-reward exemption
`costing/spells.py` describes.

Pure: the valid set and an item-walk callable come in.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from chunksim.costing.gathering import CONFIRMED
from chunksim.costing.heuristics import ComputedMethod

SKILL = "Crafting"

TICK_SECONDS = 0.6
SECONDS_PER_HOUR = 3600.0

#: Ticks one polish takes, from the 15 July 2026 change note on all nine pages.
POLISH_TICKS = 1.0

#: The low end of `skill1exp = 200-250`. See the module docstring.
EXPERIENCE = 200.0

#: The high end, recorded rather than spent.
EXPERIENCE_HIGH = 250.0

#: `{{Skill info}}`'s `skill1lvl`, which is upstream's `Level` exactly.
LEVEL = 64

#: Every challenge upstream files under this activity, and nothing else - the
#: nine Vampyrium drops. `Tarnished locket` and `Tarnished key` share the word
#: and are a Guardians of the Rift token and a quest item; neither is polished
#: and neither is a challenge here.
TASKS: tuple[str, ...] = (
    "Polish a ~|tarnished 2h sword|~",
    "Polish a ~|tarnished amulet|~",
    "Polish a ~|tarnished battleaxe|~",
    "Polish a ~|tarnished bracelet|~",
    "Polish a ~|tarnished halberd|~",
    "Polish a ~|tarnished longsword|~",
    "Polish a ~|tarnished necklace|~",
    "Polish a ~|tarnished ring|~",
    "Polish a ~|tarnished spear|~",
)

#: The rate before the drop is charged. Stated as a name because it is what
#: `material_seconds_per_xp` exists to correct, and a reader comparing the two
#: columns is seeing exactly this.
POLISH_XP_PER_HOUR = EXPERIENCE * SECONDS_PER_HOUR / (POLISH_TICKS * TICK_SECONDS)


def consumed(challenge: Mapping[str, Any]) -> str:
    """The tarnished item a polish eats, from upstream's own `Items`.

    Read rather than derived from the task name: upstream lowercases the
    marked span (`~|tarnished 2h sword|~`) where its `Items` entry carries the
    item's real capitalisation, and the item walk is keyed on the latter.
    """
    for item in challenge.get("Items") or ():
        if isinstance(item, str) and item.rstrip("*").strip().lower().startswith(
            "tarnished "
        ):
            return item.rstrip("*").strip()
    return ""


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Crafting": (...)}` for whichever polishes a map can reach."""
    reachable = valid.get(SKILL) or {}
    found = [
        ComputedMethod(
            method=task.partition("~|")[2].rpartition("|~")[0] or task,
            xp_per_hour=POLISH_XP_PER_HOUR,
            level=LEVEL,
            match=CONFIRMED,
            knob=f"training/{task}/{SKILL}",
        )
        for task in TASKS
        if task in reachable
    ]
    return {SKILL: tuple(found)} if found else {}


def material_seconds_per_xp(
    challenges: Mapping[str, Any],
    valid: Mapping[str, Any],
    input_seconds: Callable[[str, float], float | None],
) -> dict[str, float]:
    """`{task: seconds of killing per experience}` for the nine polishes.

    **Without this the method reads 1,200,000/hr**, which is what a one-tick
    action paying 200 experience is on paper. There is no `{{Recipe}}` for a
    polish, so nothing else in `inputs.recipe_priced` fills these in - the
    same gap `costing/salvage.py` fills for Sailing.
    """
    reachable = valid.get(SKILL) or {}
    found: dict[str, float] = {}
    for task in TASKS:
        if task not in reachable:
            continue
        challenge = challenges.get(task)
        if not isinstance(challenge, dict):
            continue
        item = consumed(challenge)
        seconds = input_seconds(item, 1.0) if item else None
        if seconds is not None and seconds > 0:
            found[task] = seconds / EXPERIENCE
    return found
