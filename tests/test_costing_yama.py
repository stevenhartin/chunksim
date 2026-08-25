"""Yama's three-target encounter - see `costing/yama.py` for the citations
behind each figure."""

from __future__ import annotations

from typing import Any

import pytest

from chunksim.costing import dps_bridge, yama
from chunksim.costing.dps_bridge import load_monster_index
from chunksim.model.chunkinfo import ChunkInfo

pytestmark = pytest.mark.skipif(
    not dps_bridge.DPS_AVAILABLE,
    reason="osrs-dps is an optional extra; install it with `pip install -e ../osrs-dps`",
)


class TestTheScript:
    def test_the_two_yama_phases_sum_to_her_whole_bar(self) -> None:
        """`2/3 + 1/3 = 1.0` against `Yama#Normal`/`Yama#Phase 3`'s shared
        `hitpoints=2500` - the published 66.6%/33.3% thresholds, as exact
        thirds rather than the page's own rounding."""
        idx = load_monster_index()
        yama_phases = [p for p in yama.SCRIPT.phases if p.target.startswith("Yama#")]
        assert len(yama_phases) == 2
        total = sum(p.hp_share for p in yama_phases)
        assert total == pytest.approx(1.0)
        for phase in yama_phases:
            target = idx.get(phase.target)
            assert target is not None
            assert target.hitpoints == pytest.approx(2500.0)

    def test_the_first_phase_is_two_thirds(self) -> None:
        first = yama.SCRIPT.phases[0]
        assert first.target == "Yama#Normal"
        assert first.hp_share == pytest.approx(2.0 / 3.0)

    def test_the_final_phase_is_one_third(self) -> None:
        last = yama.SCRIPT.phases[-1]
        assert last.target == "Yama#Phase 3"
        assert last.hp_share == pytest.approx(1.0 / 3.0)

    def test_the_judge_is_fought_twice_at_the_bare_key(self) -> None:
        """Not `Judge of Yama (A Kingdom Divided)` - a different, quest-only
        encounter the library also carries."""
        judge = [p for p in yama.SCRIPT.phases if "Judge" in p.target]
        assert len(judge) == 1
        assert judge[0].target == "Judge of Yama"
        assert judge[0].hp_share == pytest.approx(2.0)

    def test_every_target_is_a_key_the_library_knows(self) -> None:
        idx = load_monster_index()
        for phase in yama.SCRIPT.phases:
            assert phase.target in idx, phase.target

    def test_the_whole_encounter_sums_hitpoints_correctly(self) -> None:
        """`2500` (her own bar, sliced) plus `400 x 2` (the Judge, twice) -
        `3300` total damage one kill needs."""
        idx = load_monster_index()
        total = 0.0
        for phase in yama.SCRIPT.phases:
            target = idx.get(phase.target)
            assert target is not None
            total += target.hitpoints * phase.hp_share
        assert total == pytest.approx(3300.0)


def _equipment() -> dict[str, Any]:
    return {
        "Abyssal whip": {
            "attack_slash": 82, "melee_strength": 82, "attack_speed": 4, "slot": "weapon",
        },
        "Rune boots": {"defence_slash": 12, "attack_speed": 0, "slot": "feet"},
    }


def _chunk_info() -> ChunkInfo:
    return ChunkInfo({"equipment": _equipment()})


_LEVELS = {"Attack": 90, "Strength": 90, "Hitpoints": 90}


class TestWiredIntoDpsBridge:
    def test_registered(self) -> None:
        assert dps_bridge.SCRIPTS[yama.YAMA] is yama.SCRIPT

    def test_a_scripted_kill_carries_the_full_encounter(self) -> None:
        picks = {"Melee-weapon": "Abyssal whip", "Melee-feet": "Rune boots"}
        loadouts = dps_bridge.build_loadouts(_chunk_info(), picks, _LEVELS)
        idx = load_monster_index()
        versions = dps_bridge.version_index(idx)
        candidates = dps_bridge.candidate_targets(idx, yama.YAMA, versions)
        kill = dps_bridge.best_kill(loadouts, yama.YAMA, candidates, index=idx, boss=True)
        assert kill is not None
        assert kill.match == "scripted"
        assert kill.hitpoints == pytest.approx(3300.0)

    def test_a_missing_target_refuses_the_whole_script(self) -> None:
        picks = {"Melee-weapon": "Abyssal whip"}
        loadouts = dps_bridge.build_loadouts(_chunk_info(), picks, _LEVELS)
        idx = load_monster_index()
        partial = [
            (k, t)
            for k, t in ((n, idx.get(n)) for n in ("Yama#Normal", "Yama#Phase 3"))
            if t is not None
        ]
        kill = dps_bridge.best_kill(loadouts, yama.YAMA, partial, boss=True)
        assert kill is None
