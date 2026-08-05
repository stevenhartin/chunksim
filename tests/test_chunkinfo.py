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
    "shopItems": {"General Store": {"Pot": True}},
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
    assert info.shop_items == DATA["shopItems"]
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
    assert info.shop_items == {}
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


def test_area_names_maps_a_region_to_the_place_it_is_part_of() -> None:
    """**A named area's location, and it is exact rather than a name match.**

    The export stores such a place twice: once under its name, holding the
    contents, and once as ordinary numbered chunks carrying `Name`. A numbered
    chunk is a region, so it has a square - which is what makes `Abyss`
    drawable at all.
    """
    info = ChunkInfo(
        {
            "chunks": {
                "6727": {"Name": "Grotesque Guardians' Lair", "Object": {"Ladder": 1}},
                "5022": {"Name": "Karuulm Slayer Dungeon"},
                "5023": {"Name": "Karuulm Slayer Dungeon"},
                "12850": {"Monster": {"Cow": 4}},
                "Grotesque Guardians' Lair": {"Monster": {"Dusk": 1}},
                "broken": [],
            }
        }
    )

    names = info.area_names()

    assert names["6727"] == "Grotesque Guardians' Lair"
    # Many-to-one: an area spans several regions, a region has one name.
    assert names["5022"] == names["5023"] == "Karuulm Slayer Dungeon"
    # A chunk with no `Name` is not in an area, and the name-keyed entry -
    # which holds the *contents* - is not a region and carries no `Name`.
    assert "12850" not in names
    assert "Grotesque Guardians' Lair" not in names
    # Tolerant of a wrongly-typed branch, like every other accessor here.
    assert "broken" not in names


def test_area_names_ignores_an_empty_or_wrongly_typed_name() -> None:
    info = ChunkInfo({"chunks": {"1": {"Name": ""}, "2": {"Name": 7}, "3": {"Name": "Ok"}}})

    assert info.area_names() == {"3": "Ok"}
