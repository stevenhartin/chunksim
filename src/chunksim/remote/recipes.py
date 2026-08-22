"""What one action of a training method costs and pays, from the wiki.

**The number the export does not have.** The chunk export says a method exists,
what it consumes and what it produces, and what level it needs - but nothing
anywhere in it is an experience figure or a duration. So a rate had to be joined
from a money-making guide, which covers 225 of 2,657 methods and is a *guess by
association* even when it joins.

`{{Recipe}}` on the wiki carries the two missing halves directly - experience per
action and the action's tick cost - and every invocation is written into the
`recipe` Bucket table, so a single request returns them for a whole skill:

    bucket('recipe')
      .select('page_name','production_json')
      .where('uses_skill','Herblore')
      .limit(5000).run()

Pure parsing only; `remote/api.py` does the fetching, as it does for every other
host. What is *done* with a recipe - how a tick cost and an ingredient walk
become an XP rate - belongs to `costing/`, the same way `wiki.py` parses a
money-making guide and `heuristics.py` decides what rate it implies.

Three shapes to know about, all measured against the live table:

- **`production_json` is JSON inside JSON.** The Bucket row's field is a string
  that has to be decoded a second time.
- **Every number is a string**, including the fractional ones (`"6.2"`), and
  `"ticks"` says three different things: a positive count, `""` for *nobody has
  timed this*, and `"0"` for *the action is instant* - which `Module:Recipe`
  renders as "0 (0s) per action". `None` is the honest answer for the blank;
  a zero is a claim and is kept as one. Measured over the whole table that is
  3,466 positive, 168 blank and **448 zero**, so collapsing the last two - as
  this did until the count was taken - discards a published fact about an
  eighth of the corpus. `Recipe.timed` is the predicate a caller wants.
- **One page can produce several recipes.** `Bronze bar` has three - a normal
  furnace, the Blast Furnace, and a third - distinguished only by the output's
  `subtxt`. Keying on the page alone would silently keep whichever came last.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Material:
    """One ingredient of a recipe, and how many it takes."""

    name: str
    quantity: float

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "quantity": self.quantity}


@dataclass(frozen=True)
class Recipe:
    """One action: what it needs, what it makes, what it pays, how long it takes.

    `ticks` is `None` when the wiki does not say. A caller must treat that as
    "cannot compute a rate from this" rather than as zero, or an unknown becomes
    the fastest method on the map. A *published* figure is always a whole tick;
    the field is a float because a caller may stand a **stated** duration in
    for a missing one, and those need not be - `herblore.CLEAN_TICKS` is 18/28
    of a tick and `chisel.CHISEL_TICKS` is zero.
    """

    page: str
    #: The output's own name, which carries the dose for potions
    #: (`Attack potion(3)`) where `page` does not.
    output: str
    output_quantity: float
    skill: str
    level: int
    experience: float
    ticks: float | None
    materials: tuple[Material, ...]
    #: The output's `subtxt` - "Normal furnace" against "Blast Furnace" - which
    #: is the only thing separating two recipes on one page.
    variant: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return self.output, self.variant

    @property
    def timed(self) -> bool:
        """Whether the wiki gave this action a duration a rate can be built on.

        **A stated `0` is a claim and not a blank**, which is the distinction
        this property exists to keep: `ticks = 0` says the action is instant -
        `Module:Recipe` renders it "0 (0s) per action" - where `ticks = ""`
        says nobody has timed it. Both need a caller to supply something, and
        they are not the same something, so the field keeps them apart and
        this is what "has a usable published duration" means.
        """
        return self.ticks is not None and self.ticks > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "output": self.output,
            "output_quantity": self.output_quantity,
            "skill": self.skill,
            "level": self.level,
            "experience": self.experience,
            "ticks": self.ticks,
            "materials": [material.as_dict() for material in self.materials],
            "variant": self.variant,
        }


def _number(value: Any) -> float | None:
    """A Bucket numeric, which arrives as a string and may be empty."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return float(value.replace(",", "").strip())
    except ValueError:
        return None


def parse_recipes(rows: list[dict[str, Any]], skill: str) -> tuple[Recipe, ...]:
    """Every recipe in `rows` that trains `skill`, in the order returned.

    A row naming several skills yields one `Recipe` per *asked-for* skill only:
    a recipe that pays Crafting and Smithing is two different training methods
    and the caller asked about one of them.

    Rows that cannot be read - no output, no experience, no level - are dropped
    rather than defaulted. This is reference data being imported wholesale, and
    a silently zeroed row would be indistinguishable from a real one.
    """
    found: list[Recipe] = []
    for row in rows:
        raw = row.get("production_json")
        if not isinstance(raw, str):
            continue
        try:
            production = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(production, dict):
            continue

        output = production.get("output")
        if not isinstance(output, dict) or not isinstance(output.get("name"), str):
            continue
        entry = next(
            (
                skills
                for skills in production.get("skills") or []
                if isinstance(skills, dict) and skills.get("name") == skill
            ),
            None,
        )
        if entry is None:
            continue
        experience, level = _number(entry.get("experience")), _number(entry.get("level"))
        if experience is None or level is None:
            continue

        materials = tuple(
            Material(name=material["name"], quantity=_number(material.get("quantity")) or 1.0)
            for material in production.get("materials") or []
            if isinstance(material, dict) and isinstance(material.get("name"), str)
        )
        ticks = _number(production.get("ticks"))
        found.append(
            Recipe(
                page=str(row.get("page_name") or ""),
                output=output["name"],
                output_quantity=_number(output.get("quantity")) or 1.0,
                skill=skill,
                level=int(level),
                experience=experience,
                # **A stated zero survives as a zero.** It used to be
                # collapsed into `None` beside the blanks, which threw away a
                # claim the wiki makes on 448 recipes - see `Recipe.timed`.
                ticks=float(ticks) if ticks is not None and ticks >= 0 else None,
                materials=materials,
                variant=str(output.get("subtxt") or ""),
            )
        )
    return tuple(found)


def recipe_query(skill: str, limit: int = 5000) -> str:
    """The Bucket query for one skill's recipes."""
    return (
        "bucket('recipe').select('page_name','production_json')"
        f".where('uses_skill','{skill}').limit({limit}).run()"
    )
