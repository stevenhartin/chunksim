"""Yama: two stat blocks for her own bar, plus a Judge fought twice in
between - three targets, one continuous kill.

**Three health segments, two `osrs_dps` keys.** [[Yama]] states the
transition thresholds directly: "Shortly after 66.6% and 33.3% of his
health, Yama will slam the pommel of his axe to the ground, teleporting the
player to the pockets of land to the side of the arena, where a Judge of
Yama must be defeated" - then, once the second Judge falls, "he will remain
static in the centre of the room, increasing all of his defence bonuses."
So her own bar has three segments (100-66.6%, 66.6-33.3%, 33.3-0%) but only
two stat blocks: `Yama#Normal` covers the first two - nothing about her own
stats changes between them, only the interruption for a Judge fight does -
and `Yama#Phase 3` covers the last, matching the library's own
`hitpoints=2500` on both keys (each carries the whole bar, exactly the
`fightscripts.Phase` convention `hydra.py`/`hueycoatl.py` already use: a key
is "the whole fight as if only this stat block existed", and `hp_share`
slices it).

`66.6%`/`33.3%` are the page's own rounding of thirds, not two arbitrary
figures - `hp_share=2/3` and `hp_share=1/3` here rather than the rounded
decimals, so the two sum to exactly `1.0` against `Yama#Normal`'s and
`Yama#Phase 3`'s shared `hitpoints=2500`.

### The Judge, fought twice, and never for its own sake

[[Judge of Yama]] carries no drop table of its own in the export -
everything Yama's kill can yield comes off her own table - so the Judge
phase is priced purely as required downtime between the two health segments,
the same "small target killed several times over" shape `hueycoatl.py`'s
body-segment phase and `sire.py`'s lung phase both are: `hp_share=2.0`
against the Judge's own `hitpoints=400`, one phase pricing both fights.
**The bare `Judge of Yama` key, not `Judge of Yama (A Kingdom Divided)`** -
the library carries both, and the second is a different, quest-only
encounter (260 hitpoints, no ranged attack) from the "A Kingdom Divided"
quest rather than the one that gates every repeat Yama kill.

### What stays unmodelled

**The Judge's own damage-immunity mechanics are not represented at all.**
[[Judge of Yama]] states every attack against it "always land[s] as both
successful and maximum hits", and that it demands alternating combat styles
- "The judge will pray reactively towards the last used combat style
against it, so two forms of combat are required in order to kill it."
Neither reaches `osrs_dps`'s ordinary accuracy-and-defence formula: pricing
the Judge phase through the library's normal `dps()` call therefore
under-states its real kill speed (guaranteed max hits are faster than an
accuracy roll ever produces) while the alternation requirement changes
nothing about the total damage needed, only which of the player's own
prayers is briefly unprotected - so this phase is a **ceiling in the slow
direction**, the same caveat `costing/nightmare.py` states for its own
unmodelled totems.

**The brief 50% damage-resistance window right at each threshold** ("After
the threshold is reached but before he teleports the players, he gains 50%
damage resistance to any attacks") has no published duration and is not
modelled - it covers, at most, the last few ticks of a segment already
priced at full rate, and inventing a number for an unstated window was
judged not worth the guess.

Pure: no `osrs_dps` import - `costing/dps_bridge._scripted_kill` is what
turns this into a priced kill.
"""

from __future__ import annotations

from chunksim.costing.fightscripts import FightScript, Phase

YAMA = "Yama"

SCRIPT = FightScript(
    name=YAMA,
    phases=(
        Phase(
            name="Yama (before the second Judge)",
            target="Yama#Normal",
            hp_share=2.0 / 3.0,
            note="100% down to the published 33.3% threshold - both "
            "pre-final-phase segments share one stat block, since nothing "
            "about her own combat changes until the second Judge falls.",
        ),
        Phase(
            name="Judge of Yama (x2)",
            target="Judge of Yama",
            hp_share=2.0,
            note="A separate 400-hitpoint target, fought once at each "
            "threshold - carries no drop table of its own. Priced by the "
            "ordinary accuracy formula, which is a ceiling in the slow "
            "direction: real kills always land as guaranteed maximum hits, "
            "which this project has no path to express. See the module "
            "docstring.",
        ),
        Phase(
            name="Yama (final phase)",
            target="Yama#Phase 3",
            hp_share=1.0 / 3.0,
            note="The published 33.3% remainder, at her raised final-phase "
            "defence.",
        ),
    ),
    note="No money-making guide publishes a kills-per-hour figure for Yama; "
    "unlike the raid/wave-minigame activities, she has a real `osrs_dps` "
    "stat block for every segment, so this is priced from combat maths "
    "directly rather than anchored to a guide. See the module docstring "
    "for what the Judge phase does not model.",
)
