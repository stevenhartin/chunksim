"""Tests for chunk-unlock eligibility and upstream's neighbour numbering."""

from __future__ import annotations

from typing import Any

import pytest

from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.derive.graph import grid_neighbours
from fray_claude.derive.neighbours import assign_numbers, eligible_neighbours, neighbour_pool
from fray_claude.derive.pipeline import Derived, MapState, derive



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


def _pool(state: MapState, unlocked: dict[str, bool]) -> list[str]:
    return neighbour_pool(state, unlocked, derive(state, unlocked))


# --- eligibility (moved from tests/test_simulate.py) -------------------------


def test_a_grid_adjacent_connected_chunk_is_eligible() -> None:
    # 101 is grid-adjacent to 100 (±1), and its section 0 connects plainly
    # back to 100, which is already unlocked.
    state = _state(chunk_info=_chunk_info(sections={"101": {"0": ["100"]}}))

    assert _pool(state, {"100": True}) == ["101"]


def test_a_chunk_with_no_sections_entry_is_not_eligible() -> None:
    # No `chunkInfo.sections` entry means "not walkable" - only the 1,172
    # walkable chunks have one (index.js:3050).
    assert _pool(_state(), {"100": True}) == []


def test_a_chunk_with_no_reachable_connection_is_not_eligible() -> None:
    # 101 connects only to 999, which is neither unlocked nor reachable.
    state = _state(chunk_info=_chunk_info(sections={"101": {"0": ["999"]}}))

    assert _pool(state, {"100": True}) == []


def test_the_f2p_rule_restricts_candidates_to_the_f2p_walkable_list() -> None:
    state = _state(
        chunk_info=_chunk_info(sections={"101": {"0": ["100"]}}, walkableChunksF2P=[]),
        rules={"F2P": True},
    )

    assert _pool(state, {"100": True}) == []


def test_a_named_area_in_the_unlocked_set_proposes_no_candidates() -> None:
    # Area names aren't grid-addressable, so they contribute no neighbours.
    state = _state(chunk_info=_chunk_info(sections={"101": {"0": ["Zanaris"]}}))

    assert _pool(state, {"Zanaris": True}) == []


def test_a_non_grid_adjacent_connection_does_not_confer_eligibility() -> None:
    """The graph keeps boat/stair/teleport edges; the neighbour walk does not
    traverse them - it only ever proposes `±1`/`±256` candidates."""
    state = _state(chunk_info=_chunk_info(sections={"1123": {"0": ["100"]}}))

    assert _pool(state, {"100": True}) == []


# --- the sectionsLimits gate (defect (a)) ------------------------------------


def test_a_sections_limit_blocks_a_candidate_until_its_task_is_valid() -> None:
    # The gate names a Quest task that's never satisfiable in this fixture
    # (it needs a chunk that's never unlocked), so 101 must stay excluded.
    state = _state(
        chunk_info=_chunk_info(
            sections={"101": {"0": ["100"]}},
            sectionsLimits={"101 to 100": {"Tasks": {"Do it": "Quest"}}},
            challenges={"Quest": {"Do it": {"Chunks": ["999"]}}},
        )
    )
    current = derive(state, {"100": True})

    assert "Do it" not in current.challenges.valid.get("Quest", {})
    assert neighbour_pool(state, {"100": True}, current) == []


def test_a_candidate_is_eligible_once_its_sections_limit_gate_is_met() -> None:
    state = _state(
        chunk_info=_chunk_info(
            sections={"101": {"0": ["100"]}},
            sectionsLimits={"101 to 100": {"Tasks": {"Do it": "Quest"}}},
            challenges={"Quest": {"Do it": {}}},
        )
    )
    current = derive(state, {"100": True})

    assert "Do it" in current.challenges.valid.get("Quest", {})
    assert neighbour_pool(state, {"100": True}, current) == ["101"]


def test_a_sections_limit_under_code_items_is_ignored() -> None:
    """Defect (a) regression: the gate is a *top-level* export key.

    An earlier port read `codeItems['sectionsLimits']`, where it has never
    existed, so the gate never fired. Pinning that the wrong branch stays
    inert is what stops the fixture and the code agreeing with each other
    while both disagree with the export.
    """
    state = _state(
        chunk_info=_chunk_info(
            sections={"101": {"0": ["100"]}},
            codeItems={"sectionsLimits": {"101 to 100": {"Tasks": {"Do it": "Quest"}}}},
            challenges={"Quest": {"Do it": {"Chunks": ["999"]}}},
        )
    )

    assert _pool(state, {"100": True}) == ["101"]


def test_a_sections_limit_with_a_non_string_skill_fails_the_gate() -> None:
    # `globalValids.hasOwnProperty(<non-string>)` is false upstream, i.e.
    # invalid - not "skip this task".
    state = _state(
        chunk_info=_chunk_info(
            sections={"101": {"0": ["100"]}},
            sectionsLimits={"101 to 100": {"Tasks": {"Do it": 7}}},
        )
    )

    assert _pool(state, {"100": True}) == []


# --- section abandonment (defect (b)) ----------------------------------------


def test_a_failed_gate_abandons_the_rest_of_that_section() -> None:
    """Defect (b) regression: upstream's `.some()` callback returns `true` on a
    failed gate (index.js:3060), ending that section's connection walk.

    `100` is unlocked and would qualify on its own, but it sits *after* the
    gated `999-1` in the same section's list, so upstream never reaches it.
    The earlier `continue` did, and wrongly made 101 eligible.
    """
    state = _state(
        chunk_info=_chunk_info(
            sections={"101": {"1": ["999-1", "100"]}},
            sectionsLimits={"101-1 to 999-1": {"Tasks": {"Do it": "Quest"}}},
            challenges={"Quest": {"Do it": {"Chunks": ["999"]}}},
        )
    )

    assert _pool(state, {"100": True}) == []


def test_a_failed_gate_does_not_abandon_the_chunks_other_sections() -> None:
    """Abandonment is `.some()`-scoped, so it is per-section: the `forEach`
    over the candidate's sections carries on."""
    state = _state(
        chunk_info=_chunk_info(
            sections={"101": {"1": ["999-1", "100"], "2": ["100"]}},
            sectionsLimits={"101-1 to 999-1": {"Tasks": {"Do it": "Quest"}}},
            challenges={"Quest": {"Do it": {"Chunks": ["999"]}}},
        )
    )
    current = derive(state, {"100": True})
    (neighbour,) = eligible_neighbours(state, {"100": True}, current)

    assert neighbour.chunk_id == "101"
    assert neighbour.via_section == "2"


# --- the bare-ref branch -----------------------------------------------------


def test_a_bare_ref_tests_the_chunk_being_unlocked_not_its_section_zero() -> None:
    """Upstream branches on `connection.includes('-')` (index.js:3065).

    `100` here is section-split, so it has no section `0` in
    `reachable_sections` - but a bare ref asks only whether the chunk is
    unlocked, so the candidate still qualifies.
    """
    state = _state(
        chunk_info=_chunk_info(sections={"101": {"0": ["100"]}, "100": {"1": [], "W1": []}})
    )
    current = derive(state, {"100": True})

    assert "0" not in current.reachable_sections.get("100", {})
    assert neighbour_pool(state, {"100": True}, current) == ["101"]


# --- numbering ---------------------------------------------------------------


def test_numbers_run_from_one_at_the_highest_chunk_id() -> None:
    assert assign_numbers(["100", "300", "200"]) == {"300": 1, "200": 2, "100": 3}


def test_numbering_ignores_the_order_it_is_given() -> None:
    assert assign_numbers(["300", "100", "200"]) == assign_numbers(["100", "200", "300"])


def test_eligible_neighbours_are_returned_in_number_order() -> None:
    state = _state(
        chunk_info=_chunk_info(
            sections={
                "101": {"0": ["100"]},
                "356": {"0": ["100"]},
                "99": {"0": ["100"]},
            }
        )
    )
    current = derive(state, {"100": True})
    result = eligible_neighbours(state, {"100": True}, current)

    assert [neighbour.number for neighbour in result] == [1, 2, 3]
    assert [neighbour.chunk_id for neighbour in result] == ["356", "101", "99"]


# --- attribution and display -------------------------------------------------


def test_attribution_names_the_first_qualifying_connection_in_export_order() -> None:
    state = _state(chunk_info=_chunk_info(sections={"101": {"0": ["100", "356"]}}))
    unlocked = {"100": True, "356": True}
    (neighbour,) = eligible_neighbours(state, unlocked, derive(state, unlocked))

    assert neighbour.via_ref == "100"


def test_attribution_is_independent_of_the_unlocked_iteration_order() -> None:
    info = _chunk_info(sections={"101": {"0": ["100", "356"]}})
    forwards = {"100": True, "356": True}
    backwards = {"356": True, "100": True}

    def via(unlocked: dict[str, bool]) -> str:
        state = _state(chunk_info=info)
        (neighbour,) = eligible_neighbours(state, unlocked, derive(state, unlocked))
        return neighbour.via_ref

    assert via(forwards) == via(backwards) == "100"


def test_the_nickname_comes_from_the_chunk_entry() -> None:
    state = _state(
        chunk_info=_chunk_info(
            sections={"101": {"0": ["100"]}}, chunks={"101": {"Nickname": "Lumbridge"}}
        )
    )
    (neighbour,) = eligible_neighbours(state, {"100": True}, derive(state, {"100": True}))

    assert neighbour.nickname == "Lumbridge"


def test_the_nickname_is_none_when_the_chunk_has_no_entry() -> None:
    state = _state(chunk_info=_chunk_info(sections={"101": {"0": ["100"]}}))
    (neighbour,) = eligible_neighbours(state, {"100": True}, derive(state, {"100": True}))

    assert neighbour.nickname is None


def test_as_dict_carries_the_json_contract() -> None:
    state = _state(
        chunk_info=_chunk_info(
            sections={"101": {"0": ["100"]}}, chunks={"101": {"Nickname": "Lumbridge"}}
        )
    )
    (neighbour,) = eligible_neighbours(state, {"100": True}, derive(state, {"100": True}))

    assert neighbour.as_dict() == {
        "number": 1,
        "chunk_id": "101",
        "nickname": "Lumbridge",
        "via_section": "0",
        "via_ref": "100",
    }


def test_neighbour_pool_is_the_sorted_ids_of_the_eligible_neighbours() -> None:
    state = _state(
        chunk_info=_chunk_info(sections={"101": {"0": ["100"]}, "356": {"0": ["100"]}})
    )
    current = derive(state, {"100": True})

    assert neighbour_pool(state, {"100": True}, current) == ["101", "356"]
    assert [n.chunk_id for n in eligible_neighbours(state, {"100": True}, current)] == [
        "356",
        "101",
    ]


# --- opt-in, against the real export -----------------------------------------


@pytest.mark.real_export
def test_the_cabin_fever_gate_blocks_its_neighbour_on_the_real_export(
    real_export: ChunkInfo,
) -> None:
    """Defect (a)'s real-data regression: the gate must actually fire.

    The export's only two `sectionsLimits` entries gate the crossing between
    `14646-1` (Port Phasmatys) and `14902` (the School Boat) on
    `~|Cabin Fever|~ 1`. Holding only `14902` makes `14646` a grid-adjacent
    candidate whose section `1` lists `["14647-1", "14902"]`: `14647-1` is not
    reachable, and `14902` is exactly the gated crossing. With the gate live
    the pool is empty; with it read from `codeItems` - where it does not exist,
    so it never fired - the pool was `["14646"]`.

    Both gated chunks are already unlocked on the real map, so this uses a
    hypothetical unlocked set rather than the cached one. That is the only way
    the gate is observable at all: it is unreachable from the map's own state.
    """
    state = _state(chunk_info=real_export)
    unlocked = {"14902": True}
    current = derive(state, unlocked)

    assert "~|Cabin Fever|~ 1" not in current.challenges.valid.get("Quest", {})
    assert neighbour_pool(state, unlocked, current) == []


@pytest.mark.real_cache
def test_the_real_maps_neighbours_satisfy_the_numbering_invariants(
    real_state: tuple[MapState, dict[str, bool]], real_derived: Derived
) -> None:
    """Structural rather than golden: a `fray fetch` after a roll changes the
    answer, and breaking the suite for that would be the wrong signal."""
    state, unlocked = real_state
    result = eligible_neighbours(state, unlocked, real_derived)

    assert [n.number for n in result] == list(range(1, len(result) + 1))
    assert all(n.chunk_id not in unlocked for n in result)
    ids = {int(n.chunk_id) for n in result}
    held = {int(chunk) for chunk in unlocked if chunk.isdigit()}
    assert all(any(side in held for side in grid_neighbours(chunk_id)) for chunk_id in ids)
    # Descending id order is the whole of `sortSelectedChunks`.
    assert [int(n.chunk_id) for n in result] == sorted(ids, reverse=True)


@pytest.mark.real_cache
def test_neighbour_numbers_match_the_apps_own_answer(
    real_state: tuple[MapState, dict[str, bool]],
    real_payload: dict[str, Any],
    real_derived: Derived,
) -> None:
    """The oracle: `chunks.selected` is upstream's own computed answer.

    `setData` writes it plain (no `encodeObject`) as `{chunk_id: number}`
    whenever `tempChunks['selected']` is populated (index.js:13773-13776), and
    the clipboard menu's "assign" action populates it by calling the very
    function this module ports (index.js:4652). It is absent until then,
    because all four `chunkNeighboursOptions` flags are off on this map.

    A mismatch here is a defect in this module, not a stale oracle. One caveat:
    `tempSelectedChunks` also carries hand-selected chunks, so the oracle is
    only clean if nothing was manually selected before "assign" was pressed.
    """
    from fray_claude.model.summary import _mapping

    state, unlocked = real_state
    oracle = _mapping(_mapping(real_payload, "chunks"), "selected")
    if not oracle:
        pytest.skip(
            "no chunks.selected recorded; run the app's 'assign' action, then `fray fetch`"
        )

    result = eligible_neighbours(state, unlocked, real_derived)
    assert {n.chunk_id: n.number for n in result} == {k: int(v) for k, v in oracle.items()}
