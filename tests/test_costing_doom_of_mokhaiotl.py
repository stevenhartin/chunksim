"""Doom of Mokhaiotl's eight-level climb - see
`costing/doom_of_mokhaiotl.py` for the citations behind each figure."""

from __future__ import annotations

from typing import Any

import pytest

from chunksim.costing import doom_of_mokhaiotl, dps_bridge
from chunksim.costing.dps_bridge import load_monster_index
from chunksim.model.chunkinfo import ChunkInfo

pytestmark = pytest.mark.skipif(
    not dps_bridge.DPS_AVAILABLE,
    reason="osrs-dps is an optional extra; install it with `pip install -e ../osrs-dps`",
)

#: The library's own per-level hitpoints, quoted from the wiki's own table
#: - see the module docstring.
_DELVE_HITPOINTS = (525.0, 550.0, 575.0, 600.0, 625.0, 650.0, 650.0, 675.0)


class TestTheScript:
    def test_eight_phases_one_per_delve_level(self) -> None:
        assert len(doom_of_mokhaiotl.SCRIPT.phases) == 8
        for level, phase in enumerate(doom_of_mokhaiotl.SCRIPT.phases, start=1):
            assert phase.target == f"Doom of Mokhaiotl#Delve {level}"
            assert phase.hp_share == pytest.approx(1.0)

    def test_every_target_is_a_key_the_library_knows_at_the_published_hitpoints(self) -> None:
        idx = load_monster_index()
        for phase, expected in zip(doom_of_mokhaiotl.SCRIPT.phases, _DELVE_HITPOINTS):
            target = idx.get(phase.target)
            assert target is not None, phase.target
            assert target.hitpoints == pytest.approx(expected)

    def test_the_climb_totals_the_published_per_level_hitpoints(self) -> None:
        idx = load_monster_index()
        total = 0.0
        for phase in doom_of_mokhaiotl.SCRIPT.phases:
            target = idx.get(phase.target)
            assert target is not None
            total += target.hitpoints * phase.hp_share
        assert total == pytest.approx(sum(_DELVE_HITPOINTS))

    def test_every_level_carries_the_guessed_mechanic_downtime(self) -> None:
        for phase in doom_of_mokhaiotl.SCRIPT.phases:
            assert phase.idle_seconds == pytest.approx(
                doom_of_mokhaiotl.MECHANIC_SECONDS_PER_DELVE
            )


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
        assert dps_bridge.SCRIPTS[doom_of_mokhaiotl.DOOM_OF_MOKHAIOTL] is doom_of_mokhaiotl.SCRIPT

    def test_a_scripted_kill_carries_the_full_climb(self) -> None:
        picks = {"Melee-weapon": "Abyssal whip", "Melee-feet": "Rune boots"}
        loadouts = dps_bridge.build_loadouts(_chunk_info(), picks, _LEVELS)
        idx = load_monster_index()
        versions = dps_bridge.version_index(idx)
        candidates = dps_bridge.candidate_targets(
            idx, doom_of_mokhaiotl.DOOM_OF_MOKHAIOTL, versions
        )
        kill = dps_bridge.best_kill(
            loadouts, doom_of_mokhaiotl.DOOM_OF_MOKHAIOTL, candidates, index=idx, boss=True
        )
        assert kill is not None
        assert kill.match == "scripted"
        assert kill.hitpoints == pytest.approx(sum(_DELVE_HITPOINTS))

    def test_a_missing_target_refuses_the_whole_script(self) -> None:
        picks = {"Melee-weapon": "Abyssal whip"}
        loadouts = dps_bridge.build_loadouts(_chunk_info(), picks, _LEVELS)
        idx = load_monster_index()
        partial = [
            (k, t)
            for k, t in (
                (n, idx.get(n))
                for n in ("Doom of Mokhaiotl#Delve 1", "Doom of Mokhaiotl#Delve 2")
            )
            if t is not None
        ]
        kill = dps_bridge.best_kill(
            loadouts, doom_of_mokhaiotl.DOOM_OF_MOKHAIOTL, partial, boss=True
        )
        assert kill is None
