"""The Alchemical Hydra: four phases, three vents, one health bar.

**Why the softest-form pick was wrong.** `osrs_dps` indexes the Hydra as four
keys - `#Serpentine`, `#Electric`, `#Fire`, `#Extinguished` - one per phase,
and they are *not* stat-identical: the final phase attacks on a 4-tick cycle
where the first three run on 6, and only it carries a `stated_max_hit`.
Before this module existed, `dps_bridge.best_kill`'s ordinary rule - take the
easiest version, right for a genuinely substitutable monster - picked among
these as if a player could choose to fight only the fastest phase and
skip the rest. A quarter of the boss's health bar was priced at whichever
phase happened to die quickest and the other three-quarters were never
charged at all.

### The phases, and where each number comes from

[[Alchemical Hydra]] states the phase boundaries in hitpoints, not as a
rounded fraction: "When the Alchemical Hydra reaches or falls below 75%, 50%,
and 25% of its health (that is, at 825, 550, and 275 Hitpoints), it will lose
one of its heads and begin the next phase." 1100 split at 825/550/275/0 is
four equal quarters, so `hp_share=0.25` on every phase is the wiki's own
arithmetic, not an assumption.

**Order**, inferred from the library's `speed`/`stated_max_hit` fields rather
than stated outright anywhere on the page: `#Extinguished` is the only one
with a faster attack cycle and a `stated_max_hit`, which matches the page's
"In its final phase, the Hydra will alternate combat styles every attack with
increased attack speed and max hit" - so `#Extinguished` is phase four and
the other three, all identical on those two fields, are phases one through
three in the order the page's colour list gives them: poison (green,
`#Serpentine`), electricity (blue, `#Electric`), fire (red, `#Fire`).

### The vent, and the one guessed number in this module

"At the start of each phase, it has a 75% damage reduction, which can be
removed if it is lured over a vent on the floor... Barring the last phase,
the damage reduction is reapplied." Two things are published here and one is
not:

- **75% reduction is `Phase.reduced_dps_fraction=0.25`** - the wiki's own
  number, not fitted to anything.
- **"Barring the last phase" is why phase four carries no vent** -
  `reduced_seconds=0.0` there and nowhere else.
- **How long finding and using the vent actually takes is not published
  anywhere this project found**, and `VENT_SECONDS` below is this project's
  own figure for it - exactly the shape `costing/tzhaar.py`'s
  `PER_WAVE_SECONDS` is. Every phase's `kills_per_hour` this module produces
  is therefore a `GUESS`, by the rule that one invented factor makes the
  product invented, however published the rest of it is.

**Whether phase one's vent - the very start of the fight - is real or
assumed.** The page says "at the start of *each* phase" without excluding the
first, and phase one is a phase, so this module reads it as vented like
phases two and three. If that reading is wrong the fix is one number:
`hp_share` stays right regardless, only `VENT_SECONDS` on phase one's
`Mechanic` moves.

### What stays unmodelled

The three heads' own special attacks (poison pools, electricity, fire) are
avoidable per the wiki and are not costed. Nothing about a death or a
restarted attempt is modelled, matching every other module in this
subpackage. **This is a ceiling**, not an expectation: the ordinary case of
occasionally eating an avoidable mechanic runs slower than this script says.

Pure: no `osrs_dps` import, matching every other leaf in this subpackage -
`costing/dps_bridge._scripted_kill` is what turns this into a priced kill.
"""

from __future__ import annotations

from chunksim.costing.fightscripts import FightScript, Phase

#: Guessed - see the module docstring. How long finding and using a vent
#: costs, once per vented phase.
VENT_SECONDS = 5.0

#: Published on the boss's own page: the reduction a correct vent removes.
VENT_DPS_FRACTION = 0.25

SCRIPT = FightScript(
    name="Alchemical Hydra",
    phases=(
        Phase(
            name="Poison (Serpentine)",
            target="Alchemical Hydra#Serpentine",
            hp_share=0.25,
            reduced_seconds=VENT_SECONDS,
            reduced_dps_fraction=VENT_DPS_FRACTION,
            note="First phase. Vented like phases 2-3 - see the module docstring "
            "on why phase 1's own vent is inferred rather than stated.",
        ),
        Phase(
            name="Lightning (Electric)",
            target="Alchemical Hydra#Electric",
            hp_share=0.25,
            reduced_seconds=VENT_SECONDS,
            reduced_dps_fraction=VENT_DPS_FRACTION,
            note="Second phase, vented on entry.",
        ),
        Phase(
            name="Fire",
            target="Alchemical Hydra#Fire",
            hp_share=0.25,
            reduced_seconds=VENT_SECONDS,
            reduced_dps_fraction=VENT_DPS_FRACTION,
            note="Third phase, vented on entry.",
        ),
        Phase(
            name="Final (Extinguished)",
            target="Alchemical Hydra#Extinguished",
            hp_share=0.25,
            note="Fourth and final phase. Published: no vent reapplied here - "
            "'barring the last phase' on the boss's own page. The style "
            "alternation and speed-up this phase adds are the monster's own "
            "offence, not the player's, so they cost nothing in this model.",
        ),
    ),
    note="Money-making guide 'Killing the Alchemical Hydra' publishes kph=25 "
    "at Slayer 95, Ranged 75+ recommended - see "
    "tests/test_costing_hydra.py::TestAgainstTheGuide for the oracle "
    "comparison at that gear.",
)
