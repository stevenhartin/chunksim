"""Phosani's Nightmare's `FightScript`, its wiring into `dps_bridge`, and the
oracle comparison against its own money-making guide.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from chunksim.costing import dps_bridge, nightmare, oracle
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.remote.wiki import mmg_rates

pytestmark = pytest.mark.skipif(
    not dps_bridge.DPS_AVAILABLE,
    reason="osrs-dps is an optional extra; install it with `pip install -e ../osrs-dps`",
)


class TestTheScript:
    """The published counts, pinned - see `costing/nightmare.py` for the
    citations behind each figure."""

    def test_one_phase_against_the_full_boss(self) -> None:
        """Not split into the page's four sub-phases - see the module
        docstring on why this project has no evidence for how the totem
        bursts divide across her health."""
        assert len(nightmare.SCRIPT.phases) == 1
        phase = nightmare.SCRIPT.phases[0]
        assert phase.target == "Phosani's Nightmare"
        assert phase.hp_share == pytest.approx(1.0)

    def test_the_target_is_a_key_the_library_knows(self) -> None:
        index = dps_bridge.load_monster_index()
        assert nightmare.SCRIPT.phases[0].target in index

    def test_downtime_is_zero_rate_not_reduced_rate(self) -> None:
        """Unlike the Hydra's vent, nothing here lands *any* damage on her
        during the window - totems and sleepwalkers are a different target
        entirely."""
        phase = nightmare.SCRIPT.phases[0]
        assert phase.reduced_dps_fraction == 0.0
        assert phase.reduced_seconds == pytest.approx(nightmare.DOWNTIME_SECONDS)

    def test_the_sleepwalker_counts_match_the_wiki(self) -> None:
        """2, 3 and 4 at the end of phases 1-3, capping at four - the
        desperation phase's own sleepwalkers are excluded, since the page
        says to ignore them."""
        assert nightmare.SLEEPWALKERS_BY_PHASE == (2, 3, 4)

    def test_downtime_is_three_totem_phases_and_nine_sleepwalkers(self) -> None:
        expected = nightmare.TOTEM_SECONDS_PER_PHASE * 3 + nightmare.SLEEPWALKER_SECONDS_PER_KILL * 9
        assert nightmare.DOWNTIME_SECONDS == pytest.approx(expected)


def _equipment() -> dict[str, Any]:
    return {
        "Abyssal whip": {
            "attack_slash": 82,
            "melee_strength": 82,
            "attack_speed": 4,
            "slot": "weapon",
        },
        "Rune platebody": {"defence_slash": 82, "attack_speed": 0, "slot": "body"},
    }


def _chunk_info() -> ChunkInfo:
    return ChunkInfo({"equipment": _equipment()})


_LEVELS = {"Attack": 90, "Strength": 90, "Defence": 90, "Hitpoints": 90}


class TestWiredIntoDpsBridge:
    """The registry interception in `dps_bridge.best_kill` - the same
    machinery `TestWiredIntoDpsBridge` in `tests/test_costing_hydra.py`
    exercises, checked here because a boss whose one phase names *itself* as
    the target is a real hazard the Hydra's four distinct keys never raised -
    see `dps_bridge._scripted_kill`'s docstring on why it calls
    `kills_by_style` and never `best_kill`.
    """

    def test_the_nightmare_is_registered(self) -> None:
        assert dps_bridge.SCRIPTS["Phosani's Nightmare"] is nightmare.SCRIPT

    def _kill(self) -> "dps_bridge.KillEstimate | None":
        picks = {"Melee-weapon": "Abyssal whip", "Melee-body": "Rune platebody"}
        loadouts = dps_bridge.build_loadouts(_chunk_info(), picks, _LEVELS)
        index = dps_bridge.load_monster_index()
        versions = dps_bridge.version_index(index)
        candidates = dps_bridge.candidate_targets(index, "Phosani's Nightmare", versions)
        return dps_bridge.best_kill(loadouts, "Phosani's Nightmare", candidates, boss=True)

    def test_a_same_named_phase_does_not_recurse_forever(self) -> None:
        """The regression this class exists for: `Phase.target ==
        script.name` here, unlike every Hydra phase."""
        kill = self._kill()
        assert kill is not None

    def test_a_scripted_kill_is_marked_as_one(self) -> None:
        kill = self._kill()
        assert kill is not None
        assert kill.match == "scripted"

    def test_the_total_time_is_the_raw_fight_plus_the_downtime(self) -> None:
        """Pins the arithmetic: with one phase and zero-rate downtime,
        `_phase_seconds` reduces to `raw_ttk + reduced_seconds` exactly."""
        picks = {"Melee-weapon": "Abyssal whip", "Melee-body": "Rune platebody"}
        loadouts = dps_bridge.build_loadouts(_chunk_info(), picks, _LEVELS)
        index = dps_bridge.load_monster_index()
        versions = dps_bridge.version_index(index)
        candidates = dps_bridge.candidate_targets(index, "Phosani's Nightmare", versions)
        styled = dps_bridge.kills_by_style(loadouts, "Phosani's Nightmare", candidates, boss=True)
        raw = min(styled.values(), key=lambda k: k.ttk)

        kill = self._kill()
        assert kill is not None
        assert kill.ttk == pytest.approx(raw.ttk + nightmare.DOWNTIME_SECONDS, rel=1e-9)

    def test_the_full_boss_health_is_carried(self) -> None:
        kill = self._kill()
        assert kill is not None
        assert kill.hitpoints == pytest.approx(3200.0)


class TestAgainstTheGuide:
    """**The oracle.** Compares this project's simulator, at the guide's own
    stated gear and levels, against the guide's own published `kph`.

    Single-boss only, and offline - see `tests/test_costing_hydra.py`'s
    identical class docstring for both points; nothing here repeats that
    reasoning.

    **The one thing this guide adds beyond the Hydra's**: it names two
    strategies - a melee one (`Scythe of Vitur`/`Inquisitor's mace`, "on
    crush") and a magic one (`Trident of the swamp`/`Sanguinesti staff`) -
    under one `kph`, and its `Skill=` field states a level for only one of
    them: `{{SCP|Attack}}`, `{{SCP|Strength}}` and `{{SCP|Defence}}` all
    carry no number at all, where `{{SCP|Magic|90+}}` does.
    `oracle.style_of` therefore reads this guide as a Magic one - not
    because the guide is magic-first, but because Magic is the only style it
    can find a level for. That is a real, stated gap in guide-prose parsing,
    not a bug: nothing publishes which of two named strategies a guide's
    `kph` describes, and this project does not guess. The melee interpretation
    is what is tested below, with the level-less skills given explicitly,
    because it is the one this project could verify makes sense of the
    guide's own emphasis - "on crush", `Ferocious gloves` (a melee
    unlock) - and gives a result in the same band the Hydra's oracle did; the
    magic interpretation was tried too and came out 15-30x slow, entirely
    explained by `Tumeken's shadow` - the one weapon the guide calls out as
    making Magic viable against this boss's very high magic defence - being
    absent from this project's own equipment reference altogether.
    """

    # A trimmed copy of https://oldschool.runescape.wiki/w/Money_making_guide/Killing_Phosani%27s_Nightmare
    # (fetched under CLAUDE.md's User-Agent rule). Kept: Activity, Skill,
    # Item, Input, kph. Output rows (drop odds) are unrelated and dropped.
    _GUIDE_TEXT = """
{{Mmgtable
|Activity = Killing [[Phosani's Nightmare]]
|Skill =
* {{SCP|Attack}}, {{SCP|Strength}}, {{SCP|Defence}}, {{SCP|Hitpoints|90+}}, {{SCP|Magic|90+}}
* {{SCP|Prayer|70+}} recommended
|Item =
* Melee: [[Abyssal bludgeon]], [[Scythe of Vitur]] (on crush), [[Soulreaper Axe]] (on crush), [[Inquisitor's mace]] and [[Avernic defender]]<br/>[[Highest bonuses#Strength|Max strength bonus armour]]
* Mage: [[Trident of the swamp]], [[Sanguinesti staff]], [[Eye of Ayak]], or [[Tumekens shadow]] with a [[Saturated heart]]<br/>[[Occult necklace]], [[God capes#Imbuing|Imbued god cape]], [[Ancestral robes]]
* Food & Potions: [[Divine super combat potion]]s, [[Super restore]]s, [[Anglerfish]] or equivalent
|isperkill = y
|kph = 9.5
|Input1 = Divine super combat potion(4)
|Input1num = 1/2.667
|Input2 = Sanfew serum(4)
|Input2num = 1.25
}}
"""

    def _guide(self) -> Any:
        guide = mmg_rates(self._GUIDE_TEXT)
        assert guide is not None
        return guide

    def test_the_fixture_parses_the_way_the_real_page_does(self) -> None:
        guide = self._guide()
        assert guide.kph == 9.5
        # Attack/Strength/Defence carry no {{SCP}} level - see this class's
        # own docstring.
        assert guide.skill_levels == {"Hitpoints": 90, "Magic": 90, "Prayer": 70}
        assert "Trident of the swamp" in guide.gear_links
        assert "Inquisitor's mace" in guide.gear_links

    def test_an_unmodified_read_picks_magic_for_a_stated_reason(self) -> None:
        assert oracle.style_of(self._guide()) == "Magic"

    @pytest.mark.real_export
    def test_weapon_and_2h_do_not_both_get_worn_at_once(
        self, real_export: ChunkInfo
    ) -> None:
        """**A real defect this guide's own prose exposed**: `Abyssal
        bludgeon` (`2h`) and `Inquisitor's mace` (`weapon`) both resolve as
        equipment, and before `oracle.gear_from_guide` treated the two slots
        as one contest, both were worn *at once* - a melee weapon's bonuses
        silently summed into what was meant to be a pure loadout."""
        guide = replace(self._guide(), skill_levels={"Attack": 99, "Strength": 99, "Defence": 99})
        picks = oracle.gear_from_guide(real_export, guide)
        weapon_slots = [key for key in picks if key.endswith(("-weapon", "-2h"))]
        assert len(weapon_slots) == 1

    @pytest.mark.real_export
    def test_the_simulator_reproduces_the_guides_kph_at_the_melee_reading(
        self, real_export: ChunkInfo
    ) -> None:
        """See this class's docstring for why melee, and why not closer to
        1.0: `Scythe of Vitur` is not in this project's equipment reference,
        leaving `Inquisitor's mace` as the resolved weapon, and neither
        special-attack weapons nor full armour are named specifically enough
        in the guide's prose for `gear_from_guide` to fill them - the same
        shape of gap `test_costing_hydra.py` measures for its own guide.
        """
        guide = replace(
            self._guide(),
            skill_levels={"Attack": 99, "Strength": 99, "Defence": 99, "Hitpoints": 90, "Prayer": 70},
        )
        assert oracle.style_of(guide) == "Melee"
        kph = oracle.oracle_kph(real_export, guide, "Phosani's Nightmare")
        assert kph is not None
        ratio = kph / guide.kph
        assert 0.30 < ratio < 0.65, (
            f"ratio {ratio:.2f} - see this test's docstring for the band's origin"
        )
