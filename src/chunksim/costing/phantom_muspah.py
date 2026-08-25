"""Phantom Muspah: a ranged/melee alternation split by damage rather than
health fraction, then a shield that costs real time without touching his
health bar at all.

### The alternation is damage-chunked, not phase-fraction-split

`[[Phantom Muspah]]`: "alternates between a ranged form and a melee form
roughly every 100 damage in ranged form and 80 damage in melee form that it
takes" - unlike the Hydra's clean quarters or Zulrah's rotation-table split,
his phases are sized in *damage dealt*, not in a published fraction of his
`hitpoints=850`. Converted to shares of that total: 723 of his 850
hitpoints alternate in `100:80` chunks before the shield triggers (see
below), which is `723 x (100/180) = 401.67` in ranged form and
`723 x (80/180) = 321.33` in melee form - `hp_share=0.4725` and `0.3780`
respectively, both read straight off that division rather than assumed
equal the way `costing/hydra.py`'s quarters are.

**Which style each favours is published and matched by `osrs_dps`
exactly**: "in its range form... is weakest to ranged... In this form
[melee] it is weakest to magic" - `Phantom Muspah#Ranged` carries
`defence_magic=437` against `defence_ranged=56`, and `#Melee` the reverse
shape at `defence_magic=34` against `defence_ranged=261`. Neither is a
hard zero, so - matching the Kalphite Queen and every other "merely very
lopsided" boss in this subpackage - no `Phase.styles` restriction is
applied; the gap alone is enough for the ordinary search to find the right
style.

### The shield: real time, no progress against his own health

"Upon reaching less than 127 health, the Phantom Muspah will teleport to
the centre of the arena... It then activates a prayer shield... The shield
should be drained via using Smite... After the shield is depleted it will
return to its ranged form." `Phantom Muspah#Shielded` is its own
`hitpoints=75` key, entirely separate from his `850` - **damage spent on it
does not reduce his own health at all**, exactly the shape the user asked
this module to make explicit: "he has a shield phase where we hit a shield
which won't appear as actual damage on the boss." That is
`costing/fightscripts.py`'s third `Phase` shape, "one small target," the
same one `costing/sire.py`'s lung phase is - `hp_share=1.0` against the
shield's own 75-hitpoint pool, contributing pure overhead to the fight
rather than a slice of the 850.

`Phantom Muspah#Post-shield` carries the identical stat block `#Ranged`
does (`defence_magic=437`/`defence_ranged=56`) - "return to its ranged
form" is exactly that - so the remaining `127` hitpoints (`850 - 723`,
`hp_share=0.1494`) are priced against it rather than against `#Ranged`
itself, keeping the phase list in the order the fight actually visits them.

### What stays unmodelled

The two special attacks (Lightning Clouds, Homing Spikes) at 75%/50% health
and the arena-covering spike mechanic are avoidable per the wiki's own
strategy sections and are not costed, matching every other boss module in
this subpackage. The "roughly" in the wiki's own phrasing on the 100/80
split is not resolved further than the arithmetic above - a boss whose own
page will not commit to an exact number is not one this project should
invent more precision for.

Pure: no `osrs_dps` import - `costing/dps_bridge._scripted_kill` is what
turns this into a priced kill.
"""

from __future__ import annotations

from chunksim.costing.fightscripts import FightScript, Phase

PHANTOM_MUSPAH = "Phantom Muspah"

#: Published: total hitpoints, and the damage chunk each form takes before
#: alternating - `[[Phantom Muspah]]`'s own "roughly every 100 damage in
#: ranged form and 80 damage in melee form."
TOTAL_HITPOINTS = 850.0
RANGED_CHUNK = 100.0
MELEE_CHUNK = 80.0

#: Published: the shield triggers "upon reaching less than 127 health" -
#: the point the 100/80 alternation stops.
SHIELD_TRIGGER_HITPOINTS = 127.0
BEFORE_SHIELD_HITPOINTS = TOTAL_HITPOINTS - SHIELD_TRIGGER_HITPOINTS

#: The 100:80 split of `BEFORE_SHIELD_HITPOINTS` - see the module
#: docstring for the arithmetic.
_CYCLE = RANGED_CHUNK + MELEE_CHUNK
_RANGED_BEFORE_SHARE = BEFORE_SHIELD_HITPOINTS * (RANGED_CHUNK / _CYCLE) / TOTAL_HITPOINTS
_MELEE_BEFORE_SHARE = BEFORE_SHIELD_HITPOINTS * (MELEE_CHUNK / _CYCLE) / TOTAL_HITPOINTS
_AFTER_SHIELD_SHARE = SHIELD_TRIGGER_HITPOINTS / TOTAL_HITPOINTS

SCRIPT = FightScript(
    name=PHANTOM_MUSPAH,
    phases=(
        Phase(
            name="Ranged (before shield)",
            target="Phantom Muspah#Ranged",
            hp_share=_RANGED_BEFORE_SHARE,
            note="Weakest to ranged (defence_ranged=56 against "
            "defence_magic=437). Published damage chunk: 100.",
        ),
        Phase(
            name="Melee (before shield)",
            target="Phantom Muspah#Melee",
            hp_share=_MELEE_BEFORE_SHARE,
            note="Weakest to magic (defence_magic=34 against "
            "defence_ranged=261). Published damage chunk: 80.",
        ),
        Phase(
            name="Shield",
            target="Phantom Muspah#Shielded",
            hp_share=1.0,
            note="A separate 75-hitpoint pool - damage here does not "
            "reduce his own health at all. See the module docstring.",
        ),
        Phase(
            name="Ranged (after shield)",
            target="Phantom Muspah#Post-shield",
            hp_share=_AFTER_SHIELD_SHARE,
            note="'Return to its ranged form' - same stat block as "
            "#Ranged, finishing the remaining 127 hitpoints.",
        ),
    ),
    note="Money-making guide 'Killing Phantom Muspah (Twisted bow)' "
    "publishes kph=25, noting '30 can be achieved by using magic during "
    "the melee phases' - independent confirmation that switching style "
    "per phase, exactly what this script does, is the real optimal play. "
    "See tests/test_costing_phantom_muspah.py::TestAgainstTheGuide.",
)
