"""Tests for section connectivity (`findConnectedSections` + the live half of
`getAllChunkAreas`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from fray_claude.chunkinfo import ChunkInfo
from fray_claude.sections import expand_chunk_areas, unlocked_sections

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
    data = json.loads(Path(_REAL_CHUNKINFO).read_text(encoding="utf-8"))
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
