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

from dataclasses import dataclass, replace
from typing import Any

import re

from collections import Counter

from fray_claude.remote.wikitable import (
    SCP_LEVEL,
    column_index,
    name_in,
    names_in,
    number,
    rows,
    table_with,
    tables,
)

#: The four pages this reads. `Shortcuts` and `Stall/Thievable` are dedicated
#: transcluded tables; the other two are sections of the skill's own page.
SHORTCUTS_PAGE = "Shortcuts"
AGILITY_PAGE = "Agility"
STALLS_PAGE = "Stall/Thievable"
THIEVING_PAGE = "Thieving"
#: The page whose table gives a log's Firemaking level and experience.
FIREMAKING_PAGE = "Firemaking"
WOODCUTTING_PAGE = "Pay-to-play Woodcutting training"
HUNTER_PAGE = "Hunter training"
FISHING_PAGE = "Pay-to-play Fishing training"

#: The Fishing headings that name one fish rather than a technique, mapped to
#: the export's name for it. The rest cover several fish each and are
#: deliberately not joined. Written out rather than derived by stripping
#: `Raw `: two of the four need it and two do not, so a rule would be a rule
#: with as many exceptions as cases - and this is the same kind of small,
#: auditable table `COURSE_ALIASES` already is.
FISHING_BY_FISH: dict[str, str] = {
    "Monkfish": "Raw monkfish",
    "Karambwan": "Raw karambwan",
    "Infernal eel": "Infernal eel",
    "Sacred eel": "Sacred eel",
}
PAGES: tuple[str, ...] = (
    SHORTCUTS_PAGE,
    AGILITY_PAGE,
    STALLS_PAGE,
    THIEVING_PAGE,
    "Rooftop Agility Courses",
    FIREMAKING_PAGE,
    WOODCUTTING_PAGE,
    HUNTER_PAGE,
    FISHING_PAGE,
)

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

@dataclass(frozen=True)
class SkillRow:
    """One row of one of the four tables, already reduced to what is spent.

    `xp_per_hour` is set only where the table publishes one - courses and
    stalls do, shortcuts and pickpockets do not, and inventing a cycle time
    here would put a modelling decision in a parser. `costing/heuristics.py`
    turns `experience` into a rate for those two.
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


def parse_shortcuts(text: str) -> tuple[SkillRow, ...]:
    """`Shortcuts`: the object, its Agility level, and the xp one use pays.

    Rows with no experience (`{{NA}}`) are dropped rather than zeroed - a
    grapple shortcut that pays nothing is not a training method, and a zero
    would divide into an infinite rate downstream.
    """
    table = table_with(text, "!Level(s)", "!XP")
    found: list[SkillRow] = []
    for cells in rows(table):
        if len(cells) < 6:
            continue
        levels = {
            match.group("skill"): int(match.group("level"))
            for match in SCP_LEVEL.finditer(cells[0])
        }
        level = levels.get("Agility")
        name = name_in(cells[2])
        experience = number(cells[5])
        if level is None or not name or not experience:
            continue
        found.append(SkillRow(name=name, level=level, experience=experience))
    return tuple(found)


def parse_courses(text: str) -> tuple[SkillRow, ...]:
    """`Agility`'s full course list: level, course, experience per hour."""
    table = table_with(text, "Experience per hour")
    found: list[SkillRow] = []
    for cells in rows(table):
        if len(cells) < 4:
            continue
        level, name, rate = number(cells[0]), name_in(cells[1]), number(cells[3])
        if level is None or not name or not rate:
            continue
        found.append(SkillRow(name=name, level=int(level), xp_per_hour=rate))
    return tuple(found)


def parse_stalls(text: str) -> tuple[SkillRow, ...]:
    """`Stall/Thievable`: level, xp a steal, and the wiki's own max xp/hour.

    The last column is already `3600 / respawn * xp`, so the arithmetic is
    upstream's rather than a second copy of it here.
    """
    table = table_with(text, "Respawn Time")
    found: list[SkillRow] = []
    for cells in rows(table):
        name = name_in(cells[0])
        numbers = [(index, number(cell)) for index, cell in enumerate(cells[1:], 1)]
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
    table = table_with(text, "100% success lvl")
    found: list[SkillRow] = []
    for cells in rows(table):
        names = names_in(" ".join(cells[:2]))
        numbers = [value for cell in cells if (value := number(cell)) is not None]
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


#: The page whose table carries marks of grace per hour, per course.
ROOFTOP_PAGE = "Rooftop Agility Courses"

#: `10-13.8`, `16\u201318` - a bare range with no thousands separator. The `t`
#: guard is load-bearing: the lap-time column two along reads `108\u2013110t`,
#: and the header spans two rows so the column cannot be found by index.
_MARK_RANGE = re.compile(r"^(\d+(?:\.\d+)?)\s*[-\u2013]\s*(\d+(?:\.\d+)?)(?![\d.,]|\s*t\b)")


def parse_mark_rate(text: str) -> float | None:
    """Marks of grace an hour, from the rooftop table's own column.

    **The best published figure, and the spread is why one number will do.**
    Every course pays between 8 and 18 an hour - Canifis is the best at 16-18
    and Al Kharid the worst at 8-11.5 - so which course a map can reach barely
    moves the answer, which is what makes a single currency rate honest here
    where a per-map one would be false precision.

    The top of the range, because a rate is what the best available method
    pays; that is the convention every other rate in this project follows.
    """
    table = table_with(text, "Marks of grace")
    best: float | None = None
    for cells in rows(table):
        for cell in cells:
            found = _MARK_RANGE.match(cell.strip())
            if found is None:
                continue
            value = float(found.group(2))
            # Marks are single figures an hour; anything larger is a column
            # this pattern was not meant to reach.
            if 0 < value <= 40 and (best is None or value > best):
                best = value
    return best


def parse_burning(text: str) -> tuple[SkillRow, ...]:
    """Each log's Firemaking level and the experience burning one pays.

    **Burning a log is not a `{{Recipe}}`**, so the recipe bucket has only
    *pyre* logs and the skill was left with one rated method above level 75.
    The plain table on the skill's own page has all of them - normal logs 40
    xp at level 1, oak 60 at 15, willow 90 at 30 - and `costing/heuristics.py`
    turns that into a rate.

    Keyed by the **log**, which is what the export's `Burn ~|oak logs|~`
    challenge names in its `Items`.
    """
    table = table_with(text, "Experience")
    found: list[SkillRow] = []
    body = list(rows(table))
    if not body:
        return ()
    width = Counter(len(cells) for cells in body).most_common(1)[0][0]
    at_level = column_index(table, "level", width=width)
    at_item = column_index(table, "item", width=width)
    at_xp = column_index(table, "experience", width=width)
    if at_level is None or at_item is None or at_xp is None:
        return ()
    for cells in body:
        if len(cells) <= max(at_level, at_item, at_xp):
            continue
        level, name, experience = (
            number(cells[at_level]),
            name_in(cells[at_item]),
            number(cells[at_xp]),
        )
        if level is None or not name or not experience:
            continue
        found.append(SkillRow(name=name, level=int(level), experience=experience))
    return tuple(found)


#: `{{plinkt|Willow logs|txt=Willow}}` - the item link that opens every row of
#: the Woodcutting rates table. The first parameter is the item's real name,
#: which is what the export's `Output` holds; `txt=` is only how it is
#: displayed, so a parser reading the label would join nothing.
_PLINKT = re.compile(r"\{\{plinkt\|([^|}]+)")

#: A footnote marker, which lands inside the level and rate cells alike.
_REF = re.compile(r"<ref.*?(?:/>|</ref>)", re.DOTALL)


def parse_woodcutting(text: str) -> tuple[SkillRow, ...]:
    """Each log's Woodcutting level and the experience an hour cutting it pays.

    **The one gathering skill the wiki tabulates per item.** Mining's ore table
    and Fishing's fish table publish experience per *action* and stop there,
    which is the number `Module:Skill calc` already carries and not the one a
    rate needs; only `Pay-to-play Woodcutting training` gives an hourly figure
    for every log. So this reads that table and the other two gathering skills
    stay on their guide joins - see this module's docstring.

    Joined on the item, `Output` to `{{plinkt}}`'s first parameter, which made
    all sixteen rows join and left none over. That is a whole-string comparison
    of two item names, so there is nothing fuzzy here either.

    **The bottom of a range, not the top.** Teak reads `90,000-255,000` because
    the upper figure is 2-tick manipulation, which the page describes as
    "difficult and click-intensive"; the same table's own note says "without
    tick-manipulation, the experience is 90,000 per hour". Quoting the top
    would price every climb on a technique almost nobody sustains - and it is
    the opposite of the convention `parse_mark_rate` follows, deliberately: a
    mark rate's range is which *course* you pick, where this one is how well
    you click.
    """
    found: list[SkillRow] = []
    for table in tables(text):
        for cells in rows(table):
            if len(cells) < 4:
                continue
            item = _PLINKT.search(cells[0])
            if item is None:
                continue
            level = number(_REF.sub("", cells[1]))
            rates = [
                float(value.replace(",", ""))
                for value in re.findall(r"[\d,]{4,}", _REF.sub("", cells[3]))
            ]
            if level is None or not rates:
                continue
            found.append(
                SkillRow(
                    name=item.group(1).strip(),
                    level=int(level),
                    xp_per_hour=min(rates),
                )
            )
    return tuple(found)


#: A `(Level)` heading's own words, so the technique's name is what is left.
_HEADING_LEVELS = re.compile(r"^Levels?\s+[\d/\u2013\u2014-]+\s*:\s*", re.I)

#: A wikitext section heading, at any depth.
_HEADING = re.compile(r"^={2,4}\s*(.+?)\s*={2,4}\s*$", re.M)


def _singular(name: str) -> str:
    """`Black chinchompas` -> `Black chinchompa`. Plural `s` only."""
    return name[:-1] if name.endswith("s") and not name.endswith("ss") else name


def _heading_rates(text: str) -> tuple[SkillRow, ...]:
    """Every `level -> XP/h` table in `text`, keyed by the heading above it.

    Shared by Hunter and Fishing, whose training pages are the same shape and
    unlike every other table here: the rate is a curve down the page and the
    *technique* is named by the section heading rather than by a column. What
    differs is how many of those headings name something the export also
    names - see each caller.
    """
    found: list[SkillRow] = []
    marks = [(m.start(), m.group(1)) for m in _HEADING.finditer(text)]
    for index, (start, title) in enumerate(marks):
        end = marks[index + 1][0] if index + 1 < len(marks) else len(text)
        name = _singular(_HEADING_LEVELS.sub("", title).strip())
        for table in tables(text[start:end]):
            if "XP/h" not in table:
                continue
            columns = [
                position
                for position, cell in enumerate(
                    header.strip().lstrip("!").strip() for header in table.splitlines() if header.startswith("!")
                )
                if cell.startswith("XP/h")
            ]
            for cells in rows(table):
                level = number(_REF.sub("", cells[0])) if cells else None
                rates = [
                    float(value.replace(",", ""))
                    for value in re.findall(r"[\d,]{4,}", " ".join(cells[1:]))
                ]
                if level is None or not rates or level > 99:
                    continue
                found.append(
                    SkillRow(
                        name=name,
                        level=int(level),
                        # Last column, and only the plain figures - a `GP/h`
                        # cell is `{{Coins|...}}` and carries no bare number.
                        xp_per_hour=rates[-1] if len(columns) > 1 else rates[0],
                    )
                )
                break  # the lowest level the table quotes
    return tuple(found)


def parse_fishing(text: str) -> tuple[SkillRow, ...]:
    """Fishing rates, for the four techniques that are named after a fish.

    **Most of this page cannot be joined and that is the finding, not a
    shortfall.** Its headings name *techniques* - `Fly fishing`, `Barbarian
    Fishing`, `Drift net fishing`, `Tempoross`, `Minnows` - and a technique
    covers several fish where the export has one challenge per fish. Mapping
    `Fly fishing` onto both `Raw trout` and `Raw salmon` would be a hand-built
    table of exactly the kind `COURSE_ALIASES` is, and it would still have to
    choose one rate for a curve that doubles across the technique's range.

    Four headings do name one fish, and those join like Hunter's: `Monkfish`,
    `Karambwan`, `Infernal eel`, `Sacred eel`. Their curves are nearly flat
    (karambwan 29,000 at 65 to 31,000 at 99), which is what makes taking the
    lowest row honest here where it would not be for fly fishing.

    Everything else keeps its money-making-guide join. Checked rather than
    assumed: the guides' figures agree with this page where both cover a
    method - the salmon rate in use is 25,432 against the page's own 25,000
    AFK at that level - so the guides are not being overridden by a better
    source, only supplemented where they have nothing.
    """
    return tuple(
        replace(row, name=FISHING_BY_FISH[row.name])
        for row in _heading_rates(text)
        if row.name in FISHING_BY_FISH
    )


def parse_hunter(text: str) -> tuple[SkillRow, ...]:
    """What each Hunter technique pays an hour, at the level it opens.

    **Hunter publishes a rate per technique, not per creature**, and its
    tables are `Hunter level -> XP/h` curves rather than one figure per row -
    a different shape from every other table here. The technique is named by
    the *section heading* that owns the table, which is wikitext structure
    rather than prose, so the join is a whole-string comparison after two
    stated normalisations: the heading's `Levels 73-99: ` prefix comes off,
    and a plural `s` does. Four of the six join - `Black chinchompas`,
    `Maniacal monkeys`, `Carnivorous chinchompas`, `Herbiboar` - and the two
    that do not are activities with no one creature to name (`Drift net
    fishing`, `Hunters' Rumours`), which is a correct miss rather than a gap.

    **The first row and the last column**, both deliberately conservative and
    both matching decisions already made here. The first row is the lowest
    level the table quotes, which is the rate at the level the method opens -
    the same choice `PICKPOCKET_CYCLE_SECONDS` is calibrated against, for a
    rate that climbs with level. The last `XP/h` column is the unassisted one
    where a table splits: black chinchompas quote `Alt` before `Solo` and
    carnivorous ones `Tick manip.` before `No tick manip.`, so the last column
    is the figure a player gets without a second account or 2-tick clicking -
    the same reasoning as `parse_woodcutting` taking the bottom of its range.

    The export disambiguates a creature from its item with a ` (Hunter)`
    suffix (`Black chinchompa (Hunter)`), which `heuristics._join_keys`
    strips; nothing about that is done here.
    """
    return _heading_rates(text)


def parse_pages(pages: dict[str, str]) -> dict[str, tuple[SkillRow, ...]]:
    """Every table this module reads, keyed by what it describes."""
    return {
        "shortcuts": parse_shortcuts(pages.get(SHORTCUTS_PAGE, "")),
        "courses": parse_courses(pages.get(AGILITY_PAGE, "")),
        "stalls": parse_stalls(pages.get(STALLS_PAGE, "")),
        "pickpockets": parse_pickpockets(pages.get(THIEVING_PAGE, "")),
        "burning": parse_burning(pages.get(FIREMAKING_PAGE, "")),
        "woodcutting": parse_woodcutting(pages.get(WOODCUTTING_PAGE, "")),
        "hunter": parse_hunter(pages.get(HUNTER_PAGE, "")),
        "fishing": parse_fishing(pages.get(FISHING_PAGE, "")),
    }
