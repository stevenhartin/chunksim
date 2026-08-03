"""Tests for the shared sections -> sources -> challenges pipeline."""

from __future__ import annotations

from typing import Any

from fray_claude.chunkinfo import ChunkInfo
from fray_claude.pipeline import MapState, derive, load_map_state


def _chunk_info(**data: Any) -> ChunkInfo:
    return ChunkInfo(data)


def _state(**overrides: Any) -> MapState:
    defaults: dict[str, Any] = {
        "chunk_info": _chunk_info(),
        "rules": {},
        "settings": {},
        "manual_sections": {},
        "manual_monsters": {},
        "manual_equipment": {},
        "backlogged_sources": {},
        "max_skill": {},
        "passive_skill": {},
    }
    defaults.update(overrides)
    return MapState(**defaults)


def test_derive_runs_sections_sources_and_challenges_together() -> None:
    info = _chunk_info(
        chunks={"100": {"Monster": {"Goblin": True}}},
        drops={"Goblin": {"Bones": {"1": "Always"}}},
        challenges={"Nonskill": {"Use bones": {"Items": ["Bones"]}}},
    )

    result = derive(_state(chunk_info=info), {"100": True})

    assert result.source_index.monsters == {"Goblin": {"100": True}}
    assert result.challenges.valid == {"Nonskill": {"Use bones": True}}
    assert result.reachable_sections == {}


def test_derive_tolerates_no_unlocked_chunks() -> None:
    result = derive(_state(), {})

    assert result.reachable_sections == {}
    assert result.source_index.items == {}
    assert result.challenges.valid == {}


def test_load_map_state_decodes_a_raw_payload() -> None:
    payload = {
        "chunks": {"unlocked": {"100": True}},
        "rules": {"Boss": True},
        "settings": {"optOutSections": True},
        "chunkinfo": {
            "manualSections": {"*fb*_100": {"*fb*_1": True}},
            "manualMonsters": {"Monsters": {"Cow": True}},
            "maxSkill": {"Cooking": 50},
        },
    }

    state, unlocked = load_map_state(payload, _chunk_info())

    assert unlocked == {"100": True}
    assert state.rules == {"Boss": True}
    assert state.settings == {"optOutSections": True}
    assert state.manual_sections == {"100": {"1": True}}
    assert state.manual_monsters == {"Monsters": {"Cow": True}}
    assert state.max_skill == {"Cooking": 50}


def test_load_map_state_tolerates_an_empty_payload() -> None:
    state, unlocked = load_map_state({}, _chunk_info())

    assert unlocked == {}
    assert state.rules == {}
    assert state.manual_sections == {}
