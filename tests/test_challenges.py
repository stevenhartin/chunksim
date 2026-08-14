"""Tests for the core challenge-validity fixed point."""

from __future__ import annotations

from typing import Any

import pytest

from chunksim.derive.challenges import (
    UNSUPPORTED_CATEGORIES,
    _compile_items,
    _item_plan_met,
    _is_secondary,
    _items_requirement_met,
    _objects_requirement,
    _seedable_objects,
    calc_challenges,
    contains_sections,
    has_allowed_source,
    only_shop,
)
from chunksim.derive.pipeline import MapState, derive
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.derive.sources import SourceIndex, gather_chunks_info

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
            # Level 1 + Primary keeps Slayer trainable; an untrainable skill
            # is pruned to its Level 1 challenges *inside* the fixed point,
            # which would collapse the dependency under test.
            "Slayer": {"Do slayer": {"Level": 1, "Primary": True}},
        }
    )

    result = calc_challenges({}, {}, _EMPTY, info, rules={})

    assert result.valid["Nonskill"] == {"Needs slayer": True}


def test_tasks_family_requirement_needs_one_valid_member() -> None:
    info = _chunk_info(
        challenges={
            "Nonskill": {"Needs a master": {"Tasks": {"Masters[+]x1": "Slayer"}}},
            "Slayer": {"Ask Vannaka": {"Level": 1, "Primary": True}},
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


def test_a_valid_challenges_output_object_feeds_the_next_pass_as_a_new_object() -> None:
    """The `Output Object` twin of the test above, and the whole of the
    salvaging-hook chain in miniature: nothing on the map holds a hook, one
    valid challenge builds one, and the challenge requiring one follows.
    """
    info = _chunk_info(
        challenges={
            "Construction": {
                "Build a plank": {"Level": 1, "Primary": True},
                "Build a hook": {"Output Object": "Bronze salvaging hook"},
            },
            "Nonskill": {"Salvage a wreck": {"Objects": ["Bronze salvaging hook"]}},
        }
    )

    result = calc_challenges({}, {}, _EMPTY, info, rules={})

    assert result.valid["Nonskill"] == {"Salvage a wreck": True}
    assert result.available_objects["Bronze salvaging hook"] == {
        "Build a hook": "primary-Construction"
    }


def test_a_seeded_object_satisfies_a_family_requirement() -> None:
    """`AnySalvagingHook[+]` is an `objectsPlus` family, so the deferral has to
    survive the family expansion as well as the plain name.
    """
    info = _chunk_info(
        challenges={
            "Construction": {
                "Build a plank": {"Level": 1, "Primary": True},
                "Build a hook": {"Output Object": "Rune salvaging hook"},
            },
            "Nonskill": {"Salvage a wreck": {"Objects": ["AnyHook[+]"]}},
        },
        codeItems={"objectsPlus": {"AnyHook[+]": ["Bronze salvaging hook", "Rune salvaging hook"]}},
    )

    assert calc_challenges({}, {}, _EMPTY, info, rules={}).valid["Nonskill"] == {
        "Salvage a wreck": True
    }


def test_a_backlogged_build_does_not_seed_its_object() -> None:
    """Upstream's own gate (worker.js:3036): backlogging the build says you
    will not do it, so what it would have made must not arrive anyway.
    """
    info = _chunk_info(
        challenges={
            "Construction": {
                "Build a plank": {"Level": 1, "Primary": True},
                "Build a hook": {"Output Object": "Bronze salvaging hook"},
            },
            "Nonskill": {"Salvage a wreck": {"Objects": ["Bronze salvaging hook"]}},
        }
    )

    result = calc_challenges(
        {}, {}, _EMPTY, info, rules={}, backlog={"Construction": {"Build a hook": True}}
    )

    assert "Nonskill" not in result.valid
    assert "Bronze salvaging hook" not in result.available_objects


def test_an_objects_requirement_no_challenge_builds_is_still_decided_once() -> None:
    """The tri-state is what keeps `Objects` out of the sweeps, so it is worth
    asserting rather than inferring from the answers being right: a met
    requirement and an unbuildable one are both settled against the base
    index, and only a *seedable* absence defers.
    """
    info = _chunk_info(
        challenges={"Construction": {"Build a hook": {"Output Object": "Bronze salvaging hook"}}}
    )
    seedable = _seedable_objects(info.challenges)
    present = {"Anvil": {"100": True}}

    assert _objects_requirement({"Objects": ["Anvil"]}, present, info, seedable) is True
    assert _objects_requirement({"Objects": ["Furnace"]}, present, info, seedable) is False
    assert _objects_requirement({}, present, info, seedable) is True
    assert _objects_requirement(
        {"Objects": ["Bronze salvaging hook"]}, present, info, seedable
    ) == (("Bronze salvaging hook",),)


def test_seeding_objects_only_ever_adds() -> None:
    """The property the split leans on: an `Objects` requirement the base index
    already meets can never stop being met, which is what lets it be decided
    once.
    """
    index = SourceIndex(
        items={},
        objects={"Anvil": {"100": True}},
        monsters={},
        npcs={},
        shops={},
        drop_rates={},
    )
    info = _chunk_info(
        challenges={"Construction": {"Build a hook": {"Output Object": "Bronze salvaging hook"}}}
    )

    result = calc_challenges({}, {}, index, info, rules={})

    assert set(result.available_objects) >= set(index.objects)


@pytest.mark.real_export
def test_the_salvaging_hook_chain_is_joined_end_to_end(real_export: ChunkInfo) -> None:
    """The export's own shape, asserted rather than remembered: every hook is
    something a challenge *builds*, and the family the shipwrecks require
    names exactly those. This is the join that was read as broken - the
    family was looked for in `itemsPlus`, where it is a stray `null`.
    """
    seedable = _seedable_objects(real_export.challenges)
    family = (real_export.code_items.get("objectsPlus") or {})["AnySalvagingHook[+]"]

    assert set(family) <= seedable
    assert len(family) == 7
    assert (real_export.code_items.get("itemsPlus") or {}).get("AnySalvagingHook[+]") is None


@pytest.mark.real_cache
def test_a_map_holding_the_shipyard_can_build_a_hook_and_salvage_with_it(
    real_export: ChunkInfo, real_state: tuple[MapState, dict[str, bool]]
) -> None:
    """The end-to-end oracle for `Output Object`, and it needs every chunk:
    `8234-1` is the Shipyard and no cached map reaches it.

    Before the port `source_index.objects` held **zero** salvaging hooks
    however many were buildable, so all eight shipwrecks were invalid and 243
    Sailing challenges followed them down.
    """
    state, _ = real_state
    everywhere = {chunk_id: True for chunk_id in real_export.data.get("chunks", {})}

    derived = derive(state, everywhere)

    hooks = {n for n in derived.challenges.available_objects if n.endswith("salvaging hook")}
    assert len(hooks) == 7
    assert {n for n in derived.challenges.valid["Sailing"] if n.startswith("Salvage at a ")}
    # The point of the port: nothing in an unlocked chunk holds a hook.
    assert not hooks & set(derived.source_index.objects)


def test_only_a_marked_ingredient_can_make_a_method_secondary() -> None:
    """The `*` is upstream's consumed-secondary marker. An unmarked entry is a
    tool you buy once, and charging the flag to it would call every
    Woodcutting method a by-product for owning an axe.
    """
    info = _chunk_info()
    by_product = {"Ore": {"Some quest": "secondary-Quest"}}

    assert _is_secondary({"Items": ["Ore*"]}, by_product, info, {}) is True
    assert _is_secondary({"Items": ["Ore"]}, by_product, info, {}) is False
    assert _is_secondary({}, by_product, info, {}) is False


@pytest.mark.parametrize("tag", ["primary-Mining", "shop"])
def test_a_real_source_clears_the_secondary_flag(tag: str) -> None:
    """`primary-<skill>` and `shop` are both ways of *getting* the thing, so
    neither leaves the method depending on somebody else's leftovers.
    """
    assert _is_secondary({"Items": ["Ore*"]}, {"Ore": {"x": tag}}, _chunk_info(), {}) is False


def test_one_usable_family_member_clears_the_flag_for_the_whole_family() -> None:
    info = _chunk_info(codeItems={"itemsPlus": {"Ore[+]": ["Copper ore", "Tin ore"]}})
    items = {"Copper ore": {"q": "secondary-Quest"}, "Tin ore": {"m": "primary-Mining"}}

    only_by_product = {"Copper ore": items["Copper ore"]}

    assert _is_secondary({"Items": ["Ore[+]*"]}, items, info, {}) is False
    assert _is_secondary({"Items": ["Ore[+]*"]}, only_by_product, info, {}) is True


def test_the_farming_clause_applies_to_a_plain_item_and_not_to_a_family() -> None:
    """Upstream writes the same test twice and the two are not the same
    (worker.js:4014 against 4086). In the plain form `-Farming` is a
    conjunct, so a farmed source leaves the method secondary unless
    `Farming Primary` is on; in the family form it sits inside a disjunct
    that has already fired, so it is dead. Ported as written rather than
    reconciled - see `_secondary_source_ok`.
    """
    info = _chunk_info(codeItems={"itemsPlus": {"Herb[+]": ["Guam"]}})
    farmed = {"Guam": {"patch": "primary-Farming"}}

    assert _is_secondary({"Items": ["Guam*"]}, farmed, info, {}) is True
    assert _is_secondary({"Items": ["Guam*"]}, farmed, info, {"Farming Primary": True}) is False
    assert _is_secondary({"Items": ["Herb[+]*"]}, farmed, info, {}) is False


def test_a_secondary_primary_method_does_not_make_its_skill_trainable() -> None:
    """The one live consequence of the marker (worker.js:5135), end to end:
    a skill whose only training method consumes something obtainable solely
    as a by-product is untrainable, and an untrainable skill keeps nothing
    above level 1.
    """
    info = _chunk_info(
        challenges={
            "Smithing": {
                "Smelt a bar": {"Level": 1, "Primary": True, "Items": ["Ore*"]},
                "Smith a sword": {"Level": 50},
            }
        }
    )

    def index(tag: str) -> SourceIndex:
        return SourceIndex(
            items={"Ore": {"Somewhere": tag}},
            objects={},
            monsters={},
            npcs={},
            shops={},
            drop_rates={},
        )

    trainable = calc_challenges({}, {}, index("primary-Mining"), info, rules={}).valid
    by_product = calc_challenges({}, {}, index("secondary-Quest"), info, rules={}).valid

    assert trainable["Smithing"] == {"Smelt a bar": 1, "Smith a sword": 50}
    assert by_product["Smithing"] == {"Smelt a bar": 1}


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


def _axes(**extra: Any) -> ChunkInfo:
    """An `Extra` `Set` in the export's own key order, best first.

    `Priority` is lower-is-better, so `infernal` outranks the rest. No
    `Items`, so every member is valid until the sweep says otherwise - the
    ladder, not the reachability, is what these tests are about.
    """
    challenges = {
        "Obtain an infernal axe": {"Set": "BIS Axe", "Priority": 3},
        "Obtain a dragon axe": {"Set": "BIS Axe", "Priority": 5},
        "Obtain a steel axe": {"Set": "BIS Axe", "Priority": 15},
        "Obtain a herb sack": {"Set": "BIS Herb Sack", "Priority": 2},
    }
    for name, fields in extra.items():
        challenges[name.replace("_", " ")] = fields
    return _chunk_info(challenges={"Extra": challenges})


def test_a_worse_set_member_is_dropped_once_a_better_one_is_valid() -> None:
    """The reported bug: a player holding an infernal axe was still being
    told to obtain the steel, mithril, adamant and dragon ones. A `Set` is
    one slot's interchangeable ladder, and only its best reachable rung is
    worth chasing. Other sets are untouched - the sweep is per-`Set`."""
    result = calc_challenges({}, {}, _EMPTY, _axes(), rules={})

    assert set(result.valid["Extra"]) == {"Obtain an infernal axe", "Obtain a herb sack"}


def test_a_better_set_member_listed_later_leaves_the_earlier_one_standing() -> None:
    """Upstream's sweep keeps the running *minima*, not the single best: the
    delete meant for the beaten incumbent reads `.Set` off the challenge's
    value rather than the challenge, so it lands on nothing and the incumbent
    survives. This is not hypothetical - the real export lists `BIS Angler
    Hat`'s ordinary hat (`Priority` 2) before the spirit one (`Priority` 1),
    so a player who can reach both is offered both.
    """
    info = _chunk_info(
        challenges={
            "Extra": {
                "Obtain the angler hat": {"Set": "BIS Angler Hat", "Priority": 2},
                "Obtain the spirit angler headband": {"Set": "BIS Angler Hat", "Priority": 1},
                "Obtain a straw hat": {"Set": "BIS Angler Hat", "Priority": 9},
            }
        }
    )

    result = calc_challenges({}, {}, _EMPTY, info, rules={})

    # The straw hat loses to whichever member is incumbent by then; the two
    # that each beat everything before them both stay.
    assert set(result.valid["Extra"]) == {
        "Obtain the angler hat",
        "Obtain the spirit angler headband",
    }


def test_a_backlogged_set_member_is_dropped_and_stops_outclassing() -> None:
    """Upstream refuses a backlogged `Set` member back in `checkChallenge`
    (`'Set outclassed'`), so it never reaches the sweep - backlogging the
    best rung has to promote the next one, not leave the whole ladder
    deleted by a challenge the player has said no to."""
    result = calc_challenges(
        {}, {}, _EMPTY, _axes(), rules={}, backlog={"Extra": {"Obtain an infernal axe": ""}}
    )

    assert set(result.valid["Extra"]) == {"Obtain a dragon axe", "Obtain a herb sack"}


def test_manual_valid_exempts_a_set_member_from_being_outclassed() -> None:
    """`ManualValid` is upstream's "I said so" flag, checked in the two
    branches that delete and not in the one that takes the first incumbent."""
    info = _chunk_info(
        challenges={
            "Extra": {
                "Obtain an infernal axe": {"Set": "BIS Axe", "Priority": 3},
                "Obtain a dragon axe": {"Set": "BIS Axe", "Priority": 5, "ManualValid": True},
                "Obtain a steel axe": {"Set": "BIS Axe", "Priority": 15},
            }
        }
    )

    result = calc_challenges({}, {}, _EMPTY, info, rules={})

    assert set(result.valid["Extra"]) == {"Obtain an infernal axe", "Obtain a dragon axe"}


def test_a_set_of_one_survives_intact() -> None:
    info = _chunk_info(challenges={"Extra": {"Obtain a herb sack": {"Set": "BIS Herb Sack", "Priority": 2}}})

    result = calc_challenges({}, {}, _EMPTY, info, rules={})

    assert result.valid == {"Extra": {"Obtain a herb sack": True}}


@pytest.mark.real_export
def test_only_bis_skilling_challenges_carry_a_set(real_export: ChunkInfo) -> None:
    """What `_drop_outclassed_extra_sets` rests on: `Set` lives only on
    `Extra`, only on `BIS Skilling` entries, and always beside an integer
    `Priority`. A `Set` appearing elsewhere - or without a `Priority` - would
    put the sweep somewhere it has never been measured.
    """
    carriers = {
        (category, name): challenge
        for category, entries in real_export.challenges.items()
        for name, challenge in entries.items()
        if isinstance(challenge, dict) and "Set" in challenge
    }

    assert carriers, "the export no longer defines any Set"
    assert {category for category, _ in carriers} == {"Extra"}
    assert all(challenge.get("Label") == "BIS Skilling" for challenge in carriers.values())
    assert all(
        isinstance(challenge.get("Priority"), int) and not isinstance(challenge["Priority"], bool)
        for challenge in carriers.values()
    )


@pytest.mark.real_export
def test_extra_challenges_carry_no_level_so_the_export_order_is_the_sweep_order(
    real_export: ChunkInfo,
) -> None:
    """Upstream sweeps `newValids['Extra']` in insertion order, and those
    entries are inserted by a scan sorted on `Description` then `Level`
    (worker.js:3673). No `Extra` challenge has either, so that comparator is
    `NaN` throughout and the export's own key order survives into the sweep -
    which is the order `_drop_outclassed_extra_sets` iterates. An `Extra`
    entry growing a `Level` would quietly reorder upstream's sweep and not
    ours.
    """
    extra = real_export.challenges["Extra"]

    assert not [
        name
        for name, challenge in extra.items()
        if isinstance(challenge, dict) and ("Level" in challenge or "Description" in challenge)
    ]


def _shortcut_map() -> ChunkInfo:
    """Agility trainable *only* by a shortcut - the `Shortcut` category's
    whole point, and the case the rule is there to switch off."""
    return _chunk_info(
        challenges={
            "Agility": {
                "Squeeze past the ~|loose railing|~": {
                    "Level": 1,
                    "Primary": True,
                    "Category": ["Shortcut"],
                },
                "Climb the ~|basalt rock|~": {"Level": 60, "Category": ["Shortcut"]},
            }
        }
    )


def test_a_shortcut_stops_training_agility_when_its_rule_is_off() -> None:
    """`maybePrimary`: these categories are primary only while their rule is
    ticked. With `Shortcut` off the only `Primary` Agility challenge stops
    counting, `checkPrimaryMethod` calls the skill untrainable, and
    everything above Level 1 is pruned. On the oracle map this is 177
    challenges; here it is the one.
    """
    on = calc_challenges({}, {}, _EMPTY, _shortcut_map(), rules={"Shortcut": True})
    off = calc_challenges({}, {}, _EMPTY, _shortcut_map(), rules={"Shortcut": False})

    assert set(on.valid["Agility"]) == {
        "Squeeze past the ~|loose railing|~",
        "Climb the ~|basalt rock|~",
    }
    assert set(off.valid["Agility"]) == {"Squeeze past the ~|loose railing|~"}


def test_the_shortcut_category_is_still_exempt_from_the_ordinary_rule_gate() -> None:
    """The downgrade is the *other* half of `maybePrimary`. A `Shortcut`
    challenge with the rule off must lose its `Primary` flag, not its
    validity - upstream's gate skips these four categories outright, so
    turning the rule off never invalidates one on its own."""
    info = _chunk_info(
        challenges={
            "Agility": {
                "Walk about": {"Level": 1, "Primary": True},
                "Climb the ~|basalt rock|~": {"Level": 60, "Category": ["Shortcut"]},
            }
        }
    )

    off = calc_challenges({}, {}, _EMPTY, info, rules={"Shortcut": False})

    assert "Climb the ~|basalt rock|~" in off.valid["Agility"]


def test_an_unruled_category_leaves_the_primary_flag_alone() -> None:
    """Only the four `maybePrimary` categories are affected; an ordinary
    category's rule gates validity and never touches `Primary`."""
    info = _chunk_info(
        challenges={
            "Agility": {
                "Squeeze past the ~|loose railing|~": {
                    "Level": 1,
                    "Primary": True,
                    "Category": ["Minigame"],
                },
                "Climb the ~|basalt rock|~": {"Level": 60},
            }
        }
    )

    result = calc_challenges({}, {}, _EMPTY, info, rules={"Minigame": True})

    assert set(result.valid["Agility"]) == {
        "Squeeze past the ~|loose railing|~",
        "Climb the ~|basalt rock|~",
    }


_MTA = "Participate in all parts of the ~|Magic Training Arena|~"


def _mta_map() -> ChunkInfo:
    """The one challenge upstream ever sets `forcedPrimary` on, consuming an
    ingredient that has only a by-product source."""
    return _chunk_info(
        challenges={
            "Magic": {
                "Cast a spell": {"Level": 1, "Primary": True},
                _MTA: {"Level": 33, "Items": ["Nature rune*"]},
            }
        }
    )


def _byproduct_runes() -> SourceIndex:
    return SourceIndex(
        items={"Nature rune": {"Kill a thing": "secondary-drop"}},
        objects={}, monsters={}, npcs={}, shops={}, drop_rates={},
    )


def test_secondary_mta_off_invalidates_a_by_product_only_arena_run() -> None:
    """`forcedPrimary && Secondary -> invalid`. With the rule off the arena
    has to be reachable as a primary method, and an ingredient available only
    as somebody else's by-product does not qualify."""
    result = calc_challenges(
        {}, {}, _byproduct_runes(), _mta_map(), rules={"Secondary MTA": False}
    )

    assert _MTA not in result.valid["Magic"]


def test_secondary_mta_on_leaves_the_arena_valid() -> None:
    """On, `forcedPrimary` is false and the gate never fires - which is why
    neither cached map sees this."""
    result = calc_challenges(
        {}, {}, _byproduct_runes(), _mta_map(), rules={"Secondary MTA": True}
    )

    assert _MTA in result.valid["Magic"]


def test_the_forced_primary_gate_is_limited_to_the_arena() -> None:
    """`forcedPrimary` is set on one challenge by name, not on a shape - any
    other by-product-only Magic challenge stays valid with the rule off."""
    info = _chunk_info(
        challenges={
            "Magic": {
                "Cast a spell": {"Level": 1, "Primary": True},
                "Bind something": {"Level": 33, "Items": ["Nature rune*"]},
            }
        }
    )

    result = calc_challenges(
        {}, {}, _byproduct_runes(), info, rules={"Secondary MTA": False}
    )

    assert "Bind something" in result.valid["Magic"]


def _smelting_map() -> ChunkInfo:
    """Smithing whose only `Primary` route is above the passive floor, so
    `_has_primary_task` refuses it and the `manualTasks` branch of
    `checkPrimaryMethod` is what decides whether the skill is trainable."""
    return _chunk_info(
        challenges={
            "Smithing": {
                "Smelt a ~|runite bar|~": {"Level": 85, "Primary": True},
                "Smith a ~|rune platebody|~": {"Level": 99},
            }
        }
    )


_SMELT = {"Smithing": {"Smelt a ~|runite bar|~": 85}}


def _with_anvil() -> SourceIndex:
    return SourceIndex(
        items={}, objects={"Anvil": {"100": True}},
        monsters={}, npcs={}, shops={}, drop_rates={},
    )


def test_smelting_alone_does_not_train_smithing_when_its_rule_is_off() -> None:
    """worker.js:5226. A manually-added smelting task proves nothing about
    Smithing unless there is an anvil to hammer on - with the rule off and no
    anvil the skill is untrainable, and a challenge that needs it goes."""
    result = calc_challenges(
        {}, {}, _EMPTY, _smelting_map(),
        rules={"Smithing by Smelting": False},
        manual_tasks=_SMELT,
    )

    assert "Smith a ~|rune platebody|~" not in result.valid.get("Smithing", {})


def test_an_anvil_trains_smithing_whatever_the_rule_says() -> None:
    result = calc_challenges(
        {}, {}, _with_anvil(), _smelting_map(),
        rules={"Smithing by Smelting": False},
        manual_tasks=_SMELT,
    )

    assert "Smith a ~|rune platebody|~" in result.valid["Smithing"]


def test_smithing_by_smelting_on_needs_no_anvil() -> None:
    """On, the condition short-circuits - which is the state both cached maps
    are in, and why not modelling this was invisible."""
    result = calc_challenges(
        {}, {}, _EMPTY, _smelting_map(),
        rules={"Smithing by Smelting": True},
        manual_tasks=_SMELT,
    )

    assert "Smith a ~|rune platebody|~" in result.valid["Smithing"]


def _clue_map(steps_valid: int) -> ChunkInfo:
    """Four `easy` clue steps, `steps_valid` of them reachable, plus one
    reward task gated on that tier."""
    nonskill = {
        f"Clue step {i}": {"ClueTier": "easy", "Level": 1, **({} if i < steps_valid else {"Chunks": ["999"]})}
        for i in range(4)
    }
    return _chunk_info(
        challenges={
            "Nonskill": nonskill,
            "Extra": {
                "Obtain a ~|ranger boot|~": {
                    "Category": ["Collection Log", "Collection Log Clues"],
                    "ClueRewardTier": "easy",
                    "Label": "Collection Log",
                }
            },
        }
    )


def _clue_rules(**over: Any) -> dict[str, Any]:
    return {"Collection Log": True, "Collection Log Clues": True, **over}


def test_a_clue_reward_waits_until_its_tier_is_reachable_enough() -> None:
    """The half of `Collection Log Clues` that was missing. The category gate
    decides whether the 517 reward tasks are in play at all; this decides
    which of them, by the share of that tier's steps the map can actually do
    against `Collection Log Clues Amount`.
    """
    half = calc_challenges(
        {}, {}, _EMPTY, _clue_map(2), rules=_clue_rules(**{"Collection Log Clues Amount": "50"})
    )
    all_four = calc_challenges(
        {}, {}, _EMPTY, _clue_map(4), rules=_clue_rules(**{"Collection Log Clues Amount": "50"})
    )

    assert "Obtain a ~|ranger boot|~" in half.valid["Extra"]
    assert "Obtain a ~|ranger boot|~" in all_four.valid["Extra"]


def test_a_tier_short_of_the_bar_keeps_its_rewards_out() -> None:
    result = calc_challenges(
        {}, {}, _EMPTY, _clue_map(2), rules=_clue_rules(**{"Collection Log Clues Amount": "100"})
    )

    assert "Extra" not in result.valid


def test_the_shipped_default_of_100_wants_the_whole_tier() -> None:
    """`Collection Log Clues Amount` is `"100"` in upstream's defaults and in
    both cached maps, so a reward task needs *every* step of its tier - which
    is why turning the rule on used to add 519 tasks here and rather fewer
    upstream."""
    result = calc_challenges(
        {}, {}, _EMPTY, _clue_map(4), rules=_clue_rules(**{"Collection Log Clues Amount": "100"})
    )

    assert "Obtain a ~|ranger boot|~" in result.valid["Extra"]


def test_the_gate_sleeps_while_the_rule_is_off() -> None:
    """Off, the category gate has already taken the task out, so the tier
    share is never consulted - and turning the rule off must not resurrect
    anything."""
    result = calc_challenges(
        {}, {}, _EMPTY, _clue_map(0), rules={"Collection Log": True, "Collection Log Clues": False}
    )

    assert "Extra" not in result.valid


def test_a_reward_task_with_no_tier_is_not_gated() -> None:
    """Upstream reads `ClueRewardTier` with `hasOwnProperty`; 517 export
    entries carry one, and a `Collection Log Clues` challenge without one
    passes untouched."""
    info = _chunk_info(
        challenges={
            "Extra": {
                "Obtain a ~|clue box|~": {
                    "Category": ["Collection Log", "Collection Log Clues"],
                    "Label": "Collection Log",
                }
            }
        }
    )

    result = calc_challenges({}, {}, _EMPTY, info, rules=_clue_rules())

    assert "Obtain a ~|clue box|~" in result.valid["Extra"]


def test_a_tier_the_export_never_mentions_is_refused() -> None:
    """Upstream's `||` has two clauses and they are opposite: a tier *absent*
    from the table fails, where a tier present but immeasurable passes."""
    info = _chunk_info(
        challenges={
            "Extra": {
                "Obtain a ~|third-age boot|~": {
                    "Category": ["Collection Log Clues"],
                    "ClueRewardTier": "legendary",
                }
            }
        }
    )

    result = calc_challenges({}, {}, _EMPTY, info, rules=_clue_rules())

    assert "Extra" not in result.valid


def _fishing_world(**over: Any) -> ChunkInfo:
    return _chunk_info(
        challenges={"Fishing": {"Catch a ~|shrimp|~": {"Level": 1, "Primary": True, **over}}}
    )


def test_a_trainable_skill_puts_its_pet_within_reach() -> None:
    """A skilling pet is not dropped or sold - it falls out of doing the
    skill, so upstream adds it to the item index directly. The tag is
    `secondary-<skill>`, which keeps it from ever counting as a way to train
    anything: nobody trains Fishing by fishing up a Heron."""
    result = calc_challenges({}, {}, _EMPTY, _fishing_world(), rules={"Skilling Pets": True})

    assert result.available_items["Heron"] == {"Manually Added*": "secondary-Fishing"}


def test_no_pet_without_the_rule() -> None:
    result = calc_challenges({}, {}, _EMPTY, _fishing_world(), rules={})

    assert "Heron" not in result.available_items


def test_a_task_flagged_nopet_earns_nothing() -> None:
    result = calc_challenges(
        {}, {}, _EMPTY, _fishing_world(NoPet=True), rules={"Skilling Pets": True}
    )

    assert "Heron" not in result.available_items


def test_a_task_with_prose_earns_nothing_either() -> None:
    """`Description` marks the quest and diary steps folded into a skill;
    upstream excludes them from earning a pet the same way it excludes
    `NoPet`."""
    result = calc_challenges(
        {}, {}, _EMPTY, _fishing_world(Description="Speak to the fisherman."),
        rules={"Skilling Pets": True},
    )

    assert "Heron" not in result.available_items


def test_an_untrainable_skill_earns_nothing() -> None:
    """The pet needs the skill trainable, not merely present: a `Fishing`
    challenge above Level 1 with no primary route leaves the skill untrainable
    and the Heron out of reach."""
    info = _chunk_info(challenges={"Fishing": {"Catch a ~|shark|~": {"Level": 76}}})

    result = calc_challenges({}, {}, _EMPTY, info, rules={"Skilling Pets": True})

    assert "Heron" not in result.available_items


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


def _diary_info(**rules_unused: Any) -> ChunkInfo:
    return _chunk_info(
        challenges={
            "Diary": {
                "~|Varrock Diary#Easy|~ Task 1": {"BaseQuest": "Varrock Diary"},
                "~|Varrock Diary#Easy|~ Complete the Easy Diary": {
                    "BaseQuest": "Varrock Diary",
                    "Reward": ["Varrock armour 1"],
                    "Tasks": {"~|Varrock Diary#Easy|~ Task 1": "Diary"},
                },
                "~|Varrock Diary#Medium|~ Task 10": {
                    "BaseQuest": "Varrock Diary",
                    "Chunks": ["100"],
                    "Tasks": {"~|Varrock Diary#Easy|~ Complete the Easy Diary": "Diary"},
                },
            }
        }
    )


def test_show_diary_tasks_any_waives_the_tier_completion_dependency() -> None:
    """A later tier's tasks depend on the previous tier's completion
    challenge, which carries a `Reward`. `Show Diary Tasks Any` - "show all
    diary tasks possible, regardless of tier" - drops that dependency.
    """
    info = _diary_info()

    result = calc_challenges(
        {"100": True}, {}, _EMPTY, info, rules={"Show Diary Tasks Any": True}
    )

    assert "~|Varrock Diary#Medium|~ Task 10" in result.valid["Diary"]


def test_without_the_rule_the_tier_completion_dependency_still_applies() -> None:
    info = _diary_info()

    # The Easy tier's own task needs no chunk, so the tier completion *is*
    # valid here; make it unreachable by withholding the Medium task's chunk
    # only, leaving the dependency as the sole thing under test.
    result = calc_challenges({"100": True}, {}, _EMPTY, info, rules={})

    assert "~|Varrock Diary#Medium|~ Task 10" in result.valid["Diary"]

    # ... and with the Easy tier itself unreachable, the dependency bites.
    blocked = _chunk_info(
        challenges={
            "Diary": {
                "~|Varrock Diary#Easy|~ Complete the Easy Diary": {
                    "BaseQuest": "Varrock Diary",
                    "Chunks": ["999"],
                    "Reward": ["Varrock armour 1"],
                },
                "~|Varrock Diary#Medium|~ Task 10": {
                    "BaseQuest": "Varrock Diary",
                    "Tasks": {"~|Varrock Diary#Easy|~ Complete the Easy Diary": "Diary"},
                },
            }
        }
    )

    off = calc_challenges({}, {}, _EMPTY, blocked, rules={})
    on = calc_challenges({}, {}, _EMPTY, blocked, rules={"Show Diary Tasks Any": True})

    assert off.valid == {}
    assert "~|Varrock Diary#Medium|~ Task 10" in on.valid["Diary"]


def test_the_waiver_never_applies_to_a_tier_completion_itself() -> None:
    """Waiving it for tier-completion challenges too would collapse the
    tiers into one another, so upstream requires the dependent to carry no
    `Reward` of its own."""
    info = _chunk_info(
        challenges={
            "Diary": {
                "~|Varrock Diary#Easy|~ Complete the Easy Diary": {
                    "Chunks": ["999"],
                    "Reward": ["Varrock armour 1"],
                },
                "~|Varrock Diary#Medium|~ Complete the Medium Diary": {
                    "Reward": ["Varrock armour 2"],
                    "Tasks": {"~|Varrock Diary#Easy|~ Complete the Easy Diary": "Diary"},
                },
            }
        }
    )

    result = calc_challenges({}, {}, _EMPTY, info, rules={"Show Diary Tasks Any": True})

    assert result.valid == {}


def test_a_manual_task_is_valid_regardless_of_its_requirements() -> None:
    """`manualTasks` is the player asserting "I can do this", recorded per
    account; upstream writes it straight into valids (worker.js:1168). Not
    applying it hid two `Extra` entries the map's own oracle lists.
    """
    info = _chunk_info(
        challenges={"Extra": {"Obtain an ~|eternal gem|~": {"Items": ["Eternal gem"]}}}
    )

    without = calc_challenges({}, {}, _EMPTY, info, rules={})
    with_manual = calc_challenges(
        {}, {}, _EMPTY, info, rules={},
        manual_tasks={"Extra": {"Obtain an ~|eternal gem|~": True}},
    )

    assert without.valid == {}
    assert with_manual.valid == {"Extra": {"Obtain an ~|eternal gem|~": True}}


def test_a_manual_task_the_export_no_longer_defines_is_ignored() -> None:
    info = _chunk_info(challenges={"Extra": {}})

    result = calc_challenges(
        {}, {}, _EMPTY, info, rules={}, manual_tasks={"Extra": {"Some retired task": True}}
    )

    assert result.valid == {}


def test_a_manual_task_is_never_injected_for_bis() -> None:
    """`BiS` has no static definitions at all - `bis.py` computes it - so
    upstream skips the category here and so must this."""
    info = _chunk_info(challenges={"Extra": {"Obtain a thing": {}}})

    result = calc_challenges(
        {}, {}, _EMPTY, info, rules={}, manual_tasks={"BiS": {"Obtain a whip": True}}
    )

    assert "BiS" not in result.valid


def test_a_manual_task_exempts_a_backup_from_being_dropped() -> None:
    info = _chunk_info(
        challenges={
            "Hunter": {
                "Catch a butterfly": {"Level": 1, "Primary": True},
                "Catch a wandering lucky impling": {"Level": 89},
                "Barehanded catch a wandering lucky impling": {
                    "Level": 99,
                    "BackupParent": "Catch a wandering lucky impling",
                },
            }
        }
    )

    result = calc_challenges(
        {}, {}, _EMPTY, info, rules={},
        manual_tasks={"Hunter": {"Barehanded catch a wandering lucky impling": True}},
    )

    assert "Barehanded catch a wandering lucky impling" in result.valid["Hunter"]


def _subskill_info(needed: dict[str, Any]) -> ChunkInfo:
    """An `Extra` challenge gated on a sub-skill, plus a `Fishing` category
    that is trainable only when its Level 1 `Primary` route is valid."""
    return _chunk_info(
        challenges={
            "Extra": {"Obtain a thing": {"Label": "Collection Log", "Skills": needed}},
            "Fishing": {"Catch a shrimp": {"Level": 1, "Primary": True}},
        }
    )


def test_a_non_skill_challenge_needing_an_untrainable_subskill_is_dropped() -> None:
    """worker.js:8533 - `Extra`/`Quest`/`Diary` have no per-skill winner to
    pick, so upstream instead deletes any challenge whose `Skills` names a
    sub-skill that is untrainable and uncovered by `passiveSkill`.
    """
    info = _chunk_info(
        challenges={
            "Extra": {"Obtain a thing": {"Label": "Collection Log", "Skills": {"Fishing": 40}}},
            "Fishing": {"Catch a shark": {"Level": 76, "Primary": True}},
        }
    )

    result = calc_challenges({}, {}, _EMPTY, info, rules={})

    assert "Extra" not in result.valid


def test_a_trainable_subskill_keeps_the_challenge() -> None:
    info = _subskill_info({"Fishing": 40})

    result = calc_challenges({}, {}, _EMPTY, info, rules={})

    assert "Obtain a thing" in result.valid["Extra"]


def test_a_subskill_requirement_above_max_skill_is_dropped() -> None:
    """The `maxSkill` arm bites even when the sub-skill is trainable."""
    info = _subskill_info({"Fishing": 80})

    result = calc_challenges({}, {}, _EMPTY, info, rules={}, max_skill={"Fishing": 70})

    assert "Extra" not in result.valid


def test_a_manual_task_is_exempt_from_the_subskill_filter() -> None:
    info = _chunk_info(
        challenges={
            "Extra": {"Obtain a thing": {"Label": "Collection Log", "Skills": {"Fishing": 40}}},
            "Fishing": {"Catch a shark": {"Level": 76, "Primary": True}},
        }
    )

    result = calc_challenges(
        {}, {}, _EMPTY, info, rules={}, manual_tasks={"Extra": {"Obtain a thing": True}}
    )

    assert "Obtain a thing" in result.valid["Extra"]


def test_the_subskill_filter_leaves_real_skill_categories_alone() -> None:
    """Only `Extra`/`Quest`/`Diary`/`BiS` go down that branch; a skill
    category's own `Skills` requirement is handled by `_skills_requirement_met`
    during the fixed point instead."""
    info = _chunk_info(
        challenges={
            "Woodcutting": {
                "Chop a sapling": {"Level": 1, "Primary": True},
                "Chop with a fishing rod": {"Level": 5, "Skills": {"Fishing": 40}},
            },
            "Fishing": {"Catch a shark": {"Level": 76, "Primary": True}},
        }
    )

    result = calc_challenges({}, {}, _EMPTY, info, rules={})

    # Dropped by the ordinary `Skills` requirement check, not by the filter -
    # and Woodcutting itself survives, which the filter would not have allowed.
    assert "Chop a sapling" in result.valid["Woodcutting"]


# --- the compiled `Items` plan ----------------------------------------------


@pytest.mark.parametrize(
    ("refs", "items", "expected"),
    [
        (["Bones"], {"Bones": {"Goblin": "primary-drop"}}, True),
        (["Bones"], {}, False),
        # `*` is a secondary marker, stripped and otherwise ignored.
        (["*Bones"], {"Bones": {"Goblin": "primary-drop"}}, True),
        (["Axe[+]"], {"Bronze axe": {"Shop": "shop"}}, True),
        (["Axe[+]"], {"Unrelated": {"Shop": "shop"}}, False),
        # `[+]xN` needs N distinct members of the family.
        (["Axe[+]x2"], {"Bronze axe": {"Shop": "shop"}}, False),
        (["Axe[+]x2"], {"Bronze axe": {"Shop": "shop"}, "Iron axe": {"Shop": "shop"}}, True),
        # An unresolvable family fails the whole requirement.
        (["Nothing[+]"], {"Bronze axe": {"Shop": "shop"}}, False),
    ],
)
def test_a_compiled_item_plan_answers_exactly_as_the_uncompiled_path(
    refs: list[str], items: dict[str, dict[str, str]], expected: bool
) -> None:
    """The compile hoists *parsing* out of the fixed point and nothing else, so
    the two paths must never disagree - `calc_challenges` uses the compiled one
    on every sweep."""
    info = _chunk_info(codeItems={"itemsPlus": {"Axe[+]": ["Bronze axe", "Iron axe"]}})
    challenge: dict[str, Any] = {"Items": refs}

    plan = _compile_items(challenge, info, skill="Nonskill", rules={})
    assert plan is not None
    compiled = _item_plan_met(plan, items)
    uncompiled = _items_requirement_met(challenge, items, info, skill="Nonskill", rules={})

    assert compiled == uncompiled == expected


def test_a_challenge_with_no_items_compiles_to_no_plan() -> None:
    assert _compile_items({"Level": 1}, _chunk_info()) is None


def test_the_item_plan_is_static_but_the_check_is_not() -> None:
    """The plan is built once per `calc_challenges` call and checked against an
    item index that keeps growing - so a requirement unmet on one sweep must
    still be able to pass on the next."""
    info = _chunk_info(codeItems={"itemsPlus": {"Axe[+]": ["Bronze axe"]}})
    challenge: dict[str, Any] = {"Items": ["Axe[+]"]}
    plan = _compile_items(challenge, info, skill="Nonskill", rules={})
    assert plan is not None

    before = _item_plan_met(plan, {})
    after = _item_plan_met(plan, {"Bronze axe": {"Shop": "shop"}})

    assert (before, after) == (False, True)


def test_a_static_gate_rejection_never_reaches_the_dynamic_half() -> None:
    """What the candidate prefilter relies on: a challenge whose `Chunks`,
    `Objects`/`Monsters`/`NPCs`, level or category gate fails cannot be revived
    by anything the fixed point does, because none of those gates read
    anything the fixed point changes."""
    info = _chunk_info(
        challenges={
            "Nonskill": {
                "Open the chest": {"Output": "Iron bar"},
                # Wants the item that `Output` supplies, so the fixed point
                # does reach it - but it sits in a chunk that is not unlocked,
                # which is a static rejection nothing downstream can undo.
                "Use the bar": {"Items": ["Iron bar"], "Chunks": ["999"]},
                # The same requirement without the chunk gate, as a control.
                "Use it here": {"Items": ["Iron bar"]},
            }
        }
    )

    result = calc_challenges({"100": True}, {}, _EMPTY, info, rules={})

    assert result.valid["Nonskill"] == {"Open the chest": True, "Use it here": True}


_SPINY = {"Items": ["Spiny helmet"]}
_HELD = {"Spiny helmet": {"Somewhere": "chunk"}}


def _plan_met(skill: str, challenge: dict[str, Any], blocked: frozenset[str]) -> bool:
    plan = _compile_items(
        challenge, _chunk_info(), skill=skill, rules={}, locked_equipment=blocked
    )
    assert plan is not None
    return _item_plan_met(plan, _HELD)


def test_locked_slayer_gear_cannot_satisfy_a_combat_requirement() -> None:
    """worker.js:4067 - a starred item counts for every skill but a combat
    one, and locked slayer gear is exactly what upstream stars."""
    assert _plan_met("Defence", _SPINY, frozenset({"Spiny helmet"})) is False


def test_locked_slayer_gear_still_satisfies_a_non_combat_requirement() -> None:
    """You can craft a spiny helmet at any Slayer level; what the lock stops
    is wearing it. Dropping the item outright would be a stronger gate than
    upstream has."""
    assert _plan_met("Crafting", _SPINY, frozenset({"Spiny helmet"})) is True


def test_unlocked_slayer_gear_satisfies_a_combat_requirement() -> None:
    assert _plan_met("Defence", _SPINY, frozenset()) is True


def test_a_plus_family_survives_on_a_member_that_is_not_locked_gear() -> None:
    """`Facemask[+]` is satisfiable by anything in the family, so a blocked
    member is struck out rather than failing the whole requirement."""
    info = _chunk_info(codeItems={"itemsPlus": {"Facemask[+]": ["Facemask", "Slayer helmet"]}})
    plan = _compile_items(
        {"Items": ["Facemask[+]"]},
        info,
        skill="Ranged",
        rules={},
        locked_equipment=frozenset({"Facemask"}),
    )

    assert plan is not None
    assert _item_plan_met(plan, {"Slayer helmet": {"Shop": "chunk"}}) is True
    assert _item_plan_met(plan, {"Facemask": {"Shop": "chunk"}}) is False


def _sources(unlocked: dict[str, bool], info: ChunkInfo) -> SourceIndex:
    return gather_chunks_info(unlocked, {}, info, rules={})


def _quest_world(**extra: Any) -> ChunkInfo:
    """A completable quest whose reward is a boat, and something that needs
    the boat - the export's own Pandemonium shape in miniature."""
    extra.setdefault("chunks", {"100": {"NPC": {"Will": True}}})
    return _chunk_info(
        challenges={
            "Quest": {"Sail 1": {"NPCs": ["Will"], "Reward": ["Raft", "Spyglass"]}},
            "Nonskill": {"Set sail": {"Items": ["Raft"]}},
        },
        **extra,
    )


def test_a_valid_quests_reward_becomes_an_available_item() -> None:
    """worker.js:3345-3354. `Reward` was read only as a marker meaning "this
    is a tier or quest completion" and never as a source of items."""
    result = calc_challenges({"100": True}, {}, _sources({"100": True}, _quest_world()),
                             _quest_world(), rules={})

    assert "Raft" in result.available_items
    assert result.valid["Nonskill"] == {"Set sail": True}


def test_an_invalid_quest_hands_over_nothing() -> None:
    info = _quest_world(chunks={"100": {}})

    result = calc_challenges({"100": True}, {}, _sources({"100": True}, info), info, rules={})

    assert "Raft" not in result.available_items
    assert result.valid.get("Nonskill", {}) == {}


def test_a_backlogged_quest_hands_over_nothing() -> None:
    """Backlogging a quest says you will not do it, so its rewards must not
    arrive anyway - upstream gates the seed on `backlog[category]`."""
    info = _quest_world()

    result = calc_challenges(
        {"100": True}, {}, _sources({"100": True}, info), info,
        rules={}, backlog={"Quest": {"Sail 1": True}},
    )

    assert "Raft" not in result.available_items


def test_a_backlogged_reward_item_is_left_out_on_its_own() -> None:
    info = _quest_world()

    result = calc_challenges(
        {"100": True}, {}, _sources({"100": True}, info), info,
        rules={}, backlogged_sources={"items": {"Raft": True}},
    )

    assert "Raft" not in result.available_items
    assert "Spyglass" in result.available_items


@pytest.mark.real_cache
def test_clues_at_the_default_amount_admit_nothing_on_the_oracle_map(
    real_payload: dict[str, Any],
    real_export: ChunkInfo,
    real_tasks_map: dict[str, str],
) -> None:
    """`Collection Log Clues` is off on the oracle map, which is how the
    threshold half of it went unported: the category gate alone let the rule
    add all 517 reward tasks.

    Turning it on at the shipped `"100"` now adds none - no tier on that map
    is fully reachable, the best being three quarters of `beginner` - and
    dropping the bar to 0 admits the lot. The two ends are what make this a
    test of the *threshold* rather than of the category gate.
    """
    import copy

    from chunksim.derive.pipeline import derive, load_map_state

    def extra_valid(**rules: Any) -> int:
        payload = copy.deepcopy(real_payload)
        payload["rules"].update(rules)
        state, unlocked = load_map_state(payload, real_export, real_tasks_map)
        return len(derive(state, unlocked).challenges.valid.get("Extra", {}))

    off = extra_valid()

    assert extra_valid(**{"Collection Log Clues": True}) == off
    assert extra_valid(**{"Collection Log Clues": True, "Collection Log Clues Amount": "0"}) > off
