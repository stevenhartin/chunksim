"""The Skills panel: what each skill's level is, and which layer decided it.

**Four states, and the interface exists to show the fourth.**
`costing/levels.resolve_levels` lays a linked account's experience and any set
by hand over the floor that `infer_levels` reads out of a map's completions,
and refuses any of them that would *lower* a skill. That refusal is the whole
reason this is a panel rather than a line of text: a number quietly raised
back to the floor is indistinguishable from one that was right, and the case
is common - the reference account reads Fishing 80 against a floor of 85,
which is an admiral pie, and Smithing 98 against 99, which is a dwarven stout.

    floor        blue     nothing but the map's own completions
    linked       yellow   the account the map is linked to
    set          green    experience typed in for this map
    below-floor  red      a figure refused for crossing the floor

Read the colours as *provenance*, not as good and bad - blue is not a warning
and yellow is not a caution. Red is the only one that says something is wrong,
and what it says is "these two disagree", not "this is broken".

**The panel is a derived route**, because a floor cannot be read without
parsing the export: `infer_levels` walks the map's completed challenges
against the export's own `Level` fields. That is the split
`gui/routes_view.py` and `gui/routes_derived.py` keep, and this belongs on the
expensive side of it.

Pure: everything comes from a `DerivedState` and the reference blobs.
"""

from __future__ import annotations

from typing import Any, Mapping

from chunksim.costing.levels import (
    BELOW_FLOOR,
    FLOOR,
    LINKED,
    SET,
    resolve_levels,
)
from chunksim.model.experience import (
    MAX_SKILL_LEVEL,
    level_for_xp,
    xp_for_level,
)

#: The skills a panel shows, in the order the game's own Stats tab lays them
#: out - down the columns rather than across, which is why this is a list and
#: not `sorted()`. Two of the export's "skills" are not on it: `Combat` is
#: derived from the others, and there is no 25th.
SKILL_ORDER: tuple[str, ...] = (
    "Attack", "Hitpoints", "Mining",
    "Strength", "Agility", "Smithing",
    "Defence", "Herblore", "Fishing",
    "Ranged", "Thieving", "Cooking",
    "Prayer", "Crafting", "Firemaking",
    "Magic", "Fletching", "Woodcutting",
    "Runecraft", "Slayer", "Farming",
    "Construction", "Hunter", "Sailing",
)

#: What the interface paints each source. Kept here rather than in `app.js`
#: because the states are the model's, and `tests/test_gui_contract.py` reads
#: both so the two cannot drift.
STATE_COLOURS: Mapping[str, str] = {
    FLOOR: "floor",
    LINKED: "linked",
    SET: "set",
    BELOW_FLOOR: "error",
}


def panel(
    state: Any,
    blobs: Any,
) -> dict[str, Any]:
    """`{rsn, skills: [...]}` for one map's Skills panel.

    Every skill is present whether or not anything is known about it, because
    a grid with holes in reads as a loading failure rather than as a floor.
    """
    resolved = resolve_levels(
        state, blobs.levels, blobs.linked_experience, blobs.set_experience
    )
    rows: list[dict[str, Any]] = []
    for skill in SKILL_ORDER:
        found = resolved.get(skill)
        level = found.level if found else 1
        floor = found.floor if found else 1
        source = found.source if found else FLOOR
        experience = found.experience if found else 0
        rows.append(
            {
                "skill": skill,
                "level": level,
                "floor": floor,
                "source": source,
                "state": STATE_COLOURS.get(source, "floor"),
                # **The experience behind the level, and the level's own
                # threshold where nothing supplied one.** A panel that offered
                # an empty box to override would make the user find the number
                # themselves; showing the floor's own experience means typing
                # over it is an edit rather than a lookup.
                "xp": experience or xp_for_level(min(level, MAX_SKILL_LEVEL)),
                # **What the supplied experience *said*, which is not
                # `level` when it was refused.** `resolve_levels` raises a
                # below-floor figure to the floor and reports the refusal;
                # without this the panel could paint the row red but not say
                # what the two numbers were, which is the only useful half.
                "given": (
                    min(level_for_xp(experience), MAX_SKILL_LEVEL)
                    if experience
                    else level
                ),
                # Whether this skill carries a hand-set figure, so the
                # interface can offer to clear it rather than guessing.
                "set": skill in (blobs.set_experience or {}),
            }
        )
    return {
        "rsn": getattr(blobs, "rsn", "") or "",
        "linked": bool(blobs.linked_experience),
        "skills": rows,
    }
