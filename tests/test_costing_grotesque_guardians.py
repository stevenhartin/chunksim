"""Grotesque Guardians' `FightScript`, its wiring into `dps_bridge`, and a
hand sanity check against the real guide - see `costing/grotesque_guardians.py`
for the citations behind each figure."""

from __future__ import annotations

from typing import Any

import pytest

from chunksim.costing import dps_bridge, grotesque_guardians as gg, oracle
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.remote.wiki import mmg_rates

pytestmark = pytest.mark.skipif(
    not dps_bridge.DPS_AVAILABLE,
    reason="osrs-dps is an optional extra; install it with `pip install -e ../osrs-dps`",
)


class TestTheScript:
    """The wiki's own published phase order and style restrictions, pinned -
    see `costing/grotesque_guardians.py` for the citations."""

    def test_the_four_phases_alternate_dawn_and_dusk(self) -> None:
        targets = [phase.target for phase in gg.SCRIPT.phases]
        assert targets == ["Dawn", "Dusk#First form", "Dawn", "Dusk#Second form"]

    def test_every_phase_is_half_of_its_own_target(self) -> None:
        assert [p.hp_share for p in gg.SCRIPT.phases] == pytest.approx([0.5, 0.5, 0.5, 0.5])

    def test_dawns_two_phases_and_dusks_two_phases_each_sum_to_a_whole_kill(self) -> None:
        """The 'several independent targets, each fully depleted' shape
        `Phase`'s own docstring names this boss as the example of - **not**
        the Hydra/Zulrah 'one shared pool' shape, even though every
        `hp_share` here happens to also be `0.5`."""
        dawn = [p for p in gg.SCRIPT.phases if p.target == "Dawn"]
        dusk = [p for p in gg.SCRIPT.phases if p.target.startswith("Dusk")]
        assert len(dawn) == 2 and len(dusk) == 2
        assert sum(p.hp_share for p in dawn) == pytest.approx(1.0)
        assert sum(p.hp_share for p in dusk) == pytest.approx(1.0)

    def test_every_target_is_a_key_the_library_knows(self) -> None:
        index = dps_bridge.load_monster_index()
        for phase in gg.SCRIPT.phases:
            assert phase.target in index, phase.target

    def test_dawn_is_never_offered_melee(self) -> None:
        """'Cannot be targeted by non-halberd melee weapons' - this project
        has no halberd-only notion, so Melee is excluded outright rather
        than approximated. See the module docstring on `Phase.styles`."""
        for phase in gg.SCRIPT.phases:
            if phase.target == "Dawn":
                assert phase.styles == frozenset({"Ranged", "Magic"})

    def test_dusk_is_offered_only_melee(self) -> None:
        """'Completely immune to magic and ranged damage.'"""
        for phase in gg.SCRIPT.phases:
            if phase.target.startswith("Dusk"):
                assert phase.styles == frozenset({"Melee"})

    def test_only_the_second_dawn_phase_carries_the_flight_transition(self) -> None:
        """Published: the outbound flight transition was removed, the
        inbound one still occurs - so only phase 3 (Dawn returning) carries
        `TRANSITION_SECONDS`."""
        phase_1, phase_2, phase_3, phase_4 = gg.SCRIPT.phases
        assert phase_1.reduced_seconds == 0.0
        assert phase_2.reduced_seconds == 0.0
        assert phase_3.reduced_seconds == gg.TRANSITION_SECONDS
        assert phase_3.reduced_dps_fraction == pytest.approx(0.0)
        assert phase_4.reduced_seconds == 0.0


def _equipment() -> dict[str, Any]:
    return {
        "Twisted bow": {
            "attack_ranged": 85,
            "ranged_strength": 65,
            "attack_speed": 5,
            "slot": "2h",
        },
        "Abyssal whip": {
            "attack_slash": 82,
            "melee_strength": 82,
            "attack_speed": 4,
            "slot": "weapon",
        },
        "Rune boots": {"defence_slash": 12, "attack_speed": 0, "slot": "feet"},
    }


def _chunk_info() -> ChunkInfo:
    return ChunkInfo({"equipment": _equipment()})


_LEVELS = {"Attack": 90, "Strength": 90, "Ranged": 90, "Magic": 80, "Hitpoints": 90}


class TestWiredIntoDpsBridge:
    """The registry interception in `dps_bridge.best_kill`, and the
    `Phase.styles` restriction that makes this boss priceable at all - an
    unrestricted search over these two undefended stat blocks (see the
    module docstring) would happily price a style that deals zero real
    damage in-game."""

    def test_the_guardians_are_registered(self) -> None:
        assert dps_bridge.SCRIPTS["Grotesque Guardians"] is gg.SCRIPT

    def _kill(self) -> "dps_bridge.KillEstimate | None":
        picks = {
            "Ranged-2h": "Twisted bow",
            "Ranged-feet": "Rune boots",
            "Melee-weapon": "Abyssal whip",
            "Melee-feet": "Rune boots",
        }
        loadouts = dps_bridge.build_loadouts(_chunk_info(), picks, _LEVELS)
        index = dps_bridge.load_monster_index()
        versions = dps_bridge.version_index(index)
        candidates = dps_bridge.candidate_targets(index, "Grotesque Guardians", versions)
        return dps_bridge.best_kill(
            loadouts, "Grotesque Guardians", candidates, index=index, boss=True
        )

    def test_a_ranged_only_loadout_cannot_kill_dusk_and_the_script_refuses(self) -> None:
        """No Melee loadout is on offer - Dawn's phases can still be priced
        with Ranged, but Dusk's `styles={"Melee"}` leaves nothing to fight
        him with, so the whole script must refuse rather than silently
        pricing half a kill."""
        picks = {"Ranged-2h": "Twisted bow", "Ranged-feet": "Rune boots"}
        loadouts = dps_bridge.build_loadouts(_chunk_info(), picks, _LEVELS)
        index = dps_bridge.load_monster_index()
        versions = dps_bridge.version_index(index)
        candidates = dps_bridge.candidate_targets(index, "Grotesque Guardians", versions)
        kill = dps_bridge.best_kill(
            loadouts, "Grotesque Guardians", candidates, index=index, boss=True
        )
        assert kill is None

    def test_a_scripted_kill_is_marked_as_one(self) -> None:
        kill = self._kill()
        assert kill is not None
        assert kill.match == "scripted"

    def test_the_full_health_of_both_guardians_is_carried(self) -> None:
        """450 each, both fully depleted - 900 total, not 450."""
        kill = self._kill()
        assert kill is not None
        assert kill.hitpoints == pytest.approx(900.0)

    def test_melee_never_wins_a_dawn_phase(self) -> None:
        """Direct check on `kills_by_style`'s own per-phase call: even with
        a strong Melee loadout on offer, Dawn's phases must never resolve to
        Melee, because `phase.styles` excludes it before the search runs."""
        picks = {
            "Ranged-2h": "Twisted bow",
            "Ranged-feet": "Rune boots",
            "Melee-weapon": "Abyssal whip",
            "Melee-feet": "Rune boots",
        }
        loadouts = dps_bridge.build_loadouts(_chunk_info(), picks, _LEVELS)
        index = dps_bridge.load_monster_index()
        target = index.get("Dawn")
        assert target is not None
        restricted = {s: l for s, l in loadouts.items() if s in {"Ranged", "Magic"}}
        styled = dps_bridge.kills_by_style(restricted, "Dawn", (("Dawn", target),), boss=True)
        assert "Melee" not in styled


class TestAgainstTheGuide:
    """Parses the real 'Killing the Grotesque Guardians' guide, but stops
    short of a `kph` ratio assertion - `oracle.py`'s gear builder produces
    one style per guide, and this fight needs two at once. Matches the
    precedent `costing/zulrah.py` already sets for the same reason.

    Uses hardcoded wikitext, matching every other guide-parsing test in this
    project: no network call here.
    """

    # A trimmed copy of https://oldschool.runescape.wiki/w/Money_making_guide/Killing_the_Grotesque_Guardians
    # (fetched under CLAUDE.md's User-Agent rule), keeping only the fields
    # this project reads.
    _GUIDE_TEXT = """
{{Mmgtable
|Activity = Killing [[Grotesque Guardians]]
|Skill =
* {{SCP|Slayer|75}}
* {{SCP|Combat|90+}}
* {{SCP|Prayer|43+}}
* ({{SCP|Prayer|70+}} and {{SCP|Defence|70+}} recommended to use [[Piety]])
|Item =
* Weapons: [[Abyssal Whip]] or better for [[Dusk]], [[Toxic Blowpipe]] for [[Dawn]]
* Special attack weapon: [[crystal halberd]], [[Saradomin godsword]] or [[dragon claws]]
* Armour: [[Slayer helmet (i)]], [[Melee equipment]] and [[Ranged equipment]]
|isperkill = y
|kph = 24
|Input1 = Divine super combat potion(4)
|Input1num = 3
}}
"""

    def _guide(self) -> Any:
        guide = mmg_rates(self._GUIDE_TEXT)
        assert guide is not None
        return guide

    def test_the_fixture_parses_the_way_the_real_page_does(self) -> None:
        guide = self._guide()
        assert guide.kph == 24.0
        assert "Abyssal Whip" in guide.gear_links
        assert "Toxic Blowpipe" in guide.gear_links

    def test_the_guide_names_no_combat_style_level_so_defaults_to_melee(self) -> None:
        """Every `{{SCP|...}}` in this guide's `Skill=` field is either not a
        combat-style skill (`Slayer`, `Combat`, `Prayer`, `Defence`) or has
        no numeric level at all - `style_of` correctly finds none of
        `Attack`/`Strength`/`Ranged`/`Magic` and falls back to `Melee`. This
        is exactly the gap `oracle.gear_from_guide`'s own docstring names: a
        single-style guess at a fight the real guide itself splits between
        Ranged (for Dawn) and Melee (for Dusk)."""
        guide = self._guide()
        assert not ({"Attack", "Strength", "Ranged", "Magic"} & guide.skill_levels.keys())
        assert oracle.style_of(guide) == "Melee"

    @pytest.mark.real_export
    def test_a_hand_built_mixed_loadout_produces_a_plausible_kph(
        self, real_export: ChunkInfo
    ) -> None:
        """**The sanity check, not the oracle.** `oracle.py` cannot build the
        guide's real hybrid loadout, so this constructs one by hand from the
        guide's own named items (`Abyssal whip` for Dusk, `Toxic blowpipe`
        for Dawn) against the real export's equipment table, and checks the
        result is the right order of magnitude next to the guide's `kph=24`
        rather than asserting a tight ratio band - matching
        `costing/zulrah.py`'s own precedent for a boss its oracle harness
        cannot represent.
        """
        picks = {"Melee-weapon": "Abyssal whip", "Ranged-2h": "Toxic blowpipe"}
        levels = {"Attack": 99, "Strength": 99, "Ranged": 99, "Magic": 99, "Hitpoints": 99}
        loadouts = dps_bridge.build_loadouts(real_export, picks, levels)
        assert "Melee" in loadouts and "Ranged" in loadouts
        index = dps_bridge.load_monster_index()
        versions = dps_bridge.version_index(index)
        candidates = dps_bridge.candidate_targets(index, "Grotesque Guardians", versions)
        kill = dps_bridge.best_kill(
            loadouts, "Grotesque Guardians", candidates, index=index, boss=True
        )
        assert kill is not None
        kph = kill.kills_per_hour()
        # Generous band: a hand-picked two-item loadout with no armour,
        # potions or prayer against maxed-level, well-equipped guide advice
        # is not meant to land close - just the right order of magnitude.
        assert 5.0 < kph < 60.0
