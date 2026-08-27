"""The brimstone chest: what a key really costs, Konar's own twin of Larran's.

Same shape of gap `costing/larran.py` already closed for Larran's small and big
chests. `Brimstone chest` is a `skillItems.Nonskill` activity (like both
Larran's chests) the item walk reaches directly whenever something inside
wants pricing, reading the chest as an ordinary monster-shaped source and
asking `Heuristics.kills_per_hour` how often it opens. It has no stat block,
so that call fell to `DEFAULT_KPH["regular"]`, 150/hr, and every item inside -
an uncut ruby, a rune platebody, dragon arrowtips - priced as though the chest
opened on demand.

**The key is the whole cost, and there is exactly one way to earn one:
Konar quo Maten's slayer tasks** (`Brimstone key`: "players can acquire [it]
from slaying monsters assigned by Konar", the wiki's own words). So, exactly
like `larran.py`, this is not `keyed_chests`' fixed per-monster fraction - it
is Konar's *entire* weighted task table, run through the wiki's own published
formula (`https://oldschool.runescape.wiki/w/Brimstone_key`, fetched
2026-08-27):

    P(L) = 1 / (100 + floor((100-L)^2 / 5))   for 0 < L < 100
    P(L) = 1 / (120 - floor(L/5))              for 100 <= L <= 350
    P(L) = 1/50                                for L > 350

where `L` is the killed monster's combat level - `key_drop_chance` below,
checked against the page's own worked continuity (the two pieces agree
exactly at the `L=100` seam) and against the cap at `L=350`. **Cross-checked,
not fitted**: run against this project's own scraped combat levels and the
export's own per-monster `Brimstone key` drop fractions, 66 of 74 real
monsters land within 3% of the formula's own answer - strong enough to trust
the shape without claiming every one of the residual eight is this formula's
fault. At least one of those eight is not: this project's own combat-level
scrape disagrees with itself between two monsters (`Ankou` and `Fire giant`
read `86` and `104` respectively in `wiki_rates.json`, the wrong way round
against their well-known real levels), a scrape-quality question for another
day rather than a reason to distrust the formula quoted above. **One modifier
the page states, applied**: a monster "that has a Slayer level requirement" -
`chunk_info.slayer_monsters` is exactly that list, reused unchanged from
`larran.py` - gets a 20% boost. **And "a brimstone key is always dropped by a
superior slayer monster assigned by Konar"** is folded in as a flat addition
of `slayer.superior_spawns_per_hour`, exactly as `larran.py` does for the
identical wording about Larran's key.

**What is different from Larran's key, and simpler**: no analogue of the
Wilderness Slayer Cave's further 15% is published for the brimstone key at
all, so there is nothing else this module declines to model. **What is the
same**: which monster's combat level, per task (`slayer.best_modelled_
candidate` where one exists, else an equal average over every reachable
candidate - see `larran.py`'s own docstring on why), and a monster the wiki's
`infobox_monster` scrape carries no combat level for contributes nothing to
its task's average rather than a guessed level.

**Independent of the `dps` extra, unlike `keyed_chests`**, for the same reason
`larran.py` is: Konar's own economy (`slayer.master_rates`) needs no
DPS-resolved rate table, so this is wired directly in `estimate.py`'s own
builder, where a `MasterRate` for Konar is already in hand.

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

#: Upstream's own name for the chest - a `skillItems.Nonskill` key and a
#: `Heuristics.monsters` key alike.
CHEST = "Brimstone chest"

#: One click to use a key once it is in hand - mirrors `larran.OPEN_SECONDS`,
#: itself a mirror of `costing.estimate.DEFAULT_ACTION_SECONDS`.
OPEN_SECONDS = 4 * 0.6

#: The formula's own seam, in combat levels.
_LOW_CUTOFF = 100.0
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
    if combat_level < _LOW_CUTOFF:
        denominator = math.floor((_LOW_CUTOFF - combat_level) ** 2 / 5.0) + 100
    elif combat_level <= _HIGH_CUTOFF:
        denominator = 120 - math.floor(combat_level / 5.0)
    else:
        return 1.0 / 50.0
    return 1.0 / denominator if denominator > 0 else 0.0


def _requires_slayer_level(chunk_info: ChunkInfo, monster: str) -> bool:
    """Whether `monster` is one the wiki means by "requires a certain Slayer
    level to kill" - see `larran._requires_slayer_level`, reused unchanged."""
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
    """Expected brimstone keys per hour slaying for `master`.

    Shaped exactly like `larran.keys_per_hour`: a weight-share average over
    every assignable task, divided by the master's own average assignment
    length so a long task's kills count for longer than a short one's. The
    guaranteed key off a superior spawn is a flat addition on top - see the
    module docstring on why it is not folded into the per-kill average
    instead.
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
    """`heuristics` with the chest's opens-per-hour synthesised from `master`
    (Konar's own rate, or `None` where she cannot be reached at all, in which
    case this is a no-op).

    **Written explicitly, even at `0.0`, never left absent** - see
    `larran.priced`'s own docstring for why: `Heuristics.kills_per_hour` falls
    through to `DEFAULT_KPH` for anything it has not heard of, and the chest
    has no stat block to be heard of *from*.
    """
    if master is None:
        return heuristics
    total = effective_seconds(keys_per_hour(master, chunk_info, heuristics, reachable_monsters))
    value = 3600.0 / total if total is not None and total > 0 else 0.0
    rate = Rate(value=value, source="derived:Brimstone key", match="keyed")
    return dataclasses.replace(heuristics, monsters={**heuristics.monsters, CHEST: rate})
