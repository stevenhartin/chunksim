"""Reading a `Module:Skill calc/<Skill>` table, for the eleven skills that have one.

**One reader, because there is one format.** Every skill calculator on the wiki
is backed by a plain Lua module that `return`s a list of rows, and the rows are
the same shape in all of them:

    { name = 'Raw sardine', level = 5, xp = 20,
      materials = { { name = 'Fishing bait', quantity = 1 } },
      members = 'No', type = 'Bait' }

`remote/farming.py` read that format first and this module is its parser lifted
out unchanged, because five more skills now want the same three lines. What
`farming.py` keeps is the part that is about *crops* - `plantXp`, the yield
mechanic, which patch a thing goes in.

**Brace matching rather than splitting on `name =`.** That is the measured part
and the reason this is not a two-line regex: a row containing a `materials`
table contains a second `name`, so splitting gives 152 fragments for 76 crops -
and worse, each fragment then *ends* at its own materials, before the `type`
field that says what the row is. Every crop parsed as unusable and the table
came back empty.

**`type` is the row's method family and is load-bearing here**, where
`farming.py` reads it as the patch. It is the wiki's own grouping - `Small net`,
`Bait`, `Bird snare`, `Tracking`, `Pickpocket`, `Stalls`, `Regular` - and it is
what `costing/gathering.py` joins a roll interval to, so a fishing spot worked
with a net and one worked with a rod are not assumed to take the same time.

Pure parsing; `remote/api.py` fetches, as it does for every other wiki page. The
module is fetched raw rather than rendered because it is a literal table with no
logic in it, and if that ever stops being true this returns nothing rather than
something plausible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: The page each skill's table lives on. **Eleven, not twenty-three** - there is
#: no `Module:Skill calc/Slayer` and none for the combat skills, because a
#: calculator needs a list of actions and those skills have none.
SKILL_CALC_PAGES: dict[str, str] = {
    skill: f"Module:Skill calc/{skill}"
    for skill in (
        "Agility",
        "Construction",
        "Cooking",
        "Crafting",
        "Farming",
        "Firemaking",
        "Fishing",
        "Fletching",
        "Herblore",
        "Hunter",
        "Magic",
        "Mining",
        "Prayer",
        "Runecraft",
        "Sailing",
        "Smithing",
        "Thieving",
        "Woodcutting",
    )
}

#: One `name = value` pair, string or number. Quoted forms first so a value
#: containing digits is not read as a number.
_FIELD = re.compile(r"(\w+)\s*=\s*(?:'([^']*)'|\"([^\"]*)\"|([\d.]+))")

#: A `{ name = '...', quantity = N }` pair inside a `materials` table.
_MATERIAL = re.compile(
    r"\{\s*name\s*=\s*'([^']*)'\s*,\s*quantity\s*=\s*([\d.]+)\s*\}"
)

#: The `materials = { ... }` block, so a row's own `name` is not read out of it.
_MATERIALS = re.compile(r"materials\s*=\s*\{(.*?)\n\s*\}", re.S)


@dataclass(frozen=True)
class Ingredient:
    """One input a row consumes, and how many of it."""

    name: str
    quantity: float

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "quantity": self.quantity}


@dataclass(frozen=True)
class CalcRow:
    """One row of one skill calculator: an action, its level, and what it pays.

    `kind` is the module's own `type` field. It is not normalised here -
    whatever the wiki groups by is what a caller joins on, and inventing a
    tidier vocabulary would put a modelling decision in a parser.
    """

    name: str
    level: int
    experience: float
    kind: str = ""
    members: bool = True
    materials: tuple[Ingredient, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "level": self.level,
            "experience": self.experience,
            "kind": self.kind,
            "members": self.members,
            "materials": [material.as_dict() for material in self.materials],
        }


def entries(text: str) -> list[str]:
    """Each top-level `{...}` inside the returned table.

    See the module docstring on why this matches braces rather than splitting.
    """
    start = text.find("{")
    if start < 0:
        return []
    found: list[str] = []
    depth = 0
    opened = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
            if depth == 2:
                opened = index
        elif char == "}":
            if depth == 2:
                found.append(text[opened : index + 1])
            depth -= 1
            if depth == 0:
                break
    return found


def fields(chunk: str) -> dict[str, str]:
    """The `name = value` pairs of one row, **first wins**.

    First-wins is what keeps a row's own `name` rather than its first
    material's, which is the same trap the brace matching exists for.
    """
    found: dict[str, str] = {}
    for match in _FIELD.finditer(chunk):
        key = match.group(1)
        value = next(group for group in match.groups()[1:] if group is not None)
        found.setdefault(key, value)
    return found


def materials(chunk: str) -> tuple[Ingredient, ...]:
    """What one row consumes, or empty where it consumes nothing.

    Read out of the `materials = { ... }` block alone, so a row with no
    materials cannot pick up a stray pair from elsewhere in the entry.
    """
    block = _MATERIALS.search(chunk)
    if block is None:
        return ()
    return tuple(
        Ingredient(name=name, quantity=float(quantity))
        for name, quantity in _MATERIAL.findall(block.group(1))
    )


def parse_rows(text: str) -> tuple[CalcRow, ...]:
    """Every row of a skill calculator module, in the order written.

    A row missing a name, a level or an experience figure is dropped rather
    than defaulted: those three are what makes it an action, and a row without
    them is a parse that has gone wrong rather than an action worth nothing.
    """
    found: list[CalcRow] = []
    for entry in entries(text):
        parsed = fields(entry)
        name = parsed.get("name")
        level, experience = parsed.get("level"), parsed.get("xp")
        if not name or level is None or experience is None:
            continue
        try:
            found.append(
                CalcRow(
                    name=name,
                    level=int(float(level)),
                    experience=float(experience),
                    kind=parsed.get("type", ""),
                    members=parsed.get("members", "Yes").strip().lower() != "no",
                    materials=materials(entry),
                )
            )
        except ValueError:
            continue
    return tuple(found)
