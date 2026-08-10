"""Agility and Thieving rates, from the wiki's own tables.

**The two skills `{{Recipe}}` cannot describe.** A rooftop course is not a
recipe and neither is a pickpocket, so `remote/recipes.py` returns nothing for
either - Agility and Thieving have zero rows in the wiki's `recipe` bucket, and
no money-making guide joins their method names. The result was `fray estimate`
pricing every one of them at the 1,000/hr floor: 2,142 hours for one Agility
climb, with `(none found)` where a method should be.

The export is not the gap. It already holds 9 rooftop courses, 9 other courses,
5 Sepulchre floors, 185 shortcuts, 33 pickpocket targets and 21 stalls, each
with its level and the object or NPC it needs. What it has never held is an
experience figure. That is what this module reads, from four wiki pages:

| page | rows | gives |
|---|---|---|
| `Shortcuts` | 168 | level, object, xp per use |
| `Agility` (`Full list`) | 23 | level, course, xp per hour |
| `Stall/Thievable` | 30 | level, stall, xp, respawn, max xp/hour |
| `Thieving` (`Thievable NPCs`) | 33 | level, npc, xp per pickpocket |

**Three of the four join on a structured name, not a fuzzy one.** A shortcut
row links its object (`[[Rocks (Corsair Cove)|Rocks]]`) and the export names
the same object in the challenge's `Objects`; stalls and pickpockets work the
same way through `Objects`/`NPCs`. So there is nothing to be fuzzy about and no
`contained` tier here - contrast `heuristics.py`, whose joins really do span two
vocabularies.

**The courses are the exception, and they are hand-mapped for a reason.** They
join on the course *name*, and the export spells three of them differently:
`Canafis Rooftop Course` for the wiki's Canifis, and `Colossal Wyrm Basic`/
`Advanced Course` where the wiki has one page. A fuzzy tier would paper over
exactly that and then quietly mis-join something else; a 23-entry table of
aliases is checkable by reading it, which is the standard this project already
holds `heuristics.py`'s joins to.

Pure parsing only - `remote/api.py` does the fetching, as it does for every
other host, and `costing/` decides what rate a row implies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterator

#: The four pages this reads. `Shortcuts` and `Stall/Thievable` are dedicated
#: transcluded tables; the other two are sections of the skill's own page.
SHORTCUTS_PAGE = "Shortcuts"
AGILITY_PAGE = "Agility"
STALLS_PAGE = "Stall/Thievable"
THIEVING_PAGE = "Thieving"
PAGES: tuple[str, ...] = (SHORTCUTS_PAGE, AGILITY_PAGE, STALLS_PAGE, THIEVING_PAGE)

#: Export course name -> the wiki's spelling. **Only for the ones that differ.**
#: Upstream's `Canafis` is a typo for Canifis, and its Colossal Wyrm courses are
#: split where the wiki keeps one page; the export has no Prifddinas course at
#: all. Everything else joins on its own name.
COURSE_ALIASES: dict[str, str] = {
    "Canafis Rooftop Course": "Canifis Rooftop Course",
    "Colossal Wyrm Basic Course": "Colossal Wyrm Agility Course",
    "Colossal Wyrm Advanced Course": "Colossal Wyrm Agility Course",
    "Shayzien Agility Course": "Shayzien Basic Course",
}

_NUMBER = re.compile(r"^\s*([\d,]+(?:\.\d+)?)")
_SCP_LEVEL = re.compile(r"\{\{SCP\|(?P<skill>[A-Za-z ]+)\|(?P<level>\d+)")
_LINK_TARGET = re.compile(r"\[\[([^\]|#]+)")
_PLINK_NAME = re.compile(r"\{\{(?:plink|chatl)[a-z]*\|([^|}]+)")
_PLINK_TEXT = re.compile(r"\|txt=([^|}]+)")


@dataclass(frozen=True)
class SkillRow:
    """One row of one of the four tables, already reduced to what is spent.

    `xp_per_hour` is set only where the table publishes one - courses and
    stalls do, shortcuts and pickpockets do not, and inventing a cycle time
    here would put a modelling decision in a parser. `costing/` turns
    `experience` into a rate for those two.
    """

    #: The name to join on: an object for a shortcut or stall, an NPC for a
    #: pickpocket, a course name for a course.
    name: str
    level: int
    experience: float = 0.0
    xp_per_hour: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "level": self.level,
            "experience": self.experience,
            "xp_per_hour": self.xp_per_hour,
        }


def _split_cells(row: str) -> list[str]:
    """A table row's cells, respecting `{{...}}` and `[[...]]` nesting.

    Wikitext separates cells with a newline `|` or an inline `||`, and both
    appear inside templates (`{{Coins|{{GEP|Amylase crystal|10*13.8}}}}`) where
    they mean nothing of the sort. A depth counter is the difference between
    reading a level and reading half a template.
    """
    cells: list[str] = []
    current: list[str] = []
    depth = 0
    index = 0
    while index < len(row):
        pair = row[index : index + 2]
        if pair in ("{{", "[["):
            depth += 1
            current.append(pair)
            index += 2
            continue
        if pair in ("}}", "]]"):
            depth = max(0, depth - 1)
            current.append(pair)
            index += 2
            continue
        if depth == 0 and pair == "||":
            cells.append("".join(current))
            current = []
            index += 2
            continue
        if depth == 0 and row[index] == "\n" and row[index + 1 : index + 2] == "|":
            cells.append("".join(current))
            current = []
            index += 2
            continue
        current.append(row[index])
        index += 1
    cells.append("".join(current))
    return [cell.strip() for cell in cells]


def _tables(text: str) -> Iterator[str]:
    """Every `{| ... |}` block in `text`, outermost only."""
    depth = 0
    start = 0
    for match in re.finditer(r"\{\||\|\}", text):
        if match.group(0) == "{|":
            if depth == 0:
                start = match.start()
            depth += 1
        elif depth:
            depth -= 1
            if depth == 0:
                yield text[start : match.end()]


def _table_with(text: str, *needles: str) -> str:
    """The first table whose header mentions all of `needles`."""
    for table in _tables(text):
        head = table[: table.find("\n|-") if "\n|-" in table else len(table)]
        if all(needle in head for needle in needles):
            return table
    return ""


def _rows(table: str) -> Iterator[list[str]]:
    """Data rows of `table`, header skipped, as cell lists."""
    for chunk in table.split("\n|-")[1:]:
        body = chunk.split("\n|}")[0]
        cells = [cell for cell in _split_cells(body) if cell]
        if cells:
            yield cells


def _number(cell: str) -> float | None:
    found = _NUMBER.match(cell.replace("&nbsp;", " ").strip())
    return float(found.group(1).replace(",", "")) if found else None


def _names_in(cell: str) -> tuple[str, ...]:
    """Every joinable name a cell offers, in order, deduplicated.

    **Targets, not display text**, because `[[Rocks (Corsair Cove)|Rocks]]`
    renders as "Rocks" and joins as nothing - the export names the
    disambiguated object. But `{{plinkt|Warrior (Thieving)|txt=Warrior}}`
    needs the *other* half too: the page is disambiguated where the export's
    NPC is not, so both spellings are offered and the caller keeps whichever
    joins.

    All of them rather than the first, because one cell can name two things -
    `{{plinkt|Man}}/[[Woman]]` is two NPCs on one row, and taking either alone
    silently loses a level-1 training method.
    """
    found = [
        *(match.group(1).strip() for match in _PLINK_NAME.finditer(cell)),
        *(match.group(1).strip() for match in _PLINK_TEXT.finditer(cell)),
        *(match.group(1).strip() for match in _LINK_TARGET.finditer(cell)),
    ]
    return tuple(dict.fromkeys(name for name in found if name))


def _name_in(cell: str) -> str:
    """The first joinable name in a cell, or `""`."""
    names = _names_in(cell)
    return names[0] if names else ""


def parse_shortcuts(text: str) -> tuple[SkillRow, ...]:
    """`Shortcuts`: the object, its Agility level, and the xp one use pays.

    Rows with no experience (`{{NA}}`) are dropped rather than zeroed - a
    grapple shortcut that pays nothing is not a training method, and a zero
    would divide into an infinite rate downstream.
    """
    table = _table_with(text, "!Level(s)", "!XP")
    found: list[SkillRow] = []
    for cells in _rows(table):
        if len(cells) < 6:
            continue
        levels = {
            match.group("skill"): int(match.group("level"))
            for match in _SCP_LEVEL.finditer(cells[0])
        }
        level = levels.get("Agility")
        name = _name_in(cells[2])
        experience = _number(cells[5])
        if level is None or not name or not experience:
            continue
        found.append(SkillRow(name=name, level=level, experience=experience))
    return tuple(found)


def parse_courses(text: str) -> tuple[SkillRow, ...]:
    """`Agility`'s full course list: level, course, experience per hour."""
    table = _table_with(text, "Experience per hour")
    found: list[SkillRow] = []
    for cells in _rows(table):
        if len(cells) < 4:
            continue
        level, name, rate = _number(cells[0]), _name_in(cells[1]), _number(cells[3])
        if level is None or not name or not rate:
            continue
        found.append(SkillRow(name=name, level=int(level), xp_per_hour=rate))
    return tuple(found)


def parse_stalls(text: str) -> tuple[SkillRow, ...]:
    """`Stall/Thievable`: level, xp a steal, and the wiki's own max xp/hour.

    The last column is already `3600 / respawn * xp`, so the arithmetic is
    upstream's rather than a second copy of it here.
    """
    table = _table_with(text, "Respawn Time")
    found: list[SkillRow] = []
    for cells in _rows(table):
        name = _name_in(cells[0])
        numbers = [(index, _number(cell)) for index, cell in enumerate(cells[1:], 1)]
        real = [(index, value) for index, value in numbers if value is not None]
        if not name or len(real) < 2:
            continue
        level, experience = real[0][1], real[1][1]
        # The rate column sits after the respawn time; take the last number on
        # the row that is larger than the per-steal xp.
        rates = [value for _, value in real[2:] if value > experience]
        found.append(
            SkillRow(
                name=name,
                level=int(level),
                experience=experience,
                xp_per_hour=rates[-1] if rates else None,
            )
        )
    return tuple(found)


def parse_pickpockets(text: str) -> tuple[SkillRow, ...]:
    """`Thieving`'s thievable NPCs: level and xp per successful pickpocket."""
    table = _table_with(text, "100% success lvl")
    found: list[SkillRow] = []
    for cells in _rows(table):
        names = _names_in(" ".join(cells[:2]))
        numbers = [value for cell in cells if (value := _number(cell)) is not None]
        if not names or len(numbers) < 2:
            continue
        # One row can name two NPCs (`Man`/`Woman`) and one NPC two ways (a
        # disambiguated page plus its display text). Both get the row's rate;
        # only the spellings the export uses will ever be looked up.
        found.extend(
            SkillRow(name=name, level=int(numbers[0]), experience=numbers[1])
            for name in names
        )
    return tuple(found)


def parse_pages(pages: dict[str, str]) -> dict[str, tuple[SkillRow, ...]]:
    """Every table this module reads, keyed by what it describes."""
    return {
        "shortcuts": parse_shortcuts(pages.get(SHORTCUTS_PAGE, "")),
        "courses": parse_courses(pages.get(AGILITY_PAGE, "")),
        "stalls": parse_stalls(pages.get(STALLS_PAGE, "")),
        "pickpockets": parse_pickpockets(pages.get(THIEVING_PAGE, "")),
    }
