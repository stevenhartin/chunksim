"""Tests for the bootstrap roll pool and the roll simulation ledger.

Neighbour eligibility moved to `tests/test_neighbours.py` with the logic.
"""

from __future__ import annotations

from typing import Any

from fray_claude.chunkinfo import ChunkInfo
from fray_claude.pipeline import MapState, derive
from fray_claude.simulate import roll_pool, simulate_rolls


def _chunk_info(**data: Any) -> ChunkInfo:
    return ChunkInfo(data)


def _state(**overrides: Any) -> MapState:
    defaults: dict[str, Any] = {
        "chunk_info": _chunk_info(),
        "rules": {},
        "settings": {},
        "manual_sections": {},
        "manual_areas": {},
        "manual_monsters": {},
        "manual_equipment": {},
        "backlogged_sources": {},
        "max_skill": {},
        "passive_skill": {},
        "completed_challenges": {},
        "checked_challenges": {},
        "manual_tasks": {},
        "backlog": {},
        "active_tasks": {},
    }
    defaults.update(overrides)
    return MapState(**defaults)


def test_bootstrap_pool_defaults_to_every_region_when_none_are_selected() -> None:
    info = _chunk_info(
        rollingChunks={"misthalin": ["100"], "karamja": ["200"]},
        walkableChunks=["100", "200"],
    )
    state = _state(chunk_info=info)
    current = derive(state, {})

    assert roll_pool(state, {}, current) == ["100", "200"]


def test_bootstrap_pool_restricts_to_selected_regions() -> None:
    info = _chunk_info(
        rollingChunks={"misthalin": ["100"], "karamja": ["200"]},
        walkableChunks=["100", "200"],
    )
    state = _state(chunk_info=info, settings={"rollingChunksOptions": {"misthalin": True}})
    current = derive(state, {})

    assert roll_pool(state, {}, current) == ["100"]


def test_bootstrap_pool_intersects_with_bank_when_selected() -> None:
    info = _chunk_info(
        rollingChunks={"misthalin": ["100", "200"], "bank": ["100"]},
        walkableChunks=["100", "200"],
    )
    state = _state(chunk_info=info, settings={"rollingChunksOptions": {"bank": True}})
    current = derive(state, {})

    assert roll_pool(state, {}, current) == ["100"]


def test_bootstrap_pool_excludes_non_walkable_candidates() -> None:
    info = _chunk_info(
        rollingChunks={"misthalin": ["100", "999"]},
        walkableChunks=["100"],
    )
    state = _state(chunk_info=info)
    current = derive(state, {})

    assert roll_pool(state, {}, current) == ["100"]


def test_bootstrap_pool_uses_f2p_walkable_chunks_under_the_f2p_rule() -> None:
    info = _chunk_info(
        rollingChunks={"misthalin": ["100", "200"]},
        walkableChunks=["100", "200"],
        walkableChunksF2P=["100"],
    )
    state = _state(chunk_info=info, rules={"F2P": True})
    current = derive(state, {})

    assert roll_pool(state, {}, current) == ["100"]


def test_simulate_rolls_stops_early_when_the_pool_is_empty() -> None:
    info = _chunk_info(sections={"101": {"0": ["100"]}})
    state = _state(chunk_info=info)

    ledger = simulate_rolls(state, {"100": True}, rolls=5, seed=1)

    assert [record.chunk_id for record in ledger] == ["101"]


def test_simulate_rolls_is_deterministic_given_the_same_seed() -> None:
    info = _chunk_info(
        sections={
            "101": {"0": ["100"]},
            "102": {"0": ["100"]},
            "103": {"0": ["100"]},
        }
    )
    state = _state(chunk_info=info)

    first = simulate_rolls(state, {"100": True}, rolls=3, seed=7)
    second = simulate_rolls(state, {"100": True}, rolls=3, seed=7)

    assert [r.chunk_id for r in first] == [r.chunk_id for r in second]


def test_simulate_rolls_no_task_appears_in_two_records() -> None:
    info = _chunk_info(
        chunks={
            "100": {"Monster": {"Goblin": True}},
            "101": {"Object": {"Anvil": True}},
        },
        sections={"101": {"0": ["100"]}},
        drops={"Goblin": {"Bones": {"1": "Always"}}},
        challenges={"Nonskill": {"Use bones": {"Items": ["Bones"]}}},
    )
    state = _state(chunk_info=info)

    ledger = simulate_rolls(state, {"100": True}, rolls=2, seed=1)

    seen: set[tuple[str, str]] = set()
    for record in ledger:
        for skill, names in record.new_tasks.items():
            for name in names:
                assert (skill, name) not in seen
                seen.add((skill, name))


def test_a_later_roll_does_not_change_an_earlier_records_delta() -> None:
    info = _chunk_info(
        chunks={
            "100": {"Monster": {"Goblin": True}},
            "101": {"Object": {"Anvil": True}},
            "102": {"NPC": {"Banker": True}},
        },
        sections={"101": {"0": ["100"]}, "102": {"0": ["100", "101"]}},
        drops={"Goblin": {"Bones": {"1": "Always"}}},
        challenges={"Nonskill": {"Use bones": {"Items": ["Bones"]}}},
    )
    state = _state(chunk_info=info)

    full_run = simulate_rolls(state, {"100": True}, rolls=2, seed=3)
    assert len(full_run) == 2
    first_chunk = full_run[0].chunk_id

    stopped_after_one = simulate_rolls(state, {"100": True}, rolls=1, seed=3)

    assert stopped_after_one[0].chunk_id == first_chunk
    assert stopped_after_one[0].new_tasks == full_run[0].new_tasks
    assert stopped_after_one[0].new_sections == full_run[0].new_sections
