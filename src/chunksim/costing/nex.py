"""Nex: five phases gated by four bodyguards, a 500-hitpoint heal on the
last one, and a fight this project prices as the duo it actually is.

**Why this is not five different Nex stat blocks.** Unlike the Hydra,
Zulrah or the Kalphite Queen, `osrs_dps` carries exactly one `Nex` key at
`hitpoints=3400` - her own defence does not change between the Smoke,
Shadow, Blood, Ice and Zaros phases, only which style the wiki recommends
*positioning-wise* does ("ranged is highly recommended for the Shadow and
Zaros phases," about kiting and avoiding damage, not about her own stat
block). So her own hitpoints need no phase-by-phase split at all - one
`Phase` against `Nex` prices the whole of her own health, and what
genuinely does need scripting is the four bodyguards interrupting it and
the heal on the last phase.

### The bodyguards: one real fight each, gating progress

`[[Nex]]`: "After Nex has lost 20% of her maximum health, the mage
responsible for empowering Nex can be attacked and must be killed in order
to progress to the next phase." Four thresholds, four mages - `Fumus`
(80%), `Umbra` (60%), `Cruor` (40%), `Glacies` (20%) - each carrying
`hitpoints=500` in `osrs_dps` and each weakest to a different melee
substyle, matched exactly to the wiki's own claims: `Fumus` weakest to
stab (`defence_stab=25`), `Cruor` to slash (`defence_slash=25`), `Glacies`
to crush (`defence_crush=25`), `Umbra` to ranged rather than any melee
substyle (`defence_ranged=25`). None of the four carries a hard
zero-defence exclusion, so - matching every other "merely lopsided" boss
in this subpackage - no `Phase.styles` restriction is applied.

**`Glacies` is the one place the wiki's own practical advice and the raw
numbers disagree, stated rather than hidden**: "weakest to crush attacks,
but should still be ranged" - the strategy page's own reasoning is
positional (staying away from Nex to avoid her freeze), which this
project's combat model does not represent, so an unrestricted search may
prefer crush where a real team would range for safety. This is the same
shape as every other unmodelled positioning mechanic in this subpackage,
named explicitly because the numeric answer and the practical one differ.

**Killing a bodyguard needs no transition time of its own** - nothing on
the wiki states a delay between a bodyguard's death and Nex resuming, so
none is added, unlike `costing/kalphite_queen.py`'s published twelve
seconds.

### The Zaros-phase heal, published exactly

"Nex's fifth and final phase, the Zaros phase, starts when she shouts
'NOW, THE POWER OF ZAROS!' During this phase, Nex will call on Zaros'
power, healing her for 500 hitpoints." A real, stated addition to her own
health total - `hp_share` on her one phase is `(3,400 + 500) / 3,400`
rather than `1.0`, pricing the full 3,900 hitpoints a kill actually
requires rather than her base total alone. This is exactly the "boss can
regenerate health" mechanic this module was asked to price.

### Priced as the duo it is published to be

"She has very high hitpoints and deals relatively high damage even
through protection prayers, so fighting her in a team is effectively a
requirement" - and `Money making guide/Killing Nex (Duo)` is a real,
maintained guide publishing `kph = 6.5` for "a reasonably efficient 2-man
team." `PARTY_SIZE = 2` and `effective_seconds` divides the scripted
kill's own total by it, the same semantic `costing/encounter.build`'s own
`attackers` parameter states: "a party is: `kill_seconds` answers for one
player, and three of them put a boss down in a third of the time" - here
two do it in half. Applied as a separate correction rather than through
`encounter.build` itself, because the phase/bodyguard/heal structure needs
`costing/fightscripts.py`'s per-target style search, which `encounter.build`
does not provide.

### What stays unmodelled

The Blood Siphon special ("all damage she receives will instead heal
her," roughly eight ticks, an unpublished number of times per Blood
phase) is avoidable by simply not attacking during it, so it costs a real
player time but nothing this project can anchor a duration or frequency
on - left out rather than guessed twice over. The essence-gathering
required to reach her chamber is a one-time or occasional barrier crossing,
excluded from the guide's own `kph` ("these rates exclude the time spent
obtaining essence") and from this module for the same reason.

Pure: no `osrs_dps` import - `costing/dps_bridge._scripted_kill` is what
turns this into a priced kill.
"""

from __future__ import annotations

from chunksim.costing.fightscripts import FightScript, Phase

NEX = "Nex"
FUMUS, UMBRA, CRUOR, GLACIES = "Fumus", "Umbra", "Cruor", "Glacies"

#: Published on `[[Nex]]`'s own infobox and matched by `osrs_dps`.
NEX_HITPOINTS = 3400.0

#: Published: "healing her for 500 hitpoints" on entering the Zaros phase.
ZAROS_HEAL_HITPOINTS = 500.0

#: This project's own accepted party size - see the module docstring.
#: `Money making guide/Killing Nex (Duo)` is real, maintained, published
#: content, not an assumption invented here.
PARTY_SIZE = 2

SCRIPT = FightScript(
    name=NEX,
    phases=(
        Phase(
            name="Nex",
            target=NEX,
            hp_share=(NEX_HITPOINTS + ZAROS_HEAL_HITPOINTS) / NEX_HITPOINTS,
            note="Her own 3,400 hitpoints plus the published 500-hitpoint "
            "Zaros-phase heal - one stat block throughout, since "
            "osrs_dps carries no phase-specific version of her.",
        ),
        Phase(
            name="Fumus (Smoke phase's mage)",
            target=FUMUS,
            hp_share=1.0,
            note="Attackable at 80% Nex health. Weakest to stab "
            "(defence_stab=25).",
        ),
        Phase(
            name="Umbra (Shadow phase's mage)",
            target=UMBRA,
            hp_share=1.0,
            note="Attackable at 60% Nex health. Weakest to ranged "
            "(defence_ranged=25) rather than any melee substyle.",
        ),
        Phase(
            name="Cruor (Blood phase's mage)",
            target=CRUOR,
            hp_share=1.0,
            note="Attackable at 40% Nex health. Weakest to slash "
            "(defence_slash=25).",
        ),
        Phase(
            name="Glacies (Ice phase's mage)",
            target=GLACIES,
            hp_share=1.0,
            note="Attackable at 20% Nex health. Weakest to crush "
            "(defence_crush=25) numerically, though the wiki recommends "
            "ranged for positioning reasons this project does not model "
            "- see the module docstring.",
        ),
    ),
    note="Money-making guide 'Killing Nex (Duo)' publishes kph=6.5 for a "
    "2-man team - see tests/test_costing_nex.py::TestAgainstTheGuide for "
    "the oracle comparison, applied after `effective_seconds` divides by "
    "`PARTY_SIZE`.",
)


def effective_seconds(kill_seconds: float) -> float:
    """`kill_seconds` (one player's own solo time against the whole
    scripted fight) divided by `PARTY_SIZE` - `costing/encounter.build`'s
    own `attackers` semantic, applied separately since Nex's phase
    structure needs `costing/fightscripts.py` rather than
    `costing/encounter.py`."""
    return kill_seconds / PARTY_SIZE if PARTY_SIZE > 0 else kill_seconds
