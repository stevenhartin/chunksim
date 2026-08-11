"""How long the outstanding work would take, in the roughest useful terms.

Four buckets - quests, boss drops, activity unlocks and skilling, the set
`BUCKETS` names. Every number spent here comes from `heuristics.py` and is a guess;
the only exact arithmetic is `experience.py`'s XP curve. Read both before
quoting a total.

**Scope is the active set, not everything valid.** One goal per skill
(`active_tasks.py`'s winner), the outstanding BiS picks, and the valid
uncompleted Diary/Quest/Extra tasks - about a hundred things rather than the
~2,700 valid ones. "How long to finish this chunk" is a question about what
you are actually working towards; the superseded tiers below each winner are
not work you will ever do.

**The item is the unit of work, not the task.** Tasks overlap heavily: an
abyssal whip answers a BiS pick, a Slayer collection-log entry *and* the
Abyssal Sire's own log entry, and you obtain one whip. Costing per task
charged for it three times - 1,035 of the real map's hours were that
duplication, across seven items. `ItemEstimate` therefore keys on the item and
carries the tasks it satisfies alongside. Quests are the exception and stay
per-task, a quest not being something you can get twice over.

**Items from one source are earned in parallel, and the total says so.**
Killing abyssal demons for a dagger at 1/32,000 hands you the head at 1/6,000
long before you finish, so the pair costs the dagger's 533 hours and not their
633. Every `ItemEstimate` therefore records the `source` it comes off, and
`EstimateResult.buckets` takes the **longest** item per source rather than the
sum - a superior counting as its base monster, since that is what you are
actually killing. This was the estimate's largest single overstatement:
correcting it took the real map from 10,673 hours to 3,849. The per-item hours
are untouched and still printed, because "how long for this one thing" and
"how long for all of it" are different questions.

**The item walk.** A task needs items; an item has routes (`search.py`'s
`WorldIndex`, the whole-world index of all five); a route has a rate. The
cheapest route wins and its cost is `(1 / p) / kills_per_hour`. Rates come
from `drops`/`skillItems` and are parsed by `rates.parse_ratio`, falling back
to `Heuristics.rarity` for the ~1,200 entries the export words rather than
numbers (`Always`, `Common`, ...). Drop tables compose multiplicatively, the
same expansion `sources.py` does for the unlocked case.

**Three gates stand between a drop and its price, and skipping any of them
prices a game nobody is playing.**

1. *The provider has to be reachable.* `WorldIndex` spans the whole world,
   so without a check the walk costs every drop in OSRS. `SourceIndex`'s
   monsters, objects *and* NPCs are the answer - all placed in an unlocked
   chunk and past their `taskUnlocks` gates. `Colossal Hydra` is what taught
   the check: a `skillItems.Slayer` activity with 43 drops and no chunk
   anywhere, priced as though you could go and fight one. `Larran's big
   chest` taught the breadth of it: a `skillItems` activity is only
   *usually* a monster, and a monsters-only gate refused its 34 drops.
2. *A task-gated monster has to be assigned.* `taskUnlocks['Monsters']` names
   a `<X> task` Nonskill requirement per location - Grotesque Guardians want
   a gargoyle task - and being sent one costs far more than the fighting
   does. `task_gated_monsters` reads them; `_task_hours` prices the wait. If
   no reachable master can assign it, the route has **no** price rather than
   a free one.
3. *The master has to be reachable too.* That gate lives in `slayer.py`, and
   its absence had this module quoting Duradel on a map holding none of him.

**Superiors are the exception that proves the first gate.** A superior slayer
monster is never in a chunk - it replaces a normal counterpart on death, on
task, at 1/200 - so gate 1 correctly refuses it and `_superior_hours` then
prices it through its base monster, which carries gates 2 and 3 itself.

**The four items superiors *share* are priced differently again.** Imbued
heart, eternal gem and the two battlestaves sit on `SuperiorDropTable+`,
which every superior rolls, so they are one source and not thirty-one: you
never hunt a particular superior, you take a master's assignments and price
whatever turns up. `slayer.superior_rolls_per_hour` aggregates the rate over
everything that master can send you to - Krystilia's abyssal demons, jellies
and nechryaels feeding one pool - and does it **per master**, because you
serve one at a time and combining two would describe nobody's game. A
superior's *own* drops stay attributed to its base monster.

**Two deliberate limits, both of which would otherwise bite.**

- *An item made from other items recurses*, and can cycle: A is the output of
  a challenge needing B, which needs A. Bounded by `_MAX_DEPTH` and a visited
  set, and anything hitting either is reported `unpriced` rather than guessed
  at - the posture `challenges.py` takes with `unsupported`.
- *A task can want a kill rather than a drop.* Several diary tasks are of
  that shape - "kill an abyssal demon in the Slayer Tower" - with `Monsters`
  and no `Items`. They cost one kill, attributed to the monster, so the
  per-source clamp folds them into any grind already happening there. Only a
  BiS task, which has no challenge at all, has its item read out of its
  `~|...|~` span; doing that to a challenge produced a request for an item
  called `Morytania Diary#Elite`.
- *Quantity is ignored.* Drop quantities are strings this project has never
  parsed (`"25-30 (noted)"`, `"1,3"`, `"104-194"`), and every task here is
  "obtain one", so the first drop ends it. A task wanting fifty of something
  is therefore under-costed; none of the active-set tasks currently are.

**The skilling bucket, and the honest gap in it.** Time to a level is
`xp_between(current, target) / rate`, where the rate is the fastest *reachable*
`Primary: true` method - reachable meaning present in `ChallengeResult.valid`,
so an unlocked chunk adding a faster method shortens the estimate. Slayer
takes `slayer.best_master` instead, because its rate is a distribution rather
than a method you pick.

`current` is the problem, and it reaches further than this bucket. **The map
records no skill levels.** `maxSkill` is a *cap* the player declared, not a
level they hold; `passiveSkill` is what is reachable *without* a training
method (`worker.js:5114`) and names five skills on the real map. Neither is
"what I am now".

`infer_levels` reads it out of the ledger instead: **a completed challenge is
proof of its own level requirement.** `Buy the ~|Defence cape|~` is not
something a player under 99 Defence has ticked off, so the highest `Level`
among a skill's completions is a floor on that skill. On the real map that
gives 22 skills real numbers - Defence 99, Cooking 99, Mining 99, Attack 75 -
where `passiveSkill` alone gave five.

It is still a floor. A player at 99 Attack who has ticked nothing above 75
reads as 75, and every skill row prints the level it assumed so a wrong one
is visible. `levels` in `heuristics/overrides.json` replaces it outright.

**`goal_levels` raises that floor to where the chunk is going.** An active
goal carries the level it needs, and finishing the chunk means reaching it -
Slayer here is inferred at 45 and aiming at 92. What a slayer master offers
is judged at *those* levels, because that list is the one that holds for the
tail of the chunk and the tail is where the time goes. The XP still to earn
is measured from the floor up, which is the whole point of the climb.

`slayer.py` reads these numbers to decide what a master will offer, and that
is where they matter most: Vannaka's basilisks want Defence 20, which
`passiveSkill` could not confirm, so the task read as "never offered" - free -
instead of "offered and unreachable", which costs a 30-point skip.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from fray_claude.costing.levels import (
    goal_levels,
    infer_levels,
    reachable_providers,
    task_gated_monsters,
    _levels,
)
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.model.experience import (
    MAX_LEVEL,
    level_for_xp,
    xp_between,
    xp_for_level,
)
from fray_claude.costing.combat_xp import COMBAT_SKILLS, hitpoints_credit, slayer_credit
from fray_claude.costing.farming import (
    DEFAULT_HARVESTS_PER_DAY,
    FarmingPlan,
    plan_for as farming_plan,
)
from fray_claude.costing.training import (
    LampGrant,
    TrainingBand,
    TrainingOption,
    quest_xp_grants,
    training_bands,
    training_options,
)
from fray_claude.costing.heuristics import (
    TITHE_SOURCE,
    Heuristics,
    Superior,
    activity_name,
)
from fray_claude.derive.pipeline import Derived, MapState
from fray_claude.model.rates import parse_quantity, parse_ratio
from fray_claude.derive.search import WorldIndex, normalise
from fray_claude.costing.slayer import (
    MasterRate,
    best_master,
    master_rates,
    superior_rolls_per_hour,
    superior_spawns_per_hour,
    superior_table_items,
)
from fray_claude.model.summary import _mapping

#: The buckets, in the order `fray estimate` reports them.
BUCKETS = ("quests", "boss drops", "activities", "skilling")

#: How far the item walk will chase "made from" chains before giving up. Three
#: is past every real case measured (an imbued ring is output <- item <-
#: drop); beyond it the answer is guesswork stacked on guesswork.
_MAX_DEPTH = 3

#: Routes that cost no meaningful time once reachable: a shop purchase and a
#: ground spawn are both "walk there and take it".
_FREE_ROUTES = frozenset({"shop", "spawn"})

#: Skills this project will not put an hours figure on, whatever the export
#: says about training them. **A refusal, not a gap in the data** - and the
#: only entry is `Sailing`, which was new enough that no money-making guide
#: covered it, `{{Recipe}}` had no rows for it and no wiki table published a
#: rate for any of its 27 primary methods. So every one of them sat at the
#: 1,000/hr floor and the climb read as 13,034 hours, which is not a
#: conservative estimate but a made-up one wearing a number.
#:
#: **Membership is now a *precondition*, not the decision.** It used to be
#: both, which made it a standing claim about the world that nothing rechecked
#: - and the world has since moved: `Sailing training` now publishes figures
#: for barracuda trials, courier tasks, salvaging and sea charting. So a skill
#: named here is refused only while **no reachable method of it has a real
#: rate**, which `training_options` already answers by dropping every
#: `default`. The day one of those rates is joined, the skill prices itself
#: and needs no edit here.
#:
#: The pairing matters in both directions. Without the set, "nothing is rated"
#: would refuse any skill the scrape simply has not reached yet, where the
#: floor is the honest answer and an improving scrape will fix it. Without the
#: recheck, a skill stays refused after the numbers arrive. Remove a skill from
#: here when its rates are not merely published but *joined* - until then the
#: entry costs nothing and stops a 13,034-hour fiction.
UNRATED_SKILLS = frozenset({"Sailing"})

#: Seconds to reach a shop and get back to where the work happens. **A rough
#: fixed figure, not a measurement** - the export has no geography to compute
#: one from, and a bank-to-shop-to-bank run is thirty seconds either side of
#: plausible for most of the map.
SHOP_TRIP_SECONDS = 30.0

#: Seconds one *action* takes when nothing says otherwise. **Performing a
#: conversion used to be free**, so a chain bottoming out in a gathering action
#: with no inputs cost nothing at all: `Plank <- Process logs <- Logs <- Cut
#: logs from roots <- (nothing)`. Four ticks is an ordinary skilling action and
#: is what stands in until a guide's `kph` or a recipe's tick cost says better.
DEFAULT_ACTION_SECONDS = 4 * 0.6

#: Seconds to pick one item off the ground. One tick, which caps collection
#: at 6,000 an hour before anything else is considered.
SPAWN_PICKUP_SECONDS = 0.6

#: How often you can be standing at a fresh spawn, per hour. **A ground item
#: does not respawn while you wait for it** - the cheap way to collect is to
#: hop worlds, which costs roughly ten seconds, so six hops a minute is the
#: realistic ceiling. Multiplied by how many of the item sit at that spawn.
SPAWN_HOPS_PER_HOUR = 360.0

#: Items one trip can carry back. An inventory is 28 slots and one holds what
#: you are working with, so a purchase run brings 27.
SHOP_TRIP_ITEMS = 27.0


@dataclass(frozen=True)
class TaskEstimate:
    """One task's cost, and the single most expensive thing behind it."""

    task: str
    bucket: str
    hours: float
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "bucket": self.bucket,
            "hours": self.hours,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class _Priced:
    """A costed route to one item: how long, why, and off what."""

    hours: float
    detail: str
    #: The thing you repeatedly kill or do to get it. Items sharing a source
    #: are earned *at the same time*, which is what `EstimateResult.buckets`
    #: uses to stop adding them together.
    source: str


@dataclass(frozen=True)
class ItemEstimate:
    """One item's cost, and every active task that wants it.

    The unit of the boss-drop and activity buckets. Tasks overlap heavily -
    an abyssal whip is a BiS pick *and* two separate log entries - and the
    work of getting one is done once, so the cost is counted once.
    """

    item: str
    bucket: str
    hours: float
    detail: str = ""
    #: What you kill or do for it. Shared sources are worked in parallel.
    source: str = ""
    tasks: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "item": self.item,
            "bucket": self.bucket,
            "hours": self.hours,
            "detail": self.detail,
            "source": self.source,
            "tasks": list(self.tasks),
        }


@dataclass(frozen=True)
class SkillEstimate:
    """One skill's climb to its current goal."""

    skill: str
    goal: str
    current_level: int
    target_level: int
    xp: int
    xp_per_hour: float
    method: str
    hours: float
    #: True when the *whole* climb is at the un-joined floor. A climb that is
    #: only part floored reports `floor_xp` instead - see `_skill_estimate`.
    defaulted: bool = False
    #: The climb split where the rate changes, in order. Empty for a skill
    #: already at its goal.
    bands: tuple[TrainingBand, ...] = ()
    #: How much of `xp` is priced at the floor rather than at a measured rate.
    #: Defaulted so every existing constructor stays valid.
    floor_xp: int = 0
    #: XP this climb is spared by quests the map can finish. Already removed
    #: from `xp`, so it is a note about where the head start came from.
    xp_from_quests: int = 0
    #: Calendar days this climb takes, where that is the real constraint
    #: rather than the hours. Farming only - see `costing/farming.py`.
    days: float = 0.0
    #: XP this climb is spared because the *other* combat skills earn it on
    #: the way. Hitpoints only, and in practice most of the climb - see
    #: `combat_xp.hitpoints_credit`. Already removed from `xp`, like the
    #: quest grant beside it.
    xp_from_combat: float = 0.0
    #: The level the quest XP leaves you at, which is where the climb starts.
    #: Equal to `current_level` when no quest pays into this skill.
    effective_level: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "goal": self.goal,
            "current_level": self.current_level,
            "target_level": self.target_level,
            "xp": self.xp,
            "xp_per_hour": self.xp_per_hour,
            "method": self.method,
            "hours": self.hours,
            "defaulted": self.defaulted,
            "floor_xp": self.floor_xp,
            "xp_from_quests": self.xp_from_quests,
            "xp_from_combat": round(self.xp_from_combat, 1),
            "days": round(self.days, 1),
            "xp_from_combat": self.xp_from_combat,
            "effective_level": self.effective_level,
            "bands": [band.as_dict() for band in self.bands],
        }


@dataclass(frozen=True)
class UnpricedSkill:
    """A skill goal this project refuses to put a number on, and why.

    **Not zero, and not the floor.** `Attack`, `Defence`, `Hitpoints` and
    `Ranged` carry no `Primary: true` challenge anywhere in the export - there
    is no "train Attack" entry, because you train it by fighting - so the old
    code divided by a zero rate and reported the climb as **free**, and pricing
    it at the floor instead would put 288 hours on five levels of Attack, wrong
    by two orders of magnitude and in the headline.

    Refusing is the posture this module already takes for an item it cannot
    route (`unpriced`), and it keeps the same total while making it honest.
    """

    skill: str
    goal: str
    current_level: int
    target_level: int
    xp: int
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "goal": self.goal,
            "current_level": self.current_level,
            "target_level": self.target_level,
            "xp": self.xp,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class EstimateResult:
    """Per-bucket hours, the detail behind them, and what could not be priced."""

    #: Quest-bucket entries. Quests are the one thing costed per *task*, since
    #: a quest is not an item you can get twice over.
    tasks: tuple[TaskEstimate, ...] = ()
    #: The boss-drop and activity buckets, one entry per unique item.
    items: tuple[ItemEstimate, ...] = ()
    skills: tuple[SkillEstimate, ...] = ()
    #: The master the Slayer estimate used - the fastest reachable one.
    slayer: MasterRate | None = None
    #: **Every** reachable master, fastest first. The estimate has to pick
    #: one, but XP rate is not the only reason to choose: coverage, how much
    #: of the list is unpriced, and how often supers turn up all differ, and
    #: a player may reasonably want a slower master for any of them. Shown in
    #: full rather than collapsed to the winner.
    slayer_masters: tuple[MasterRate, ...] = ()
    #: `master -> superior *spawns* per hour`. What a player recognises,
    #: and two orders of magnitude commoner than a shared-table roll.
    superior_spawns: dict[str, float] = field(default_factory=dict)
    #: `master -> superior-table rolls per hour`, for the same comparison.
    #: Computed at the levels the player has *declared they can reach*, not
    #: the ones they hold, because that is what the item prices rest on - the
    #: skilling bucket is already paying for the climb. At a passive floor of
    #: 45 every superior-bearing task is level-gated out and this would read
    #: zero everywhere, which would contradict the hours printed beside it.
    superior_rolls: dict[str, float] = field(default_factory=dict)
    #: Items with no priceable route - the honest coverage figure.
    unpriced: tuple[str, ...] = ()
    #: Skill goals with no trainable method anywhere in the export. Reported
    #: rather than priced; see `UnpricedSkill`.
    unpriced_skills: tuple[UnpricedSkill, ...] = ()
    #: Quest XP that may go to one of several skills, left unspent. See
    #: `training.LampGrant`.
    unallocated_quest_xp: tuple[LampGrant, ...] = ()

    @property
    def buckets(self) -> dict[str, float]:
        """Hours per bucket, **clamped per source**.

        Items from the same source are earned at the same time, not one after
        another: the hours that get you an abyssal dagger at 1/32,000 have
        long since got you the abyssal head at 1/6,000, so the pair costs the
        dagger's time and not their sum. Summing them was the estimate's
        largest single overstatement - on the real map it turned a 2,400-hour
        Abyssal demon grind into nearly 4,000.

        The per-item hours are untouched and still reported: "how long for
        this one thing" and "how long for all of it" are different questions
        and both are worth answering.
        """
        totals = {bucket: 0.0 for bucket in BUCKETS}
        for task in self.tasks:
            totals[task.bucket] = totals.get(task.bucket, 0.0) + task.hours
        for (bucket, _), hours in self.by_source().items():
            totals[bucket] = totals.get(bucket, 0.0) + hours
        totals["skilling"] += sum(skill.hours for skill in self.skills)
        return totals

    def by_source(self) -> dict[tuple[str, str], float]:
        """`(bucket, source) -> hours`, the longest item that source owes."""
        longest: dict[tuple[str, str], float] = {}
        for item in self.items:
            key = (item.bucket, item.source or item.item)
            longest[key] = max(longest.get(key, 0.0), item.hours)
        return longest

    def sources_in(self, bucket: str) -> list[tuple[str, float, list[ItemEstimate]]]:
        """Each source in `bucket`: what it costs, and what it yields."""
        grouped: dict[str, list[ItemEstimate]] = {}
        for item in self.items_in(bucket):
            grouped.setdefault(item.source or item.item, []).append(item)
        return sorted(
            (
                (source, max(item.hours for item in items), items)
                for source, items in grouped.items()
            ),
            key=lambda row: (-row[1], row[0]),
        )

    @property
    def total_hours(self) -> float:
        return sum(self.buckets.values())

    def items_in(self, bucket: str) -> list[ItemEstimate]:
        return sorted(
            (item for item in self.items if item.bucket == bucket),
            key=lambda item: (-item.hours, item.item),
        )

    def in_bucket(self, bucket: str) -> list[TaskEstimate]:
        return sorted(
            (task for task in self.tasks if task.bucket == bucket),
            key=lambda task: (-task.hours, task.task),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "buckets": self.buckets,
            "total_hours": self.total_hours,
            "tasks": [task.as_dict() for task in self.tasks],
            "items": [item.as_dict() for item in self.items],
            "by_source": {
                f"{bucket}/{source}": hours
                for (bucket, source), hours in self.by_source().items()
            },
            "skills": [skill.as_dict() for skill in self.skills],
            "slayer": self.slayer.as_dict() if self.slayer else None,
            "slayer_masters": [
                {
                    **rate.as_dict(),
                    "superior_spawns_per_hour": self.superior_spawns.get(rate.master, 0.0),
                    "superior_rolls_per_hour": self.superior_rolls.get(rate.master, 0.0),
                }
                for rate in self.slayer_masters
            ],
            "unpriced": list(self.unpriced),
            "unpriced_skills": [skill.as_dict() for skill in self.unpriced_skills],
            "unallocated_quest_xp": [lamp.as_dict() for lamp in self.unallocated_quest_xp],
        }


@dataclass(frozen=True)
class _Walk:
    """Everything the item walk reads, bundled so it isn't passed six-deep."""

    chunk_info: ChunkInfo
    world: WorldIndex
    heuristics: Heuristics
    tables: dict[str, Any] = field(default_factory=dict)
    #: Everything reachable on this map that can *provide* an item: the
    #: monsters, objects and NPCs of `SourceIndex`, all past their
    #: `taskUnlocks` gates. Not monsters alone - a `skillItems` activity is
    #: only usually a monster (`search.py`), and `Larran's big chest` is an
    #: Object, so a monsters-only gate refused its 34 drops outright.
    available: frozenset[str] = frozenset()
    #: Items this map can actually get hold of - `SourceIndex.items`, which is
    #: already gated on `taskUnlocks['Shops']`, the minigame rule and the
    #: backlog. A shop or spawn route is only free if it is *here*.
    reachable_items: frozenset[str] = frozenset()
    #: Monster -> the slayer task you must be on to fight it, where one is
    #: required. Derived from `taskUnlocks`; see `task_gated_monsters`.
    task_gates: dict[str, str] = field(default_factory=dict)
    #: `codeItems.itemsPlus`: `Air rune[+]` -> the four runes that satisfy it.
    #: **Upstream's "or anything equivalent" marker**, and the item walk never
    #: read it - so a task wanting `Air rune[+]` found no item by that name and
    #: went unpriced, while `Air rune` itself priced in 2.4 seconds.
    item_families: dict[str, list[str]] = field(default_factory=dict)
    #: The shared superior drop table: item -> its share of one roll.
    superior_table: dict[str, float] = field(default_factory=dict)
    #: `master -> superior-table rolls per hour` while serving that master.
    superior_rolls: dict[str, float] = field(default_factory=dict)
    #: Every master's task table. A gated kill is priced against whichever
    #: master can assign the task *soonest*, not the one with the best XP
    #: rate: different masters assign different things, and Krystilia being
    #: fastest overall is no help at all when the task you need is gargoyles.
    masters: tuple[MasterRate, ...] = ()
    #: Lowercased item name -> the export's own spelling. Task names carry
    #: the item in lower case inside their `~|...|~` span
    #: (`Obtain a ~|granite ring (i)|~`) while `item_sources` is keyed by the
    #: item itself (`Granite ring (i)`), so a case-sensitive lookup silently
    #: fails to price every task reached through its span.
    by_lower: dict[str, str] = field(default_factory=dict)

    @property
    def reachable_lower(self) -> frozenset[str]:
        return frozenset(name.lower() for name in self.reachable_items)

    def resolve(self, item: str) -> str:
        """The export's spelling of `item`, if it has one."""
        return self.by_lower.get(item.strip().lower(), item)


def _probability(raw: str, heuristics: Heuristics) -> float | None:
    """A drop-rate string as a probability, or `None` if it says nothing.

    `rates.parse_ratio` returns `nan` for every non-fraction, which is 1,197
    of the export's 12,939 rate entries; the worded ones resolve through the
    config, and `Varies`/`Unknown` stay `None` on purpose.
    """
    ratio = parse_ratio(raw.partition("@")[0])
    if not math.isnan(ratio):
        return ratio if 0 < ratio <= 1 else None
    return heuristics.rarity(raw)


def _drop_rates(walk: _Walk, monster: str, item: str) -> tuple[float, float] | None:
    """`(chance, yield)` for one kill of `monster`: how often `item` drops, and
    how many arrive when it does.

    **Two numbers because there are two questions.** Obtaining an item at all
    is one roll of the table however big the stack - Hydra's dragon knives are
    1/10,000 whether the drop is 200 or 400 - so a *goal* is priced on
    `chance`. Accumulating a hundred of something is priced on the expected
    yield, `chance * stack`, because the stack really does amortise. Using
    either number for the other question is wrong by the stack size, which the
    export puts as high as 45.

    A range is its mean and a note is the same item; see `rates.parse_quantity`
    for both, and `_kill_hours` for how the two combine.

    Several rows can offer the same item, so the best of each wins.
    """
    best: tuple[float, float] | None = None
    for source in (walk.chunk_info.drops, *_skill_item_tables(walk)):
        rows = _mapping(source, monster)
        for name, quantities in rows.items():
            if not isinstance(quantities, dict):
                continue
            direct = name == item
            table = walk.tables.get(name) if not direct else None
            if not direct and not isinstance(table, dict):
                continue
            for count, raw in quantities.items():
                chance = _probability(str(raw), walk.heuristics)
                if chance is None:
                    continue
                if not direct:
                    within = _table_probability(table, item, walk.heuristics)
                    if within is None:
                        continue
                    chance *= within
                stack = parse_quantity(str(count)) or 1.0
                found = (chance, chance * stack)
                best = found if best is None else (
                    max(best[0], found[0]), max(best[1], found[1])
                )
    return best


def _skill_item_tables(walk: _Walk) -> list[dict[str, Any]]:
    """`skillItems` flattened to the same `{activity: {item: {qty: rate}}}`."""
    return [
        _mapping(walk.chunk_info.skill_items, skill)
        for skill in walk.chunk_info.skill_items
    ]


def _table_probability(
    table: dict[str, Any] | None, item: str, heuristics: Heuristics
) -> float | None:
    if not isinstance(table, dict):
        return None
    raw = table.get(item)
    return _probability(str(raw), heuristics) if raw is not None else None


def _item_hours(
    walk: _Walk,
    item: str,
    *,
    quantity: float = 1.0,
    amortise: bool = False,
    depth: int = 0,
    seen: frozenset[str] = frozenset(),
) -> _Priced | None:
    """Cheapest route to `quantity` of `item`, as `(hours, why)`, or `None`.

    `None` is "no route this module can price", which the caller reports as
    unpriced rather than dropping - an estimate that silently skips its
    expensive half is worse than one that admits a gap.

    **`quantity` defaults to one, which is every goal.** A task wants an
    abyssal whip, not forty; the parameter exists for *materials*, where a
    recipe consuming two guam leaves an action is asking a different question
    and a stacked drop amortises across it. See `_drop_rates`.
    """
    item = walk.resolve(item)
    if item in seen or depth > _MAX_DEPTH:
        return None

    # **`[+]` means "or anything equivalent", so take the cheapest.** The
    # family is upstream's own list; picking the best of it is the same
    # reading `_required_kills` already takes for `monstersPlus`, which stops
    # at the first *reachable* member. Done before `resolve`, since the family
    # key is not an item name and will not resolve to one.
    members = walk.item_families.get(item)
    if members:
        cheapest: _Priced | None = None
        for member in members:
            if not isinstance(member, str) or member in seen:
                continue
            priced = _item_hours(
                walk,
                member,
                quantity=quantity,
                amortise=amortise,
                depth=depth + 1,
                seen=seen | {item},
            )
            if priced is not None and (cheapest is None or priced.hours < cheapest.hours):
                cheapest = priced
        return cheapest

    # **Currency is earned, not fetched.** `Coins` and `Tokkul` are ordinary
    # items to the export - both have ground spawns - so the walk found one
    # lying about and priced ten million of them at nothing. What money costs
    # is the time to earn it, at its own rate, and that is true however you
    # come by it. Checked before the routes so no spawn can undercut it.
    earned = walk.heuristics.currency_per_hour.get(item)
    if earned is not None:
        if earned <= 0:
            return None
        return _Priced(quantity / earned, f"earn {quantity:,.0f} {item}", f"currency:{item}")

    shared = _superior_table_hours(walk, item, quantity)
    if shared is not None:
        return shared

    best: _Priced | None = None
    for source in walk.world.item_sources.get(item, ()):
        priced = _route_hours(
            walk, item, source.route, source.name, depth, seen | {item}, quantity, amortise
        )
        if priced is not None and (best is None or priced.hours < best.hours):
            best = priced
    return best


def _superior_table_hours(
    walk: _Walk, item: str, quantity: float = 1.0
) -> _Priced | None:
    """Price one of the four items every superior shares, or `None`.

    **Superiors are one source, not thirty-one.** The table is rolled by any
    superior, and you never hunt a particular one - you take a master's
    assignments and whatever supers turn up, turn up. So the rate is the
    master's *aggregate*: Krystilia's abyssal demons, jellies and nechryaels
    all feed the same pool. Pricing this against a single base monster asks
    which superior you are farming, which is not a question the game poses.

    Per master, because you serve one at a time - combining two masters'
    pools would describe nobody's game. The best of them wins, as everywhere
    else here.
    """
    share = walk.superior_table.get(item)
    if not share:
        return None

    best: tuple[float, str] | None = None
    for master, rolls in walk.superior_rolls.items():
        if rolls <= 0:
            continue
        hours = (max(1.0, quantity) / share) / rolls
        if best is None or hours < best[0]:
            best = (hours, master)
    if best is None:
        return None

    hours, master = best
    return _Priced(
        hours,
        f"superior table under {master},"
        f" {max(1.0, quantity) / share:,.1f} rolls at {_rolls_label(walk, master)}",
        f"superiors:{master}",
    )


def _rolls_label(walk: _Walk, master: str) -> str:
    """How often the *shared table* comes up - far rarer than a superior."""
    rolls = walk.superior_rolls.get(master, 0.0)
    return f"1 table roll per {1 / rolls:,.0f}h" if rolls > 0 else "no supers"


def _route_hours(
    walk: _Walk,
    item: str,
    route: str,
    provider: str,
    depth: int,
    seen: frozenset[str],
    quantity: float = 1.0,
    amortise: bool = False,
) -> _Priced | None:
    if route in _FREE_ROUTES:
        # **A shop is only free if you can walk into it.** `WorldIndex` spans
        # the whole world, so without this any item stocked by any of the
        # export's 435 shops - or lying on the ground anywhere - priced at zero
        # and won the `min` outright. Every *kill* route was already hard-gated
        # on reachability (`_kill_hours`: "availability is not negotiable"), so
        # this was the one route that could reach off the map.
        #
        # It barely moved the item bucket - 4 of 207 items on the real map -
        # but it is decisive for anything priced *per action*: eye of newt,
        # grimy guam leaf and snapdragon are all stocked or spawned somewhere,
        # so an ingredient walk without this gate concludes that every recipe's
        # inputs are instant.
        if item.lower() not in walk.reachable_lower:
            return None
        if route == "spawn":
            # **A ground spawn is cheap, not free.** Picking one up is a tick,
            # which alone caps collection at 6,000 an hour - and the item does
            # not come back while you stand there, so the real limit is how
            # fast you can reach a fresh one. Hopping worlds is the usual
            # answer at roughly ten seconds a hop, and each hop yields however
            # many of the item lie at that spawn.
            #
            # Left free, a `Spawn` of two planks priced a ten-plank wooden
            # fence at nothing and made it 296,471 Construction xp/hr.
            at_spawn = _mapping(
                _mapping(walk.chunk_info.data, "chunks").get(provider, {}), "Spawn"
            ).get(item)
            count = float(at_spawn) if isinstance(at_spawn, (int, float)) else 1.0
            per_hour = min(
                3600.0 / SPAWN_PICKUP_SECONDS, SPAWN_HOPS_PER_HOUR * max(1.0, count)
            )
            hours = quantity / per_hour if per_hour > 0 else 0.0
            return _Priced(
                hours,
                f"{route}: {provider}"
                + (f", {quantity:,.0f}x" if quantity > 1 else "")
                + f" ({count:g} per hop, {per_hour:,.0f}/hr)",
                f"{route}:{provider}",
            )

        # **Buying is instant; the money is not.** A shop route costs however
        # long it takes to earn the price, at the currency's own rate - which
        # is what stops a Construction build reading `Coins x 10,000,000` from
        # being the fastest training in the game. A price the wiki does not
        # list, or one charged in a currency with no rate, is *no route* rather
        # than a free one.
        seconds = walk.heuristics.shop_seconds(provider, item)
        if seconds is None:
            return None
        # **The money is not the only cost; the walk there is.** A shop run
        # brings back one inventory, so buying is priced per *trip* as well as
        # per coin. `amortise` is the difference between the two questions the
        # walk is asked: a goal wants one item and pays for the whole trip,
        # while a recipe wants two planks *per action* and pays its share of a
        # trip that also supplied the next dozen actions. Charging a full trip
        # per action put thirty seconds on every cast of every spell.
        trips = quantity / SHOP_TRIP_ITEMS
        if not amortise:
            trips = max(1.0, math.ceil(trips))
        travel = trips * SHOP_TRIP_SECONDS
        hours = (seconds * quantity + travel) / 3600.0
        return _Priced(
            hours,
            f"{route}: {provider}"
            + (f", {quantity:,.0f}x" if quantity > 1 else "")
            + f" ({seconds * quantity:,.0f}s earning + {travel:,.0f}s travel)",
            f"{route}:{provider}",
        )

    if route.startswith("task:"):
        # Made rather than found: the cost is its inputs, recursively.
        challenge = _mapping(walk.chunk_info.challenges, route.removeprefix("task:")).get(
            provider
        )
        if not isinstance(challenge, dict):
            return None
        total = 0.0
        for required in challenge.get("Items") or ():
            if not isinstance(required, str):
                continue
            priced = _item_hours(
                walk,
                required.replace("*", ""),
                quantity=quantity,
                amortise=amortise,
                depth=depth + 1,
                seen=seen,
            )
            if priced is None:
                return None
            total += priced.hours
        # **The conversion itself can cost money.** Upstream models the
        # sawmill as a swap of logs for planks and records no price, so a
        # mahogany plank came out costing exactly one mahogany log. The fee is
        # `remote/stores.py`'s and is zero for every conversion that has none.
        # **And performing it costs time.** A guide's `kph` or a recipe's tick
        # cost where either is known, and four ticks where neither is.
        total += (
            walk.heuristics.action_seconds.get(provider, DEFAULT_ACTION_SECONDS)
            * quantity
            / 3600.0
        )
        made = challenge.get("Output")
        if isinstance(made, str):
            fee = walk.heuristics.conversion_seconds(made) * quantity / 3600.0
            if not math.isfinite(fee):
                return None
            total += fee
        return _Priced(total, f"make: {provider}", f"make:{provider}")

    return _kill_hours(walk, provider, item, quantity)


def _kill_hours(
    walk: _Walk, provider: str, item: str, quantity: float = 1.0
) -> _Priced | None:
    """Hours of killing `provider` for `quantity` of `item`, gates included.

    **Availability is checked first and is not negotiable.** `provider` has to
    be a monster this map can actually reach - placed in an unlocked chunk and
    past its `taskUnlocks` gates. Without that the walk prices the whole game:
    `Colossal Hydra` is a `skillItems.Slayer` activity with 43 drops and no
    chunk anywhere (it is a superior, spawned from Alchemical Hydra), and it
    was being costed as though you could go and fight one.
    """
    if provider not in walk.available:
        superior = walk.heuristics.superiors.get(provider)
        return _superior_hours(walk, superior, item, quantity) if superior else None

    rates = _drop_rates(walk, provider, item)
    if rates is None or rates[0] <= 0 or rates[1] <= 0:
        return None
    chance, per_kill = rates
    rate = walk.heuristics.kills_per_hour(provider)
    if rate.value <= 0:
        return None

    # **Both bounds, and the binding one wins.** You cannot see the drop in
    # fewer than `1/chance` kills however large the stack, and once you want
    # more than one stack it is `quantity/yield`. At `quantity == 1` the first
    # always binds, which is what keeps a goal priced on the rate alone.
    kills = max(1 / chance, quantity / per_kill)
    detail = f"{provider} at 1/{1 / chance:,.0f}, {rate.value:g}/hr"
    if kills > 1 / chance:
        detail = f"{provider} x{kills:,.0f} kills, {rate.value:g}/hr"

    if provider in walk.task_gates:
        # Mandatory: a task-gated monster priced without its task reads as
        # though you could walk up and fight it. If the wait cannot be
        # costed, the honest answer is that this route has no price.
        gated = _task_hours(walk, provider, kills, rate.value)
        if gated is None:
            return None
        hours, task = gated
        return _Priced(hours, f"{detail} on {task} task", provider)
    return _Priced(kills / rate.value, detail, provider)


def _task_hours(
    walk: _Walk, provider: str, kills: float, kills_per_hour: float
) -> tuple[float, str] | None:
    """Cost of `kills` of a task-gated monster, waiting for tasks included.

    You cannot go and kill a Grotesque Guardian; you have to be *sent*. One
    assignment yields `mean_count` of them, so `kills` needs
    `kills / mean_count` assignments, and each of those costs the wait for
    that task to come up plus the killing itself. Ignoring the wait is what
    made these look cheap: a gargoyle task once every several hours dwarfs the
    twenty minutes of actual fighting.
    """
    task = walk.task_gates.get(provider)
    if task is None:
        return None

    # Cheapest over the masters that can assign it: the size is theirs too,
    # so wait and assignment length have to come from the same one.
    best: float | None = None
    for master in walk.masters:
        wait = master.hours_to_be_assigned(task)
        rate = (walk.heuristics.slayer.get(master.master) or {}).get(task)
        if wait is None or rate is None or rate.count <= 0:
            continue
        assignments = max(1.0, kills / rate.count)
        hours = assignments * (wait + rate.count / kills_per_hour)
        best = hours if best is None else min(best, hours)
    return (best, task) if best is not None else None


def _superior_hours(
    walk: _Walk, superior: Superior, item: str, quantity: float = 1.0
) -> _Priced | None:
    """Hours to obtain `quantity` of `item` from a superior slayer monster.

    A superior is never placed in a chunk: it replaces one of its normal
    counterparts on death, only while on task, at roughly 1/200. So its cost
    is its base monster's cost multiplied by how many base kills a superior
    takes - and the base is usually task-gated itself, which the recursion
    picks up.
    """
    if superior.spawn_rate <= 0 or superior.base not in walk.available:
        return None
    rates = _drop_rates(walk, superior.name, item)
    if rates is None or rates[0] <= 0 or rates[1] <= 0:
        return None
    chance, per_kill = rates
    rate = walk.heuristics.kills_per_hour(superior.base)
    if rate.value <= 0:
        return None

    # Base kills needed: one superior per `1 / spawn_rate`, and the same two
    # bounds `_kill_hours` takes - the drop has to happen at all, and a stack
    # amortises once you want more than one.
    supers = max(1 / chance, quantity / per_kill)
    kills = (1 / superior.spawn_rate) * supers
    if superior.base in walk.task_gates:
        # Same rule as a direct kill: if the base's task cannot be costed,
        # the route has no price. Falling back to an ungated figure here made
        # the superior route look *cheaper* than the base monster's own drop,
        # which is how a 1/512 drop came out at 1,707 hours.
        gated = _task_hours(walk, superior.base, kills, rate.value)
        if gated is None:
            return None
        hours = gated[0]
    else:
        hours = kills / rate.value
    # The *base* monster is the source: the superior spawns while you kill it,
    # so its drops accumulate alongside the base's own.
    return _Priced(
        hours,
        f"{superior.name} (superior) <- {superior.base}"
        f" at 1/{1 / superior.spawn_rate:,.0f}, drop 1/{1 / chance:,.0f}",
        superior.base,
    )


def _bucket_for(walk: _Walk, source: str) -> str:
    """Boss drops and activity unlocks differ only in what you are killing."""
    return "boss drops" if source in walk.world.boss_monsters else "activities"


def _quest_tasks(derived: Derived, heuristics: Heuristics) -> list[TaskEstimate]:
    """Each outstanding quest, costed by the fraction of its steps left.

    `other_tasks.py` groups quest steps under their `BaseQuest`, which is also
    the wiki's page title, so the group name is the join key and the group's
    active list is what remains.
    """
    category = derived.other_tasks.categories.get("Quest")
    if category is None:
        return []

    estimates: list[TaskEstimate] = []
    for group in category.groups:
        remaining = len(group.active)
        if not remaining:
            continue
        rate = heuristics.quest_hours(group.name)
        total = max(remaining, _steps_in(derived, group.name))
        estimates.append(
            TaskEstimate(
                task=group.name,
                bucket="quests",
                hours=rate.hours * remaining / total,
                detail=f"{remaining}/{total} steps, {rate.length or 'unknown length'}",
            )
        )
    return estimates


def _steps_in(derived: Derived, quest: str) -> int:
    return sum(
        1
        for names in (derived.challenges.valid.get("Quest") or {},)
        for name in names
        if normalise(name).startswith(normalise(quest))
    )


def _has_training_method(chunk_info: ChunkInfo, skill: str, heuristics: Heuristics) -> bool:
    """Is there *any* way of training `skill`?

    Two different sources, because the combat skills answer differently. A
    challenge-based skill asks the export rather than the map: "this map cannot
    reach a Herblore method yet" is a floor band and a correctable gap, while
    "nothing anywhere trains Attack" is a different statement wanting a
    different answer. Measured: Attack 131 challenges and 0 primary, Defence
    146/0, Hitpoints 11/0, Ranged 172/0.

    **And that used to be the whole answer, which made combat unpriceable.**
    It is not a gap in the export - combat has no training *task* because it
    does not need one, it needs a monster. So a computed combat rate counts as
    a method here, and the five skills leave `unpriced_skills` the moment
    `costing/combat_xp.py` can reach something to hit.
    """
    if heuristics.combat.get(skill) is not None:
        return True
    return any(
        isinstance(challenge, dict) and challenge.get("Primary") is True
        for challenge in _mapping(chunk_info.challenges, skill).values()
    )


def _farming_bands(
    plan: FarmingPlan,
    options: Sequence[TrainingOption],
    start_xp: int,
    capped: int,
) -> tuple[tuple[TrainingBand, ...], float]:
    """Farming's climb and its calendar, which are two different quantities.

    **The schedule is one method among the skill's others, not the whole
    answer.** It used to be the whole answer, and that hid Tithe Farm - a
    minigame with no growing time at all, which the map may or may not reach.

    **Where the minigame is available it is preferred outright, and not
    because it is faster by the hour.** It is not: the schedule's blended rate
    counts only the clicking, so it reads several times higher while taking
    months of calendar to deliver. The axis that decides is the calendar, and
    on that the minigame wins by roughly six to one - so it is chosen above
    the level it opens at and the schedule keeps everything below, which is
    also what a player would really do. The wiki says the same thing from the
    other side: you tithe farm *between* the time patches take to grow.

    The calendar is charged for the schedule's stretch alone, since the bands
    the minigame wins have no waiting in them.
    """
    schedule = TrainingOption(
        method=f"{len(plan.runs)} patches, {plan.xp_per_day:,.0f} xp/day",
        level=1,
        xp_per_hour=plan.xp_per_day / plan.hours_per_day,
        match="farming",
    )
    active = min(
        (option.level or 1 for option in options if option.source == TITHE_SOURCE),
        default=None,
    )
    if active is None or active >= capped:
        bands = training_bands((*options, schedule), start_xp, capped)
    else:
        split = max(start_xp, xp_for_level(active))
        bands = training_bands((*options, schedule), start_xp, level_for_xp(split))
        # Above the minigame's level the schedule is left out rather than
        # outranked, which is the whole of "prefer it where you have it".
        bands += training_bands(options, split, capped)
    grown = sum(band.xp for band in bands if band.match == "farming")
    return bands, plan.days_for(grown) if grown > 0 else 0.0


def _skill_estimate(
    skill: str,
    goal: str,
    current: int,
    target: int,
    xp: int,
    bands: tuple[TrainingBand, ...],
    *,
    xp_from_quests: int = 0,
    xp_from_combat: float = 0.0,
    days: float = 0.0,
    effective_level: int = 0,
) -> SkillEstimate:
    """One skill's row, summarised from its bands.

    **`xp_per_hour` is the blended rate and `method` the band that trains the
    most XP**, which is what keeps this change additive: every existing reader -
    the CLI's `{xp} xp @ {rate}/hr = {hours}h {method}` line, the panel, the
    JSON - keeps working and keeps saying something true. The bands carry the
    detail for anyone who wants it.

    `defaulted` keeps its old meaning too: the *whole* climb is at the floor,
    i.e. nothing on this map has a measured rate for this skill. A climb that is
    part floored says so through `floor_xp` instead, which is the more common
    and more interesting case - on the real map the floor is 1% of Herblore's
    XP and 56% of its hours.
    """
    hours = sum(band.hours for band in bands)
    floor_xp = sum(band.xp for band in bands if band.match == "default")
    widest = max(bands, key=lambda band: band.xp, default=None)
    return SkillEstimate(
        skill=skill,
        goal=goal,
        current_level=current,
        target_level=target,
        xp=xp,
        xp_per_hour=xp / hours if hours > 0 else 0.0,
        method=(widest.method if widest and widest.method else "(none found)"),
        hours=hours,
        defaulted=bool(bands) and floor_xp == xp,
        bands=bands,
        floor_xp=floor_xp,
        xp_from_quests=xp_from_quests,
        xp_from_combat=xp_from_combat,
        days=days,
        effective_level=effective_level or current,
    )


@dataclass(frozen=True)
class _Setup:
    """The walk, and the three things `estimate` computes on the way to it.

    Built by `_setup` so that pricing a *material* uses the same gates as
    pricing a goal. Two constructions of `_Walk` would be two answers to
    "can this map reach a blast furnace", and the second one would be wrong
    the moment either moved.
    """

    walk: _Walk
    levels: dict[str, int]
    masters: tuple[MasterRate, ...]
    slayer: MasterRate | None


def _challenge_outputs(
    chunk_info: ChunkInfo, valid: Mapping[str, Mapping[str, Any]]
) -> set[str]:
    """Everything a *valid* challenge names as its `Output`.

    Usually an item; sometimes the name of a `skillItems` table, which is how
    the export says "doing this gives you a roll on that".
    """
    found: set[str] = set()
    for category, names in valid.items():
        challenges = _mapping(chunk_info.challenges, category)
        for name, ok in names.items():
            if not ok:
                continue
            entry = challenges.get(name)
            if isinstance(entry, dict) and isinstance(entry.get("Output"), str):
                found.add(entry["Output"])
    return found


def _setup(
    state: MapState,
    derived: Derived,
    world: WorldIndex,
    heuristics: Heuristics,
    level_overrides: dict[str, int],
) -> _Setup:
    """Everything the item walk needs, assembled once."""
    levels = _levels(state, level_overrides or {})
    reachable = frozenset(derived.source_index.monsters)
    providers = reachable_providers(derived)
    valid = derived.challenges.valid
    # `derive`'s *settled* expansion, not a fresh one-shot call: areas keep
    # opening as challenges become valid, and expanding once leaves 60 named
    # areas locked on the real map - `Wilderness Slayer Cave` among them,
    # which silently cost Krystilia every task that can roll a superior.
    expanded = dict(derived.expanded_chunks)
    # A slayer master you cannot reach assigns nothing - see `slayer.py`.
    reachable_masters = frozenset(derived.source_index.npcs)

    # End-of-chunk levels, not today's: the task list a master offers then
    # is the one that holds for the tail of the chunk, which is where the
    # time goes.
    goals = goal_levels(state, derived, levels)
    reachable_rates = tuple(
        master_rates(
            state.chunk_info,
            heuristics,
            reachable_monsters=reachable,
            valid=valid,
            unlocked=expanded,
            reachable_sections=derived.reachable_sections,
            levels=goals,
            combat_level=goals.get("Combat", MAX_LEVEL),
            reachable_masters=reachable_masters,
        )
    )
    slayer_rate = best_master(list(reachable_rates))
    # The same end-of-chunk levels for task-gated drops. Grotesque Guardians
    # need a gargoyle task, which needs Slayer 75; at today's level that task
    # is unassignable and the drop would read as unobtainable forever. It
    # isn't - the skilling bucket is already costing the climb.
    # **An activity a valid challenge unlocks is a provider too.** The export
    # models the Evil chicken outfit as `Trade bird's eggs for nests*` at a
    # Shrine, whose `Output` names the `skillItems.Nonskill` table holding the
    # four pieces at 1/1200 - so the pieces are reachable the moment the trade
    # is, and were unpriced because nothing put the *table* in the provider
    # set beside monsters, objects and NPCs.
    #
    # **Gated on someone having stated a rate**, which is what keeps this from
    # pricing the other 322 such tables at the 60/hr default: a minigame reward
    # table given a guessed rate would make its rarest drop look cheap, and a
    # guessed rate multiplied by a real drop chance is the mistake
    # `combat_xp.best_target` already refuses.
    unlocked_activities = frozenset(
        name
        for name in _challenge_outputs(state.chunk_info, valid)
        if any(name in _mapping(state.chunk_info.skill_items, skill)
               for skill in state.chunk_info.skill_items)
        and not heuristics.kills_per_hour(name).source.startswith("default")
    )
    providers = providers | unlocked_activities
    gate_masters = reachable_rates
    walk = _Walk(
        chunk_info=state.chunk_info,
        world=world,
        heuristics=heuristics,
        tables=_mapping(state.chunk_info.code_items, "dropTables"),
        by_lower={item.lower(): item for item in world.item_sources},
        available=providers,
        reachable_items=frozenset(derived.source_index.items),
        task_gates=task_gated_monsters(
            state.chunk_info, world, frozenset(expanded)
        ),
        masters=gate_masters,
        item_families={
            name: members
            for name, members in _mapping(state.chunk_info.code_items, "itemsPlus").items()
            if isinstance(members, list)
        },
        superior_table=superior_table_items(state.chunk_info),
        superior_rolls={
            rate.master: superior_rolls_per_hour(rate, state.chunk_info, heuristics)
            for rate in gate_masters
        },
    )
    return _Setup(
        walk=walk, levels=levels, masters=reachable_rates, slayer=slayer_rate
    )


def material_seconds(
    state: MapState,
    derived: Derived,
    world: WorldIndex,
    heuristics: Heuristics,
    *,
    level_overrides: dict[str, int] | None = None,
) -> Callable[[str, float], float | None]:
    """A callable pricing `quantity` of an item, in seconds, or `None`.

    **What `costing/recipe_rates.py` needs and cannot build for itself.** The
    item walk lives here, behind a `_Walk` carrying this map's reachability
    gates; a recipe is a pure fact about the game. So the seam is this
    closure: `recipe_rates` asks "how long to get two guam leaves" without
    learning what a `_Walk` is, and `estimate` answers without learning what a
    recipe is.

    `None` means no route, which the caller must treat as *drop the method*
    rather than as free - see that module's docstring.

    The closure holds one `_Walk` and is therefore worth reusing across a whole
    skill's recipes; it is a local, never a module-level cache, so the purity
    rule that keeps `--jobs` honest is untouched.
    """
    walk = _setup(state, derived, world, heuristics, level_overrides or {}).walk

    def seconds(item: str, quantity: float) -> float | None:
        # `amortise`: a recipe's materials are bought for a run of actions,
        # not fetched one trip at a time. See `_route_hours`.
        priced = _item_hours(walk, item, quantity=quantity, amortise=True)
        return None if priced is None else priced.hours * 3600.0

    return seconds


def estimate(
    state: MapState,
    derived: Derived,
    world: WorldIndex,
    heuristics: Heuristics,
    *,
    level_overrides: dict[str, int] | None = None,
) -> EstimateResult:
    """Estimate the outstanding active work. See the module docstring first."""
    setup = _setup(state, derived, world, heuristics, level_overrides or {})
    walk, levels = setup.walk, setup.levels
    reachable_rates, slayer_rate = setup.masters, setup.slayer
    tasks: list[TaskEstimate] = list(_quest_tasks(derived, heuristics))
    unpriced: list[str] = []

    # Price the *item*, once, no matter how many tasks want it. An abyssal
    # whip answers a BiS pick, a Slayer log entry and a monster-drop log
    # entry; charging for it three times inflated the total by however much
    # the active set happens to overlap, which on the real map is a lot.
    items: list[ItemEstimate] = []
    for item, wanted_by in sorted(_required_items(walk, derived).items()):
        priced = _item_hours(walk, item)
        if priced is None:
            unpriced.append(item)
            continue
        items.append(
            ItemEstimate(
                item=item,
                bucket=_bucket_for(walk, priced.source),
                hours=priced.hours,
                detail=priced.detail,
                source=priced.source,
                tasks=tuple(sorted(wanted_by)),
            )
        )

    # Tasks wanting a kill rather than a drop: one kill at that monster's
    # rate, attributed to it so the clamp folds it into any grind already
    # happening there.
    for monster, wanted_by in sorted(_required_kills(walk, derived).items()):
        kph = heuristics.kills_per_hour(monster).value
        if kph <= 0:
            continue
        items.append(
            ItemEstimate(
                item=f"kill {monster}",
                bucket=_bucket_for(walk, monster),
                hours=1 / kph,
                detail=f"one kill at {kph:g}/hr",
                source=monster,
                tasks=tuple(sorted(wanted_by)),
            )
        )

    skills: list[SkillEstimate] = []
    unpriced_skills: list[UnpricedSkill] = []
    combat_at: dict[str, tuple[int, str, int, int, int, int, int]] = {}
    grants, lamps = quest_xp_grants(derived, state.chunk_info)
    for skill, classification in sorted(derived.task_classification.skills.items()):
        goal = classification.active
        if goal is None:
            continue
        challenge = _mapping(state.chunk_info.challenges, skill).get(goal)
        target = challenge.get("Level") if isinstance(challenge, dict) else None
        if not isinstance(target, (int, float)) or isinstance(target, bool):
            continue
        current = levels.get(skill, 1)
        capped = min(int(target), MAX_LEVEL)
        target_xp = xp_for_level(capped)
        # **One operation, not two.** Adding the quest reward to the starting
        # total both removes that XP from the climb and moves the start up the
        # curve, so there is no separate level adjustment that could disagree
        # with it. Clamped at the goal: a reward can overshoot.
        granted = grants.get(skill, 0)
        start_xp = min(xp_for_level(max(1, min(current, MAX_LEVEL))) + granted, target_xp)
        xp = max(0, target_xp - start_xp)
        # **Two different refusals, and the difference is worth saying.** One
        # is "the export lists nothing that trains this"; the other is "the
        # export lists plenty and nobody anywhere has timed any of it". Both
        # end here rather than at the floor, because a four-figure number with
        # nothing behind it is worse than an admission.
        refusal = ""
        if xp > 0 and skill in UNRATED_SKILLS and not training_options(
            derived, state.chunk_info, heuristics, skill
        ):
            refusal = "no published rates for this skill yet"
        elif xp > 0 and not _has_training_method(state.chunk_info, skill, heuristics):
            # No `Primary: true` challenge anywhere in the export - the four
            # combat skills, which you train by fighting rather than by an
            # activity the export lists. Refused, not guessed at.
            refusal = "no training method exists for this skill"
        if refusal:
            unpriced_skills.append(
                UnpricedSkill(
                    skill=skill,
                    goal=goal,
                    current_level=current,
                    target_level=int(target),
                    xp=xp,
                    reason=refusal,
                )
            )
            continue
        farming_days = 0.0
        bands: tuple[TrainingBand, ...] = ()
        if skill == "Farming" and heuristics.crops:
            # **Farming is days, not hours.** A crop grows while you do
            # something else, so the schedule - how many harvests a day you
            # get round to - is what limits it. `active_hours` is the clicking
            # and goes in the bucket beside every other skill; the calendar is
            # reported next to it and deliberately not added, because a day of
            # waiting is not a day of playing.
            plan = farming_plan(
                heuristics.crops,
                capped,
                harvests_per_day={
                    **DEFAULT_HARVESTS_PER_DAY,
                    **heuristics.farming_schedule,
                },
            )
            if plan.xp_per_day > 0 and plan.hours_per_day > 0:
                bands, farming_days = _farming_bands(
                    plan,
                    training_options(derived, state.chunk_info, heuristics, skill),
                    start_xp,
                    capped,
                )
        if bands:
            pass
        elif skill == "Slayer" and slayer_rate is not None and slayer_rate.xp_per_hour > 0:
            # **Slayer is one band by nature.** Its rate is a distribution over
            # what a master assigns rather than a method you pick and outgrow,
            # so `slayer.py` answers for the whole climb and there is nothing
            # to band.
            bands = (
                TrainingBand(
                    level_from=level_for_xp(start_xp),
                    level_to=capped,
                    xp=xp,
                    xp_per_hour=slayer_rate.xp_per_hour,
                    method=slayer_rate.master,
                    match="slayer",
                ),
            )
        else:
            bands = training_bands(
                training_options(derived, state.chunk_info, heuristics, skill),
                start_xp,
                capped,
            )
        skills.append(
            _skill_estimate(
                skill,
                goal,
                current,
                int(target),
                xp,
                bands,
                xp_from_quests=min(granted, xp_between(current, capped)),
                days=farming_days,
                effective_level=level_for_xp(start_xp),
            )
        )
        if skill in COMBAT_SKILLS:
            combat_at[skill] = (
                len(skills) - 1, goal, current, int(target), capped, start_xp, granted
            )

    def _rebuild(skill: str, credited: float) -> None:
        """Re-price one combat climb with `credited` XP taken off its front."""
        at, goal_, level_, target_, capped_, start_, granted_ = combat_at[skill]
        target_xp_ = xp_for_level(capped_)
        moved = int(min(start_ + credited, target_xp_))
        skills[at] = _skill_estimate(
            skill,
            goal_,
            level_,
            target_,
            max(0, target_xp_ - moved),
            training_bands(
                training_options(derived, state.chunk_info, heuristics, skill),
                moved,
                capped_,
            ),
            xp_from_quests=min(granted_, xp_between(level_, capped_)),
            xp_from_combat=min(credited, float(xp_between(level_, capped_))),
            effective_level=level_for_xp(moved),
        )

    # **A Slayer task is a fight, so it pays the combat skills too.** Its XP is
    # the monster's hitpoints, which makes a Slayer rate a damage rate - and
    # 394 hours of it on the benchmark map had already earned the Hitpoints,
    # Defence and Attack climbs being charged for beside it. Credited before
    # `hitpoints_credit`, so that pass sees the hours that are actually left.
    slayer_at = next(
        (i for i, entry in enumerate(skills) if entry.skill == "Slayer"), None
    )
    if slayer_at is not None and slayer_rate is not None and combat_at:
        damage = skills[slayer_at].hours * slayer_rate.xp_per_hour
        needs = {
            skill: float(skills[at].xp) for skill, (at, *_) in combat_at.items()
        }
        for skill, credited in sorted(slayer_credit(damage, needs).items()):
            if credited > 0:
                _rebuild(skill, credited + skills[combat_at[skill][0]].xp_from_combat)

    # **Hitpoints is earned by the other combat climbs, not beside them.**
    # Every point of damage paying 4 XP to Strength pays 1.33 to Hitpoints at
    # the same instant, so pricing both climbs in full bills the same hours
    # twice. Done after the loop rather than inside it because the credit
    # depends on skills that sort after `Hitpoints` - Magic, Ranged, Strength.
    if "Hitpoints" in combat_at and heuristics.combat_damage:
        at = combat_at["Hitpoints"][0]
        credit = hitpoints_credit(
            {entry.skill: entry.hours for entry in skills},
            heuristics.combat_damage,
        )
        if credit > 0:
            _rebuild("Hitpoints", credit + skills[at].xp_from_combat)
    return EstimateResult(
        unpriced_skills=tuple(unpriced_skills),
        unallocated_quest_xp=lamps,
        tasks=tuple(tasks),
        items=tuple(items),
        skills=tuple(skills),
        slayer=slayer_rate,
        slayer_masters=reachable_rates,
        superior_rolls=dict(walk.superior_rolls),
        superior_spawns={
            rate.master: superior_spawns_per_hour(rate, state.chunk_info, heuristics)
            for rate in reachable_rates
        },
        unpriced=tuple(sorted(unpriced)),
    )


def _item_tasks(derived: Derived) -> list[str]:
    """The active non-quest tasks: BiS picks still to get, plus Diary/Extra."""
    names = list(derived.bis.active)
    for category, tasks in derived.other_tasks.categories.items():
        if category == "Quest":
            continue
        names.extend(name for group in tasks.groups for name in group.active)
    return names


def _required_items(walk: _Walk, derived: Derived) -> dict[str, set[str]]:
    """Every item the active set needs, mapped to the tasks that want it.

    **The item is the unit of work, not the task.** One abyssal whip closes a
    BiS pick, a Slayer collection-log entry and a monster-drop log entry; you
    obtain it once. Keying on the item collapses that to a single cost and
    keeps the tasks it answers alongside, so the listing can still show why
    it is wanted.

    A BiS task names its item in its `~|...|~` span and has **no challenge
    behind it** (`bis.py` synthesises those names), so the span is the only
    handle there. Where a challenge *does* exist the span is not an item and
    must not be read as one: `~|Morytania Diary#Elite|~ Task 5` is "kill an
    abyssal demon in the Slayer Tower", and taking its span produced a
    request for an item called `Morytania Diary#Elite`, which of course had
    no route and reported as unpriced.
    """
    wanted: dict[str, set[str]] = {}
    for task in _item_tasks(derived):
        challenge = _find_challenge(walk, task)
        if challenge is None:
            wanted.setdefault(walk.resolve(activity_name(task)), set()).add(task)
            continue
        for item in _challenge_items(walk, task):
            wanted.setdefault(walk.resolve(item), set()).add(task)
    return wanted


def _required_kills(walk: _Walk, derived: Derived) -> dict[str, set[str]]:
    """Tasks that want no item, only something dead, by what has to die.

    Several diary tasks are of this shape - "kill an abyssal demon in the
    Slayer Tower", "kill Callisto, Venenatis and Vet'ion". One kill is
    cheap, but it is not free and it is not an item, and pricing it against
    the monster means the per-source clamp folds it into whatever grind that
    monster is already part of.
    """
    families = _mapping(walk.chunk_info.code_items, "monstersPlus")
    wanted: dict[str, set[str]] = {}
    for task in _item_tasks(derived):
        challenge = _find_challenge(walk, task)
        if challenge is None or challenge.get("Items"):
            continue
        for name in challenge.get("Monsters") or ():
            if not isinstance(name, str):
                continue
            members = families.get(name) if "[+]" in name else [name]
            for member in members if isinstance(members, list) else [name]:
                if isinstance(member, str) and member in walk.available:
                    wanted.setdefault(member, set()).add(task)
                    break
    return wanted


def _find_challenge(walk: _Walk, task: str) -> dict[str, Any] | None:
    for challenges in walk.chunk_info.challenges.values():
        if isinstance(challenges, dict) and isinstance(challenges.get(task), dict):
            found: dict[str, Any] = challenges[task]
            return found
    return None


def _challenge_items(walk: _Walk, task: str) -> list[str]:
    for challenges in walk.chunk_info.challenges.values():
        if not isinstance(challenges, dict):
            continue
        challenge = challenges.get(task)
        if isinstance(challenge, dict):
            return [
                item.replace("*", "")
                for item in challenge.get("Items") or ()
                if isinstance(item, str)
            ]
    return []
