"""The Tombs of Amascut: an invocation dial, and the level that pays best.

Phase three, and the raid whose reward is a *function of a setting* rather
than of a mode. Raising the invocation level makes every room harder and every
unique likelier, so the answer is an optimisation over the dial rather than a
choice between two doors - which is the thing neither the Theatre nor the
Chambers asked for.

### Points are damage here, and that is the contrast worth keeping

`costing/xeric.py` had to take its point total from a guide because the
Chambers' points come mostly from braziers and grubs. The Tombs states the
opposite outright: "room points are awarded per damage dealt to every NPC in
the raid. For most NPCs, 1 damage dealt equates to 1 room point", and then
tabulates the exceptions - Ba-Ba at 2x, Zebak at 1.5x, the Wardens at 2x and
2.5x across their phases, Kephri's scarabs at 0.5x and the Warden's core at
**zero**.

So this model *derives* its points from the health it is already scaling, and
the two raids' modules read differently for a reason rather than by accident.

Three caps ride on top, all published: 20,000 room points a room, 64,000
reward points overall, and the 5,000 a player starts with being subtracted
again at the end.

**The known understatement, and it is large.** `ROOMS` is six health bars and
a raid scores on *every* NPC in it - Kephri's scarabs and swarms, the Apmeken
baboons, the obelisks, Het's seal, the core - so the points here are a floor
rather than the total. Measured against the published 64,000 cap the gap is
about fourfold, which pushes the unique chance down and the raids-for-a-drop
up.

Which direction that biases the *answer* is worth stating, because it is the
safe one: understated points make drops look slower, so they make the cape
look **less** likely to bind. Every conclusion below of the form "the cape
binds" is therefore conservative, and closing the gap would only strengthen
it.

### The unique chance, which is where the dial bites

"Players will have a 1% chance to receive a unique item for every
`10,500 - 20 x RL` total reward points", where `RL` is the raid level bent
through a piecewise function that flattens twice - once above 310 and again
above 430. `scaled_raid_level` is that function and the wiki's own worked
example checks it: raid level 400 gives 3,700 points per percent.

**Unlike the Chambers, excess points do not roll again.** The chest caps at
55% and stops - "excess points will not contribute towards a second roll" - so
a Tombs raid is worth at most one unique however well it goes.

The unique *table* moves with the level too, and in the player's favour: the
fang and the lightbearer thin out above 305 while everything else thickens, so
a higher level is better twice over. `WEIGHTS` is that table as published, at
the five levels the wiki gives, and `weights_at` interpolates nothing - it
takes the nearest published row at or below the level, because a table with
five rows is a set of measurements rather than a curve.

### What actually decides it

`Icthlarin's shroud (tier 5)` wants **2,000 completions**, and the export
carries all five tiers as collection log entries - so the shroud is not
optional and entry mode cannot count towards it. That is why `TIERS` exists
and why entry is excluded from the defaults: a raid level below 150 is faster
and worth nothing towards the only constraint that binds.

The model computes both bounds and reports which won, rather than assuming.

Pure: the valid set and a stat lookup, both handed in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from chunksim.costing import encounter
from chunksim.costing.encounter import (
    EXPERIENCE,
    FightPlan,
    KillSeconds,
    Mechanic,
    Objective,
    PuzzlePlan,
    UNIQUE,
)

LOOT_TASK = "Loot a mask of rebirth from the Tombs of Amascut*"

#: `target -> (seconds to kill, hitpoints)`, or `None`. **Two numbers because
#: the points are the damage**: this raid needs the health it is fighting as
#: well as how long it takes, which the Chambers never did.
StatsFor = Callable[[str], "tuple[float, float] | None"]

ENTRY, NORMAL, EXPERT = "entry", "normal", "expert"

#: The invocation bands the game names, by raid level.
TIERS: Mapping[str, tuple[int, int]] = {
    ENTRY: (0, 149),
    NORMAL: (150, 299),
    EXPERT: (300, 600),
}


def tier_of(raid_level: int) -> str:
    """Which band `raid_level` falls in."""
    for tier, (low, high) in TIERS.items():
        if low <= raid_level <= high:
            return tier
    return EXPERT


#: The four path bosses and then the Wardens, with the point multiplier each
#: pays. **Published**, and the zero is as load-bearing as the rest: the
#: Warden's core is fought and scores nothing.
ROOMS: tuple[tuple[str, str, float], ...] = (
    ("Akkha", "Akkha", 1.0),
    ("Ba-Ba", "Ba-Ba", 2.0),
    ("Kephri", "Kephri#Aggressive", 1.0),
    ("Zebak", "Zebak#Normal", 1.5),
    ("Wardens (phase 2)", "Tumeken's Warden#Active", 2.0),
    ("Wardens (phase 3)", "Elidinis' Warden#Enraged", 2.5),
)

#: Walking, looting and the puzzle rooms between the bosses. **Invented.**
OVERHEAD_SECONDS = 300.0

#: Share of a raid spent dealing damage, as the other two use it. **Invented.**
UPTIME = 0.66

#: "Players start the raid with 5,000 total reward points", and "at the end of
#: the raid, the starting 5,000 points are subtracted when calculating loot".
STARTING_POINTS = 5_000.0

#: "Capped at 20,000 room points" and "capped at 64,000 total points".
ROOM_POINT_CAP = 20_000.0
TOTAL_POINT_CAP = 64_000.0

#: "A maximum rate of 55% to see a unique", and unlike the Chambers there is
#: no second roll: "excess points will not contribute towards a second roll".
MAX_UNIQUE_CHANCE = 0.55

#: The published weights, per raid level, as `1/n` chances that sum to one.
WEIGHTS: Mapping[int, Mapping[str, float]] = {
    150: {
        "Osmumten's fang": 1 / 3.43, "Lightbearer": 1 / 3.43,
        "Elidinis' ward": 1 / 8, "Masori mask": 1 / 12,
        "Masori body": 1 / 12, "Masori chaps": 1 / 12,
        "Tumeken's shadow (uncharged)": 1 / 24,
    },
    350: {
        "Osmumten's fang": 1 / 3.67, "Lightbearer": 1 / 3.67,
        "Elidinis' ward": 1 / 7.33, "Masori mask": 1 / 11,
        "Masori body": 1 / 11, "Masori chaps": 1 / 11,
        "Tumeken's shadow (uncharged)": 1 / 22,
    },
    400: {
        "Osmumten's fang": 1 / 4.75, "Lightbearer": 1 / 3.8,
        "Elidinis' ward": 1 / 6.33, "Masori mask": 1 / 9.5,
        "Masori body": 1 / 9.5, "Masori chaps": 1 / 9.5,
        "Tumeken's shadow (uncharged)": 1 / 19,
    },
    450: {
        "Osmumten's fang": 1 / 4.5, "Lightbearer": 1 / 4.5,
        "Elidinis' ward": 1 / 6, "Masori mask": 1 / 9,
        "Masori body": 1 / 9, "Masori chaps": 1 / 9,
        "Tumeken's shadow (uncharged)": 1 / 18,
    },
    500: {
        "Osmumten's fang": 1 / 5.5, "Lightbearer": 1 / 4.71,
        "Elidinis' ward": 1 / 5.5, "Masori mask": 1 / 8.25,
        "Masori body": 1 / 8.25, "Masori chaps": 1 / 8.25,
        "Tumeken's shadow (uncharged)": 1 / 16.5,
    },
}

#: `Icthlarin's shroud (tier 5)`, and the export carries all five tiers as
#: collection log entries - so it is not optional.
CAPE_COMPLETIONS = 2_000

#: The lowest level that counts towards the shroud, and therefore the lowest
#: worth running at all for a collection log.
LOWEST_COUNTING_LEVEL = 150


def scaled_raid_level(raid_level: float) -> float:
    """`RL`, the raid level bent through the chest's own piecewise function.

    It flattens twice - above 310 and again above 430 - which is what makes a
    very high invocation worth less than it looks and the optimisation
    interesting rather than monotone-obvious.
    """
    if raid_level <= 310:
        return float(raid_level)
    if raid_level <= 430:
        return 310 + (raid_level - 310) / 3
    return 350 + (raid_level - 430) / 6


def points_per_percent(raid_level: float) -> float:
    """`10,500 - 20 x RL` - points bought for one percent of a unique."""
    return 10_500.0 - 20.0 * scaled_raid_level(raid_level)


def unique_chance(points: float, raid_level: float) -> float:
    """The chance one raid gives a unique, capped and never rolled twice."""
    per = points_per_percent(raid_level)
    if per <= 0 or points <= 0:
        return 0.0
    return min(MAX_UNIQUE_CHANCE, points / (per * 100.0))


def weights_at(raid_level: int) -> Mapping[str, float]:
    """The published table at or below `raid_level`.

    **Nearest published row, not an interpolation.** Five rows is a set of
    measurements; drawing a curve through them would invent weights the game
    never stated and hide which of the five a figure came from.
    """
    rows = [level for level in WEIGHTS if level <= max(raid_level, LOWEST_COUNTING_LEVEL)]
    return WEIGHTS[max(rows) if rows else min(WEIGHTS)]


def plans(stats: Mapping[str, tuple[float, float]]) -> tuple[FightPlan | PuzzlePlan, ...]:
    """One run's rooms, in the order the raid fights them."""
    found: list[FightPlan | PuzzlePlan] = [
        FightPlan(name=room, target=target) for room, target, _ in ROOMS
    ]
    found.append(PuzzlePlan(name="paths and walking", seconds=OVERHEAD_SECONDS))
    return tuple(found)


def mechanics() -> dict[str, Mechanic]:
    note = "share of a Tombs raid spent attacking"
    return {target: Mechanic(uptime=UPTIME, note=note) for _r, target, _m in ROOMS}


def points_for(stats: Mapping[str, tuple[float, float]]) -> float:
    """Reward points one raid scores, from the damage it deals.

    Each room's damage times its published multiplier, capped per room, summed,
    capped overall, and then the starting 5,000 taken back off.
    """
    total = 0.0
    for _room, target, multiplier in ROOMS:
        found = stats.get(target)
        if found is None:
            continue
        _seconds, hitpoints = found
        total += min(ROOM_POINT_CAP, hitpoints * multiplier)
    return max(0.0, min(TOTAL_POINT_CAP, total + STARTING_POINTS) - STARTING_POINTS)


def item_chances(
    stats: Mapping[str, tuple[float, float]], raid_level: int
) -> dict[str, float]:
    """`{item: chance one raid gives it}` at `raid_level`."""
    chance = unique_chance(points_for(stats), raid_level)
    return {item: chance * weight for item, weight in weights_at(raid_level).items()}


@dataclass(frozen=True)
class Answer:
    """What one raid level costs for one objective."""

    raid_level: int
    run: encounter.Encounter
    runs: float
    bound_by: str = "drops"

    @property
    def tier(self) -> str:
        return tier_of(self.raid_level)

    @property
    def seconds(self) -> float:
        return self.run.seconds * self.runs

    @property
    def hours(self) -> float:
        return self.seconds / 3600.0


def answer(
    raid_level: int,
    stats_for: StatsFor,
    objective: Objective = encounter.FULL_LOG,
    party_size: int = 1,
) -> Answer | None:
    """One raid level priced, or `None` if a room cannot be priced."""
    stats: dict[str, tuple[float, float]] = {}
    for _room, target, _multiplier in ROOMS:
        found = stats_for(target)
        if found is None:
            return None
        stats[target] = found

    def seconds(target: str) -> float | None:
        got = stats.get(target)
        return got[0] if got else None

    run = encounter.build(
        f"Tombs of Amascut ({raid_level})",
        plans(stats),
        seconds,
        mechanics(),
        attackers=party_size,
    )
    if run is None:
        return None
    chances = item_chances(stats, raid_level)
    if objective.kind == UNIQUE:
        return Answer(raid_level, run, encounter.expected_runs(chances.get(objective.item, 0.0)))
    if objective.kind == EXPERIENCE:
        return None
    drops = encounter.runs_for_all(list(chances.values()))
    if raid_level < LOWEST_COUNTING_LEVEL:
        # **Entry raids count for nothing.** The shroud is a collection log
        # entry and entry mode does not advance it, so a faster raid below 150
        # buys a log that never closes.
        return Answer(raid_level, run, float("inf"), bound_by="cape")
    cape = float(CAPE_COMPLETIONS)
    return Answer(
        raid_level, run, max(drops, cape),
        bound_by="cape" if cape >= drops else "drops",
    )


#: The levels `best` searches. The published weight rows plus the band edges,
#: because those are where the answer can change.
SEARCH_LEVELS: tuple[int, ...] = (150, 200, 250, 300, 350, 400, 450, 500, 550, 600)


def best(
    stats_for: Callable[[int], StatsFor],
    objective: Objective = encounter.FULL_LOG,
    party_size: int = 1,
    levels: Sequence[int] = SEARCH_LEVELS,
) -> Answer | None:
    """The raid level that reaches `objective` soonest.

    **A factory per level**, for `costing/xeric.py`'s reason one step further:
    the invocation level is a scaling input, so every level is the same
    monsters at different health and one lookup would price them all alike.
    """
    found = [
        got
        for level in levels
        if (got := answer(level, stats_for(level), objective, party_size)) is not None
    ]
    priced = [got for got in found if got.seconds < float("inf")]
    return min(priced, key=lambda got: got.seconds) if priced else None
