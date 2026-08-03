"""Tests for the core challenge-validity fixed point."""

from __future__ import annotations

from typing import Any

from fray_claude.challenges import (
    UNSUPPORTED_CATEGORIES,
    calc_challenges,
    contains_sections,
    has_allowed_source,
    only_shop,
    strip_task_markup,
)
from fray_claude.chunkinfo import ChunkInfo
from fray_claude.sources import SourceIndex

_EMPTY = SourceIndex(items={}, objects={}, monsters={}, npcs={}, shops={}, drop_rates={})


def _chunk_info(**data: Any) -> ChunkInfo:
    return ChunkInfo(data)


def test_contains_sections_recognises_a_numbered_section() -> None:
    assert contains_sections("100-1") is True


def test_contains_sections_recognises_a_water_section() -> None:
    assert contains_sections("100-W1") is True


def test_contains_sections_rejects_a_plain_chunk_id() -> None:
    assert contains_sections("100") is False


def test_contains_sections_rejects_a_non_numeric_base() -> None:
    assert contains_sections("Zanaris-1") is False


def test_only_shop_is_true_when_every_source_is_shop() -> None:
    assert only_shop({"General Store": "shop"}) is True
    assert only_shop({"Goblin": "primary-drop", "Store": "shop"}) is False


def test_has_allowed_source_with_no_restriction() -> None:
    assert has_allowed_source({"Goblin": "primary-drop"}, None) is True
    assert has_allowed_source({"Goblin": "primary-drop"}, []) is True


def test_has_allowed_source_checks_source_keys() -> None:
    assert has_allowed_source({"Goblin": "primary-drop"}, ["Goblin"]) is True
    assert has_allowed_source({"Goblin": "primary-drop"}, ["Cow"]) is False


def test_a_challenge_with_no_requirements_is_valid() -> None:
    info = _chunk_info(challenges={"Nonskill": {"Do a thing": {}}})

    result = calc_challenges({}, {}, _EMPTY, info, rules={})

    assert result.valid == {"Nonskill": {"Do a thing": True}}
    assert result.unsupported == frozenset()


def test_quest_and_diary_challenges_are_valued_true_not_by_level() -> None:
    info = _chunk_info(challenges={"Quest": {"Do a quest": {"Level": 5}}})

    result = calc_challenges({}, {}, _EMPTY, info, rules={})

    assert result.valid == {"Quest": {"Do a quest": True}}


def test_a_skill_challenge_is_valued_by_its_level() -> None:
    # The Level 1 `Primary` entry keeps `Woodcutting` trainable; without one
    # `_prune_untrainable_skills` strips everything above Level 1.
    info = _chunk_info(
        challenges={
            "Woodcutting": {
                "Chop a sapling": {"Level": 1, "Primary": True},
                "Chop a tree": {"Level": 15},
            }
        }
    )

    result = calc_challenges({}, {}, _EMPTY, info, rules={})

    assert result.valid == {"Woodcutting": {"Chop a sapling": 1, "Chop a tree": 15}}


def test_chunks_requirement_needs_the_chunk_unlocked() -> None:
    info = _chunk_info(challenges={"Nonskill": {"Visit": {"Chunks": ["100"]}}})

    without = calc_challenges({}, {}, _EMPTY, info, rules={})
    with_chunk = calc_challenges({"100": True}, {}, _EMPTY, info, rules={})

    assert without.valid == {}
    assert with_chunk.valid == {"Nonskill": {"Visit": True}}


def test_chunks_requirement_with_a_section_needs_it_reachable() -> None:
    info = _chunk_info(challenges={"Nonskill": {"Visit": {"Chunks": ["100-1"]}}})

    unreachable = calc_challenges({"100": True}, {}, _EMPTY, info, rules={})
    reachable = calc_challenges({"100": True}, {"100": {"1": True}}, _EMPTY, info, rules={})

    assert unreachable.valid == {}
    assert reachable.valid == {"Nonskill": {"Visit": True}}


def test_chunks_family_requirement_needs_at_least_one_member() -> None:
    info = _chunk_info(
        challenges={"Nonskill": {"Visit a bank": {"Chunks": ["Bank[+]"]}}},
        codeItems={"chunksPlus": {"Bank[+]": ["100", "200"]}},
    )

    assert calc_challenges({}, {}, _EMPTY, info, rules={}).valid == {}
    assert calc_challenges({"200": True}, {}, _EMPTY, info, rules={}).valid == {
        "Nonskill": {"Visit a bank": True}
    }


def test_chunks_family_count_requirement() -> None:
    info = _chunk_info(
        challenges={"Nonskill": {"Visit two banks": {"Chunks": ["Bank[+]x2"]}}},
        codeItems={"chunksPlus": {"Bank[+]": ["100", "200", "300"]}},
    )

    one = calc_challenges({"100": True}, {}, _EMPTY, info, rules={})
    two = calc_challenges({"100": True, "200": True}, {}, _EMPTY, info, rules={})

    assert one.valid == {}
    assert two.valid == {"Nonskill": {"Visit two banks": True}}


def test_objects_monsters_npcs_requirements_need_presence() -> None:
    info = _chunk_info(
        challenges={
            "Nonskill": {
                "Do it": {"Objects": ["Anvil"], "Monsters": ["Goblin"], "NPCs": ["Banker"]}
            }
        }
    )
    index = SourceIndex(
        items={},
        objects={"Anvil": {"100": True}},
        monsters={"Goblin": {"100": True}},
        npcs={"Banker": {"100": True}},
        shops={},
        drop_rates={},
    )

    assert calc_challenges({}, {}, _EMPTY, info, rules={}).valid == {}
    assert calc_challenges({}, {}, index, info, rules={}).valid == {"Nonskill": {"Do it": True}}


def test_mix_requirement_accepts_either_monster_or_npc() -> None:
    info = _chunk_info(challenges={"Nonskill": {"Kill it": {"Mix": ["Goblin"]}}})
    monster_index = SourceIndex(
        items={}, objects={}, monsters={"Goblin": {"100": True}}, npcs={}, shops={}, drop_rates={}
    )
    npc_index = SourceIndex(
        items={}, objects={}, monsters={}, npcs={"Goblin": {"100": True}}, shops={}, drop_rates={}
    )

    assert calc_challenges({}, {}, _EMPTY, info, rules={}).valid == {}
    assert calc_challenges({}, {}, monster_index, info, rules={}).valid == {
        "Nonskill": {"Kill it": True}
    }
    assert calc_challenges({}, {}, npc_index, info, rules={}).valid == {
        "Nonskill": {"Kill it": True}
    }


def test_items_requirement_needs_presence() -> None:
    info = _chunk_info(challenges={"Nonskill": {"Craft it": {"Items": ["Iron bar"]}}})
    index = SourceIndex(
        items={"Iron bar": {"100": "shop"}}, objects={}, monsters={}, npcs={}, shops={}, drop_rates={}
    )

    assert calc_challenges({}, {}, _EMPTY, info, rules={}).valid == {}
    assert calc_challenges({}, {}, index, info, rules={}).valid == {"Nonskill": {"Craft it": True}}


def test_items_requirement_respects_non_shop() -> None:
    info = _chunk_info(
        challenges={"Nonskill": {"Find it": {"Items": ["Iron bar"], "NonShop": True}}}
    )
    shop_only = SourceIndex(
        items={"Iron bar": {"General Store": "shop"}},
        objects={},
        monsters={},
        npcs={},
        shops={},
        drop_rates={},
    )
    also_dropped = SourceIndex(
        items={"Iron bar": {"General Store": "shop", "Goblin": "primary-drop"}},
        objects={},
        monsters={},
        npcs={},
        shops={},
        drop_rates={},
    )

    assert calc_challenges({}, {}, shop_only, info, rules={}).valid == {}
    assert calc_challenges({}, {}, also_dropped, info, rules={}).valid == {
        "Nonskill": {"Find it": True}
    }


def test_items_requirement_respects_allowed_sources() -> None:
    info = _chunk_info(
        challenges={
            "Nonskill": {"Find it": {"Items": ["Iron bar"], "AllowedSources": ["Goblin"]}}
        }
    )
    wrong_source = SourceIndex(
        items={"Iron bar": {"Store": "shop"}}, objects={}, monsters={}, npcs={}, shops={}, drop_rates={}
    )
    right_source = SourceIndex(
        items={"Iron bar": {"Goblin": "primary-drop"}},
        objects={},
        monsters={},
        npcs={},
        shops={},
        drop_rates={},
    )

    assert calc_challenges({}, {}, wrong_source, info, rules={}).valid == {}
    assert calc_challenges({}, {}, right_source, info, rules={}).valid == {
        "Nonskill": {"Find it": True}
    }


def test_item_family_requirement_needs_a_member_present() -> None:
    info = _chunk_info(
        challenges={"Nonskill": {"Chop it": {"Items": ["Axe[+]"]}}},
        codeItems={"itemsPlus": {"Axe[+]": ["Bronze axe", "Iron axe"]}},
    )
    index = SourceIndex(
        items={"Iron axe": {"General Store": "shop"}},
        objects={},
        monsters={},
        npcs={},
        shops={},
        drop_rates={},
    )

    assert calc_challenges({}, {}, _EMPTY, info, rules={}).valid == {}
    assert calc_challenges({}, {}, index, info, rules={}).valid == {"Nonskill": {"Chop it": True}}


def test_item_family_count_requirement() -> None:
    info = _chunk_info(
        challenges={"Nonskill": {"Chop lots": {"Items": ["Axe[+]x2"]}}},
        codeItems={"itemsPlus": {"Axe[+]": ["Bronze axe", "Iron axe", "Steel axe"]}},
    )
    one = SourceIndex(
        items={"Iron axe": {"Store": "shop"}}, objects={}, monsters={}, npcs={}, shops={}, drop_rates={}
    )
    two = SourceIndex(
        items={"Iron axe": {"Store": "shop"}, "Steel axe": {"Store": "shop"}},
        objects={},
        monsters={},
        npcs={},
        shops={},
        drop_rates={},
    )

    assert calc_challenges({}, {}, one, info, rules={}).valid == {}
    assert calc_challenges({}, {}, two, info, rules={}).valid == {"Nonskill": {"Chop lots": True}}


def test_unknown_item_family_is_invalid_not_unsupported() -> None:
    info = _chunk_info(challenges={"Nonskill": {"Chop it": {"Items": ["Axe[+]"]}}})

    result = calc_challenges({}, {}, _EMPTY, info, rules={})

    assert result.valid == {}
    assert result.unsupported == frozenset()


def test_secondary_marker_is_stripped_and_does_not_block_validity() -> None:
    info = _chunk_info(challenges={"Nonskill": {"Use coins": {"Items": ["Coins*"]}}})
    index = SourceIndex(
        items={"Coins": {"Goblin": "secondary-drop"}},
        objects={},
        monsters={},
        npcs={},
        shops={},
        drop_rates={},
    )

    result = calc_challenges({}, {}, index, info, rules={})

    assert result.valid == {"Nonskill": {"Use coins": True}}
    assert result.unsupported == frozenset()


def test_source_quality_gate_rejects_a_combat_items_only_source_is_crafted() -> None:
    info = _chunk_info(challenges={"Attack": {"Wield it": {"Items": ["Rune scimitar"]}}})
    only_crafted = SourceIndex(
        items={"Rune scimitar": {"Smith a rune scimitar": "primary-Smithing"}},
        objects={},
        monsters={},
        npcs={},
        shops={},
        drop_rates={},
    )
    also_dropped = SourceIndex(
        items={
            "Rune scimitar": {
                "Smith a rune scimitar": "primary-Smithing",
                "Goblin": "secondary-drop",
            }
        },
        objects={},
        # `Attack`'s `universalPrimary` line is `Monster[+]`, so something to
        # hit is what makes the skill trainable at all.
        monsters={"Goblin": {"100": True}},
        npcs={},
        shops={},
        drop_rates={},
    )

    assert calc_challenges({}, {}, only_crafted, info, rules={}).valid == {}
    assert calc_challenges({}, {}, also_dropped, info, rules={}).valid == {
        "Attack": {"Wield it": True}
    }


def test_source_quality_gate_ignores_non_combat_non_bis_skilling_skills() -> None:
    info = _chunk_info(challenges={"Nonskill": {"Use it": {"Items": ["Rune scimitar"]}}})
    only_crafted = SourceIndex(
        items={"Rune scimitar": {"Smith a rune scimitar": "primary-Smithing"}},
        objects={},
        monsters={},
        npcs={},
        shops={},
        drop_rates={},
    )

    assert calc_challenges({}, {}, only_crafted, info, rules={}).valid == {
        "Nonskill": {"Use it": True}
    }


def test_source_quality_gate_allows_wield_crafted_items_rule() -> None:
    info = _chunk_info(challenges={"Attack": {"Wield it": {"Items": ["Rune scimitar"]}}})
    only_crafted = SourceIndex(
        items={"Rune scimitar": {"Smith a rune scimitar": "primary-Smithing"}},
        objects={},
        # `Attack` trains on monsters (`universalPrimary`), so one has to be
        # present or the whole skill is pruned before the gate is reached.
        monsters={"Goblin": {"100": True}},
        npcs={},
        shops={},
        drop_rates={},
    )

    result = calc_challenges(
        {}, {}, only_crafted, info, rules={"Wield Crafted Items": True}
    )

    assert result.valid == {"Attack": {"Wield it": True}}


def test_unsupported_challenges_do_not_block_evaluable_ones() -> None:
    info = _chunk_info(
        challenges={
            "Nonskill": {
                "Points": {"QuestPointsNeeded": 5},
                "Simple": {},
            }
        }
    )

    result = calc_challenges({}, {}, _EMPTY, info, rules={})

    assert result.valid == {"Nonskill": {"Simple": True}}
    assert result.unsupported == frozenset({"Nonskill/Points"})


def test_tasks_requirement_needs_the_prerequisite_valid() -> None:
    info = _chunk_info(
        challenges={
            "Quest": {"Do quest A": {}},
            "Nonskill": {"Needs quest A": {"Tasks": {"Do quest A": "Quest"}}},
        }
    )

    result = calc_challenges({}, {}, _EMPTY, info, rules={})

    assert result.valid["Quest"] == {"Do quest A": True}
    assert result.valid["Nonskill"] == {"Needs quest A": True}


def test_tasks_requirement_fails_when_the_prerequisite_is_invalid() -> None:
    info = _chunk_info(
        challenges={
            "Quest": {"Do quest A": {"Chunks": ["999"]}},
            "Nonskill": {"Needs quest A": {"Tasks": {"Do quest A": "Quest"}}},
        }
    )

    result = calc_challenges({}, {}, _EMPTY, info, rules={})

    assert "Quest" not in result.valid
    assert "Nonskill" not in result.valid


def test_skills_requirement_needs_the_sub_skill_trainable() -> None:
    # A `Skills` requirement needs the sub-skill *trainable*, which for a
    # `Primary[+]` skill like Cooking means a valid challenge actually
    # flagged `Primary` - not merely any valid entry (see
    # `_check_primary_method`).
    info = _chunk_info(
        challenges={
            "Cooking": {"Cook something": {"Level": 1, "Primary": True}},
            "Nonskill": {"Needs cooking": {"Skills": {"Cooking": 1}}},
        }
    )

    result = calc_challenges({}, {}, _EMPTY, info, rules={})

    assert result.valid["Nonskill"] == {"Needs cooking": True}


def test_skills_requirement_rejects_a_sub_skill_with_no_training_method() -> None:
    # Same fixture without the `Primary` flag: the Cooking challenge is
    # valid, but it isn't a way to *train* Cooking, so the dependent task
    # stays invalid.
    info = _chunk_info(
        challenges={
            "Cooking": {"Cook something": {"Level": 1}},
            "Nonskill": {"Needs cooking": {"Skills": {"Cooking": 1}}},
        }
    )

    result = calc_challenges({}, {}, _EMPTY, info, rules={})

    assert result.valid.get("Cooking") == {"Cook something": 1}
    assert "Nonskill" not in result.valid


def test_combat_is_trainable_when_any_monster_exists() -> None:
    # `Combat` has almost no challenges of its own; upstream defines it as
    # "any combat skill is trainable", and those need only something to
    # hit. Before this, every `Skills: {Combat: N}` task was dead.
    info = _chunk_info(challenges={"Nonskill": {"Fight something": {"Skills": {"Combat": 40}}}})
    with_monster = SourceIndex(
        items={}, objects={}, monsters={"Goblin": {"100": True}}, npcs={}, shops={}, drop_rates={}
    )

    assert calc_challenges({}, {}, _EMPTY, info, rules={}).valid == {}
    assert calc_challenges({}, {}, with_monster, info, rules={}).valid == {
        "Nonskill": {"Fight something": True}
    }


def test_tasks_requirement_resolves_across_category_iteration_order() -> None:
    # `Nonskill` is iterated before `Slayer` in the real export, so a
    # Nonskill task depending on a Slayer one must still resolve - the
    # fixed point consults the previous pass, not just the partially-built
    # current one.
    info = _chunk_info(
        challenges={
            "Nonskill": {"Needs slayer": {"Tasks": {"Do slayer": "Slayer"}}},
            "Slayer": {"Do slayer": {}},
        }
    )

    result = calc_challenges({}, {}, _EMPTY, info, rules={})

    assert result.valid["Nonskill"] == {"Needs slayer": True}


def test_tasks_family_requirement_needs_one_valid_member() -> None:
    info = _chunk_info(
        challenges={
            "Nonskill": {"Needs a master": {"Tasks": {"Masters[+]x1": "Slayer"}}},
            "Slayer": {"Ask Vannaka": {}},
        },
        codeItems={"tasksPlus": {"Masters[+]": ["Ask Duradel", "Ask Vannaka"]}},
    )

    result = calc_challenges({}, {}, _EMPTY, info, rules={})

    assert result.valid["Nonskill"] == {"Needs a master": True}


def test_tasks_family_requirement_fails_with_no_valid_member() -> None:
    info = _chunk_info(
        challenges={"Nonskill": {"Needs a master": {"Tasks": {"Masters[+]x1": "Slayer"}}}},
        codeItems={"tasksPlus": {"Masters[+]": ["Ask Duradel"]}},
    )

    assert calc_challenges({}, {}, _EMPTY, info, rules={}).valid == {}


def test_skills_requirement_respects_max_skill() -> None:
    info = _chunk_info(
        challenges={
            "Nonskill": {"Needs high cooking": {"Skills": {"Cooking": 50}}},
        }
    )

    result = calc_challenges({}, {}, _EMPTY, info, rules={}, max_skill={"Cooking": 10})

    assert result.valid == {}


def test_max_skill_gate_on_the_challenges_own_level() -> None:
    info = _chunk_info(challenges={"Woodcutting": {"Chop a tree": {"Level": 50}}})

    result = calc_challenges({}, {}, _EMPTY, info, rules={}, max_skill={"Woodcutting": 10})

    assert result.valid == {}


def test_not_f2p_and_not_skiller_gates() -> None:
    info = _chunk_info(
        challenges={
            "Nonskill": {
                "F2P only": {"Not F2P": True},
                "Skiller only": {"Not Skiller": True},
            }
        }
    )

    default = calc_challenges({}, {}, _EMPTY, info, rules={})
    f2p = calc_challenges({}, {}, _EMPTY, info, rules={"F2P": True})
    skiller = calc_challenges({}, {}, _EMPTY, info, rules={"Skiller": True})

    assert default.valid["Nonskill"] == {"F2P only": True, "Skiller only": True}
    assert "F2P only" not in f2p.valid.get("Nonskill", {})
    assert "Skiller only" not in skiller.valid.get("Nonskill", {})


def test_category_rule_gate_excludes_when_the_rule_is_off() -> None:
    info = _chunk_info(challenges={"Nonskill": {"Boss task": {"Category": ["Boss"]}}})

    off = calc_challenges({}, {}, _EMPTY, info, rules={"Boss": False})
    on = calc_challenges({}, {}, _EMPTY, info, rules={"Boss": True})

    assert off.valid == {}
    assert on.valid == {"Nonskill": {"Boss task": True}}


def test_inside_poh_primary_category_needs_the_rule_above_level_one() -> None:
    info = _chunk_info(
        challenges={"Nonskill": {"POH task": {"Category": ["InsidePOH Primary"], "Level": 2}}}
    )

    off = calc_challenges({}, {}, _EMPTY, info, rules={"InsidePOH": False})
    on = calc_challenges({}, {}, _EMPTY, info, rules={"InsidePOH": True})

    assert off.valid == {}
    assert on.valid == {"Nonskill": {"POH task": 2}}


def test_unsupported_level_gates_raise_are_caught_and_reported() -> None:
    info = _chunk_info(
        challenges={"Nonskill": {"Points task": {"QuestPointsNeeded": 5}}}
    )

    result = calc_challenges({}, {}, _EMPTY, info, rules={})

    assert result.valid == {}
    assert result.unsupported == frozenset({"Nonskill/Points task"})


def test_a_valid_challenges_output_feeds_the_next_pass_as_a_new_item() -> None:
    info = _chunk_info(
        challenges={
            "Smithing": {
                "Smelt a bronze bar": {"Level": 1, "Primary": True},
                "Smelt a bar": {"Output": "Iron bar"},
            },
            "Nonskill": {"Use the bar": {"Items": ["Iron bar"]}},
        }
    )

    result = calc_challenges({}, {}, _EMPTY, info, rules={})

    assert result.valid["Smithing"] == {"Smelt a bronze bar": 1, "Smelt a bar": True}
    assert result.valid["Nonskill"] == {"Use the bar": True}


def test_calc_challenges_tolerates_an_empty_export() -> None:
    result = calc_challenges({}, {}, _EMPTY, _chunk_info(), rules={})

    assert result.valid == {}
    assert result.unsupported == frozenset()
    assert result.as_dict() == {"valid": {}, "unsupported": []}


def test_highest_level_grouping_picks_the_lowest_level_consumer_when_off() -> None:
    info = _chunk_info(
        challenges={
            "Smithing": {
                "Smith a bronze dagger": {"Level": 1, "Items": ["Bronze bar*"]},
                "Smith a bronze axe": {"Level": 1, "Items": ["Bronze bar*"]},
                "Smith a bronze med helm": {"Level": 3, "Items": ["Bronze bar*"]},
            }
        }
    )
    index = SourceIndex(
        items={"Bronze bar": {"Smelt a bronze bar": "primary-Smithing"}},
        objects={},
        monsters={},
        npcs={},
        shops={},
        drop_rates={},
    )

    result = calc_challenges({}, {}, index, info, rules={"Highest Level": False})

    # Both level-1 challenges tie; the first one in `challenges`' key order
    # wins (upstream's first-seen-wins tie-break, `_group_processing_skill_challenges`).
    assert result.valid == {"Smithing": {"Smith a bronze dagger": 1}}


def test_highest_level_grouping_keeps_every_consumer_when_on() -> None:
    info = _chunk_info(
        challenges={
            "Smithing": {
                "Smith a bronze dagger": {"Level": 1, "Primary": True, "Items": ["Bronze bar*"]},
                "Smith a bronze med helm": {"Level": 3, "Items": ["Bronze bar*"]},
            }
        }
    )
    index = SourceIndex(
        items={"Bronze bar": {"Smelt a bronze bar": "primary-Smithing"}},
        objects={},
        monsters={},
        npcs={},
        shops={},
        drop_rates={},
    )

    result = calc_challenges({}, {}, index, info, rules={"Highest Level": True})

    assert result.valid == {
        "Smithing": {"Smith a bronze dagger": 1, "Smith a bronze med helm": 3}
    }


def test_highest_level_grouping_leaves_non_processing_skills_alone() -> None:
    info = _chunk_info(
        challenges={
            "Woodcutting": {
                "Chop a sapling": {"Level": 1, "Primary": True},
                "Chop a tree": {"Level": 15},
            }
        }
    )

    result = calc_challenges({}, {}, _EMPTY, info, rules={"Highest Level": False})

    assert result.valid == {"Woodcutting": {"Chop a sapling": 1, "Chop a tree": 15}}


def test_bis_is_never_computed_even_if_present_and_trivially_valid() -> None:
    # Real exports never have a `challenges.BiS` branch at all (it's
    # synthesized at runtime upstream) - this proves the absence isn't
    # incidental, in case that ever changes.
    assert "BiS" in UNSUPPORTED_CATEGORIES
    info = _chunk_info(challenges={"BiS": {"Obtain a whip": {}}})

    result = calc_challenges({}, {}, _EMPTY, info, rules={})

    assert "BiS" not in result.valid


def test_challenge_output_naming_a_skill_items_activity_yields_its_items() -> None:
    # Upstream's link (worker.js:2848): a challenge's `Output` doubles as the
    # activity key into `skillItems[skill]`. `Master wand` is real-world only
    # reachable this way, via `~|Pizazz points|~*` -> `Pizazz points loot`.
    info = _chunk_info(
        challenges={"Nonskill": {"Earn pizazz points": {"Output": "Pizazz points loot"}}},
        skillItems={"Nonskill": {"Pizazz points loot": {"Master wand": {"1": "Always"}}}},
    )

    result = calc_challenges({}, {}, _EMPTY, info, rules={})

    assert "Master wand" in result.available_items
    assert "Pizazz points loot" in result.available_items


def test_backlogged_items_are_excluded_from_output_seeding() -> None:
    # A backlogged source means "I will not do this", so it must not sneak
    # back in as a prerequisite - real case: a backlogged `Uncut onyx` was
    # re-entering through a skillItems activity and dragging a whole
    # crafting chain with it.
    info = _chunk_info(
        challenges={"Nonskill": {"Open the bag": {"Output": "Bag loot"}}},
        skillItems={
            "Nonskill": {"Bag loot": {"Uncut onyx": {"1": "1/100000000"}, "Coal": {"1": "1/2"}}}
        },
    )

    result = calc_challenges(
        {}, {}, _EMPTY, info, rules={}, backlogged_sources={"items": {"Uncut onyx": True}}
    )

    assert "Uncut onyx" not in result.available_items
    assert "Coal" in result.available_items


def test_a_backlogged_direct_output_is_excluded_too() -> None:
    info = _chunk_info(challenges={"Smithing": {"Smelt a bar": {"Output": "Iron bar"}}})

    result = calc_challenges(
        {}, {}, _EMPTY, info, rules={}, backlogged_sources={"items": {"Iron bar": True}}
    )

    assert "Iron bar" not in result.available_items


def test_boss_log_activities_are_gated_by_the_boss_rule() -> None:
    info = _chunk_info(
        challenges={"Nonskill": {"Loot the chest": {"Output": "Monumental chest"}}},
        skillItems={"Nonskill": {"Monumental chest": {"Rare thing": {"1": "1/50"}}}},
        codeItems={"bossLogs": {"Monumental chest": True}},
    )

    off = calc_challenges({}, {}, _EMPTY, info, rules={})
    on = calc_challenges({}, {}, _EMPTY, info, rules={"Boss": True})

    assert "Rare thing" not in off.available_items
    assert "Rare thing" in on.available_items


def test_strip_task_markup_keeps_the_text_and_its_casing() -> None:
    assert strip_task_markup("Obtain a ~|Karil's coif|~") == "Obtain a Karil's coif"


def test_strip_task_markup_leaves_an_unmarked_name_alone() -> None:
    assert strip_task_markup("Mine a size-9 shooting star") == "Mine a size-9 shooting star"


def test_strip_task_markup_handles_several_marked_spans() -> None:
    assert strip_task_markup("Use ~|bones|~ on the ~|altar|~") == "Use bones on the altar"


def test_strip_task_markup_repairs_the_malformed_canoe_names() -> None:
    """Four real export names put the opening `|` several characters late.
    Removing the delimiter characters renders them correctly; removing
    `~|`/`|~` pairs would leave `Carve a ~log |canoe`.
    """
    assert strip_task_markup("Carve a ~log |canoe|~") == "Carve a log canoe"
    assert strip_task_markup("Carve a ~stable dugout |canoe|~") == "Carve a stable dugout canoe"


def test_strip_task_markup_leaves_the_variant_separator_and_secondary_marker() -> None:
    """Both are real parts of the stored name, and how upstream renders them
    isn't something this project has located - so they pass through rather
    than being guessed at."""
    assert strip_task_markup("Build a ~|wooden hull#Raft|~") == "Build a wooden hull#Raft"
    assert strip_task_markup("Kill a runite golem*") == "Kill a runite golem*"


def test_a_backup_challenge_is_dropped_once_its_parent_is_valid() -> None:
    """`BackupParent` names the proper way to do the same thing; the backup
    exists only while that is out of reach. The reported bug: `Barehanded
    catch a wandering lucky impling` (Level 99) outranked its own parent and
    became the active Hunter task despite the account owning a net.
    """
    info = _chunk_info(
        challenges={
            "Hunter": {
                "Catch a butterfly": {"Level": 1, "Primary": True},
                "Catch a wandering lucky impling": {"Level": 89, "Items": ["Butterfly net"]},
                "Barehanded catch a wandering lucky impling": {
                    "Level": 99,
                    "BackupParent": "Catch a wandering lucky impling",
                },
            }
        }
    )
    with_net = SourceIndex(
        items={"Butterfly net": {"100": "shop"}},
        objects={},
        monsters={},
        npcs={},
        shops={},
        drop_rates={},
    )

    barehanded_only = calc_challenges({}, {}, _EMPTY, info, rules={})
    with_the_net = calc_challenges({}, {}, with_net, info, rules={})

    # No net: the parent can't be done, so the backup stands.
    assert barehanded_only.valid == {
        "Hunter": {"Catch a butterfly": 1, "Barehanded catch a wandering lucky impling": 99}
    }
    # Net: the parent is possible, so the backup is deleted outright.
    assert with_the_net.valid == {
        "Hunter": {"Catch a butterfly": 1, "Catch a wandering lucky impling": 89}
    }


def test_a_backlogged_parent_also_drops_the_backup() -> None:
    """Upstream counts a backlogged parent the same as a valid one -
    backlogging is a deliberate "not this one", not a reason to offer the
    fallback instead."""
    info = _chunk_info(
        challenges={
            "Hunter": {
                "Catch a butterfly": {"Level": 1, "Primary": True},
                "Catch a wandering lucky impling": {"Level": 89, "Items": ["Butterfly net"]},
                "Barehanded catch a wandering lucky impling": {
                    "Level": 99,
                    "BackupParent": "Catch a wandering lucky impling",
                },
            }
        }
    )

    result = calc_challenges(
        {}, {}, _EMPTY, info, rules={}, backlog={"Hunter": {"Catch a wandering lucky impling": ""}}
    )

    assert result.valid == {"Hunter": {"Catch a butterfly": 1}}


def test_manual_valid_exempts_a_backup_from_being_dropped() -> None:
    info = _chunk_info(
        challenges={
            "Hunter": {
                "Catch a butterfly": {"Level": 1, "Primary": True},
                "Catch a wandering lucky impling": {"Level": 89},
                "Barehanded catch a wandering lucky impling": {
                    "Level": 99,
                    "BackupParent": "Catch a wandering lucky impling",
                    "ManualValid": True,
                },
            }
        }
    )

    result = calc_challenges({}, {}, _EMPTY, info, rules={})

    assert set(result.valid["Hunter"]) == {
        "Catch a butterfly",
        "Catch a wandering lucky impling",
        "Barehanded catch a wandering lucky impling",
    }


def test_a_backup_whose_parent_is_unknown_is_left_alone() -> None:
    info = _chunk_info(
        challenges={
            "Hunter": {
                "Catch a butterfly": {"Level": 1, "Primary": True},
                "Barehanded catch a wandering lucky impling": {
                    "Level": 99,
                    "BackupParent": "Catch a wandering lucky impling",
                },
            }
        }
    )

    result = calc_challenges({}, {}, _EMPTY, info, rules={})

    assert result.valid == {
        "Hunter": {"Catch a butterfly": 1, "Barehanded catch a wandering lucky impling": 99}
    }


def test_an_untrainable_skill_keeps_only_its_level_one_challenges() -> None:
    """How upstream locks a skill behind a quest. `Herblore`'s only Level 1
    `Primary` route is `Unlock ~|Herblore|~ after Druidic Ritual`; while that
    quest is out of reach the skill is untrainable and everything above
    Level 1 is discarded outright, not merely deprioritised.
    """
    info = _chunk_info(
        challenges={
            "Herblore": {
                "Unlock Herblore after Druidic Ritual": {
                    "Level": 1,
                    "Primary": True,
                    "Tasks": {"Druidic Ritual": "Quest"},
                },
                "Clean a grimy guam leaf": {"Level": 3, "Primary": True},
                "Mix a super combat potion": {"Level": 90, "Primary": True},
            },
            "Quest": {"Druidic Ritual": {"Chunks": ["100"]}},
        }
    )

    locked = calc_challenges({}, {}, _EMPTY, info, rules={})
    unlocked = calc_challenges({"100": True}, {}, _EMPTY, info, rules={})

    # Quest out of reach -> the unlock is invalid -> only Level 1 survives,
    # and the unlock itself is Level 1 but invalid, so nothing does.
    assert "Herblore" not in locked.valid
    # Quest reachable -> the unlock is valid -> the skill trains normally.
    assert set(unlocked.valid["Herblore"]) == {
        "Unlock Herblore after Druidic Ritual",
        "Clean a grimy guam leaf",
        "Mix a super combat potion",
    }


def test_an_untrainable_skill_with_a_passive_floor_is_left_alone() -> None:
    info = _chunk_info(challenges={"Herblore": {"Mix a potion": {"Level": 40}}})

    pruned = calc_challenges({}, {}, _EMPTY, info, rules={})
    spared = calc_challenges({}, {}, _EMPTY, info, rules={}, passive_skill={"Herblore": 55})

    assert pruned.valid == {}
    assert spared.valid == {"Herblore": {"Mix a potion": 40}}


def test_monster_plus_is_a_wildcard_for_any_monster() -> None:
    """`Monster[+]` has no `monstersPlus` entry; upstream reads it as "any
    monster at all" rather than an unsatisfiable family (worker.js:4306).
    Getting this wrong made `Cast ~|wind strike|~` - Magic's only Level 1
    `Primary` route on the real map - permanently invalid, which in turn
    reported the whole skill untrainable.
    """
    info = _chunk_info(
        challenges={"Magic": {"Cast wind strike": {"Level": 1, "Primary": True, "Monsters": ["Monster[+]"]}}}
    )
    with_monster = SourceIndex(
        items={}, objects={}, monsters={"Goblin": {"100": True}}, npcs={}, shops={}, drop_rates={}
    )

    assert calc_challenges({}, {}, _EMPTY, info, rules={}).valid == {}
    assert calc_challenges({}, {}, with_monster, info, rules={}).valid == {
        "Magic": {"Cast wind strike": 1}
    }


def test_an_unknown_plus_family_is_still_unsatisfiable() -> None:
    """Only `Monster[+]` gets the wildcard treatment - a `[+]` name with no
    family table stays a dead requirement otherwise."""
    info = _chunk_info(
        challenges={"Magic": {"Cast it": {"Level": 1, "Primary": True, "Monsters": ["Dragon[+]"]}}}
    )
    with_monster = SourceIndex(
        items={}, objects={}, monsters={"Goblin": {"100": True}}, npcs={}, shops={}, drop_rates={}
    )

    assert calc_challenges({}, {}, with_monster, info, rules={}).valid == {}
