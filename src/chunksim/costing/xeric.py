"""The Chambers of Xeric: a random layout, a point system, and 2,000 raids.

Phase two of the raid work, and the one that exercises what the Theatre never
did - `costing/encounter.py` handles a run whose rooms are *drawn* rather than
fixed, and a reward that is a function of points rather than a flat chance.

### The layout, and why this prices a mean rather than a draw

A normal raid is three floors: two of rooms and one holding the Great Olm. Each
of the first two carries "one resource room, one or two scavenger rooms, and
two or three combat and/or skilling rooms", so a raid fights **four to six** of
the twelve combat and skilling rooms and always ends at Olm.

This prices the *expected* raid: every room contributes its duration times the
chance it appears. That is what a rate wants - a player running 2,000 raids
gets the mean, not a layout - and it is why there is no random draw here and
nothing seeded. `costing/runs/` is where this project simulates; a cost model
integrates.

**Challenge Mode has no layout at all.** Every combat and puzzle room is
present, over four floors rather than three, and every enemy but Olm has its
stats and health raised - `osrs-dps` implements that as
`RaidInputs.challenge_mode` and it comes out at exactly 1.5x health on
everything except Olm, who is untouched, which is what the wiki says in words.
There are no `#Challenge Mode` monsters in the library and there should not be.

### Points, which are not damage

The obvious model is wrong and worth recording. A solo normal raid's rooms and
Olm come to about 4,300 hitpoints, and `Money making guide/Chambers of Xeric`
says "a solo deathless raid will generally yield around 30,000 points" - seven
times more. Points are dominated by the *skilling* sources, not the fighting:
the Ice Demon's braziers alone cap "at about 6050 points", the Thieving room
pays "115 points per grub" against a 30-grub solo minimum, and potions, food,
shortcuts and the storage unit are all capped sources on top.

So `SOLO_NORMAL_POINTS` is the guide's own 30,000 rather than anything derived,
and the check is that it reproduces the guide's other two figures: 30,000 over
`POINTS_PER_PERCENT` is 3.46%, against its stated "roughly a 3.4% chance" and
"~1/33 drop rate".

**Challenge Mode's points are not published**, and this is the weakest number
in the module. It fights every room instead of five of twelve and adds a floor,
so `CM_POINT_MULTIPLIER` scales the normal figure by the room count and says so;
the 5,000 the wiki *does* publish for a fast completion is added on top of it.

### The chest

Fully published, and the arithmetic is exact rather than approximate. "For
every 8,676 total points obtained, a 1% chance to obtain a unique loot is
given", capped at **65.7%** at 570,000 points, after which the surplus rolls
again - the wiki's own worked example is 855,000 points giving 65.7% then
32.85% - to a maximum of six rolls. `unique_rolls` is that, and it is a *sum of
chances* rather than one chance, which is why a raid can be worth more than one
unique.

### What decides the answer, which is not the drop rate

Two rewards exist only in Challenge Mode - the twisted ancestral colour kit at
1/75 and metamorphic dust at 1/400, both gated on finishing inside the time the
wiki tabulates - so a collection log cannot be closed by normal raids however
fast they run. And `Xeric's champion` wants **2,000 Challenge Mode
completions**, counted separately from normal ones.

At 1/75 those 2,000 raids are worth about 26 colour kits, so the kit is not the
constraint and neither is any unique: **the cape is**, and the green-log answer
is very nearly "how fast can 2,000 Challenge Mode raids be run". The model says
so by computing both and taking the larger, rather than by asserting it.

Pure: the valid set and a kill-time lookup, both handed in.
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

#: `mode -> a kill-time lookup for that mode`. See `answer` on why this is a
#: factory where the Theatre needs only a lookup.
KillSecondsFor = Callable[[str], KillSeconds]

LOOT_TASK = "Chambers of Xeric loot*"

NORMAL, CHALLENGE = "normal", "challenge"

#: The seven combat rooms, each as the targets one clear fights. Muttadile is
#: two crocodiles and Vespula's room holds her portal; the library models both
#: apart, and a raid kills all of them.
COMBAT_ROOMS: Mapping[str, tuple[str, ...]] = {
    "Tekton": ("Tekton#Normal",),
    "Muttadile": ("Muttadile#Small", "Muttadile#Large"),
    "Vespula": ("Vespula#Normal", "Abyssal portal#Normal"),
    "Vasa Nistirio": ("Vasa Nistirio#Normal",),
    "Vanguards": ("Vanguard#Melee", "Vanguard#Ranged", "Vanguard#Magic"),
    "Lizardman shamans": ("Lizardman shaman (Chambers of Xeric)#Normal",),
    "Skeletal mystics": ("Skeletal Mystic#Normal",),
}

#: The four skilling rooms, timed outright. **Invented**, which is one of the
#: reasons every figure here is a `GUESS` - the wiki's guides solve each of
#: these to a routine but publish no clock for any of them.
PUZZLE_ROOMS: Mapping[str, float] = {
    # **The Guardians are a mining room, not a fight**, which `osrs-dps`
    # says by refusing to price one: they take no damage from a weapon and
    # are broken down with a pickaxe, which is why `RaidInputs` carries a
    # `party_sum_mining_level` at all. Listing them as combat priced the
    # whole raid at nothing, since one unpriceable room drops the run.
    "Guardians": 120.0,
    "Crabs": 60.0,
    "Ice demon (braziers)": 150.0,
    "Tightrope": 60.0,
    "Thieving": 120.0,
}

#: The Great Olm, always the last room and three targets.
OLM: tuple[str, ...] = (
    "Great Olm#Left claw (Normal)",
    "Great Olm#Right claw (Normal)",
    "Great Olm#Head (Normal)",
)

#: "Two or three combat and/or skilling rooms" on each of two floors.
NORMAL_ROOMS_LOW, NORMAL_ROOMS_HIGH = 4, 6

#: Seconds of walking, banking and scavenging a raid carries whatever it
#: fights. **Invented.**
OVERHEAD_SECONDS = 240.0

#: Share of a raid spent dealing damage, as `costing/theatre.py` uses it and
#: for the same reason. **Invented.**
UPTIME = 0.66

#: `Money making guide/Chambers of Xeric`, normal mode: `kph = 3`.
PUBLISHED_RAIDS_PER_HOUR = 3.0
PUBLISHED_SECONDS = 3600.0 / PUBLISHED_RAIDS_PER_HOUR

#: The same guide: "a solo deathless raid will generally yield around 30,000
#: points". **Published**, and the anchor the whole reward half rests on.
SOLO_NORMAL_POINTS = 30_000.0

#: "For every 8,676 total points obtained, a 1% chance ... is given."
#:
#: **The two pages disagree by one point** - `Ancient chest` writes 8,676 and
#: `Chambers of Xeric/Strategies` writes 8,675 - and the cap does not settle
#: it, since 570,000 over either rounds to the 65.7% both quote. The chest's
#: figure is taken, being the page about the chest; the difference is a
#: thousandth of a percent on a roll.
POINTS_PER_PERCENT = 8_676.0

#: The cap, and the points that reach it.
MAX_ROLL_CHANCE = 0.657
POINTS_PER_ROLL = 570_000.0

#: "Up to six unique rewards can be obtained per raid."
MAX_ROLLS = 6

#: Points a Challenge Mode completion inside the time adds. **Published.**
CM_COMPLETION_POINTS = 5_000.0

#: How much more a Challenge Mode raid scores than a normal one. **Not
#: published** - the wiki says only "much higher" - so this is the ratio of
#: rooms fought, every room against the mean normal draw, and it is the
#: weakest number here.
CM_POINT_MULTIPLIER = (len(COMBAT_ROOMS) + len(PUZZLE_ROOMS)) / (
    (NORMAL_ROOMS_LOW + NORMAL_ROOMS_HIGH) / 2
)

#: The unique tables, as `Ancient chest` publishes them.
UNIQUE_TABLE: Mapping[str, Mapping[str, float]] = {
    NORMAL: {
        "Dexterous prayer scroll": 14 / 60,
        "Arcane prayer scroll": 14 / 60,
        "Twisted buckler": 4 / 60,
        "Dragon hunter crossbow": 4 / 60,
        "Dinh's bulwark": 3 / 60,
        "Ancestral hat": 4 / 60,
        "Ancestral robe top": 4 / 60,
        "Ancestral robe bottom": 4 / 60,
        "Dragon claws": 3 / 60,
        "Elder maul": 2 / 60,
        "Kodai insignia": 2 / 60,
        "Twisted bow": 2 / 60,
    },
    CHALLENGE: {
        "Dexterous prayer scroll": 12 / 56,
        "Arcane prayer scroll": 12 / 56,
        "Twisted buckler": 4 / 56,
        "Dragon hunter crossbow": 4 / 56,
        "Dinh's bulwark": 3 / 56,
        "Ancestral hat": 4 / 56,
        "Ancestral robe top": 4 / 56,
        "Ancestral robe bottom": 4 / 56,
        "Dragon claws": 3 / 56,
        "Elder maul": 2 / 56,
        "Kodai insignia": 2 / 56,
        "Twisted bow": 2 / 56,
    },
}

#: Rewards **only Challenge Mode can give**, and their published chances. Both
#: are gated on finishing inside the tabulated time.
CHALLENGE_ONLY: Mapping[str, float] = {
    "Twisted ancestral colour kit": 1 / 75,
    "Metamorphic dust": 1 / 400,
}

#: `Xeric's champion`, and the reason this raid's answer is a completion count
#: rather than a drop rate. Counted separately from normal raids.
CAPE_COMPLETIONS = 2_000

#: The solo time a Challenge Mode raid must beat for the kit, the dust and the
#: 5,000 points. **Published**, and a bound this model's own duration is
#: checked against rather than fitted to.
CM_SOLO_TIME_LIMIT_SECONDS = 70.0 * 60.0


def expected_normal_rooms() -> float:
    """How many of the twelve a normal raid draws, on average."""
    return (NORMAL_ROOMS_LOW + NORMAL_ROOMS_HIGH) / 2


def room_share(mode: str) -> float:
    """The chance any one room is in a raid of `mode`.

    One for Challenge Mode, which fights all of them; the drawn fraction
    otherwise. **A mean rather than a draw** - see the module docstring.
    """
    if mode == CHALLENGE:
        return 1.0
    return expected_normal_rooms() / (len(COMBAT_ROOMS) + len(PUZZLE_ROOMS))


def plans(mode: str) -> tuple[FightPlan | PuzzlePlan, ...]:
    """One expected run's rooms, ending at Olm."""
    share = room_share(mode)
    found: list[FightPlan | PuzzlePlan] = []
    for room, targets in COMBAT_ROOMS.items():
        for target in targets:
            found.append(FightPlan(name=room, target=target, count=share))
    for room, seconds in PUZZLE_ROOMS.items():
        found.append(PuzzlePlan(name=room, seconds=seconds * share))
    for target in OLM:
        found.append(FightPlan(name="Great Olm", target=target))
    found.append(PuzzlePlan(name="walking and scavenging", seconds=OVERHEAD_SECONDS))
    return tuple(found)


def mechanics() -> dict[str, Mechanic]:
    """`UPTIME` against every fight - one number, as the Theatre does it."""
    note = "share of a Chambers raid spent attacking"
    targets = [t for ts in COMBAT_ROOMS.values() for t in ts] + list(OLM)
    return {target: Mechanic(uptime=UPTIME, note=note) for target in targets}


def points_for(mode: str, fast: bool = True) -> float:
    """Team points one raid of `mode` scores.

    `fast` is whether a Challenge Mode raid finished inside the tabulated
    time, which is what the published 5,000 rides on.
    """
    if mode != CHALLENGE:
        return SOLO_NORMAL_POINTS
    points = SOLO_NORMAL_POINTS * CM_POINT_MULTIPLIER
    return points + (CM_COMPLETION_POINTS if fast else 0.0)


def unique_rolls(points: float) -> float:
    """Expected uniques from `points`, as `Ancient chest` describes them.

    **A sum of chances, not one chance**, which is what lets a raid be worth
    more than one unique: each full `POINTS_PER_ROLL` is a capped roll and the
    surplus rolls once more at its own rate, to `MAX_ROLLS`.
    """
    if points <= 0:
        return 0.0
    total = 0.0
    left = points
    for _ in range(MAX_ROLLS):
        if left <= 0:
            break
        chance = min(MAX_ROLL_CHANCE, left / (POINTS_PER_PERCENT * 100.0))
        total += chance
        left -= POINTS_PER_ROLL
    return total


def item_chances(mode: str, fast: bool = True) -> dict[str, float]:
    """`{item: expected number of it per raid}`.

    Challenge Mode's two exclusives ride alongside the shared table rather
    than inside it: they are separate rolls on the same chest.
    """
    rolls = unique_rolls(points_for(mode, fast))
    found = {
        item: rolls * weight for item, weight in UNIQUE_TABLE[mode].items()
    }
    # **Every mode names every item, including the ones it cannot give.**
    # A normal raid that simply omitted the colour kit and the dust would
    # have `runs_for_all` closing a log that is two items short of closed -
    # 821 hours against an honest infinity. Naming them at zero is what makes
    # "normal mode can never green-log this raid" arithmetic rather than a
    # comment.
    for item, chance in CHALLENGE_ONLY.items():
        found[item] = chance if (mode == CHALLENGE and fast) else 0.0
    return found


@dataclass(frozen=True)
class Answer:
    """What one mode costs for one objective."""

    mode: str
    run: encounter.Encounter
    runs: float
    #: What forced the run count, for a reader: `"drops"` or `"cape"`.
    bound_by: str = "drops"

    @property
    def seconds(self) -> float:
        return self.run.seconds * self.runs

    @property
    def hours(self) -> float:
        return self.seconds / 3600.0


def answer(
    mode: str,
    kill_seconds_for: "KillSecondsFor",
    objective: Objective = encounter.FULL_LOG,
    party_size: int = 1,
) -> Answer | None:
    """`mode` priced for `objective`, or `None` if a room cannot be priced.

    **`kill_seconds_for` is a factory rather than a lookup**, and that is a
    difference from `costing/theatre.py` worth knowing: the Theatre's modes are
    *separate monsters* in `osrs-dps`, so one lookup answers for all three,
    while Challenge Mode is the same monsters under
    `RaidInputs.challenge_mode`. A single lookup would have priced Challenge
    Mode at normal-mode health.
    """
    run = encounter.build(
        f"Chambers of Xeric ({mode})",
        plans(mode),
        kill_seconds_for(mode),
        mechanics(),
        attackers=party_size,
    )
    if run is None:
        return None
    fast = run.seconds <= CM_SOLO_TIME_LIMIT_SECONDS
    chances = item_chances(mode, fast)
    if objective.kind == UNIQUE:
        return Answer(mode, run, encounter.expected_runs(chances.get(objective.item, 0.0)))
    if objective.kind == EXPERIENCE:
        return None
    drops = encounter.runs_for_all(list(chances.values()))
    if mode != CHALLENGE:
        # **Normal raids can never close the log**, and `item_chances` has
        # already made that infinite rather than merely large: the colour kit
        # and the dust are Challenge Mode's alone.
        return Answer(mode, run, drops, bound_by="drops")
    cape = float(CAPE_COMPLETIONS)
    return Answer(
        mode, run, max(drops, cape), bound_by="cape" if cape >= drops else "drops"
    )


def best(
    kill_seconds_for: "KillSecondsFor",
    objective: Objective = encounter.FULL_LOG,
    party_size: int = 1,
    modes: Sequence[str] = (NORMAL, CHALLENGE),
) -> Answer | None:
    """The fastest mode for `objective`."""
    found = [
        got
        for mode in modes
        if (got := answer(mode, kill_seconds_for, objective, party_size)) is not None
    ]
    priced = [got for got in found if got.seconds < float("inf")]
    return min(priced, key=lambda got: got.seconds) if priced else None
