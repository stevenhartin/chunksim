"""Tempoross, priced from the wiki's own table rather than from a tier guess.

**This replaces three invented numbers with twenty published ones**, and the
shape of the error is what makes it worth a module. `costing/stated.py` used to
carry Tempoross as one figure per harpoon tier - 100,000 for crystal or
infernal, 85,000 for dragon, 80,000 for a plain one - marked `guess` and flat
across the whole climb. Against the wiki's table that is wrong twice over: a
plain harpoon at level 35 is **30,000**, not 80,000, and crystal and infernal
are 95,000 and 76,000 rather than one number for both.

What the wiki publishes is a rate for each of four harpoons at five levels,
which is what `RATES` carries. Every cell is read; nothing here is fitted or
interpolated between them beyond holding a point until the next one, which is
what `units_at` does everywhere else in this project.

### Why the published table and not the published formulas

The page also gives the experience of every action exactly - a harpoonfish is
`floor(450 + 550 * (level - 35) / 64) / 100` below level 70 and
`floor(890 + 110 * (level - 70) / 29) / 100` above it, with the ammunition
crate ten times that and the spirit pool eleven - so it is tempting to derive
the hourly rate instead. **It does not work, and measuring says why.** Every
action's experience is proportional to one `base`, so if the *count* of actions
were level-free the rate would be too. Dividing the published column by `base`:

    level 35   30,000 / 450  = 66.7
    level 70   62,000 / 890  = 69.7
    level 90   68,000 / 965  = 70.5
    level 99   74,000 / 1000 = 74.0

It climbs, so the catching gets faster as well as richer, and nothing publishes
that second curve. The formulas therefore check the *shape* and cannot produce
the rate, which is why this is a transcription and says so.

### The harpoon

**The best tier the map holds and the level can wield**, which is the reading
`gathering.best_tool` takes of an axe - a crystal harpoon in a reachable chunk
is not a crystal harpoon at level 60. The gates are the items' own: 61 Fishing
for a dragon harpoon, 71 for a crystal one, 75 for an infernal one, and none
for a plain or barb-tail harpoon. They are exactly where the wiki's table goes
`N/A`, which is the check on them.

Best is decided **by rate rather than by tier order**, because the tiers are not
ordered: an infernal harpoon is better than a dragon one and worse than a
crystal one at every level, and a list would have to encode that twice.

### Cooking is the other regime, and it is a second method

The wiki tabulates two, and the Fishing rate above is the **not cooking** one:
"not cooking the harpoonfish means getting lower amounts of points/loot but
significantly more experience". This module used to stop there, on the stated
grounds that "the export carries no Cooking challenge for Tempoross to hang
that on". **That was simply wrong** - `Cook fish at ~|Tempoross|~` is right
there under Cooking, and it was carrying a money-making guide's figure for
want of anyone looking.

So the cooking regime is priced too, and it is **one flat number** because
every part of it is fixed. The wiki's own `Solo cooking + firefighting (max
permits)` walkthrough counts the fish out: 17 in the first stretch and 19 more
to finish phase one - "much less than the 36 needed for the first phase" - then
19 in phase two, and none at all in phase three, which is spent dousing fires.
**55 cooked and loaded a game.** A game is "around 12 minutes", and the page's
own permit arithmetic agrees that the twelve includes the wait between games:
15.5 permits a game against "roughly 75-80 permits per hour" is exactly 5.
A harpoonfish pays **10** Cooking experience - the wiki's `{{Recipe}}`, level 1
- and the shrine cannot burn one, so nothing about this moves with level:

    5 games x 55 fish x 10 xp = 2,750 Cooking xp an hour

against the 2,500 `mmg:Money making guide/Subduing Tempoross` was supplying.
The two figures being close is the reassurance; what changes is that this one
is derived from counted actions rather than borrowed.

**The two challenges are two choices, not a split**, exactly as the Arceuus
library's two are. A player cooking gets ~20,000 Fishing an hour at level 35
rather than 30,000, but the export has one Fishing challenge and one Cooking
one, and a climb takes the best of what it is offered - so Fishing keeps the
not-cooking table and Cooking gets this. Pricing the cooking regime's *Fishing*
as well would offer a strictly worse number for the skill that already has one.

### Tiny tempor, and why redemption is not the bottleneck

`Tempoross` is absent from `chunk_info.drops` entirely, the same gap
`costing/wintertodt.py`'s own phoenix closes. `[[Reward pool]]`: "players
need to earn at least 2,000 points during a successful encounter to
receive reward permits, starting at 1 and adding 1 per 700 point
threshold" - permits are earned by *fighting* Tempoross and spent later by
*fishing* the pool, "at a rate of 1 reward for every 3 ticks (1.8
seconds)," which is fast enough that redemption itself is never the limit
- earning the permits is. `Tiny Tempor` is `1/8,000` per redeemed permit
(`[[Tiny_tempor]]`'s own item-sources table), and `GAMES_PER_HOUR`'s own
docstring already states the permit yield this reuses: "an average game
yields 15-16 permits," `PERMITS_PER_GAME` taking the same 15.5 the
existing `GAMES_PER_HOUR` derivation is checked against.

Pure: the level and the reachable set come in as arguments.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from chunksim.costing.gathering import CONFIRMED, CURVE_STEPS, GUESS, units_at
from chunksim.costing.heuristics import ComputedMethod

#: The export's own name for the catch, and the level Tempoross opens at.
TASK = "Catch fish at ~|Tempoross|~"
OPENS_AT = 35

SKILL = "Fishing"

#: The other challenge, and the skill it pays. See the module docstring for
#: why the two are choices rather than halves of one method.
COOKING_TASK = "Cook fish at ~|Tempoross|~"
COOKING_SKILL = "Cooking"

#: What a Cooking band calls it, told apart from the Fishing bands by naming
#: the regime rather than the harpoon.
COOKING_ACTIVITY = "Tempoross (cooking)"

#: Games an hour. **The twelve minutes a game takes already includes the wait
#: between them**, which is the page's own permit arithmetic checking itself:
#: an average game yields 15-16 permits and an hour yields "roughly 75-80", so
#: 15.5 into 77.5 is exactly five.
GAMES_PER_HOUR = 5.0

#: Fish cooked and loaded in one game, off the `Solo cooking + firefighting
#: (max permits)` walkthrough: 17 then 19 to finish phase one - the page calls
#: that "the 36 needed for the first phase" - and 19 in phase two. Phase three
#: cooks none; it is spent dousing fires.
FISH_PER_GAME = 17 + 19 + 19

#: Cooking experience one harpoonfish pays, from the wiki's own `{{Recipe}}`.
#: **Flat in level**, because the shrine cannot burn a fish - which is what
#: makes this whole method one number instead of a curve.
COOKING_EXPERIENCE = 10.0

#: The level the Cooking challenge opens at. Upstream's own, and it is 1: what
#: gates this is reaching Tempoross, which is Fishing's business.
COOKING_OPENS_AT = 1

#: The third challenge, and the only one here whose rate rests on a guess.
CONSTRUCTION_TASK = "Repair masts and totem poles at ~|Tempoross|~"
CONSTRUCTION_SKILL = "Construction"
CONSTRUCTION_ACTIVITY = "Tempoross (repairs)"

#: Experience one repair pays, per point of Construction level. **Published,
#: and not the 40 in the reward table** - that column is headed `Points`, and
#: the 40 is what dousing a fire pays too. `Mast (Tempoross)` states the
#: experience in prose and again in its `{{Skill info}}`: "Construction
#: experience equal to 4 times the player's level", `skill1exp = 4 x
#: Construction Level`.
REPAIR_XP_PER_LEVEL = 4.0

#: Repairs landed in one game. **The one invented number in this module**, and
#: what marks the whole Construction rate a guess.
#:
#: Everything around it is published and none of it closes the question. A
#: tether site breaks "between 15% and 25%" per wave, "rolled independently
#: for each tether site" - so about one wave in five breaks any given site -
#: and the cove has two masts and the island totem poles. What nothing states
#: is **how many waves a game contains**: the wave is one of several attacks
#: Tempoross chooses between, it only attacks above 10% energy, and the fight
#: runs a variable number of phase cycles. Without that count the expected
#: repairs cannot be derived, only estimated.
#:
#: One is the estimate, and it is deliberately the low end: a player fishing
#: for max permits is not standing by a broken mast waiting to fix it, and a
#: repair only pays if you are the one who does it.
REPAIRS_PER_GAME = 1.0

#: Harpoon -> the Fishing level it needs, and its `(level, xp/hr)` points from
#: the wiki's **Not cooking** table. The plain and barb-tail harpoons share a
#: row because the page says they do: "the standard harpoon, the barb-tail
#: harpoon, and Barbarian Fishing all have the same experience rates".
RATES: dict[str, tuple[int, tuple[tuple[int, float], ...]]] = {
    "Harpoon": (
        1,
        ((35, 30_000.0), (70, 62_000.0), (80, 65_000.0), (90, 68_000.0), (99, 74_000.0)),
    ),
    "Barb-tail harpoon": (
        1,
        ((35, 30_000.0), (70, 62_000.0), (80, 65_000.0), (90, 68_000.0), (99, 74_000.0)),
    ),
    "Dragon harpoon": (
        61,
        ((70, 66_000.0), (80, 69_000.0), (90, 72_000.0), (99, 74_000.0)),
    ),
    "Crystal harpoon": (
        71,
        ((70, 77_000.0), (80, 85_000.0), (90, 92_000.0), (99, 95_000.0)),
    ),
    "Infernal harpoon": (
        75,
        ((80, 71_000.0), (90, 74_000.0), (99, 76_000.0)),
    ),
}


def harpoon_rate(harpoon: str, level: int) -> float:
    """What one harpoon pays at `level`, or `0.0` if it cannot be used yet."""
    entry = RATES.get(harpoon)
    if entry is None:
        return 0.0
    needs, points = entry
    if level < needs or level < points[0][0]:
        return 0.0
    return units_at(points, level)


def best_harpoon(level: int, available: frozenset[str]) -> tuple[str, float]:
    """The reachable harpoon paying most at `level`, and what it pays.

    By rate rather than by tier, because the tiers are not ordered - see the
    module docstring. `("", 0.0)` where the map holds none, which the caller
    must read as "cannot price" rather than as the worst one.
    """
    best, paid = "", 0.0
    for harpoon in sorted(RATES):
        if harpoon not in available:
            continue
        rate = harpoon_rate(harpoon, level)
        if rate > paid:
            best, paid = harpoon, rate
    return best, paid


def rate_at(level: int, available: frozenset[str]) -> float:
    """Fishing experience an hour at `level` with the best harpoon held."""
    if level < OPENS_AT:
        return 0.0
    return best_harpoon(level, available)[1]


def cooking_xp_per_hour() -> float:
    """Cooking experience an hour under the max-permits regime.

    A constant, and deliberately expressed as the product it is: every factor
    is counted or published, so a reader can check the number by checking
    three.
    """
    return GAMES_PER_HOUR * FISH_PER_GAME * COOKING_EXPERIENCE


def cooking_methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Cooking": (...)}` where a map can reach Tempoross.

    One band, at the challenge's own level, because nothing about the regime
    moves with Cooking level: the fish count is the fight's and the shrine
    cannot burn one.

    Needs no harpoon check. `available` gates the Fishing bands because the
    tier decides the rate there; here the fish are cooked whatever caught
    them, and a map that reaches Tempoross at all reaches a harpoon.
    """
    if COOKING_TASK not in (valid.get(COOKING_SKILL) or {}):
        return {}
    return {
        COOKING_SKILL: (
            ComputedMethod(
                method=COOKING_ACTIVITY,
                xp_per_hour=cooking_xp_per_hour(),
                level=COOKING_OPENS_AT,
                match=CONFIRMED,
                knob=f"training/{COOKING_TASK}/{COOKING_SKILL}",
            ),
        )
    }


def construction_xp_per_hour(level: int) -> float:
    """Construction an hour from repairs, at `level`.

    `4 x level` a repair, one repair a game, five games an hour - so
    **20 x level**, which is 1,980 an hour at 99 and 20 at level 1. Two of
    those three factors are published; see `REPAIRS_PER_GAME` for the one
    that is not, and why this method's bands are `GUESS` because of it.
    """
    return REPAIR_XP_PER_LEVEL * level * REPAIRS_PER_GAME * GAMES_PER_HOUR


def construction_methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Construction": (...)}` where a map can reach Tempoross.

    Banded, because the experience is a multiple of the *Construction* level
    where the Cooking regime beside it is flat in Cooking - a repair pays
    `4 x level` whoever swings the hammer.

    **Marked `GUESS`, not `CONFIRMED`.** The other two regimes in this module
    transcribe published figures; this one multiplies a published experience
    by an invented count, and one invented factor makes the product invented.
    Upstream's own challenge carries the house requirement the wiki notes -
    "players without a house will no longer gain Construction experience" - so
    that gate is the derivation's rather than this module's.
    """
    if CONSTRUCTION_TASK not in (valid.get(CONSTRUCTION_SKILL) or {}):
        return {}
    bands = tuple(
        ComputedMethod(
            method=CONSTRUCTION_ACTIVITY,
            xp_per_hour=construction_xp_per_hour(level),
            level=level,
            match=GUESS,
            knob=f"training/{CONSTRUCTION_TASK}/{CONSTRUCTION_SKILL}",
        )
        for level in (1, *CURVE_STEPS)
        if construction_xp_per_hour(level) > 0
    )
    return {CONSTRUCTION_SKILL: bands} if bands else {}


def methods(
    valid: Mapping[str, Mapping[str, object]],
    available: frozenset[str] | None = None,
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{"Fishing": (...)}` where a map can reach Tempoross and hold a harpoon.

    Banded, and the harpoon is re-chosen at every step for the reason
    `gathering.priced_methods` re-chooses an axe: a map holding a crystal
    harpoon swings a plain one until 71, and that is a real band edge.
    """
    if TASK not in (valid.get(SKILL) or {}):
        return {}
    held = available or frozenset()
    levels: Sequence[int] = (
        OPENS_AT,
        *(step for step in CURVE_STEPS if step > OPENS_AT),
    )
    bands = tuple(
        ComputedMethod(
            method=f"Tempoross ({best_harpoon(level, held)[0].lower()})",
            xp_per_hour=rate_at(level, held),
            level=level,
            match=CONFIRMED,
            knob=f"training/{TASK}/{SKILL}",
        )
        for level in levels
        if rate_at(level, held) > 0
    )
    return {SKILL: bands} if bands else {}


#: Published on `[[Tiny tempor]]`'s own item-sources table: `1/8,000` per
#: redeemed reward permit.
TINY_TEMPOR_CHANCE_PER_ROLL = 1.0 / 8000.0

#: `[[Reward pool]]`: "an average game yields 15-16 permits" - the same
#: figure `GAMES_PER_HOUR`'s own docstring checks itself against ("15.5
#: into 77.5 is exactly five").
PERMITS_PER_GAME = 15.5


def item_seconds() -> dict[str, float]:
    """`{"Tiny tempor": seconds}`, at the max-permits regime's own
    `GAMES_PER_HOUR` - see the module docstring on why redemption itself is
    never the bottleneck."""
    chance = PERMITS_PER_GAME * TINY_TEMPOR_CHANCE_PER_ROLL
    if chance <= 0 or GAMES_PER_HOUR <= 0:
        return {}
    return {"Tiny tempor": 3600.0 / (GAMES_PER_HOUR * chance)}
