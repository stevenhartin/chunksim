"""The Hueycoatl's four-target encounter - see `costing/hueycoatl.py` for
the citations behind each figure."""

from __future__ import annotations

from typing import Any

import pytest

from chunksim.costing import dps_bridge, hueycoatl
from chunksim.costing.dps_bridge import load_monster_index
from chunksim.model.chunkinfo import ChunkInfo

pytestmark = pytest.mark.skipif(
    not dps_bridge.DPS_AVAILABLE,
    reason="osrs-dps is an optional extra; install it with `pip install -e ../osrs-dps`",
)


class TestTheScript:
    def test_the_published_total_is_four_thousand_fifty(self) -> None:
        """`5 x 250 + 2,500 + 300 = 4,050` - `[[The Hueycoatl/Strategies]]`'s
        own stated total, recomputed independently here from each phase's
        own `hp_share x target hitpoints`."""
        idx = load_monster_index()
        total = 0.0
        for phase in hueycoatl.SCRIPT.phases:
            target = idx.get(phase.target)
            assert target is not None
            total += target.hitpoints * phase.hp_share
        assert total == pytest.approx(4050.0)

    def test_the_body_phase_is_five_segments(self) -> None:
        body = hueycoatl.SCRIPT.phases[0]
        assert body.target == "The Hueycoatl#Body"
        assert body.hp_share == pytest.approx(5.0)

    def test_the_head_splits_exactly_in_half(self) -> None:
        head_phases = [p for p in hueycoatl.SCRIPT.phases if p.target == "The Hueycoatl#Normal"]
        assert len(head_phases) == 2
        for phase in head_phases:
            assert phase.hp_share == pytest.approx(0.5)

    def test_the_tail_is_a_separate_pool(self) -> None:
        tail = [p for p in hueycoatl.SCRIPT.phases if p.target == "The Hueycoatl#Tail"]
        assert len(tail) == 1
        assert tail[0].hp_share == pytest.approx(1.0)

    def test_every_target_is_a_key_the_library_knows(self) -> None:
        idx = load_monster_index()
        for phase in hueycoatl.SCRIPT.phases:
            assert phase.target in idx, phase.target

    def test_the_respawn_wait_is_on_the_body_phase(self) -> None:
        body = hueycoatl.SCRIPT.phases[0]
        assert body.idle_seconds == pytest.approx(hueycoatl.RESPAWN_SECONDS)
        assert hueycoatl.RESPAWN_SECONDS == pytest.approx(30.0)


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
        assert dps_bridge.SCRIPTS[hueycoatl.HUEYCOATL] is hueycoatl.SCRIPT

    def test_a_scripted_kill_carries_the_full_encounter(self) -> None:
        picks = {"Melee-weapon": "Abyssal whip", "Melee-feet": "Rune boots"}
        loadouts = dps_bridge.build_loadouts(_chunk_info(), picks, _LEVELS)
        idx = load_monster_index()
        versions = dps_bridge.version_index(idx)
        candidates = dps_bridge.candidate_targets(idx, hueycoatl.HUEYCOATL, versions)
        kill = dps_bridge.best_kill(loadouts, hueycoatl.HUEYCOATL, candidates, index=idx, boss=True)
        assert kill is not None
        assert kill.match == "scripted"
        assert kill.hitpoints == pytest.approx(4050.0)

    def test_a_missing_target_refuses_the_whole_script(self) -> None:
        picks = {"Melee-weapon": "Abyssal whip"}
        loadouts = dps_bridge.build_loadouts(_chunk_info(), picks, _LEVELS)
        idx = load_monster_index()
        partial = [
            (k, t)
            for k, t in ((n, idx.get(n)) for n in ("The Hueycoatl#Body", "The Hueycoatl#Normal"))
            if t is not None
        ]
        kill = dps_bridge.best_kill(loadouts, hueycoatl.HUEYCOATL, partial, boss=True)
        assert kill is None
