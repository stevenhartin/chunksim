"""Tests for the bootstrap roll pool, the roll ledger, and the payload a
finished ledger turns back into.

Neighbour eligibility moved to `tests/test_neighbours.py` with the logic;
persisting a payload is `tests/test_batch.py`'s.
"""

from __future__ import annotations

import json
from typing import Any

from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.derive.pipeline import MapState, derive
from fray_claude.simulate import UnlockRecord, roll_pool, simulate_rolls, simulated_payload


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


# --- turning a finished ledger back into a map payload -----------------------


def _record(chunk_id: str, order: int = 1) -> UnlockRecord:
    return UnlockRecord(
        order=order,
        chunk_id=chunk_id,
        new_sections={},
        new_tasks={},
        new_unsupported=frozenset(),
        bis_upgrades={},
    )


def test_simulated_payload_adds_the_rolled_chunks_in_the_payloads_own_form() -> None:
    base = {"chunks": {"unlocked": {"100": "100"}}}

    payload = simulated_payload(base, [_record("101"), _record("102", 2)])

    # `{id: id}`, matching real data - not `{id: True}`.
    assert payload["chunks"]["unlocked"] == {"100": "100", "101": "101", "102": "102"}


def test_simulated_payload_never_mutates_the_payload_it_was_given() -> None:
    """Runs in a batch share one base payload; mutating it would leak roll N
    into run N+1."""
    base = {"chunks": {"unlocked": {"100": "100"}}, "chunkOrder": {}, "chunkinfo": {}}
    before = json.loads(json.dumps(base))

    simulated_payload(base, [_record("101")])

    assert base == before


def test_simulated_payload_logs_each_roll_in_chunk_order() -> None:
    base = {"chunks": {"unlocked": {}}, "chunkOrder": {"1709907279995": 7222}}

    payload = simulated_payload(base, [_record("101"), _record("102", 2)], start_time_ms=1000)

    assert payload["chunkOrder"] == {"1709907279995": 7222, "1000": 101, "1001": 102}


def test_simulated_payload_commits_the_current_chunks_tick_offs() -> None:
    """Rolling migrates `checkedChallenges` into `completedChallenges` and
    clears it upstream (`completeChallenges`, index.js:12718)."""
    base = {
        "chunks": {"unlocked": {}},
        "chunkinfo": {
            "completedChallenges": {"Mining": {"t_1": True}},
            "checkedChallenges": {"Mining": {"t_2": True}, "BiS": {"t_3": True}},
        },
    }

    payload = simulated_payload(base, [_record("101")])

    assert payload["chunkinfo"]["completedChallenges"] == {
        "Mining": {"t_1": True, "t_2": True},
        "BiS": {"t_3": True},
    }
    assert "checkedChallenges" not in payload["chunkinfo"]


def test_simulated_payload_leaves_tick_offs_alone_when_nothing_rolled() -> None:
    base = {"chunks": {"unlocked": {}}, "chunkinfo": {"checkedChallenges": {"Mining": {"t_2": 1}}}}

    payload = simulated_payload(base, [])

    assert payload["chunkinfo"]["checkedChallenges"] == {"Mining": {"t_2": 1}}


def test_simulated_payload_drops_upstreams_recorded_answers() -> None:
    """`activeTasks` and `chunks.selected` are upstream's own computed answers
    for a chunk set it has actually seen - this project's oracles. Carrying
    them into a simulated state would invent an oracle for a world upstream
    never computed."""
    base = {
        "chunks": {"unlocked": {}, "selected": {"101": 1}},
        "chunkinfo": {"activeTasks": {"Slayer": {"t_9": "x"}}, "maxSkill": {"Mining": 70}},
    }

    payload = simulated_payload(base, [_record("101")])

    assert "selected" not in payload["chunks"]
    assert "activeTasks" not in payload["chunkinfo"]
    assert payload["chunkinfo"]["maxSkill"] == {"Mining": 70}
