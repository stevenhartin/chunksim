"""Tests for section connectivity (`findConnectedSections` + the live half of
`getAllChunkAreas`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from fray_claude.cache import read_chunkinfo
from fray_claude.chunkinfo import ChunkInfo
from fray_claude.sections import (
    ChunkSections,
    area_connections,
    describe_sections,
    expand_chunk_areas,
    unlockable_areas,
    unlocked_sections,
)

_REAL_CHUNKINFO = os.environ.get("FRAY_CHUNKINFO")


def _chunk_info(**data: Any) -> ChunkInfo:
    return ChunkInfo(data)


def test_expand_chunk_areas_adds_enabled_manual_areas() -> None:
    assert expand_chunk_areas({"a": True}, manual_areas={"b": True}) == {"a": True, "b": True}


def test_expand_chunk_areas_removes_disabled_manual_areas() -> None:
    result = expand_chunk_areas({"a": True, "b": True}, manual_areas={"b": False})

    assert result == {"a": True}


def test_expand_chunk_areas_tolerates_no_manual_areas() -> None:
    assert expand_chunk_areas({"a": True}) == {"a": True}


def test_section_zero_is_never_reported() -> None:
    info = _chunk_info(sections={"800": {"0": ["900"]}})

    reachable = unlocked_sections({"800": True, "900": True}, info)

    assert reachable == {}


def test_a_plain_connection_needs_the_target_chunk_unlocked() -> None:
    info = _chunk_info(sections={"100": {"1": ["200"]}})

    assert unlocked_sections({"100": True}, info) == {}
    assert unlocked_sections({"100": True, "200": True}, info) == {"100": {"1": True}}


def test_reachability_propagates_across_a_multi_pass_fixed_point() -> None:
    # Section 2 depends on section 1, which only becomes reachable once
    # chunk 200 (separately unlocked) grounds it - two passes are required.
    info = _chunk_info(sections={"100": {"1": ["200"], "2": ["100-1"]}})

    reachable = unlocked_sections({"100": True, "200": True}, info)

    assert reachable == {"100": {"1": True, "2": True}}


def test_a_dashed_connection_needs_the_target_section_reachable() -> None:
    info = _chunk_info(sections={"100": {"1": ["200-1"]}, "200": {"1": ["999"]}})

    # Chunk 200's own section 1 never becomes reachable (999 is never
    # unlocked), so 100's section 1 can't ground on it either.
    reachable = unlocked_sections({"100": True, "200": True}, info)

    assert reachable == {}


def test_static_connect_grounds_a_section_via_a_linked_area() -> None:
    info = _chunk_info(
        sections={"300": {"1": []}},
        chunks={
            "300": {"Sections": {"1": {"Connect": {"400": {}}}}},
            "400": {"Name": "Extra Area"},
        },
    )

    reachable = unlocked_sections({"300": True, "Extra Area": True}, info)

    assert reachable == {"300": {"1": True}}


def test_static_connect_excludes_unconnected_areas() -> None:
    info = _chunk_info(
        sections={"300": {"1": []}},
        chunks={
            "300": {"Sections": {"1": {"Connect": {"400": {}}}}},
            "400": {"Name": "Zanaris"},
        },
    )

    reachable = unlocked_sections({"300": True, "Zanaris": True}, info)

    assert reachable == {}


def test_manual_section_true_is_seeded_regardless_of_connectivity() -> None:
    info = _chunk_info(sections={"500": {"1": ["999"]}})

    reachable = unlocked_sections(
        {"500": True}, info, manual_sections={"500": {"1": True}}
    )

    assert reachable == {"500": {"1": True}}


def test_manual_section_false_blocks_an_otherwise_reachable_section() -> None:
    info = _chunk_info(sections={"600": {"1": ["700"]}})

    reachable = unlocked_sections(
        {"600": True, "700": True}, info, manual_sections={"600": {"1": False}}
    )

    assert reachable.get("600", {}).get("1") is not True


def test_manual_section_is_ignored_for_a_chunk_that_is_not_unlocked() -> None:
    info = _chunk_info(sections={"500": {"1": ["999"]}})

    reachable = unlocked_sections({}, info, manual_sections={"500": {"1": True}})

    assert reachable == {}


def test_opt_out_sections_opens_non_water_sections_only() -> None:
    info = _chunk_info(sections={"1000": {"1": ["missing"], "W1": ["missing"]}})

    reachable = unlocked_sections({"1000": True}, info, opt_out_sections=True)

    assert reachable == {"1000": {"1": True}}


def test_opt_out_sections_water_opens_every_section() -> None:
    info = _chunk_info(sections={"1000": {"1": ["missing"], "W1": ["missing"]}})

    reachable = unlocked_sections({"1000": True}, info, opt_out_sections_water=True)

    assert reachable == {"1000": {"1": True, "W1": True}}


def test_unlocked_sections_tolerates_an_empty_export() -> None:
    assert unlocked_sections({"100": True}, _chunk_info()) == {}


@pytest.mark.skipif(
    not _REAL_CHUNKINFO, reason="set FRAY_CHUNKINFO to a real export to run this"
)
def test_manual_sections_match_a_real_export() -> None:
    """Opt-in oracle: a real map's `chunkinfo.manualSections` entries against
    the real export, cross-checked by hand when this was written (`fray
    sections` against a cached map with these four chunks unlocked)."""
    assert _REAL_CHUNKINFO is not None
    data = read_chunkinfo(override=Path(_REAL_CHUNKINFO))
    info = ChunkInfo(data)

    unlocked = {chunk_id: True for chunk_id in ("13874", "13878", "6705", "8748")}
    manual_sections = {
        "13874": {"1": True, "2": True, "3": True},
        "13878": {"1": True, "2": False, "3": False, "4": False, "5": False},
        "6705": {"1": True},
        "8748": {"1": True},
    }

    reachable = unlocked_sections(unlocked, info, manual_sections=manual_sections)

    assert reachable.get("13874") == {"1": True, "2": True, "3": True}
    assert reachable.get("13878") == {"1": True}
    assert reachable.get("6705") == {"1": True}
    assert reachable.get("8748", {}).get("1") is True


def test_describe_sections_reports_section_0_for_an_unsectioned_chunk() -> None:
    info = _chunk_info(chunks={"100": {"Nickname": "Home"}})

    entries = describe_sections({"100": True}, {}, info)

    assert entries == [ChunkSections(chunk_id="100", name="Home", reachable=["0"], locked=[])]


def test_describe_sections_splits_reachable_from_locked() -> None:
    info = _chunk_info(sections={"100": {"1": [], "2": [], "3": []}})

    entries = describe_sections({"100": True}, {"100": {"1": True, "3": True}}, info)

    assert entries[0].reachable == ["0", "1", "3"]
    assert entries[0].locked == ["2"]


def test_describe_sections_prefers_nickname_over_name() -> None:
    info = _chunk_info(chunks={"100": {"Nickname": "Home", "Name": "Formal Name"}})

    entries = describe_sections({"100": True}, {}, info)

    assert entries[0].name == "Home"


def test_describe_sections_falls_back_to_name_then_none() -> None:
    info = _chunk_info(chunks={"100": {"Name": "Formal Name"}, "200": {}})

    entries = describe_sections({"100": True, "200": True}, {}, info)

    by_id = {e.chunk_id: e.name for e in entries}
    assert by_id == {"100": "Formal Name", "200": None}


def test_describe_sections_sorts_chunk_ids_numerically() -> None:
    info = _chunk_info()

    entries = describe_sections({"200": True, "30": True, "100": True}, {}, info)

    assert [e.chunk_id for e in entries] == ["30", "100", "200"]


def test_describe_sections_as_dict() -> None:
    entry = ChunkSections(chunk_id="100", name="Home", reachable=["0", "1"], locked=["2"])

    assert entry.as_dict() == {
        "chunk_id": "100",
        "name": "Home",
        "reachable": ["0", "1"],
        "locked": ["2"],
    }


# --- named-area unlocks (getAllChunkAreas' Connect walk + the UnlocksArea
# pass). The export stores such an area twice: the numbered entrance chunk
# carrying `Connect`/`Name`, and a top-level key under the area's own name
# holding its contents - real shape, e.g. 6727/"Grotesque Guardians' Lair".


def _area_info(**overrides: Any) -> ChunkInfo:
    data: dict[str, Any] = {
        "chunks": {
            "100": {"Connect": {"6727": True}},
            "6727": {"Name": "Guardians' Lair", "Connect": {"100": True}},
            "Guardians' Lair": {"Monster": {"Grotesque Guardians": True}},
        },
        "challenges": {"Nonskill": {"Guardians' Lair": {"UnlocksArea": True}}},
    }
    data.update(overrides)
    return ChunkInfo(data)


def test_area_connections_maps_an_area_to_its_connecting_chunk() -> None:
    assert area_connections({"100": True}, _area_info()) == {"Guardians' Lair": {"100": True}}


def test_area_connections_walks_section_level_connects() -> None:
    info = ChunkInfo(
        {
            "chunks": {
                "100": {"Sections": {"1": {"Connect": {"6727": True}}}},
                "6727": {"Name": "Guardians' Lair"},
            }
        }
    )

    assert area_connections({"100": True}, info) == {"Guardians' Lair": {"100": True}}


def test_area_connections_ignores_targets_without_a_name() -> None:
    info = ChunkInfo({"chunks": {"100": {"Connect": {"200": True}}, "200": {}}})

    assert area_connections({"100": True}, info) == {}


def test_unlockable_areas_unlocks_a_valid_unlocks_area_challenge() -> None:
    info = _area_info()
    valid = {"Nonskill": {"Guardians' Lair": True}}

    assert unlockable_areas(valid, {"100": True}, {}, info) == {"Guardians' Lair": True}


def test_unlockable_areas_needs_the_challenge_to_be_valid() -> None:
    assert unlockable_areas({}, {"100": True}, {}, _area_info()) == {}


def test_unlockable_areas_needs_the_unlocks_area_flag() -> None:
    info = _area_info(challenges={"Nonskill": {"Guardians' Lair": {}}})
    valid = {"Nonskill": {"Guardians' Lair": True}}

    assert unlockable_areas(valid, {"100": True}, {}, info) == {}


def test_unlockable_areas_needs_a_connecting_chunk_unlocked() -> None:
    valid = {"Nonskill": {"Guardians' Lair": True}}

    assert unlockable_areas(valid, {"999": True}, {}, _area_info()) == {}


def test_unlockable_areas_skips_an_area_already_unlocked() -> None:
    valid = {"Nonskill": {"Guardians' Lair": True}}
    chunks = {"100": True, "Guardians' Lair": True}

    assert unlockable_areas(valid, chunks, {}, _area_info()) == {}


def test_unlockable_areas_respects_a_disabling_manual_area() -> None:
    valid = {"Nonskill": {"Guardians' Lair": True}}

    assert (
        unlockable_areas(
            valid, {"100": True}, {}, _area_info(), manual_areas={"Guardians' Lair": False}
        )
        == {}
    )


def test_unlockable_areas_applies_the_skills_needed_gate() -> None:
    info = _area_info(
        challenges={
            "Nonskill": {"Guardians' Lair": {"UnlocksArea": True, "SkillsNeeded": {"Slayer": 75}}},
            "Slayer": {"Train it": {}},
        }
    )
    valid_without: dict[str, dict[str, Any]] = {"Nonskill": {"Guardians' Lair": True}}
    valid_with: dict[str, dict[str, Any]] = {
        "Nonskill": {"Guardians' Lair": True},
        "Slayer": {"Train it": 1},
    }

    assert unlockable_areas(valid_without, {"100": True}, {}, info) == {}
    assert unlockable_areas(valid_with, {"100": True}, {}, info) == {"Guardians' Lair": True}
    # A passive-skill floor covers the requirement even with no valid Slayer task.
    assert unlockable_areas(
        valid_without, {"100": True}, {}, info, passive_skill={"Slayer": 80}
    ) == {"Guardians' Lair": True}
    # ...but max_skill below the requirement still blocks it.
    assert unlockable_areas(valid_with, {"100": True}, {}, info, max_skill={"Slayer": 50}) == {}


def test_unlockable_areas_requires_the_linking_section_reachable() -> None:
    info = ChunkInfo(
        {
            "chunks": {
                "100": {"Sections": {"1": {"Connect": {"6727": True}}}},
                "6727": {"Name": "Guardians' Lair"},
            },
            "challenges": {"Nonskill": {"Guardians' Lair": {"UnlocksArea": True}}},
        }
    )
    valid = {"Nonskill": {"Guardians' Lair": True}}

    assert unlockable_areas(valid, {"100": True}, {}, info) == {}
    assert unlockable_areas(valid, {"100": True}, {"100": {"1": True}}, info) == {
        "Guardians' Lair": True
    }
