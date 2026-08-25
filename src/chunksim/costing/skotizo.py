"""Skotizo: gated on a dark totem, assembled from three pieces farmed
elsewhere and consumed to reach the fight.

**The fight is not the rate, and the reason is a different shape from
Hespori's.** `Skotizo` already carries a real drop table in the export, so
the ordinary combat kph is right about the fight itself. What it does not
know is that the fight cannot start at all without a [[dark totem]], one
consumed per attempt: "It is used on the altar in the centre of the
Catacombs of Kourend to access the lower level of the catacombs to fight
Skotizo. The totem is consumed when using it on the altar regardless of the
outcome of the fight." Every kill therefore costs the fight *plus* however
long the totem took to assemble - and unlike a raid's entry fee, the totem
is not itself a monster with a kph: it is farmed from a chance shared across
several unrelated monsters, so the time it costs has to be optimised over
which of them to fight, not looked up.

### The totem: three pieces, one published formula

`[[Dark totem]]`: "The totem pieces are dropped in that order and duplicates
drop after all three are obtained" - base, then middle, then top, strictly
sequential, so three pieces is three independent waits at the same
mechanic, not a coupon-collector problem over three distinct items. Every
non-superior, non-Skotizo source shares one formula, stated on the totem's
own page and on each piece's: `1/(500-H)`, where `H` is the killed
monster's own hitpoints. **`Superior slayer monster`s are excluded** - a
guaranteed drop the ordinary formula does not describe - and so are ghosts,
both per the totem's own page.

### Why low-hp monsters win, and why this optimises rather than assumes it

The wiki states the qualitative answer outright: "Since the improvement in
drop rate as monster HP increases is very small, dark totem pieces can be
most quickly obtained by killing low HP monsters within the catacombs, such
as hill giants." That is evidence for a *shape* - kill time grows much
faster than `1/(500-H)` falls as H rises - not a licence to hardcode one
monster's name as the answer for every map: two candidates can have the
same hitpoints and very different kill times depending on what a chunk map
actually reached, which is exactly the question `dps_bridge` exists to
answer. `totem_seconds` below tries every entry in `CANDIDATE_HITPOINTS`
against the map's own `KillSeconds` and keeps whichever gives the fastest
piece rate, the same "try every candidate, keep the fastest" shape
`dps_bridge.best_kill` uses across styles and `derive/bis.py` across gear.

**`CANDIDATE_HITPOINTS` is a curated subset, not the Catacombs' full
roster, and that is a stated scoping choice rather than an oversight.** The
dungeon holds two dozen more monsters (demons, dragons, nechryael and
similar), all combat level 85 and up - the wiki's own "very small
improvement" claim means none of them can beat a candidate a fifth their
hitpoints on pieces-per-hour, whatever a map's gear looks like, so including
them would multiply this module's surface for an answer that never changes.
Six low-hitpoint candidates from the Catacombs of Kourend and the Giants'
Den (which "have access to the Catacombs of Kourend drop table") are kept,
each hitpoint figure the specific level the location's own page states
(`Hill Giant`'s own Reeking Cove/Giants' Den level, `Ankou`'s stated 95,
`Moss giant`'s stated 42) rather than an unrelated version elsewhere in the
game that happens to share the name.

**One approximation, stated rather than hidden**: three of the six
candidates (`Magic axe`, `Moss giant`, `Ankou`) are ambiguous names in
`osrs_dps`, and `best_kill`'s ordinary resolution - not this module - picks
whichever *version* dies fastest, which need not be the exact hitpoints
`CANDIDATE_HITPOINTS` states. Where the ambiguous versions share identical
hitpoints (`Magic axe`) this costs nothing; where they do not (`Ankou`,
`Moss giant`), the wiki's own "very small improvement" claim bounds the
error the same way it justifies excluding the high-hitpoint majority of the
dungeon in the first place.

### Where the correction happens

Applied by `costing/dps_bridge.enrich` directly to the `Rate` that
`price_monsters` already computed for both `Skotizo` and every totem
candidate - no re-simulation, since `Skotizo`'s own kill time and each
candidate's are already in hand by the time this runs. If no candidate can
be priced at all (none reachable), `Skotizo`'s entry is dropped rather than
left at its uncorrected, too-fast combat-only rate - this project would
rather report nothing than a wrong kill time, matching every other refusal
in this subpackage.

Pure: no `osrs_dps` import - `KillSeconds` is handed in, matching every
other encounter-shaped module in this subpackage.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.costing.encounter import KillSeconds

SKOTIZO = "Skotizo"

#: Pieces needed per totem - always exactly one of each, strictly
#: sequential. See the module docstring.
PIECES_NEEDED = 3

def piece_chance(hitpoints: float) -> float:
    """The per-kill chance of a dark totem piece from a monster with
    `hitpoints` health.

    Published on `[[Dark totem]]` and each piece's own page, for any
    non-superior, non-Skotizo monster in the Catacombs of Kourend or the
    Giants' Den: `1/(500-H)`.
    """
    return 1.0 / (500.0 - hitpoints)


#: `{monster: hitpoints}` - see the module docstring on why these six and no
#: others. Hitpoints are the specific location-stated level, read off
#: `osrs_dps`'s own stat block for that exact key:
#:
#: - `Hill Giant` (28 combat, Reeking Cove and Giants' Den): 35
#: - `Skeleton (Catacombs of Kourend)` (22 combat, Reeking Cove): 29
#: - `Possessed pickaxe#Catacombs of Kourend` (Reeking Cove): 40
#: - `Magic axe` (42 combat, Reeking Cove): 44 - both `osrs_dps` versions
#:   share this figure, so the ambiguous-name approximation costs nothing
#:   here.
#: - `Moss giant` (42 combat, Reeking Cove/Shallows/Giants' Den): 60
#: - `Ankou` (95 combat, Reeking Cove, matching `osrs_dps`'s own
#:   `Ankou#Level 95`): 60
CANDIDATE_HITPOINTS: Mapping[str, float] = {
    "Hill Giant": 35.0,
    "Skeleton (Catacombs of Kourend)": 29.0,
    "Possessed pickaxe#Catacombs of Kourend": 40.0,
    "Magic axe": 44.0,
    "Moss giant": 60.0,
    "Ankou": 60.0,
}


def totem_seconds(kill_seconds: KillSeconds) -> float | None:
    """Seconds to assemble one dark totem at the map's own best candidate,
    or `None` if none of `CANDIDATE_HITPOINTS` can be priced.

    One candidate's own `hp_share`-free arithmetic: `kill_seconds(name) /
    piece_chance(hp)` is that candidate's expected seconds per piece, and
    three pieces at the winning candidate's rate is `3x` that - see the
    module docstring on why three sequential pieces need no
    coupon-collector term.
    """
    best: float | None = None
    for name, hitpoints in CANDIDATE_HITPOINTS.items():
        found = kill_seconds(name)
        if found is None or found <= 0:
            continue
        chance = piece_chance(hitpoints)
        if chance <= 0:
            continue
        per_piece = found / chance
        if best is None or per_piece < best:
            best = per_piece
    return None if best is None else best * PIECES_NEEDED
