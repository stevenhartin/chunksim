"""Tests for the per-chunk unlock delta and its attribution guarantees."""

from __future__ import annotations

from typing import Any

from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.pipeline import MapState
from fray_claude.unlock import diff_bis_picks, diff_reachable_sections, diff_valid_tasks, tasks_added_by


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


def test_diff_valid_tasks_finds_only_newly_valid_entries() -> None:
    before = {"Nonskill": {"A": True}}
    after = {"Nonskill": {"A": True, "B": True}, "Quest": {"C": True}}

    assert diff_valid_tasks(before, after) == {"Nonskill": {"B": True}, "Quest": {"C": True}}


def test_diff_valid_tasks_is_empty_when_nothing_changed() -> None:
    same = {"Nonskill": {"A": True}}

    assert diff_valid_tasks(same, same) == {}


def test_diff_reachable_sections_finds_only_newly_reachable_entries() -> None:
    before = {"100": {"1": True}}
    after = {"100": {"1": True, "2": True}, "200": {"1": True}}

    assert diff_reachable_sections(before, after) == {"100": {"2": True}, "200": {"1": True}}


def test_tasks_added_by_reports_the_new_tasks_and_sections() -> None:
    info = _chunk_info(
        chunks={"100": {"Monster": {"Goblin": True}}},
        drops={"Goblin": {"Bones": {"1": "Always"}}},
        challenges={"Nonskill": {"Use bones": {"Items": ["Bones"]}}},
    )
    state = _state(chunk_info=info)

    delta = tasks_added_by(state, {}, "100")

    assert delta.chunk_id == "100"
    assert delta.new_tasks == {"Nonskill": {"Use bones": True}}
    assert delta.task_count == 1


def test_tasks_added_by_reports_nothing_for_an_already_satisfied_task() -> None:
    info = _chunk_info(
        chunks={
            "100": {"Monster": {"Goblin": True}},
            "200": {"Object": {"Anvil": True}},
        },
        drops={"Goblin": {"Bones": {"1": "Always"}}},
        challenges={"Nonskill": {"Use bones": {"Items": ["Bones"]}}},
    )
    state = _state(chunk_info=info)

    delta = tasks_added_by(state, {"100": True}, "200")

    assert delta.new_tasks == {}
    assert delta.task_count == 0


def test_a_task_is_attributed_to_only_the_unlock_that_first_makes_it_valid() -> None:
    # Chunk A grounds a Nonskill task; chunk B unlocked afterwards must not
    # re-report a task that was already valid before it - the partition
    # property the whole simulation ledger depends on.
    info = _chunk_info(
        chunks={
            "100": {"Monster": {"Goblin": True}},
            "200": {"Object": {"Anvil": True}},
        },
        drops={"Goblin": {"Bones": {"1": "Always"}}},
        challenges={"Nonskill": {"Use bones": {"Items": ["Bones"]}}},
    )
    state = _state(chunk_info=info)

    delta_a = tasks_added_by(state, {}, "100")
    delta_b = tasks_added_by(state, {"100": True}, "200")

    assert delta_a.new_tasks == {"Nonskill": {"Use bones": True}}
    assert delta_b.new_tasks == {}
    a_tasks = {(skill, name) for skill, names in delta_a.new_tasks.items() for name in names}
    b_tasks = {(skill, name) for skill, names in delta_b.new_tasks.items() for name in names}
    assert a_tasks.isdisjoint(b_tasks)


def test_unlocking_b_does_not_change_the_already_computed_delta_for_a() -> None:
    info = _chunk_info(
        chunks={
            "100": {"Monster": {"Goblin": True}},
            "200": {"Object": {"Anvil": True}},
        },
        drops={"Goblin": {"Bones": {"1": "Always"}}},
        challenges={
            "Nonskill": {
                "Use bones": {"Items": ["Bones"]},
                "Needs both": {"Objects": ["Anvil"], "Items": ["Bones"]},
            }
        },
    )
    state = _state(chunk_info=info)

    delta_a_alone = tasks_added_by(state, {}, "100")
    # A run that continues on to unlock B must reproduce an identical record
    # for A, computed the same way (against the state immediately before A).
    delta_a_in_sequence = tasks_added_by(state, {}, "100")
    delta_b_after_a = tasks_added_by(state, {"100": True}, "200")

    assert delta_a_alone == delta_a_in_sequence
    assert delta_a_alone.new_tasks == {"Nonskill": {"Use bones": True}}
    # "Needs both" only becomes valid once B is also unlocked, so it belongs
    # to B's record, never retroactively folded into A's.
    assert delta_b_after_a.new_tasks == {"Nonskill": {"Needs both": True}}


def test_tasks_added_by_reports_newly_reachable_sections() -> None:
    info = _chunk_info(sections={"100": {"1": ["200"]}})
    state = _state(chunk_info=info)

    delta = tasks_added_by(state, {"100": True}, "200")

    assert delta.new_sections == {"100": {"1": True}}


def test_diff_bis_picks_reports_new_and_changed_slots() -> None:
    before = {"Melee-weapon": "Bronze sword"}
    after = {"Melee-weapon": "Rune scimitar", "Melee-shield": "Rune kiteshield"}

    assert diff_bis_picks(before, after) == {
        "Melee-weapon": ("Bronze sword", "Rune scimitar"),
        "Melee-shield": (None, "Rune kiteshield"),
    }


def test_diff_bis_picks_ignores_unchanged_slots() -> None:
    same = {"Melee-weapon": "Rune scimitar"}

    assert diff_bis_picks(same, same) == {}


def test_tasks_added_by_reports_a_new_bis_upgrade() -> None:
    info = _chunk_info(
        chunks={"100": {"Monster": {"Goblin": True}}},
        drops={"Goblin": {"Rune scimitar": {"1": "Always"}}},
        equipment={
            "Rune scimitar": {
                "slot": "weapon",
                "attack_speed": 4,
                "attack_slash": 45,
                "melee_strength": 44,
            }
        },
    )
    state = _state(chunk_info=info)

    delta = tasks_added_by(state, {}, "100")

    # The sole weapon candidate wins every active style by default.
    assert delta.bis_upgrades == {
        "Melee-weapon": (None, "Rune scimitar"),
        "Ranged-weapon": (None, "Rune scimitar"),
        "Magic-weapon": (None, "Rune scimitar"),
    }
