"""Vorkath: a repeating freeze/acid cycle through one continuous fight, and
the wrong Vorkath without a script.

**The version problem, same shape as `costing/duke_sucellus.py`'s.**
`osrs_dps` carries `Vorkath#Dragon Slayer II` (460 hitpoints, the one-time
quest encounter) and `Vorkath#Post-quest` (750, the version fought on every
repeat kill) as separate, unranked alternatives - neither name matches
`_SEQUENTIAL_VERSIONS`, so unscripted resolution would pick whichever dies
faster, which is the 460-hitpoint quest-only Vorkath fought exactly once
ever. `SCRIPT` is a single, unsplit phase naming `Post-quest` explicitly,
fixing the target rather than modelling a mechanic.

### The freeze/acid cycle is not a phase - it repeats through one fight

Unlike a boss with published health thresholds, Vorkath's downtime is
gated on *his own attack count*, not on his health: "After six normal/
dragonfire attacks, it will use one of two special attacks and alternate
between them... After six regular attacks, then the other after six more,
and so on." That happens every eighteen seconds of the fight (`attack
speed = 5` ticks, published on his own infobox - `3.0` seconds a hit,
times six) for as long as the kill takes, which is why this is not
expressed as `Phase.reduced_seconds` - that field is one window at a
phase's *start*, and Vorkath's fight has no phase boundaries to hang
repeated windows off. `effective_seconds` instead derives a steady-state
average dps directly, over one full two-special cycle (freeze, then acid,
then repeat), and applies it as a multiplier - the same shape
`costing/giant_mole.py`'s and `costing/duke_sucellus.py`'s corrections
are, chosen for the same reason: nothing here is a slice of health, so
nothing here belongs in `costing/fightscripts.py`.

### The two specials, and what is published against what is guessed

**Freeze**: "Vorkath is immune to damage as soon as the breath is
launched, and remains as such until the spawn is killed or explodes" - a
true zero-damage window, published. Its *length* is not: a
[[Zombified Spawn]] is 38 hitpoints and dies instantly to a well-timed
Crumble Undead cast, so `FREEZE_SECONDS` is this project's own figure for
"cast one spell and wait for it to land," not a measurement.

**Acid**: "Vorkath has a flat 50% damage reduction" during the acid pools/
rapid-fire barrage - published, and matched by a separate changelog entry
("Maximum damage dealt to Vorkath during acid attack phase is now reduced
by 50%") confirming it is a real cap rather than prose. Its *length* is
equally unpublished, so `ACID_SECONDS` is this project's own figure too.
Both being guessed makes every rate this module produces a `GUESS`.

### The arithmetic

One full two-special cycle: `36` seconds of ordinary combat (two six-attack
blocks) plus one freeze window (zero damage) plus one acid window (half
damage). The average dps over that cycle divided into the boss's own
hitpoints, compared against the plain `hp / base_dps` an unscripted kill
would read, is the multiplier `effective_seconds` applies - self
-consistently scaling with however fast the map's own gear kills normally,
the same way `costing/giant_mole.py`'s correction does.

### What stays unmodelled

Which style is being used during the acid window changes whether a real
player deals the reduced 50% or nothing at all - a melee Woox Walk answers
differently from a ranged or magic hybrid that can attack while dodging.
This project has no per-style downtime model, so the published 50% is
applied uniformly, matching the infobox's own unqualified statement rather
than picking a side.

Pure: `FightScript`/`Phase` construction and one function, no `osrs_dps`
import.
"""

from __future__ import annotations

from chunksim.costing.fightscripts import FightScript, Phase

VORKATH = "Vorkath"

#: Published on Vorkath's own infobox: `attack speed = 5` ticks.
ATTACK_SPEED_SECONDS = 3.0

#: Published: a special triggers after every six of his own attacks.
ATTACKS_BEFORE_SPECIAL = 6

#: One special-triggering block's worth of ordinary combat.
NORMAL_SECONDS_PER_BLOCK = ATTACK_SPEED_SECONDS * ATTACKS_BEFORE_SPECIAL

#: Guessed - see the module docstring. Casting Crumble Undead on the
#: Zombified Spawn and waiting for it to land.
FREEZE_SECONDS = 4.0

#: Published: "a flat 50% damage reduction" during the acid special.
ACID_DPS_FRACTION = 0.5

#: Guessed - see the module docstring. The acid-pool/rapid-fire barrage's
#: own duration.
ACID_SECONDS = 10.0

SCRIPT = FightScript(
    name=VORKATH,
    phases=(
        Phase(
            name=VORKATH,
            target="Vorkath#Post-quest",
            hp_share=1.0,
            note="The repeatable, post-quest Vorkath - not the "
            "460-hitpoint one-time Dragon Slayer II quest fight, which "
            "shares the bare name ambiguously. See the module docstring.",
        ),
    ),
    note="The freeze/acid cycle is applied separately by "
    "`vorkath.effective_seconds`, not by this script - see the module "
    "docstring on why it is not phase-shaped.",
)


def effective_seconds(kill_seconds: float) -> float:
    """`kill_seconds` at Vorkath's own uninterrupted dps, corrected for the
    freeze/acid cycle's steady-state average.

    `kill_seconds` is treated as `hitpoints / base_dps` with the cycle's
    downtime already excluded - exactly what an unscripted `KillEstimate`
    against a single stat block already is - and the result divides that
    same `hitpoints` by the cycle-averaged dps instead.
    """
    if kill_seconds <= 0:
        return kill_seconds
    cycle_seconds = 2 * NORMAL_SECONDS_PER_BLOCK + FREEZE_SECONDS + ACID_SECONDS
    cycle_damage_shares = 2.0 + ACID_DPS_FRACTION * (ACID_SECONDS / NORMAL_SECONDS_PER_BLOCK)
    # `cycle_damage_shares` is the cycle's total damage, in units of "one
    # `NORMAL_SECONDS_PER_BLOCK` block's worth of full-rate damage" - two
    # ordinary blocks, plus whatever the reduced acid window contributes at
    # its own fraction of the same rate.
    base_dps_seconds_per_block = NORMAL_SECONDS_PER_BLOCK
    blocks_to_kill = kill_seconds / base_dps_seconds_per_block
    cycles_to_kill = blocks_to_kill / cycle_damage_shares
    return cycles_to_kill * cycle_seconds
