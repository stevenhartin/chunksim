"""Zalcano: a skilling boss `dps_bridge` cannot price at all, corrected to
the group's own published throughput.

**Not modelled as part of skilling, and this is not that either.** `[[
Zalcano]]`: "fought using skilling rather than conventional combat. Being
immune to traditional combat damage, players must use their Mining,
Smithing, and Runecraft skills to create imbued tephra... All of Zalcano's
attacks are typeless, meaning that protection prayers cannot be used." Her
own drop table is already fully populated in the export - `Smolcano` at
the correct published `1/2,250` among it - so nothing here is a missing
chest. What is wrong is the *rate*: `osrs_dps` carries `Zalcano#Armoured`
and `#Weakened` as ordinary combat targets with **every defence bonus at
zero**, because the library has no notion of "immune to conventional
damage, hurt only by skilling actions" - so an unscripted kill prices her
as whatever weapon the map's own gear happens to be, which kills a
zero-defence target in seconds. That is not a slower or faster answer than
reality, it is a **different question entirely**, and `costing/
fightscripts.py`'s per-target style search cannot fix a boss that no
combat style actually damages.

### Why the correction is a flat override, not a formula

Every other "gated boss" correction in this subpackage (`costing/
hespori.py`, `costing/giant_mole.py`, `costing/duke_sucellus.py`, `costing/
vorkath.py`, `costing/nex.py`) takes the map's own simulated kill time and
adds or multiplies something onto it, because the simulated time is at
least *real* - a genuine combat kill happening alongside an overhead. Here
the simulated time is not real at all, so `effective_seconds` ignores its
argument entirely and returns the published figure. This is a considered
choice, not an oversight: `Money making guide/Killing Zalcano` states "The
profit rate assumes 48 kills per hour on a Themed world with equal
contributions among 15 participants" - a **group's** throughput, driven by
however many players are mining and imbuing at once, not by any one
player's own weapon or levels. There is no map-specific number to compute
here that this project's own combat model could answer better than the
guide's own measured figure.

### Smolcano, and why nothing further is needed here

"Players who have contributed enough to the Zalcano fight will now have a
static 1/2,250 chance at the Smolcano pet" - and separately, on the
drop table's own notes: "The chance of rolling Smolcano is unaffected by
performance." Eligibility itself ("31 combined damage") is a low bar any
real participant in a themed-world kill clears, so once `effective_seconds`
corrects the group's own kph, the export's own `1/2,250` entry for
`Smolcano` is already right and the ordinary item walk prices it correctly
without a separate chest fix - unlike `costing/barrows.py`,
`costing/colosseum.py`, `costing/moons.py` and `costing/gauntlet.py`, none
of which had a real table to fall back on.

**The points-scaled main and tertiary tables (`Zalcano shard`, `Crystal
tool seed`, `Uncut onyx`) are not corrected further either** - the
export's own flat rarities for them already describe some averaged
contribution level, the same trust every other per-kill rate in this
project extends to the export's own numbers once the *rate* feeding them
is right.

Pure: one constant and one function, no `osrs_dps` import.
"""

from __future__ import annotations

ZALCANO = "Zalcano"

#: `Money making guide/Killing Zalcano`: "48 kills per hour on a Themed
#: world with equal contributions among 15 participants." A group's own
#: throughput, not derivable from one player's gear - see the module
#: docstring.
PUBLISHED_KILLS_PER_HOUR = 48.0
PUBLISHED_SECONDS = 3600.0 / PUBLISHED_KILLS_PER_HOUR


def effective_seconds(kill_seconds: float) -> float:
    """The published group throughput, ignoring `kill_seconds` entirely -
    see the module docstring on why the simulated combat time is not a
    real answer to correct rather than a wrong one to discard."""
    return PUBLISHED_SECONDS
