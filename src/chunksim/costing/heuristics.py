"""The hand-correctable numbers behind `chunksim estimate`, and how they merge.

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
`chunksim heuristics`. The overrides file is checked in, sparse, and hand-written,
so a correction is diffable, survives a re-scrape, and travels with the repo.
`disagreements()` reports where a fresh scrape has moved away from a value
someone pinned by hand - the one thing a silent merge would hide.

**On coverage, honestly.** The money-making guides are about money, and most
ways of training a skill do not make any, so they have no guide at all.
Measured against the real export: 1,015 of 1,111 guides carry a `kph`, and they
join to **225 of the 2,657** `Primary: true` training methods and **93 of the
872** monsters with drops. Quests are the exception and come out complete,
209 of 209.

**They are no longer the only source, which is the point of the layers above.**
`remote/skill_tables.py` adds 85 Agility and Thieving methods from the wiki's
own tables, `costing/recipe_rates.py` computes a rate for anything the recipe
data reaches, and `costing/combat_xp.py` derives the five combat skills from
damage. On the benchmark map that is **943 of 1,323 reachable methods priced,
71%**, against the 310 this file's own two layers manage.

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
from typing import Any, Callable, Mapping, Sequence, TypeVar

from chunksim.model.chunkinfo import ChunkInfo
from chunksim.derive.search import normalise
from chunksim.model.summary import _mapping
from chunksim.derive.task_names import strip_task_markup
from chunksim.remote.combat import AttackSpell, MonsterStats, SpellCost
from chunksim.remote.prayer import Altar, Bone
from chunksim.remote.farming import Crop
from chunksim.remote.skill_tables import (
    COURSE_ALIASES,
    SHORTCUT_ALIASES,
    ShortcutInfo,
    GUARDIAN_SUFFIX,
    TITHE_CATEGORY,
    SkillRow,
)
from chunksim.remote.stores import ShopPrice
from chunksim.remote.wiki import Assignment, MmgRates, quest_difficulty, quest_length

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
#: nothing by default. For Mortimer that really does make skipping ruinous
#: (his cancel is 100); for Turael and Spria it makes it *free* - see
#: `RESET_MASTERS`, which is the distinction this comment used to miss.
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

#: The masters who hand out a fresh assignment for the asking, so cancelling
#: at them costs no points at all. This is the "Turael skip": they are the
#: bottom of the ladder and their whole role is to be re-askable. It is why
#: paying nothing does **not** make them expensive to skip at, which is the
#: opposite of what the note above `SLAYER_POINTS` used to conclude - a
#: master who pays nothing and charges nothing has no points economy to run
#: out of, and is the one master who can never lock you.
RESET_MASTERS: frozenset[str] = frozenset({"Turael", "Spria"})

#: Completed assignments before a master pays points at all - the wiki's own
#: rule, and the reason a skip is unaffordable long after it looks affordable
#: on the per-task average.
TASKS_BEFORE_POINTS = 5.0

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
class ComputedMethod:
    """A training method this project computed rather than read off a task.

    **For the skills the export models no training for.** Combat has no
    "Train Strength" challenge and Prayer has no "bury a bone" one, because
    neither needs a task in the game - one needs a monster and the other needs
    a bone. So their rates are computed (`costing/combat_xp.py`,
    `costing/prayer.py`) and reach `costing/training.py` through
    `Heuristics.computed` instead of through `Heuristics.training`.

    `level` is the Prayer or Attack level the method opens at, so the band walk
    can use it exactly as it uses a challenge's `Level`. `None` means "open
    from the start", which is what a combat rate is.
    """

    method: str
    xp_per_hour: float
    level: int | None = None
    match: str = "computed"
    #: The override path behind this rate, or `""` when the file describes
    #: nothing that would move it. Set by whichever module computed the
    #: method, because that is the only place that knows: combat's rate is
    #: damage against a monster's hitpoints (`monster_stats/<monster>`), and
    #: Prayer's comes off bone and altar tables that no branch describes.
    #: Inferring it downstream from `method` was tried and was wrong three
    #: separate ways - see `estimate._skill_knobs`.
    knob: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "xp_per_hour": round(self.xp_per_hour, 1),
            "level": self.level,
            "match": self.match,
        }


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


#: The wiki spells three of the export's spells differently, and no rule
#: separates the three cases: one is a disambiguated page (`(standard)`), one is
#: an abbreviation the wiki prefers (`Tele Block`), and one is a **misspelling
#: in the export** (`fenkenstain`). Same shape as `skill_tables.COURSE_ALIASES`.
SPELL_PAGE_ALIASES: dict[str, str] = {
    "ape atoll teleport": "Ape Atoll Teleport (standard)",
    "fenkenstain's castle teleport": "Fenkenstrain's Castle Teleport",
    "teleport block": "Tele Block",
}

#: The export's own prefix on a casting challenge. The join runs through the
#: task's words because a spell challenge names no object, no NPC and usually
#: no `Output` - the same reason `PLUNDER_BY_LEVEL` does.
_CAST_PREFIX = "Cast "


@dataclass(frozen=True)
class MaterialCost:
    """What one action of a method consumes, against the XP that action pays.

    The pair `material_seconds_per_xp` needs and **the export states neither
    half of** - see `costing/inputs.py`. Three things produce it: a hand entry
    in `heuristics/overrides.json`, the wiki's `infobox_spell`, and
    `Module:Skill calc/<Skill>` by way of `costing/production.py` - the last of
    which is what turned this from a per-method correction into a layer.

    **Quantities are fractional and have to be.** A rune comes in whole
    numbers, but a calculator row states an *average* action: Mahogany Homes
    costs half a steel bar and 9.7 planks a contract. Held as `int` those
    became 0 and 9 - the bar dropped silently and the planks were undercharged
    by 7%.
    """

    experience: float
    items: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"experience": self.experience, "items": dict(sorted(self.items.items()))}


def spell_materials(
    chunk_info: ChunkInfo, costs: Mapping[str, SpellCost]
) -> dict[str, MaterialCost]:
    """Join `infobox_spell`'s rune costs onto the export's `Cast ...` tasks.

    A whole-string comparison of the task's own words against the page name,
    case-insensitively, plus `SPELL_PAGE_ALIASES` - no fuzzy tier, because
    there is nothing to be fuzzy about: both vocabularies name the spell.

    Measured on the real export: **190 of its 214 `Cast` challenges join.** The
    24 that miss are all `... from a spell sack` and `... from a rune pouch`
    variants, where the runes come out of a container rather than being
    supplied - so a miss there is the right answer rather than a gap.
    """
    joined: dict[str, MaterialCost] = {}
    by_page = {name.lower(): cost for name, cost in costs.items()}
    for name in chunk_info.challenges.get("Magic") or {}:
        if not name.startswith(_CAST_PREFIX):
            continue
        spell = strip_task_markup(name).removeprefix(_CAST_PREFIX).strip().lower()
        cost = by_page.get(spell) or by_page.get(SPELL_PAGE_ALIASES.get(spell, "").lower())
        if cost is not None:
            joined[name] = MaterialCost(
                experience=cost.experience,
                items={item: float(count) for item, count in cost.items.items()},
            )
    return joined


@dataclass(frozen=True)
class Heuristics:
    """Every hand-correctable number, already merged across the two layers."""

    quests: dict[str, QuestRate] = field(default_factory=dict)
    monsters: dict[str, Rate] = field(default_factory=dict)
    superiors: dict[str, Superior] = field(default_factory=dict)
    #: Training task name -> skill -> XP per hour.
    training: dict[str, dict[str, Rate]] = field(default_factory=dict)
    #: The task names `heuristics/overrides.json` speaks about.
    #:
    #: **Carried so `training.training_options` can tell a hand figure from a
    #: scraped one**, which it otherwise cannot: an override lands in
    #: `training` looking exactly like the guide row it replaced. The rule that
    #: needs it is that a *computed* method beats a scrape for the same task
    #: and loses to a pin, which is the layering `costing/__init__.py` states
    #: and the one place it was not being applied.
    pinned: frozenset[str] = frozenset()
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
    #: `Cast ...` task -> the runes one cast eats and the XP it pays. Priced by
    #: `inputs.recipe_priced` into `material_seconds_per_xp`, **below** a
    #: recipe and above nothing: an enchant has a `{{Recipe}}` that charges the
    #: jewellery as well, and that is the larger and righter number.
    spell_costs: dict[str, MaterialCost] = field(default_factory=dict)
    #: Combat skill -> its computed rate. Filled by `inputs.priced_heuristics`
    #: **after** the kill rates are final, since it multiplies them.
    combat: dict[str, Rate] = field(default_factory=dict)
    #: Skill -> the methods this project computed for it, for the skills the
    #: export models no training task for. Combat's are written **after** the
    #: kill rates are final; Prayer's in `inputs.recipe_priced`, which is where
    #: the item walk that prices a bone already exists. Read by
    #: `costing/training.py` and by nothing else.
    computed: dict[str, tuple[ComputedMethod, ...]] = field(default_factory=dict)
    #: Training task -> seconds of gathering per XP, for the materials its
    #: published rate assumes to hand. Filled by `inputs.recipe_priced`, which
    #: is where the item walk lives; read by `costing/training.py` to rank a
    #: method on what it really costs. See `TrainingOption.effective_xp_per_hour`.
    material_seconds_per_xp: dict[str, float] = field(default_factory=dict)
    #: Every set of remains the wiki states a burial value for, best first.
    bones: tuple[Bone, ...] = ()
    #: The house altars and what each multiplies a bone by.
    altars: tuple[Altar, ...] = ()
    #: Every crop the wiki's farming calculator knows, for `costing/farming.py`.
    crops: tuple[Crop, ...] = ()
    #: Harvests a day by schedule key, overriding `DEFAULT_HARVESTS_PER_DAY`.
    farming_schedule: dict[str, float] = field(default_factory=dict)
    #: Shop -> item -> what it charges. From `remote/stores.py`.
    shop_prices: dict[str, dict[str, ShopPrice]] = field(default_factory=dict)
    #: Challenge name -> seconds to perform it once. From a guide's `kph`
    #: (actions an hour) or a recipe's tick cost; absent means unknown, and
    #: `estimate.DEFAULT_ACTION_SECONDS` stands in.
    action_seconds: dict[str, float] = field(default_factory=dict)
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
        # Shop-qualified first: see `DEFAULT_CURRENCY_PER_HOUR` on why
        # `Points` cannot have one rate.
        rate = self.currency_per_hour.get(f"{shop}:{entry.currency}")
        if rate is None:
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
        """Points cancelling a task costs.

        Zero at a `RESET_MASTERS` master: they reassign for the asking, so
        there is nothing to pay. An override still wins, as everywhere else.
        """
        if master in RESET_MASTERS:
            return self.master_skip_costs.get(master, 0.0)
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

    2,657 of them on the real export, across 21 skill categories. These are
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
    # **Overwritten by the scrape**, which reads the rooftop table's own
    # column; this is the floor if that ever fails to parse. Every course pays
    # between 8 and 18 an hour, so one figure is honest here.
    "Mark of grace": 12.0,
    # Minigame currencies, each earned at its own activity's pace: Guardians
    # of the Rift pays pearls, the Tithe Farm points, Soul Wars zeal. Stated
    # figures rather than measured ones, and tunable like the rest.
    "Abyssal pearls": 40.0,
    "Tithe": 80.0,
    "Zeal Tokens": 200.0,
    # **`Points` is not one currency.** 127 store lines are priced in
    # something called Points and they are not interchangeable - Mahogany
    # Homes, Pest Control and the Barbarian Assault shops each mean their own.
    # So a rate may be qualified by shop, `"<shop>:<currency>"`, and that is
    # checked before the bare name. Mahogany Homes pays roughly 100 an hour.
    "Mahogany Homes Reward Shop:Points": 100.0,
}

#: How this labels a shortcut rate it computed, in `Rate.match`.
#:
#: **The 18-second cycle this replaced was a guess and said so.** Its comment
#: called it "a stated target, not a measurement", chosen so the best shortcut
#: in the table reached ~5,000/hr. `costing/shortcuts.py` prices the attempt
#: instead - eight ticks, the experience its own page states, the experience a
#: *failure* pays, and the published success curve - and the answers come out
#: 3.75x higher because the old cycle was 3.75x too long.
SHORTCUT_MATCH = "modelled"

#: `Rate.source` for a shortcut rate this project computed.
SHORTCUT_SOURCE = "computed:shortcut"

#: Seconds one pickpocket attempt takes, stuns and failures included.
#: **Calibrated against the wiki's own published figure**: a Knight of Ardougne
#: pays 84.3 xp and `Thieving training` quotes 86,000 xp/hr at level 55, which
#: is 3.5s an attempt. That is the rate at the level the method *opens*, which
#: is deliberately the conservative end - the same table quotes 240,000 at 95,
#: because success rate climbs with level and one constant cannot follow it.
#: A band is priced from where it opens, so this understates the tail rather
#: than overstating the start.
PICKPOCKET_CYCLE_SECONDS = 3.5

#: Seconds one dart takes to fletch. **The third assumption in this file, and
#: the one with the clearest statement of what it is assuming.** Dart fletching
#: is one of the few actions the tick system does not gate - two clicks make a
#: whole set of ten - so no page publishes an hourly figure for it and none
#: could: the rate is however fast a person can click. `Fletching training`
#: says 2-4 sets a tick is reachable on mobile and declines to turn that into a
#: number.
#:
#: One set a tick is the modelled figure: 10 darts per 0.6s, so 60,000 darts an
#: hour. That is a fair intensive pace rather than the ceiling, the same
#: conservative end taken for a published range everywhere else here - the
#: mobile two-fingered version would be two to four times this. It puts rune
#: darts at 1,128,000 xp/hr and dragon at 1,500,000, which is what the skill
#: does at the top.
DART_CYCLE_SECONDS = 0.6 / 10.0

#: Seconds one cooked item takes, banking included. **The pace of a range is
#: the same whatever is on it** - four ticks a cook - which is why the wiki
#: publishes experience per food and no hourly figure per food: one constant
#: describes the whole skill.
#:
#: An inventory of 27 at 2.4s is 64.8s, and a bank trip is about 10s, so a
#: cycle of 28 items takes 77.2s and an hour is ~1,306 cooks. Stated rather
#: than measured, like the shortcut and dart cycles beside it, and checkable
#: against a figure it did not come from: anglerfish at 230 xp works out at
#: 300,311/hr where the community quotes ~300,000.
COOK_CYCLE_SECONDS = 77.2 / 28.0


#: Ticks to light one fire. The action is fixed; what varies is the log.
FIRE_TICKS = 4

#: Logs an inventory carries, one slot going to the tinderbox.
FIRE_LOGS_PER_TRIP = 27

#: Seconds to bank and come back for the next inventory.
FIRE_BANK_SECONDS = 10.0


def burning_rate(experience: float) -> float:
    """XP an hour burning a log worth `experience`.

    **Firemaking is the one skill where the whole method is a constant plus a
    number.** You light a fire every four ticks, twenty-seven of them to an
    inventory, then bank - so a trip is `27 * 2.4 + 10` seconds and pays
    `27 * experience`. Normal logs come out at 52,000 an hour and willow at
    117,000, which is what the skill actually does.

    Burning is not a `{{Recipe}}` and no money-making guide covers the bottom
    of the skill, so before this the only rated method was magic logs at level
    75 and **Firemaking 1 -> 99 priced at 1,738 hours**, 1,210 of them at the
    floor. It is one of the fastest skills in the game.

    The logs are assumed to hand, which is how every published Firemaking rate
    is quoted. Charging the walk to gather them would price the Woodcutting
    climb twice over on any map training both.
    """
    trip = FIRE_LOGS_PER_TRIP * FIRE_TICKS * 0.6 + FIRE_BANK_SECONDS
    return FIRE_LOGS_PER_TRIP * experience * 3600.0 / trip


#: Which tables can answer for which skill, and the cycle a row needs when the
#: table publishes experience per action rather than per hour.
#:
#: **Keyed by skill, and that is load-bearing rather than tidy.** These used to
#: be tried in one fixed order for every skill, which was harmless only while
#: no two tables shared a key space. They do: the Firemaking table is keyed on
#: the *log* (`Burn ~|magic logs|~` joins through `Items`) and so is the
#: Woodcutting one (`Chop ~|magic logs|~` joins through `Output`), so the first
#: match won and `Chop ~|magic logs|~` was priced at 394,778/hr - the rate for
#: *burning* a magic log, on a Woodcutting climb. Woodcutting 1-99 came out at
#: 35.3 hours, which is roughly a third of what the fastest method in the game
#: can do.
TABLE_KINDS: dict[str, tuple[tuple[str, float | None], ...]] = {
    # **Shortcuts are gone from here**, priced by `_add_shortcuts` instead:
    # this machinery turns one experience figure into a rate with a fixed
    # cycle, and a shortcut needs a failure experience and a success curve
    # that a `SkillRow` cannot carry.
    "Agility": (("courses", None),),
    "Thieving": (
        ("stalls", None),
        ("pickpockets", PICKPOCKET_CYCLE_SECONDS),
        ("plunder", None),
    ),
    "Firemaking": (("burning", None),),
    "Woodcutting": (("woodcutting", None),),
    "Hunter": (("hunter", None),),
    "Fishing": (("fishing", None),),
    "Mining": (("mining", None),),
    "Herblore": (("herblore", None),),
    "Fletching": (("darts", DART_CYCLE_SECONDS),),
    "Sailing": (("sailing", None),),
    "Cooking": (("cooking", COOK_CYCLE_SECONDS),),
    "Crafting": (("glass", None),),
}


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

    **Woodcutting is here for a different reason from the other three.** It is
    not a skill `{{Recipe}}` cannot describe; it is one whose guide joins reach
    4 of 53 methods, and whose own training page happens to tabulate an hourly
    figure per log. Joined on `Output` to the item, all sixteen rows landed and
    none was left over. Mining, Fishing and Hunter publish experience per
    *action* in the equivalent tables and no hourly figure at all, so they are
    deliberately absent rather than approximated from it - see
    `remote/skill_tables.parse_woodcutting`.
    """
    lookup = {
        kind: {row.name.lower(): row for row in rows} for kind, rows in tables.items()
    }
    rated: dict[str, dict[str, Rate]] = {}
    # **Walked per skill, not through `primary_training_tasks`.** That returns
    # one skill per task, so a challenge listed under several loses all but the
    # last - 50 of the export's 2,657 primary challenges are claimed by more
    # than one skill, and the three barbarian-fishing ones went to `Strength`,
    # taking their `Output` with them and silently costing Fishing its join.
    for skill in sorted(TABLE_KINDS):
        for task, challenge in sorted(_mapping(chunk_info.challenges, skill).items()):
            if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
                continue
            keys = _join_keys(challenge, task, COURSE_ALIASES)
            made = _output_keys(challenge)
            for kind, per_hour in TABLE_KINDS[skill]:
                rows_for = lookup.get(kind, {})
                offered = made if kind in OUTPUT_ONLY_KINDS else keys
                row = next((rows_for[key] for key in offered if key in rows_for), None)
                if row is None:
                    continue
                if kind == "burning":
                    value: float | None = burning_rate(row.experience)
                elif per_hour is None:
                    value = row.xp_per_hour
                else:
                    value = row.experience * 3600.0 / per_hour
                if value and value > 0:
                    rated.setdefault(task, {})[skill] = Rate(
                        value=value, source=f"wiki:{kind}", match="exact"
                    )
                break
    _add_banded(
        chunk_info, "Runecraft", tables.get("gotr") or (), rated, GOTR_SOURCE, _is_gotr
    )
    _add_banded(
        chunk_info, "Farming", tables.get("tithe") or (), rated, TITHE_SOURCE, _is_tithe
    )
    return rated


#: What `_table_rates` calls the two minigame joins, and what
#: `costing/training.py` recognises as rates that have already paid for their
#: own materials - see `_add_banded`.
GOTR_SOURCE = "wiki:gotr"
TITHE_SOURCE = "wiki:tithe"


def _is_gotr(task: str, challenge: dict[str, Any]) -> bool:
    """The twelve runes craftable inside Guardians of the Rift.

    Upstream names them `Craft a <rune> rune with guardian essence`, and that
    suffix is its own statement that the challenge *is* the minigame.
    """
    return GUARDIAN_SUFFIX in strip_task_markup(task)


def _is_tithe(task: str, challenge: dict[str, Any]) -> bool:
    """The three fruits grown inside Tithe Farm, by upstream's own category.

    Better than a name test and for the same reason `_is_gotr`'s suffix is:
    the export says so itself. One of the three is spelled `Grow a
    ~|golovanova fruit|~ alt`, which no name rule would want to know about.
    """
    categories = challenge.get("Category")
    return isinstance(categories, list) and TITHE_CATEGORY in categories


def shortcut_keys(obj: str) -> tuple[str, ...]:
    """Names a shortcut object might be filed under, most specific first.

    **The export and the wiki disambiguate the same object differently**, and
    all three rewrites here are structural rather than fuzzy:

    - `Jutting wall (Zanaris)#Medium` - upstream already writes the version as
      an anchor, which is exactly `ShortcutInfo.name`'s own form, so this is
      tried untouched first.
    - `Railing (Arceuus Library, middle level)` - upstream folds the version
      into the parenthetical where the wiki keeps a separate page section, so
      the text after the comma is dropped.
    - the bare object, for the pages that carry no parenthetical at all.

    A word-overlap join was tried and rejected: it paired "Access the
    Lighthouse basalt rocks shortcut" with `Rocks (Wyrmscraig)` and put two
    different Pollnivneach tasks on one row. Nothing here matches on a
    substring, which is what keeps this an exact join.
    """
    keys = [obj]
    base = obj.split("#", 1)[0].strip()
    if base != obj:
        keys.append(base)
    inside = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", base)
    if inside:
        head, inner = inside.group(1).strip(), inside.group(2)
        if "," in inner:
            keys.append(f"{head} ({inner.split(',')[0].strip()})")
        keys.append(head)
    return tuple(key for key in dict.fromkeys(keys) if key)


def _add_shortcuts(
    chunk_info: ChunkInfo,
    shortcuts: Sequence[ShortcutInfo],
    rated: dict[str, dict[str, Rate]],
) -> None:
    """Price every Agility shortcut challenge from `costing/shortcuts.py`.

    **Joined on the export's own `Objects`**, which names the scenery the
    challenge acts on and is the wiki's page name for it - see `shortcut_keys`
    for the three ways the two spell it differently. A challenge with no
    `Objects` cannot be joined at all and keeps nothing; measured on the
    every-rollable-chunk map that is 32 of 76, and they are the ones upstream
    names only in prose (`Access the ~|Ardougne log balance|~ shortcut`).

    Read at the level the shortcut *opens*, the conservative end taken
    everywhere else here - a curve only improves with level, so this is the
    worst rate a player who can use it at all would see.
    """
    # **Imported here rather than at module scope, to break a real cycle.**
    # `costing/shortcuts.py` needs `gathering.success_chance` and
    # `costing/gathering.py` imports this module for `Rate`, so a top-level
    # import makes `heuristics -> shortcuts -> gathering -> heuristics`. Every
    # other costing module avoids it by not being imported *by* this one; this
    # is the one layer `build_config` has to reach forward for. Deferred, not
    # conditional: it always runs.
    from chunksim.costing import shortcuts as shortcut_model

    index = {info.name.lower(): info for info in shortcuts}
    # **A versioned page under its bare name too, chosen by level.** `Rocks
    # (Vampyrium)` is one page holding a 27.5-xp slide at 78 and a 0-xp climb
    # at 61, so `parse_agility_info` names them `...#Slide` and `...#Climb` -
    # but the export names the object bare and says which it means with its
    # own `Level`. Matching on that is exact; picking the better-paying
    # version would be inventing an answer for a challenge that stated one.
    versions: dict[str, list[ShortcutInfo]] = {}
    for info in shortcuts:
        versions.setdefault(info.name.split("#", 1)[0].lower(), []).append(info)
    for task, challenge in sorted(_mapping(chunk_info.challenges, "Agility").items()):
        if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
            continue
        # **`Objects` first, then the challenge's other names.** The scenery
        # is the wiki's own page title and so is the exact key; the fallback
        # is `_join_keys`, which is what the table join used before this and
        # is how the handful upstream names only in prose still land.
        offered = [
            key
            for obj in challenge.get("Objects") or []
            if isinstance(obj, str)
            for key in shortcut_keys(obj)
        ] + _join_keys(challenge, task, COURSE_ALIASES)
        # **Hand-written names last, so they can only add a join.** An alias
        # is the residue after `shortcut_keys`' structural rewrites - see
        # `SHORTCUT_ALIASES` - and never displaces a name that already lands.
        offered += [SHORTCUT_ALIASES[key] for key in offered if key in SHORTCUT_ALIASES]
        found = next((index[key.lower()] for key in offered if key.lower() in index), None)
        if found is None:
            level = challenge.get("Level")
            found = next(
                (
                    info
                    for key in offered
                    for info in versions.get(key.lower(), ())
                    if info.level == level
                ),
                None,
            )
        if found is None or found.experience <= 0:
            continue
        rate = shortcut_model.xp_per_hour(found, found.level)
        if rate <= 0:
            continue
        rated.setdefault(task, {})["Agility"] = Rate(
            value=rate, source=SHORTCUT_SOURCE, match=SHORTCUT_MATCH
        )


def _add_banded(
    chunk_info: ChunkInfo,
    skill: str,
    bands: Sequence[SkillRow],
    rated: dict[str, dict[str, Rate]],
    source: str,
    belongs: Callable[[str, dict[str, Any]], bool],
) -> None:
    """A minigame's `level -> XP/h` curve, over the challenges that are it.

    **A minigame's rate depends on the player's level, not on which of its
    outputs you happen to get**, so its table has nothing a challenge *name*
    joins to and this cannot go through `TABLE_KINDS`' name lookup. What it
    joins on instead is upstream's own labelling - a suffix for Guardians of
    the Rift, a `Category` for Tithe Farm - and each challenge takes the band
    containing its own level, which is the rate at the level that method
    opens, the reading taken everywhere else here.

    **Below the first band there is no rate and none is invented.** The Rift
    opens at 27 where its guide tabulates from 40, so the cosmic (27) and
    chaos (35) variants keep nothing rather than borrowing the 40-50 figure.
    **Tithe Farm used to be the other example here and no longer is**: it
    opens at 34 with a figure published only from 74, which left two of its
    three fruits unrated and Farming untrainable at the minigame until 74 -
    when the game allows it from 34. `skill_tables.parse_tithe` now computes
    the two lower tiers from the minigame's own stated reward mechanics and
    spends the published figure only on the scale, so all three bands exist.
    Above the top band, nothing in the export sits in the
    Rift's 85+ bands - there is no guardian variant of a wrath rune - so those
    rows are read and never spent, understating the top rather than the
    reverse.

    **For the Rift it replaced a rate that was wrong twice over.** Those
    challenges used to join the ordinary rune's money-making guide through
    `Output`, so `Craft a chaos rune with guardian essence` was priced at the
    chaos altar's own 28,475/hr - a figure describing a dedicated altar run
    with bought essence, which is not this activity - and then charged that
    rune's essence on top, where the minigame's essence is mined inside it and
    is already in the published rate.
    """
    steps = sorted((row.level, row.xp_per_hour or 0.0) for row in bands)
    if not steps:
        return
    for task, challenge in sorted(_mapping(chunk_info.challenges, skill).items()):
        if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
            continue
        level = challenge.get("Level")
        if not isinstance(level, int) or not belongs(task, challenge):
            continue
        band = [rate for start, rate in steps if start <= level]
        if not band or not band[-1]:
            continue
        rated.setdefault(task, {})[skill] = Rate(
            value=band[-1], source=source, match="exact"
        )


#: The export's "this is the skill's version of that name" suffix, and
#: **only** that. `Black chinchompa (Hunter)` is the creature where the bare
#: name is the item; `Gem stall (Mor Ul Rek)` and `Counter (Gu'Tanoth)` are
#: *places*, and the wiki tabulates those separately with the parenthetical
#: intact - so stripping one of those would quietly fall back to a different
#: row's rate while still calling the join exact. Skill names only.
_DISAMBIGUATOR = re.compile(
    r"\s*\((?:Hunter|Prayer|Construction|Crafting|Cooking|Farming|Firemaking"
    r"|Fishing|Fletching|Herblore|Magic|Mining|Runecraft|Slayer|Smithing"
    r"|Thieving|Woodcutting|Agility|Attack|Defence|Strength|Hitpoints|Ranged"
    r"|Sailing)\)\s*$",
    re.IGNORECASE,
)


#: Kinds joined on what the challenge *makes* and on nothing else.
#: **`Items` is a join key** - Firemaking needs it, since `Burn ~|oak logs|~`
#: names the log there - and for a table of made things that is a trap: the
#: glass table's `Empty light orb` row matched `Craft a ~|light orb|~`, whose
#: `Items` are `["Empty light orb*", "Cave goblin wire*"]`. That challenge is
#: the *assembly* step, not the blowing, and it took the blowing's 122,500/hr
#: with no glass charged against it - and won the Crafting climb with it.
OUTPUT_ONLY_KINDS = frozenset({"glass"})


def _output_keys(challenge: dict[str, Any]) -> list[str]:
    """Just what the challenge makes, lowercased - `Output`, then its object
    form for Construction. The narrow half of `_join_keys`."""
    made = [
        challenge.get(field)
        for field in ("Output", "Output Object")
        if isinstance(challenge.get(field), str)
    ]
    return [
        name.split("#")[0].replace("[+]", "").replace("*", "").strip().lower()
        for name in made
        if isinstance(name, str)
    ]


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
    # `Items` for Firemaking, whose `Burn ~|oak logs|~` names the log there
    # and calls its `Output` "Ashes".
    for field in ("Objects", "NPCs", "Items"):
        keys += [clean(name) for name in challenge.get(field) or () if isinstance(name, str)]
    spelled = strip_task_markup(task).removeprefix("Access the ").strip()
    keys.append(clean(aliases.get(spelled, spelled)))
    # **The export's skill disambiguator, dropped as a *second* key.**
    # `Black chinchompa (Hunter)` is the creature where the bare name is the
    # item, and the wiki names only one of them. Appended after the exact
    # keys, never instead of them, so a name the wiki does tabulate with its
    # parenthetical (`Gem stall (Mor Ul Rek)`) still matches itself first and
    # this can only ever add a join, never redirect one.
    keys += [_DISAMBIGUATOR.sub("", key).strip() for key in list(keys)]
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
    shortcuts: Sequence[ShortcutInfo] = (),
    monster_stats: Mapping[str, MonsterStats] | None = None,
    spells: Sequence[AttackSpell] = (),
    spell_costs: Mapping[str, SpellCost] | None = None,
    shop_prices: Mapping[str, Mapping[str, ShopPrice]] | None = None,
    conversion_fees: Mapping[str, ShopPrice] | None = None,
    currency_rates: Mapping[str, float] | None = None,
    crops: Sequence[Crop] = (),
    bones: Sequence[Bone] = (),
    altars: Sequence[Altar] = (),
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

    # **A guide's `kph` is actions an hour, which is the only statement of how
    # long a skilling action takes that this project has for most methods.**
    # Kept beside the rate rather than derived from it: a rate is xp an hour
    # and dividing it back out needs the xp per action, which is a second
    # number and not always the one that joined.
    actions: dict[str, float] = {}
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
        rate_kph = guides[guide][1].kph or 0.0
        if rate_kph > 0:
            actions[task] = 3600.0 / rate_kph

    # **The Agility and Thieving tables, which no guide covers.** They are
    # joined structurally rather than by name, so they outrank a `contained`
    # money-making guide - but an *exact* guide keeps its method, on the same
    # rule that settles every other contest here: the more specific claim wins,
    # and a guide that names the method exactly is as specific as it gets.
    table_rated = _table_rates(chunk_info, skill_tables or {})
    # **After the tables, so a computed shortcut rate replaces nothing it
    # should not**: `_table_rates` no longer produces one, and the courses it
    # does produce join on a different key space entirely.
    _add_shortcuts(chunk_info, shortcuts, table_rated)
    for task, skills in table_rated.items():
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
        "spell_costs": {
            task: cost.as_dict()
            for task, cost in sorted(spell_materials(chunk_info, spell_costs or {}).items())
        },
        # **Only shops the export knows about.** The wiki lists 588 and the
        # export stocks 435; the rest are a copy of the wiki rather than a
        # config for this map.
        "shops": {
            shop: {item: entry.as_dict() for item, entry in sorted(items.items())}
            for shop, items in sorted((shop_prices or {}).items())
            if shop in chunk_info.data.get("shopItems", {})
        },
        "actions": dict(sorted(actions.items())),
        "conversions": {
            item: entry.as_dict() for item, entry in sorted((conversion_fees or {}).items())
        },
        "currencies": {**DEFAULT_CURRENCY_PER_HOUR, **(currency_rates or {})},
        "crops": [crop.as_dict() for crop in crops],
        "bones": [bone.as_dict() for bone in bones],
        "altars": [altar.as_dict() for altar in altars],
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


#: Every branch `load` reads out of a merged config - which is to say every
#: place a correction can be written in `heuristics/overrides.json` or a map's
#: own file.
#:
#: **Named here because the branch names and the `Heuristics` field names are
#: not the same**, and three of them differ: `currencies` becomes
#: `currency_per_hour`, `actions` becomes `action_seconds`, `shops` becomes
#: `shop_prices`. Anything that hands a user a path to go and edit has to
#: speak the file's names, and the first version of `estimate._Priced.knobs`
#: spoke the field's - which reads like a working pointer and is not one.
CONFIG_BRANCHES: frozenset[str] = frozenset(
    {
        "actions",
        "conversions",
        "currencies",
        "farming",
        "masters",
        "monster_stats",
        "monsters",
        "quests",
        "rarities",
        "shops",
        "slayer",
        "spell_costs",
        "superiors",
        "training",
    }
)


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
        crops=tuple(
            Crop(
                name=str(entry.get("name") or ""),
                patch=str(entry.get("patch") or ""),
                level=int(_float(entry.get("level"), 1.0)),
                experience=_float(entry.get("experience"), 0.0),
                plant_experience=_float(entry.get("plant_experience"), 0.0),
                seed=str(entry.get("seed") or ""),
                seeds_per_patch=_float(entry.get("seeds_per_patch"), 1.0),
            )
            for entry in config.get("crops") or ()
            if isinstance(entry, dict) and entry.get("name")
        ),
        farming_schedule={
            key: _float(value, 0.0)
            for key, value in _mapping(config, "farming").items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        },
        bones=tuple(
            Bone(
                name=str(entry.get("name") or ""),
                experience=_float(entry.get("experience"), 0.0),
                level=int(_float(entry.get("level"), 1.0)),
            )
            for entry in config.get("bones") or ()
            if isinstance(entry, dict) and entry.get("name")
        ),
        altars=tuple(
            Altar(
                name=str(entry.get("name") or ""),
                base=_float(entry.get("base"), 1.0),
                lit=_float(entry.get("lit"), 1.0),
            )
            for entry in config.get("altars") or ()
            if isinstance(entry, dict) and entry.get("name")
        ),
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
        action_seconds={
            task: _float(value, 0.0)
            for task, value in _mapping(config, "actions").items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
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
        spell_costs={
            task: MaterialCost(
                experience=_float(entry.get("experience"), 0.0),
                items={
                    str(item): _float(quantity, 0.0)
                    for item, quantity in _mapping(entry, "items").items()
                    if _float(quantity, 0.0) > 0
                },
            )
            for task, entry in _entries(config, "spell_costs")
            if isinstance(entry, dict) and _float(entry.get("experience"), 0.0) > 0
        },
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
