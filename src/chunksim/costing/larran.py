"""Larran's small and big chests: what a key really costs.

Same shape of gap `costing/keyed_chests.py` already closed for Bryophyta's
and Obor's lairs - both chests are `skillItems.Nonskill` activities
(`Larran's small chest`/`Larran's big chest`) the item walk reaches directly
whenever something inside wants pricing, reading the chest as an ordinary
monster-shaped source and asking `Heuristics.kills_per_hour` how often it
opens. Neither chest has a stat block, so that call fell to
`DEFAULT_KPH["regular"]`, 150/hr, and every item inside - an uncut ruby, a
rune platebody, a dragon arrowtip - priced as though the chest opened on
demand.

**The key is the whole cost, and there is exactly one way to earn one:
"Wilderness Slayer tasks from Krystilia"** (the wiki's own words). So unlike
`keyed_chests`' fixed per-monster fraction (Bryophyta drops a Mossy key at a
flat 1/16), a Larran's key's rate is Krystilia's *entire* weighted task
table, run through the wiki's own published formula
(`https://oldschool.runescape.wiki/w/Larran%27s_key`, fetched 2026-08-27):

    P(L) = 1 / (floor(0.3 * (80-L)^2) + 100)   for 0 < L <= 80
    P(L) = 1 / (floor(-5/27 * L) + 115)        for 80 < L <= 350
    P(L) = 1/50                                for L > 350

where `L` is the killed monster's combat level - `key_drop_chance` below,
checked against the page's own worked points: level 1 reads 1/1972, level 80
and 81 both read 1/100 (the two pieces agree exactly at the seam), and level
350 reads 1/50. **Two modifiers the page states, both applied**: a monster
"that requires a certain Slayer level to kill" - `chunk_info.slayer_monsters`
is exactly that list - drops a key 20% more often, checked against a widely
quoted community figure this validates rather than invents: an abyssal demon
(level 124, Slayer-gated) computes to 1/92 unmodified and 1/76.6 with the
bonus, matching "roughly 1 in 76" without either figure being fed in by
hand. And "superior slayer monsters... will always drop a key on death" is
folded in as a flat addition of `slayer.superior_spawns_per_hour` - already
computed for the shared superior-drop-table pricing, and exactly the rate of
"an extra guaranteed key" this wants.

**What is deliberately not modelled: the Wilderness Slayer Cave's further
15%.** The bonus is about *where* a kill happens, not which monster it is,
and nothing this project reads says which of a task's several fighting spots
counts as that specific sub-area - `task_monsters` already collapses Konar's
"category - place" naming for the opposite reason (the monster is the same
wherever it stands). Modelling this would mean guessing which location a
player chooses, which is exactly the shape of invented factor
`costing/__init__.py`'s ordering warns against. Its omission makes this an
**underestimate** of the true rate, stated here rather than hidden.

**Which monster's combat level, per task.** A task can cover several
monsters (`Dwarves` names eight), and nothing states how kills split between
them. Where `slayer.best_modelled_candidate` names the one monster this
map's own kill rate is actually computed from, its combat level is used
alone - the same monster the rate already represents. Failing that (the
ordinary case: most tasks have no `dps_bridge` simulation at all), every
reachable candidate's chance is averaged equally, for want of a real
kill-share to weight by.

A monster the wiki's `infobox_monster` scrape carries no combat level for
(`MonsterStats.combat_level == 0.0`) contributes nothing to its task's
average rather than a guessed level - understating the true rate again, in
the same direction as the cave omission, never overstating it.

**Independent of the `dps` extra, unlike `keyed_chests`.** That module is
wired through `dps_bridge._apply_gated_bosses` because its one candidate
monster's kill time has to come from the fully DPS-resolved rate table this
pipeline stage happens to hold. Krystilia's own economy
(`slayer.master_rates`) needs no such thing - `slayer.task_kills_per_hour`
already falls back to the spreadsheet's own figure with no simulation at
all - so this is wired directly in `estimate.py`'s own builder instead,
where a `MasterRate` for Krystilia is already in hand, and prices a chest
whether or not `osrs-dps` is installed.

Pure arithmetic; the caller supplies the master's rate and every lookup.
"""

from __future__ import annotations

import dataclasses
import math

from chunksim.costing.heuristics import Heuristics, Rate
from chunksim.costing.slayer import (
    MasterRate,
    TaskRate,
    best_modelled_candidate,
    superior_spawns_per_hour,
    task_monsters,
)
from chunksim.model.chunkinfo import ChunkInfo

#: Upstream's own names for the two chests - `skillItems.Nonskill` keys and
#: `Heuristics.monsters` keys alike.
SMALL_CHEST = "Larran's small chest"
BIG_CHEST = "Larran's big chest"

#: One click to use a key once it is in hand - mirrors, rather than imports,
#: `keyed_chests.OPEN_SECONDS` (itself a mirror of
#: `costing.estimate.DEFAULT_ACTION_SECONDS`): four game ticks, the same
#: stand-in every module in this layer spends for "an action nothing states
#: a pace for".
OPEN_SECONDS = 4 * 0.6

#: The formula's own seam, in combat levels.
_LOW_CUTOFF = 80.0
_HIGH_CUTOFF = 350.0

#: The Slayer-requirement bonus - "the drop chance is increased by 20%".
_SLAYER_MONSTER_BONUS = 1.20


def key_drop_chance(combat_level: float) -> float:
    """The wiki's own piecewise formula, before either modifier.

    `combat_level <= 0` is "unknown", not "level zero", and returns `0.0` -
    a caller must treat that as a missing figure rather than an impossible
    monster.
    """
    if combat_level <= 0:
        return 0.0
    if combat_level <= _LOW_CUTOFF:
        denominator = math.floor(0.3 * (_LOW_CUTOFF - combat_level) ** 2) + 100
    elif combat_level <= _HIGH_CUTOFF:
        denominator = math.floor(-5.0 / 27.0 * combat_level) + 115
    else:
        return 1.0 / 50.0
    return 1.0 / denominator if denominator > 0 else 0.0


def _requires_slayer_level(chunk_info: ChunkInfo, monster: str) -> bool:
    """Whether `monster` is one the wiki means by "requires a certain Slayer
    level to kill" - `chunk_info.slayer_monsters`'s own membership, keyed
    (like `slayer.task_monsters`'s callers already have to allow for) by a
    bare name or by `name#variant`."""
    return any(
        key.split("#", 1)[0].strip() == monster for key in chunk_info.slayer_monsters
    )


def _monster_key_chance(chunk_info: ChunkInfo, heuristics: Heuristics, monster: str) -> float | None:
    """One kill's key chance for `monster`, or `None` where the wiki states
    no combat level for it at all."""
    stats = heuristics.monster_stats.get(monster)
    if stats is None or stats.combat_level <= 0:
        return None
    chance = key_drop_chance(stats.combat_level)
    if _requires_slayer_level(chunk_info, monster):
        chance *= _SLAYER_MONSTER_BONUS
    return chance


def _task_key_chance(
    chunk_info: ChunkInfo,
    heuristics: Heuristics,
    reachable_monsters: frozenset[str],
    task: TaskRate,
) -> float:
    """One kill's key chance for `task`, over whichever monster(s) it covers.

    See the module docstring: the `dps`-modelled candidate alone when one
    exists (it is who the task's own `kills_per_hour` already represents),
    else an equal average over every reachable candidate.
    """
    candidates = task_monsters(chunk_info, task.task) & reachable_monsters
    if not candidates:
        return 0.0
    modelled = best_modelled_candidate(chunk_info, heuristics, task.task, reachable_monsters)
    names = (modelled[0],) if modelled is not None else tuple(sorted(candidates))
    chances = [
        chance
        for name in names
        if (chance := _monster_key_chance(chunk_info, heuristics, name)) is not None
    ]
    return sum(chances) / len(chances) if chances else 0.0


def keys_per_hour(
    master: MasterRate,
    chunk_info: ChunkInfo,
    heuristics: Heuristics,
    reachable_monsters: frozenset[str],
) -> float:
    """Expected Larran's keys per hour slaying for `master`.

    Shaped exactly like `slayer.superior_rolls_per_hour`: a weight-share
    average over every assignable task, divided by the master's own average
    assignment length so a long task's kills count for longer than a short
    one's. The guaranteed key off a superior spawn is a flat addition on top
    - see the module docstring on why it is not folded into the per-kill
    average instead.
    """
    if master.average_hours <= 0:
        return 0.0
    total_weight = sum(entry.weight for entry in master.tasks)
    if total_weight <= 0:
        return 0.0

    per_assignment = 0.0
    for task in master.tasks:
        chance = _task_key_chance(chunk_info, heuristics, reachable_monsters, task)
        if chance > 0:
            per_assignment += (task.weight / total_weight) * task.mean_count * chance
    ordinary = per_assignment / master.average_hours
    return ordinary + superior_spawns_per_hour(master, chunk_info, heuristics)


def effective_seconds(rate_per_hour: float) -> float | None:
    """One key's worth of slaying, plus opening the chest with it - `None`
    where nothing prices a key at all."""
    if rate_per_hour <= 0:
        return None
    return 3600.0 / rate_per_hour + OPEN_SECONDS


def priced(
    heuristics: Heuristics,
    master: MasterRate | None,
    chunk_info: ChunkInfo,
    reachable_monsters: frozenset[str],
) -> Heuristics:
    """`heuristics` with both chests' opens-per-hour synthesised from
    `master` (Krystilia's own rate, or `None` where she cannot be reached at
    all, in which case this is a no-op).

    **Written explicitly, even at `0.0`, never left absent** - the same rule
    `dps_bridge._apply_gated_bosses` follows for the same reason:
    `Heuristics.kills_per_hour` falls through to `DEFAULT_KPH` for anything
    it has not heard of, and a chest has no stat block to be heard of
    *from*. Both chest names take the identical rate: a key opens either
    one, and a player farming a specific chest spends every key on it.
    """
    if master is None:
        return heuristics
    total = effective_seconds(keys_per_hour(master, chunk_info, heuristics, reachable_monsters))
    value = 3600.0 / total if total is not None and total > 0 else 0.0
    rate = Rate(value=value, source="derived:Larran's key", match="keyed")
    return dataclasses.replace(
        heuristics,
        monsters={**heuristics.monsters, SMALL_CHEST: rate, BIG_CHEST: rate},
    )
