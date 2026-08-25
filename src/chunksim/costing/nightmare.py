"""Phosani's Nightmare: one continuous fight, with two mechanics that steal
real time from it - see the module docstring for why they are the only two
modelled.

**Only the solo variant is priceable at all.** `The Nightmare` is team
content and sits in `dps_bridge.GROUP_BOSSES`; `Phosani's Nightmare` is the
solo encounter and the one this module scripts. Its own page states the
difference plainly - fewer, harder phases, but "significantly faster" than
fighting the original with a group.

### Why this is one `Phase`, not four

The page states the fight in two currencies at once: "3 phases of 400 shield
durability and 1 phase of 150 health... a total of 1,350 physical damage" -
and separately, "totem charges needed are 2,400 (1,200 if maging)... for a
total of 2,550 damage". The `osrs_dps` library's own `Target` for `"Phosani's
Nightmare"` carries `hitpoints=3200`, which is neither of those numbers.

**This project has no way to say how the totem-triggered burst - "a powerful
hit on the boss" the totems unleash once charged - divides across her
3200-point bar**, because nothing publishes that split; the 1,350 the wiki
states is the *physical* combat portion alone, and the library's ttk formula
prices whatever `hitpoints` says against her real defence, however that
number is actually made up of physical hits and totem bursts in the real
fight. Splitting `hp_share` across four sub-phases the way `costing/hydra.py`
does needs exactly the number this project does not have. So there is one
`Phase`, `hp_share=1.0`, priced as a plain damage race against the library's
full stat block - the same posture every other single-key boss in this
project takes, and an explicit admission that the totem mechanic's own damage
contribution is folded into that race rather than modelled apart from it.

**This is very likely a ceiling in the slow direction.** If some share of her
3200 HP is genuinely delivered "for free" by the totem bursts rather than by
the player's own accuracy-rolled swings, then pricing the whole bar as an
ordinary fight overstates how long the physical combat actually takes. There
is no published figure to correct this with, so it is stated rather than
guessed away.

### What is scripted: the two mechanics that eat real time

**Per the person who asked for this module**: most of the fight's mechanics
(Flower Power, spores, husks, parasites, Grasping Claws) are dodged rather
than fought, and cost attention rather than clock time against a player who
knows the fight - `costing/hydra.py`'s ceiling caveat applies to all of them
identically and none is scripted. Two mechanics are different in kind: both
genuinely stop the player's damage landing on Phosani's own health bar for a
real stretch of time, which is exactly the `reduced_dps_fraction=0.0` shape
`costing/fightscripts.Phase` already has from the Hydra's vent - here at its
limit, since neither totems nor sleepwalkers take *any* of a normal attack's
damage off her HP within the window this module prices.

- **The totem ("pillar") phase.** Published: four totems per phase, each
  needing 200 charge (100 if attacked with magic, which the totems' own page
  says takes double damage). Not published anywhere this project found: how
  long finding, walking to and charging all four actually takes - the
  strategy page's own advice to "focus on one totem at a time, otherwise ...
  waste a lot of time moving between them" says the walk is real without
  saying how long. `TOTEM_SECONDS_PER_PHASE` is this project's own guess, at
  the order of magnitude four totems and a walk between them implies.
- **The sleepwalker phase, phases 1-3 only.** Published: 2, 3 and 4
  sleepwalkers spawn at the end of phases 1, 2 and 3 respectively, capping at
  four; each has 10 hitpoints and the player always hits it for maximum
  damage - a near-instant kill once one is targeted. What costs time is not
  the kill, which `SLEEPWALKER_SECONDS_PER_KILL` prices as a few seconds of
  interruption (finding it, switching weapon, landing the hit) rather than a
  combat duration in its own right - a guess of the same kind and for the
  same reason as the totem constant.

**Phase four, the "desperation phase", is deliberately given neither.** It
has no totems at all, and its own strategy guide says to ignore the
sleepwalkers it spawns rather than kill them - "focusing on ending the fight
instead of dealing with the sleepwalkers is crucial." Since this module does
not split the fight into four `hp_share`s to begin with, that distinction
shows up as the *only* input two constants below feed: `SCRIPT.phases[0]`
carries three totem-phases' and nine sleepwalkers' worth of downtime and
none of phase four's, because none of it belongs to phase four.

Pure: no `osrs_dps` import - `costing/dps_bridge._scripted_kill` is what
turns this into a priced kill.
"""

from __future__ import annotations

from chunksim.costing.fightscripts import FightScript, Phase

#: Guessed - see the module docstring. Walking to and charging all four
#: totems, once per vented phase.
TOTEM_SECONDS_PER_PHASE = 20.0

#: Vented phases: three, all identical - phases 1 through 3.
_VENTED_PHASES = 3

#: Guessed - see the module docstring. One sleepwalker: the target-switch,
#: the walk, the kill-click. Real damage from a leaked sleepwalker is a
#: survivability cost, not a time one, and is not what this prices.
SLEEPWALKER_SECONDS_PER_KILL = 2.5

#: Published on the boss's own page: 2, 3 and 4 sleepwalkers at the end of
#: phases 1, 2 and 3. Nine, not the "four" cap alone - the cap is the most in
#: any *one* phase, and this project prices every phase's worth.
SLEEPWALKERS_BY_PHASE = (2, 3, 4)

#: The total downtime `SCRIPT`'s one phase carries - three totem phases plus
#: every sleepwalker across phases 1-3. Named so a reader can see the two
#: terms without re-deriving them from the constants above.
DOWNTIME_SECONDS = (
    TOTEM_SECONDS_PER_PHASE * _VENTED_PHASES
    + SLEEPWALKER_SECONDS_PER_KILL * sum(SLEEPWALKERS_BY_PHASE)
)

SCRIPT = FightScript(
    name="Phosani's Nightmare",
    phases=(
        Phase(
            name="Full fight",
            target="Phosani's Nightmare",
            hp_share=1.0,
            reduced_seconds=DOWNTIME_SECONDS,
            reduced_dps_fraction=0.0,
            note="Priced against the library's full 3200 hitpoints as one "
            "continuous fight - see the module docstring on why this is not "
            "split into the page's four phases. Downtime carries three "
            "totem ('pillar') phases and nine sleepwalker kills; phase "
            "four's desperation sleepwalkers are deliberately excluded, "
            "since the boss's own strategy guide says to ignore them.",
        ),
    ),
    note="Money-making guide 'Killing Phosani's Nightmare' exists but this "
    "project has not built an oracle test against it - see "
    "tests/test_costing_hydra.py::TestAgainstTheGuide for the pattern this "
    "would follow.",
)
