"""The numbers a gathering action is made of, from the wiki's own tables.

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
| stall restock | `Stall/Thievable`'s `Respawn Time` column | seconds per stall |
| chest restock | the Thieving page's `Thievable chests` table | seconds per chest |
| traps at once | `Multiple traps`, on the Hunter and crab pages | units per level |
| rock respawn | each rock's own `{{Mining info}}` `time` field | seconds per rock |

**These are what finished Thieving and Hunter**, the two skills the model refused
longest, and none of them needed a fit. A stall or a chest hands over one item
and is empty until it restocks, so the restock time *is* its rate - one parser
reads both tables, because it is one mechanic written twice. A trap line runs
several traps at once and the count is a step function of level that no success
curve can express. All of it was sitting on pages already being fetched for
something else.

**Two trap tables, not one, and they disagree.** The Hunter page's opens at
level 1 with five steps; `Crab trapping`'s opens at 21 with four, because crab
traps are a different activity that happens to share the mechanic. They also
spell their heading differently - `Traps` against `Number of traps` - which is
why `parse_trap_counts` tries both and why `Tables.parallel` is keyed by loop.

**The last row is the one this project got wrong for a long time.** It looked
for a rock respawn the way it had found a tree's - a table on the skill page
covering every node - and there is none, which was written down as the figure
being unpublished and a single fitted constant standing in for all 96 rocks. It
is published one rock at a time, in the `time` field of the `{{Mining info}}`
infobox on the rock's own page, and it spans copper's 2.4 seconds to runite's
720. **A table is a convenience, not the data**: where a skill's numbers vary
per node, look at the node's page before concluding nobody wrote them down.
`{{Mining info}}` is the only one of the five skill infoboxes that carries a
`time`, which is why `RESPAWN_INFO_TEMPLATES` is a set beside
`SKILL_INFO_TEMPLATES` rather than a field every template is asked for.

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

**A transcluded table is not in the page that shows it.** The thievable-stall
table renders inside `Stall` and lives at `Stall/Thievable`; fetching the
article returns `{{/Thievable}}` and nothing else. Read the subpage.

Pure parsing. `remote/api.py` fetches, `costing/gathering.py` decides what a row
implies, and the success *formula* lives there too - it is the game's own
arithmetic rather than anything read off a page.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from chunksim.remote.skill_tables import STALLS_PAGE
from chunksim.remote.wiki import parse_amount
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

#: The Hunter skill page, for its `Multiple traps` table.
HUNTER_PAGE = "Hunter"

#: The Thieving skill page, for its `Thievable chests` table - the same shape as
#: the stall one and read by the same parser, since a chest is the same
#: mechanic: one loot, then a restock.
THIEVING_PAGE = "Thieving"

#: `Drift net fishing`, whose rate table is the only place the activity's two
#: skills are costed together - and the only place its experience is stated at
#: all, since neither calculator carries a row for a fish shoal.
DRIFT_NET_PAGE = "Drift net fishing"

#: `Forestry/Strategies`, whose rewards table is the only place the nine events
#: are costed side by side - actions per event against experience per action,
#: with the level written into each formula.
FORESTRY_PAGE = "Forestry/Strategies"

#: The infoboxes a skilled *thing* carries, by the skill they are about.
#: **The only place some of them state their experience** - the calculator has
#: no row for a letvek at all, nor for any Chambers of Xeric fish, and it omits
#: half the rocks in the game.
#:
#: Not only creatures, which is why the name is `skill_info` and not
#: `creature_info`: `{{Mining info}}` sits on a rock.
SKILL_INFO_TEMPLATES: dict[str, str] = {
    "Hunter": "Hunter info",
    "Fishing": "Fishing info",
    "Mining": "Mining info",
    "Woodcutting": "Woodcutting info",
    "Thieving": "Thieving info",
}

#: The templates whose `time` field is a **node respawn**.
#:
#: **This is where every rock's downtime was hiding.** The Woodcutting page
#: tabulates despawn and respawn for thirteen trees and nothing does the same
#: for rocks, from which this project concluded the figure was unpublished and
#: fitted a single constant to stand in for all of them. It is published, one
#: rock at a time: iron respawns in 5.4 seconds and gem rocks in 59.4, an
#: eleven-fold spread no one constant could have covered.
#:
#: **`{{Woodcutting info}}` carries it too and the tabulated thirteen are why
#: it looked as though it did not.** Those thirteen state a despawn *and* a
#: respawn, which is a duty cycle and outranks a restock floor - so every tree
#: this project already priced ignores what is read here, and adding the
#: template moved not one of the sixteen fitted rows. What it reaches is the
#: trees the table omits: the jungle at Tai Bwo Wannai, whose 90 seconds is
#: the whole of its rate. Two spellings of "no wait" fall out on their own -
#: `N/A` parses to nothing and blisterwood's `0 seconds` is filtered by the
#: `> 0`, which is the right answer for both.
#: **And `Thieving info` states one too, for two of its six kinds.** Its own
#: `type` field says what the `time` means, which is the whole reason it can
#: be read at all: a `Stall`'s is the restock and a `Chest`'s the loot
#: respawn - the same mechanic, take the one thing and wait - while a
#: `Pickpocket`'s is the **stun timer**, sixty pages of it, and reading that
#: as a restock would price every NPC as a stall. `parse_info_respawn` gates
#: on the kind for exactly that reason.
#:
#: The curated tables still win, because `respawns` is filled with
#: `setdefault` and they are read first. What this adds is the two Mor Ul Rek
#: counters, which `Stall/Thievable` files under names their own pages do not
#: carry (`Gem stall (Mor Ul Rek)` against `Shop Counter (gems)`) - and
#: reading their own page is better than aliasing the names, because an alias
#: redirects *every* lookup and the calculator's row for the gem counter
#: states 160 experience where both its page and the stall table say 408.
RESPAWN_INFO_TEMPLATES: frozenset[str] = frozenset(
    {"Mining info", "Woodcutting info", "Thieving info"}
)

#: The `Thieving info` kinds whose `time` is a restock rather than a stun.
RESTOCK_KINDS: frozenset[str] = frozenset({"stall", "chest"})

#: The templates whose `type` field names the **loop** a node belongs to.
#:
#: **The numerator was never Thieving's missing input.** Reading its 240
#: infoboxes gained nothing at all, because `SkillProfile.strict_kinds` is on
#: for that skill and a node priced from an infobox alone carried no loop -
#: and a loop is what says whether you are rolling every 2 ticks at a stall or
#: every 15.5 at a chest. The template states it outright, in a field no other
#: skill's carries.
LOOP_INFO_TEMPLATES: frozenset[str] = frozenset({"Thieving info"})

#: Infobox `type` -> the calculator's own name for the same loop.
#:
#: **Three are loops and three are not, and both halves are carried.** `Door`,
#: `Trap` and `Trapdoor` are twenty-two pages between them and none is a
#: training method: you unlock a door once and it stays unlocked. Leaving them
#: *unmapped* used to be how they stayed refused, and that was a mistake of
#: exactly the kind `coverage.REFUSED` exists for - an unmapped kind is
#: indistinguishable from a page nobody scraped, so eleven deliberate
#: refusals printed as `unpriced`, the word that means "somebody should go and
#: close this". Carrying the name is what lets
#: `gathering.SkillProfile.refused_kinds` say the decision out loud, and
#: `strict_kinds` still refuses the rate because no profile gives these a roll
#: interval.
LOOP_KINDS: dict[str, str] = {
    "pickpocket": "Pickpocket",
    "stall": "Stalls",
    "chest": "Chests",
    "door": "Door",
    "trapdoor": "Trapdoor",
    "trap": "Trap",
}


def parse_info_loop(text: str, template: str) -> str | None:
    """The loop an infobox's `type` names, in the calculator's vocabulary.

    `None` where the field is absent, blank, or a value `LOOP_KINDS` does not
    list. Two pages state a `type` this cannot read at all (`Chest
    (Dorgesh-Kaan Rich)` and `Crossbow stall`, whose values run into the next
    template), and both keep no loop and so no rate, rather than a guess at
    which one was meant.

    **A door is named rather than dropped.** It is still not a training
    method - see `LOOP_KINDS` - but "the wiki calls this a door" and "nobody
    scraped this page" have to be different answers, or a refusal reads as a
    gap.
    """
    block = re.search(r"\{\{" + re.escape(template) + r"(.*?)\n\}\}", text, re.S)
    if block is None:
        return None
    fields = {key: value.strip() for key, value in _INFO_FIELD.findall(block.group(1))}
    return LOOP_KINDS.get(fields.get("type", "").strip().lower())

#: The aerial fishing article, whose creature table is the only place the four
#: catches' experience is stated for **both** skills they pay.
AERIAL_PAGE = "Aerial fishing"

#: The herbiboar article, whose experience table is the one thing about that
#: activity worth reading: it is a minigame rather than a loop, and what a
#: catch pays is the only part of it a model can hold.
HERBIBOAR_PAGE = "Herbiboar"

#: The impling article, whose four spawn-tier tables say which impling appears
#: at which kind of spawn point. **Four tables on one page distinguished only
#: by their headings**, which is why `parse_spawn_tiers` reads headings rather
#: than looking for a table by its columns.
IMPLING_PAGE = "Impling"

#: `Crab trapping`, which publishes a trap-count table of its **own**. It is not
#: the Hunter page's - it opens at 21 rather than 1 and has four steps rather
#: than five - which is why `Tables.parallel` is keyed by loop and not just by
#: skill.
CRAB_PAGE = "Crab trapping"

#: The thievable-stall table - **the same page `remote/skill_tables.py` reads,
#: and imported from there rather than spelled twice.** It is a transclusion,
#: `{{/Thievable}}` inside `Stall`, so the subpage is what has to be fetched;
#: getting that wrong once is enough, and a rename upstream must not be able to
#: fix one reader and leave the other on a 404.
#:
#: **Two columns, two answers, and that is the whole relationship between this
#: model and the scrape.** `skill_tables.parse_stalls` reads the `Max XP/Hr`
#: column, which the wiki computes as `3600 / respawn * xp`; this reads the
#: `Respawn Time` column the wiki computed it *from*. So the two agree exactly
#: by construction where a stall is restock-bound, and differ only where the
#: rolling is slower than the restock - which is the half a maximum cannot
#: express. See `costing/gathering.py` on why that agreement is an identity
#: rather than evidence.
STALL_PAGE = STALLS_PAGE

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
    #: Where the numbers came from. **Everything read off a chart is
    #: `confirmed`**; the other two values exist for `costing/gathering.py`,
    #: which has to fill gaps the wiki has not measured and should not be able
    #: to do so silently.
    provenance: str = "confirmed"

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "low": self.low,
            "high": self.high,
            "requirement": self.requirement,
            "provenance": self.provenance,
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


#: The chart's own `label=`, which is the one thing saying what it charts.
#: **A page can carry two and mean different things by them** - the H.A.M.
#: Member's first chart is "Avoiding concussions using Agility" and the
#: Menaphite Thug's is a blackjack "knockout chance" - so a caller that wants a
#: particular chart has to read this rather than take the first.
_CHART_LABEL = re.compile(r"\|\s*label\s*=\s*([^|\n}]*)")


#: Page -> the label of the chart to keep, where the **first** chart on the
#: page is about something else entirely.
#:
#: **Measured before it was written**: 31 of the 643 pages carrying
#: `{{Skilling success chart}}` carry more than one, and on 29 of them the
#: first is the one about the page's own action - a chest's teleport-on-failure
#: chart, a fishing spot's second rod, the Motherlode ore split. Two are not,
#: and both are NPCs you can also *fight*: the H.A.M. Member's first chart is
#: "Avoiding concussions using Agility" and the Menaphite Thug's a blackjack
#: "knockout chance".
#:
#: **Both were wrong in the tables and priced**, which is what makes this a
#: defect rather than a gap: the H.A.M. Member read 65,571/hr at 99 off the
#: concussion curve against a true 49,950, and the Menaphite Thug **330,274**
#: off the knockout curve against 104,422 - a fake method that would have beaten
#: the Rogues' Castle chest on any map holding it. `costing/pickpocket.py`
#: already knew: "a chart is matched by its own label, and three pages prove
#: why". Its own scrape does that and this one did not.
#:
#: A hand table rather than a rule, for `recipe_rates.HAND_ALIASES`' reason: two
#: cases out of 31 is a vocabulary gap, and a rule general enough to catch them
#: would have to guess which of a page's charts is about the skill being asked -
#: which the label says only sometimes, and which "first" says correctly 29
#: times out of 31.
CHART_LABELS: dict[str, str] = {
    "H.A.M. Member": "H.A.M Member pickpocket chance",
    "Menaphite Thug": "Menaphite Thug pickpocket chance",
}


def chart_for(title: str, text: str) -> tuple[SuccessCurve, ...]:
    """The chart on `title` that is about `title`'s own action.

    The first, except on the pages `CHART_LABELS` names - see it for the
    measurement and for the two that need it.
    """
    charts = parse_labelled_success_charts(text)
    if not charts:
        return ()
    wanted = CHART_LABELS.get(title)
    if wanted:
        for label, curves in charts:
            if label.strip() == wanted:
                return curves
    return charts[0][1]


def parse_success_charts(text: str) -> tuple[tuple[SuccessCurve, ...], ...]:
    """Every success chart on a page, each as its series in written order.

    The labels dropped; see `parse_labelled_success_charts`, which this is a
    thin wrapper on and which a caller wanting a *particular* chart needs.
    """
    return tuple(curves for _, curves in parse_labelled_success_charts(text))


def parse_labelled_success_charts(
    text: str,
) -> tuple[tuple[str, tuple[SuccessCurve, ...]], ...]:
    """Every success chart on a page, as `(its own label, its series)`.

    A tuple per chart rather than one flat list, because a page can carry more
    than one and they are about different things - `Motherlode Mine` charts the
    pay-dirt and the sack separately. Series are ordered as the template writes
    them, which for a tool chart is worst tool first.

    A series missing `low` or `high` is dropped: those two *are* the curve, and
    a series without them is a legend entry rather than a rate.
    """
    found: list[tuple[str, tuple[SuccessCurve, ...]]] = []
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
            label = _CHART_LABEL.search(chart.group(1))
            found.append(((label.group(1).strip() if label else ""), tuple(curves)))
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


@dataclass(frozen=True)
class StallRespawn:
    """How long a thievable stall takes to restock, in seconds."""

    name: str
    respawn: float

    def as_dict(self) -> dict[str, Any]:
        return {"respawn": self.respawn}


def parse_stall_respawns(text: str) -> tuple[StallRespawn, ...]:
    """`Stall/Thievable`'s respawn column, as seconds.

    **The one table that makes Thieving's stalls modellable.** A stall yields
    one item and then has to restock, so its respawn *is* its rate - and the
    wiki tabulates it for every thievable stall, which no other page does.

    Two shapes have to survive here. The name is a `{{plinkt|...}}` rather than
    a `[[link]]`, so `_link_name` does not reach it; and a handful of rows
    qualify the number by location - `2.4 seconds (9.6 seconds in Keldagrim)` -
    where the leading figure is the ordinary one and the parenthesis is a
    variant this project has no way to choose between. Taking the leading
    figure is therefore the same conservative reading `tool_curve` takes of a
    tool tier: the common case, stated first.

    **A zero is a restock and not a missing one**, which this refused for a
    long time. Four chests on the Thieving page's own table state `0 seconds`
    - the rusty, tarnished, stone and reinforced ones - and their pages say
    what that means in words: "the chest's loot respawns instantly". Dropped
    as falsy they had no restock at all, so `restock_kinds` refused them and
    four real methods read `unpriced`. Only `None` and a negative are
    unreadable; a nought is the answer.
    """
    # **Two needles, because one stopped being enough when `tables_with`
    # folded case.** `Respawn Time` alone also matches a Woodcutting despawn
    # table headed `Respawn time`, whose rows are trees rather than chests -
    # the capitalisation had been doing work nobody meant it to do. The
    # Thieving page's own header names the thing as well, and a tree table
    # never will.
    table = table_with(text, "Respawn Time", "Thieving")
    if not table:
        return ()
    body = [cells for cells in rows(table) if not cells[0].lstrip().startswith("!")]
    respawn_at = column_index(table, "respawn time", width=max((len(c) for c in body), default=0))
    if respawn_at is None:
        return ()
    found: list[StallRespawn] = []
    for cells in body:
        if len(cells) <= respawn_at:
            continue
        name = _plink_name(cells[0])
        respawn = _duration(cells[respawn_at])
        if not name or respawn is None or respawn < 0:
            continue
        found.append(StallRespawn(name=name, respawn=respawn))
    return tuple(found)


def parse_trap_counts(text: str) -> tuple[tuple[int, float], ...]:
    """The `Multiple traps` table: `(level, traps)`, ascending.

    **A published mechanic the model was silently pricing at one trap.** Box
    trapping, net trapping and bird snaring all run several traps at once and
    the count is a step function of Hunter level - 1, 2, 3, 4, 5 at 1, 20, 40,
    60 and 80 - which is most of why hunting gets faster as you level, and none
    of which a success curve says.

    Two plain columns, and the only table on either page whose header mentions
    traps - but the two pages **spell that header differently**, `Traps` on the
    Hunter page and `Number of traps` on the crab one. `table_with` compares
    header text exactly, so one needle cannot find the other.
    """
    table = table_with(text, "Traps") or table_with(text, "Number of traps")
    if not table:
        return ()
    found: list[tuple[int, float]] = []
    for cells in rows(table):
        if len(cells) < 2 or cells[0].lstrip().startswith("!"):
            continue
        level = _leading(cells[0])
        traps = _leading(cells[1])
        if level is None or traps is None or traps <= 0:
            continue
        found.append((int(level), float(traps)))
    return tuple(sorted(found))


#: A wikitext heading at any depth, with its own words captured.
_HEADING = re.compile(r"^=+\s*(.+?)\s*=+\s*$", re.M)


def parse_spawn_tiers(text: str) -> dict[str, tuple[tuple[str, float], ...]]:
    """Each `Types of spawn` table, keyed by its heading's own words.

    **Heading-scoped rather than column-scoped**, because the four tables are
    identical in shape - `Impling` against `Chance` - and differ only in which
    section they sit under. Asking for "the table with a Chance column" would
    return the low tier four times.

    The chance is written as a fraction of a varying denominator (`20/100`,
    `10/101`, `150/301`), so it is read as one and returned as a share; a tier
    whose shares do not sum to about one is a parse that has gone wrong rather
    than a tier worth spending.
    """
    found: dict[str, tuple[tuple[str, float], ...]] = {}
    marks = list(_HEADING.finditer(text))
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        section = text[mark.end() : end]
        table = table_with(section, "Chance")
        if not table:
            continue
        entries: list[tuple[str, float]] = []
        for cells in rows(table):
            if len(cells) < 2 or cells[0].lstrip().startswith("!"):
                continue
            name = _plink_name(cells[0])
            share = _ratio(cells[-1])
            if name and share is not None and share > 0:
                entries.append((name, share))
        total = sum(share for _, share in entries)
        if entries and 0.95 <= total <= 1.05:
            found[mark.group(1)] = tuple(entries)
    return found


def _ratio(cell: str) -> float | None:
    """`20/100` -> `0.2`, or `None` where the cell is not a fraction."""
    match = re.search(r"(\d+)\s*/\s*(\d+)", cell)
    if match is None:
        return None
    denominator = float(match.group(2))
    return float(match.group(1)) / denominator if denominator else None


#: An `{{#expr:}}` giving experience in a named skill, optionally per a named
#: unit. **`[^}]` rather than `.` in the body**: two of these sit in one cell
#: with bark between them, and a lazy `.` still runs from the first `#expr` to
#: the second one's skill tag.
_EVENT_EXPR = re.compile(
    r"\{\{#expr:\s*([^}]*?)\s*(?:round\s+\d+\s*)?\}\}\s*"
    r"\{\{SCP\|(\w+)\}\}\s*xp(?:\s*per\s+(\w+))?",
    re.I,
)

#: The same, written as a plain number rather than a formula.
_EVENT_FLAT = re.compile(
    r"([\d.]+)\s*\{\{SCP\|(\w+)\}\}\s*xp(?:\s*per\s+(\w+))?", re.I
)

#: `(50^2)` and the like - MediaWiki's power, which is expanded rather than
#: translated. Bounded to a single digit, since the only one in the table is a
#: square and an unbounded exponent is a way to hang a scrape.
_POWER = re.compile(r"\(?([\d.]+)\s*\^\s*(\d)\)?")

#: `30<br/>(5 chops * 6 roots)` - the total, and the two units it breaks into.
_EVENT_ACTIONS = re.compile(r"^(\d+)")
_EVENT_UNITS = re.compile(r"\((\d+)\s*(\w+)\s*\*\s*(\d+)\s*(\w+)\)")

#: The level the table is written at. Every `50` in an experience cell is this
#: - checked against all nine rows - so substituting it is how the table is
#: read at any other level.
FORESTRY_TABLE_LEVEL = 50


def _event_value(expression: str, level: int) -> float | None:
    """One `{{#expr:}}` body at `level`, or `None` if it is not arithmetic.

    Two rewrites before evaluating. The table's assumed level becomes the one
    asked for; and a power is **expanded into repeated multiplication** rather
    than translated, because `remote/wiki.py`'s evaluator deliberately allows
    only the four operations and widening it for one table would widen it for
    the whole scrape. The beehive's per-hive term is
    `5.45*50 - 0.02*(50^2)` - the one power in the table, and read as Python's
    XOR it is not merely wrong but a different shape of curve.
    """
    body = re.sub(r"\b%d\b" % FORESTRY_TABLE_LEVEL, str(level), expression)
    body = _POWER.sub(
        lambda match: "(" + "*".join([f"({match.group(1)})"] * int(match.group(2))) + ")",
        body,
    )
    return parse_amount(body)


def parse_forestry_events(text: str) -> dict[str, dict[str, float]]:
    """`{event: {skill: experience for one occurrence}}` at each level.

    Returns the level-50 figures; call `forestry_by_level` for the curve. Kept
    separate so the parsing is testable without a hundred evaluations.
    """
    return _forestry_at(text, FORESTRY_TABLE_LEVEL)


def _forestry_at(text: str, level: int) -> dict[str, dict[str, float]]:
    table = table_with(text, "Typical actions per event")
    if not table:
        return {}
    found: dict[str, dict[str, float]] = {}
    for cells in rows(table):
        if not cells or cells[0].lstrip().startswith("!") or len(cells) < 4:
            continue
        name = _link_name(cells[0].strip().lstrip("|"))
        name = name.split("|")[-1].strip()
        total = _EVENT_ACTIONS.search(cells[1].strip())
        if not name or total is None:
            continue
        counts = {"": float(total.group(1))}
        units = _EVENT_UNITS.search(cells[1])
        if units is not None:
            per, first, outer, second = units.groups()
            counts[first.rstrip("s").lower()] = float(per) * float(outer)
            counts[second.rstrip("s").lower()] = float(outer)
        paid: dict[str, float] = {}
        # Per-action rewards are multiplied by the count; the end-of-event
        # bonus happens once.
        for cell, multiply in ((cells[2], True), (cells[3], False)):
            for value, skill, unit in _event_fragments(cell, level):
                times = counts.get(unit, counts[""]) if multiply else 1.0
                paid[skill] = paid.get(skill, 0.0) + value * times
        if paid:
            found[name] = paid
    return found


def _event_fragments(cell: str, level: int) -> list[tuple[float, str, str]]:
    """`(experience, skill, unit)` for every xp figure in one cell."""
    found: list[tuple[float, str, str]] = []
    spans: list[tuple[int, int]] = []
    for match in _EVENT_EXPR.finditer(cell):
        spans.append(match.span())
        value = _event_value(match.group(1), level)
        if value is not None:
            found.append((value, match.group(2), (match.group(3) or "").rstrip("s").lower()))
    for match in _EVENT_FLAT.finditer(cell):
        if any(start <= match.start() < end for start, end in spans):
            continue
        value = _float(match.group(1))
        if value is not None:
            found.append((value, match.group(2), (match.group(3) or "").rstrip("s").lower()))
    return found


def forestry_by_level(text: str, levels: Sequence[int]) -> dict[str, dict[int, float]]:
    """`{skill: {level: experience from one of each event}}`.

    Summed over the events rather than kept per event, because a player does
    not choose which one spawns: an hour of forestry is a share of all nine,
    and what a *skill* is paid is the only question downstream asks. The event
    count travels with it as `FORESTRY_EVENTS`.
    """
    found: dict[str, dict[int, float]] = {}
    for level in levels:
        for paid in _forestry_at(text, level).values():
            for skill, value in paid.items():
                found.setdefault(skill, {})[level] = (
                    found.setdefault(skill, {}).get(level, 0.0) + value
                )
    return found


def parse_drift_net(text: str) -> dict[int, tuple[float, float]]:
    """`{level: (Hunter xp/hr, Fishing xp/hr)}` from the rate table.

    **Read as hourly rates rather than as per-shoal experience**, because the
    table already multiplies by its own assumption of 1,150 shoals an hour and
    re-deriving that would only give this project a chance to disagree with the
    page it is reading.

    The two level columns are paired and equal except on the opening row, where
    the requirements differ - 44 Hunter against 47 Fishing - so the Hunter one
    is the key and the pairing is what the row means. Experience stops scaling
    at 70 in both skills, which is why the table ends there rather than at 99.
    """
    table = table_with(text, "XP/shoal")
    if not table:
        return {}
    found: dict[int, tuple[float, float]] = {}
    for cells in rows(table):
        if len(cells) < 6 or cells[0].lstrip().startswith("!"):
            continue
        level = _leading(cells[0])
        hunter = _leading(cells[4].replace(",", ""))
        fishing = _leading(cells[5].replace(",", ""))
        if level is None or hunter is None or fishing is None:
            continue
        if level < 1 or hunter <= 0 or fishing <= 0:
            continue
        found[int(level)] = (hunter, fishing)
    return found


#: What a rod catch pays against a trawling net's, measured on the five shoals
#: that publish both.
_ROD_SHARE = 5.0

_INFO_FIELD = re.compile(r"\|\s*(\w+)\s*=\s*([^\n|]*)")


def parse_skill_info(text: str, template: str) -> tuple[int, float] | None:
    """`(level, experience)` from a creature's own infobox, or `None`.

    **A second source of experience, for the things no calculator lists.**
    `Module:Skill calc/<Skill>` covers the methods a training calculator cares
    about; these templates are on the creature itself, so a letvek - which the
    calculator omits entirely - states its 208.5 here and nowhere else, and the
    seven Chambers of Xeric fish state theirs the same way.

    Read as a fallback and never as an override: where both exist they agree,
    and the calculator is the one with the loop attached.
    """
    block = re.search(r"\{\{" + re.escape(template) + r"(.*?)\n\}\}", text, re.S)
    if block is None:
        return None
    fields = {key: value.strip() for key, value in _INFO_FIELD.findall(block.group(1))}
    level = _leading(fields.get("level", ""))
    paid = _leading(fields.get("xp", ""))
    if paid is None:
        # **A page with two versions states them numbered.** Every trawling
        # shoal carries `skill1exp1` for the net and `skill1exp2` for the rod
        # rather than a plain `xp`, and the first is the one this project
        # prices - the rod is the same fish caught the slow way.
        paid = _leading(fields.get("skill1exp1", ""))
    if paid is None:
        # **A rock paying two different things labels them instead of
        # numbering them.** Barronite rocks read `skill1exp = 16` for shards
        # and `skill2exp = 32` for a deposit, which the drop table splits
        # 76/24. The first is taken and the second is not averaged in: the
        # split lives in a table this parser does not read, and 16 is the
        # conservative end of a figure that is really about 19.8. It is the
        # only page of the 106 shaped this way.
        paid = _leading(fields.get("skill1exp", ""))
    if paid is None:
        # **A versioned rock numbers its `xp` instead.** `Iron rocks` reads
        # `xp1 = 35` against `xp2 = 0`, the second version being The Node,
        # where mining pays nothing; taking whichever came last would have
        # priced iron - the most-mined rock in the game - at zero.
        paid = _leading(fields.get("xp1", ""))
    if paid is None:
        # **The rod figure is exactly a fifth of the net one**, on all five
        # shoals that state both - 265.5/53.1, 220.5/44.1, 195.5/39.1,
        # 155.5/31.1, 128.5/25.7 - so the giant krill shoal, which states only
        # the rod's 22.5, is the one row this recovers.
        rod = _leading(fields.get("skill1exp2", ""))
        paid = None if rod is None else rod * _ROD_SHARE
    if level is None or paid is None or level < 1 or paid <= 0:
        return None
    return int(level), paid


def parse_info_respawn(text: str, template: str) -> float | None:
    """The `time` an infobox states, in seconds, or `None`.

    **The leading figure where several are given.** Limestone reads `5.4
    seconds if fully depleted / 11.4 if two remain / 23.4 if one`, and the
    first is the case a player rotating rocks is actually in - the others
    describe a partly-mined vein nobody waits at.

    **`Thieving info` is asked what its own `time` means before it is
    believed.** A `Stall` states a restock and a `Chest` its loot respawn; a
    `Pickpocket` states the **stun timer**, which is not a wait between
    actions at all but the price of failing one - `costing/pickpocket.py`
    already spends it, from `Stun (status)`. Sixty of the box's ninety-four
    `time` fields are stuns, so reading the field without the gate would price
    every pickpocketable NPC as a stall restocking every five seconds.
    """
    block = re.search(r"\{\{" + re.escape(template) + r"(.*?)\n\}\}", text, re.S)
    if block is None:
        return None
    fields = {key: value.strip() for key, value in _INFO_FIELD.findall(block.group(1))}
    if template in LOOP_INFO_TEMPLATES:
        if fields.get("type", "").strip().lower() not in RESTOCK_KINDS:
            return None
    return _duration(fields.get("time", ""))


def parse_aerial_fish(text: str) -> tuple[tuple[str, int, float, int, float], ...]:
    """`(name, fishing level, fishing xp, hunter level, hunter xp)` per catch.

    **The one table that states a catch's experience in two skills at once**,
    which is what aerial fishing pays and what no skill calculator records: the
    Fishing calculator has no row for these at all and the Hunter one has none
    either.

    The header is two rows deep - a `colspan=2` per skill over a `Level`/`Exp`
    pair - so the second one arrives through `rows` as data and is skipped like
    any other `!` line. Cooking's pair is read and dropped; it is real, but
    nothing here prices a catch for a third skill.
    """
    table = table_with(text, "Creature")
    if not table:
        return ()
    found: list[tuple[str, int, float, int, float]] = []
    for cells in rows(table):
        if len(cells) < 5 or cells[0].lstrip().startswith("!"):
            continue
        name = _plink_name(cells[0])
        numbers = [_leading(cell) for cell in cells[1:5]]
        if not name or any(value is None for value in numbers):
            continue
        fishing_level, fishing_xp, hunter_level, hunter_xp = numbers
        assert fishing_level is not None and fishing_xp is not None
        assert hunter_level is not None and hunter_xp is not None
        found.append(
            (name, int(fishing_level), fishing_xp, int(hunter_level), hunter_xp)
        )
    return tuple(found)


def parse_level_experience(text: str) -> dict[int, float]:
    """A `Hunter Level | XP` table, as `{level: experience}`.

    **Two pairs of columns per row**, which is how the wiki fits levels 74 to 99
    into thirteen lines - so a row is read as `(level, xp)` twice rather than
    once, and a parser that took the first two cells would lose half the table.
    """
    table = table_with(text, "Hunter Level", "XP")
    if not table:
        return {}
    found: dict[int, float] = {}
    for cells in rows(table):
        if cells and cells[0].lstrip().startswith("!"):
            continue
        for index in range(0, len(cells) - 1, 2):
            level = _leading(cells[index])
            paid = _leading(cells[index + 1])
            if level is None or paid is None or level < 1 or paid <= 0:
                continue
            found[int(level)] = paid
    return found


def _plink_name(cell: str) -> str:
    """The page title out of `{{plinkt|Fur stall|pic=...}}`.

    `plinkt`'s first argument is the page; a `txt=` override is what the row
    *displays* and is deliberately not read, since the join downstream is on
    the page name.
    """
    match = _PLINK.search(cell)
    if match:
        return match.group(1).strip()
    return _link_name(cell)


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
    #: Stall -> seconds to restock. A separate table from `cycles` because it
    #: is a different mechanic: a tree yields for a window, a stall yields
    #: exactly one item and then is empty.
    respawns: dict[str, float] = field(default_factory=dict)
    #: Hunter level -> experience for one herbiboar.
    herbiboar_xp: dict[int, float] = field(default_factory=dict)
    #: The aerial catches: `(name, fishing level, fishing xp, hunter level,
    #: hunter xp)`.
    aerial_fish: tuple[tuple[str, int, float, int, float], ...] = ()
    #: Hunter level -> `(Hunter xp/hr, Fishing xp/hr)` for drift net fishing.
    drift_net: dict[int, tuple[float, float]] = field(default_factory=dict)
    #: Skill -> level -> experience from one of each Forestry event, and how
    #: many events that sum is over.
    forestry: dict[str, dict[int, float]] = field(default_factory=dict)
    forestry_events: int = 0
    #: Skill -> creature page -> `(level, experience)` off its own infobox.
    skill_info: dict[str, dict[str, tuple[int, float]]] = field(default_factory=dict)
    #: Skill -> node -> the loop its infobox names. See `LOOP_INFO_TEMPLATES`.
    skill_loops: dict[str, dict[str, str]] = field(default_factory=dict)
    #: Spawn-tier heading -> `(impling, share)`, the chance table each kind of
    #: Puro-Puro spawn point rolls.
    spawn_tiers: dict[str, tuple[tuple[str, float], ...]] = field(default_factory=dict)
    #: Skill -> loop -> `(level, units)` steps for a loop worked several at a
    #: time, `""` being the skill's default. A table rather than a constant
    #: because the count is what changes as the skill levels, and keyed by loop
    #: because Hunter publishes two that disagree: the general one opens at
    #: level 1 with five steps and crab trapping's opens at 21 with four.
    parallel: dict[str, dict[str, tuple[tuple[int, float], ...]]] = field(
        default_factory=dict
    )
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
            "respawns": dict(sorted(self.respawns.items())),
            "aerial_fish": [list(entry) for entry in self.aerial_fish],
            "drift_net": {
                str(level): [hunter, fishing]
                for level, (hunter, fishing) in sorted(self.drift_net.items())
            },
            "forestry": {
                skill: {str(level): paid for level, paid in sorted(by_level.items())}
                for skill, by_level in sorted(self.forestry.items())
            },
            "forestry_events": self.forestry_events,
            "skill_info": {
                skill: {
                    name: [level, paid]
                    for name, (level, paid) in sorted(entries.items())
                }
                for skill, entries in sorted(self.skill_info.items())
            },
            "skill_loops": {
                skill: dict(sorted(entries.items()))
                for skill, entries in sorted(self.skill_loops.items())
            },
            "herbiboar_xp": {
                str(level): paid for level, paid in sorted(self.herbiboar_xp.items())
            },
            "spawn_tiers": {
                tier: [[name, share] for name, share in entries]
                for tier, entries in sorted(self.spawn_tiers.items())
            },
            "parallel": {
                skill: {
                    loop: [list(step) for step in steps]
                    for loop, steps in sorted(loops.items())
                }
                for skill, loops in sorted(self.parallel.items())
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
        chart = chart_for(title, text)
        if chart:
            curves[title] = chart

    say("reading tool speeds, node cycles, restock times and trap counts")
    mechanics = fetch_pages(
        [
            PICKAXE_PAGE,
            WOODCUTTING_PAGE,
            STALL_PAGE,
            THIEVING_PAGE,
            HUNTER_PAGE,
            CRAB_PAGE,
            IMPLING_PAGE,
            HERBIBOAR_PAGE,
            AERIAL_PAGE,
            FORESTRY_PAGE,
            DRIFT_NET_PAGE,
        ]
    )
    tool_ticks = {
        tool.name: tool.ticks
        for tool in parse_tool_speeds(mechanics.get(PICKAXE_PAGE, ""))
    }
    cycles = {
        cycle.name: cycle
        for cycle in parse_node_cycles(mechanics.get(WOODCUTTING_PAGE, ""))
    }
    # **Stalls and chests are one table twice.** Both publish a `Respawn Time`
    # column against a `{{plinkt}}` name, because both are the same mechanic -
    # take the one thing, wait for it to come back - so one parser reads both
    # and they share one index.
    respawns = {
        entry.name: entry.respawn
        for page in (STALL_PAGE, THIEVING_PAGE)
        for entry in parse_stall_respawns(mechanics.get(page, ""))
    }
    parallel: dict[str, dict[str, tuple[tuple[int, float], ...]]] = {}
    traps = parse_trap_counts(mechanics.get(HUNTER_PAGE, ""))
    if traps:
        parallel.setdefault("Hunter", {})[""] = traps
    spawn_tiers = parse_spawn_tiers(mechanics.get(IMPLING_PAGE, ""))
    herbiboar_xp = parse_level_experience(mechanics.get(HERBIBOAR_PAGE, ""))
    aerial_fish = parse_aerial_fish(mechanics.get(AERIAL_PAGE, ""))

    drift_net = parse_drift_net(mechanics.get(DRIFT_NET_PAGE, ""))
    forestry = forestry_by_level(mechanics.get(FORESTRY_PAGE, ""), range(1, 100))
    forestry_events = len(parse_forestry_events(mechanics.get(FORESTRY_PAGE, "")))

    say(f"reading skill infoboxes for {len(SKILL_INFO_TEMPLATES)} skills")
    skill_info: dict[str, dict[str, tuple[int, float]]] = {}
    skill_loops: dict[str, dict[str, str]] = {}
    creatures: list[str] = []
    for skill, template in sorted(SKILL_INFO_TEMPLATES.items()):
        titles_for = sorted(set(list_transclusions(f"Template:{template}")))
        creatures.extend(titles_for)
        for title, body in fetch_pages(titles_for).items():
            found = parse_skill_info(body, template)
            if found is not None:
                skill_info.setdefault(skill, {})[title] = found
            if template in RESPAWN_INFO_TEMPLATES:
                waited = parse_info_respawn(body, template)
                if waited is not None and waited > 0:
                    respawns.setdefault(title, waited)
            if template in LOOP_INFO_TEMPLATES:
                loop = parse_info_loop(body, template)
                if loop:
                    skill_loops.setdefault(skill, {})[title] = loop
    crabs = parse_trap_counts(mechanics.get(CRAB_PAGE, ""))
    if crabs:
        parallel.setdefault("Hunter", {})["Crab trapping"] = crabs

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
        respawns=respawns,
        spawn_tiers=spawn_tiers,
        herbiboar_xp=herbiboar_xp,
        aerial_fish=aerial_fish,
        drift_net=drift_net,
        forestry=forestry,
        forestry_events=forestry_events,
        skill_info=skill_info,
        skill_loops=skill_loops,
        parallel=parallel,
        actions=actions,
        sources={
            "success charts": (len(curves), len(titles)),
            "skill calculators": (len(actions), len(SKILL_CALC_PAGES)),
            "skill infoboxes": (
                sum(len(entries) for entries in skill_info.values()),
                len(creatures),
            ),
        },
        counts={
            "tool speeds": len(tool_ticks),
            "node cycles": len(cycles),
            "node respawns": len(respawns),
            "infobox loops": sum(len(found) for found in skill_loops.values()),
            "spawn tiers": len(spawn_tiers),
            "herbiboar levels": len(herbiboar_xp),
            "aerial catches": len(aerial_fish),
            "forestry events": forestry_events,
            "drift net levels": len(drift_net),
            "parallel steps": sum(
                len(steps) for loops in parallel.values() for steps in loops.values()
            ),
        },
    )


__all__ = [
    "CHART_LABELS",
    "chart_for",
    "AERIAL_PAGE",
    "FORESTRY_PAGE",
    "DRIFT_NET_PAGE",
    "GatheringTables",
    "HERBIBOAR_PAGE",
    "HUNTER_PAGE",
    "IMPLING_PAGE",
    "NodeCycle",
    "PICKAXE_PAGE",
    "CRAB_PAGE",
    "STALL_PAGE",
    "THIEVING_PAGE",
    "SKILL_INFO_TEMPLATES",
    "SUCCESS_TEMPLATE",
    "StallRespawn",
    "SuccessCurve",
    "ToolSpeed",
    "WOODCUTTING_PAGE",
    "build_tables",
    "parse_node_cycles",
    "parse_aerial_fish",
    "forestry_by_level",
    "parse_drift_net",
    "parse_forestry_events",
    "parse_info_respawn",
    "parse_skill_info",
    "parse_level_experience",
    "parse_spawn_tiers",
    "parse_stall_respawns",
    "parse_trap_counts",
    "parse_success_charts",
    "parse_labelled_success_charts",
    "parse_tool_speeds",
]
