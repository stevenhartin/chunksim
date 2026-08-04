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

**The item walk.** A task needs items; an item has routes (`search.py`'s
`WorldIndex`, the whole-world index of all five); a route has a rate. The
cheapest route wins and its cost is `(1 / p) / kills_per_hour`. Rates come
from `drops`/`skillItems` and are parsed by `rates.parse_ratio`, falling back
to `Heuristics.rarity` for the ~1,200 entries the export words rather than
numbers (`Always`, `Common`, ...). Drop tables compose multiplicatively, the
same expansion `sources.py` does for the unlocked case.

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
from fray_claude.heuristics import Heuristics, activity_name
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

    tasks: tuple[TaskEstimate, ...] = ()
    skills: tuple[SkillEstimate, ...] = ()
    slayer: MasterRate | None = None
    #: Tasks whose items have no priceable route - the honest coverage figure.
    unpriced: tuple[str, ...] = ()

    @property
    def buckets(self) -> dict[str, float]:
        totals = {bucket: 0.0 for bucket in BUCKETS}
        for task in self.tasks:
            totals[task.bucket] = totals.get(task.bucket, 0.0) + task.hours
        totals["skilling"] += sum(skill.hours for skill in self.skills)
        return totals

    @property
    def total_hours(self) -> float:
        return sum(self.buckets.values())

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

    chance = _drop_probability(walk, provider, item)
    if chance is None or chance <= 0:
        return None
    rate = walk.heuristics.kills_per_hour(provider)
    if rate.value <= 0:
        return None
    hours = (1 / chance) / rate.value
    return hours, f"{provider} at 1/{1 / chance:,.0f}, {rate.value:g}/hr"


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
    walk = _Walk(
        chunk_info=state.chunk_info,
        world=world,
        heuristics=heuristics,
        tables=_mapping(state.chunk_info.code_items, "dropTables"),
        by_lower={item.lower(): item for item in world.item_sources},
    )
    levels = _levels(state, level_overrides or {})

    tasks: list[TaskEstimate] = list(_quest_tasks(derived, heuristics))
    unpriced: list[str] = []

    for name in _item_tasks(derived):
        priced = _cheapest_for_task(walk, name)
        if priced is None:
            unpriced.append(name)
            continue
        hours, detail = priced
        tasks.append(
            TaskEstimate(
                task=name, bucket=_bucket_for(walk, detail), hours=hours, detail=detail
            )
        )

    slayer_rate = best_master(
        master_rates(
            state.chunk_info,
            heuristics,
            reachable_monsters=frozenset(derived.source_index.monsters),
            valid_quests=frozenset(derived.challenges.valid.get("Quest") or {}),
            levels=levels,
            combat_level=levels.get("Combat", MAX_LEVEL),
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


def _cheapest_for_task(walk: _Walk, task: str) -> tuple[float, str] | None:
    """Price a task by the items it needs, summing them.

    A BiS task names its item in its `~|...|~` span and has no challenge
    behind it (`bis.py` synthesises those names), so the span is the only
    handle; an ordinary challenge lists its `Items`.
    """
    items = _required_items(walk, task) or [activity_name(task)]
    total = 0.0
    detail = ""
    for item in items:
        priced = _item_hours(walk, item)
        if priced is None:
            return None
        total += priced[0]
        if not detail or priced[0] > 0:
            detail = priced[1]
    return total, detail


def _required_items(walk: _Walk, task: str) -> list[str]:
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
