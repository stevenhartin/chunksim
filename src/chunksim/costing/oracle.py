"""A money-making guide's own gear, simmed - the calibration a bare `kph`
comparison cannot give.

**Why comparing a map's kph to a guide's is usually meaningless.**
`costing/dps_overhead.py` already says this about the trash-mob rates it
fits: "the wiki's rates assume near-max gear and this project's `ttk` comes
from chunk-restricted BiS, so the two are not the same fight." That is worse
for a single boss than for a trash mob, because the gap between a chunk map's
gear and a guide's stated Twisted bow and Rigour is bigger, not smaller. This
module answers a narrower, honest question instead: **at the gear and levels
the guide itself states, does this project's simulator reproduce the guide's
own `kph`?** That is a real test of the *model*, uncontaminated by which
chunks any particular map has unlocked.

### Single bosses only, and this is a constraint on the caller, not a defect

A guide's `kph` is a kill rate for **one monster fought alone**. `costing/
raids.py` and `costing/tzhaar.py` price a *run* - a raid's rooms, an
Inferno's sixty-nine waves - and no guide states "kph" for either: the
Theatre's guide states raids-per-hour for a trio, which is a different
quantity divided by a different thing. Feeding a raid or a wave minigame's
final boss through this module would compare a solo kill time against a
number that was never describing one. **Nothing here enforces that
distinction** - `oracle_rate` will happily price `TzKal-Zuk` if asked - so a
caller building a per-boss oracle test is the one who has to have made this
choice, and `tests/test_costing_hydra.py`'s own docstring says so rather than
leaving it to be discovered.

### Where the gear comes from, and what is deliberately not attempted

`remote.wiki.MmgRates.gear_links` is unfiltered wiki prose - `[[Twisted
bow]]` beside `[[Ranged armour]]` (not an item) and `[[Rada's blessing 3 or
4]]` (a teleport, not gear). `gear_from_guide` keeps whatever resolves
against `ChunkInfo.equipment`, which is the project's one static, map-free
reference table for every item's stats - and drops the rest silently, the
same "take what parses, let the rest go" posture `remote/wiki.py`'s own
parsers take toward malformed wikitext.

**Which style a guide is written for is read off its own `Skill=` levels**,
not guessed from item names: a `Ranged` entry in `skill_levels` means a
Ranged guide. **A slot two candidate items both want is resolved by which
gives the larger bonus in that style** - `Twisted bow` beats `Toxic
blowpipe` on `attack_ranged` - rather than by which the wiki listed first,
since guide prose orders items by narrative, not by rank.

**No accuracy is spent modelling anything the guide does not state.** A
guide's `Item=` field is the gear it recommends and its `Skill=` field the
levels it assumes; boosts and prayer are read the same way every other
loadout in this project reads them, through `assemble_kit` on the guide's own
`inputs`. Nothing here infers "the player also brought an ice barrage" or
similar - if the guide does not say so, this does not model it.

Pure aside from the one call it makes into `dps_bridge.best_kill`, behind the
same `_require` guard every other DPS-touching call in this project takes.
"""

from __future__ import annotations

from typing import Mapping

from chunksim.derive.sources import SourceIndex
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.remote.wiki import MmgRates

#: `skill_levels` key -> the style it names. Checked in this order, so a
#: guide naming more than one (rare) reads as the first it states here.
_STYLE_SKILLS: tuple[tuple[str, str], ...] = (
    ("Ranged", "Ranged"),
    ("Magic", "Magic"),
    ("Strength", "Melee"),
    ("Attack", "Melee"),
)

#: The stat(s) this style's weapon choice is ranked on, when two guide items
#: compete for the same slot. Summed where there is more than one.
#:
#: **Magic is two fields, not one, and that was a real bug.** A powered
#: staff - `Trident of the swamp`, `Sanguinesti staff` - deals its damage
#: through a level-scaled formula the export represents as `attack_magic`
#: alone; `magic_damage` on both reads `0`. Ranking on `magic_damage` alone
#: tied every real magic weapon with every melee one at zero, and a tie
#: resolves to whichever `gear_links` lists first - which handed
#: `Phosani's Nightmare`'s guide its `Inquisitor's mace` (a crush weapon)
#: as its **Magic** weapon, because the mace happened to be named earlier in
#: the guide's prose than either staff. Measured against both: `attack_magic`
#: is `25` for each staff and `0` for the mace, which is the field that
#: actually tells them apart.
_RANK_FIELDS: Mapping[str, tuple[str, ...]] = {
    "Melee": ("melee_strength",),
    "Ranged": ("ranged_strength",),
    "Magic": ("attack_magic", "magic_damage"),
}


def style_of(guide: MmgRates) -> str:
    """Which combat style `guide`'s own `Skill=` levels are written for.

    Defaults to `Melee` when the guide names none of `Attack`/`Strength`/
    `Ranged`/`Magic` - a guide for something with no combat-style requirement
    at all is not one this module is meant for, and `Melee` is the styling
    `build_loadouts` falls back to bare-handed rather than pricing nothing.
    """
    for skill, style in _STYLE_SKILLS:
        if skill in guide.skill_levels:
            return style
    return "Melee"


#: `"weapon"` and `"2h"` are mutually exclusive - a two-handed weapon
#: replaces the shield rather than sitting beside it - so a guide naming one
#: of each competes for the *same* choice, not two independent ones.
#: `build_loadouts` does not enforce this itself: it sums whatever entries a
#: caller hands it, on the documented assumption that a caller never hands it
#: both. `gear_from_guide` collides them under this shared key before either
#: reaches a real slot.
_WEAPON_SLOT_GROUP = "weapon"


def gear_from_guide(chunk_info: ChunkInfo, guide: MmgRates) -> dict[str, str]:
    """`{"{style}-{slot}": item}` picks, from whichever of `guide.gear_links`
    is real equipment.

    One style only - `style_of(guide)`'s answer - because a guide's `Item=`
    field describes one loadout, not a wardrobe. A slot two items both claim
    keeps whichever scores higher on that style's own bonus (see
    `_RANK_FIELDS`); a slot named once is kept outright.

    **`weapon` and `2h` compete against each other, not independently.**
    Without this, a guide naming both a one-handed and a two-handed option -
    `Phosani's Nightmare`'s guide lists `Trident of the swamp` (`weapon`)
    beside `Abyssal bludgeon` (`2h`) for entirely different playstyles -
    populated both, and `build_loadouts` summed a melee weapon's bonuses into
    what was meant to be a pure Magic loadout. See `_WEAPON_SLOT_GROUP`.
    """
    style = style_of(guide)
    fields = _RANK_FIELDS.get(style, ("melee_strength",))
    equipment = chunk_info.equipment
    picks: dict[str, str] = {}
    scores: dict[str, float] = {}
    # The real slot behind each *group* key, so the winner is written back
    # under the slot it actually occupies rather than the group name.
    slots: dict[str, str] = {}
    for name in guide.gear_links:
        entry = equipment.get(name)
        if not isinstance(entry, dict):
            continue
        slot = entry.get("slot")
        if not isinstance(slot, str) or not slot:
            continue
        group = _WEAPON_SLOT_GROUP if slot in ("weapon", "2h") else slot
        key = f"{style}-{group}"
        score = sum(
            float(value) if isinstance((value := entry.get(field, 0)), (int, float)) else 0.0
            for field in fields
        )
        if key not in picks or score > scores[key]:
            picks[key] = name
            scores[key] = score
            slots[key] = slot
    return {f"{style}-{slots[key]}": name for key, name in picks.items()}


def oracle_kit_inputs(guide: MmgRates) -> dict[str, bool]:
    """`{item: True}` for `assemble_kit`'s `items`, from what the guide's own
    gear and consumables name.

    Merges `gear_links` and `inputs`: `combat_boost` and the prayer-scroll
    gate in `_PRAYER_TIERS` both check `item in items`, and a guide's boost
    potions live in `Input=`, not `Item=` - `Divine ranging potion(4)` is
    exactly the spelling `codeItems.boostItems` keys on, so nothing here
    translates it.
    """
    return {name: True for name in (*guide.gear_links, *guide.inputs)}


def oracle_ttk(
    chunk_info: ChunkInfo,
    guide: MmgRates,
    target: str,
    *,
    boss: bool = True,
) -> float | None:
    """Seconds to kill `target` at `guide`'s own stated gear and levels.

    **`target` is the name to price** - `dps_bridge.best_kill`'s ordinary
    resolution runs underneath, so a scripted boss (see
    `costing/fightscripts.py`) is priced by its script here exactly as it
    would be for a real map, and an ordinary one by the plain damage race.

    Levels the guide does not state default to `1`, matching
    `build_loadouts`' own floor for an unproven skill - **not** to 99. A
    guide silent about Strength is a guide this function should price
    conservatively, not one this function should assume is maxed.
    """
    from chunksim.costing import dps_bridge as D

    D._require()
    items = oracle_kit_inputs(guide)
    empty_index = SourceIndex(items={}, objects={}, monsters={}, npcs={}, shops={}, drop_rates={})
    kit = D.assemble_kit(chunk_info, guide.skill_levels, items=items, source_index=empty_index)
    picks = gear_from_guide(chunk_info, guide)
    loadouts = D.build_loadouts(chunk_info, picks, guide.skill_levels, kit)
    if not loadouts:
        return None
    monster_index = D.load_monster_index()
    versions = D.version_index(monster_index)
    kill = D.best_kill(
        loadouts,
        target,
        D.candidate_targets(monster_index, target, versions),
        index=monster_index,
        reductions=kit.reductions,
        boss=boss,
    )
    return kill.ttk if kill is not None else None


def oracle_kph(
    chunk_info: ChunkInfo,
    guide: MmgRates,
    target: str,
    *,
    boss: bool = True,
) -> float | None:
    """`3600 / (ttk + overhead)` at the guide's own gear, matching the shape
    `guide.kph` itself is - see `oracle_ttk`."""
    from chunksim.costing import dps_bridge as D

    ttk = oracle_ttk(chunk_info, guide, target, boss=boss)
    if ttk is None or ttk <= 0:
        return None
    estimate = D.KillEstimate(
        monster=target, style="", ttk=ttk, dps=0.0, max_hit=0, accuracy=0.0, is_boss=boss
    )
    return estimate.kills_per_hour()
