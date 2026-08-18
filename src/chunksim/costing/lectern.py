"""Teleport tablets, which are the only repeatable way to cast a teleport.

**A teleport cast cannot be a training method and a tablet can.** Casting one
to travel moves you somewhere you cannot cast it again, and how long it takes
to get back is on no page - which is why `costing/spells.py` refuses the whole
`Teleport` kind and why pricing a teleport at its 3-tick animation reads
111,000/hr. The lectern is what makes the same cast repeatable: you stand at
it, you feed it soft clay and the teleport's own runes, and you get a tablet
and the teleport's own experience.

**So upstream's `Cast ~|camelot teleport|~` is answered by the wiki's `Camelot
teleport (tablet)`**, and the four money-making guides that were pricing those
tasks - `mmg:Money making guide/Creating Camelot teleport tablets` and its
siblings - turn out to be describing exactly this. They were not mis-joined so
much as more specific than the task they landed on. The recipes are already in
the corpus with everything needed: 2 or 4 ticks, the runes, the clay, and the
experience. `recipe_rates` charges the bank trip on top, which is the "27 to an
inventory" the guides talk about.

### Two families, two gates, and everything else refused

- **Standard spellbook tablets are gated on the lectern** (`STANDARD_TABLETS`,
  off `Lectern space`'s own table): an oak lectern at Construction 40 makes
  Varrock, an eagle one at 47 adds Falador and Lumbridge, teak eagle at 57 adds
  Camelot, Ardougne and Kourend Castle, mahogany eagle at 67 adds Watchtower,
  Civitas illa Fortis, teleport to house and teleport to boat, and the marble
  lectern at 77 makes them all. A map with no player-owned house builds none of
  them and gets none of these.
- **Arceuus tablets need no gate here because their material is one.** Draynor
  Manor, Barrows, Ape Atoll and the rest are made from a **dark essence block**
  rather than soft clay, and a map that cannot route one already has the
  method refused by `recipe_rates.rate_for` - the same refusal every
  unpriceable ingredient gets. Adding a second gate would be a worse copy of
  the one already working.
**A tablet is no longer the *only* way to price a teleport**, and this module
is no worse for it. `costing/spells.py` used to refuse the whole kind on the
grounds that a cast "moves you somewhere you cannot cast it again"; the wiki
publishes a rate for repeat-casting one, so it prices them now. What a lectern
still answers is a different question - *making* tablets is its own method,
with the spell's experience paid at the bench and no runes spent - and
`training_bands` takes whichever is faster.

- **Everything else is refused**, which is a whitelist and fails closed.
  Ancient and Lunar tablets consume soft clay like the standard ones, so
  nothing about their *materials* says a player-owned house cannot make them -
  and `Lectern space` does not list them, which is the only evidence available.
  A rule that let them through would price a method on the strength of the
  wiki's silence.

Pure: the challenges, the recipes and the valid set all come in as arguments.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from chunksim.remote.recipes import Recipe

#: The suffix the wiki gives a tablet, and the prefix upstream gives a cast.
TABLET_SUFFIX = " (tablet)"
CAST_PREFIX = "Cast "

#: The material that makes a tablet an Arceuus one. Its own route is the gate -
#: see the module docstring.
ARCEUUS_MATERIAL = "Dark essence block"

#: The lectern at Construction 77, which `Lectern space` says makes every
#: standard tablet. Any tablet below is also makeable here.
MARBLE_LECTERN = "Build a ~|marble lectern|~"

#: Tablet -> the **cheapest** lectern that makes it, off `Lectern space`'s own
#: table. A lectern higher up the list makes everything below it, which is why
#: only the cheapest is recorded and why `MARBLE_LECTERN` stands in for all of
#: them.
STANDARD_TABLETS: dict[str, str] = {
    "Varrock teleport (tablet)": "Build an ~|oak lectern|~",
    "Falador teleport (tablet)": "Build an ~|eagle lectern|~",
    "Lumbridge teleport (tablet)": "Build an ~|eagle lectern|~",
    "Camelot teleport (tablet)": "Build a ~|teak eagle lectern|~",
    "Ardougne teleport (tablet)": "Build a ~|teak eagle lectern|~",
    "Kourend castle teleport (tablet)": "Build a ~|teak eagle lectern|~",
    "Watchtower teleport (tablet)": "Build a ~|mahogany eagle lectern|~",
    "Civitas illa fortis teleport (tablet)": "Build a ~|mahogany eagle lectern|~",
    "Teleport to house (tablet)": "Build a ~|mahogany eagle lectern|~",
    "Teleport to boat (tablet)": "Build a ~|mahogany eagle lectern|~",
    # **Listed on `Lectern space` beside the two above and missed here**, in
    # the same mahogany-eagle row - newer Sailing content that arrived after
    # this table was first read off the page.
    "Summon boat (tablet)": "Build a ~|mahogany eagle lectern|~",
}


def buildable(valid: Mapping[str, Any]) -> frozenset[str]:
    """The lectern challenges a map can reach, plus marble's stand-in for all.

    Reads the derivation's own `Construction` set rather than checking chunks
    or levels, so a lectern this map cannot build for *any* reason - no
    player-owned house, no planks, no gold leaf - is simply absent.
    """
    construction = valid.get("Construction") or {}
    held = {task for task in STANDARD_TABLETS.values() if task in construction}
    if MARBLE_LECTERN in construction:
        held |= set(STANDARD_TABLETS.values())
    return frozenset(held)


def tablet_recipes(
    challenges: Mapping[str, Any],
    recipes: Sequence[Recipe],
    valid: Mapping[str, Any],
) -> dict[str, tuple[Recipe, ...]]:
    """`{cast task: tablet recipes}` for every teleport a map can make.

    Keyed by the *cast* task, because that is what upstream carries and what
    `recipe_rates` is joining. A tablet with no lectern and no dark essence
    block in it is absent, which the caller must treat as "no tablet route"
    rather than falling back to the bare cast: see the module docstring for why
    a bare teleport cast is not a training method at all.
    """
    lecterns = buildable(valid)
    by_output: dict[str, list[Recipe]] = {}
    for recipe in recipes:
        if not recipe.output.endswith(TABLET_SUFFIX):
            continue
        arceuus = any(
            material.name == ARCEUUS_MATERIAL for material in recipe.materials
        )
        if not arceuus and STANDARD_TABLETS.get(recipe.output) not in lecterns:
            continue
        by_output.setdefault(recipe.output.lower(), []).append(recipe)

    found: dict[str, tuple[Recipe, ...]] = {}
    for task, body in challenges.items():
        if not isinstance(body, dict) or not task.startswith(CAST_PREFIX):
            continue
        rows = by_output.get(f"{_spell(task)}{TABLET_SUFFIX}".lower())
        if rows:
            found[task] = tuple(rows)
    return found


def _spell(task: str) -> str:
    """`Cast ~|camelot teleport|~` -> `Camelot teleport`, as the wiki spells it.

    The markup is upstream's own and the capitalisation is the wiki's: a page
    title is sentence case, so only the first word is lifted.
    """
    from chunksim.derive.task_names import strip_task_markup

    words = strip_task_markup(task).removeprefix(CAST_PREFIX).strip()
    return words[:1].upper() + words[1:]
