"""Doom of Mokhaiotl: an eight-level climb, one export drop table.

**Eight independent full-health targets, not one boss fought once.**
[[Doom of Mokhaiotl]]'s own mechanics describe a *climb*: beating the boss
at one delve level lets a player either bank or "continue the pursuit
deeper", each level re-fighting the same boss at a harder stat block -
`osrs_dps` carries this exactly, with `Doom of Mokhaiotl#Delve 1` through
`#Delve 8` each its own key and its own rising hitpoints (525, 550, 575,
600, 625, 650, 650, 675 - matched exactly against the library's own
figures). `SCRIPT` prices one full climb through all eight as eight
`hp_share=1.0` phases, the "several independent targets, each fully
depleted" shape `fightscripts.Phase`'s own docstring names Grotesque
Guardians as the worked example of.

**Delve 9 and beyond ("Deep Delve") is not priced.** The library's own
`#Deep Delve` key carries a *lower* `hitpoints=625` than several of the
levels below it - the wiki explains why: "environmental hazards persist,
making them practically harder despite lower health" - and this project has
no way to price a hazard `osrs_dps`'s stat block does not carry. Stopping at
eight is also where the money-making guide's own published bracket stops
(see below).

### What the climb costs beyond the damage race

Three mechanics repeat at every level, none with a directly stated downtime
figure: a demonic shield ("500 shield health"), which "only demonbane
(excluding holy water) will reset the charge" of and which `osrs_dps` has no
representation for at all; larvae that "despawn after ~20 or so seconds";
and a rock-throw whose shockwave triggers "20 ticks (12s) after they
appear". None of the three states how much of that time is genuinely lost
output rather than concurrent with normal attacking, so
`MECHANIC_SECONDS_PER_DELVE` folds all three into one guessed idle window
per level, at the order of magnitude the ~12-20s figures above imply -
**one invented number, the same shape `costing/hydra.py`'s `VENT_SECONDS`
and `costing/nightmare.py`'s totem/sleepwalker constants both are**, stated
here rather than split into three unfounded guesses that would only look
more precise than they are.

### The one thing this module cannot resolve: what the export's rate means

**Loot rolls once per delve level cleared, published exactly**: "Each delve
level rolls once on the regular loot table... For uniques, each one has a
minimum delve level that must be completed in order for it to be rolled,
with their drop rates increasing the deeper the delve level" - Avernic
treads alone moves from 1/1,350 at delve 4 to 1/540 at delve 9+. The
export's own `drops['Doom of Mokhaiotl']` is one flat table with no notion
of depth at all, so **this project cannot tell whether that rate already
represents the accumulated chance across a full climb's eight rolls, a
single level's, or some other blend** - the wiki does not say which depth a
flat "per kill" figure would even mean here. `SCRIPT` prices the *time* for
one full eight-level climb, matching the money-making guide's own published
unit ("Delve 1-8": 10,822,886 gp/hr with 90+ Ranged) - if the export's rate
in fact describes a single level's roll rather than a whole climb's, the
hours this produces for a unique are too high by roughly the ratio of rolls
per climb to one. **Stated rather than silently resolved**, the same
posture `costing/theatre.py` takes on its own guide-vs-model gap.

Pure: no `osrs_dps` import - `costing/dps_bridge._scripted_kill` is what
turns this into a priced kill.
"""

from __future__ import annotations

from chunksim.costing.fightscripts import FightScript, Phase

DOOM_OF_MOKHAIOTL = "Doom of Mokhaiotl"

#: This project's own guess at the shield/larvae/rock-throw mechanics'
#: combined cost each level, at the order of magnitude the published
#: ~12-20 second figures for the individual mechanics imply. See the module
#: docstring - not a measurement, and every hour this script produces is a
#: `GUESS` because of it, however published the hitpoints and thresholds
#: above are.
MECHANIC_SECONDS_PER_DELVE = 15.0

SCRIPT = FightScript(
    name=DOOM_OF_MOKHAIOTL,
    phases=tuple(
        Phase(
            name=f"Delve {level}",
            target=f"Doom of Mokhaiotl#Delve {level}",
            hp_share=1.0,
            idle_seconds=MECHANIC_SECONDS_PER_DELVE,
            note="One full-health kill at this level's own stat block, "
            "plus this project's own guessed downtime for the shield, "
            "larvae and rock-throw mechanics - see the module docstring.",
        )
        for level in range(1, 9)
    ),
    note="Prices one full Delve 1-8 climb, matching the money-making "
    "guide's own published unit. **Whether the export's flat drop rate "
    "means one climb or one level is not stated anywhere this project "
    "found** - see the module docstring's closing section before trusting "
    "an hours figure for a specific unique.",
)
