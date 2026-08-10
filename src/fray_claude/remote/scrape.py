"""The ~18 requests that build the estimator's scraped layer.

**The export carries no durations, rates or XP figures at all**, so every hour
`fray estimate` spends comes from `heuristics/overrides.json`, a default in
`heuristics.py`, or this. It reads the OSRS wiki (quest pages, the money-making
guides, each slayer master's assignment table, the superiors page) and one
published Google Sheet, and hands the lot to `heuristics.build_config`.

**It lives here rather than in `cli.py` because both apps run it**, which is
`batch.save_unlock`'s reasoning applied again: `fray heuristics` and the GUI's
*Refresh Rates* must produce the same file, and two copies of an eighteen-step
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
from typing import Any

from fray_claude.remote.api import (
    DEFAULT_TIMEOUT,
    TASK_LENGTHS_TAB,
    WIKI_API_URL,
    FetchError,
    fetch_text,
    fetch_wiki_page_titles,
    fetch_wiki_pages,
    slayer_sheet_url,
)
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.heuristics import (
    build_config,
    primary_training_tasks,
    quest_names,
)
from fray_claude.slayer import SheetFormatError, parse_mob_data, parse_task_lengths
from fray_claude.model.summary import _mapping
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

    Roughly eighteen requests and a few seconds. `progress` is called with a
    human sentence before each stage, so a caller has something to print or
    draw; it is optional and nothing here depends on it.
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

    config = build_config(
        info,
        quest_pages=quest_pages,
        mmg_pages=mmg,
        assignments=assignments,
        mob_data=mob_data,
        task_lengths=lengths,
        superiors=superiors,
    )
    return ScrapeResult(
        config=config,
        coverage=coverage_of(info, config),
        sources={
            "quest pages": (len(quest_pages), len(quests)),
            "money guides": (len(mmg), len(titles)),
            "assignment pages": (len(assignments), len(masters)),
        },
        counts={
            "assignment rows": sum(len(rows) for rows in assignments.values()),
            "superiors": len(superiors),
            "slayer tasks": len(mob_data),
            "task lengths": len(lengths),
        },
        sheet_error=sheet_error,
    )


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
