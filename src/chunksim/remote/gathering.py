"""The three numbers a gathering action is made of, from the wiki's own tables.

**Gathering was the hole every other rate source left.** `{{Recipe}}` describes
nothing here - a fishing spot is not a recipe, so `remote/recipes.py` returns
zero rows for Fishing, Woodcutting and Mining - and the money-making guides
reach four of Woodcutting's fifty-three methods. What stood in was
`remote/skill_tables.py`, which reads *published hourly figures* off training
guides: a real number, but somebody else's, quoted for their account at their
level with their axe, and unjoinable for any method nobody wrote a guide about.

This module reads the inputs a rate is *computed* from instead, and the wiki
publishes all three in machine-readable form:

| what | where | shape |
|---|---|---|
| success chance | `{{Skilling success chart}}` | `low`/`high`/`req` per series |
| roll interval | the tool page's `Ticks between rolls` column | ticks per pickaxe |
| node cycle | the skill page's despawn/respawn table | seconds per node |

**The chart template is the find, and it is everywhere.** Over 500 article-space
pages transclude it - every tree, rock, fishing spot, kebbit, stall and
pickpocket target - and the pages are named exactly what the chunk export names
in `Objects`/`NPCs`: `Iron rocks`, `Willow tree`, `Fishing spot (cage,
harpoon)`, `Warrior (Thieving)`, `Black chinchompa (Hunter)`. So the join is
structural and there is no fuzzy tier here, the same standard
`remote/skill_tables.py` holds its four tables to.

**The two tool axes are different and the data says which is which.** A
`Willow tree` chart carries nine series, one per axe tier, because an axe
changes the *chance*; an `Iron rocks` chart carries one, because a pickaxe
changes the *interval* instead and the wiki says so in as many words ("Your
level affects the chance of getting ore each time the game rolls; your pickaxe
affects how often that happens" - Mod Ash, 28 October 2019). Reading the shape
off the chart rather than branching per skill is what lets one model serve both.

Pure parsing. `remote/api.py` fetches, `costing/gathering.py` decides what a row
implies, and the success *formula* lives there too - it is the game's own
arithmetic rather than anything read off a page.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from chunksim.remote.skillcalc import SKILL_CALC_PAGES, CalcRow, parse_rows
from chunksim.remote.wikitable import column_index, rows, table_with

#: The page whose `Ticks between rolls` column is the Mining roll interval.
#: **Only pickaxes have one published**, which is the whole reason Mining is the
#: skill whose tool changes the interval - see the module docstring.
PICKAXE_PAGE = "Pickaxe"

#: The skill pages carrying a despawn/respawn table for their nodes.
WOODCUTTING_PAGE = "Woodcutting"

#: The template every success curve is written as.
SUCCESS_TEMPLATE = "Skilling success chart"

#: One `{{Skilling success chart|...}}` invocation. Matched non-greedily and
#: without nesting support on purpose: the template takes flat scalar
#: parameters, so a `}}` inside one would mean the page has stopped being the
#: shape this reads and returning nothing is the honest answer.
_CHART = re.compile(r"\{\{" + SUCCESS_TEMPLATE + r"(.*?)\}\}", re.S)

#: A numbered parameter of that template: `low3`, `high3`, `label3`, `req3`.
_SERIES = re.compile(r"\|\s*(label|low|high|req)(\d+)\s*=\s*([^|\n}]*)")

#: `1 minute, 54 seconds` / `8.4 seconds` / `2 minutes`. The wiki writes these
#: as prose in the despawn table rather than as a number with a unit column.
_DURATION = re.compile(
    r"(?:(?P<minutes>[\d.]+)\s*minutes?)?[,\s]*(?:(?P<seconds>[\d.]+)\s*seconds?)?"
)

#: The leading number of a cell, ignoring any footnote glued to it. The dragon
#: pickaxe's interval is written `2.83{{efn|3 ticks by default, 1/6 chance to
#: be 2 ticks.}}`, and the figure before the note is the one to spend.
_LEADING_NUMBER = re.compile(r"-?[\d,]*\.?\d+")

#: `{{plinkt|Bronze pickaxe}}` - the item cell of a tool table.
_PLINK = re.compile(r"\{\{plink[a-z]*\|([^|}]+)")


@dataclass(frozen=True)
class SuccessCurve:
    """One `low`/`high` pair: the chance of an action succeeding, by level.

    `label` is the series' own name. On a single-series chart it is the
    resource (`Iron rocks`); on a multi-series one it is the **tool tier**
    (`Bronze`, `Rune`, `Crystal`), which is what makes an axe's effect on
    woodcutting readable rather than assumed.

    `requirement` is the level the series is drawn from and is *not* the
    action's level requirement - the two agree on most rows and the chart is
    not the authority on either, so `costing/gathering.py` takes the level from
    `Module:Skill calc` and uses this only to order the tiers.
    """

    label: str
    low: float
    high: float
    requirement: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "low": self.low,
            "high": self.high,
            "requirement": self.requirement,
        }


@dataclass(frozen=True)
class ToolSpeed:
    """One tool, and how often it rolls.

    `ticks` is fractional where the wiki says so: a dragon pickaxe is "3 ticks
    by default, 1/6 chance to be 2 ticks" and the page tabulates the 2.83 that
    follows from it. Taking the published average rather than recomputing it
    keeps the arithmetic the wiki's rather than this project's.
    """

    name: str
    ticks: float
    level: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ticks": self.ticks, "level": self.level}


@dataclass(frozen=True)
class NodeCycle:
    """How long a node lasts and how long it takes to come back.

    **This is the inactivity term**, and without it a gathering model prices a
    world of infinite resources: a normal tree yields one log and vanishes, so
    a rate computed from the roll interval alone reads 37,500 xp/hr against a
    published 12,500. `despawn` is the wiki's own "despawn time" - how long the
    node keeps yielding once you start - and `respawn` how long until it is
    workable again.
    """

    name: str
    despawn: float
    respawn: float

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "despawn": self.despawn, "respawn": self.respawn}


def parse_success_charts(text: str) -> tuple[tuple[SuccessCurve, ...], ...]:
    """Every success chart on a page, each as its series in written order.

    A tuple per chart rather than one flat list, because a page can carry more
    than one and they are about different things - `Motherlode Mine` charts the
    pay-dirt and the sack separately. Series are ordered as the template writes
    them, which for a tool chart is worst tool first.

    A series missing `low` or `high` is dropped: those two *are* the curve, and
    a series without them is a legend entry rather than a rate.
    """
    found: list[tuple[SuccessCurve, ...]] = []
    for chart in _CHART.finditer(text):
        series: dict[int, dict[str, str]] = {}
        for key, index, value in _SERIES.findall(chart.group(1)):
            series.setdefault(int(index), {})[key] = value.strip()
        curves: list[SuccessCurve] = []
        for index in sorted(series):
            entry = series[index]
            low, high = _float(entry.get("low")), _float(entry.get("high"))
            if low is None or high is None:
                continue
            curves.append(
                SuccessCurve(
                    label=entry.get("label", "").strip(),
                    low=low,
                    high=high,
                    requirement=int(_float(entry.get("req")) or 1),
                )
            )
        if curves:
            found.append(tuple(curves))
    return tuple(found)


def parse_tool_speeds(text: str) -> tuple[ToolSpeed, ...]:
    """Every tool on a page that publishes a `Ticks between rolls` column.

    **Both tables on the page, not just the first.** The `Pickaxe` page splits
    "Standard pickaxes" from "Other pickaxes", and the second holds the gilded,
    3rd age and infernal variants the export's `toolLevels` also names - so
    reading one table loses four of the twelve tools the export can offer.

    The name comes from the cell's `{{plinkt|...}}`, which is the item's own
    page title and therefore the string the export uses; a row whose name or
    interval will not parse is skipped rather than defaulted.
    """
    found: list[ToolSpeed] = []
    seen: set[str] = set()
    for table in _tool_tables(text):
        # **Widths come from the data, not the header.** These tables open
        # `!colspan=2|Item` and then render the icon and the name from one
        # `{{plinkt}}`, so the span over-counts by one and every column after
        # it reads one to the left - `header_columns` resolves that only when
        # told how many cells a row actually has.
        body = [cells for cells in rows(table) if not cells[0].lstrip().startswith("!")]
        width = len(body[0]) if body else None
        ticks_at = column_index(table, "ticks between rolls", width=width)
        level_at = column_index(table, "mining", width=width)
        if ticks_at is None:
            continue
        for cells in body:
            if len(cells) <= ticks_at:
                continue
            name = _PLINK.search(cells[0])
            ticks = _leading(cells[ticks_at])
            if name is None or ticks is None or ticks <= 0:
                continue
            title = name.group(1).strip()
            if title in seen:
                continue
            seen.add(title)
            level = (
                _leading(cells[level_at])
                if level_at is not None and len(cells) > level_at
                else None
            )
            found.append(
                ToolSpeed(name=title, ticks=ticks, level=int(level) if level else 1)
            )
    return tuple(found)


def _tool_tables(text: str) -> list[str]:
    """Every wikitable on the page carrying a roll-interval column."""
    from chunksim.remote.wikitable import tables

    return [table for table in tables(text) if "Ticks between rolls" in table]


def parse_node_cycles(text: str) -> tuple[NodeCycle, ...]:
    """The despawn/respawn table, as seconds.

    Both columns are prose (`1 minute, 54 seconds`), so both go through
    `_duration`. A row missing either is dropped - half a cycle cannot be spent
    and defaulting the other half would invent the very number this exists to
    supply.
    """
    table = table_with(text, "Despawn time", "Respawn time")
    if not table:
        return ()
    despawn_at = column_index(table, "despawn time")
    respawn_at = column_index(table, "respawn time")
    if despawn_at is None or respawn_at is None:
        return ()
    found: list[NodeCycle] = []
    for cells in rows(table):
        # **The header can arrive as a row.** This table opens with `|-` and
        # puts its `!` lines after it, which is the shape `table_with` exists
        # for - and it means `rows` yields the header cells as row one.
        if cells[0].lstrip().startswith("!"):
            continue
        if len(cells) <= max(despawn_at, respawn_at):
            continue
        name = _link_name(cells[0])
        despawn = _duration(cells[despawn_at])
        respawn = _duration(cells[respawn_at])
        if not name or despawn is None or respawn is None:
            continue
        found.append(NodeCycle(name=name, despawn=despawn, respawn=respawn))
    return tuple(found)


def _link_name(cell: str) -> str:
    """The page title out of `[[Oak tree]]` or `[[Rocks (x)|Rocks]]`."""
    match = re.search(r"\[\[([^\]|]+)", cell)
    return (match.group(1) if match else cell).strip()


def _duration(cell: str) -> float | None:
    """`1 minute, 54 seconds` -> `114.0`, or `None` if it says no time at all."""
    match = _DURATION.search(cell.replace("&nbsp;", " "))
    if match is None:
        return None
    minutes, seconds = match.group("minutes"), match.group("seconds")
    if minutes is None and seconds is None:
        return None
    return float(minutes or 0.0) * 60.0 + float(seconds or 0.0)


def _leading(cell: str) -> float | None:
    """The first number in a cell, ignoring a footnote glued to it."""
    match = _LEADING_NUMBER.search(cell.replace("&nbsp;", " "))
    if match is None:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value.strip())
    except ValueError:
        return None



@dataclass(frozen=True)
class GatheringTables:
    """Everything one `chunksim gather-tables` run read, ready to write out.

    **The whole point is that this is written once and then shipped**, so it
    carries counts as well as rows: a distributed build reads the JSON and can
    never re-fetch, which makes "how much did the scrape actually reach" a
    question only the file can answer.
    """

    #: Page title -> its success curves. A page with several charts keeps only
    #: the first, which is the one about the page's own subject; the others
    #: describe a variant or a sub-activity and have no name to join on.
    curves: dict[str, tuple[SuccessCurve, ...]] = field(default_factory=dict)
    #: Tool item -> ticks between rolls, for the one family that publishes it.
    tool_ticks: dict[str, float] = field(default_factory=dict)
    #: Node -> how long it yields and how long it takes to come back.
    cycles: dict[str, NodeCycle] = field(default_factory=dict)
    #: Skill -> its calculator rows: level and experience per action.
    actions: dict[str, tuple[CalcRow, ...]] = field(default_factory=dict)
    #: `source -> (came back, asked for)`, so a 404 is visible rather than a
    #: quietly shorter table. The same accounting `remote/scrape.py` keeps, and
    #: **only for the two stages that have a denominator**: a page either
    #: answers or it does not, where "how many pickaxes were on the pickaxe
    #: page" is a row count with nothing to be out of.
    sources: dict[str, tuple[int, int]] = field(default_factory=dict)
    #: Row counts that have no denominator - `remote/scrape.py`'s `counts`.
    counts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "curves": {
                page: [curve.as_dict() for curve in curves]
                for page, curves in sorted(self.curves.items())
            },
            "tool_ticks": dict(sorted(self.tool_ticks.items())),
            "cycles": {
                name: {"despawn": cycle.despawn, "respawn": cycle.respawn}
                for name, cycle in sorted(self.cycles.items())
            },
            "actions": {
                skill: [row.as_dict() for row in rows]
                for skill, rows in sorted(self.actions.items())
            },
            "sources": {name: list(counts) for name, counts in sorted(self.sources.items())},
            "counts": dict(sorted(self.counts.items())),
        }


#: Told what stage is starting, so the command can print it. Never told a rate.
Progress = Callable[[str], None]


def build_tables(
    list_transclusions: Callable[[str], Sequence[str]],
    fetch_pages: Callable[[Sequence[str]], dict[str, str]],
    *,
    progress: Progress | None = None,
) -> GatheringTables:
    """Read every page the gathering model is computed from.

    **Fetching is injected rather than imported**, the same shape
    `costing/recipe_rates.py` takes its pricing callable: it keeps this module
    pure, keeps every socket `remote/api.py`'s, and makes the whole sequence
    testable against a dict of fixtures rather than the live wiki.

    Four stages and about fifteen requests, since titles are batched. **Every
    chart-bearing page is read, not just the ones this map needs** - the file
    is checked in and shipped, so it has to answer for a map nobody has fetched
    yet. Which of them a given export actually names is `costing/gathering.py`'s
    question and is asked long after this has run.
    """
    say = progress or (lambda _step: None)

    say(f"listing pages using {SUCCESS_TEMPLATE}")
    titles = sorted(set(list_transclusions(f"Template:{SUCCESS_TEMPLATE}")))

    say(f"reading {len(titles)} success charts")
    pages = fetch_pages(titles)
    curves: dict[str, tuple[SuccessCurve, ...]] = {}
    for title in titles:
        text = pages.get(title)
        if not text:
            continue
        charts = parse_success_charts(text)
        if charts:
            curves[title] = charts[0]

    say("reading tool speeds and node cycles")
    mechanics = fetch_pages([PICKAXE_PAGE, WOODCUTTING_PAGE])
    tool_ticks = {
        tool.name: tool.ticks
        for tool in parse_tool_speeds(mechanics.get(PICKAXE_PAGE, ""))
    }
    cycles = {
        cycle.name: cycle
        for cycle in parse_node_cycles(mechanics.get(WOODCUTTING_PAGE, ""))
    }

    say(f"reading {len(SKILL_CALC_PAGES)} skill calculators")
    calc_pages = fetch_pages(sorted(SKILL_CALC_PAGES.values()))
    actions: dict[str, tuple[CalcRow, ...]] = {}
    for skill, page in sorted(SKILL_CALC_PAGES.items()):
        parsed = parse_rows(calc_pages.get(page, ""))
        if parsed:
            actions[skill] = parsed

    return GatheringTables(
        curves=curves,
        tool_ticks=tool_ticks,
        cycles=cycles,
        actions=actions,
        sources={
            "success charts": (len(curves), len(titles)),
            "skill calculators": (len(actions), len(SKILL_CALC_PAGES)),
        },
        counts={"tool speeds": len(tool_ticks), "node cycles": len(cycles)},
    )


__all__ = [
    "GatheringTables",
    "NodeCycle",
    "PICKAXE_PAGE",
    "SUCCESS_TEMPLATE",
    "SuccessCurve",
    "ToolSpeed",
    "WOODCUTTING_PAGE",
    "build_tables",
    "parse_node_cycles",
    "parse_success_charts",
    "parse_tool_speeds",
]
