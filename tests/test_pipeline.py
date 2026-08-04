"""Tests for the shared sections -> sources -> challenges pipeline."""

from __future__ import annotations

from typing import Any

import pytest

from fray_claude.chunkinfo import ChunkInfo
from fray_claude.pipeline import ConvergenceError, MapState, derive, load_map_state


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


def test_load_map_state_merges_checked_into_completed_challenges() -> None:
    # `checkedChallenges` is what you've ticked during the *current* chunk;
    # upstream only migrates it into `completedChallenges` on the next roll,
    # so treating it as not-yet-obtained would report an item you hold.
    payload = {
        "chunkinfo": {
            "completedChallenges": {"BiS": {"Obtain a ~|black cape|~": True}},
            "checkedChallenges": {"BiS": {"Obtain ~|dragon boots|~": True}},
        }
    }

    state, _ = load_map_state(payload, _chunk_info())

    assert state.completed_challenges["BiS"] == {
        "Obtain a ~|black cape|~": True,
        "Obtain ~|dragon boots|~": True,
    }


def test_load_map_state_also_keeps_checked_challenges_on_their_own() -> None:
    # The merge above is what completion *tests* read; this un-merged view
    # exists so output can tell this chunk's acquisitions from earlier ones.
    payload = {
        "chunkinfo": {
            "completedChallenges": {"BiS": {"Obtain a ~|black cape|~": True}},
            "checkedChallenges": {"BiS": {"Obtain ~|dragon boots|~": True}},
        }
    }

    state, _ = load_map_state(payload, _chunk_info())

    assert state.checked_challenges["BiS"] == {"Obtain ~|dragon boots|~": True}
    # A subset of the merged view, never a separate source of truth.
    assert set(state.checked_challenges["BiS"]) <= set(state.completed_challenges["BiS"])


def test_load_map_state_leaves_checked_challenges_empty_when_absent() -> None:
    state, _ = load_map_state({"chunkinfo": {}}, _chunk_info())

    assert state.checked_challenges == {}


def test_derive_unlocks_an_area_and_gathers_its_contents() -> None:
    # The area's monster is only reachable once the `UnlocksArea` challenge
    # is valid - the circular step `derive`'s loop exists for.
    info = _chunk_info(
        chunks={
            "100": {"Connect": {"6727": True}},
            "6727": {"Name": "Guardians' Lair", "Connect": {"100": True}},
            "Guardians' Lair": {"Monster": {"Grotesque Guardians": True}},
        },
        drops={"Grotesque Guardians": {"Granite gloves": {"1": "1/500"}}},
        challenges={"Nonskill": {"Guardians' Lair": {"UnlocksArea": True}}},
    )

    # `Rare Drop Amount` defaults to "0" - an infinite threshold admitting no
    # rate-based drop - and this test is about the area unlock reaching the
    # drop at all, so give it a threshold the 1/500 rate clears.
    result = derive(
        _state(chunk_info=info, rules={"Rare Drop Amount": "1000"}), {"100": True}
    )

    assert "Grotesque Guardians" in result.source_index.monsters
    assert "Granite gloves" in result.source_index.items


def test_derive_does_not_unlock_an_area_whose_challenge_is_invalid() -> None:
    info = _chunk_info(
        chunks={
            "100": {"Connect": {"6727": True}},
            "6727": {"Name": "Guardians' Lair", "Connect": {"100": True}},
            "Guardians' Lair": {"Monster": {"Grotesque Guardians": True}},
        },
        challenges={
            "Nonskill": {"Guardians' Lair": {"UnlocksArea": True, "Chunks": ["999"]}}
        },
    )

    result = derive(_state(chunk_info=info), {"100": True})

    assert "Grotesque Guardians" not in result.source_index.monsters


def test_derive_exposes_challenge_output_items_to_bis() -> None:
    # `Granite ring (i)` exists only as an imbue challenge's `Output`, so it
    # is absent from `SourceIndex.items` yet must still be a BiS candidate.
    info = _chunk_info(
        challenges={"Nonskill": {"Imbue a granite ring": {"Output": "Granite ring (i)"}}},
        equipment={"Granite ring (i)": {"slot": "ring", "melee_strength": 5}},
    )

    result = derive(_state(chunk_info=info), {})

    assert "Granite ring (i)" not in result.source_index.items
    assert "Granite ring (i)" in result.challenges.available_items
    assert result.bis.picks["Melee-ring"] == "Granite ring (i)"


def test_derive_refuses_to_return_a_truncated_derivation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The loop used to stop silently at its cap. On the real map it converges
    on exactly the last allowed pass, so a map one link deeper would have got a
    quietly short answer - fewer areas, fewer sources, fewer valid tasks.
    """
    monkeypatch.setattr("fray_claude.pipeline._MAX_AREA_PASSES", 1)
    info = _chunk_info(
        chunks={"100": {"Monster": {"Goblin": True}}},
        drops={"Goblin": {"Bones": {"1": "Always"}}},
        challenges={"Prayer": {"Bury bones": {"Items": ["Bones"], "Level": 1}}},
    )

    with pytest.raises(ConvergenceError, match="did not settle in 1 passes"):
        derive(_state(chunk_info=info), {"100": True})


def test_derive_converges_well_inside_the_cap_on_a_simple_state() -> None:
    """Guards the other direction: the cap is headroom, not a target."""
    info = _chunk_info(
        chunks={"100": {"Monster": {"Goblin": True}}},
        drops={"Goblin": {"Bones": {"1": "Always"}}},
    )

    result = derive(_state(chunk_info=info), {"100": True})

    assert "Bones" in result.source_index.items
