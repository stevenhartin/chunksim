"""Zulrah: one health bar, three forms, and a style switch for each.

**Why this is not "pick the easiest form and price the whole fight there".**
`osrs_dps` indexes Zulrah as three keys - `#Serpentine`, `#Magma`,
`#Tanzanite` - one per form, and every one of them carries the *full*
`hitpoints=500`, exactly the shape `costing/hydra.py`'s four phases take.
Before this module existed, `dps_bridge.best_kill`'s ordinary rule - take
whichever version dies quickest - picked Serpentine every time: her
`defence_magic=-45` there is a magic *bonus* rather than a resistance, so a
magic loadout kills that version in under a minute. The other two forms are
not optional in a real fight - she cycles through all three, and Magma's
`defence_ranged=300` and Tanzanite's `defence_magic=300` are both genuinely
tanky against the style the other forms reward - so pricing the whole 500 HP
at the Serpentine rate understated real kill time by roughly the same
mechanism the Hydra's softest-form bug did, just for a different reason: not
"only a quarter of the bar was priced", but "the wrong three-quarters of the
bar were priced at the easiest form's rate".

### Where the three `hp_share`s come from

**Not published as a fraction anywhere.** Unlike the Hydra's 825/550/275/0
thresholds, nothing states "Zulrah spends X% of a kill in each form" as a
number. What is published, on `Zulrah/Strategies`, is the complete phase
list for all four of her rotations - which form each phase is, and how many
attacks it lasts, since her attack speed (3 ticks, `Infobox Monster`) is the
same in every form and so attack count is a fair proxy for the time a phase
takes.

`WAVE_TALLY` is that count, summed by form across all four rotations - **173
attacks total**, not weighted toward any one rotation, because "at the start
of the fight, Zulrah will be in one of four possible rotations... chosen at
random" and there is no published reason to expect a kill to favour one.
Phases that state no attack count at all - the opening venom-cloud phase
every rotation shares, a handful of pure snakeling-orb phases - contribute
nothing to either side of the split; see "What is not modelled" below.

    Serpentine (green):  95/173 = 0.5491
    Magma (crimson/red): 16/173 = 0.0925
    Tanzanite (blue):    62/173 = 0.3584

**This reduces the same way `costing/tzhaar.py`'s wave tables do**: the
published counts are read straight off the wiki, and this project's own
choice is only *how* to turn a per-phase table into a single split, not the
numbers going into it - `tests/test_costing_zulrah.py` pins the tally against
the wiki's own phase-by-phase text so a transcription slip is a test failure
rather than a silent drift.

### The one guessed number: diving between forms

"Zulrah periodically changes forms by diving into the swamp and resurfacing
somewhere else" - published as a fact, not as a duration. Averaged across the
four rotations there are 10.75 such transitions in one full rotation's worth
of phases (`(10 + 10 + 11 + 12) / 4`, one fewer than each rotation's phase
count). `DIVE_SECONDS_PER_TRANSITION` is this project's own figure for how
long one dive-and-resurface costs, exactly the shape `costing/hydra.py`'s
`VENT_SECONDS` and `costing/nightmare.py`'s totem/sleepwalker constants are -
and, as with both of those, it makes every rate this module produces a
`GUESS`, however published the form split and the health total are.

The total is booked entirely on the Serpentine phase rather than split three
ways, purely for bookkeeping: the dives happen *between* phases regardless of
which two forms they connect, and there is nowhere more meaningful to put a
single combined figure than the phase with the largest share.

### What is not modelled

**Venom, snakelings and the zero-attack phases are not priced in either
direction.** A phase with no stated attack count - filling the arena with
venom clouds, spewing snakeling orbs - is excluded from `WAVE_TALLY`
entirely: not counted as fighting time at any form's rate, and not added as
downtime the way the Hydra's vent or the Nightmare's totems are. This project
found no published duration for these phases to anchor a number on, and a
guessed one would be exactly as invented as `DIVE_SECONDS_PER_TRANSITION`
without the benefit of being named separately - stacking uncosted guesses
where a stated omission is more honest. In practice they are short beside
the ~173 attacks the rotations otherwise total, so the size of what is left
out is small; it is still left out rather than folded in silently.

**The damage cap is not modelled.** "Damage at Zulrah is capped at 50; any
hit greater than this deals 45-50 instead" - `osrs_dps`'s own combat
simulation is expected to apply this itself, being the one module allowed to
know what the library does with a hit roll; this project does not duplicate
it.

Pure: no `osrs_dps` import - `costing/dps_bridge._scripted_kill` is what
turns this into a priced kill, exactly as it does for the other two scripts
in this subpackage.
"""

from __future__ import annotations

from chunksim.costing.fightscripts import FightScript, Phase

#: Attack counts by form, summed across all four published rotations -
#: `tests/test_costing_zulrah.py` pins this against the wiki's own
#: phase-by-phase text. Keys are this module's own short names; `SCRIPT`
#: below is what maps them to `osrs_dps`'s `Zulrah#<Form>` keys.
WAVE_TALLY = {"Serpentine": 95, "Magma": 16, "Tanzanite": 62}

#: `WAVE_TALLY`'s total - the denominator every `hp_share` divides by.
TOTAL_ATTACKS = sum(WAVE_TALLY.values())

#: Guessed - see the module docstring. One dive-and-resurface between forms.
DIVE_SECONDS_PER_TRANSITION = 1.8

#: Transitions in one full rotation's worth of phases, averaged across all
#: four - `(11-1 + 11-1 + 12-1 + 13-1) / 4`, one fewer than each rotation's
#: own phase count.
TRANSITIONS_PER_ROTATION = 10.75

#: The total dive overhead one kill carries, booked on the Serpentine phase -
#: see the module docstring on why one phase rather than a three-way split.
DIVE_SECONDS = DIVE_SECONDS_PER_TRANSITION * TRANSITIONS_PER_ROTATION

SCRIPT = FightScript(
    name="Zulrah",
    phases=(
        Phase(
            name="Serpentine (green)",
            target="Zulrah#Serpentine",
            hp_share=WAVE_TALLY["Serpentine"] / TOTAL_ATTACKS,
            reduced_seconds=DIVE_SECONDS,
            reduced_dps_fraction=0.0,
            note="Weak to Magic (defence_magic=-45, a bonus rather than a "
            "resistance) - the form a magic loadout wants. Carries the "
            "whole fight's dive overhead - see the module docstring.",
        ),
        Phase(
            name="Magma (crimson)",
            target="Zulrah#Magma",
            hp_share=WAVE_TALLY["Magma"] / TOTAL_ATTACKS,
            note="Also weak to Magic (defence_magic=0) and heavily resistant "
            "to Ranged (defence_ranged=300) - the shortest-lived form in "
            "every rotation, always exactly two attacks per occurrence.",
        ),
        Phase(
            name="Tanzanite (blue)",
            target="Zulrah#Tanzanite",
            hp_share=WAVE_TALLY["Tanzanite"] / TOTAL_ATTACKS,
            note="The one form where Ranged wins outright "
            "(defence_magic=300, defence_ranged=0) - matches the strategy "
            "guide's own advice to bring a Ranged switch primarily for this "
            "phase.",
        ),
    ),
    note="Money-making guide 'Killing Zulrah' publishes kph=20 (180s/kill), "
    "matching the strategies page's own 'about three minutes to complete "
    "each full rotation' - a real kill and one rotation are roughly the "
    "same length. No formal oracle test: Zulrah's own guide recommends a "
    "hybrid Magic/Ranged loadout switched per form, which "
    "`costing/oracle.py`'s one-style-per-guide gear builder cannot "
    "construct - see that module's docstring. Sanity-checked by hand "
    "instead: a genuinely mixed loadout correctly lets Magic win Serpentine "
    "and Magma and Ranged win Tanzanite, and the blended rate at "
    "reachable-BiS gear on the benchmark map came out faster than the "
    "guide's own 20kph, which is the expected direction for a 'typical' "
    "guide figure against a strong map's gear.",
)
