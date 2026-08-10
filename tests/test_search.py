"""Tests for world-wide fuzzy search."""

from __future__ import annotations

from typing import Any

import pytest

from fray_claude.chunkinfo import ChunkInfo
from fray_claude.pipeline import MapState, derive
from fray_claude.search import ItemSource, build_world_index, normalise, rank, search



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


def test_normalise_strips_challenge_markup() -> None:
    assert normalise("~|Ardougne Diary#Easy|~ Task 1") == "ardougne diary easy task 1"


def test_normalise_collapses_whitespace_and_lowercases() -> None:
    assert normalise("Rune   Platebody") == "rune platebody"


def test_rank_prefers_exact_over_prefix_over_substring() -> None:
    candidates = ["Whip", "Abyssal whip", "Abyssal whip mix"]

    assert rank("whip", candidates, limit=10) == ["Whip", "Abyssal whip", "Abyssal whip mix"]


def test_rank_tolerates_a_typo() -> None:
    candidates = ["Rune platebody", "Bronze platebody", "Coal"]

    assert rank("rune platebdy", candidates, limit=10)[0] == "Rune platebody"


def test_rank_excludes_unrelated_candidates() -> None:
    assert rank("abyssal whip", ["Coal", "Logs"], limit=10) == []


def test_rank_respects_the_limit() -> None:
    candidates = ["Log", "Logs", "Log pile", "Logging axe"]

    assert len(rank("log", candidates, limit=2)) == 2


def test_rank_empty_query_returns_nothing() -> None:
    assert rank("", ["Anything"], limit=10) == []


def test_build_world_index_covers_the_drop_route() -> None:
    info = _chunk_info(drops={"Goblin": {"Bones": {"1": "Always"}}})

    world = build_world_index(info)

    assert world.item_sources["Bones"][0].route == "drop"
    assert world.item_sources["Bones"][0].name == "Goblin"


def test_build_world_index_expands_a_drop_table() -> None:
    info = _chunk_info(
        drops={"Goblin": {"RareDropTable+": {"1": "1/128"}}},
        codeItems={"dropTables": {"RareDropTable+": {"Loot A": "1/2@1", "Loot B": "1/4@1"}}},
    )

    world = build_world_index(info)

    assert {s.name for s in world.item_sources["Loot A"]} == {"Goblin"}
    assert {s.name for s in world.item_sources["Loot B"]} == {"Goblin"}
    assert "RareDropTable+" not in world.item_sources


def test_build_world_index_covers_skill_items_route() -> None:
    # Abyssal whip is real-world only reachable this way - not in `drops` at
    # all, only `skillItems.Slayer` (verified against the real export).
    info = _chunk_info(skillItems={"Slayer": {"Abyssal demon": {"Abyssal whip": {"1": "1/512"}}}})

    world = build_world_index(info)

    assert world.item_sources["Abyssal whip"] == [ItemSource("Slayer", "Abyssal demon")]


def test_build_world_index_covers_the_shop_route() -> None:
    info = _chunk_info(shopItems={"General Store": {"Pot": True}})

    world = build_world_index(info)

    assert world.item_sources["Pot"][0].route == "shop"
    assert world.item_sources["Pot"][0].name == "General Store"


def test_build_world_index_covers_the_spawn_route_and_its_own_location() -> None:
    info = _chunk_info(chunks={"100": {"Spawn": {"Iron ore": True}}})

    world = build_world_index(info)

    source = world.item_sources["Iron ore"][0]
    assert source.route == "spawn"
    assert source.name == "100"


def test_build_world_index_covers_the_challenge_output_route() -> None:
    info = _chunk_info(challenges={"Smithing": {"Smelt a bar": {"Output": "Iron bar"}}})

    world = build_world_index(info)

    source = world.item_sources["Iron bar"][0]
    assert source.route == "task:Smithing"
    assert source.name == "Smelt a bar"


def test_build_world_index_walks_sectioned_and_unsectioned_chunks() -> None:
    info = _chunk_info(
        chunks={
            "100": {"Monster": {"Goblin": True}},
            "200": {"Sections": {"1": {"Monster": {"Goblin": True}}}},
        }
    )

    world = build_world_index(info)

    assert world.locations["Monster"]["Goblin"] == {"100", "200-1"}


def test_build_world_index_reads_chunk_names_preferring_nickname() -> None:
    info = _chunk_info(chunks={"100": {"Nickname": "Home", "Name": "Formal Name"}})

    world = build_world_index(info)

    assert world.chunk_names["100"] == "Home"


def test_build_world_index_flags_boss_monsters() -> None:
    info = _chunk_info(codeItems={"bossMonsters": {"General Graardor": True}})

    world = build_world_index(info)

    assert "General Graardor" in world.boss_monsters
    assert "Goblin" not in world.boss_monsters


def test_search_finds_an_item_with_no_known_location() -> None:
    # A drop/skillItems source whose monster never appears in `chunks` - a
    # real occurrence (137 of 1,000 in the actual export).
    info = _chunk_info(drops={"Quest Boss": {"Rare drop": {"1": "1/1000"}}})
    world = build_world_index(info)

    hits = search(world, "rare drop", types=["item"], limit=5)

    assert len(hits) == 1
    assert hits[0].detail["sources"][0]["locations"] == []
    assert hits[0].available is False


def test_search_marks_available_when_the_chunk_is_unlocked() -> None:
    info = _chunk_info(
        chunks={"100": {"Monster": {"Goblin": True}}},
        drops={"Goblin": {"Bones": {"1": "Always"}}},
    )
    world = build_world_index(info)
    state = _state(chunk_info=info)
    derived = derive(state, {"100": True})

    locked = search(world, "bones", types=["item"], limit=5)[0]
    unlocked_hit = search(
        world, "bones", types=["item"], unlocked={"100": True}, derived=derived, limit=5
    )[0]

    assert locked.available is False
    assert unlocked_hit.available is True


def test_search_restricts_to_the_requested_types() -> None:
    info = _chunk_info(
        chunks={"100": {"Monster": {"Whip seller": True}}},
        drops={"Whip seller": {"Whip": {"1": "Always"}}},
    )
    world = build_world_index(info)

    item_only = search(world, "whip", types=["item"], limit=10)
    monster_only = search(world, "whip", types=["monster"], limit=10)

    assert {hit.type for hit in item_only} == {"item"}
    assert {hit.type for hit in monster_only} == {"monster"}


def test_search_entity_hit_reports_locations_and_what_it_provides() -> None:
    info = _chunk_info(
        chunks={"100": {"Monster": {"Goblin": True}}},
        drops={"Goblin": {"Bones": {"1": "Always"}}},
    )
    world = build_world_index(info)

    hit = search(world, "goblin", types=["monster"], limit=5)[0]

    assert hit.detail["locations"] == [{"chunk_id": "100", "available": False}]
    assert hit.detail["provides"] == ["Bones"]
    assert hit.detail["boss"] is False


def test_search_task_hit_reports_category_and_validity() -> None:
    info = _chunk_info(challenges={"Nonskill": {"Do a thing": {}}})
    world = build_world_index(info)
    state = _state(chunk_info=info)
    derived = derive(state, {})

    hit = search(world, "do a thing", types=["task"], derived=derived, limit=5)[0]

    assert hit.detail["category"] == "Nonskill"
    assert hit.available is True


def test_search_respects_the_limit_across_types() -> None:
    info = _chunk_info(
        chunks={"100": {"Monster": {"Whip A": True}, "Object": {"Whip B": True}}},
        drops={"Whip A": {"Whip C": {"1": "Always"}}},
    )
    world = build_world_index(info)

    hits = search(world, "whip", limit=2)

    assert len(hits) == 2


def test_search_exact_name_match_suppresses_fuzzy_neighbours() -> None:
    info = _chunk_info(
        chunks={"100": {"Monster": {"Abyssal whipper": True}}},
        drops={
            "Abyssal demon": {
                "Abyssal whip": {"1": "1/512"},
                "Abyssal whip ornament kit": {"1": "1/1000"},
            }
        },
    )
    world = build_world_index(info)

    hits = search(world, "Abyssal whip", limit=10)

    assert [hit.name for hit in hits] == ["Abyssal whip"]


def test_search_exact_monster_name_match_suppresses_fuzzy_neighbours() -> None:
    info = _chunk_info(
        chunks={
            "100": {"Monster": {"Abyssal demon": True}},
            "200": {"Monster": {"Abyssal demon#Wilderness Slayer Cave": True}},
        }
    )
    world = build_world_index(info)

    hits = search(world, "Abyssal demon", types=["monster"], limit=10)

    assert [hit.name for hit in hits] == ["Abyssal demon"]


def test_search_exact_task_name_match_suppresses_fuzzy_neighbours() -> None:
    info = _chunk_info(
        challenges={
            "Agility": {
                "Access the ~|Dorgesh-Kaan Agility Course|~": {},
                "Access the ~|Dorgesh-Kaan Agility Course|~ (grapple route)": {},
            }
        }
    )
    world = build_world_index(info)

    hits = search(world, "Access the Dorgesh-Kaan Agility Course", types=["task"], limit=10)

    assert [hit.name for hit in hits] == ["Access the ~|Dorgesh-Kaan Agility Course|~"]


def test_search_exact_name_match_is_case_insensitive() -> None:
    info = _chunk_info(
        drops={
            "Abyssal demon": {
                "Abyssal whip": {"1": "1/512"},
                "Abyssal whip ornament kit": {"1": "1/1000"},
            }
        }
    )
    world = build_world_index(info)

    hits = search(world, "ABYSSAL WHIP", types=["item"], limit=10)

    assert [hit.name for hit in hits] == ["Abyssal whip"]


def test_search_empty_query_returns_nothing() -> None:
    info = _chunk_info(chunks={"100": {"Monster": {"Goblin": True}}})
    world = build_world_index(info)

    assert search(world, "", limit=10) == []


@pytest.mark.real_export
def test_abyssal_whip_resolves_through_skill_items_to_a_real_chunk(
    real_export: ChunkInfo,
) -> None:
    """Opt-in oracle: the exact trace this feature was built on - "Abyssal
    whip" is unreachable via `drops` at all (verified when this was
    written), only via `skillItems.Slayer` -> "Abyssal demon" -> chunk
    12108. A regression in any of the five item routes breaks this.
    """
    info = real_export
    world = build_world_index(info)

    sources = world.item_sources["Abyssal whip"]
    assert not any(s.route == "drop" for s in sources)
    slayer_sources = {s.name for s in sources if s.route == "Slayer"}
    assert "Abyssal demon" in slayer_sources
    assert "12108" in world.locations["Monster"]["Abyssal demon"]

    hits = search(world, "abyssal whip", types=["item"], limit=1)
    item_hit = hits[0]
    abyssal_demon_source = next(
        s for s in item_hit.detail["sources"] if s["name"] == "Abyssal demon"
    )
    assert any(loc["chunk_id"] == "12108" for loc in abyssal_demon_source["locations"])
