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

from fray_claude.remote.wiki import parse_amount
from fray_claude.remote.wikitable import (
    SCP_LEVEL,
    column_index,
    header_columns,
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
MINING_PAGE = "Pay-to-play Mining training"
HERBLORE_PAGE = "Herblore training"
#: **A transcluded template, not a section.** `Fletching training` writes
#: `{{Table/Fletching/Darts}}` where the table should be, so the page's own
#: wikitext holds the prose around it and none of the figures.
DARTS_PAGE = "Template:Table/Fletching/Darts"
#: The Thieving *training guide*, not the skill page `THIEVING_PAGE` reads -
#: the pickpocket table is on the latter and Pyramid Plunder is only here.
THIEVING_TRAINING_PAGE = "Thieving training"
#: The Runecraft training guide, read for the Guardians of the Rift table.
RUNECRAFT_PAGE = "Pay-to-play Runecraft training"
FARMING_PAGE = "Farming training"
SAILING_PAGE = "Sailing training"
#: The skill's own page, whose `Types of food` tables are the only place the
#: experience for cooking one item is written down.
COOKING_PAGE = "Cooking"

#: One `{{formatnum:{{#expr:...}}}}` block. **A cell may hold two** - the
#: Gwenith Glide's Marlin figure is quoted again with a crystal extractor on
#: a line of its own - and taking the first is the conservative end, the same
#: choice as the bottom of a published range everywhere else here. Without
#: this the cell reads as two templates, which `wiki.parse_amount` correctly
#: refuses, and the best trial in the game silently goes unrated.
_FORMATNUM = re.compile(r"\{\{formatnum:\{\{#expr:[^{}]*\}\}\}\}")

#: The three difficulty ranks every Barracuda trial is run at, in the order
#: the guide's header puts them and the order the export names them. A fixed
#: game concept rather than a parse, and short enough to read.
BARRACUDA_RANKS: tuple[str, ...] = ("Swordfish", "Shark", "Marlin")

#: Upstream's own category for the three fruits grown inside the Tithe Farm
#: minigame, which is what `heuristics._add_tithe` joins on.
TITHE_CATEGORY = "Tithe Farm"

#: The task-name suffix upstream gives the twelve runes craftable inside
#: Guardians of the Rift. **Upstream's own wording, not a pattern invented
#: here**, which is what makes the join structural.
GUARDIAN_SUFFIX = "with guardian essence"

#: The Pyramid Plunder rows the wiki publishes, by the Thieving level each
#: band opens at, mapped to the export's name for the room that opens there.
#: **The wiki's breakpoints are the export's challenge levels** - 71, 81 and
#: 91 are exactly where the sixth, seventh and eighth rooms unlock - so the
#: minigame's curve is already three methods and needs no curve support, the
#: same coincidence that made Barbarian Fishing tractable. The five rooms
#: below have no published rate at all: the guide says the rates before 91
#: are "much lower" and declines to quote one, so they are refused rather
#: than given the level-71 figure.
PLUNDER_BY_LEVEL: dict[int, str] = {
    71: "Sixth room of Pyramid Plunder",
    81: "Seventh room of Pyramid Plunder",
    91: "Eighth room of Pyramid Plunder",
}

#: The Mining headings that name a rock the export also names, mapped to the
#: export's name for it. `_names` offers a heading under both spellings, so
#: these keys are the singular ones; the values are what the challenge
#: carries, which is plural for two of the three.
MINING_BY_ROCK: dict[str, str] = {
    "Granite": "Granite",
    "Gem rock": "Gem rocks",
    "Calcified rock": "Calcified rocks",
}

#: The Fishing headings that name one fish rather than a technique, mapped to
#: the export's name for it. The rest cover several fish each and are
#: deliberately not joined. Written out rather than derived by stripping
#: `Raw `: two of the four need it and two do not, so a rule would be a rule
#: with as many exceptions as cases - and this is the same kind of small,
#: auditable table `COURSE_ALIASES` already is.
#: Barbarian Fishing's table rows, by the Fishing level each one states, to
#: the export's name for the fish caught at that level. **The wiki's own
#: breakpoints are the export's challenge levels** - 48, 58 and 70 are exactly
#: where leaping trout, salmon and sturgeon unlock - so the technique's curve
#: is already three methods and needs no curve support to model. Its rows at
#: 80, 90 and 99 are the sturgeon method again at higher level and have no
#: challenge of their own; dropping them leaves sturgeon at its level-70
#: figure, which is the conservative end.
BARBARIAN_PAGE_HEADING = "Barbarian Fishing"
BARBARIAN_BY_LEVEL: dict[int, str] = {
    48: "Leaping trout",
    58: "Leaping salmon",
    70: "Leaping sturgeon",
}

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
    MINING_PAGE,
    HERBLORE_PAGE,
    DARTS_PAGE,
    THIEVING_TRAINING_PAGE,
    RUNECRAFT_PAGE,
    FARMING_PAGE,
    SAILING_PAGE,
    COOKING_PAGE,
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


#: A prose rate, and the *low* end where the page publishes a range:
#: `31,000 experience per hour`, `20,000-28,000 experience per hour`. The
#: words are required adjacent, so `500 coins` and `4 seconds` cannot match.
_PROSE_RATE = re.compile(
    r"([\d,]{3,})(?:\s*[\u2013\u2014-]\s*[\d,]{3,})?\s*"
    r"(?:experience|xp)\s+per\s+hour",
    re.I,
)

#: A falconry bullet: `* [[Spotted kebbit]]s (43-57) give 60,000 up to 70,000.`
_QUARRY_BULLET = re.compile(r"^\*\s*\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]", re.M)


def _names(title: str) -> tuple[str, ...]:
    """A heading's name and its singular, because a heading may be either.

    `Black chinchompas` is plural and `Sapphire glacialis` is not, and no rule
    tells them apart - stripping a trailing `s` from the second gives
    `glaciali`, which joins nothing while looking like it tried. So both
    spellings are offered and the export picks, the same way `parse_herblore`
    emits a potion under its bare and its dosed name.
    """
    name = _HEADING_LEVELS.sub("", title).strip()
    bare = name[:-1] if name.endswith("s") and not name.endswith("ss") else name
    return (name,) if bare == name else (name, bare)


def _sections(text: str) -> list[tuple[str, str]]:
    """Each section of `text`, as (heading, body including the heading)."""
    marks = [(m.start(), m.group(1)) for m in _HEADING.finditer(text)]
    return [
        (title, text[start : marks[index + 1][0] if index + 1 < len(marks) else len(text)])
        for index, (start, title) in enumerate(marks)
    ]


def _heading_rates(text: str) -> tuple[SkillRow, ...]:
    """Every `level -> XP/h` table in `text`, keyed by the heading above it.

    Shared by Hunter and Fishing, whose training pages are the same shape and
    unlike every other table here: the rate is a curve down the page and the
    *technique* is named by the section heading rather than by a column. What
    differs is how many of those headings name something the export also
    names - see each caller.
    """
    found: list[SkillRow] = []
    for title, body in _sections(text):
        for table in tables(body):
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
                found += [
                    SkillRow(
                        name=name,
                        level=int(level),
                        # Last column, and only the plain figures - a `GP/h`
                        # cell is `{{Coins|...}}` and carries no bare number.
                        xp_per_hour=rates[-1] if len(columns) > 1 else rates[0],
                    )
                    for name in _names(title)
                ]
                break  # the lowest level the table quotes
    return tuple(found)


def _prose_rates(text: str) -> tuple[SkillRow, ...]:
    """The rate a section states in words, for the sections holding no table.

    **Hunter publishes most of its rates in prose**, one section per creature:
    `Players can gain around 13,000 experience per hour.` The heading is still
    structure - it names the creature and the level the method opens at - and
    what changes is only where the number is read from, so this walks the same
    sections `_heading_rates` does and takes the ones it left behind.

    Two rules, both of them the conservative reading this project already
    takes elsewhere:

    - **The lowest figure the section quotes.** A section states several: a
      range (`20,000-28,000`), a better rate with more traps, a better one
      with an alternate account feeding supplies, a level-99 ceiling. Taking
      the minimum is the same choice as `parse_woodcutting` taking the bottom
      of a published range and `_heading_rates` taking a table's first row.
    - **The level the heading opens at**, since there is no table column to
      read one from. `Levels 29-43: Swamp lizards` is a level 29 method.

    A section holding an `XP/h` table is skipped, so the two readers never
    describe the same technique and the table - which resolves a whole curve -
    always wins.
    """
    found: list[SkillRow] = []
    for title, body in _sections(text):
        levels = _HEADING_LEVELS.match(title)
        if levels is None or any("XP/h" in table for table in tables(body)):
            continue
        opens = re.findall(r"\d+", levels.group(0))
        rates = [float(value.replace(",", "")) for value in _PROSE_RATE.findall(body)]
        if not opens or not rates:
            continue
        found += [
            SkillRow(name=name, level=int(opens[0]), xp_per_hour=min(rates))
            for name in _names(title)
        ]
    return tuple(found)


def _quarry_rows(text: str) -> tuple[SkillRow, ...]:
    """Falconry, whose one section is three creatures in a bulleted list.

    `* [[Spotted kebbit]]s (43-57) give 60,000 up to 70,000.` - the heading
    names the *technique* and so joins nothing, exactly like Fishing's `Fly
    fishing`, but each bullet links the creature it describes and the export
    has a challenge per kebbit. So the bullet is the row here and the link is
    the name, which is wikitext structure rather than prose.

    The level comes from the bullet's own parenthetical range and the rate is
    the lowest figure in the bullet, both for the reasons `_prose_rates`
    states. Bullets naming no creature the export knows simply miss.
    """
    found: list[SkillRow] = []
    for _, body in _sections(text):
        for line in body.splitlines():
            bullet = _QUARRY_BULLET.match(line)
            if bullet is None:
                continue
            rest = line[bullet.end() :]
            # `(43-57)`, and `(69+)` for the one with no upper bound.
            level = re.search(r"\((\d{1,2})\s*[+\u2013\u2014-]", rest)
            rates = [float(value.replace(",", "")) for value in re.findall(r"[\d,]{5,}", rest)]
            if level is None or not rates:
                continue
            found.append(
                SkillRow(
                    name=bullet.group(1).strip(),
                    level=int(level.group(1)),
                    xp_per_hour=min(rates),
                )
            )
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
    named = tuple(
        replace(row, name=FISHING_BY_FISH[row.name])
        for row in _heading_rates(text)
        if row.name in FISHING_BY_FISH
    )
    return named + _barbarian_rows(text)


def _barbarian_rows(text: str) -> tuple[SkillRow, ...]:
    """Barbarian Fishing, as the three methods its own table already is.

    **The wiki's level breakpoints are the export's challenge levels.** The
    table steps at 48, 58 and 70, which is exactly where leaping trout, salmon
    and sturgeon unlock, so what looks like one technique with a curve is three
    challenges with a rate each - and the band walk then uses the right one at
    the right level with no curve support needed. That correspondence is why
    this is a structural join rather than a guess: the rows *are* the fish.

    **The AFK column, and this skill's own share of it.** The table gives
    `XP/h (AFK)` before `XP/h (3-tick)`, so unlike Hunter's `Alt`/`Solo` the
    conservative group is the *first* rather than the last - which is why this
    reads the column explicitly instead of reusing `_heading_rates`' position
    rule. Within it, the `Fishing` column rather than the `Total`: barbarian
    fishing really does pay Strength and Agility as well (48,000 Fishing
    against 56,800 total at level 70), but those belong to those skills and
    crediting them here would price one action into three climbs.
    """
    start = text.find("== " + BARBARIAN_PAGE_HEADING)
    if start < 0:
        start = text.find(BARBARIAN_PAGE_HEADING)
    if start < 0:
        return ()
    for table in tables(text[start:]):
        if "XP/h (AFK)" not in table:
            continue
        found: list[SkillRow] = []
        for cells in rows(table):
            level = number(_REF.sub("", cells[0])) if cells else None
            if level is None or int(level) not in BARBARIAN_BY_LEVEL:
                continue
            rates = [
                float(value.replace(",", ""))
                for value in re.findall(r"[\d,]{4,}", " ".join(cells[1:]))
            ]
            if not rates:
                continue
            found.append(
                SkillRow(
                    name=BARBARIAN_BY_LEVEL[int(level)],
                    level=int(level),
                    xp_per_hour=rates[0],
                )
            )
        return tuple(found)
    return ()


#: `{{plinkt|Name|pic=Name(3)}}` - the item, and the dose-suffixed form the
#: export actually keys by.
_PLINKT_FULL = re.compile(r"\{\{plinkt\|([^}]+)\}\}")


def parse_herblore(text: str) -> tuple[SkillRow, ...]:
    """What each potion pays an hour, from the per-item tables.

    **The one page where the rate is already tabulated per item and literal.**
    Unlike Crafting and Fletching, whose figures are MediaWiki `{{#var:}}` and
    `{{#expr:}}` expressions that wikitext cannot yield, Herblore's tables
    carry `| 3 | Attack potion | ... | 25 | 62,500 |` outright - so this reads
    them with no evaluation and no rendered-HTML fetch.

    **The first `{{plinkt}}` in a row is the potion**; the two after it are its
    base and secondary, which are ingredients rather than methods and must not
    be emitted. That is why this cannot use a naive "every plinkt is a row"
    walk the way `parse_woodcutting` does.

    **Both the name and its `pic=` are emitted**, because the export keys by
    dose - `attack potion(3)` - where the wiki names the potion and puts the
    dosed form in `pic=`. Measured over the page: the bare name joins 45 of
    the challenges and the `pic=` form another 35, and emitting both costs a
    duplicate lookup key rather than a decision about which is right.
    """
    found: list[SkillRow] = []
    for table in tables(text):
        if "plinkt" not in table:
            continue
        body = list(rows(table))
        if not body:
            continue
        width = Counter(len(cells) for cells in body).most_common(1)[0][0]
        # `header_columns` normalises, so `XP/Hour` arrives as `xp hour`.
        at_rate = column_index(table, "xp hour", "xp h", width=width)
        at_level = column_index(table, "level", width=width)
        if at_rate is None or at_level is None:
            continue
        for cells in body:
            if len(cells) <= max(at_rate, at_level):
                continue
            level = number(_REF.sub("", cells[at_level]))
            rate = number(_REF.sub("", cells[at_rate]))
            if level is None or rate is None or rate <= 0:
                continue
            # The potion, not its ingredients: the *first* plinkt in the row.
            first = next(
                (m for cell in cells for m in [_PLINKT_FULL.search(cell)] if m), None
            )
            if first is None:
                continue
            parts = [part.strip() for part in first.group(1).split("|")]
            names = [parts[0]]
            pic = next((p.split("=", 1)[1].strip() for p in parts[1:] if p.startswith("pic=")), None)
            if pic and pic != parts[0]:
                names.append(pic)
            for name in names:
                found.append(SkillRow(name=name, level=int(level), xp_per_hour=rate))
    return tuple(found)


def parse_mining(text: str) -> tuple[SkillRow, ...]:
    """Mining rates, for the three headings that name a rock.

    **An earlier pass refused this page and was wrong.** It reads the ore
    table (experience per *action*, which `Module:Skill calc` already carries)
    and the `! Method ! Levels ! XP/h !` summary (prose method names), and
    concluded from those two that nothing joined. It stopped before the
    section headings - the one shape already proven to work on Hunter - where
    `Granite`, `Gem rocks` and `Calcified rocks` each own a `level -> XP/h`
    table and each names a rock the export names.

    **The tick-manipulated column comes first here**, as it does on the Hunter
    page and unlike the Fishing one, so `_heading_rates`' last-column rule
    already picks the honest figure: granite 87,000 rather than the 134,498
    tick-perfect benchmark, gem rocks 46,000 rather than 93,000, calcified
    23,500 rather than 40,000.

    Still unjoined and named as such: iron ore, sandstone and Motherlode Mine
    have their rates only in that summary table's prose, in ranges qualified by
    level and by gear (`45,000-55,000 below level 60`). Iron's is the one that
    matters most and is a hand entry in `heuristics/overrides.json` instead.
    """
    return tuple(
        replace(row, name=MINING_BY_ROCK[row.name])
        for row in _heading_rates(text)
        if row.name in MINING_BY_ROCK
    )


def parse_hunter(text: str) -> tuple[SkillRow, ...]:
    """What each Hunter technique pays an hour, at the level it opens.

    **Hunter publishes a rate per technique, not per creature**, and its
    tables are `Hunter level -> XP/h` curves rather than one figure per row -
    a different shape from every other table here. The technique is named by
    the *section heading* that owns the table, which is wikitext structure
    rather than prose, so the join is a whole-string comparison after two
    stated normalisations: the heading's `Levels 73-99: ` prefix comes off,
    and a plural `s` does. Four of the six tabled sections join - `Black
    chinchompas`, `Maniacal monkeys`, `Carnivorous chinchompas`, `Herbiboar` -
    and the two that do not are activities with no one creature to name
    (`Drift net fishing`, `Hunters' Rumours`), which is a correct miss.

    **But only six of this page's twenty-two sections hold a table at all**,
    and reading those alone left 10 rated of Hunter's 88 methods. The rest
    state their rate in words - `Players can gain 31,000 experience per hour
    with two traps` - which is why this is the one parser here that reads
    prose, through `_prose_rates`. That is a real loss of robustness and it is
    bounded deliberately: the *heading* still supplies the name and the level,
    so a rephrasing costs a rate rather than mis-joining one, and the number
    must sit immediately before the words `experience per hour`.

    Falconry is the third shape, `_quarry_rows`: one section covering three
    kebbits, each with its own bullet, its own level range and its own rate.

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
    # Prose first, so a name a table also describes keeps the *table*'s
    # figure - `heuristics._table_rates` builds a dict and the last row wins.
    return _prose_rates(text) + _quarry_rows(text) + _heading_rates(text)


def parse_darts(text: str) -> tuple[SkillRow, ...]:
    """Each dart tier's Fletching level and the experience one dart pays.

    **Experience per *dart*, never per hour**, which is the whole reason this
    table can be read at all: dart fletching is one of the few actions in the
    game the tick system does not gate, so no page publishes an hourly figure
    for it and none could - the rate is however fast a person can click. The
    wiki says 2-4 sets a tick is reachable on mobile and declines to turn that
    into a number. `heuristics.DART_CYCLE_SECONDS` is where that decision is
    made and stated, the same separation this module already keeps for
    shortcuts and pickpockets.

    Eight tiers, and their levels are the export's challenge levels exactly -
    10, 22, 37, 52, 67, 81, 90, 95 - so every row joins on the `{{plinkt}}`
    name, which is the export's `Output`.
    """
    table = table_with(text, "|XP/dart")
    found: list[SkillRow] = []
    for cells in rows(table):
        item = _PLINKT.search(" ".join(cells))
        level = number(cells[0]) if cells else None
        # **The first figure after the level, not a resolved column index.**
        # `column_index` counts a header's `colspan` against the width the
        # data uses, and here the two genuinely disagree: `{{plinkt}}` expands
        # to *two* rendered cells (icon, then link), which is what the `Dart`
        # header's `colspan="2"` is counting, but the wikitext splitter sees
        # one. Resolving `XP/dart` that way lands on `XP/buy limit` - 23,400
        # rather than 1.8, and a bronze dart priced at 1.4 billion an hour.
        # The scan is unambiguous because every cell between the level and the
        # experience is an item template carrying no bare figure of its own.
        experience = next(
            (value for cell in cells[1:] if (value := number(cell)) is not None), None
        )
        if level is None or item is None or not experience:
            continue
        found.append(
            SkillRow(name=item.group(1).strip(), level=int(level), experience=experience)
        )
    return tuple(found)


def parse_plunder(text: str) -> tuple[SkillRow, ...]:
    """Pyramid Plunder, as the three methods its own table already is.

    The table is `Thieving levels -> XP/hour` over bands rather than one row
    per thing, which is the shape that made Fishing's techniques unjoinable -
    except that here the bands' opening levels **are** three of the export's
    eight `Access the Nth room of Pyramid Plunder` challenges, so it resolves
    into one rate per challenge with nothing invented.

    `PLUNDER_BY_LEVEL` carries the export's phrasing because the join runs
    through the task's own words - the challenge names no object and no NPC,
    having none - and that is the same small auditable table `COURSE_ALIASES`
    already is. The low end of each band is the level, as everywhere else.
    """
    section = next(
        (body for title, body in _sections(text) if "Pyramid Plunder" in title), ""
    )
    table = table_with(section, "XP/hour")
    found: list[SkillRow] = []
    for cells in rows(table):
        level = number(cells[0]) if cells else None
        rate = number(cells[1]) if len(cells) > 1 else None
        if level is None:
            continue
        name = PLUNDER_BY_LEVEL.get(int(level))
        if name is None or not rate:
            continue
        found.append(SkillRow(name=name, level=int(level), xp_per_hour=rate))
    return tuple(found)


def parse_gotr(text: str) -> tuple[SkillRow, ...]:
    """The Guardians of the Rift curve, as bands rather than as one figure.

    **A minigame's rate depends on the player's level and not on which rune
    comes out of it**, so this table is `Runecraft level -> XP/h` over five
    bands and there is nothing in it to join a challenge name to. The bands
    are the rows, named after the minigame itself; `heuristics._gotr_rates`
    is what applies them to the twelve `with guardian essence` challenges.

    Deliberately reading only the Runecraft column. The same table publishes
    the passive Crafting and Mining the minigame also pays, which are real but
    belong to those climbs and would be a second, separate join.
    """
    section = next(
        (body for title, body in _sections(text) if "Guardians of the Rift" in title), ""
    )
    table = table_with(section, "Runecraft")
    found: list[SkillRow] = []
    for cells in rows(table):
        level = number(cells[0]) if cells else None
        rate = number(cells[1]) if len(cells) > 1 else None
        if level is None or not rate or level > 99:
            continue
        found.append(
            SkillRow(name="Guardians of the Rift", level=int(level), xp_per_hour=rate)
        )
    return tuple(found)


def parse_tithe(text: str) -> tuple[SkillRow, ...]:
    """Tithe Farm's one published rate, from the one sentence stating it.

    **The guide gives a single figure and no table**: "From level 74 onwards,
    players can get around 90,000-100,000 experience per hour." So this is the
    second prose reader here after Hunter's, and the narrowest - it wants a
    level and a rate out of one sentence in one section.

    The bottom of the range and the level it is stated from, both the
    conservative end as everywhere else. The 34 and 54 fruits are not rated:
    the guide says only that experience "may be gained" at those levels and
    quotes no figure, and the minigame's rate climbs steeply with the seed
    tier, so lending them the level-74 number would be inventing one.
    """
    section = next(
        (body for title, body in _sections(text) if TITHE_CATEGORY in title), ""
    )
    stated = re.search(
        r"[Ff]rom level (\d{1,2}) onwards.{0,120}?"
        r"([\d,]{3,})(?:\s*[\u2013\u2014-]\s*[\d,]{3,})?\s*(?:experience|xp)\s+per\s+hour",
        section,
        re.S,
    )
    if stated is None:
        return ()
    return (
        SkillRow(
            name=TITHE_CATEGORY,
            level=int(stated.group(1)),
            xp_per_hour=float(stated.group(2).replace(",", "")),
        ),
    )


def parse_sailing(text: str) -> tuple[SkillRow, ...]:
    """The Barracuda trials, nine rows of trial against rank.

    **The fastest Sailing experience from level 30**, and the reason the skill
    stopped being refused outright: when `estimate.UNRATED_SKILLS` was written
    nothing published a rate for any of Sailing's 27 methods, and this table
    is one of four places that now do.

    Regular in a way that needs no mapping table - `level | trial | (xp/trial,
    xp/hour) x 3` - so the export's phrasing is a format string rather than a
    hand-written list: the trial comes from the row's own wiki link and the
    rank from `BARRACUDA_RANKS`, giving `Complete <trial> at <rank> rank`,
    which is the challenge name exactly.

    Every figure is `{{formatnum:{{#expr:... round 0}}}}`, which is why this
    is the one parser here that reaches for `wiki.parse_amount` rather than
    `wikitable.number` - the cells hold no bare digits at all, and reading the
    first number out of one would take a component of the sum. **The Gwenith
    Glide's Marlin cell holds two** figures, the second with a crystal
    extractor; taking the first is the conservative end, as everywhere else.
    """
    table = table_with(text, "XP / Hour")
    found: list[SkillRow] = []
    for cells in rows(table):
        level = number(cells[0]) if cells else None
        trial = name_in(cells[1]) if len(cells) > 1 else ""
        if level is None or not trial:
            continue
        for index, rank in enumerate(BARRACUDA_RANKS):
            # The pairs run (xp/trial, xp/hour) from the trial's own column.
            at_rate = 3 + index * 2
            cell = cells[at_rate] if at_rate < len(cells) else ""
            stated = _FORMATNUM.search(cell)
            rate = parse_amount(stated.group(0) if stated else cell)
            if not rate:
                continue
            found.append(
                SkillRow(
                    name=f"Complete {trial} at {rank} rank",
                    level=int(level),
                    xp_per_hour=rate,
                )
            )
    return tuple(found)


def parse_cooking(text: str) -> tuple[SkillRow, ...]:
    """What one cooked item pays, from the skill page's `Types of food`.

    **Experience per action, like `parse_darts`, and for a related reason**:
    nothing publishes an hourly figure per food because the pace is the same
    for all of them. It is the range's, not the item's - four ticks a cook -
    so one table plus one constant describes the whole skill, and
    `heuristics.COOK_CYCLE_SECONDS` is where that constant is stated.

    **Only the `Meat / fish` section, and that restriction is the whole of the
    judgement here.** Those foods are one raw item on a range: the published
    experience *is* the action, and the raw fish is priced by the item walk.
    The page's other tables are pies, cakes and stews - several ingredients
    assembled over several steps, where the range action this constant
    describes is the last and cheapest of them. Read whole, the table put
    `curry` at **365,596/hr with its ingredients free** and it topped the
    climb, which is the documented material bias picking a method nobody would
    train on. So they are refused rather than flattered.

    The `{{plinkt}}` names the *cooked* item, which is what the export's
    `Output` holds.
    """
    section = next(
        (body for title, body in _sections(text) if "Meat / fish" in title), ""
    )
    found: list[SkillRow] = []
    for table in tables(section):
        headers = header_columns(table)
        if "level" not in headers or "xp" not in headers:
            continue
        for cells in rows(table):
            item = _PLINKT.search(" ".join(cells))
            level = number(cells[0]) if cells else None
            experience = next(
                (value for cell in cells[1:] if (value := number(cell)) is not None), None
            )
            if item is None or level is None or not experience or level > 99:
                continue
            found.append(
                SkillRow(
                    name=item.group(1).strip(), level=int(level), experience=experience
                )
            )
    return tuple(found)


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
        "mining": parse_mining(pages.get(MINING_PAGE, "")),
        "herblore": parse_herblore(pages.get(HERBLORE_PAGE, "")),
        "darts": parse_darts(pages.get(DARTS_PAGE, "")),
        "plunder": parse_plunder(pages.get(THIEVING_TRAINING_PAGE, "")),
        "gotr": parse_gotr(pages.get(RUNECRAFT_PAGE, "")),
        "tithe": parse_tithe(pages.get(FARMING_PAGE, "")),
        "sailing": parse_sailing(pages.get(SAILING_PAGE, "")),
        "cooking": parse_cooking(pages.get(COOKING_PAGE, "")),
    }
