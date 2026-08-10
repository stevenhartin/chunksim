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
Measured against the real export: 1,015 of 1,111 guides carry a `kph`, and they
join to **246 of the 2,657** `Primary: true` training methods and **91 of the
872** monsters with drops. Quests are the exception and come out complete,
209 of 209.

That monster count is 91 rather than 106 because **a `kph` is only a kill rate
when its guide says so**. `Mmgtable` counts whatever its guide is about, so
joining every guide to a monster name had `Grinding unicorn horns` pricing a
`Unicorn` at 9,000 an hour. `MmgRates.counts_kills` is the gate; the training
path deliberately keeps using every guide, since XP per hour is exactly what
the non-kill ones measure. Everything unjoined gets a default, which is why
`DEFAULT_XP_PER_HOUR` is deliberately *low* - an un-joined method should look
slow and obvious rather than fast and invisible, so the entries worth an
afternoon of hand-correction are the ones dominating the total. The generated
config lists every quest, monster and training method regardless, so there is
always a line to correct.

**Joins record how they were made**, and there are only two ways. `exact`
means the identity-bearing words are the same set - which covers `Jellies`
against `Jelly` and `Killing General Graardor` against `General Graardor`,
since plurals and filler words carry no identity. `contained` means every
word of the task name appears in a longer activity name, as `Agility Pyramid`
does inside `Climbing the Agility Pyramid`. Writing the provenance next to the
number is what makes a wrong join findable in a 3,700-entry file instead of
buried inside one total.

Plurals get `stems`, which generates *every* singular a word might be rather
than applying one rule. English does not have one rule - `jellies`/`jelly`,
`axes`/`axe`, `zombies`/`zombie` - and a single rule silently loses whichever
words it does not fit. `rstrip("s")` read `Jellies` as `jellie`, never matched
the spreadsheet's `Jelly`, and the task reported as having no kill-rate data
while the row sat there.

**There is no fuzzy tier, and that was a measurement rather than a taste.**
An edit-distance fallback (`search.rank`) lifted monster coverage from 105 to
179 - and 116 of those 179 were fuzzy matches including `Albatross` to
`Barrows` and `Air elemental` to `Chaos Elemental`. Those are worse than no
answer: a default announces itself as a default, while a wrong join reads as
evidence and will be believed. The lower number is the honest one.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence, TypeVar

from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.derive.search import normalise
from fray_claude.model.summary import _mapping
from fray_claude.derive.task_names import strip_task_markup
from fray_claude.remote.combat import AttackSpell, MonsterStats
from fray_claude.remote.skill_tables import COURSE_ALIASES, SkillRow
from fray_claude.remote.stores import ShopPrice
from fray_claude.remote.wiki import Assignment, MmgRates, quest_difficulty, quest_length

#: Quest length word -> hours. The words are the wiki's own `Length` column
#: on `Quests/List`; the hours are this project's, the wiki giving no duration.
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

#: Slayer reward points a completed task pays, by master. Not in the export;
#: these are the wiki's published figures. Turael, Spria and Mortimer pay
#: nothing by default, which is exactly why they are cheap to train at and
#: expensive to *skip* at.
SLAYER_POINTS: dict[str, float] = {
    "Turael": 0.0,
    "Spria": 0.0,
    "Mazchna": 6.0,
    "Vannaka": 8.0,
    "Chaeldar": 10.0,
    "Nieve": 12.0,
    "Duradel": 15.0,
    "Konar quo Maten": 18.0,
    "Krystilia": 25.0,
    "Mortimer": 0.0,
}

#: Task-streak milestones: every Nth completed task pays this multiple of
#: the master's base points. **Only the highest applicable one is awarded**,
#: not the sum - checked against the wiki's own worked example, a 1,000-task
#: Krystilia streak paying 44,375. Highest-applicable reproduces that
#: exactly; stacking them gives 53,500.
STREAK_BONUSES: dict[int, float] = {10: 5.0, 50: 15.0, 100: 25.0, 250: 35.0, 1000: 50.0}

#: What cancelling a task costs. The flat 30 is universal; Mortimer is the
#: exception. Note this is the *skip* cost, not the far larger `block` cost
#: the wiki tabulates beside it - blocking is permanent and a different
#: decision.
DEFAULT_SKIP_COST = 30.0
SLAYER_SKIP_COST: dict[str, float] = {"Mortimer": 100.0}

#: Kills per hour above which a slayer rate must have been measured with a
#: multi-target method - chinning or barrage bursting - rather than by
#: fighting one thing at a time. See `SlayerTask.is_multi_target` for why the
#: rate is the only available tell and what the line misses.
MULTI_TARGET_KPH = 1000.0

#: What an unpriced *slayer task* is assumed to yield. Deliberately poor -
#: the tasks with no data are the low-level ones nobody optimises, and a
#: master whose list is full of them should look slow rather than look fast
#: by having them quietly excluded from its average.
DEFAULT_SLAYER_XP_PER_HOUR = 7000.0

#: A superior's base spawn chance from a normal counterpart's death, per the
#: wiki. The per-monster figures in its table are the improved rates that the
#: `Bigger and Badder` unlock buys; this is the plain one.
DEFAULT_SUPERIOR_SPAWN_RATE = 1 / 200

#: Words that carry no identity in an activity name, so a task name matching
#: everything but these still counts as contained. `Killing X` and `X` are the
#: same activity; `Making a Y` and `Y` likewise.
_FILLER = frozenset(
    """a an the of and with for in at to from into by on
    making make made killing kill buying buy casting cast creating create
    cooking cook crafting craft completing complete climbing climb
    participating participate raw""".split()
)

_T = TypeVar("_T")

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
    """One master's assignment of one task: how many, and how fast.

    **Sizes are per master and the rates are not.** Duradel assigns 130-200
    abyssal demons where Krystilia assigns 75-125, so the config is keyed
    `slayer[master][task]`; how quickly you kill one and what it gives is a
    property of the monster, so those repeat across masters.

    `extended_count` is the size with the Extended unlock bought, and is
    **off unless `extended` says otherwise** - it is a paid unlock, so
    assuming it would silently lengthen every task for a player who has not
    bought it. Set it per task in `heuristics/overrides.json`.
    """

    mean_count: float
    xp_per_kill: float
    kills_per_hour: float
    source: str = "default"
    #: `0.0` where the task has no extended size, which most do not have.
    extended_count: float = 0.0
    extended: bool = False

    @property
    def count(self) -> float:
        """The assignment size actually in force - read this, not the fields."""
        if self.extended and self.extended_count > 0:
            return self.extended_count
        return self.mean_count

    @property
    def is_multi_target(self) -> bool:
        """Whether this rate was measured with chinning or barrage bursting.

        **The spreadsheet records the best method, and the best method for a
        stackable task is not fighting things one at a time.** `Spiders` reads
        3,360 kills an hour - one every 1.07 seconds - which no weapon does
        single-target; it is red chinchompas thrown into a stack. `Ankous`,
        `Jellies` and `Zombies` all read 1,500, the same signature.

        There is no column saying so, so the rate itself is the only tell and
        `MULTI_TARGET_KPH` is where the line is drawn. It catches 18 of the
        147 measured tasks.

        **Deliberately conservative, and it misses some.** `Dust devils` at
        950 and `Kalphites` at 870 are bursting tasks in practice and sit just
        under. Pin them in `heuristics/overrides.json` if their rates matter;
        the threshold is not trying to be clever, only to name the rows that
        obviously are not single-target.

        Why any of this is worth knowing: these methods need things a chunk
        map may simply not have - barrage wants Desert Treasure I, chinning
        wants a box trap and the roughly 500 chinchompas an hour that catching
        them yields - so a 70,000 XP an hour figure derived from one is not a
        rate this player can achieve. `dps_bridge.price_slayer_tasks` computes
        the single-target alternative.
        """
        return self.kills_per_hour >= MULTI_TARGET_KPH

    def as_dict(self) -> dict[str, Any]:
        return {
            "mean_count": self.mean_count,
            "extended_count": self.extended_count,
            "extended": self.extended,
            "xp_per_kill": self.xp_per_kill,
            "kills_per_hour": self.kills_per_hour,
            "source": self.source,
        }


@dataclass(frozen=True)
class TaskLength:
    """One task's assignment size, ordinary and with the Extended unlock."""

    task: str
    low: float
    high: float
    extended_low: float = 0.0
    extended_high: float = 0.0

    @property
    def mean_count(self) -> float:
        return (self.low + self.high) / 2

    @property
    def extended_count(self) -> float:
        """`0.0` when the task has no extended size, which most do not."""
        if self.extended_low <= 0 or self.extended_high <= 0:
            return 0.0
        return (self.extended_low + self.extended_high) / 2


@dataclass(frozen=True)
class Superior:
    """A superior slayer monster, and the ordinary one it replaces.

    Superiors are never placed in a chunk - they spawn from the death of a
    normal counterpart, only while on a slayer task, at roughly 1/200. The
    export has no idea they exist as monsters: `Colossal Hydra` appears only
    as a `skillItems.Slayer` activity with 43 drops and no location at all.
    """

    name: str
    base: str
    spawn_rate: float = DEFAULT_SUPERIOR_SPAWN_RATE

    def as_dict(self) -> dict[str, Any]:
        return {"base": self.base, "spawn_rate": self.spawn_rate}


@dataclass(frozen=True)
class Heuristics:
    """Every hand-correctable number, already merged across the two layers."""

    quests: dict[str, QuestRate] = field(default_factory=dict)
    monsters: dict[str, Rate] = field(default_factory=dict)
    superiors: dict[str, Superior] = field(default_factory=dict)
    #: Training task name -> skill -> XP per hour.
    training: dict[str, dict[str, Rate]] = field(default_factory=dict)
    #: `slayer[master][task]` - sizes differ by master, so the master is
    #: part of the key. See `SlayerTask`.
    slayer: dict[str, dict[str, SlayerTask]] = field(default_factory=dict)
    rarities: dict[str, float] = field(default_factory=lambda: dict(RARITY_PROBABILITY))
    #: Per-master point values, overriding `SLAYER_POINTS`.
    master_points: dict[str, float] = field(default_factory=dict)
    master_skip_costs: dict[str, float] = field(default_factory=dict)
    boss_monsters: frozenset[str] = frozenset()
    slayer_monsters: frozenset[str] = frozenset()
    #: Monster -> hitpoints and xp multiplier, for `costing/combat_xp.py`.
    monster_stats: dict[str, MonsterStats] = field(default_factory=dict)
    #: Autocastable spells, cheapest level first.
    spells: tuple[AttackSpell, ...] = ()
    #: Combat skill -> its computed rate. Filled by `inputs.priced_heuristics`
    #: **after** the kill rates are final, since it multiplies them.
    combat: dict[str, Rate] = field(default_factory=dict)
    #: Shop -> item -> what it charges. From `remote/stores.py`.
    shop_prices: dict[str, dict[str, ShopPrice]] = field(default_factory=dict)
    #: Item -> the fee charged to make it, where a conversion has one. The
    #: export models the sawmill and not its price; see `remote/stores.py`.
    conversion_fees: dict[str, ShopPrice] = field(default_factory=dict)
    #: Currency -> how much of it can be earned an hour. A currency missing
    #: from here cannot be priced at all - see `DEFAULT_CURRENCY_PER_HOUR`.
    currency_per_hour: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_CURRENCY_PER_HOUR)
    )
    #: Combat skill -> the damage per hour behind that rate. Carried
    #: separately because it cannot be recovered from the rate: Magic's is
    #: mostly casting experience. `combat_xp.hitpoints_credit` needs it.
    combat_damage: dict[str, float] = field(default_factory=dict)

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

    def shop_seconds(self, shop: str, item: str) -> float | None:
        """Seconds of earning to afford one `item` at `shop`, or `None`.

        `None` is "this cannot be priced" and the caller must treat it as no
        route - either the wiki does not list the price, or it is charged in a
        currency with no rate. **Not zero**: a shop route priced at nothing is
        how a build costing ten million coins became the fastest training in
        the game.

        Zero *is* returned for a genuinely free item, which the wiki does
        record - a price of 0 in coins is a giveaway, not a missing figure.
        """
        entry = self.shop_prices.get(shop, {}).get(item)
        if entry is None:
            return None
        rate = self.currency_per_hour.get(entry.currency)
        if rate is None or rate <= 0:
            return None
        return entry.price * 3600.0 / rate

    def conversion_seconds(self, item: str) -> float:
        """Seconds of earning to pay the fee for making `item`, or zero.

        **Zero rather than `None`**, unlike `shop_seconds`: a conversion with
        no recorded fee is free to perform, which is the common case - only
        the sawmill charges. An unknown *currency* is the exception and is
        refused, since that is a fee we cannot price rather than none.
        """
        entry = self.conversion_fees.get(item)
        if entry is None:
            return 0.0
        rate = self.currency_per_hour.get(entry.currency)
        if rate is None or rate <= 0:
            return math.inf
        return entry.price * 3600.0 / rate

    def xp_per_hour(self, task: str, skill: str) -> Rate:
        found = self.training.get(task, {}).get(skill)
        return found if found is not None else Rate(value=DEFAULT_XP_PER_HOUR)

    def slayer_points(self, master: str) -> float:
        """Points a completed task pays, before any diary modifiers."""
        return self.master_points.get(master, SLAYER_POINTS.get(master, 0.0))

    def slayer_skip_cost(self, master: str) -> float:
        """Points cancelling a task costs."""
        return self.master_skip_costs.get(
            master, SLAYER_SKIP_COST.get(master, DEFAULT_SKIP_COST)
        )

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
            "slayer": {
                master: {name: task.as_dict() for name, task in tasks.items()}
                for master, tasks in self.slayer.items()
            },
            "rarities": self.rarities,
        }


def streak_factor(bonuses: dict[int, float] | None = None) -> float:
    """Average points multiplier per completed task, milestones included.

    The milestones are worth having in the average: 1.775x on the standard
    table, so a master paying 25 a task really pays 44.4 over a long streak.
    Amortising them is the honest way to carry that - the alternative is a
    per-task figure that is right for 900 tasks in 1,000 and wrong for the
    other hundred.

    Computed by walking one full cycle rather than by inclusion-exclusion,
    because the milestones overlap (task 1,000 is also a 250th, a 100th, a
    50th and a 10th) and only the highest counts. Walking it cannot get the
    overlaps wrong; the closed form can, and did.

    **Assumes cancelling does not break the streak.** In-game it is
    Turael-skipping that resets it, not paying a master to cancel - which is
    the whole reason cancelling costs points.
    """
    table = bonuses if bonuses is not None else STREAK_BONUSES
    if not table:
        return 1.0
    cycle = max(table)
    total = 0.0
    for task in range(1, cycle + 1):
        hit = [multiple for interval, multiple in table.items() if task % interval == 0]
        total += max(hit) if hit else 1.0
    return total / cycle


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


def stems(word: str) -> frozenset[str]:
    """Every singular `word` might be, because English has no single rule.

    `jellies` is `jelly`, `axes` is `axe`, `zombies` is `zombie`: any one
    stemming rule gets some of those and breaks the others. Naive
    `rstrip("s")` reads `Jellies` as `jellie` and so never matched the
    spreadsheet's `Jelly` - which then reported as "no kill rate for this
    task" when the row was sitting right there. Generating the candidates and
    accepting any overlap costs nothing at these lengths and cannot be wrong
    in the way a single rule is.
    """
    candidates = {word}
    if word.endswith("s") and not word.endswith("ss"):
        candidates.add(word[:-1])
    if word.endswith("es"):
        candidates.add(word[:-2])
    if word.endswith("ies") and len(word) > 4:
        candidates.add(f"{word[:-3]}y")
    if word.endswith("ves") and len(word) > 4:
        # `wolves`/`elves`/`dwarves` are `wolf`/`elf`/`dwarf`, and `knives` is
        # `knife` - two rules, so both candidates go in. Slayer names four
        # task categories this way (`Wolves`, `Elves`, `Dwarves`,
        # `Werewolves`), none of which matched a monster without it.
        candidates.add(f"{word[:-3]}f")
        candidates.add(f"{word[:-3]}fe")
    return frozenset(candidates)


def _same_word(left: str, right: str) -> bool:
    return bool(stems(left) & stems(right))


def _words(text: str) -> frozenset[str]:
    """Identity-bearing words of a name, filler dropped.

    Kept unstemmed; comparison goes through `_same_word`, which considers
    every plural form either side might be wearing.
    """
    return frozenset(_WORD_RE.findall(normalise(text))) - _FILLER


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

    # Singular/plural counts as exact: `Jellies` and `Jelly` are one task.
    same = [
        key
        for key in candidates
        if len(_words(key)) == len(name_words)
        and all(any(_same_word(word, other) for other in _words(key)) for word in name_words)
    ]
    if same:
        return min(same, key=len), "exact"

    contained = [
        key
        for key in candidates
        if all(any(_same_word(word, other) for other in _words(key)) for word in name_words)
    ]
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


#: How fast a currency can be earned, per hour. **Tunable, and the two that
#: are here are the two anyone converts.** `Coins` at 500,000 an hour is a
#: middling money-maker; `Tokkul` at 25,000 is far slower, which is the whole
#: point of listing it separately - an obsidian weapon at 375 Tokkul costs
#: fifteen times what its coin price would suggest.
#:
#: A currency **absent from this map is refused, not guessed**: castle wars
#: tickets, trading sticks and the various point currencies have no exchange
#: rate anyone would agree on, so an item sold only for those has no price
#: here rather than a free one. Override under `currencies` in
#: `heuristics/overrides.json`.
DEFAULT_CURRENCY_PER_HOUR: dict[str, float] = {
    "Coins": 500_000.0,
    "Tokkul": 25_000.0,
}

#: Seconds one shortcut use takes, door to door. **A stated target, not a
#: measurement**: nothing publishes a shortcut rate, so this is set so that the
#: best shortcut in the table (25 xp) reaches ~5,000 xp/hr, which is what
#: spamming one actually yields. Most pay 0.5-3 xp and are worth nothing as
#: training, which is the honest outcome - they exist in the export as *access*,
#: and pricing them generously would invent a training method out of a door.
SHORTCUT_CYCLE_SECONDS = 18.0

#: Seconds one pickpocket attempt takes, stuns and failures included.
#: **Calibrated against the wiki's own published figure**: a Knight of Ardougne
#: pays 84.3 xp and `Thieving training` quotes 86,000 xp/hr at level 55, which
#: is 3.5s an attempt. That is the rate at the level the method *opens*, which
#: is deliberately the conservative end - the same table quotes 240,000 at 95,
#: because success rate climbs with level and one constant cannot follow it.
#: A band is priced from where it opens, so this understates the tail rather
#: than overstating the start.
PICKPOCKET_CYCLE_SECONDS = 3.5


def _table_rates(
    chunk_info: ChunkInfo, tables: Mapping[str, Sequence[SkillRow]]
) -> dict[str, dict[str, Rate]]:
    """Agility and Thieving rates, joined from `remote/skill_tables.py`.

    **Structural joins, so there is no fuzzy tier.** A shortcut, stall or
    pickpocket challenge names the object or NPC it acts on, and the wiki table
    names the same thing; a course joins on its own name through
    `COURSE_ALIASES`. Nothing here matches on a substring, which is why these
    are recorded as `exact`.

    The two rates the tables do not publish - a shortcut's and a pickpocket's -
    are `experience / cycle`, with the cycles above.
    """
    lookup = {
        kind: {row.name.lower(): row for row in rows} for kind, rows in tables.items()
    }
    rated: dict[str, dict[str, Rate]] = {}
    for task, skill in sorted(primary_training_tasks(chunk_info).items()):
        if skill not in ("Agility", "Thieving"):
            continue
        challenge = _mapping(chunk_info.challenges, skill).get(task)
        if not isinstance(challenge, dict):
            continue
        keys = _join_keys(challenge, task, COURSE_ALIASES)
        for kind, per_hour in (
            ("courses", None),
            ("stalls", None),
            ("pickpockets", PICKPOCKET_CYCLE_SECONDS),
            ("shortcuts", SHORTCUT_CYCLE_SECONDS),
        ):
            rows_for = lookup.get(kind, {})
            row = next((rows_for[key] for key in keys if key in rows_for), None)
            if row is None:
                continue
            value = row.xp_per_hour if per_hour is None else row.experience * 3600.0 / per_hour
            if value and value > 0:
                rated.setdefault(task, {})[skill] = Rate(
                    value=value, source=f"wiki:{kind}", match="exact"
                )
            break
    return rated


def _join_keys(challenge: dict[str, Any], task: str, aliases: Mapping[str, str]) -> list[str]:
    """Every name a challenge offers to join on, lowercased.

    `Output` first because it is the one field every pickpocket carries -
    `NPCs` is present on only 5 of 33 - then the objects and NPCs, then the
    task's own words for a course. `[+]`, `*` and `#section` are stripped:
    upstream uses them to mean "or its variants" and "this part of", neither of
    which changes which wiki row describes the thing.
    """
    def clean(name: str) -> str:
        return name.split("#")[0].replace("[+]", "").replace("*", "").strip().lower()

    keys: list[str] = []
    output = challenge.get("Output")
    if isinstance(output, str):
        keys.append(clean(output))
    for field in ("Objects", "NPCs"):
        keys += [clean(name) for name in challenge.get(field) or () if isinstance(name, str)]
    spelled = strip_task_markup(task).removeprefix("Access the ").strip()
    keys.append(clean(aliases.get(spelled, spelled)))
    return [key for key in dict.fromkeys(keys) if key]


def build_config(
    chunk_info: ChunkInfo,
    *,
    quest_pages: dict[str, str],
    mmg_pages: dict[str, MmgRates],
    assignments: dict[str, list[Assignment]],
    mob_data: dict[str, SlayerTask],
    task_lengths: dict[str, dict[str, TaskLength]] | None = None,
    superiors: list[tuple[str, str]] | None = None,
    skill_tables: Mapping[str, Sequence[SkillRow]] | None = None,
    monster_stats: Mapping[str, MonsterStats] | None = None,
    spells: Sequence[AttackSpell] = (),
    shop_prices: Mapping[str, Mapping[str, ShopPrice]] | None = None,
    conversion_fees: Mapping[str, ShopPrice] | None = None,
) -> dict[str, Any]:
    """Generate the full config from the export plus everything fetched.

    Every quest, monster and training method in the export gets an entry,
    defaulted where nothing was found, so the file is a complete list of what
    can be corrected rather than only what happened to join.
    """
    guides = _mmg_index(mmg_pages)

    quests: dict[str, Any] = {}
    for quest in sorted(quest_names(chunk_info)):
        text = quest_pages.get(quest)
        length = quest_length(text) if text else None
        quests[quest] = QuestRate(
            hours=hours_for_length(length or ""),
            length=length or "",
            difficulty=(quest_difficulty(text) if text else None) or "",
            source="wiki" if length else "default",
        ).as_dict()

    # **Only guides that count kills can price a kill.** `Mmgtable`'s `kph`
    # counts whatever its guide is about, so joining a monster name against
    # every guide let `Grinding unicorn horns` set `Unicorn` to 9,000 an hour
    # and `Pickpocketing Knights of Ardougne` set that knight to 3,000 - rates
    # of grinding and thieving, not of killing. See `MmgRates.counts_kills`.
    kill_guides = {
        key: value for key, value in guides.items() if value[1].counts_kills
    }

    monsters: dict[str, Any] = {}
    for monster in sorted(chunk_info.drops):
        found = _best_match(monster, kill_guides)
        if found is None:
            continue
        title, rates = kill_guides[found[0]]
        monsters[monster] = Rate(
            value=rates.kph or 0.0, source=f"mmg:{title}", match=found[1]
        ).as_dict()

    training: dict[str, Any] = {}
    # **A guide somebody names exactly is not available to anybody else.**
    # `_best_match`'s containment tier is right far more often than not - a
    # guide called "Cleaning grimy torstol" really is the one for cleaning
    # torstol - but it cannot tell a padded title from a *different, better*
    # item: `Mix a ~|combat potion|~` contains itself in "Making **super**
    # combat potions" and inherited its 315,000 xp/hr, and `Cut a ~|diamond|~`
    # took the rate for crafting diamond *bracelets*, which is a different
    # action entirely.
    #
    # The fix needs no word list and no judgement about English: if another
    # method matches that guide *exactly*, the guide is that method's, and the
    # contained claim is refused. Measured on the real scrape this is 9 joins,
    # every one of them wrong: six gem bracelets, chocolate cake, fine fish
    # offcuts, and the combat potion. What is left has no rate, which is the
    # honest answer - the floor says so, where a stolen number does not.
    claims: list[tuple[str, str, str, str, str, float]] = []
    exact_claims: set[str] = set()
    for task, skill in sorted(primary_training_tasks(chunk_info).items()):
        # Only guides that actually report this skill's XP can price it.
        pool = {name: entry for name, entry in guides.items() if skill in entry[1].experience}
        found = _best_match(activity_name(task), pool)
        if found is None:
            continue
        guide, how = found
        title, rates = pool[guide]
        # **`Experience{N}isph` means the figure is already hourly.**
        # Multiplying it by `kph` again is how Tempoross reached 3,720,000
        # Fishing xp an hour off a guide plainly stating 62,000.
        per_hour = (
            rates.experience[skill]
            if skill in rates.per_hour
            else rates.experience[skill] * (rates.kph or 0.0)
        )
        claims.append((task, skill, guide, how, title, per_hour))
        if how == "exact":
            exact_claims.add(guide)

    # **And the most specific contained claim wins the rest.** The exact rule
    # above only fires when some method names the guide outright, which leaves
    # every guide nobody names exactly open to its vaguest claimant:
    # `Chop ~|logs|~` is contained in "Cutting camphor logs" exactly as
    # `Chop ~|camphor logs|~` is, and it is a level *1* method that inherited
    # a 66-Woodcutting rate - which the band walk then applied from level 1
    # upwards. A claim that is a strict substring of another claim on the same
    # guide is the less specific reading of it, and is refused.
    by_guide: dict[str, set[str]] = {}
    for _, _, guide, how, _, _ in claims:
        if how != "exact":
            by_guide.setdefault(guide, set())
    for task, skill, guide, how, _, _ in claims:
        if how != "exact" and guide in by_guide:
            by_guide[guide].add(activity_name(task))

    for task, skill, guide, how, title, per_hour in claims:
        if how != "exact" and guide in exact_claims:
            continue
        if how != "exact":
            mine = activity_name(task)
            if any(
                other != mine and mine in other for other in by_guide.get(guide, ())
            ):
                continue
        if per_hour <= 0:
            continue
        training.setdefault(task, {})[skill] = Rate(
            value=per_hour, source=f"mmg:{title}", match=how
        ).as_dict()

    # **The Agility and Thieving tables, which no guide covers.** They are
    # joined structurally rather than by name, so they outrank a `contained`
    # money-making guide - but an *exact* guide keeps its method, on the same
    # rule that settles every other contest here: the more specific claim wins,
    # and a guide that names the method exactly is as specific as it gets.
    for task, skills in _table_rates(chunk_info, skill_tables or {}).items():
        for skill, rate in skills.items():
            existing = training.get(task, {}).get(skill)
            if existing is not None and existing.get("match") == "exact":
                continue
            training.setdefault(task, {})[skill] = rate.as_dict()

    # Only superiors the export actually knows about, so the section stays a
    # list of things that can appear in an estimate rather than a copy of the
    # wiki. `skillItems.Slayer` is where they live - never `drops`.
    known = set(_mapping(chunk_info.skill_items, "Slayer"))
    return {
        "quests": quests,
        "monsters": monsters,
        "training": training,
        "slayer": _slayer_section(chunk_info, assignments, mob_data, task_lengths),
        "superiors": {
            superior: Superior(name=superior, base=base).as_dict()
            for superior, base in superiors or ()
            if superior in known
        },
        "rarities": dict(RARITY_PROBABILITY),
        # **Only the monsters an estimate could ask about.** The wiki has
        # 1,382 with hitpoints and the export knows 872; storing the rest
        # would be a copy of the wiki rather than a config for this map.
        "monster_stats": {
            name: entry.as_dict()
            for name, entry in sorted((monster_stats or {}).items())
            if name in chunk_info.drops or name in known
        },
        "spells": [spell.as_dict() for spell in spells],
        # **Only shops the export knows about.** The wiki lists 588 and the
        # export stocks 435; the rest are a copy of the wiki rather than a
        # config for this map.
        "shops": {
            shop: {item: entry.as_dict() for item, entry in sorted(items.items())}
            for shop, items in sorted((shop_prices or {}).items())
            if shop in chunk_info.data.get("shopItems", {})
        },
        "conversions": {
            item: entry.as_dict() for item, entry in sorted((conversion_fees or {}).items())
        },
        "currencies": dict(DEFAULT_CURRENCY_PER_HOUR),
    }


def quest_names(chunk_info: ChunkInfo) -> set[str]:
    """Every quest with challenges, by `BaseQuest` - the wiki's page title."""
    quests: set[str] = set()
    for challenge in _mapping(chunk_info.challenges, "Quest").values():
        if isinstance(challenge, dict) and isinstance(challenge.get("BaseQuest"), str):
            quests.add(challenge["BaseQuest"])
    return quests


def _sheet_master(master: str, lengths: dict[str, dict[str, TaskLength]]) -> str:
    """The sheet's label for an export master: `Konar` for `Konar quo Maten`."""
    for label in lengths:
        if _words(label) <= _words(master):
            return label
    return master


def _lookup(key: str, table: dict[str, _T]) -> _T | None:
    """`table[key]`, falling back to the plural-tolerant match."""
    found = table.get(key)
    if found is not None:
        return found
    near = _best_match(key, table)
    return table[near[0]] if near else None


def _slayer_section(
    chunk_info: ChunkInfo,
    assignments: dict[str, list[Assignment]],
    mob_data: dict[str, SlayerTask],
    task_lengths: dict[str, dict[str, TaskLength]] | None = None,
) -> dict[str, Any]:
    """`slayer[master][task]`: how many, and how fast.

    **Keyed by master, because the size is.** Duradel assigns 130-200 abyssal
    demons and Krystilia 75-125; a flat per-task config had to pick one and
    was silently wrong for every other master. The rates are per monster and
    so repeat across masters, which is duplication a generated file can
    afford.

    Sizes come from two places. The spreadsheet's Task Lengths tab is
    preferred where it has the task, because it is the only source for the
    *extended* size as well; the wiki's per-master tables cover the six
    masters that tab omits. Weights deliberately live in neither: the export
    already has them, and duplicating them would let the two disagree about
    the same fact.
    """
    lengths = task_lengths or {}
    sizes_by_master: dict[str, dict[str, Assignment]] = {
        master: {normalise(row.task): row for row in rows}
        for master, rows in assignments.items()
    }
    anywhere: dict[str, Assignment] = {}
    for rows in assignments.values():
        for row in rows:
            anywhere.setdefault(normalise(row.task), row)

    section: dict[str, Any] = {}
    for master, master_tasks in _mapping(chunk_info.data, "slayerMasterTasks").items():
        if not isinstance(master_tasks, dict):
            continue
        entries: dict[str, Any] = {}
        for task in master_tasks:
            # Konar keys her tasks `<task> - <location>` ("Aberrant spectres
            # - Catacombs of Kourend"), 93 of them; the rates are recorded
            # against the task, so the location comes off before any lookup.
            # Keyed back under the full name, which is what the export - and
            # therefore `slayer.py` - asks for.
            key = normalise(task.split(" - ")[0])

            length = _lookup(key, lengths.get(_sheet_master(master, lengths)) or {})
            size = _lookup(key, sizes_by_master.get(master) or {}) or _lookup(key, anywhere)
            rates = _lookup(key, mob_data)

            mean = length.mean_count if length else (size.mean_count if size else 0.0)
            if mean <= 0 and rates is None:
                continue
            entries[task] = SlayerTask(
                mean_count=mean,
                extended_count=length.extended_count if length else 0.0,
                extended=False,
                xp_per_kill=rates.xp_per_kill if rates else 0.0,
                kills_per_hour=rates.kills_per_hour if rates else 0.0,
                source="+".join(
                    part
                    for part, present in (
                        ("lengths", length is not None),
                        ("wiki", length is None and size is not None),
                        ("sheet", rates is not None),
                    )
                    if present
                )
                or "default",
            ).as_dict()
        if entries:
            section[master] = entries
    return section


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
        superiors={
            name: Superior(
                name=name,
                base=str(entry.get("base") or ""),
                spawn_rate=_float(entry.get("spawn_rate"), DEFAULT_SUPERIOR_SPAWN_RATE),
            )
            for name, entry in _entries(config, "superiors")
            if entry.get("base")
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
            master: {
                name: SlayerTask(
                    mean_count=_float(entry.get("mean_count"), 0.0),
                    extended_count=_float(entry.get("extended_count"), 0.0),
                    extended=entry.get("extended") is True,
                    xp_per_kill=_float(entry.get("xp_per_kill"), 0.0),
                    kills_per_hour=_float(entry.get("kills_per_hour"), 0.0),
                    source=str(entry.get("source") or "default"),
                )
                for name, entry in tasks.items()
                if isinstance(entry, dict)
            }
            for master, tasks in _entries(config, "slayer")
            if isinstance(tasks, dict)
        },
        master_points={
            str(master): float(entry["points"])
            for master, entry in _entries(config, "masters")
            if isinstance(entry.get("points"), (int, float))
            and not isinstance(entry.get("points"), bool)
        },
        master_skip_costs={
            str(master): float(entry["skip_cost"])
            for master, entry in _entries(config, "masters")
            if isinstance(entry.get("skip_cost"), (int, float))
            and not isinstance(entry.get("skip_cost"), bool)
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
        shop_prices={
            shop: {
                item: ShopPrice(
                    price=_float(entry.get("price"), 0.0),
                    currency=str(entry.get("currency") or ""),
                )
                for item, entry in items.items()
                if isinstance(entry, dict)
            }
            for shop, items in _entries(config, "shops")
            if isinstance(items, dict)
        },
        conversion_fees={
            item: ShopPrice(
                price=_float(entry.get("price"), 0.0),
                currency=str(entry.get("currency") or ""),
            )
            for item, entry in _entries(config, "conversions")
        },
        currency_per_hour={
            **DEFAULT_CURRENCY_PER_HOUR,
            **{
                name: _float(value, 0.0)
                for name, value in _mapping(config, "currencies").items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            },
        },
        monster_stats={
            name: MonsterStats(
                name=name,
                hitpoints=_float(entry.get("hitpoints"), 0.0),
                experience_bonus=_float(entry.get("experience_bonus"), 0.0),
            )
            for name, entry in _entries(config, "monster_stats")
        },
        spells=tuple(
            AttackSpell(
                name=str(entry.get("name") or ""),
                level=int(_float(entry.get("level"), 1.0)),
                experience=_float(entry.get("experience"), 0.0),
                spellbook=str(entry.get("spellbook") or ""),
            )
            for entry in config.get("spells") or ()
            if isinstance(entry, dict) and entry.get("name")
        ),
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
