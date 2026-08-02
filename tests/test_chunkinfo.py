"""Tests for the typed chunkinfo accessor layer."""

from __future__ import annotations

from typing import Any

from fray_claude.chunkinfo import ChunkInfo

DATA: dict[str, Any] = {
    "chunks": {"3883": {"Nickname": "Lumbridge"}},
    "sections": {"12597": {"1": ["12341"]}},
    "sectionsLimits": {"14646-1 to 14902": {"Tasks": {}}},
    "challenges": {"Cooking": {"Cook a shrimp": {"Level": 1}}},
    "drops": {"Chef": {"Chef hat": {"1": "1/128"}}},
    "codeItems": {"boostItems": {"Cooking": {}}},
    "rollingChunks": {"bank": ["4912"]},
    "walkableChunks": ["3883", "3884"],
    "walkableChunksF2P": ["3883"],
}


def test_accessors_return_the_matching_branch() -> None:
    info = ChunkInfo(DATA)

    assert info.chunks == DATA["chunks"]
    assert info.sections == DATA["sections"]
    assert info.sections_limits == DATA["sectionsLimits"]
    assert info.challenges == DATA["challenges"]
    assert info.drops == DATA["drops"]
    assert info.code_items == DATA["codeItems"]
    assert info.rolling_chunks == DATA["rollingChunks"]
    assert info.walkable_chunks == ["3883", "3884"]
    assert info.walkable_chunks_f2p == ["3883"]


def test_chunk_returns_a_single_entry() -> None:
    info = ChunkInfo(DATA)

    assert info.chunk("3883") == {"Nickname": "Lumbridge"}


def test_chunk_tolerates_an_unknown_id() -> None:
    info = ChunkInfo(DATA)

    assert info.chunk("999999") == {}


def test_accessors_tolerate_an_empty_export() -> None:
    info = ChunkInfo({})

    assert info.chunks == {}
    assert info.sections == {}
    assert info.sections_limits == {}
    assert info.challenges == {}
    assert info.drops == {}
    assert info.code_items == {}
    assert info.rolling_chunks == {}
    assert info.walkable_chunks == []
    assert info.walkable_chunks_f2p == []


def test_accessors_tolerate_branches_of_the_wrong_type() -> None:
    info = ChunkInfo({"chunks": "unexpected", "walkableChunks": {"not": "a list"}})

    assert info.chunks == {}
    assert info.walkable_chunks == []


def test_walkable_chunks_drops_non_string_elements() -> None:
    info = ChunkInfo({"walkableChunks": ["3883", 42, None]})

    assert info.walkable_chunks == ["3883"]
