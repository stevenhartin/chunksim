"""Phantom Muspah's damage-chunked alternation and shield phase - see
`costing/phantom_muspah.py` for the citations behind each figure."""

from __future__ import annotations

from typing import Any

import pytest

from chunksim.costing import dps_bridge, oracle, phantom_muspah
from chunksim.costing.dps_bridge import load_monster_index
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.remote.wiki import mmg_rates

pytestmark = pytest.mark.skipif(
    not dps_bridge.DPS_AVAILABLE,
    reason="osrs-dps is an optional extra; install it with `pip install -e ../osrs-dps`",
)


class TestTheScript:
    def test_the_three_main_pool_phases_sum_to_one(self) -> None:
        """Ranged, Melee and the post-shield finish all target his own
        850-hitpoint pool - the shield's separate 75 is not part of this
        sum, checked on its own below."""
        main_pool = [
            p.hp_share for p in phantom_muspah.SCRIPT.phases if p.target != "Phantom Muspah#Shielded"
        ]
        assert sum(main_pool) == pytest.approx(1.0)

    def test_the_order_is_ranged_melee_shield_ranged(self) -> None:
        targets = [p.target for p in phantom_muspah.SCRIPT.phases]
        assert targets == [
            "Phantom Muspah#Ranged",
            "Phantom Muspah#Melee",
            "Phantom Muspah#Shielded",
            "Phantom Muspah#Post-shield",
        ]

    def test_every_target_is_a_key_the_library_knows(self) -> None:
        idx = load_monster_index()
        for phase in phantom_muspah.SCRIPT.phases:
            assert phase.target in idx, phase.target

    def test_the_hundred_eighty_split_matches_the_published_chunks(self) -> None:
        ranged, melee, shield, post = phantom_muspah.SCRIPT.phases
        before_shield = phantom_muspah.BEFORE_SHIELD_HITPOINTS
        assert ranged.hp_share == pytest.approx(
            before_shield * (100.0 / 180.0) / phantom_muspah.TOTAL_HITPOINTS
        )
        assert melee.hp_share == pytest.approx(
            before_shield * (80.0 / 180.0) / phantom_muspah.TOTAL_HITPOINTS
        )

    def test_the_shield_is_a_separate_pool_not_a_slice_of_his_health(self) -> None:
        """The user's own framing: 'a shield which won't appear as actual
        damage on the boss.'"""
        shield = phantom_muspah.SCRIPT.phases[2]
        assert shield.target == "Phantom Muspah#Shielded"
        assert shield.hp_share == pytest.approx(1.0)
        idx = load_monster_index()
        target = idx.get("Phantom Muspah#Shielded")
        assert target is not None
        assert target.hitpoints == pytest.approx(75.0)
        assert target.hitpoints != phantom_muspah.TOTAL_HITPOINTS

    def test_the_shield_trigger_threshold_is_published(self) -> None:
        assert phantom_muspah.SHIELD_TRIGGER_HITPOINTS == pytest.approx(127.0)

    def test_the_defences_match_the_published_weaknesses(self) -> None:
        idx = load_monster_index()
        ranged = idx.get("Phantom Muspah#Ranged")
        melee = idx.get("Phantom Muspah#Melee")
        assert ranged is not None and melee is not None
        assert ranged.bonuses.defence_ranged < ranged.bonuses.defence_magic
        assert melee.bonuses.defence_magic < melee.bonuses.defence_ranged


def _equipment() -> dict[str, Any]:
    return {
        "Twisted bow": {
            "attack_ranged": 85, "ranged_strength": 65, "attack_speed": 5, "slot": "weapon",
        },
        "Tumeken's shadow": {
            "attack_magic": 70, "magic_damage": 40, "attack_speed": 4, "slot": "2h",
        },
        "Rune boots": {"defence_slash": 12, "attack_speed": 0, "slot": "feet"},
    }


def _chunk_info() -> ChunkInfo:
    return ChunkInfo({"equipment": _equipment()})


_LEVELS = {"Attack": 90, "Strength": 90, "Ranged": 90, "Magic": 90, "Hitpoints": 90}


class TestWiredIntoDpsBridge:
    def test_registered(self) -> None:
        assert dps_bridge.SCRIPTS[phantom_muspah.PHANTOM_MUSPAH] is phantom_muspah.SCRIPT

    def test_a_scripted_kill_carries_the_published_total(self) -> None:
        picks = {"Ranged-weapon": "Twisted bow", "Magic-2h": "Tumeken's shadow"}
        loadouts = dps_bridge.build_loadouts(_chunk_info(), picks, _LEVELS)
        idx = load_monster_index()
        versions = dps_bridge.version_index(idx)
        candidates = dps_bridge.candidate_targets(idx, phantom_muspah.PHANTOM_MUSPAH, versions)
        kill = dps_bridge.best_kill(
            loadouts, phantom_muspah.PHANTOM_MUSPAH, candidates, index=idx, boss=True
        )
        assert kill is not None
        assert kill.match == "scripted"
        # Main pool (850) plus the separate 75-point shield.
        assert kill.hitpoints == pytest.approx(925.0)


class TestAgainstTheGuide:
    """Parses the real 'Killing Phantom Muspah (Twisted bow)' guide -
    hardcoded wikitext, no network call."""

    _GUIDE_TEXT = """
{{Mmgtable
|Activity = Killing [[Phantom Muspah]]
|Skill =
* {{SCP|Ranged|85+}}
* {{SCP|Magic|85+}}
* {{SCP|Prayer|70+}}
|Item =
* [[Twisted bow]]
* [[Tumeken's shadow]]
|Intensity = Medium
|isperkill = y
|kph = 25
}}
"""

    def _guide(self) -> Any:
        guide = mmg_rates(self._GUIDE_TEXT)
        assert guide is not None
        return guide

    def test_the_fixture_parses_the_way_the_real_page_does(self) -> None:
        assert self._guide().kph == 25.0

    @pytest.mark.real_export
    def test_the_simulator_produces_a_plausible_ratio_against_the_guide(
        self, real_export: ChunkInfo
    ) -> None:
        guide = self._guide()
        kph = oracle.oracle_kph(real_export, guide, phantom_muspah.PHANTOM_MUSPAH)
        assert kph is not None
        ratio = kph / guide.kph
        # Wide band: the guide switches gear mid-guide prose ("using magic
        # during the melee phases") which `oracle.py`'s single-style
        # builder cannot represent, the same gap `costing/zulrah.py`'s own
        # docstring names.
        assert 0.1 < ratio < 3.0, f"ratio {ratio:.2f}"
