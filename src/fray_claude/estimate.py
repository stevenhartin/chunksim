"""How long the outstanding work would take, in the roughest useful terms.

Four buckets, from `plan.md`: quests, boss drops, activity unlocks, and
skilling. Every number spent here comes from `heuristics.py` and is a guess;
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

**The item walk.** A task needs items; an item has routes (`search.py`'s
`WorldIndex`, the whole-world index of all five); a route has a rate. The
cheapest route wins and its cost is `(1 / p) / kills_per_hour`. Rates come
from `drops`/`skillItems` and are parsed by `rates.parse_ratio`, falling back
to `Heuristics.rarity` for the ~1,200 entries the export words rather than
numbers (`Always`, `Common`, ...). Drop tables compose multiplicatively, the
same expansion `sources.py` does for the unlocked case.

**Three gates stand between a drop and its price, and skipping any of them
prices a game nobody is playing.**

1. *The monster has to be reachable.* `WorldIndex` spans the whole world, so
   without a check the walk costs every drop in OSRS. `SourceIndex.monsters`
   is the answer - placed in an unlocked chunk *and* past its `taskUnlocks`
   gates. `Colossal Hydra` is what taught this: a `skillItems.Slayer` activity
   with 43 drops and no chunk anywhere, priced as though you could go and
   fight one.
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

**Two deliberate limits, both of which would otherwise bite.**

- *An item made from other items recurses*, and can cycle: A is the output of
  a challenge needing B, which needs A. Bounded by `_MAX_DEPTH` and a visited
  set, and anything hitting either is reported `unpriced` rather than guessed
  at - the posture `challenges.py` takes with `unsupported`.
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

`current` is the problem. **The map does not record the player's skill
levels.** `max_skill` is a declared *cap* (`sources.py` reads it as "levels I
can reach"), and `passive_skill` is what a level is attainable *without* a
training method (`worker.js:5114`). Neither is "what I am now". This module
takes `passive_skill` as the floor, because it is the only per-skill number in
the payload that means anything like progress, and lets a `levels` override
replace it outright. Where that floor is wrong the skilling bucket is wrong
with it, which is why every skill row prints the level it assumed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from fray_claude.chunkinfo import ChunkInfo
from fray_claude.experience import MAX_LEVEL, xp_between
from fray_claude.heuristics import Heuristics, Superior, activity_name
from fray_claude.pipeline import Derived, MapState
from fray_claude.rates import parse_ratio
from fray_claude.search import WorldIndex, normalise
from fray_claude.slayer import MasterRate, best_master, master_rates
from fray_claude.summary import _mapping

#: The buckets, in the order `fray estimate` reports them.
BUCKETS = ("quests", "boss drops", "activities", "skilling")

#: How far the item walk will chase "made from" chains before giving up. Three
#: is past every real case measured (an imbued ring is output <- item <-
#: drop); beyond it the answer is guesswork stacked on guesswork.
_MAX_DEPTH = 3

#: Routes that cost no meaningful time once reachable: a shop purchase and a
#: ground spawn are both "walk there and take it".
_FREE_ROUTES = frozenset({"shop", "spawn"})


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
    tasks: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "item": self.item,
            "bucket": self.bucket,
            "hours": self.hours,
            "detail": self.detail,
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
    #: True when the rate is the un-joined floor, i.e. a guess worth fixing.
    defaulted: bool = False

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
    slayer: MasterRate | None = None
    #: Items with no priceable route - the honest coverage figure.
    unpriced: tuple[str, ...] = ()

    @property
    def buckets(self) -> dict[str, float]:
        totals = {bucket: 0.0 for bucket in BUCKETS}
        for task in self.tasks:
            totals[task.bucket] = totals.get(task.bucket, 0.0) + task.hours
        for item in self.items:
            totals[item.bucket] = totals.get(item.bucket, 0.0) + item.hours
        totals["skilling"] += sum(skill.hours for skill in self.skills)
        return totals

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
            "skills": [skill.as_dict() for skill in self.skills],
            "slayer": self.slayer.as_dict() if self.slayer else None,
            "unpriced": list(self.unpriced),
        }


@dataclass(frozen=True)
class _Walk:
    """Everything the item walk reads, bundled so it isn't passed six-deep."""

    chunk_info: ChunkInfo
    world: WorldIndex
    heuristics: Heuristics
    tables: dict[str, Any] = field(default_factory=dict)
    #: Monsters actually reachable on this map: placed in an unlocked chunk
    #: *and* past their `taskUnlocks` gates. This is `SourceIndex.monsters`,
    #: and gating on it is the difference between pricing the world and
    #: pricing your world - see `_route_hours`.
    available: frozenset[str] = frozenset()
    #: Monster -> the slayer task you must be on to fight it, where one is
    #: required. Derived from `taskUnlocks`; see `task_gated_monsters`.
    task_gates: dict[str, str] = field(default_factory=dict)
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


def _drop_probability(walk: _Walk, monster: str, item: str) -> float | None:
    """The chance one kill of `monster` yields `item`, tables included."""
    best: float | None = None
    for source in (walk.chunk_info.drops, *_skill_item_tables(walk)):
        rows = _mapping(source, monster)
        for name, quantities in rows.items():
            if not isinstance(quantities, dict):
                continue
            direct = name == item
            table = walk.tables.get(name) if not direct else None
            if not direct and not isinstance(table, dict):
                continue
            for raw in quantities.values():
                chance = _probability(str(raw), walk.heuristics)
                if chance is None:
                    continue
                if not direct:
                    within = _table_probability(table, item, walk.heuristics)
                    if within is None:
                        continue
                    chance *= within
                best = chance if best is None else max(best, chance)
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
    walk: _Walk, item: str, *, depth: int = 0, seen: frozenset[str] = frozenset()
) -> tuple[float, str] | None:
    """Cheapest route to one `item`, as `(hours, why)`, or `None`.

    `None` is "no route this module can price", which the caller reports as
    unpriced rather than dropping - an estimate that silently skips its
    expensive half is worse than one that admits a gap.
    """
    item = walk.resolve(item)
    if item in seen or depth > _MAX_DEPTH:
        return None

    best: tuple[float, str] | None = None
    for source in walk.world.item_sources.get(item, ()):
        priced = _route_hours(walk, item, source.route, source.name, depth, seen | {item})
        if priced is not None and (best is None or priced[0] < best[0]):
            best = priced
    return best


def _route_hours(
    walk: _Walk, item: str, route: str, provider: str, depth: int, seen: frozenset[str]
) -> tuple[float, str] | None:
    if route in _FREE_ROUTES:
        return 0.0, f"{route}: {provider}"

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
            priced = _item_hours(walk, required.replace("*", ""), depth=depth + 1, seen=seen)
            if priced is None:
                return None
            total += priced[0]
        return total, f"make: {provider}"

    return _kill_hours(walk, provider, item)


def _kill_hours(walk: _Walk, provider: str, item: str) -> tuple[float, str] | None:
    """Hours of killing `provider` to see one `item`, gates included.

    **Availability is checked first and is not negotiable.** `provider` has to
    be a monster this map can actually reach - placed in an unlocked chunk and
    past its `taskUnlocks` gates. Without that the walk prices the whole game:
    `Colossal Hydra` is a `skillItems.Slayer` activity with 43 drops and no
    chunk anywhere (it is a superior, spawned from Alchemical Hydra), and it
    was being costed as though you could go and fight one.
    """
    if provider not in walk.available:
        superior = walk.heuristics.superiors.get(provider)
        return _superior_hours(walk, superior, item) if superior else None

    chance = _drop_probability(walk, provider, item)
    if chance is None or chance <= 0:
        return None
    rate = walk.heuristics.kills_per_hour(provider)
    if rate.value <= 0:
        return None

    kills = 1 / chance
    detail = f"{provider} at 1/{kills:,.0f}, {rate.value:g}/hr"

    if provider in walk.task_gates:
        # Mandatory: a task-gated monster priced without its task reads as
        # though you could walk up and fight it. If the wait cannot be
        # costed, the honest answer is that this route has no price.
        gated = _task_hours(walk, provider, kills, rate.value)
        if gated is None:
            return None
        hours, task = gated
        return hours, f"{detail} on {task} task"
    return kills / rate.value, detail


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
    rate = walk.heuristics.slayer.get(task) if task else None
    if task is None or rate is None or rate.mean_count <= 0:
        return None

    waits = [
        wait
        for master in walk.masters
        if (wait := master.hours_to_be_assigned(task)) is not None
    ]
    if not waits:
        return None
    assignments = max(1.0, kills / rate.mean_count)
    return assignments * (min(waits) + rate.mean_count / kills_per_hour), task


def _superior_hours(
    walk: _Walk, superior: Superior, item: str
) -> tuple[float, str] | None:
    """Hours to see one `item` from a superior slayer monster.

    A superior is never placed in a chunk: it replaces one of its normal
    counterparts on death, only while on task, at roughly 1/200. So its cost
    is its base monster's cost multiplied by how many base kills a superior
    takes - and the base is usually task-gated itself, which the recursion
    picks up.
    """
    if superior.spawn_rate <= 0 or superior.base not in walk.available:
        return None
    chance = _drop_probability(walk, superior.name, item)
    if chance is None or chance <= 0:
        return None
    rate = walk.heuristics.kills_per_hour(superior.base)
    if rate.value <= 0:
        return None

    # Base kills needed: one superior per `1 / spawn_rate`, and one drop per
    # `1 / chance` superiors.
    kills = (1 / superior.spawn_rate) * (1 / chance)
    gated = _task_hours(walk, superior.base, kills, rate.value)
    hours = gated[0] if gated is not None else kills / rate.value
    return hours, (
        f"{superior.name} (superior) <- {superior.base}"
        f" at 1/{1 / superior.spawn_rate:,.0f}, drop 1/{1 / chance:,.0f}"
    )


def task_gated_monsters(chunk_info: ChunkInfo) -> dict[str, str]:
    """Monsters you must be *on a slayer task* to fight, and which task.

    Read out of `taskUnlocks['Monsters']`, whose entries are per location::

        "Grotesque Guardians": {"Grotesque Guardians' Lair":
                                    [{"Gargoyle task": "Nonskill"}]}
        "Alchemical Hydra":    {"Karuulm Slayer Dungeon":
                                    [{"Hydra task": "Nonskill"}]}

    A `Nonskill` requirement named `<something> task` is the export's way of
    saying "only while assigned". The other gates there are quests
    (`Adamant dragon` wants Dragon Slayer II) and are ordinary validity
    requirements `challenges.py` already enforces, so only the task-shaped
    ones matter here. The name maps back to a `codeItems.slayerTasks` key -
    `Gargoyle task` to the `Gargoyles` assignment - because that is where the
    weight lives.

    Nothing marks these monsters directly, which is why this is inferred
    rather than looked up. Guessing instead (all 469 monsters a slayer task
    covers, say) would put a waiting cost on every aberrant spectre you can
    already walk up to and kill.
    """
    assignments = _mapping(chunk_info.code_items, "slayerTasks")
    by_normalised = {normalise(name): name for name in assignments}

    gates: dict[str, str] = {}
    for monster, locations in _mapping(chunk_info.data, "taskUnlocks").get("Monsters", {}).items():
        if not isinstance(locations, dict):
            continue
        for requirements in locations.values():
            for requirement in requirements if isinstance(requirements, list) else ():
                if not isinstance(requirement, dict):
                    continue
                for name, category in requirement.items():
                    if category != "Nonskill" or not name.endswith(" task"):
                        continue
                    subject = normalise(name.removesuffix(" task"))
                    for candidate in (subject, f"{subject}s", f"{subject}es"):
                        if candidate in by_normalised:
                            gates[monster] = by_normalised[candidate]
                            break
    return gates


def _bucket_for(walk: _Walk, detail: str) -> str:
    """Boss drops and activity unlocks differ only in what you are killing."""
    provider = detail.split(" at 1/")[0]
    return "boss drops" if provider in walk.world.boss_monsters else "activities"


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


def _declared(state: MapState) -> dict[str, int]:
    """The levels the map says are *reachable* (`maxSkill`), not held."""
    return {
        skill: int(level)
        for skill, level in state.max_skill.items()
        if isinstance(level, (int, float)) and not isinstance(level, bool)
    }


def _levels(state: MapState, overrides: dict[str, int]) -> dict[str, int]:
    """The per-skill level to count from. See the module docstring's caveat."""
    levels = {
        skill: int(level)
        for skill, level in state.passive_skill.items()
        if isinstance(level, (int, float)) and not isinstance(level, bool)
    }
    levels.update(overrides)
    return levels


def _training_rate(
    derived: Derived, chunk_info: ChunkInfo, heuristics: Heuristics, skill: str, level: int
) -> tuple[float, str, bool]:
    """The fastest reachable primary method for `skill`: `(rate, name, is default)`."""
    challenges = _mapping(chunk_info.challenges, skill)
    best = (0.0, "", True)
    for name in derived.challenges.valid.get(skill) or {}:
        challenge = challenges.get(name)
        if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
            continue
        required = challenge.get("Level")
        if isinstance(required, (int, float)) and required > level:
            continue
        rate = heuristics.xp_per_hour(name, skill)
        if rate.value > best[0]:
            best = (rate.value, activity_name(name), rate.match == "default")
    return best


def estimate(
    state: MapState,
    derived: Derived,
    world: WorldIndex,
    heuristics: Heuristics,
    *,
    level_overrides: dict[str, int] | None = None,
) -> EstimateResult:
    """Estimate the outstanding active work. See the module docstring first."""
    levels = _levels(state, level_overrides or {})
    reachable = frozenset(derived.source_index.monsters)
    valid_quests = frozenset(derived.challenges.valid.get("Quest") or {})
    # A slayer master you cannot reach assigns nothing - see `slayer.py`.
    reachable_masters = frozenset(derived.source_index.npcs)

    slayer_rate = best_master(
        master_rates(
            state.chunk_info,
            heuristics,
            reachable_monsters=reachable,
            valid_quests=valid_quests,
            levels=levels,
            combat_level=levels.get("Combat", MAX_LEVEL),
            reachable_masters=reachable_masters,
        )
    )
    # Every master's table, for *task-gated drops only*, computed at the
    # levels the player has declared they can reach rather than the ones they
    # have. Grotesque Guardians need a gargoyle task, which needs Slayer 75;
    # at the current level that task is unassignable and the drop would read
    # as unobtainable forever. It isn't - the skilling bucket is already
    # costing the climb - so the kill is priced at what it will cost once
    # assignable.
    gate_masters = tuple(
        master_rates(
            state.chunk_info,
            heuristics,
            reachable_monsters=reachable,
            valid_quests=valid_quests,
            levels={**levels, **_declared(state)},
            combat_level=MAX_LEVEL,
            reachable_masters=reachable_masters,
        )
    )
    walk = _Walk(
        chunk_info=state.chunk_info,
        world=world,
        heuristics=heuristics,
        tables=_mapping(state.chunk_info.code_items, "dropTables"),
        by_lower={item.lower(): item for item in world.item_sources},
        available=reachable,
        task_gates=task_gated_monsters(state.chunk_info),
        masters=gate_masters,
    )

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
        hours, detail = priced
        items.append(
            ItemEstimate(
                item=item,
                bucket=_bucket_for(walk, detail),
                hours=hours,
                detail=detail,
                tasks=tuple(sorted(wanted_by)),
            )
        )

    skills: list[SkillEstimate] = []
    for skill, classification in sorted(derived.task_classification.skills.items()):
        goal = classification.active
        if goal is None:
            continue
        challenge = _mapping(state.chunk_info.challenges, skill).get(goal)
        target = challenge.get("Level") if isinstance(challenge, dict) else None
        if not isinstance(target, (int, float)) or isinstance(target, bool):
            continue
        current = levels.get(skill, 1)
        xp = xp_between(current, min(int(target), MAX_LEVEL))
        if skill == "Slayer" and slayer_rate is not None and slayer_rate.xp_per_hour > 0:
            rate, method, defaulted = slayer_rate.xp_per_hour, slayer_rate.master, False
        else:
            rate, method, defaulted = _training_rate(
                derived, state.chunk_info, heuristics, skill, current
            )
        skills.append(
            SkillEstimate(
                skill=skill,
                goal=goal,
                current_level=current,
                target_level=int(target),
                xp=xp,
                xp_per_hour=rate,
                method=method or "(none found)",
                hours=xp / rate if rate > 0 else 0.0,
                defaulted=defaulted,
            )
        )

    return EstimateResult(
        tasks=tuple(tasks),
        items=tuple(items),
        skills=tuple(skills),
        slayer=slayer_rate,
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

    A BiS task names its item in its `~|...|~` span and has no challenge
    behind it (`bis.py` synthesises those names), so the span is the only
    handle; an ordinary challenge lists its `Items`.
    """
    wanted: dict[str, set[str]] = {}
    for task in _item_tasks(derived):
        for item in _challenge_items(walk, task) or [activity_name(task)]:
            wanted.setdefault(walk.resolve(item), set()).add(task)
    return wanted


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
