"""The Abyssal Sire: a lung phase against four small targets, then three
combat phases against one health bar split at published thresholds.

### Why this is not one damage race

`osrs_dps` indexes the Sire as `Respiratory system` (50 hitpoints, fought
four times) plus three combat keys - `#Phase 2`, `#Phase 3 (stage 1)`,
`#Phase 3 (stage 2)` - each carrying the *full* `hitpoints=425`, the same
"whole fight, priced as if only this stat block existed" shape
`costing/hydra.py` and `costing/zulrah.py` both use. `#Phase 1` does not
appear at all: the Sire's own health bar takes no damage during the lung
phase (`[[Abyssal Sire]]`: "In the first phase players must kill the Sire's
four respiratory systems... The Sire can be disoriented by... dealing 75
damage to it", which stuns rather than depletes), so nothing here prices a
`#Phase 1` key against the Sire itself.

### The four phases, and where each number comes from

**The lung phase is a small target killed four times over**, the third shape
`Phase`'s own docstring names: `hp_share=4.0` against `Respiratory system`
prices "kill this 50-hp target four times", which is exactly what the wiki
states - four respiratory systems, each its own kill, none of which touches
the Sire's 425-hitpoint bar.

**The three combat-phase thresholds are published in hitpoints, not as a
rounded fraction**: "When the Sire gets below 210 health, it will walk to
the middle of the room..." and "When the Sire gets below 140 health, it will
teleport the player...". That reads as three windows against the 425 total:

    Phase 2:            425 -> 210 (215 hp, hp_share = 215/425 = 0.5059)
    Phase 3 (stage 1):  210 -> 140 ( 70 hp, hp_share =  70/425 = 0.1647)
    Phase 3 (stage 2):  140 ->   0 (140 hp, hp_share = 140/425 = 0.3294)

215 + 70 + 140 = 425 exactly, and the three fractions sum to `1.0` - the
"one shared pool" shape, same as every combat-phase key reporting the boss's
full health.

### The transition reduction, and the one guessed number in this module

"Damage dealt to the Sire while it is transitioning between phases is
reduced by 50%" is published outright, and the update log that introduced it
("Increased Sire's Hitpoints by 25 and introduced a 50% damage reduction
during its transition phases") uses the plural - not one exception the way
the Hydra's "barring the last phase" is. Each of the three combat phases'
own entry into the fight is described as its own transition: getting off the
throne into Phase 2, walking to the middle at 210 health into stage 1, and
teleporting the player at 140 health into stage 2 - so `TRANSITION_SECONDS`
below is applied at the start of all three, none excepted.

**How long a transition actually takes is not published anywhere this
project found**, so `TRANSITION_SECONDS` is this project's own figure -
smaller than `costing/hydra.py`'s `VENT_SECONDS` because a walk to the
middle of the room or an instant teleport is quicker than luring across the
arena to a vent and back. Every rate this module produces is therefore a
`GUESS`, exactly as Hydra's is, however published the 50% figure and the
phase thresholds are.

### What stays unmodelled

The lung-phase mechanics beyond the kill itself - poison fumes, spawns
maturing into scions if ignored - are avoidable per the wiki and not costed,
matching every other module in this subpackage. Phase 2's forced-teleport
retaliation for standing too far away is player error, not a mechanic a
correct fight pays. This is a ceiling, not an expectation.

Pure: no `osrs_dps` import - `costing/dps_bridge._scripted_kill` is what
turns this into a priced kill.
"""

from __future__ import annotations

from chunksim.costing.fightscripts import FightScript, Phase

#: Guessed - see the module docstring. How long one phase-transition (a walk
#: or a teleport) costs before full-rate damage resumes.
TRANSITION_SECONDS = 3.0

#: Published on the boss's own page: the reduction each transition applies.
TRANSITION_DPS_FRACTION = 0.5

#: The Sire's own health total - `hp_share`s for the three combat phases are
#: quoted from the published 210/140 thresholds against this.
TOTAL_HITPOINTS = 425.0

SCRIPT = FightScript(
    name="Abyssal Sire",
    phases=(
        Phase(
            name="Lung phase",
            target="Respiratory system",
            hp_share=4.0,
            note="Four respiratory systems, 50 hitpoints each, none of which "
            "touches the Sire's own health bar. Published mechanic, no "
            "guessed constant.",
        ),
        Phase(
            name="Phase 2",
            target="Abyssal Sire#Phase 2",
            hp_share=215.0 / TOTAL_HITPOINTS,
            reduced_seconds=TRANSITION_SECONDS,
            reduced_dps_fraction=TRANSITION_DPS_FRACTION,
            note="425 -> 210 health, published threshold. Transitioned on "
            "entry - the Sire getting off its throne.",
        ),
        Phase(
            name="Phase 3 (stage 1)",
            target="Abyssal Sire#Phase 3 (stage 1)",
            hp_share=70.0 / TOTAL_HITPOINTS,
            reduced_seconds=TRANSITION_SECONDS,
            reduced_dps_fraction=TRANSITION_DPS_FRACTION,
            note="210 -> 140 health, published threshold. Transitioned on "
            "entry - the walk to the middle of the room.",
        ),
        Phase(
            name="Phase 3 (stage 2)",
            target="Abyssal Sire#Phase 3 (stage 2)",
            hp_share=140.0 / TOTAL_HITPOINTS,
            reduced_seconds=TRANSITION_SECONDS,
            reduced_dps_fraction=TRANSITION_DPS_FRACTION,
            note="140 -> 0 health, published threshold - the final stretch. "
            "Transitioned on entry - the forced teleport.",
        ),
    ),
    note="Money-making guide 'Killing the Abyssal Sire' publishes kph=39 - "
    "see tests/test_costing_sire.py::TestAgainstTheGuide for the oracle "
    "comparison. Can only be fought on a Slayer task, matching the wiki's "
    "own note on the guide page.",
)
