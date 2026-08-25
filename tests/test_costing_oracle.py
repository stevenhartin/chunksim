"""Tests for `costing/oracle.py`'s pure gear-selection logic.

The DPS-touching functions (`oracle_ttk`/`oracle_kph`) are covered end to end
in `tests/test_costing_hydra.py::TestAgainstTheGuide`, against the real
export; what is tested here is the part that needs no `osrs_dps` call at
all - which style a guide is read as, and which of its gear resolves.
"""

from __future__ import annotations

from chunksim.costing import oracle
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.remote.wiki import MmgRates


def _equipment() -> dict[str, object]:
    return {
        "Twisted bow": {"attack_ranged": 75, "ranged_strength": 20, "slot": "2h"},
        "Toxic blowpipe": {"attack_ranged": 30, "ranged_strength": 25, "slot": "2h"},
        "Abyssal whip": {"attack_slash": 82, "melee_strength": 82, "slot": "weapon"},
        "Ranger boots": {"defence_ranged": 8, "slot": "feet"},
        # No 'slot' at all - a link that resolved to something that is not
        # equipment shaped the way `chunk_info.equipment` shapes it.
        "Rada's blessing 3 or 4": {},
    }


def _chunk_info() -> ChunkInfo:
    return ChunkInfo({"equipment": _equipment()})


class TestStyleOf:
    def test_a_ranged_guide_reads_as_ranged(self) -> None:
        guide = MmgRates(skill_levels={"Slayer": 95, "Ranged": 75})
        assert oracle.style_of(guide) == "Ranged"

    def test_a_guide_with_no_style_skill_defaults_melee(self) -> None:
        """`build_loadouts`' own bare-handed fallback, not a claim that the
        guide is a melee one - see `style_of`'s docstring."""
        guide = MmgRates(skill_levels={"Slayer": 95})
        assert oracle.style_of(guide) == "Melee"

    def test_ranged_is_checked_before_melee(self) -> None:
        guide = MmgRates(skill_levels={"Attack": 70, "Ranged": 75})
        assert oracle.style_of(guide) == "Ranged"


class TestGearFromGuide:
    def test_resolvable_links_become_picks(self) -> None:
        guide = MmgRates(
            skill_levels={"Ranged": 75},
            gear_links=("Twisted bow", "Ranger boots", "Ranged armour"),
        )
        picks = oracle.gear_from_guide(_chunk_info(), guide)
        assert picks["Ranged-2h"] == "Twisted bow"
        assert picks["Ranged-feet"] == "Ranger boots"
        assert "Ranged armour" not in picks.values()

    def test_a_link_absent_from_equipment_is_dropped(self) -> None:
        guide = MmgRates(skill_levels={"Ranged": 75}, gear_links=("Not an item",))
        assert oracle.gear_from_guide(_chunk_info(), guide) == {}

    def test_a_link_with_no_slot_is_dropped(self) -> None:
        guide = MmgRates(
            skill_levels={"Ranged": 75}, gear_links=("Rada's blessing 3 or 4",)
        )
        assert oracle.gear_from_guide(_chunk_info(), guide) == {}

    def test_a_slot_collision_keeps_the_higher_ranged_strength(self) -> None:
        """Twisted bow's 20 beats Toxic blowpipe's 25? No - the fixture is
        deliberately the other way round, so this pins that the *higher*
        value wins regardless of which item that turns out to be."""
        guide = MmgRates(
            skill_levels={"Ranged": 75},
            gear_links=("Twisted bow", "Toxic blowpipe"),
        )
        picks = oracle.gear_from_guide(_chunk_info(), guide)
        assert picks["Ranged-2h"] == "Toxic blowpipe"

    def test_every_resolved_link_is_filed_under_the_guides_one_style(self) -> None:
        """**No filtering by whether an item suits the style** - `style_of`
        picks one style for the whole guide, and everything that resolves to
        equipment is filed under it. An Abyssal whip named in a Ranged
        guide's gear list would be filed as `Ranged-weapon`, not dropped -
        its melee bonuses simply contribute nothing to a Ranged loadout's
        sum, which is `build_loadouts`' own arithmetic and not a defect this
        module works around."""
        guide = MmgRates(skill_levels={"Ranged": 75}, gear_links=("Abyssal whip",))
        picks = oracle.gear_from_guide(_chunk_info(), guide)
        assert picks == {"Ranged-weapon": "Abyssal whip"}


class TestOracleKitInputs:
    def test_gear_and_consumables_are_merged(self) -> None:
        guide = MmgRates(
            gear_links=("Twisted bow",), inputs=("Divine ranging potion(4)",)
        )
        items = oracle.oracle_kit_inputs(guide)
        assert items == {"Twisted bow": True, "Divine ranging potion(4)": True}


def _equipment_with_weapon_conflict() -> dict[str, object]:
    return {
        # A powered staff: real magic damage, but through `attack_magic`
        # alone - `magic_damage` is 0, matching how the export actually
        # represents Trident of the swamp / Sanguinesti staff.
        "Trident of the swamp": {
            "attack_magic": 25,
            "magic_damage": 0,
            "slot": "weapon",
        },
        # A melee weapon that happens to tie 0-0 with the staff above on
        # `magic_damage` alone - the field the ranking used to read.
        "Inquisitor's mace": {
            "attack_crush": 102,
            "melee_strength": 96,
            "magic_damage": 0,
            "slot": "weapon",
        },
        # A two-handed melee weapon - a *different* slot, so nothing here
        # collides with the two `weapon`-slot items above without the
        # `weapon`/`2h` grouping fix.
        "Abyssal bludgeon": {
            "attack_crush": 102,
            "melee_strength": 85,
            "magic_damage": 0,
            "slot": "2h",
        },
    }


class TestTheWeaponRankingRegression:
    """**Both bugs `costing/nightmare.py`'s own guide exposed**, pinned
    directly so a future change to `_RANK_FIELDS` or the weapon-slot
    grouping cannot reopen either silently.
    """

    def test_a_powered_staff_beats_a_tied_melee_weapon_for_magic(self) -> None:
        """`magic_damage` alone ties every real magic weapon against every
        melee one at zero; `attack_magic` is what actually tells them apart.
        `Inquisitor's mace` is named first in `gear_links`, so a tie would
        resolve to the wrong weapon by list order alone."""
        info = ChunkInfo({"equipment": _equipment_with_weapon_conflict()})
        guide = MmgRates(
            skill_levels={"Magic": 90},
            gear_links=("Inquisitor's mace", "Trident of the swamp"),
        )
        picks = oracle.gear_from_guide(info, guide)
        assert picks["Magic-weapon"] == "Trident of the swamp"

    def test_weapon_and_2h_never_both_get_worn(self) -> None:
        """A two-handed weapon replaces the shield rather than sitting beside
        a one-handed one - `build_loadouts` sums whichever entries a caller
        hands it and does not itself enforce this."""
        info = ChunkInfo({"equipment": _equipment_with_weapon_conflict()})
        guide = MmgRates(
            skill_levels={"Attack": 90, "Strength": 90},
            gear_links=("Abyssal bludgeon", "Inquisitor's mace"),
        )
        picks = oracle.gear_from_guide(info, guide)
        weapon_keys = [k for k in picks if k.endswith(("-weapon", "-2h"))]
        assert len(weapon_keys) == 1

    def test_the_higher_scoring_weapon_wins_the_shared_contest(self) -> None:
        """`Inquisitor's mace` (96 melee strength) should beat `Abyssal
        bludgeon` (85) for Melee, even though they occupy different slots."""
        info = ChunkInfo({"equipment": _equipment_with_weapon_conflict()})
        guide = MmgRates(
            skill_levels={"Attack": 90, "Strength": 90},
            gear_links=("Abyssal bludgeon", "Inquisitor's mace"),
        )
        picks = oracle.gear_from_guide(info, guide)
        assert picks == {"Melee-weapon": "Inquisitor's mace"}
