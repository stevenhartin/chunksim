"""What a crop pays, from the wiki's own calculator data.

**Farming is the one skill where an hourly rate is the wrong answer**, and the
estimator said 75,353 hours for 1 to 99 before anything here existed. A crop
spends hours or days growing while you do something else, so what limits the
skill is how many harvests a day you get round to - not how fast you click.

`Module:Skill calc/Farming` is the table behind `Calculator:Farming`, and it is
plain Lua rather than a template, so it comes back whole from `action=raw`.
**`remote/skillcalc.py` reads that format** - it is one format across eleven
skills, and the brace matching it needs was measured here first:

    { name = 'Ranarr weed', level = 32, xp = 30.5, plantXp = 27,
      materials = { { name = 'Ranarr seed', quantity = 1 } },
      type = 'Herb' }

76 crops across eight patch types - 20 Special, 16 Herb, 8 Fruit tree, 8
Allotment, 7 Hops, 6 Flower, 6 Bush, 5 Tree.

**`xp` is per item harvested and `plantXp` is once**, which is why a banana
tree reads 1,841.5 and a potato 9: a tree is checked once for all of it, an
allotment pays per potato. So a harvest is worth `plantXp + xp * yield`, and
`yield` is where the two kinds of crop part company:

- **Trees, fruit trees and most Specials have a fixed yield of one** - you
  check the tree's health once and take the experience.
- **Herbs, allotments, hops and bushes vary**, on a "harvest lives" mechanic:
  three lives, four with compost, five with supercompost, six with ultra, and
  each pick has a chance to spare one. The wiki's `ChanceToSave` needs a
  per-crop `Chance1`/`Chance99` pair that **is not in this module and is not
  anywhere in the Module namespace** - it lives in the calculator's JavaScript.
  So `costing/farming.py` uses the calculator's own published assumed yields
  for those, and says so.

Pure parsing; `remote/api.py` fetches. The Lua is read with a regex rather than
an interpreter because the file is a literal table with no logic in it - and if
that ever stops being true the parse returns nothing rather than something
plausible, which `parse_crops` is written to make obvious.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from chunksim.remote.skillcalc import entries, fields as read_fields

#: The calculator's data table, as raw Lua.
CROPS_PAGE = "Module:Skill calc/Farming"

#: A quoted `name = '...'` value, used to pick the seed out of `materials`.
_NAME = re.compile(r"name\s*=\s*'([^']*)'")


@dataclass(frozen=True)
class Crop:
    """One thing you can plant, and what harvesting it pays."""

    name: str
    #: The patch it goes in: `Herb`, `Tree`, `Fruit tree`, `Allotment`, ...
    patch: str
    level: int
    #: Experience per *item* harvested.
    experience: float
    #: Experience for putting the seed in the ground, paid once.
    plant_experience: float = 0.0
    seed: str = ""
    seeds_per_patch: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "patch": self.patch,
            "level": self.level,
            "experience": self.experience,
            "plant_experience": self.plant_experience,
            "seed": self.seed,
            "seeds_per_patch": self.seeds_per_patch,
        }


def parse_crops(text: str) -> tuple[Crop, ...]:
    """Every crop in the module, in the order written.

    Fields are read first-wins within an entry, so a crop keeps its own `name`
    rather than its seed's; the seed is taken as the *second* name, which is
    the one inside `materials`.
    """
    found: list[Crop] = []
    for entry in entries(text):
        fields = read_fields(entry)
        name, patch = fields.get("name"), fields.get("type")
        level, experience = fields.get("level"), fields.get("xp")
        if not name or not patch or level is None or experience is None:
            continue
        names = _NAME.findall(entry)
        quantity = re.search(r"quantity\s*=\s*([\d.]+)", entry)
        found.append(
            Crop(
                name=name,
                patch=patch,
                level=int(float(level)),
                experience=float(experience),
                plant_experience=float(fields.get("plantXp") or 0.0),
                seed=names[1] if len(names) > 1 else "",
                seeds_per_patch=float(quantity.group(1)) if quantity else 1.0,
            )
        )
    return tuple(found)
