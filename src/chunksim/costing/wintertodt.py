"""Wintertodt: one game, three skills, and the whole rate is a multiplier.

**The rarest shape in this directory - an activity with no chance in it at
all.** Every other computed method here spends a success curve or a published
figure; Wintertodt's experience is stated as arithmetic on the wiki's own
table, so a rate is a count of games multiplied out:

| Activity | Skill | Multiplier |
|---|---|---|
| Cutting a bruma root | Woodcutting | 0.3x |
| Fletching a bruma root | Fletching | 0.6x |
| Feeding a bruma kindling | Firemaking | 3.8x |
| Subduing with 500+ points | Firemaking | 100x |

Four of the eight rows; the table also prices lighting a brazier (6x
Firemaking), feeding an unfletched root (3x), repairing a brazier (4x
Construction) and mixing a rejuvenation potion (0.1x Herblore). Those are not
in the loop below, which is the point of writing the loop down rather than the
table.

**Repairing a brazier is not in that loop, and it is not therefore unpriced -
it belongs to the other regime.** See `solo_methods`.

**The loop, and why it is this one.** The fast regime is world-hopped: earn
the 500 points that cap the reward, leave, and start again somewhere the game
is already running, so no part of the hour is spent waiting for one to begin.
Twenty bruma kindling is exactly 500 points, and the round trip is chop
twenty roots, fletch twenty, burn twenty. `GAMES_PER_HOUR` is what that comes
to.

At 99 in all three, one game pays 594 Woodcutting, 1,188 Fletching and 7,524 +
9,900 = 17,424 Firemaking - so the hour is 14,256, 28,512 and 418,176.

**Each skill reads only its own level**, which is what makes this three
independent curves rather than one method with three outputs, and why nothing
here needs to be told what else the player has trained. Firemaking's is not a
straight line either: the 100x subdual bonus is per *game* rather than per
kindling, so it is 9,900 of the 17,424 at 99 and the reason world-hopping
beats staying - a longer game earns the same bonus.

### The solo regime, and why it is a second method rather than a correction

**A world-hopped game is over before a brazier goes out.** The regime above
earns 500 points and leaves, so no part of the hour is spent on the things a
long game demands - and repairing braziers is the clearest of them. Solo play
inverts the trade: `Wintertodt/Strategies` describes games of 15-20 minutes in
which the player lights all four braziers, holds the south-western one, heals
the pyromancers and repairs what breaks. **Less Firemaking an hour, and
Construction experience where the fast loop earns none at all.**

**The wiki publishes the whole regime as a table and every column of it is
linear in the *Firemaking* level**, which is what makes it cheap to carry and
is the finding worth writing down: every Wintertodt reward is a multiplier
times the level, so a regime is one constant per skill. Fitted one parameter
per column against the six published rows of `Solo experience (no fletching)`,
and rounded to the nearest thousand as the wiki rounds them, **17 of the 18
cells come back exactly**:

| Firemaking | Construction, `200 x L` | Woodcutting, `151.5 x L` | Firemaking, `3131 x L` |
|---|---|---|---|
| 50 | 10,000 = 10,000 | 8,000 = 8,000 | 157,000 = 157,000 |
| 60 | 12,000 = 12,000 | 9,000 = 9,000 | 188,000 = 188,000 |
| 70 | 14,000 = 14,000 | 11,000 = 11,000 | 219,000 = 219,000 |
| 80 | 16,000 = 16,000 | 12,000 = 12,000 | 250,000 vs 251,000 |
| 90 | 18,000 = 18,000 | 14,000 = 14,000 | 282,000 = 282,000 |
| 99 | 19,800 -> 20,000 | 15,000 = 15,000 | 310,000 = 310,000 |

**Only the Construction column is spent.** The other two are the evidence that
the law is proportionality rather than a curve, and carrying them would change
nothing: solo Firemaking is 310,000 against the hopped loop's 418,176, so the
running maximum in `training_bands` keeps the loop above; solo Woodcutting is
15,000 against its 14,256, a 5% edge on a method neither cached map nor the
ceiling uses for Woodcutting at all. Adding them is a one-line change if a map
ever wants them - `SOLO_PER_FIREMAKING_LEVEL` already holds the constants.

**The level axis is Firemaking's, and the rate is flat in Construction** - the
same assignment `costing/barbarian.py` makes for Strength off Fishing. How much
Construction an hour of this pays depends on how fast the game goes, which is
Firemaking; the player's Construction level does not enter it, so there are no
bands and the method is open from level 1.

**The gate is Firemaking 50, and upstream's own Construction row does not say
so.** `Repair braziers at ~|Wintertodt|~` carries `Level: 1` and asks for a
hammer, because upstream states the requirement on `Access the ~|Wintertodt|~`
instead. A rate written against the Construction row would offer the minigame
to a player who cannot enter it, which is exactly what `costing/gotr.py` found
on the twelve `with guardian essence` runes.

**So the gate is that access challenge rather than a level compared here**, and
the level is *floored* at `OPENS_AT` rather than refused below it. The two are
the same claim from different directions and the difference only shows where
levels are unknown: `chunksim training`'s export census has no Firemaking level
at all - `infer_levels` reads what a map's own state implies and the ceiling
payload implies nothing about it - so comparing `1 < 50` there reported a
method as **unpriced** when what was missing was the reader's information, not
a rate. Reading the floor is not a fabrication: being inside the game is being
at least 50, and the wiki's own bottom row is what it prices at.

**This replaces a hand-written 400,000/hr.** That figure was a single number
for a method whose rate is a function of level, and it was close at the top
(418,176) and wrong everywhere below it - Firemaking opens the boss at 50,
where the real figure is half that. Nothing is fitted here; every number is
the wiki's table or the count of actions in the regime.

The reachability gate is upstream's: each skill's own challenge has to be
valid, so a map that cannot reach the boss is never offered any of the three.

### The phoenix, and why it is a rate the export cannot answer

`Wintertodt` is absent from `chunk_info.drops` entirely - the export has no
per-kill table for it at all, the same shape `costing/raids.py` and
`costing/barrows.py` each close for their own chests. `[[Phoenix]]`: "a pet
that can be received from looting the [[Reward Cart]], from which rewards
are obtained by subduing the Wintertodt with at least 500 points" -
`[[Reward Cart]]`'s own table states the mechanic precisely: "500 points =
2 rolls," and the reward cascade tries the phoenix **first** ("a player
searches the cart and rolls for a phoenix pet. If that roll is successful,
they will receive the phoenix and the drop rolls end there"), so its own
published `1/5,000` per roll is already the effective one - no cascade
arithmetic to unwind. `item_seconds` reuses `GAMES_PER_HOUR` directly: the
world-hopped regime is defined as exactly 500 points a game, which is
exactly the reward cart's own milestone, so the same loop that prices the
three skills also prices the pet.

**The 200-million-Firemaking-experience bonus (fifteen times the rate) is
not modelled** - a player at that milestone is so far past 99 that pricing
a climb to it is not this project's question, and the base rate is the
honest one for every level this module's own bands cover.

Pure: the levels come in as arguments.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.costing.gathering import CONFIRMED, CURVE_STEPS
from chunksim.costing.heuristics import ComputedMethod

#: Games an hour under the world-hopped regime. **The one number here that is
#: not a multiplier off the wiki's table**, and it scales all three skills
#: together: it is how many times you can reach 500 points and leave, which is
#: what the method is.
GAMES_PER_HOUR = 24.0

#: Bruma kindling burnt per game. 25 points each, so twenty is the 500 that
#: caps the reward - and taking more would earn the same bonus for a longer
#: game, which is exactly what the regime refuses to do.
KINDLING_PER_GAME = 20.0

#: `{skill: (task, multiplier per action)}`, one row of the wiki's table each.
#: The action is a bruma root's whole journey, so all three are counted
#: `KINDLING_PER_GAME` times.
ACTIONS: dict[str, tuple[str, float]] = {
    "Woodcutting": ("Chop ~|bruma roots|~", 0.3),
    "Fletching": ("Fletch ~|bruma kindling|~", 0.6),
    "Firemaking": ("Burn wood at ~|Wintertodt|~", 3.8),
}

#: The skill the 500-point subdual pays, and what it pays: `level * 100`. Per
#: game rather than per action, which is the whole argument for hopping.
SUBDUAL_SKILL = "Firemaking"
SUBDUAL_MULTIPLIER = 100.0

#: What the band is called wherever a rate is shown.
METHOD = "Wintertodt (world-hopped)"

#: Firemaking level the boss opens at, stated by the export on
#: `ACCESS_TASK`. Both regimes need it; only the solo one has to say so,
#: because every task in `ACTIONS` carries the requirement itself and the
#: Construction row does not.
OPENS_AT = 50

#: Upstream's own "can this map enter the boss" challenge, and the one that
#: carries `Level: 50`. Gating on it rather than on a level comparison is what
#: keeps the export census - which infers no Firemaking level - from reading a
#: priced method as unpriced. See the module docstring.
ACCESS_TASK = "Access the ~|Wintertodt|~"

#: Experience an hour the **solo** regime pays, per point of *Firemaking*
#: level. One constant a column, fitted against the six published rows of
#: `Wintertodt/Strategies#Solo experience (no fletching)` - see the module
#: docstring for the fit, and for why only the first is spent.
SOLO_PER_FIREMAKING_LEVEL: dict[str, float] = {
    "Construction": 200.0,
    "Woodcutting": 151.5,
    "Firemaking": 3131.0,
}

#: The challenge each spent column answers for. Construction alone, because
#: the other two skills already have a faster or equal regime above.
SOLO_TASKS: dict[str, str] = {"Construction": "Repair braziers at ~|Wintertodt|~"}

#: What the solo band is called, beside `METHOD`.
SOLO_METHOD = "Wintertodt (solo)"


def experience_per_game(skill: str, level: int) -> float:
    """What one game pays `skill` at `level`, or `0.0`.

    Firemaking is the only one with two terms: twenty kindling fed, and the
    subdual bonus once.
    """
    action = ACTIONS.get(skill)
    paid = KINDLING_PER_GAME * action[1] * level if action else 0.0
    if skill == SUBDUAL_SKILL:
        paid += SUBDUAL_MULTIPLIER * level
    return paid


def rate_at(skill: str, level: int) -> float:
    """Experience an hour of world-hopped Wintertodt pays `skill` at `level`."""
    return experience_per_game(skill, level) * GAMES_PER_HOUR


def methods(
    valid: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{skill: (...)}` for whichever of the three a map can reach.

    One band per level step, because the rate is linear in the level and a
    single figure for it was the defect this module was written to fix.
    """
    found: dict[str, tuple[ComputedMethod, ...]] = {}
    for skill, (task, _multiplier) in sorted(ACTIONS.items()):
        if task not in (valid.get(skill) or {}):
            continue
        banded = tuple(
            ComputedMethod(
                method=METHOD,
                xp_per_hour=rate_at(skill, level),
                level=level,
                match=CONFIRMED,
                knob=f"training/{task}/{skill}",
            )
            for level in (1, *CURVE_STEPS)
            if rate_at(skill, level) > 0
        )
        if banded:
            found[skill] = banded
    return found


def solo_rate_at(skill: str, firemaking_level: int) -> float:
    """Experience an hour the solo regime pays `skill` at `firemaking_level`.

    Zero for a skill the table does not publish. **Read at the Firemaking
    level whatever skill is asked for**, and floored at `OPENS_AT` because
    being in the game is being at least that - see the module docstring, and
    `solo_methods` for the gate that makes the floor honest.
    """
    return SOLO_PER_FIREMAKING_LEVEL.get(skill, 0.0) * max(firemaking_level, OPENS_AT)


def solo_methods(
    valid: Mapping[str, Mapping[str, object]], firemaking_level: int
) -> dict[str, tuple[ComputedMethod, ...]]:
    """`{skill: (...)}` for the solo regime, empty where the boss is unreachable.

    One band, not a curve: the rate is flat in the skill being trained and the
    Firemaking level is a property of the map rather than of the climb. That
    is why `level` is `None` here where `methods` writes a step per point.

    **`ACCESS_TASK` is the gate**, not `firemaking_level` - see the module
    docstring. Measured, it is valid on exactly the maps `Repair braziers at
    ~|Wintertodt|~` is, so this refuses nothing upstream allows.
    """
    if ACCESS_TASK not in (valid.get("Firemaking") or {}):
        return {}
    found: dict[str, tuple[ComputedMethod, ...]] = {}
    for skill, task in sorted(SOLO_TASKS.items()):
        if task not in (valid.get(skill) or {}):
            continue
        rate = solo_rate_at(skill, firemaking_level)
        if rate <= 0:
            continue
        found[skill] = (
            ComputedMethod(
                method=SOLO_METHOD,
                xp_per_hour=rate,
                level=None,
                match=CONFIRMED,
                knob=f"training/{task}/{skill}",
            ),
        )
    return found


#: Published on `[[Reward Cart]]`'s own drop table - the phoenix is the
#: first roll in the cascade, so its own rarity is the effective one. See
#: the module docstring.
PHOENIX_CHANCE_PER_ROLL = 1.0 / 5000.0

#: Published: "500 points = 2 rolls" - the world-hopped regime's own
#: 500-point game earns exactly this many.
ROLLS_PER_GAME = 2.0


def item_seconds() -> dict[str, float]:
    """`{"Phoenix": seconds}`, at the world-hopped regime's own
    `GAMES_PER_HOUR` - see the module docstring on why that regime's own
    500-point milestone is exactly the reward cart's own."""
    chance = ROLLS_PER_GAME * PHOENIX_CHANCE_PER_ROLL
    if chance <= 0 or GAMES_PER_HOUR <= 0:
        return {}
    return {"Phoenix": 3600.0 / (GAMES_PER_HOUR * chance)}
