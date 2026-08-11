"""Tests for the shared sections -> sources -> challenges pipeline."""

from __future__ import annotations

from typing import Any

import pytest

from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.derive.pipeline import (
    ConvergenceError,
    MapState,
    SlayerLock,
    derive,
    load_map_state,
    slayer_capped_max_skill,
    slayer_locked_equipment,
    slayer_unblocked,
)


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
    monkeypatch.setattr("fray_claude.derive.pipeline._MAX_AREA_PASSES", 1)
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


def _slayer_locked_info(**extra: Any) -> ChunkInfo:
    """A world where Slayer is trainable, two tasks need it at 20 and 80, and
    the two monsters satisfying the blocked `Aberrant spectres` task sit in
    chunks of their own - one assignable at the locked level and one not.
    """
    return _chunk_info(
        chunks={
            "100": {"Monster": {"Goblin": True}},
            "200": {"Monster": {"Aberrant spectre": True}},
            "300": {"Monster": {"Deviant spectre": True}},
        },
        drops={"Goblin": {"Bones": {"1": "Always"}}},
        slayerMonsters={"Aberrant spectre": 40, "Deviant spectre": 91},
        codeItems={
            "slayerTasks": {
                "Aberrant spectres": {"Aberrant spectre": True, "Deviant spectre": True}
            }
        },
        challenges={
            "Slayer": {"Train slayer": {"Items": ["Bones"], "Primary": True}},
            "Nonskill": {
                "Needs 20 slayer": {"Items": ["Bones"], "Skills": {"Slayer": 20}},
                "Needs 80 slayer": {"Items": ["Bones"], "Skills": {"Slayer": 80}},
            },
        },
        **extra,
    )


_LOCK = SlayerLock(level=50, monster="Aberrant spectres")


def test_a_slayer_lock_blocks_what_needs_more_slayer_than_it_allows() -> None:
    state = _state(chunk_info=_slayer_locked_info(), slayer_locked=_LOCK)

    valid = derive(state, {"100": True}).challenges.valid

    assert valid["Nonskill"].keys() == {"Needs 20 slayer"}


def test_no_slayer_lock_leaves_every_slayer_requirement_alone() -> None:
    valid = derive(_state(chunk_info=_slayer_locked_info()), {"100": True}).challenges.valid

    assert valid["Nonskill"].keys() == {"Needs 20 slayer", "Needs 80 slayer"}


def test_reaching_a_monster_that_satisfies_the_blocked_task_lifts_the_lock() -> None:
    """worker.js:3824 / index.js:9788 - the assignment can be handed in, so
    Slayer is not blocked at all and the cap disappears rather than easing."""
    state = _state(chunk_info=_slayer_locked_info(), slayer_locked=_LOCK)

    assert slayer_unblocked(state, {"100": True, "200": True}) is True
    assert derive(state, {"100": True, "200": True}).challenges.valid["Nonskill"].keys() == {
        "Needs 20 slayer",
        "Needs 80 slayer",
    }


def test_a_satisfying_monster_above_the_locked_level_does_not_lift_it() -> None:
    """index.js:9790 - `Deviant spectre` needs 91 Slayer and the lock caps at
    50, so reaching it changes nothing: you still cannot be assigned it."""
    state = _state(chunk_info=_slayer_locked_info(), slayer_locked=_LOCK)

    assert slayer_unblocked(state, {"100": True, "300": True}) is False


def test_a_lock_naming_no_known_task_never_lifts() -> None:
    """`'Manually Locked'` is a sentinel upstream offers beside the real task
    names (index.js:9590); it is in no table, so nothing can satisfy it."""
    state = _state(chunk_info=_slayer_locked_info(), slayer_locked=SlayerLock(level=50, monster="Manually Locked"))

    assert slayer_unblocked(state, {"100": True, "200": True, "300": True}) is False


def test_a_slayer_lock_takes_the_lower_of_itself_and_max_skill() -> None:
    info = _slayer_locked_info()
    lock = _LOCK

    assert slayer_capped_max_skill(_state(chunk_info=info, slayer_locked=lock, max_skill={"Slayer": 30}), {})["Slayer"] == 30
    assert slayer_capped_max_skill(_state(chunk_info=info, slayer_locked=lock, max_skill={"Slayer": 70}), {})["Slayer"] == 50
    assert slayer_capped_max_skill(_state(chunk_info=info, slayer_locked=lock), {})["Slayer"] == 50


def test_a_slayer_lock_leaves_every_other_skill_alone() -> None:
    lock = _LOCK
    state = _state(chunk_info=_slayer_locked_info(), slayer_locked=lock, max_skill={"Mining": 40})

    assert slayer_capped_max_skill(state, {}) == {"Mining": 40, "Slayer": 50}


def test_load_map_state_reads_a_slayer_lock() -> None:
    """The level is a string in the payload - it comes off a text input
    (index.js:8484) - and the monster is a raw `slayerTasks` key."""
    payload = {"chunkinfo": {"slayerLocked": {"level": "42", "monster": "Aberrant spectres"}}}

    state, _ = load_map_state(payload, _chunk_info())

    assert state.slayer_locked == SlayerLock(level=42, monster="Aberrant spectres")


def test_load_map_state_reads_no_lock_when_slayer_is_unblocked() -> None:
    state, _ = load_map_state({"chunkinfo": {}}, _chunk_info())

    assert state.slayer_locked is None


@pytest.mark.parametrize("branch", [{"monster": "Aberrant spectres"}, {"level": "", "monster": "x"}, {"level": "50"}])
def test_load_map_state_refuses_a_malformed_lock_rather_than_guessing(branch: dict[str, Any]) -> None:
    """Upstream's own input handler will not store one (index.js:8481), so a
    payload holding one is corrupt - and a guessed cap would silently
    invalidate Slayer."""
    state, _ = load_map_state({"chunkinfo": {"slayerLocked": branch}}, _chunk_info())

    assert state.slayer_locked is None


def _gear_info(**extra: Any) -> ChunkInfo:
    extra.setdefault("chunks", {"100": {"Monster": {"Goblin": True}}})
    return _chunk_info(
        slayerMonsters={"Aberrant spectre": 40},
        codeItems={"slayerTasks": {"Aberrant spectres": {"Aberrant spectre": True}}},
        slayerEquipment={"Facemask": 10, "Nose peg": 60, "Spiny helmet": 35},
        **extra,
    )


def test_locked_equipment_is_the_gear_above_the_lock() -> None:
    state = _state(chunk_info=_gear_info(), slayer_locked=SlayerLock(level=35, monster="x"))

    # 35 is not *above* 35, so the spiny helmet stays wearable.
    assert slayer_locked_equipment(state, {"100": True}) == frozenset({"Nose peg"})


def test_no_lock_blocks_no_equipment() -> None:
    assert slayer_locked_equipment(_state(chunk_info=_gear_info()), {"100": True}) == frozenset()


def test_an_escaped_lock_blocks_no_equipment_either() -> None:
    """The lock lifting lifts all of it - upstream renames the starred keys
    back in the same pass (worker.js:3275)."""
    info = _gear_info(chunks={"100": {"Monster": {"Aberrant spectre": True}}})
    state = _state(chunk_info=info, slayer_locked=SlayerLock(level=50, monster="Aberrant spectres"))

    assert slayer_unblocked(state, {"100": True}) is True
    assert slayer_locked_equipment(state, {"100": True}) == frozenset()
