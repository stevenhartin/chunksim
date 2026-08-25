"""Barrows: six brothers, any order, one chest - no party, no scripted boss.

**The simplest of the export's "monster with no drop table" gaps.** Each of
the six brothers - `Ahrim the Blighted`, `Dharok the Wretched`, `Guthan the
Infested`, `Karil the Tainted`, `Torag the Corrupted`, `Verac the Defiled` -
already carries its own real table in the export (a `Brimstone key` at
1/100 apiece), so killing one is priced correctly today. **`Chest (Barrows)`
- the sarcophagus every brother's crypt holds, and the only source of any
Barrows equipment at all - is entirely absent from `drops`.** Nothing prices
`[[Karil's coif]]` or any of the other twenty-three pieces without this
module, the same gap `costing/raids.py` closes for the three raids and
`costing/moons.py` for the Moons' chest.

### No `FightScript` needed here

Unlike the Moons, the six brothers' own melee defences are close together -
within about fifteen points of each other across stab/slash/crush for the
four melee-armoured brothers, and Ahrim/Karil deal no melee damage of their
own at all (mage and ranged respectively) without carrying a matching
melee-defence gap either. `dps_bridge.best_kill`'s ordinary style search
already picks Magic against Dharok's `defence_magic=-11` and the rest
correctly; none of the six needs `Phase.styles`' exclusion the way the
Moons do.

### The run: six 100-hit-point kills plus the crypt itself

**`hp=100` for every brother** (measured against `osrs_dps`), so the six
kills are fast beside the published run. `Money making guide/Barrows`
publishes `kph = 12` - a **300-second run** - and the six brothers' own
combined health is a small fraction of that: the rest is walking six
crypts, killing enough trash (`Bloodworm`, `Crypt rat`/`spider`, `Giant
crypt rat`/`spider`, `Skeleton (Barrows)`) to build **reward potential**,
digging, and banking. `CRYPT_OVERHEAD_SECONDS` is this project's own figure
for that remainder, in the same shape `costing/theatre.py`'s
`BETWEEN_ROOMS_SECONDS` is: at an ordinary, unremarkable kill speed the six
brothers plus this overhead land at or above the published 300-second run
(`tests/test_costing_barrows.py`'s sanity check), which is the direction a
guessed remainder should err in without being fitted to hit 300 exactly.

### The chest, straight off the guide's own arithmetic

`[[Chest (Barrows)]]`'s own reward-mechanics section states the run this
project also assumes - **all six brothers killed, full reward potential
(1,012 points)** - is what every rarity on the page is quoted against, and
the money-making guide's `Output` fields give the arithmetic already
resolved: every one of the twenty-four unique pieces is `7/2448` (seven
rolls, since a sixth brother killed grants the seventh and final roll, at
1/2448 each), matching the page's own "chance of receiving a specific piece
of equipment is approximately 1/350.14" almost exactly. `Bolt rack` shares
the same `rolls=7` shape at `125/1012` per roll and is the export's other
`(Barrows Chests)` collection-log entry - twenty-five items total, and
`UNIQUE_CHANCE` covers them uniformly because the wiki's own numbers do.

**The key halves and Dragon med helm are on the page but not gated by the
export.** `Loop half of key`/`Tooth half of key`/`Dragon med helm` all have
published main-table rarities, but none of the three names a
`(Barrows Chests)` collection-log task - checked against
`ChunkInfo.challenges["Extra"]` directly - so this module does not price
them: the point of this module is closing what the export actually asks
for, not everything a reward table happens to list.

Pure: `FightPlan`/`PuzzlePlan` construction only, no `osrs_dps` import.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from chunksim.costing import encounter
from chunksim.costing.encounter import EXPERIENCE, FightPlan, KillSeconds, Objective, PuzzlePlan, UNIQUE

BARROWS = "Barrows"

#: Upstream's own challenge for the chest's loot.
LOOT_TASK = "Chest Barrows loot*"

#: The six brothers, in no particular order - the wiki's own "any order" and
#: this project's own sum agree that the order does not matter.
BROTHERS: tuple[str, ...] = (
    "Ahrim the Blighted",
    "Dharok the Wretched",
    "Guthan the Infested",
    "Karil the Tainted",
    "Torag the Corrupted",
    "Verac the Defiled",
)

#: Guessed - see the module docstring. Walking six crypts, clearing enough
#: trash for full reward potential, digging and banking - everything the
#: published 300-second run spends beyond the six brothers' own kill times.
CRYPT_OVERHEAD_SECONDS = 200.0

#: `Money making guide/Barrows`: `kph = 12`.
PUBLISHED_RUNS_PER_HOUR = 12.0
PUBLISHED_SECONDS = 3600.0 / PUBLISHED_RUNS_PER_HOUR

#: Every `(Barrows Chests)` collection-log item, and the brother whose crypt
#: must be cleared to unlock it - `[[Chest (Barrows)]]`: "the corresponding
#: brother must be killed before the chest is looted."
UNIQUE_TABLE: Mapping[str, tuple[str, ...]] = {
    "Ahrim the Blighted": ("Ahrim's hood", "Ahrim's robetop", "Ahrim's robeskirt", "Ahrim's staff"),
    "Dharok the Wretched": (
        "Dharok's helm", "Dharok's platebody", "Dharok's platelegs", "Dharok's greataxe",
    ),
    "Guthan the Infested": (
        "Guthan's helm", "Guthan's platebody", "Guthan's chainskirt", "Guthan's warspear",
    ),
    "Karil the Tainted": (
        "Karil's coif", "Karil's leathertop", "Karil's leatherskirt", "Karil's crossbow",
    ),
    "Torag the Corrupted": (
        "Torag's helm", "Torag's platebody", "Torag's platelegs", "Torag's hammers",
    ),
    "Verac the Defiled": (
        "Verac's helm", "Verac's brassard", "Verac's plateskirt", "Verac's flail",
    ),
}

#: Rolls at full reward potential with all six brothers slain - one plus one
#: per brother killed, capped at seven. `Money making guide/Barrows`'s own
#: `Output` fields.
ROLLS = 7

#: Per-roll chance of a specific unique piece, published on `[[Chest
#: (Barrows)]]`'s per-brother tables - `1/2448` for every one of the
#: twenty-four, `rolls=7`. `7/2448` is the guide's own aggregate, matched
#: almost exactly by the page's separately-stated "approximately 1/350.14".
UNIQUE_CHANCE = ROLLS / 2448.0

#: `Bolt rack`'s own per-roll share on the main table, same `rolls=7` shape.
BOLT_RACK_CHANCE = ROLLS * 125.0 / 1012.0


def item_chances() -> dict[str, float]:
    """`{item: chance one chest opening gives it}` - the twenty-four unique
    pieces plus `Bolt rack`, all at the guide's own published rates."""
    found = {
        item: UNIQUE_CHANCE for items in UNIQUE_TABLE.values() for item in items
    }
    found["Bolt rack"] = BOLT_RACK_CHANCE
    return found


def _full_log_runs() -> float:
    """Expected chests to see all twenty-five entries at least once.

    **Not `encounter.runs_for_all` on the raw twenty-five chances.** That
    function's own docstring states its cost is "exponential in the item
    count... a raid chest holds seven" - Barrows' twenty-five would be
    `2**25 - 1`, over 33 million inclusion-exclusion terms, which measured
    over a minute on this project's own hardware for one answer.

    Twenty-four of the twenty-five share `UNIQUE_CHANCE` exactly, so the sum
    collapses by symmetry: a subset's contribution depends only on *how
    many* of the twenty-four symmetric items it holds, not *which*, and
    whether it also holds `Bolt rack`. Grouping by that count turns
    `2**24` subsets into 24 - the standard "coupon collector with one
    distinguished coupon" reduction of `encounter.runs_for_all`'s own
    formula, verified against it directly in
    `tests/test_costing_barrows.py` (25 items still finishes there because
    that test also reaches for the closed form, not the raw one) and
    against `[[Chest (Barrows)]]`'s own published "All 6 sets is 1319.26
    chests".
    """
    from math import comb

    p, q, n = UNIQUE_CHANCE, BOLT_RACK_CHANCE, 24
    total = 0.0
    for k in range(1, n + 1):
        sign = 1.0 if k % 2 == 1 else -1.0
        total += sign * comb(n, k) / (k * p)
    for k in range(0, n + 1):
        sign = 1.0 if k % 2 == 0 else -1.0
        total += sign * comb(n, k) / (k * p + q)
    return total


def plans() -> tuple[FightPlan | PuzzlePlan, ...]:
    """One run: six brothers plus the crypt overhead as a single puzzle."""
    found: list[FightPlan | PuzzlePlan] = [FightPlan(name=name, target=name) for name in BROTHERS]
    found.append(PuzzlePlan(name="crypts, digging and banking", seconds=CRYPT_OVERHEAD_SECONDS))
    return tuple(found)


def run(kill_seconds: KillSeconds) -> encounter.Encounter | None:
    """One completed run, or `None` if a brother cannot be priced."""
    return encounter.build(BARROWS, plans(), kill_seconds)


@dataclass(frozen=True)
class Answer:
    """What one run costs for one objective."""

    run: encounter.Encounter
    #: Completions expected, or `inf` where the objective cannot be met.
    runs: float

    @property
    def seconds(self) -> float:
        return self.run.seconds * self.runs

    @property
    def hours(self) -> float:
        return self.seconds / 3600.0


def answer(kill_seconds: KillSeconds, objective: Objective = encounter.FULL_LOG) -> Answer | None:
    """`objective` priced against a full run (all six brothers, full reward
    potential), or `None` if a brother cannot be priced."""
    built = run(kill_seconds)
    if built is None:
        return None
    chances = item_chances()
    if objective.kind == UNIQUE:
        runs = encounter.expected_runs(chances.get(objective.item, 0.0))
    elif objective.kind == EXPERIENCE:
        # **Not answered here rather than answered badly**, matching every
        # other encounter module's refusal - see `costing/combat_xp.py`.
        return None
    else:
        runs = _full_log_runs()
    return Answer(run=built, runs=runs)


def item_seconds() -> dict[str, float]:
    """`{item: seconds}` for the item walk, at `PUBLISHED_SECONDS` - see
    `costing/raids.item_seconds` for the shape and the reason it is
    published rather than modelled at this point in the pipeline."""
    return {
        item: PUBLISHED_SECONDS / chance
        for item, chance in item_chances().items()
        if chance > 0
    }


def activity_for(item: str) -> str | None:
    """`BARROWS` if `item` is one of the chest's own rewards, else `None` -
    `costing/tzhaar.activity_for`'s exact shape, so `estimate.py`'s "named
    by the run that earns it" label works for this chest too, matched
    case-insensitively for the same reason that module's docstring gives.
    """
    wanted = item.lower()
    return BARROWS if wanted in {name.lower() for name in item_chances()} else None
