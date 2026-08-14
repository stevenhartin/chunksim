"""Tests for the source-availability index (`gatherChunksInfo`)."""

from __future__ import annotations

from typing import Any

import pytest

from chunksim.model.chunkinfo import ChunkInfo
from chunksim.derive.sources import (
    CATEGORIES,
    apply_item_task_unlocks,
    gather_chunks_info,
    task_unlock_pairs,
)


def _chunk_info(**data: Any) -> ChunkInfo:
    return ChunkInfo(data)


def test_a_monster_present_at_a_chunk_yields_its_always_drops_as_primary() -> None:
    info = _chunk_info(
        chunks={"100": {"Monster": {"Goblin": True}}},
        drops={"Goblin": {"Bones": {"1": "Always"}}},
    )

    index = gather_chunks_info({"100": True}, {}, info, rules={})

    assert index.monsters == {"Goblin": {"100": True}}
    assert index.items["Bones"] == {"Goblin": "primary-drop"}


def test_a_low_rate_drop_is_classified_secondary_by_default() -> None:
    info = _chunk_info(
        chunks={"100": {"Monster": {"Goblin": True}}},
        drops={"Goblin": {"Coins": {"1": "1/16"}}},
    )

    # `Rare Drop Amount` defaults to "0", i.e. an infinite threshold that
    # admits no rate-based drop at all; this test is about classification, so
    # give it a threshold the 1/16 rate clears.
    index = gather_chunks_info({"100": True}, {}, info, rules={"Rare Drop Amount": "100"})

    assert index.items["Coins"] == {"Goblin": "secondary-drop"}


def test_rate_below_the_rare_drop_threshold_is_excluded() -> None:
    info = _chunk_info(
        chunks={"100": {"Monster": {"Goblin": True}}},
        drops={"Goblin": {"Rare gem": {"1": "1/2000"}}},
    )

    index = gather_chunks_info({"100": True}, {}, info, rules={"Rare Drop Amount": "1000"})

    assert "Rare gem" not in index.items


def test_rare_drop_rule_bypasses_the_threshold() -> None:
    info = _chunk_info(
        chunks={"100": {"Monster": {"Goblin": True}}},
        drops={"Goblin": {"Rare gem": {"1": "1/2000"}}},
    )

    index = gather_chunks_info(
        {"100": True}, {}, info, rules={"Rare Drop Amount": "1000", "Rare Drop": True}
    )

    assert "Rare gem" in index.items


def test_a_backlogged_monster_is_excluded_entirely() -> None:
    info = _chunk_info(
        chunks={"100": {"Monster": {"Goblin": True}}},
        drops={"Goblin": {"Bones": {"1": "Always"}}},
    )

    index = gather_chunks_info(
        {"100": True}, {}, info, rules={}, backlogged_sources={"monsters": {"Goblin": True}}
    )

    assert index.monsters == {}
    assert index.items == {}


def test_skiller_rule_suppresses_drops_but_not_monster_presence() -> None:
    info = _chunk_info(
        chunks={"100": {"Monster": {"Goblin": True}}},
        drops={"Goblin": {"Bones": {"1": "Always"}}},
    )

    index = gather_chunks_info({"100": True}, {}, info, rules={"Skiller": True})

    assert index.monsters == {"Goblin": {"100": True}}
    assert index.items == {}


def test_objects_and_npcs_are_recorded_with_their_chunk_as_source() -> None:
    info = _chunk_info(chunks={"100": {"Object": {"Anvil": True}, "NPC": {"Banker": True}}})

    index = gather_chunks_info({"100": True}, {}, info, rules={})

    assert index.objects == {"Anvil": {"100": True}}
    assert index.npcs == {"Banker": {"100": True}}


def test_backlogged_objects_and_npcs_are_excluded() -> None:
    info = _chunk_info(chunks={"100": {"Object": {"Anvil": True}, "NPC": {"Banker": True}}})

    index = gather_chunks_info(
        {"100": True},
        {},
        info,
        rules={},
        backlogged_sources={"objects": {"Anvil": True}, "npcs": {"Banker": True}},
    )

    assert index.objects == {}
    assert index.npcs == {}


def test_spawn_tag_depends_on_the_primary_spawns_rule() -> None:
    info = _chunk_info(chunks={"100": {"Spawn": {"Iron ore": True}}})

    default = gather_chunks_info({"100": True}, {}, info, rules={})
    primary = gather_chunks_info({"100": True}, {}, info, rules={"Primary Spawns": True})

    assert default.items["Iron ore"] == {"100": "secondary-spawn"}
    assert primary.items["Iron ore"] == {"100": "primary-spawn"}


def test_shop_items_require_the_minigame_rule_for_a_minigame_shop() -> None:
    info = _chunk_info(
        chunks={"100": {"Shop": {"Arena Store": True}}},
        shopItems={"Arena Store": {"Ticket": True}},
        codeItems={"minigameShops": {"Arena Store": True}},
    )

    without_rule = gather_chunks_info({"100": True}, {}, info, rules={})
    with_rule = gather_chunks_info({"100": True}, {}, info, rules={"Minigame": True})

    assert "Ticket" not in without_rule.items
    assert with_rule.items["Ticket"] == {"Arena Store": "shop"}
    assert without_rule.shops == {"Arena Store": {"100": True}}


def test_sectioned_monster_requires_its_section_reachable() -> None:
    info = _chunk_info(
        chunks={"100": {"Sections": {"1": {"Monster": {"Goblin": True}}}}},
        drops={"Goblin": {"Bones": {"1": "Always"}}},
    )

    unreachable = gather_chunks_info({"100": True}, {}, info, rules={})
    reachable = gather_chunks_info({"100": True}, {"100": {"1": True}}, info, rules={})

    assert unreachable.monsters == {}
    assert reachable.monsters == {"Goblin": {"100-1": True}}


def test_puro_puro_is_excluded_unless_its_rule_is_on() -> None:
    info = _chunk_info(chunks={"Puro-Puro": {"NPC": {"Impling": True}}})

    off = gather_chunks_info({"Puro-Puro": True}, {}, info, rules={})
    on = gather_chunks_info({"Puro-Puro": True}, {}, info, rules={"Puro-Puro": True})

    assert off.npcs == {}
    assert on.npcs == {"Impling": {"Puro-Puro": True}}


def test_manual_equipment_is_tagged_secondary_drop() -> None:
    index = gather_chunks_info({}, {}, _chunk_info(), rules={}, manual_equipment={"Whip": True})

    assert index.items["Whip"] == {"Manually Added Equipment": "secondary-drop"}


def test_manual_monsters_populate_items_monsters_npcs_objects_and_shops() -> None:
    info = _chunk_info(shopItems={"Rare Shop": {"Gem": True}})
    manual = {
        "Items": {"Amulet": True, "Charm": False},
        "Monsters": {"Cow": True},
        "NPCs": {"Wizard": True},
        "Objects": {"Chest": True},
        "Shops": {"Rare Shop": True},
    }

    index = gather_chunks_info({}, {}, info, rules={}, manual_monsters=manual)

    assert index.items["Amulet"] == {"Manually Added*": "primary-Nonskill"}
    assert index.items["Charm"] == {"Manually Added*": "secondary-Nonskill"}
    assert index.monsters == {"Cow": {"Manually Added*": True}}
    assert index.npcs == {"Wizard": {"Manually Added*": True}}
    assert index.objects == {"Chest": {"Manually Added*": True}}
    assert index.shops == {"Rare Shop": {"Manually Added*": True}}
    assert index.items["Gem"] == {"Rare Shop": "shop"}


def test_rdt_family_drop_is_a_single_item_when_rdt_is_off() -> None:
    info = _chunk_info(
        chunks={"100": {"Monster": {"Goblin": True}}},
        drops={"Goblin": {"RareDropTable+": {"1": "1/128"}}},
        codeItems={"dropTables": {"RareDropTable+": {"Loot A": "1/2@1"}}},
    )

    # A threshold the 1/128 rate clears - the default amount of "0" is an
    # infinite threshold and would reject the drop before RDT even matters.
    index = gather_chunks_info({"100": True}, {}, info, rules={"Rare Drop Amount": "1000"})

    assert "RareDropTable+" in index.items
    assert "Loot A" not in index.items


def test_rdt_family_drop_expands_to_its_table_when_rdt_is_on() -> None:
    info = _chunk_info(
        chunks={"100": {"Monster": {"Goblin": True}}},
        drops={"Goblin": {"RareDropTable+": {"1": "1/128"}}},
        codeItems={"dropTables": {"RareDropTable+": {"Loot A": "1/2@1"}}},
    )

    index = gather_chunks_info(
        {"100": True}, {}, info, rules={"RDT": True, "Rare Drop Amount": "1000"}
    )

    assert "Loot A" in index.items
    assert "RareDropTable+" not in index.items


def test_key_item_bosses_rule_is_not_supported() -> None:
    with pytest.raises(NotImplementedError):
        gather_chunks_info({}, {}, _chunk_info(), rules={"KeyItem Bosses": True})


def test_droprate_override_uses_the_new_rate_when_its_chunks_are_reachable() -> None:
    info = _chunk_info(
        chunks={"100": {"Monster": {"Goblin": True}}},
        drops={"Goblin": {"Gem": {"1": "1/2000"}}},
        codeItems={
            "droprateOverrides": {
                "Goblin": {
                    "Gem": [
                        {"Chunks": ["100-1"], "NewRate": {"1": "Always"}, "OldRate": {"1": "1/2000"}}
                    ]
                }
            }
        },
    )

    index = gather_chunks_info(
        {"100": True}, {"100": {"1": True}}, info, rules={"Rare Drop Amount": "1000"}
    )

    assert index.items["Gem"] == {"Goblin": "primary-drop"}


def test_droprate_override_falls_back_to_the_old_rate_when_unreachable() -> None:
    info = _chunk_info(
        chunks={"100": {"Monster": {"Goblin": True}}},
        drops={"Goblin": {"Gem": {"1": "1/2000"}}},
        codeItems={
            "droprateOverrides": {
                "Goblin": {
                    "Gem": [
                        {"Chunks": ["100-1"], "NewRate": {"1": "Always"}, "OldRate": {"1": "1/2000"}}
                    ]
                }
            }
        },
    )

    index = gather_chunks_info({"100": True}, {}, info, rules={"Rare Drop Amount": "1000"})

    assert "Gem" not in index.items


def test_gather_chunks_info_tolerates_an_empty_export() -> None:
    index = gather_chunks_info({"100": True}, {}, _chunk_info(), rules={})

    assert index.as_dict() == {
        "items": {},
        "objects": {},
        "monsters": {},
        "npcs": {},
        "shops": {},
        "drop_rates": {},
        "drop_quantities": {},
    }


def test_category_returns_the_matching_branch() -> None:
    info = _chunk_info(chunks={"100": {"Shop": {"General Store": True}}})

    index = gather_chunks_info({"100": True}, {}, info, rules={})

    assert index.category("shops") == {"General Store": {"100": True}}


def test_category_rejects_an_unknown_name() -> None:
    index = gather_chunks_info({}, {}, _chunk_info(), rules={})

    with pytest.raises(ValueError, match="unknown source category"):
        index.category("bogus")


def test_categories_matches_the_source_index_fields() -> None:
    assert CATEGORIES == ("items", "objects", "monsters", "npcs", "shops")


def test_item_task_unlocks_removes_a_locked_monster_source() -> None:
    """`taskUnlocks['Items']`'s `"<item>^<monster>"` keys are how upstream
    keeps a merged drop table's location-specific half out:
    `skillItems.Slayer['Abyssal demon']` carries the Catacombs of Kourend
    drops alongside the Slayer Tower ones, and `Ancient shard^Abyssal demon`
    gates them on a challenge needing the Catacombs chunk.
    """
    items: dict[str, dict[str, str]] = {
        "Ancient shard": {"Abyssal demon": "secondary-drop"},
        "Abyssal whip": {"Abyssal demon": "secondary-drop"},
    }
    unlocks = {"Items": {"Ancient shard^Abyssal demon": [{"Catacombs drops": "Nonskill"}]}}

    apply_item_task_unlocks(items, unlocks, {})

    assert "Ancient shard" not in items
    assert items["Abyssal whip"] == {"Abyssal demon": "secondary-drop"}


def test_item_task_unlocks_keeps_the_source_once_the_task_is_valid() -> None:
    items: dict[str, dict[str, str]] = {"Ancient shard": {"Abyssal demon": "secondary-drop"}}
    unlocks = {"Items": {"Ancient shard^Abyssal demon": [{"Catacombs drops": "Nonskill"}]}}

    apply_item_task_unlocks(items, unlocks, {"Nonskill": {"Catacombs drops": True}})

    assert items["Ancient shard"] == {"Abyssal demon": "secondary-drop"}


def test_item_task_unlocks_also_matches_a_slay_challenge_source() -> None:
    """The challenge-`Output` route keys its sources by challenge name, so
    upstream matches `source.includes('Slay')` plus the monster name."""
    items: dict[str, dict[str, str]] = {
        "Ancient shard": {"Slay an ~|abyssal demon|~": "primary-Slayer"}
    }
    unlocks = {"Items": {"Ancient shard^Abyssal demon": [{"Catacombs drops": "Nonskill"}]}}

    apply_item_task_unlocks(items, unlocks, {})

    assert "Ancient shard" not in items


def test_item_task_unlocks_is_satisfied_by_any_one_task() -> None:
    """Unlike the entity branches' all-of semantics, this list needs only one
    entry valid (upstream filters for `length > 0`)."""
    items: dict[str, dict[str, str]] = {"Brimstone key": {"Abyssal demon": "secondary-drop"}}
    unlocks = {
        "Items": {
            "Brimstone key^Abyssal demon": [
                {"Receive an assignment from Konar": "Slayer"},
                {"Some other route": "Nonskill"},
            ]
        }
    }

    apply_item_task_unlocks(items, unlocks, {"Nonskill": {"Some other route": True}})

    assert items["Brimstone key"] == {"Abyssal demon": "secondary-drop"}


def test_item_task_unlocks_ignores_a_key_without_a_monster() -> None:
    items: dict[str, dict[str, str]] = {"Climbing boots": {"Shop": "shop"}}

    apply_item_task_unlocks(items, {"Items": {"Climbing boots": [{"A task": "Nonskill"}]}}, {})

    assert items["Climbing boots"] == {"Shop": "shop"}


def test_task_unlock_pairs_finds_a_gate_at_any_depth() -> None:
    """**The set has to be a superset or the loop stops too early.**

    The entity branches nest location -> list -> `{task: skill}`, `Items` is
    flat, and both readers skip a non-`str` skill. A walk that emits every
    `str`-valued entry catches all of it without knowing a branch name.
    """
    info = ChunkInfo({
        "taskUnlocks": {
            "Shops": {"White Knight Armoury": {"100": [{"Wanted!": "Quest"}]}},
            "Items": {"Brimstone key^Abyssal demon": [{"Konar task": "Nonskill"}]},
            "Monsters": {"Lava dragon": {"100-1": [{"F2P Only": "Extra"}]}},
        }
    })

    assert task_unlock_pairs(info) == frozenset({
        ("Quest", "Wanted!"),
        ("Nonskill", "Konar task"),
        ("Extra", "F2P Only"),
    })


def test_task_unlock_pairs_ignores_an_entry_whose_skill_is_not_a_name() -> None:
    """Matching both readers, which `continue` past a non-`str` skill rather
    than looking it up - so a pair that can never be consulted is not one."""
    info = ChunkInfo({"taskUnlocks": {"Shops": {"Shop": {"100": [{"Task": ["Quest"]}]}}}})

    assert task_unlock_pairs(info) == frozenset()


def test_task_unlock_pairs_is_empty_when_the_export_gates_nothing() -> None:
    """Which is a real answer, not a degenerate one: with no gate, validity
    never reaches `gather_chunks_info`, so one settled pass is the whole
    derivation - see `pipeline.derive`'s exit test."""
    assert task_unlock_pairs(ChunkInfo({})) == frozenset()


@pytest.mark.real_export
def test_every_real_gate_is_in_the_pair_set(real_export: ChunkInfo) -> None:
    """The completeness property, against the export itself.

    Walks `taskUnlocks` the way `_task_unlocked` and `_any_task_valid` do -
    down to the `{task: skill}` dicts they read - and asserts each pair is in
    the set. This is the test that fails if a future export nests a gate
    somewhere the walk does not reach, which is the failure the branch-name
    version of this would have made silent.
    """
    pairs = task_unlock_pairs(real_export)
    seen = 0
    for branch in (real_export.data.get("taskUnlocks") or {}).values():
        for entry in (branch or {}).values():
            lists = entry.values() if isinstance(entry, dict) else [entry]
            for required in lists:
                for item in required if isinstance(required, list) else []:
                    for task, skill in (item or {}).items() if isinstance(item, dict) else []:
                        if isinstance(skill, str):
                            assert (skill, task) in pairs, f"{skill}/{task} missing"
                            seen += 1
    assert seen > 100, "the export should carry hundreds of gate references"


def test_an_unconditional_drop_keeps_its_rate_as_written() -> None:
    """`dropRatesGlobal` keeps a rate with no `/` verbatim - upstream's
    `split('/').length <= 1 ? raw : findFraction(...)` (worker.js:779).

    Running `Always` through `find_fraction` gives the string `"NaN"`, which
    is what 189 of the second cached map's 3,402 rates read before this. It
    shows in `chunksim sources`, and these rates are pasted into the task
    names the `Every Drop` rule synthesises, so a wrong one becomes a wrong
    title.
    """
    info = _chunk_info(
        chunks={"100": {"Monster": {"Goblin": True}}},
        drops={"Goblin": {"Bones": {"1": "Always"}, "Coins": {"1": "1/16"}}},
    )

    index = gather_chunks_info({"100": True}, {}, info, rules={"Rare Drop Amount": "100"})

    assert index.drop_rates["Goblin"]["Bones"] == "Always"
    assert index.drop_rates["Goblin"]["Coins"] == "1/16"


def test_a_drop_table_rate_is_the_two_rates_multiplied() -> None:
    """The table branch has no raw fallback: it multiplies the monster's rate
    by the table entry's and formats the product (worker.js:741). A `1/2`
    monster rate into a `1/4` table row is `1/8`."""
    info = _chunk_info(
        chunks={"100": {"Monster": {"Goblin": True}}},
        drops={"Goblin": {"HerbDropTable": {"1": "1/2"}}},
        codeItems={"dropTables": {"HerbDropTable": {"Grimy guam leaf": "1/4@1"}}},
    )

    index = gather_chunks_info({"100": True}, {}, info, rules={"Rare Drop Amount": "100"})

    assert index.drop_rates["Goblin"]["Grimy guam leaf"] == "1/8"


def test_an_unconditional_drop_table_rate_stays_unrepresentable() -> None:
    """`Always` into a table is `parseFloat('Always') * rate` upstream, i.e.
    `NaN`, and `findFraction(NaN)` is the string `"NaN"`. Kept rather than
    tidied: the raw-string fallback belongs to the single-drop branch alone,
    and inventing one here would be a rate upstream never shows.
    """
    info = _chunk_info(
        chunks={"100": {"Monster": {"Goblin": True}}},
        drops={"Goblin": {"HerbDropTable": {"1": "Always"}}},
        codeItems={"dropTables": {"HerbDropTable": {"Grimy guam leaf": "1/4@1"}}},
    )

    index = gather_chunks_info({"100": True}, {}, info, rules={"Rare Drop Amount": "100"})

    assert index.drop_rates["Goblin"]["Grimy guam leaf"] == "NaN"
