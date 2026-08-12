"""The sixteen stages that build the estimator's scraped layer.

**The export carries no durations, rates or XP figures at all**, so every hour
`fray estimate` spends comes from `heuristics/overrides.json`, a default in
`heuristics.py`, or this. It reads the OSRS wiki (quest pages, the money-making
guides, each slayer master's assignment table, the superiors page) and one
published Google Sheet, and hands the lot to `heuristics.build_config`.

**It lives here rather than in `cli.py` because both apps run it**, which is
`batch.save_unlock`'s reasoning applied again: `fray heuristics` and the GUI's
*Refresh Rates* must produce the same file, and two copies of a sixteen-step
sequence would not stay the same for long.

`api.py` still owns every socket and `heuristics.py` every judgement about what
a number means; this is only the order they go in, and the reporting of what
came back. Nothing here decides a rate.

**A missing piece is reported, not fatal.** The slayer sheet is a third-party
document and the wiki can rate-limit; losing either costs part of the estimate
rather than the scrape, and `SectionCoverage` is how a caller says so instead
of writing a config that silently prices something at zero.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from collections.abc import Mapping, Sequence
from typing import Any

from fray_claude.remote.api import (
    DEFAULT_TIMEOUT,
    TASK_LENGTHS_TAB,
    WIKI_API_URL,
    FetchError,
    fetch_bucket,
    fetch_text,
    fetch_wiki_page_titles,
    fetch_wiki_pages,
    fetch_wiki_transclusions,
    slayer_sheet_url,
)
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.costing.heuristics import (
    build_config,
    primary_training_tasks,
    quest_names,
)
from fray_claude.costing.slayer import SheetFormatError, parse_mob_data, parse_task_lengths
from fray_claude.model.summary import _mapping
from fray_claude.remote.recipes import parse_recipes, recipe_query
from fray_claude.remote import combat, farming, prayer, skill_tables, stores
from fray_claude.remote.wiki import (
    ASSIGNMENTS_PAGE,
    MMG_PREFIX,
    SUPERIORS_PAGE,
    Assignment,
    mmg_rates,
    slayer_assignments,
    superior_pairs,
)

#: Told what step is starting, so a command can print it and the GUI can put
#: it in a progress bar. Never told a *rate* - that is `heuristics.py`'s.
Progress = Callable[[str], None]


@dataclass(frozen=True)
class ScrapeResult:
    """The config, and how much of what the export needs it actually found.

    Coverage is reported per section because it is the honest measure of how
    much of an estimate is real data and how much is a default waiting to be
    corrected - a total quoted without it is a number with no error bars.
    """

    config: dict[str, Any]
    #: `section -> (found, total)`, over what the export has to price. The
    #: honest measure of how much of an estimate is real data.
    coverage: dict[str, tuple[int, int]] = field(default_factory=dict)
    #: `source -> (came back, asked for)`. A page can 404 or be renamed, so
    #: "18 requests" and "18 answers" are different numbers and the gap is
    #: worth seeing.
    sources: dict[str, tuple[int, int]] = field(default_factory=dict)
    #: Row and entry counts that have no denominator to be out of.
    counts: dict[str, int] = field(default_factory=dict)
    #: Empty when the slayer sheet answered; the reason when it did not.
    sheet_error: str = ""

    @property
    def summary(self) -> str:
        """One line, for a progress card or a job's result."""
        found = sum(a for a, _ in self.sources.values())
        asked = sum(b for _, b in self.sources.values())
        quests, monsters = self.coverage.get("quests"), self.coverage.get("monsters")
        parts = [f"{found}/{asked} pages"]
        if quests:
            parts.append(f"{quests[0]} quests")
        if monsters:
            parts.append(f"{monsters[0]} monster rates")
        return ", ".join(parts) + (" (no slayer sheet)" if self.sheet_error else "")

    def as_dict(self) -> dict[str, Any]:
        return {
            "coverage": {k: list(v) for k, v in self.coverage.items()},
            "sources": {k: list(v) for k, v in self.sources.items()},
            "counts": dict(self.counts),
            "sheet_error": self.sheet_error,
            "summary": self.summary,
        }


def scrape(
    info: ChunkInfo, *, timeout: float = DEFAULT_TIMEOUT, progress: Progress | None = None
) -> ScrapeResult:
    """Read every source the estimator's scraped layer comes from.

    Sixteen stages and a few seconds. **Stages are not requests**: titles are
    asked for `api.WIKI_TITLES_PER_REQUEST` at a time, so the quest stage alone
    is 5 and the money-making guides at least 11 - counted from the real
    export and the stored scrape, the floor is 31, and the two paginated
    listings and the shop table push the real figure past it. `progress` is
    called with a human sentence before each stage, so a caller has something
    to print or draw; it is optional and nothing here depends on it.
    """
    say = progress or (lambda _message: None)

    quests = sorted(quest_names(info))
    say(f"quest pages (0/{len(quests)})")
    quest_pages = fetch_wiki_pages(quests, timeout=timeout)

    say("money-making guides")
    titles = [t for t in fetch_wiki_page_titles(MMG_PREFIX, timeout=timeout) if t != MMG_PREFIX]
    guides = fetch_wiki_pages(titles, timeout=timeout)
    mmg = {title: rates for title, text in guides.items() if (rates := mmg_rates(text))}

    # Only four masters have the `/Slayer assignments` subpage; the other six
    # keep the table on their own page, so both are asked for and whichever
    # yields rows wins.
    masters = sorted(_mapping(info.data, "slayerMasterTasks"))
    say(f"slayer assignments ({len(masters)} masters)")
    pages = fetch_wiki_pages(
        [f"{m}/{ASSIGNMENTS_PAGE}" for m in masters] + masters, timeout=timeout
    )
    assignments: dict[str, list[Assignment]] = {}
    for master in masters:
        for title in (f"{master}/{ASSIGNMENTS_PAGE}", master):
            rows = slayer_assignments(pages.get(title, ""))
            if rows:
                assignments[master] = rows
                break

    say("superior monsters")
    superior_page = fetch_wiki_pages([SUPERIORS_PAGE], timeout=timeout)
    superiors = superior_pairs(superior_page.get(SUPERIORS_PAGE, ""))

    say("slayer sheet")
    sheet_error = ""
    try:
        mob_data = parse_mob_data(fetch_text(slayer_sheet_url(), what="slayer sheet"))
        lengths = parse_task_lengths(
            fetch_text(slayer_sheet_url(sheet=TASK_LENGTHS_TAB), what="task lengths")
        )
    except (FetchError, SheetFormatError) as exc:
        # A third-party document; losing it costs the Slayer bucket, not the
        # scrape. Say so rather than writing a config that prices it at zero.
        mob_data, lengths, sheet_error = {}, {}, str(exc)

    say("agility and thieving tables")
    table_pages = fetch_wiki_pages(list(skill_tables.PAGES), timeout=timeout)
    tables = skill_tables.parse_pages(table_pages)
    mark_rate = skill_tables.parse_mark_rate(table_pages.get(skill_tables.ROOFTOP_PAGE, ""))

    say("farming crops")
    crops = farming.parse_crops(
        fetch_wiki_pages([farming.CROPS_PAGE], timeout=timeout).get(farming.CROPS_PAGE, "")
    )

    say("bones and altars")
    bone_pages = fetch_wiki_pages(
        fetch_wiki_transclusions(prayer.BONE_TEMPLATE, timeout=timeout), timeout=timeout
    )
    bones = prayer.parse_bones(bone_pages)
    altars = prayer.parse_altars(
        fetch_wiki_pages(list(prayer.ALTAR_PAGES), timeout=timeout)
    )

    say("monster hitpoints and spell xp")
    monster_stats = combat.parse_monster_stats(
        fetch_bucket(combat.monster_query(), timeout=timeout)
    )
    spells = combat.parse_attack_spells(
        fetch_wiki_pages(list(combat.SPELLBOOK_PAGES), timeout=timeout)
    )
    # **Every spell, not only the autocastable ones.** `spells` above answers
    # "what do I barrage with"; this answers "what does a cast eat", and a
    # teleport deals no damage while still costing three runes.
    spell_costs = combat.parse_spell_costs(fetch_bucket(combat.spell_query(), timeout=timeout))

    say("shop prices")
    lines: list[dict[str, Any]] = []
    while True:
        page = fetch_bucket(stores.store_query(offset=len(lines)), timeout=timeout)
        lines.extend(page)
        # The API caps a query at `PAGE_SIZE` whatever `limit` says, so a short
        # page is the end of the table rather than a reason to ask again.
        if len(page) < stores.PAGE_SIZE:
            break
    shop_prices = stores.parse_storelines(lines)
    fees = stores.parse_conversion_fees(
        fetch_wiki_pages([stores.SAWMILL_PAGE], timeout=timeout).get(stores.SAWMILL_PAGE, "")
    )

    config = build_config(
        info,
        quest_pages=quest_pages,
        mmg_pages=mmg,
        assignments=assignments,
        mob_data=mob_data,
        task_lengths=lengths,
        superiors=superiors,
        skill_tables=tables,
        monster_stats=monster_stats,
        spells=spells,
        spell_costs=spell_costs,
        shop_prices=shop_prices,
        conversion_fees=fees,
        currency_rates={"Mark of grace": mark_rate} if mark_rate else {},
        crops=crops,
        bones=bones,
        altars=altars,
    )
    return ScrapeResult(
        config=config,
        coverage=coverage_of(info, config),
        sources={
            "quest pages": (len(quest_pages), len(quests)),
            "money guides": (len(mmg), len(titles)),
            "assignment pages": (len(assignments), len(masters)),
            "skill tables": (len(table_pages), len(skill_tables.PAGES)),
        },
        counts={
            "assignment rows": sum(len(rows) for rows in assignments.values()),
            "superiors": len(superiors),
            "slayer tasks": len(mob_data),
            "task lengths": len(lengths),
            **{f"{kind} rows": len(rows) for kind, rows in sorted(tables.items())},
            "monster hitpoints": len(monster_stats),
            "shop prices": sum(len(items) for items in shop_prices.values()),
            "conversion fees": len(fees),
            "farming crops": len(crops),
            "bones": len(bones),
            "altars": len(altars),
            "attack spells": len(spells),
            "spell costs": len(spell_costs),
        },
        sheet_error=sheet_error,
    )


#: The skills the wiki's `recipe` table actually describes, measured live:
#: Construction 929 rows, Crafting 696, Cooking 536, Smithing 415, Herblore 399,
#: Fletching 255, Magic 223, Runecraft 189, Farming 138, Prayer 32, Firemaking
#: 32, Fishing 18. **Agility and Thieving have none at all** and Mining has two
#: - a rooftop course is not a recipe, which is why gathering and movement
#: skills need a different model rather than a wider query here.
RECIPE_SKILLS: tuple[str, ...] = (
    "Cooking",
    "Construction",
    "Crafting",
    "Farming",
    "Firemaking",
    "Fishing",
    "Fletching",
    "Herblore",
    "Magic",
    "Prayer",
    "Runecraft",
    "Smithing",
    "Woodcutting",
)


def scrape_recipes(
    skills: Sequence[str] = RECIPE_SKILLS, timeout: float = DEFAULT_TIMEOUT
) -> dict[str, Any]:
    """One Bucket query per skill: experience and tick cost per action.

    A dozen requests, and unlike the money-making guides these are *facts about
    the game* rather than somebody's estimate of a rate - which is why they get
    their own blob and their own refresh, and why a method priced from them
    needs no join at all.
    """
    found: dict[str, Any] = {}
    for skill in skills:
        rows = fetch_bucket(recipe_query(skill), timeout)
        found[skill] = [recipe.as_dict() for recipe in parse_recipes(rows, skill)]
    return found


def recipe_coverage(recipes: Mapping[str, Any]) -> dict[str, tuple[int, int]]:
    """Per skill, `(recipes with a tick cost, recipes)`.

    The tick cost is the half that turns experience into a *rate*, so a skill
    with recipes and no ticks is covered on paper and not in practice.
    """
    return {
        skill: (
            sum(1 for recipe in rows if recipe.get("ticks")),
            len(rows),
        )
        for skill, rows in recipes.items()
        if isinstance(rows, list)
    }


def coverage_of(info: ChunkInfo, config: dict[str, Any]) -> dict[str, tuple[int, int]]:
    """What the scrape found, against what the export has to price."""
    totals = {
        "quests": len(quest_names(info)),
        "monsters": len(info.drops),
        "training": len(primary_training_tasks(info)),
    }
    return {
        section: (len(config.get(section) or {}), total) for section, total in totals.items()
    }


#: What `write_blob` records as the source of a scraped config.
SOURCE = WIKI_API_URL
