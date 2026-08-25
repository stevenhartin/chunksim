"""Grotesque Guardians: a duo fight, Dawn and Dusk each killed in two
instalments, each with a real style restriction the library does not encode.

### The shape: two independent targets, each fully depleted

`osrs_dps` indexes this boss as `Dawn` and `Dusk#First form`/`Dusk#Second
form`, three keys, each carrying the *full* `hitpoints=450` for its own
monster - **not** the "one shared pool" shape `costing/hydra.py` and
`costing/zulrah.py` are. `[[Grotesque Guardians]]`: "The fight consists of
four phases, of which the first and third phases require the player to
fight Dawn, and the second and final phases requiring the player to fight
Dusk... The second phase starts once Dawn's health reaches around 50%...
The next phase starts when Dusk's health reaches around 50%... After killing
Dawn, Dusk will absorb her essence, increasing his stats... initiating the
last phase." So each monster is fought to 50% and finished later:
`hp_share=0.5` on each of Dawn's two phases and each of Dusk's two phases -
Dawn's pair sums to `1.0` on their own and so does Dusk's, the "several
independent targets, each fully depleted" shape `Phase`'s own docstring
names this boss as the example of. The script's total `hp_share` is `2.0`,
correctly pricing two separate full-health kills.

**Dusk's two phases are different library keys, not the same one twice**,
because his stats genuinely change: "Dusk will absorb her essence,
increasing his stats (barring his health)" - `#First form` and `#Second
form` are that pre/post split, both reporting the same `450` total since
each is "the whole of Dusk's fight, priced as if only this stat block
existed", exactly the pattern every other scripted boss's per-phase key
follows.

### The style restriction `osrs_dps` does not encode

**This is the first script in this subpackage that needs `Phase.styles`.**
Dawn and Dusk both carry ordinary all-zero defence bonuses in the library -
nothing marks either restriction below as a wall rather than a weakness:

- **Dawn** "is flying and cannot be targeted by non-halberd melee weapons."
  This project's loadout builder has no notion of "melee, but only a
  halberd" - a coarser exclusion than the real rule, but the honest one
  available: `styles={"Ranged", "Magic"}` on both of Dawn's phases, Melee
  refused outright rather than approximated as "ordinary melee, priced as if
  it worked."
- **Dusk** "is completely immune to magic and ranged damage." Both of his
  phases carry `styles={"Melee"}`.

Without this, `dps_bridge.kills_by_style`'s ordinary search would happily
price whichever of Magic or Ranged has the best raw numbers against Dusk's
undefended stat block - a style that deals zero damage in the real fight -
which is exactly the same failure shape the Hydra's and Zulrah's
softest-form bugs were, just caused by a missing exclusion instead of a
missing split.

### What stays unmodelled

**The "flies back down" transition before phase 3 is the one guessed
number.** The changelog that removed the outbound transition ("The lightning
transition phase when Dawn flies away during the fight has been removed...")
also says the inbound one survived: "The transition when she flies back will
still occur." Nothing publishes how long it takes, so `TRANSITION_SECONDS`
below is this project's own figure, in the same shape `costing/hydra.py`'s
`VENT_SECONDS` is - modelled as a zero-rate window
(`reduced_dps_fraction=0.0`), the same choice `costing/nightmare.py` makes
for its totem and sleepwalker downtime, since nothing publishes a *reduced*
rather than *zero* rate for it either. Every rate this module produces is a
`GUESS` because of it.

Energy spheres (healing Dawn 90 HP each if not absorbed), rubble stuns, the
explosive wave and the flame-prison grab are avoidable per the wiki and not
costed, matching every other module in this subpackage.

Pure: no `osrs_dps` import - `costing/dps_bridge._scripted_kill` is what
turns this into a priced kill.
"""

from __future__ import annotations

from chunksim.costing.fightscripts import FightScript, Phase

_RANGED_OR_MAGIC = frozenset({"Ranged", "Magic"})
_MELEE_ONLY = frozenset({"Melee"})

#: Guessed - see the module docstring. Dawn's flight back down before phase
#: 3, the one phase transition the wiki still confirms happens.
TRANSITION_SECONDS = 3.0

SCRIPT = FightScript(
    name="Grotesque Guardians",
    phases=(
        Phase(
            name="Dawn (to ~50%)",
            target="Dawn",
            hp_share=0.5,
            styles=_RANGED_OR_MAGIC,
            note="Flying, and 'cannot be targeted by non-halberd melee "
            "weapons' - Melee excluded outright rather than approximated. "
            "See the module docstring on Phase.styles.",
        ),
        Phase(
            name="Dusk (to ~50%)",
            target="Dusk#First form",
            hp_share=0.5,
            styles=_MELEE_ONLY,
            note="'Completely immune to magic and ranged damage' - only "
            "Melee is offered.",
        ),
        Phase(
            name="Dawn (finish)",
            target="Dawn",
            hp_share=0.5,
            styles=_RANGED_OR_MAGIC,
            reduced_seconds=TRANSITION_SECONDS,
            reduced_dps_fraction=0.0,
            note="Same style restriction as the first Dawn phase. Carries "
            "the one guessed transition - 'the transition when she flies "
            "back will still occur', duration unpublished.",
        ),
        Phase(
            name="Dusk (finish, absorbed Dawn)",
            target="Dusk#Second form",
            hp_share=0.5,
            styles=_MELEE_ONLY,
            note="Stronger stats after absorbing Dawn's essence ('barring "
            "his health'), hence the separate library key - still Melee "
            "only.",
        ),
    ),
    note="Money-making guide 'Killing Grotesque Guardians' publishes kph=24 "
    "- see tests/test_costing_grotesque_guardians.py::TestAgainstTheGuide "
    "for the oracle comparison. Requires a gargoyle Slayer task and the "
    "roof unlocked with a brittle key, per the guide's own 'Other' field.",
)
