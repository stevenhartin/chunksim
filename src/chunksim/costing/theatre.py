"""The Theatre of Blood: six rooms in a fixed order, and one chest at the end.

**The simplest of the three raids, which is why it is the one the sequencer was
built against.** There are no puzzles, no random layout and no point system -
just six bosses in the same order every time with a short walk between them -
so `costing/encounter.py` can be exercised on a real raid without its shape
having to guess at Chambers' randomness first.

### The rooms, and why the keys are a table

The order is fixed: the Maiden, the Bloat, the Nylocas, Sotetseg, Xarpus and
Verzik. Verzik is three targets rather than one, because `osrs-dps` models her
phases separately and a run fights all three.

The three modes are separate monsters in that library rather than a scaling
input - `RaidInputs.party_size` is all `apply_tob` reads - and **their suffixes
do not follow a rule**: the same mode is `#Normal`, `#Normal mode` and
`#Normal Mode` across the six. So `ROOMS` spells every key out. A suffix rule
would have looked tidier and silently missed rooms.

### Three players, and why the guide is an oracle rather than a fit

`Money making guide/Theatre of Blood` is titled "Completing the Theatre of
Blood (trio)" and states `kph = 3` - **a twenty-minute raid for a team of
three**. It is tempting to fit this model to that, and it would be wrong.

**The guide's trio is carrying a Scythe of Vitur**, which is a Theatre drop. Its
twenty minutes describes an established raider re-running content they have
already looted, not anybody's first raid and certainly not a chunk map's. Fitted
to it, every map would report twenty minutes and the gear a map actually
reached - the thing this project exists to compute - would have been divided
out. So the guide is kept as a **floor**: no party should come out faster than
an established one, and `tests/test_costing_theatre.py` asserts it.

What the model does instead is take the map's own damage and divide by the
party. `encounter.build`'s `attackers` divides the time-to-kill and nothing
else, because that is what a second player is: they halve a health bar, they do
not halve Sotetseg's maze or the phases the Bloat spends invulnerable.

`UPTIME` is that second half - the share of a raid spent attacking at all -
and it is **invented**, which is why every figure here is a `GUESS`. It is one
number across six rooms rather than six, because nothing measures any of them
individually and six invented numbers would only look more precise.
`costing/encounter.Mechanic` is per-target precisely so a room somebody *does*
measure can be given its own without disturbing the rest.

### The chest, and the third of it that is yours

`Monumental chest` publishes the whole reward mechanic. A deathless team rolls
**1/9.1** for a unique on normal mode and **1/7.7** on hard; entry mode "does
not grant pre-rolls for uniques" at all, which is why it can never close a
collection log however fast it runs. The roll is once per *team* - "the drop
rate is the same regardless of the number of players completing the raid. The
item is allocated to one player" - so a trio sees a unique as often as a solo
would and keeps a third of them.

That division is the single most important line in this module. A model that
forgot it would report the log closing three times too fast.

### What it answers

`Objective` decides which. The green log is the default and is the coupon
collector over the seven uniques (`encounter.runs_for_all`); a named unique is
its own expectation; experience is not yet answered here and says so rather
than returning a plausible number.

Pure: the valid set and a kill-time lookup, both handed in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

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

#: Upstream's own challenge for the raid's loot.
LOOT_TASK = "Theatre of Blood loot*"

#: The party the money-making guide describes and this models.
PARTY_SIZE = 3

ENTRY, NORMAL, HARD = "entry", "normal", "hard"

#: The rooms in order. Each maps a mode to the `osrs-dps` keys a run fights -
#: Verzik is three because the library models her phases apart.
ROOMS: tuple[tuple[str, Mapping[str, tuple[str, ...]]], ...] = (
    ("The Maiden", {
        ENTRY: ("The Maiden of Sugadinti#Entry Mode",),
        NORMAL: ("The Maiden of Sugadinti#Normal",),
        HARD: ("The Maiden of Sugadinti#Hard Mode",),
    }),
    ("The Pestilent Bloat", {
        ENTRY: ("Pestilent Bloat#Entry",),
        NORMAL: ("Pestilent Bloat#Normal",),
        HARD: ("Pestilent Bloat#Hard",),
    }),
    ("The Nylocas", {
        ENTRY: ("Nylocas Vasilias#Entry",),
        NORMAL: ("Nylocas Vasilias#Normal",),
        HARD: ("Nylocas Vasilias#Hard",),
    }),
    ("Sotetseg", {
        ENTRY: ("Sotetseg#Entry",),
        NORMAL: ("Sotetseg#Normal",),
        HARD: ("Sotetseg#Hard",),
    }),
    ("Xarpus", {
        ENTRY: ("Xarpus#Entry mode",),
        NORMAL: ("Xarpus#Normal mode",),
        HARD: ("Xarpus#Hard mode",),
    }),
    ("Verzik Vitur", {
        ENTRY: tuple(f"Verzik Vitur#Entry mode, Phase {n}" for n in (1, 2, 3)),
        NORMAL: tuple(f"Verzik Vitur#Normal mode, Phase {n}" for n in (1, 2, 3)),
        HARD: tuple(f"Verzik Vitur#Hard mode, Phase {n}" for n in (1, 2, 3)),
    }),
)

#: Walking between six rooms and looting the chest. Small beside `UPTIME` and
#: separated from it because it is the one part of the twenty minutes that is
#: not a fight at all.
BETWEEN_ROOMS_SECONDS = 20.0
ROOM_TRANSITIONS = len(ROOMS)

#: The guide's own figure: "Completing the Theatre of Blood (trio)", `kph = 3`.
PUBLISHED_RAIDS_PER_HOUR = 3.0
PUBLISHED_SECONDS = 3600.0 / PUBLISHED_RAIDS_PER_HOUR

#: Share of a raid spent dealing damage. **Invented**, and one number across
#: six rooms - see the module docstring. Two thirds is the shape of a raid
#: where the Bloat spends most of its room invulnerable, Sotetseg's maze is
#: walked rather than fought and Verzik's phases gate on her rather than on
#: the party.
UPTIME = 0.66

#: The team's chance of a unique, per mode. Published on `Monumental chest`;
#: entry mode "does not grant pre-rolls for uniques".
TEAM_UNIQUE_CHANCE: Mapping[str, float] = {
    ENTRY: 0.0,
    NORMAL: 1.0 / 9.1,
    HARD: 1.0 / 7.7,
}

#: The unique table, per mode, as the chest publishes it.
UNIQUE_TABLE: Mapping[str, Mapping[str, float]] = {
    NORMAL: {
        "Avernic defender hilt": 8 / 19,
        "Ghrazi rapier": 2 / 19,
        "Sanguinesti staff (uncharged)": 2 / 19,
        "Justiciar faceguard": 2 / 19,
        "Justiciar chestguard": 2 / 19,
        "Justiciar legguards": 2 / 19,
        "Scythe of Vitur (uncharged)": 1 / 19,
    },
    HARD: {
        "Avernic defender hilt": 7 / 18,
        "Ghrazi rapier": 2 / 18,
        "Sanguinesti staff (uncharged)": 2 / 18,
        "Justiciar faceguard": 2 / 18,
        "Justiciar chestguard": 2 / 18,
        "Justiciar legguards": 2 / 18,
        "Scythe of Vitur (uncharged)": 1 / 18,
    },
}


def plans(mode: str) -> tuple[FightPlan | PuzzlePlan, ...]:
    """One run's rooms, in order, with the walking between them."""
    found: list[FightPlan | PuzzlePlan] = []
    for room, targets in ROOMS:
        for index, target in enumerate(targets[mode]):
            label = room if len(targets[mode]) == 1 else f"{room} (phase {index + 1})"
            found.append(FightPlan(name=label, target=target))
    found.append(
        PuzzlePlan(
            name="between rooms",
            seconds=BETWEEN_ROOMS_SECONDS * ROOM_TRANSITIONS,
        )
    )
    return tuple(found)


def mechanics(mode: str) -> dict[str, Mechanic]:
    """`UPTIME` against every fight of `mode`.

    One number across six rooms because the evidence is a raid total - see the
    module docstring. Returned per target so a room somebody measures can be
    given its own later without touching the others.
    """
    note = "share of a Theatre raid spent attacking, fitted to the guide's trio"
    return {
        target: Mechanic(uptime=UPTIME, note=note)
        for _room, targets in ROOMS
        for target in targets[mode]
    }


def personal_unique_chance(mode: str, party_size: int = PARTY_SIZE) -> float:
    """One player's chance of a unique from one completion.

    **The team rolls once and one player keeps it**, so a bigger team does not
    roll more often - it divides the same roll further.
    """
    team = TEAM_UNIQUE_CHANCE.get(mode, 0.0)
    return team / party_size if party_size > 0 else 0.0


def item_chances(mode: str, party_size: int = PARTY_SIZE) -> dict[str, float]:
    """`{item: chance one completion gives it to this player}`."""
    share = personal_unique_chance(mode, party_size)
    return {
        item: share * weight for item, weight in (UNIQUE_TABLE.get(mode) or {}).items()
    }


@dataclass(frozen=True)
class Answer:
    """What one mode of the raid costs for one objective."""

    mode: str
    run: encounter.Encounter
    #: Completions expected, or `inf` where the objective cannot be met.
    runs: float

    @property
    def seconds(self) -> float:
        return self.run.seconds * self.runs

    @property
    def hours(self) -> float:
        return self.seconds / 3600.0


def answer(
    mode: str,
    kill_seconds: KillSeconds,
    objective: Objective = encounter.FULL_LOG,
    party_size: int = PARTY_SIZE,
) -> Answer | None:
    """`mode` priced for `objective`, or `None` if a room cannot be priced."""
    run = encounter.build(
        f"Theatre of Blood ({mode})",
        plans(mode),
        kill_seconds,
        mechanics(mode),
        attackers=party_size,
    )
    if run is None:
        return None
    chances = item_chances(mode, party_size)
    if objective.kind == UNIQUE:
        runs = encounter.expected_runs(chances.get(objective.item, 0.0))
    elif objective.kind == EXPERIENCE:
        # **Not answered here rather than answered badly.** A raid's combat
        # experience is its bosses' hitpoints against a party's damage share,
        # which is `costing/combat_xp.py`'s question and not this module's.
        return None
    else:
        runs = encounter.runs_for_all(list(chances.values()))
    return Answer(mode=mode, run=run, runs=runs)


def best(
    kill_seconds: KillSeconds,
    objective: Objective = encounter.FULL_LOG,
    party_size: int = PARTY_SIZE,
    modes: Sequence[str] = (NORMAL, HARD),
) -> Answer | None:
    """The fastest mode for `objective`.

    **Entry mode is not among the defaults**, and that is a decision rather
    than an omission: it grants no unique pre-rolls at all, so however fast it
    runs it can never close a collection log. A caller wanting it for some
    other reason can pass it.
    """
    found = [
        got
        for mode in modes
        if (got := answer(mode, kill_seconds, objective, party_size)) is not None
    ]
    priced = [got for got in found if got.seconds < float("inf")]
    return min(priced, key=lambda got: got.seconds) if priced else None
