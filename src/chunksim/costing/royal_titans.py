"""The Royal Titans: two identical bosses fought together, priced apart.

**Why this needs a script at all.** `Eldric the Ice King` and `Branda the
Fire Queen` each carry a real drop table in the export - `Deadeye prayer
scroll` under Eldric's, `Fire element staff crown` under Branda's - so
nothing here is missing a chest the way a raid's is. The gap is narrower and
easy to miss: **you cannot fight one without fighting both.** `[[Royal
Titans]]`: "Rulers over their domains... Branda is set on expanding her
territory and has begun clashing with Eldric" - they share one arena and
one encounter, and "when one of the giants reaches 35%... both will
teleport onto the arena" to finish together. Pricing `Eldric` alone at his
own 600 hitpoints - which is exactly what `dps_bridge.best_kill`'s ordinary
resolution would do, since he is an unambiguous bare key with his own real
table - understates a real completion by half: the other 600 hitpoints of
Branda still have to go down in the same encounter, whichever one is
looted afterward.

### Both scripts price the same 1,200 hitpoints, not 600 twice over

**`Eldric` and `Branda` are the same monster in every stat that matters** -
`osrs_dps` gives them identical `hitpoints=600` and an identical
`StatBlock`, matching the wiki's "similar but different standard drops"
framing exactly: cosmetically distinct, mechanically twins. That makes this
the third shape `costing/fightscripts.py`'s `Phase` docstring names - "one
small target, killed several times over" - except the two "times" are two
different monsters rather than one killed again: `hp_share=2.0` against
`Eldric`'s own key prices the whole encounter (both titans, 1,200
hitpoints) at Eldric's stat block, and the mirrored script against
`Branda`'s key prices the identical 1,200 hitpoints at hers - which, since
the two stat blocks are equal, is the same number reached two ways. Both
scripts exist rather than one, because a reader asking about `(Royal
Titans) Obtain a fire element staff crown` looks `Branda` up by her own
name, and `Heuristics.kills_per_hour` has to answer that lookup directly
rather than through Eldric's.

### What stays unmodelled

**Which one is looted is not this module's question.** "Loot" rolls twice
on whichever titan's table the player chooses - Eldric's own table already
prices at that roll count, unmodified - so a player farming Eldric's unique
loots Eldric every time and this module's only job is pricing how long one
full encounter (both titans dead) takes to reach that choice.

The elemental adds, the arena-wide spell, and the "walk one tile" melee
-range gating are real mechanics with no published duration this project
could anchor a number on, so - matching the refusal already stated for
Araxxor, Cerberus and Sol Heredit - they are not scripted. Neither titan's
defence is a hard zero against any style (Eldric/Branda are merely very
tanky to ranged and magic, `defence_ranged=defence_magic=700` against
`defence_crush=0`), so no `Phase.styles` restriction is needed either -
`dps_bridge`'s ordinary style search already finds melee correctly on the
strength of that gap alone.

Pure: `FightScript`/`Phase` construction only, no `osrs_dps` import - the
Royal Titans are registered into `dps_bridge.SCRIPTS` by that module,
exactly as every other scripted boss in this subpackage is.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.costing.fightscripts import FightScript, Phase

ELDRIC = "Eldric the Ice King"
BRANDA = "Branda the Fire Queen"

#: Both titans' own encounter, keyed by whichever name a caller asks about -
#: see the module docstring on why one script each rather than a single
#: shared one.
SCRIPTS: Mapping[str, FightScript] = {
    name: FightScript(
        name=name,
        phases=(
            Phase(
                name=name,
                target=name,
                hp_share=2.0,
                note="Both titans share one encounter and identical stats "
                "- 1,200 hitpoints total, priced at this one's own stat "
                "block. See the module docstring.",
            ),
        ),
        note="Killing either titan requires killing both - 'Loot' rolls "
        "twice on whichever one the player chooses afterward, at that "
        "titan's own published table.",
    )
    for name in (ELDRIC, BRANDA)
}
