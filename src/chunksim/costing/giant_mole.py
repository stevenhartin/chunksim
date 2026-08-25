"""The Giant Mole: a published escape mechanic that costs real chase time,
not a fight that ends the moment her health does.

**The fight is not the rate.** `Giant Mole` already carries a real drop
table in the export - guaranteed mole skin and mole claw, a rare
immaculate mole skin - so nothing here is missing a chest. What the
ordinary combat-only kph does not know is `[[Giant Mole]]`'s own published
mechanic: "While between 50% and 5% of her health, every attack from the
player has a 25% chance of causing her to burrow into the ground to another
area in the lair, losing aggression and forcing players to chase her across
the lair" - cited to Mod Ash's own "1/4 when its health is between 5% and
50%." Every burrow costs real, unfought time re-locating her, on top of
whatever the fight itself takes.

### Two guessed numbers, both stated as such

**`ASSUMED_ATTACK_SPEED_SECONDS`** stands in for a real attack speed this
correction has no access to - it is applied to an already-computed `Rate`
(`dps_bridge.price_monsters`' output), not the `KillEstimate` a `Loadout`
would let it read directly, so how many attacks the 45%-of-health burrow
window actually spans has to be inferred from `kill_seconds` alone. Four
ticks (2.4s) is a common boss-weapon speed - a whip, most crossbows, a
dragon halberd - and is this project's own stated assumption rather than
the map's real one.

**`CHASE_SECONDS_PER_BURROW`** is this project's own figure for how long
relocating her costs, in the same shape `costing/tzhaar.py`'s
`PER_WAVE_SECONDS` is: nothing publishes it, and one constant across every
burrow stands in for however many unknowns a chase actually has (which
direction, how far, whether a dirt-throw extinguishes a light source and
costs a relight). Both being guessed makes every rate this module produces
a `GUESS`, by the rule that one invented factor makes the product invented -
here there are two.

### The arithmetic

`hp=200`, and the burrow window is 50% down to 5%, so `WINDOW_HP_SHARE =
0.45` of her health is burrow-eligible - not from 100% down to 5%, and not
including the last 5%, both published exactly on the boss's own page.
`expected_burrows` estimates the attacks landed in that window as
`(kill_seconds / ASSUMED_ATTACK_SPEED_SECONDS) x WINDOW_HP_SHARE`, self
-consistently scaling with however fast a real kill actually goes - a
slower map's fight spends longer in the window in wall-clock terms but the
*attack count* crossing 90 hitpoints of her health is what the published
25% applies to, which is what this multiplies by `WINDOW_HP_SHARE` of the
*implied* attack total rather than by elapsed seconds.

### What stays unmodelled

The dirt-throw's light-source mechanic and the specific chase distance per
burrow are folded into the one `CHASE_SECONDS_PER_BURROW` figure rather
than modelled separately - two more invented constants would not have made
the estimate more honest, only more confident-looking. Cannon and
safespotting, both real and commonly used against her, are outside what
this project's single-target combat model represents at all, matching every
other boss module in this subpackage.

Pure: two constants and one function, no `osrs_dps` import.
"""

from __future__ import annotations

GIANT_MOLE = "Giant Mole"

#: Published on `[[Giant Mole]]`: the burrow chance per player attack while
#: her health is inside `WINDOW_HP_SHARE`.
BURROW_CHANCE_PER_ATTACK = 0.25

#: Published: burrow-eligible between 50% and 5% of her health - 45% of it,
#: not the last 5% and not above 50%.
WINDOW_HP_SHARE = 0.45

#: Guessed - see the module docstring. A four-tick weapon's attack speed,
#: standing in for the real one this correction cannot read.
ASSUMED_ATTACK_SPEED_SECONDS = 2.4

#: Guessed - see the module docstring. Seconds lost re-locating her, once
#: per burrow.
CHASE_SECONDS_PER_BURROW = 8.0


def expected_burrows(kill_seconds: float) -> float:
    """How many times a kill of this length is expected to trigger a
    burrow, at `ASSUMED_ATTACK_SPEED_SECONDS` and the published window and
    chance."""
    if kill_seconds <= 0:
        return 0.0
    attacks = kill_seconds / ASSUMED_ATTACK_SPEED_SECONDS
    return attacks * WINDOW_HP_SHARE * BURROW_CHANCE_PER_ATTACK


def effective_seconds(kill_seconds: float) -> float:
    """`kill_seconds`, plus the chase time its expected burrow count
    costs."""
    return kill_seconds + expected_burrows(kill_seconds) * CHASE_SECONDS_PER_BURROW
