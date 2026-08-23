"""The wiki's bounty task table, and the sea monsters' health beside it.

**Two pages again, and again the second is what makes the first spendable.**
`Bounty tasks` lists every bounty as a `{{BountyTaskLine}}` - a level, an
experience, a notice board, a monster, an item, how many are wanted and how
often it drops - and `Boat combat` carries the health of every sea monster in
the game. Health is the other half of a rate here, because boat combat pays
**one Sailing experience for every point of damage dealt**, so a monster's
hitpoints are what a kill is worth before the bounty pays anything at all.

Read together they say what a bounty costs and what it pays:

    kills  = quantity / rarity
    damage = kills x hitpoints        (which is also the experience the damage pays)

`costing/bounty.py` is the consumer and carries the model; this module only
reads.

**Experience is a property of the monster, not the task.** All nine Albatross
bounties pay 14,575 whatever the item or the quantity, and the twenty monsters
run 3,465 to 47,080 - so the table's `xp` column is really a monster
attribute that the wiki happens to print per row, which is worth knowing
before treating two rows as independent evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Callable, Mapping

#: The page carrying the bounty table.
TASKS_PAGE = "Bounty tasks"

#: The page carrying the sea monsters' health.
COMBAT_PAGE = "Boat combat"

_LINE = re.compile(r"\{\{BountyTaskLine\|([^}]*)\}\}")
#: One row of `Boat combat`'s monster table: a linked name, then hitpoints on
#: the next line. The optional group is the piped display name, which is what
#: `Mogre (sea)|Mogre` and `Manta ray (monster)|Manta ray` need.
_MONSTER = re.compile(r"\n\|\[\[([^\]|]+?)(?:\|([^\]]*))?\]\]\n\|(\d+)\n")


@dataclass(frozen=True)
class BountyTask:
    """One bounty, as the wiki tabulates it."""

    level: int
    experience: int
    notice_board: str
    monster: str
    item: str
    quantity: int
    #: The drop chance as written, `1/2`, `1/3` or `1/10`.
    rarity: str

    @property
    def kills(self) -> float:
        """Expected kills to finish it: `quantity / rarity`.

        The mean of a negative binomial, which is the honest figure for a
        method somebody runs for hours - `costing/gathering.py`'s reason for
        spending expectations rather than medians throughout.
        """
        chance = Fraction(self.rarity)
        return float(self.quantity / chance) if chance else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "experience": self.experience,
            "notice_board": self.notice_board,
            "monster": self.monster,
            "item": self.item,
            "quantity": self.quantity,
            "rarity": self.rarity,
        }


def parse_tasks(text: str) -> tuple[BountyTask, ...]:
    """Every `{{BountyTaskLine}}` on the page."""
    found: list[BountyTask] = []
    for body in _LINE.findall(text):
        args: dict[str, str] = {}
        for part in body.split("|"):
            if "=" in part:
                key, value = part.split("=", 1)
                args[key.strip()] = value.strip()
        if not args.get("xp", "").isdigit() or not args.get("level", "").isdigit():
            continue
        if not args.get("qty", "").isdigit():
            continue
        found.append(
            BountyTask(
                level=int(args["level"]),
                experience=int(args["xp"]),
                notice_board=args["noticeBoard"],
                monster=args["monster"],
                item=args.get("item", ""),
                quantity=int(args["qty"]),
                rarity=args.get("rarity", "1/1"),
            )
        )
    return tuple(found)


def parse_hitpoints(text: str) -> dict[str, int]:
    """`{monster: hitpoints}` from `Boat combat`'s monster table.

    Bounded to that table rather than swept over the page, since the drop
    sections below it link monsters too and would be read as rows.

    **Both names are kept** where the wiki pipes one - `Mogre (sea)|Mogre`
    writes the article title and the display name, and upstream's export uses
    a third spelling again (`Mogre (Sailing)`), so the consumer needs every
    handle it can get.
    """
    start = text.find("==Monsters==")
    end = text.find("===Notable drops===", start if start >= 0 else 0)
    body = text[start if start >= 0 else 0 : end if end > 0 else len(text)]
    found: dict[str, int] = {}
    for title, shown, health in _MONSTER.findall(body):
        found[title] = int(health)
        if shown:
            found[shown] = int(health)
    return found


@dataclass(frozen=True)
class BountyTables:
    """Everything the scrape reads, ready to be written as one blob."""

    tasks: tuple[BountyTask, ...]
    hitpoints: Mapping[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "tasks": [task.as_dict() for task in self.tasks],
            "hitpoints": dict(sorted(self.hitpoints.items())),
        }


def build_tables(
    fetch_pages: Callable[[list[str]], Mapping[str, str]],
) -> BountyTables:
    """Read both pages and pair them up."""
    pages = fetch_pages([TASKS_PAGE, COMBAT_PAGE])
    return BountyTables(
        tasks=parse_tasks(pages.get(TASKS_PAGE, "")),
        hitpoints=parse_hitpoints(pages.get(COMBAT_PAGE, "")),
    )
