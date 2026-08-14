"""Tests for the challenges upstream builds at runtime."""

from __future__ import annotations

from typing import Any

import pytest

from chunksim.derive.injected import (
    SynthesisInputs,
    forced_valid_from,
    injected_challenges,
    synthesised_challenges,
)
from chunksim.derive.pipeline import Derived
from chunksim.model.chunkinfo import ChunkInfo

_QUEST_CAPE = "Buy the quest point cape*"
_MAX_CAPE = "Buy the ~|Max cape|~"


def _info(**data: Any) -> ChunkInfo:
    return ChunkInfo(data)


def _quests() -> ChunkInfo:
    return _info(
        challenges={
            "Quest": {
                "~|Cook's Assistant|~ 1": {"QuestPoints": 1},
                "~|Dragon Slayer I|~ 1": {"QuestPoints": 2},
                "~|Not a quest|~": {},
            }
        }
    )


def test_the_quest_cape_needs_only_its_chunk() -> None:
    """No rule guards it - upstream gates the quest point cape on holding
    12338 and nothing else, which is why both cached maps were missing it."""
    definitions = injected_challenges(_quests(), {"12338": "12338"}, {})

    assert list(definitions) == ["Nonskill"]
    assert list(definitions["Nonskill"]) == [_QUEST_CAPE]


def test_each_cape_answers_only_to_its_own_chunk() -> None:
    """The two are independent: holding Mac's hut says nothing about the Wise
    Old Man's house, and a map holding neither gets an empty overlay."""
    mac_only = injected_challenges(_quests(), {"11063": "11063"}, {"Skillcape": True})

    assert list(mac_only) == ["Extra"]
    assert list(mac_only["Extra"]) == [_MAX_CAPE]
    assert injected_challenges(_quests(), {}, {"Skillcape": True}) == {}


def test_the_max_cape_needs_the_rule_and_the_chunk() -> None:
    held = {"11063": "11063"}

    assert _MAX_CAPE in injected_challenges(_quests(), held, {"Skillcape": True})["Extra"]
    assert injected_challenges(_quests(), held, {"Skillcape": False}) == {}
    assert injected_challenges(_quests(), {}, {"Skillcape": True}) == {}


def test_the_quest_cape_bar_is_the_export_summed() -> None:
    """`QuestPointsNeeded` is computed, not constant: upstream totals every
    `QuestPoints` in the export, so adding a quest raises the bar. A `Quest`
    entry carrying none contributes nothing rather than raising."""
    definitions = injected_challenges(_quests(), {"12338": "12338"}, {})

    assert definitions["Nonskill"][_QUEST_CAPE]["QuestPointsNeeded"] == 3


def test_membership_counts_whatever_the_chunk_maps_to() -> None:
    """Upstream tests the chunk list with `hasOwnProperty`, and this
    project's decoded `unlocked` maps an id to itself rather than to `True`."""
    assert injected_challenges(_quests(), {"12338": False}, {})["Nonskill"]


def test_the_overlay_leaves_the_original_alone() -> None:
    base = _info(challenges={"Nonskill": {"Something": {"Level": 1}}}, chunks={"1": {}})

    overlaid = base.with_challenges({"Nonskill": {"New": {"Level": 2}}})

    assert set(overlaid.challenges["Nonskill"]) == {"Something", "New"}
    assert set(base.challenges["Nonskill"]) == {"Something"}
    # Everything else is the same data, not a copy of it.
    assert overlaid.chunks is base.chunks


def test_an_empty_overlay_is_the_same_object() -> None:
    base = _info(challenges={"Nonskill": {}})

    assert base.with_challenges({}) is base


def test_derived_carries_no_injections_by_default() -> None:
    """`Derived.injected` has to default, or every test and every cached
    derivation built before it would need rewriting."""
    assert "injected" in Derived.__dataclass_fields__


@pytest.mark.real_cache
def test_the_quest_cape_is_reported_unjudgeable_rather_than_valid(
    real_derived: Derived,
) -> None:
    """The oracle regression this shape exists to prevent.

    Forcing the injected cape valid - which is what upstream's own `valids`
    seeding looks like in isolation - made `Quest point cape (t)` a reachable
    item, and that made `Perform the Quest point cape emote` an active
    Lumbridge Elite diary task on a map where upstream lists neither. The
    definition is overlaid so the challenge exists; its `QuestPointsNeeded`
    gate is unported, so it lands in `unsupported` and seeds nothing.
    """
    assert real_derived.injected == {
        "Nonskill": {_QUEST_CAPE: real_derived.injected["Nonskill"][_QUEST_CAPE]}
    }
    assert f"Nonskill/{_QUEST_CAPE}" in real_derived.challenges.unsupported
    assert _QUEST_CAPE not in real_derived.challenges.valid.get("Nonskill", {})
    assert "Quest point cape (t)" not in real_derived.challenges.available_items


def test_all_shops_names_a_task_per_shop_and_item() -> None:
    """One item sold in two shops is two tasks - the point of the rule."""
    built = synthesised_challenges(
        _info(),
        SynthesisInputs(items={"Raw beef": {"Food Store": "shop", "Kenelme's Wares": "shop"}}), {"All Shops": True}
    )

    assert set(built["Extra"]) == {
        "Food Store: ~|Raw beef|~",
        "Kenelme's Wares: ~|Raw beef|~",
    }
    assert built["Extra"]["Food Store: ~|Raw beef|~"] == {
        "Category": ["All Shops"],
        "Items": ["Raw beef"],
        "ItemsDetails": ["Raw beef"],
        "Label": "All Shops",
        "Permanent": False,
    }


def test_only_an_exact_shop_tag_counts() -> None:
    """Upstream tests the tag for equality, not membership: an item that
    merely passes through a shop carries a compound tag and is not stock."""
    built = synthesised_challenges(
        _info(),
        SynthesisInputs(
            items={"Raw beef": {"Food Store": "shop", "Some route": "primary-Cooking-shop"}}
        ),
        {"All Shops": True},
    )

    assert set(built["Extra"]) == {"Food Store: ~|Raw beef|~"}


def test_a_marked_index_entry_is_skipped_whole() -> None:
    assert synthesised_challenges(_info(), SynthesisInputs(items={"^^placeholder": {"Shop": "shop"}}), {"All Shops": True}) == {}


def test_the_secondary_marker_leaves_the_name_but_stays_in_items() -> None:
    """`*` marks a secondary ingredient. It has no business in a task title,
    but `_compile_items` reads it, so `Items` keeps it."""
    built = synthesised_challenges(_info(), SynthesisInputs(items={"Feather*": {"Shop": "shop"}}), {"All Shops": True})

    assert list(built["Extra"]) == ["Shop: ~|Feather|~"]
    assert built["Extra"]["Shop: ~|Feather|~"]["Items"] == ["Feather*"]


def test_a_marked_up_shop_name_is_unwrapped_for_the_title() -> None:
    built = synthesised_challenges(
        _info(),
        SynthesisInputs(items={"Bronze axe": {"~|Bob's Brilliant Axes|~": "shop"}}), {"All Shops": True}
    )

    assert list(built["Extra"]) == ["Bob's Brilliant Axes: ~|Bronze axe|~"]


def test_nothing_is_built_while_the_rule_is_off() -> None:
    assert synthesised_challenges(_info(), SynthesisInputs(items={"Raw beef": {"Food Store": "shop"}}), {}) == {}
    assert synthesised_challenges(_info(), SynthesisInputs(items={"Raw beef": {"Food Store": "shop"}}), {"All Shops": False}) == {}


@pytest.mark.real_cache
def test_all_shops_settles_and_fills_the_panel(
    real_payload: dict[str, Any],
    real_export: ChunkInfo,
    real_tasks_map: dict[str, str],
) -> None:
    """The loop has to converge with the rule on, which is the thing a
    per-pass synthesis can get wrong: the challenges are built from the item
    index, so a set that never settles would raise `ConvergenceError`.

    They are also the whole content of an `All Shops` panel group, which is
    what `Derived.injected` exists to let a caller render.
    """
    import copy

    from chunksim.derive.pipeline import derive, load_map_state

    payload = copy.deepcopy(real_payload)
    payload["rules"]["All Shops"] = True
    state, unlocked = load_map_state(payload, real_export, real_tasks_map)

    derived = derive(state, unlocked)
    shops = derived.injected["Extra"]

    assert shops, "the oracle map reaches no shop at all"
    assert set(shops) <= set(derived.challenges.valid["Extra"])
    groups = {group.name: group for group in derived.other_tasks.categories["Extra"].groups}
    assert len(groups["All Shops"].active) == len(shops)


def _nest_world() -> ChunkInfo:
    return _info(
        challenges={"Nonskill": {"Bird nest (egg) loot": {"Level": 1}}},
        skillItems={
            "Nonskill": {
                "Bird nest (egg) loot": {
                    "Bird nest (empty)": {"1": "Always"},
                    "Bird's egg#Blue": {"": "1/3"},
                }
            }
        },
    )


def test_a_reachable_nest_becomes_one_task_per_loot_row() -> None:
    """The rate goes into the name as the export stores it, and an empty
    quantity reads as `N/A` - upstream's `(quantity || 'N/A')`."""
    built = synthesised_challenges(
        _nest_world(), SynthesisInputs(items={"Bird nest (egg)": {}}), {"All Droptables Nest": True}
    )

    assert set(built["Extra"]) == {
        "Bird nest (egg): ~|Bird nest (empty)|~ (1) (Always)",
        "Bird nest (egg): ~|Bird's egg#Blue|~ (N/A) (1/3)",
    }


def test_a_nest_task_names_its_nest_as_an_object() -> None:
    """`Monsters: ['<nest>-object']` is a suffix no monster index carries,
    which is exactly why these have to be forced valid rather than judged."""
    built = synthesised_challenges(
        _nest_world(), SynthesisInputs(items={"Bird nest (egg)": {}}), {"All Droptables Nest": True}
    )
    entry = built["Extra"]["Bird nest (egg): ~|Bird nest (empty)|~ (1) (Always)"]

    assert entry["Monsters"] == ["Bird nest (egg)-object"]
    assert entry["Category"] == ["All Droptables"]
    assert entry["Items"] == ["Bird nest (empty)"]


def test_a_plus_family_nest_keeps_its_marker_out_of_the_title() -> None:
    """`[+]` is stripped from the task name and from nothing else - the loot
    lookup uses the index key exactly as it stands, which is why a nest whose
    key carries a marker its loot table does not simply finds nothing. No
    export nest carries one today; upstream still writes the strip.
    """
    world = _info(
        challenges={"Nonskill": {"Bird nest (egg)[+] loot": {"Level": 1}}},
        skillItems={"Nonskill": {"Bird nest (egg)[+] loot": {"Acorn": {"1": "1/2"}}}},
    )

    built = synthesised_challenges(
        world, SynthesisInputs(items={"Bird nest (egg)[+]": {}}), {"All Droptables Nest": True}
    )

    assert list(built["Extra"]) == ["Bird nest (egg): ~|Acorn|~ (1) (1/2)"]


def test_a_nest_with_no_loot_challenge_is_skipped() -> None:
    """Both halves have to exist: upstream reads the loot *table* and the
    loot *challenge*, and the second is what carries `Not F2P`."""
    world = _info(skillItems={"Nonskill": {"Bird nest (egg) loot": {"Acorn": {"1": "1/2"}}}})

    assert synthesised_challenges(
        world, SynthesisInputs(items={"Bird nest (egg)": {}}), {"All Droptables Nest": True}
    ) == {}


def test_an_f2p_map_loses_a_members_nest_whole() -> None:
    world = _info(
        challenges={"Nonskill": {"Bird nest (egg) loot": {"Level": 1, "Not F2P": True}}},
        skillItems={"Nonskill": {"Bird nest (egg) loot": {"Acorn": {"1": "1/2"}}}},
    )
    items: dict[str, dict[str, str]] = {"Bird nest (egg)": {}}

    assert synthesised_challenges(world, SynthesisInputs(items=items), {"All Droptables Nest": True})
    assert synthesised_challenges(world, SynthesisInputs(items=items), {"All Droptables Nest": True, "F2P": True}) == {}


def test_forced_valid_values_are_the_labels() -> None:
    """Upstream stores the `Label` in `valids`, and `other_tasks` groups an
    `Extra` entry by exactly that."""
    assert forced_valid_from({"Extra": {"A task": {"Label": "All Shops"}}}) == {
        "Extra": {"A task": "All Shops"}
    }


def _monster_world(**over: Any) -> ChunkInfo:
    return _info(
        challenges={
            "Slayer": {
                "Slay ~|Cave crawler|~": {"Output": "Cave crawler", "Level": 10},
                "Slay ~|cave crawler|~ alt": {"Output": "Cave crawler", "Level": 10},
            }
        },
        slayerMonsters={"Cave crawler": 10, "Abyssal demon": 85},
        codeItems={"bossMonsters": {"Zulrah": True}},
        **over,
    )


def _kill_x(**over: Any) -> dict[str, dict[str, Any]]:
    given = SynthesisInputs(
        items={},
        monsters={"Rat": True, "Cave crawler": True, "Abyssal demon": True, "Zulrah": True},
        **over,
    )
    return synthesised_challenges(_monster_world(), given, {"Kill X": True}).get("Extra", {})


def test_kill_x_names_a_task_per_reachable_monster() -> None:
    """A monster with no Slayer requirement always counts; one with a
    requirement needs Slayer trainable or a passive floor that covers it.
    Bosses are a separate rule, off here."""
    built = _kill_x()

    assert set(built) == {"Kill X ~|Rat|~"}


def test_a_trainable_slayer_brings_its_monsters_in() -> None:
    built = _kill_x(slayer_trainable=True)

    assert set(built) == {"Kill X ~|Rat|~", "Kill X ~|Cave crawler|~", "Kill X ~|Abyssal demon|~"}


def test_a_slayer_lock_caps_which_monsters_count() -> None:
    """The assignment lock stops Slayer at its level, so the level-85 monster
    goes and the level-10 one stays."""
    built = _kill_x(slayer_trainable=True, slayer_cap=40)

    assert set(built) == {"Kill X ~|Rat|~", "Kill X ~|Cave crawler|~"}


def test_a_boost_lifts_the_cap() -> None:
    built = _kill_x(slayer_trainable=True, slayer_cap=80, best_slayer_boost=5)

    assert "Kill X ~|Abyssal demon|~" in built


def test_a_passive_floor_counts_even_with_slayer_untrainable() -> None:
    """The two routes are alternatives, not conjuncts: a level already banked
    needs no way to train the skill further."""
    built = _kill_x(passive_slayer=85)

    assert "Kill X ~|Abyssal demon|~" in built


def test_an_absent_passive_floor_is_not_a_zero() -> None:
    """Upstream tests `passiveSkill.hasOwnProperty('Slayer')` before
    comparing, so a map recording none must not read as level 0 - which would
    admit any monster requiring 0."""
    assert "Kill X ~|Cave crawler|~" not in _kill_x()


def test_bosses_wait_for_their_own_rule() -> None:
    given = SynthesisInputs(items={}, monsters={"Zulrah": True})

    assert synthesised_challenges(_monster_world(), given, {"Kill X": True}) == {}
    assert "Kill X ~|Zulrah|~" in synthesised_challenges(
        _monster_world(), given, {"Kill X": True, "Kill X Boss": True}
    )["Extra"]


def test_a_backlogged_kill_is_left_out() -> None:
    """Checked here rather than left to the ordinary machinery, because a
    forced-valid challenge never reaches it."""
    built = _kill_x(backlog={"Kill X ~|Rat|~": True})

    assert "Kill X ~|Rat|~" not in built


def test_a_hash_sub_name_is_tried_both_spellings_in_the_backlog() -> None:
    given = SynthesisInputs(
        items={},
        monsters={"Cave bug#Level 6": True},
        backlog={"Kill X ~|Cave bug/Level 6|~": True},
    )

    assert synthesised_challenges(_monster_world(), given, {"Kill X": True}) == {}


def test_a_kill_task_links_to_its_slayer_assignment() -> None:
    """Skipping the `|~ alt` duplicates, and only when the map has Slayer
    validity at all."""
    unlinked = _kill_x(slayer_trainable=True)
    linked = _kill_x(slayer_trainable=True, slayer_has_tasks=True)

    assert "Tasks" not in unlinked["Kill X ~|Cave crawler|~"]
    assert linked["Kill X ~|Cave crawler|~"]["Tasks"] == {"Slay ~|Cave crawler|~": "Slayer"}
    assert "Tasks" not in linked["Kill X ~|Rat|~"]


def _drop_world() -> ChunkInfo:
    return _info(
        challenges={
            "Slayer": {"Slay ~|Abyssal demon|~": {"Output": "Abyssal demon"}},
            "Thieving": {"Pickpocket a ~|Rogue|~": {"Output": "Rogue"}},
            "Hunter": {"Catch a ~|baby impling|~": {"Output": "Baby impling jar"}},
        },
        skillItems={
            "Thieving": {"Rogue": {"Air rune": {"1": "1/16"}}},
            "Hunter": {"Baby impling jar": {"Bronze arrow": {"1": "1/8"}}},
        },
        codeItems={"dropTables": {"RareDropTable+": {"Nature rune": "1/4@1"}}, "bossMonsters": {}},
    )


def _every_drop(**over: Any) -> dict[str, dict[str, Any]]:
    given = SynthesisInputs(
        items={"Bones": {"Goblin": "primary-drop"}},
        drop_rates={"Goblin": {"Bones": "Always"}},
        **over,
    )
    return synthesised_challenges(_drop_world(), given, {"Every Drop": True}).get("Extra", {})


def test_every_drop_names_the_source_and_its_rate() -> None:
    """One task per drop line, carrying that source's own rate - which is
    what makes the same item off three monsters three tasks rather than one."""
    assert set(_every_drop()) == {"Goblin: ~|Bones|~ (Always)"}


def test_a_slay_source_is_named_by_its_monster() -> None:
    """A `Slay ` source is a challenge name; the rate is filed under what it
    outputs, so the title has to be too."""
    given = SynthesisInputs(
        items={"Abyssal whip": {"Slay ~|Abyssal demon|~": "primary-Slayer"}},
        drop_rates={"Abyssal demon": {"Abyssal whip": "1/512"}},
    )

    built = synthesised_challenges(_drop_world(), given, {"Every Drop": True})["Extra"]

    assert set(built) == {"Abyssal demon: ~|Abyssal whip|~ (1/512)"}


def test_a_pickpocket_table_is_measured_under_its_own_namespace() -> None:
    """`gather_chunks_info` never walks a Thieving loot table, so its rates
    are measured here - and filed under upstream's invented `[Thieving] `
    key, which is what keeps an NPC from colliding with a monster."""
    given = SynthesisInputs(
        items={"Air rune": {"Pickpocket a ~|Rogue|~": "primary-Thieving"}},
        drop_rates={},
    )

    built = synthesised_challenges(_drop_world(), given, {"Every Drop": True})["Extra"]

    assert set(built) == {"[Thieving] Rogue: ~|Air rune|~ (1/16)"}


def test_implings_wait_for_their_own_rule() -> None:
    """`Every Drop Implings` is a second switch, and the jar loses the word
    `jar` on the way into the title."""
    given = SynthesisInputs(
        items={"Bronze arrow": {"Catch a ~|baby impling|~": "primary-Hunter"}},
        drop_rates={},
    )

    assert synthesised_challenges(_drop_world(), given, {"Every Drop": True}) == {}
    built = synthesised_challenges(
        _drop_world(), given, {"Every Drop": True, "Every Drop Implings": True}
    )["Extra"]
    assert set(built) == {"Baby impling: ~|Bronze arrow|~ (1/8)"}


def test_a_drop_already_ticked_off_is_not_offered_again() -> None:
    """The completion is stored under the *task* name, so upstream reads the
    item back out of it - and one source having yielded it settles the rest."""
    built = _every_drop(completed_extra={"Somewhere else: ~|Bones|~ (1/2)": True})

    assert built == {}


def test_a_drop_table_name_is_not_a_thing_you_can_obtain() -> None:
    given = SynthesisInputs(
        items={"RareDropTable+": {"Goblin": "primary-drop"}},
        drop_rates={"Goblin": {"RareDropTable+": "1/128"}},
    )

    assert synthesised_challenges(_drop_world(), given, {"Every Drop": True}) == {}


def test_a_marked_index_entry_is_skipped() -> None:
    given = SynthesisInputs(
        items={"^^placeholder": {"Goblin": "primary-drop"}},
        drop_rates={"Goblin": {"^^placeholder": "1/128"}},
    )

    assert synthesised_challenges(_drop_world(), given, {"Every Drop": True}) == {}


def test_a_source_with_no_recorded_rate_names_nothing() -> None:
    """The rate is part of the title, so a source that never reached
    `dropRatesGlobal` cannot produce a task at all."""
    given = SynthesisInputs(items={"Bones": {"Goblin": "primary-drop"}}, drop_rates={})

    assert synthesised_challenges(_drop_world(), given, {"Every Drop": True}) == {}


def test_a_shop_source_is_not_a_drop() -> None:
    given = SynthesisInputs(
        items={"Bones": {"Bone Store": "shop"}}, drop_rates={"Bone Store": {"Bones": "Always"}}
    )

    assert synthesised_challenges(_drop_world(), given, {"Every Drop": True}) == {}


def _table_world() -> ChunkInfo:
    return _info(
        challenges={
            "Slayer": {"Slay ~|Abyssal demon|~": {"Output": "Abyssal demon"}},
            "Thieving": {
                "Pickpocket a ~|Rogue|~": {"Output": "Rogue", "NPCs": ["Rogue"]},
                "Loot a ~|chest|~": {"Output": "Chest", "Objects": ["Chest"]},
            },
            "Hunter": {"Catch a ~|baby impling|~": {"Output": "Baby impling jar"}},
        },
        skillItems={
            "Slayer": {"Abyssal demon": {"Abyssal whip": {"1": "1/512"}}},
            "Thieving": {
                "Rogue": {"Air rune": {"10-19": "1/16"}},
                "Chest": {"Coins": {"100": "Always"}},
            },
            "Hunter": {"Baby impling jar": {"Bronze arrow": {"1": "1/8"}}},
        },
        codeItems={"dropTables": {}, "bossMonsters": {}},
    )


def _droptables(**over: Any) -> dict[str, dict[str, Any]]:
    given = SynthesisInputs(items={}, **over)
    return synthesised_challenges(_table_world(), given, {"All Droptables": True}).get("Extra", {})


def test_a_droptable_row_carries_its_quantity_as_well_as_its_rate() -> None:
    """The difference from `Every Drop`: one task per (source, item,
    *quantity*), so a monster dropping one coin and a hundred is two rows and
    the title says which."""
    built = _droptables(
        drop_quantities={"Goblin": {"Coins": {"1": "Always", "100": "1/128"}}}
    )

    assert set(built) == {
        "Goblin: ~|Coins|~ (1) (Always)",
        "Goblin: ~|Coins|~ (100) (1/128)",
    }


def test_an_empty_quantity_reads_as_not_applicable() -> None:
    built = _droptables(drop_quantities={"Goblin": {"Bones": {"": "Always"}}})

    assert set(built) == {"Goblin: ~|Bones|~ (N/A) (Always)"}


def test_a_plain_entity_is_named_as_a_monster() -> None:
    built = _droptables(drop_quantities={"Goblin": {"Bones": {"1": "Always"}}})
    entry = built["Goblin: ~|Bones|~ (1) (Always)"]

    assert entry["Monsters"] == ["Goblin"]
    assert "NPCs" not in entry and "Objects" not in entry


def test_a_pickpocket_table_is_keyed_and_shaped_by_its_source_challenge() -> None:
    """The suffix comes off the *source challenge*, never the NPC: upstream
    asks whether the challenge has `Mix`, then `NPCs`, then `Objects`. It
    keeps the entity apart in `dropTablesGlobal` and decides whether the row
    names a monster, an NPC or an object - then is stripped from the title."""
    given = SynthesisInputs(
        items={"Air rune": {"Pickpocket a ~|Rogue|~": "primary-Thieving"}},
    )

    built = synthesised_challenges(_table_world(), given, {"All Droptables": True})["Extra"]

    name = "[Thieving] Rogue: ~|Air rune|~ (10-19) (1/16)"
    assert set(built) == {name}
    assert built[name]["NPCs"] == ["[Thieving] Rogue"]
    assert built[name]["Monsters"] == ["[Thieving] Rogue-npc"]


def test_an_object_source_names_an_object() -> None:
    given = SynthesisInputs(items={"Coins": {"Loot a ~|chest|~": "primary-Thieving"}})

    built = synthesised_challenges(_table_world(), given, {"All Droptables": True})["Extra"]
    entry = built["[Thieving] Chest: ~|Coins|~ (100) (Always)"]

    assert entry["Objects"] == ["[Thieving] Chest"]


def test_an_implings_jar_loses_the_word_and_gains_a_suffix() -> None:
    given = SynthesisInputs(
        items={"Bronze arrow": {"Catch a ~|baby impling|~": "primary-Hunter"}}
    )

    built = synthesised_challenges(_table_world(), given, {"All Droptables": True})["Extra"]
    entry = built["Baby impling: ~|Bronze arrow|~ (1) (1/8)"]

    assert entry["NPCs"] == ["Baby impling"]
    assert entry["Monsters"] == ["Baby impling-npc"]


def test_a_slayer_table_is_measured_under_its_monster() -> None:
    given = SynthesisInputs(
        items={"Abyssal whip": {"Slay ~|Abyssal demon|~": "primary-Slayer"}}
    )

    built = synthesised_challenges(_table_world(), given, {"All Droptables": True})["Extra"]

    assert set(built) == {"Abyssal demon: ~|Abyssal whip|~ (1) (1/512)"}


def test_a_skill_route_key_is_never_emitted_from() -> None:
    """Upstream refuses a `dropTablesGlobal` key whose suffix is a skill
    name - those are `skillItems` routes rather than entities. This project
    does not build them yet; the guard is here so that adding the route
    cannot silently start emitting from it.
    """
    built = _droptables(drop_quantities={"Pizazz points-Magic": {"Master wand": {"1": "1/1"}}})

    assert built == {}


def test_a_marked_item_row_is_skipped() -> None:
    built = _droptables(drop_quantities={"Goblin": {"^^placeholder": {"1": "Always"}}})

    assert built == {}
