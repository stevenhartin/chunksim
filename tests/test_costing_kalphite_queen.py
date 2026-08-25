"""The Kalphite Queen's two forms - see `costing/kalphite_queen.py` for the
citations behind each figure."""

from __future__ import annotations

from typing import Any

import pytest

from chunksim.costing import dps_bridge, kalphite_queen, oracle
from chunksim.costing.dps_bridge import load_monster_index
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.remote.wiki import mmg_rates

pytestmark = pytest.mark.skipif(
    not dps_bridge.DPS_AVAILABLE,
    reason="osrs-dps is an optional extra; install it with `pip install -e ../osrs-dps`",
)


class TestTheScript:
    def test_two_phases_both_full_health(self) -> None:
        assert len(kalphite_queen.SCRIPT.phases) == 2
        for phase in kalphite_queen.SCRIPT.phases:
            assert phase.hp_share == pytest.approx(1.0)

    def test_the_order_is_crawling_then_airborne(self) -> None:
        targets = [p.target for p in kalphite_queen.SCRIPT.phases]
        assert targets == ["Kalphite Queen#Crawling", "Kalphite Queen#Airborne"]

    def test_every_target_is_a_key_the_library_knows(self) -> None:
        idx = load_monster_index()
        for phase in kalphite_queen.SCRIPT.phases:
            assert phase.target in idx, phase.target

    def test_only_the_airborne_phase_carries_the_transition(self) -> None:
        crawling, airborne = kalphite_queen.SCRIPT.phases
        assert crawling.idle_seconds == 0.0
        assert airborne.idle_seconds == pytest.approx(kalphite_queen.TRANSITION_SECONDS)

    def test_the_transition_is_the_published_twelve_seconds(self) -> None:
        assert kalphite_queen.TRANSITION_SECONDS == pytest.approx(12.0)

    def test_the_defences_match_the_published_weaknesses(self) -> None:
        idx = load_monster_index()
        crawling = idx.get("Kalphite Queen#Crawling")
        airborne = idx.get("Kalphite Queen#Airborne")
        assert crawling is not None and airborne is not None
        assert crawling.bonuses.defence_crush < crawling.bonuses.defence_stab
        assert airborne.bonuses.defence_magic < airborne.bonuses.defence_stab


def _equipment() -> dict[str, Any]:
    return {
        "Abyssal bludgeon": {
            "attack_crush": 102, "melee_strength": 85, "attack_speed": 5, "slot": "2h",
        },
        "Twisted bow": {
            "attack_ranged": 85, "ranged_strength": 65, "attack_speed": 5, "slot": "weapon",
        },
        "Rune boots": {"defence_slash": 12, "attack_speed": 0, "slot": "feet"},
    }


def _chunk_info() -> ChunkInfo:
    return ChunkInfo({"equipment": _equipment()})


_LEVELS = {"Attack": 90, "Strength": 90, "Ranged": 90, "Magic": 80, "Hitpoints": 90}


class TestWiredIntoDpsBridge:
    def test_registered(self) -> None:
        assert dps_bridge.SCRIPTS[kalphite_queen.KALPHITE_QUEEN] is kalphite_queen.SCRIPT

    def test_a_scripted_kill_carries_both_forms_health(self) -> None:
        picks = {"Crush-2h": "Abyssal bludgeon", "Ranged-weapon": "Twisted bow"}
        loadouts = dps_bridge.build_loadouts(_chunk_info(), picks, _LEVELS)
        idx = load_monster_index()
        versions = dps_bridge.version_index(idx)
        candidates = dps_bridge.candidate_targets(idx, kalphite_queen.KALPHITE_QUEEN, versions)
        kill = dps_bridge.best_kill(
            loadouts, kalphite_queen.KALPHITE_QUEEN, candidates, index=idx, boss=True
        )
        assert kill is not None
        assert kill.match == "scripted"
        assert kill.hitpoints == pytest.approx(510.0)


class TestAgainstTheGuide:
    """Parses the real 'Killing the Kalphite Queen' guide - hardcoded
    wikitext, no network call, matching every other guide-parsing test in
    this project."""

    _GUIDE_TEXT = """
{{Mmgtable
|Activity = Killing the [[Kalphite Queen]]
|Skill =
* {{SCP|Attack|75+}}, {{SCP|Strength|75+}}, {{SCP|Ranged|75+}}, {{SCP|Magic|75+}}, {{SCP|Prayer|43+}}
|Item =
* [[Twisted bow]] or [[Toxic blowpipe]]
* [[Abyssal bludgeon]] or [[Dragon warhammer]]
|Intensity = Medium
|isperkill = y
|kph = 22
}}
"""

    def _guide(self) -> Any:
        guide = mmg_rates(self._GUIDE_TEXT)
        assert guide is not None
        return guide

    def test_the_fixture_parses_the_way_the_real_page_does(self) -> None:
        guide = self._guide()
        assert guide.kph == 22.0

    @pytest.mark.real_export
    def test_the_simulator_produces_a_plausible_ratio_against_the_guide(
        self, real_export: ChunkInfo
    ) -> None:
        guide = self._guide()
        kph = oracle.oracle_kph(real_export, guide, kalphite_queen.KALPHITE_QUEEN)
        assert kph is not None
        ratio = kph / guide.kph
        # Wide band: the guide's `Item=` field names two weapon choices in
        # prose rather than a full loadout, matching the same gap
        # `costing/hydra.py`'s own oracle test measures and documents.
        assert 0.1 < ratio < 3.0, f"ratio {ratio:.2f}"
