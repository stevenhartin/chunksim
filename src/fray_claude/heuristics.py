"""The hand-correctable numbers behind `fray estimate`, and how they merge.

Everything here is a **guess**, and the module is built around that admission.
The export has no durations, no rates and no XP figures of any kind, so every
number the estimator spends comes from the wiki, a community spreadsheet, or a
default sitting in this file - and any of them can be wrong for a given
player. `experience.py` is deliberately *not* part of this: the XP curve is
the game's own arithmetic and must not be overridable, or no estimate could
ever be checked.

**Two layers, and overrides always win.**

    defaults (this module)  <  scraped (cache/wiki_rates.json)  <  overrides
                                                                (heuristics/)

The scrape is a cache blob: refetchable, gitignored, regenerated wholesale by
`fray heuristics`. The overrides file is checked in, sparse, and hand-written,
so a correction is diffable, survives a re-scrape, and travels with the repo.
`disagreements()` reports where a fresh scrape has moved away from a value
someone pinned by hand - the one thing a silent merge would hide.

**On coverage, honestly.** The money-making guides are about money, and most
ways of training a skill do not make any, so they have no guide at all.
Measured against the real export: 960 of 1,111 guides carry a `kph`, and they
join to **243 of the 2,710** `Primary: true` training methods and **105 of the
872** monsters with drops. Quests are the exception and come out complete,
209 of 209. Everything unjoined gets a default, which is why
`DEFAULT_XP_PER_HOUR` is deliberately *low* - an un-joined method should look
slow and obvious rather than fast and invisible, so the entries worth an
afternoon of hand-correction are the ones dominating the total. The generated
config lists every quest, monster and training method regardless, so there is
always a line to correct.

**Joins record how they were made**, and there are only two ways: `exact` (the
names agree) and `contained` (every identity-bearing word of the task name
appears in the guide's activity - `Agility Pyramid` inside `Climbing the
Agility Pyramid`). Writing the provenance next to the number is what makes a
wrong join findable in a 3,700-entry file instead of buried inside one total.

**There is no fuzzy tier, and that was a measurement rather than a taste.**
An edit-distance fallback (`search.rank`) lifted monster coverage from 105 to
179 - and 116 of those 179 were fuzzy matches including `Albatross` to
`Barrows` and `Air elemental` to `Chaos Elemental`. Those are worse than no
answer: a default announces itself as a default, while a wrong join reads as
evidence and will be believed. The lower number is the honest one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from fray_claude.chunkinfo import ChunkInfo
from fray_claude.search import normalise
from fray_claude.summary import _mapping
from fray_claude.wiki import Assignment, MmgRates, quest_difficulty, quest_length

#: Quest length word -> hours, as specified in `plan.md`.
LENGTH_HOURS: dict[str, float] = {
    "very short": 0.17,
    "short": 1.0,
    "medium": 2.0,
    "long": 4.0,
    "very long": 6.0,
}

#: What a quest with no length on the wiki costs. `Medium`, the middle of the
#: scale - a missing length is unknown, not short.
DEFAULT_QUEST_HOURS = LENGTH_HOURS["medium"]

#: Rarity words the export uses instead of a fraction, as probabilities.
#: `Always` is a fact; the rest are guesses of the order of magnitude implied
#: by the word, which is why they live here and not in `rates.py`. `Varies`
#: and `Unknown` are deliberately absent - they say nothing, and inventing a
#: number for them would be worse than reporting the item as unpriced.
RARITY_PROBABILITY: dict[str, float] = {
    "always": 1.0,
    "common": 1 / 8,
    "uncommon": 1 / 32,
    "rare": 1 / 128,
    "very rare": 1 / 512,
}

#: Kills per hour for a monster no guide covers, by what kind of thing it is.
DEFAULT_KPH: dict[str, float] = {"boss": 20.0, "slayer": 60.0, "regular": 150.0}

#: The floor for a training method with no rate found anywhere. Low on
#: purpose - see the module docstring.
DEFAULT_XP_PER_HOUR = 1000.0

#: Words that carry no identity in an activity name, so a task name matching
#: everything but these still counts as contained. `Killing X` and `X` are the
#: same activity; `Making a Y` and `Y` likewise.
_FILLER = frozenset(
    """a an the of and with for in at to from into by on
    making make made killing kill buying buy casting cast creating create
    cooking cook crafting craft completing complete climbing climb
    participating participate raw""".split()
)

_WORD_RE = re.compile(r"[a-z0-9']+")
_MARKED_SPAN = re.compile(r"~\|([^|]*)\|~")


@dataclass(frozen=True)
class Rate:
    """One number, and where it came from."""

    value: float
    source: str = "default"
    match: str = "default"

    def as_dict(self) -> dict[str, Any]:
        return {"value": self.value, "source": self.source, "match": self.match}


@dataclass(frozen=True)
class QuestRate:
    """A quest's estimated hours, with the wiki words behind them."""

    hours: float
    length: str = ""
    difficulty: str = ""
    source: str = "default"

    def as_dict(self) -> dict[str, Any]:
        return {
            "hours": self.hours,
            "length": self.length,
            "difficulty": self.difficulty,
            "source": self.source,
        }


@dataclass(frozen=True)
class SlayerTask:
    """One slayer task's assignment size and the rates for killing it."""

    mean_count: float
    xp_per_kill: float
    kills_per_hour: float
    source: str = "default"

    def as_dict(self) -> dict[str, Any]:
        return {
            "mean_count": self.mean_count,
            "xp_per_kill": self.xp_per_kill,
            "kills_per_hour": self.kills_per_hour,
            "source": self.source,
        }


@dataclass(frozen=True)
class Heuristics:
    """Every hand-correctable number, already merged across the two layers."""

    quests: dict[str, QuestRate] = field(default_factory=dict)
    monsters: dict[str, Rate] = field(default_factory=dict)
    #: Training task name -> skill -> XP per hour.
    training: dict[str, dict[str, Rate]] = field(default_factory=dict)
    slayer: dict[str, SlayerTask] = field(default_factory=dict)
    rarities: dict[str, float] = field(default_factory=lambda: dict(RARITY_PROBABILITY))
    boss_monsters: frozenset[str] = frozenset()
    slayer_monsters: frozenset[str] = frozenset()

    def quest_hours(self, quest: str) -> QuestRate:
        return self.quests.get(quest) or QuestRate(hours=DEFAULT_QUEST_HOURS)

    def kills_per_hour(self, monster: str) -> Rate:
        found = self.monsters.get(monster)
        if found is not None:
            return found
        kind = (
            "boss"
            if monster in self.boss_monsters
            else "slayer"
            if monster in self.slayer_monsters
            else "regular"
        )
        return Rate(value=DEFAULT_KPH[kind], source=f"default:{kind}")

    def xp_per_hour(self, task: str, skill: str) -> Rate:
        found = self.training.get(task, {}).get(skill)
        return found if found is not None else Rate(value=DEFAULT_XP_PER_HOUR)

    def rarity(self, word: str) -> float | None:
        """A probability for a worded rate, or `None` if the word says nothing.

        `Varies` and `Unknown` return `None` on purpose: the caller should
        report the item as unpriced rather than spend an invented number.
        """
        return self.rarities.get(word.strip().lower())

    def as_dict(self) -> dict[str, Any]:
        return {
            "quests": {name: rate.as_dict() for name, rate in self.quests.items()},
            "monsters": {name: rate.as_dict() for name, rate in self.monsters.items()},
            "training": {
                task: {skill: rate.as_dict() for skill, rate in skills.items()}
                for task, skills in self.training.items()
            },
            "slayer": {name: task.as_dict() for name, task in self.slayer.items()},
            "rarities": self.rarities,
        }


def hours_for_length(length: str) -> float:
    """Hours for a wiki length word, midpointing a range like `Short – Medium`."""
    cleaned = length.strip().lower()
    if not cleaned:
        return DEFAULT_QUEST_HOURS
    if cleaned in LENGTH_HOURS:
        return LENGTH_HOURS[cleaned]
    # `Short – Medium`, `Long – Very Long`: the wiki hedges with a range for
    # about a fifth of quests, and the midpoint is the only honest reading.
    parts = [part.strip() for part in re.split(r"\s*[-–—]\s*", cleaned) if part.strip()]
    ends = [LENGTH_HOURS[part] for part in parts if part in LENGTH_HOURS]
    return sum(ends) / len(ends) if ends else DEFAULT_QUEST_HOURS


def _words(text: str) -> frozenset[str]:
    """Identity-bearing words of a name: filler dropped, plurals stemmed.

    Stemming matters more than it looks. The export names a monster
    `Adamant dragon` and the guide is titled `Killing adamant dragons`; on
    exact words those share nothing decisive, and the match falls through to
    whatever fuzzy tier exists to catch it. Stemming makes it a containment,
    which is checkable.
    """
    words = frozenset(_WORD_RE.findall(normalise(text))) - _FILLER
    return frozenset(word.rstrip("s") or word for word in words)


def activity_name(task_name: str) -> str:
    """The activity a task name points at: its `~|...|~` span, or the whole.

    `Participate in ~|Underwater Agility and Thieving|~ for Agility xp` names
    an activity the wiki also has a page for; the rest of the sentence is
    upstream's phrasing and joins to nothing.
    """
    match = _MARKED_SPAN.search(task_name)
    return match.group(1).strip() if match else task_name.strip()


def _best_match(name: str, candidates: dict[str, Any]) -> tuple[str, str] | None:
    """Match `name` against `candidates`' keys: `(key, how)`, or `None`.

    Two tiers only: the names agree, or every identity-bearing word of `name`
    appears in the candidate (`Agility Pyramid` inside
    `Climbing the Agility Pyramid`). Where several contain it, the shortest
    wins - the least padded title is the most specific one.

    **There is deliberately no fuzzy tier.** An edit-distance fallback was
    tried and measured on the real data: it joined `Albatross` to `Barrows`,
    `Air elemental` to `Chaos Elemental`, and `Baby black dragon` to
    `Killing black dragons`, at 116 of 179 monster matches. Those numbers are
    worse than no number at all, because a default is visibly a default and a
    wrong join looks like evidence. Coverage falls from 179 monsters to 63 and
    from 333 training methods to 124; every survivor is checkable by reading
    the two names, and the rest fall to a default that says so.
    """
    wanted = normalise(name)
    if not wanted:
        return None
    if wanted in candidates:
        return wanted, "exact"

    name_words = _words(name)
    if not name_words:
        return None
    contained = [key for key in candidates if name_words <= _words(key)]
    if not contained:
        return None
    return min(contained, key=lambda key: (len(_words(key)), key)), "contained"


def _mmg_index(pages: dict[str, MmgRates]) -> dict[str, tuple[str, MmgRates]]:
    """Guides keyed by normalised activity, best `kph` kept on a clash."""
    index: dict[str, tuple[str, MmgRates]] = {}
    for title, rates in pages.items():
        if rates.kph is None:
            continue
        key = normalise(rates.activity or title)
        if key and (key not in index or (rates.kph or 0) > (index[key][1].kph or 0)):
            index[key] = (title, rates)
    return index


def primary_training_tasks(chunk_info: ChunkInfo) -> dict[str, str]:
    """Every `Primary: true` challenge, mapped to the skill it trains.

    2,710 of them on the real export, across 21 skill categories. These are
    what set how fast XP arrives; the rest of a skill's challenges are things
    to do *at* a level, not ways of reaching it.
    """
    tasks: dict[str, str] = {}
    for skill, challenges in chunk_info.challenges.items():
        if not isinstance(challenges, dict):
            continue
        for name, challenge in challenges.items():
            if isinstance(challenge, dict) and challenge.get("Primary") is True:
                tasks[name] = skill
    return tasks


def build_config(
    chunk_info: ChunkInfo,
    *,
    quest_pages: dict[str, str],
    mmg_pages: dict[str, MmgRates],
    assignments: dict[str, list[Assignment]],
    mob_data: dict[str, SlayerTask],
) -> dict[str, Any]:
    """Generate the full config from the export plus everything fetched.

    Every quest, monster and training method in the export gets an entry,
    defaulted where nothing was found, so the file is a complete list of what
    can be corrected rather than only what happened to join.
    """
    guides = _mmg_index(mmg_pages)

    quests: dict[str, Any] = {}
    for quest in sorted(_quest_names(chunk_info)):
        text = quest_pages.get(quest)
        length = quest_length(text) if text else None
        quests[quest] = QuestRate(
            hours=hours_for_length(length or ""),
            length=length or "",
            difficulty=(quest_difficulty(text) if text else None) or "",
            source="wiki" if length else "default",
        ).as_dict()

    monsters: dict[str, Any] = {}
    for monster in sorted(chunk_info.drops):
        found = _best_match(monster, guides)
        if found is None:
            continue
        title, rates = guides[found[0]]
        monsters[monster] = Rate(
            value=rates.kph or 0.0, source=f"mmg:{title}", match=found[1]
        ).as_dict()

    training: dict[str, Any] = {}
    for task, skill in sorted(primary_training_tasks(chunk_info).items()):
        # Only guides that actually report this skill's XP can price it.
        pool = {key: value for key, value in guides.items() if skill in value[1].experience}
        found = _best_match(activity_name(task), pool)
        if found is None:
            continue
        title, rates = pool[found[0]]
        per_hour = rates.experience[skill] * (rates.kph or 0.0)
        if per_hour <= 0:
            continue
        training.setdefault(task, {})[skill] = Rate(
            value=per_hour, source=f"mmg:{title}", match=found[1]
        ).as_dict()

    return {
        "quests": quests,
        "monsters": monsters,
        "training": training,
        "slayer": _slayer_section(chunk_info, assignments, mob_data),
        "rarities": dict(RARITY_PROBABILITY),
    }


def _quest_names(chunk_info: ChunkInfo) -> set[str]:
    """Every quest with challenges, by `BaseQuest` - the wiki's page title."""
    quests: set[str] = set()
    for challenge in _mapping(chunk_info.challenges, "Quest").values():
        if isinstance(challenge, dict) and isinstance(challenge.get("BaseQuest"), str):
            quests.add(challenge["BaseQuest"])
    return quests


def _slayer_section(
    chunk_info: ChunkInfo,
    assignments: dict[str, list[Assignment]],
    mob_data: dict[str, SlayerTask],
) -> dict[str, Any]:
    """One entry per assignable task: its size, and the rates for killing it.

    Sizes come from the wiki (any master that assigns the task will do - they
    agree), the rates from the spreadsheet. The *weights* deliberately do not
    live here: the export already has them per master, and duplicating them
    would let the config and the export disagree about the same fact.
    """
    sizes: dict[str, Assignment] = {}
    for rows in assignments.values():
        for row in rows:
            sizes.setdefault(normalise(row.task), row)

    tasks: dict[str, Any] = {}
    for master_tasks in _mapping(chunk_info.data, "slayerMasterTasks").values():
        if not isinstance(master_tasks, dict):
            continue
        for task in master_tasks:
            key = normalise(task)
            if task in tasks:
                continue
            size = sizes.get(key)
            rates = mob_data.get(key) or (
                mob_data[found[0]] if (found := _best_match(task, mob_data)) else None
            )
            if size is None and rates is None:
                continue
            tasks[task] = SlayerTask(
                mean_count=size.mean_count if size else 0.0,
                xp_per_kill=rates.xp_per_kill if rates else 0.0,
                kills_per_hour=rates.kills_per_hour if rates else 0.0,
                source="wiki+sheet" if size and rates else "wiki" if size else "sheet",
            ).as_dict()
    return tasks


def merge(scraped: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge `overrides` over `scraped`; the deepest value wins.

    Merging rather than replacing means an override can pin one quest's hours
    without restating its length, or one skill of one training method without
    restating the others.
    """
    merged = dict(scraped)
    for key, value in overrides.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = merge(existing, value)
        else:
            merged[key] = value
    return merged


def disagreements(scraped: dict[str, Any], overrides: dict[str, Any]) -> list[str]:
    """Paths where a hand-set value differs from what the scrape now says.

    Not an error - the override is meant to win, and usually should. It is
    reported because a *silent* win is how a corrected number outlives the
    reason it was corrected.
    """
    found: list[str] = []

    def walk(left: Any, right: Any, path: str) -> None:
        if isinstance(left, dict) and isinstance(right, dict):
            for key in right:
                if key in left:
                    walk(left[key], right[key], f"{path}.{key}" if path else str(key))
        elif left != right:
            found.append(f"{path}: {left!r} -> {right!r}")

    walk(scraped, overrides, "")
    return sorted(found)


def load(
    config: dict[str, Any],
    *,
    boss_monsters: frozenset[str] = frozenset(),
    slayer_monsters: frozenset[str] = frozenset(),
) -> Heuristics:
    """Build a `Heuristics` from an already-merged config."""
    return Heuristics(
        quests={
            name: QuestRate(
                hours=_float(entry.get("hours"), DEFAULT_QUEST_HOURS),
                length=str(entry.get("length") or ""),
                difficulty=str(entry.get("difficulty") or ""),
                source=str(entry.get("source") or "default"),
            )
            for name, entry in _entries(config, "quests")
        },
        monsters={
            name: _rate(entry) for name, entry in _entries(config, "monsters")
        },
        training={
            task: {
                skill: _rate(entry)
                for skill, entry in skills.items()
                if isinstance(entry, dict)
            }
            for task, skills in _entries(config, "training")
            if isinstance(skills, dict)
        },
        slayer={
            name: SlayerTask(
                mean_count=_float(entry.get("mean_count"), 0.0),
                xp_per_kill=_float(entry.get("xp_per_kill"), 0.0),
                kills_per_hour=_float(entry.get("kills_per_hour"), 0.0),
                source=str(entry.get("source") or "default"),
            )
            for name, entry in _entries(config, "slayer")
        },
        rarities={
            **RARITY_PROBABILITY,
            **{
                str(word).lower(): float(value)
                for word, value in _mapping(config, "rarities").items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            },
        },
        boss_monsters=boss_monsters,
        slayer_monsters=slayer_monsters,
    )


def _entries(config: dict[str, Any], section: str) -> list[tuple[str, Any]]:
    return [
        (str(name), value)
        for name, value in _mapping(config, section).items()
        if isinstance(value, dict)
    ]


def _rate(entry: dict[str, Any]) -> Rate:
    return Rate(
        value=_float(entry.get("value"), 0.0),
        source=str(entry.get("source") or "default"),
        match=str(entry.get("match") or "default"),
    )


def _float(value: Any, fallback: float) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else fallback
