"""Tests for best-in-slot equipment synthesis."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from fray_claude.bis import (
    article_for,
    build_ammo_index,
    compute_bis,
    format_equip,
)
from fray_claude.chunkinfo import ChunkInfo

_REAL_CHUNKINFO = os.environ.get("FRAY_CHUNKINFO")
_REAL_MAP = os.environ.get("FRAY_MAP_CACHE")


def _chunk_info(**data: Any) -> ChunkInfo:
    return ChunkInfo(data)


def test_article_uses_an_before_a_vowel() -> None:
    assert article_for("Abyssal whip") == " an "


def test_article_uses_a_before_a_consonant() -> None:
    assert article_for("Rune platebody") == " a "


def test_article_is_bare_space_for_a_plural_name() -> None:
    assert article_for("Torag's hammers") == " "


def test_article_is_bare_space_for_a_parenthetical_plural() -> None:
    assert article_for("Rune boots (g)") == " "


def test_format_equip_uses_the_override_when_present() -> None:
    assert format_equip({"formatted_name": "Bandos godsword"}, "Bandos gs") == "Bandos godsword"


def test_format_equip_lowercases_when_no_override() -> None:
    assert format_equip({}, "Rune Platebody") == "rune platebody"


def test_build_ammo_index_inverts_and_skips_no_ammo() -> None:
    index = build_ammo_index(
        {
            "Bronze arrow": {"Shortbow": True, "Longbow": True},
            "Iron arrow": {"Longbow": True},
            "No ammo": {"Unarmed": True},
        }
    )

    assert index == {"Shortbow": ["Bronze arrow"], "Longbow": ["Bronze arrow", "Iron arrow"]}


def test_picks_the_highest_scoring_melee_weapon() -> None:
    info = _chunk_info(
        equipment={
            "Bronze sword": {
                "slot": "weapon",
                "attack_speed": 4,
                "attack_slash": 5,
                "melee_strength": 4,
            },
            "Rune scimitar": {
                "slot": "weapon",
                "attack_speed": 4,
                "attack_slash": 45,
                "melee_strength": 44,
            },
        }
    )
    items = {"Bronze sword": {"Store": "shop"}, "Rune scimitar": {"Store": "shop"}}

    result = compute_bis(info, items, {}, rules={})

    assert result.picks["Melee-weapon"] == "Rune scimitar"


def test_unreachable_items_are_never_picked() -> None:
    info = _chunk_info(
        equipment={
            "Rune scimitar": {
                "slot": "weapon",
                "attack_speed": 4,
                "attack_slash": 45,
                "melee_strength": 44,
            }
        }
    )

    result = compute_bis(info, {}, {}, rules={})

    assert "Melee-weapon" not in result.picks


def test_unarmed_is_a_fallback_melee_weapon() -> None:
    info = _chunk_info(equipment={"Unarmed": {"slot": "weapon", "attack_speed": 4}})

    result = compute_bis(info, {}, {}, rules={})

    assert result.picks["Melee-weapon"] == "Unarmed"


def test_skill_requirement_needs_the_skill_trainable_or_passive() -> None:
    info = _chunk_info(
        equipment={
            "Rune platebody": {"slot": "body", "requirements": {"Defence": 40}},
        }
    )
    items = {"Rune platebody": {"Store": "shop"}}

    untrained = compute_bis(info, items, {}, rules={})
    trained = compute_bis(info, items, {"Defence": {"Some task": True}}, rules={})
    passive = compute_bis(info, items, {}, rules={}, passive_skill={"Defence": 40})

    assert "Melee-body" not in untrained.picks
    assert trained.picks["Melee-body"] == "Rune platebody"
    assert passive.picks["Melee-body"] == "Rune platebody"


def test_skiller_rule_blocks_any_levelled_requirement() -> None:
    info = _chunk_info(equipment={"Rune platebody": {"slot": "body", "requirements": {"Defence": 40}}})
    items = {"Rune platebody": {"Store": "shop"}}

    result = compute_bis(
        info, items, {"Defence": {"Some task": True}}, rules={"Skiller": True}
    )

    assert "Melee-body" not in result.picks


def test_max_skill_caps_a_requirement() -> None:
    info = _chunk_info(equipment={"Rune platebody": {"slot": "body", "requirements": {"Defence": 40}}})
    items = {"Rune platebody": {"Store": "shop"}}

    result = compute_bis(
        info, items, {"Defence": {"Some task": True}}, rules={}, max_skill={"Defence": 10}
    )

    assert "Melee-body" not in result.picks


def test_task_unlocks_gate_needs_the_unlock_task_valid() -> None:
    info = _chunk_info(
        equipment={"Ancient platebody": {"slot": "body"}},
        taskUnlocks={"Items": {"Ancient platebody": [{"Complete the quest": "Quest"}]}},
    )
    items = {"Ancient platebody": {"Store": "shop"}}

    locked = compute_bis(info, items, {}, rules={})
    unlocked = compute_bis(info, items, {"Quest": {"Complete the quest": True}}, rules={})

    assert "Melee-body" not in locked.picks
    assert unlocked.picks["Melee-body"] == "Ancient platebody"


def test_source_quality_gate_rejects_a_crafted_only_item() -> None:
    info = _chunk_info(equipment={"Rune scimitar": {"slot": "weapon", "attack_speed": 4, "attack_slash": 45}})
    only_crafted = {"Rune scimitar": {"Smith a rune scimitar": "primary-Smithing"}}
    also_dropped = {
        "Rune scimitar": {"Smith a rune scimitar": "primary-Smithing", "Goblin": "secondary-drop"}
    }

    rejected = compute_bis(info, only_crafted, {}, rules={})
    accepted = compute_bis(info, also_dropped, {}, rules={})

    assert "Melee-weapon" not in rejected.picks
    assert accepted.picks["Melee-weapon"] == "Rune scimitar"


def test_source_quality_gate_allows_wield_crafted_items_rule() -> None:
    info = _chunk_info(equipment={"Rune scimitar": {"slot": "weapon", "attack_speed": 4, "attack_slash": 45}})
    only_crafted = {"Rune scimitar": {"Smith a rune scimitar": "primary-Smithing"}}

    result = compute_bis(info, only_crafted, {}, rules={"Wield Crafted Items": True})

    assert result.picks["Melee-weapon"] == "Rune scimitar"


def test_ranged_weapon_needs_reachable_ammo() -> None:
    info = _chunk_info(
        equipment={
            "Oak shortbow": {"slot": "2h", "attack_speed": 6, "attack_ranged": 8},
            "Bronze arrow": {"slot": "ammo", "ranged_strength": 7},
        },
        codeItems={"ammoTools": {"Bronze arrow": {"Oak shortbow": True}}},
    )

    no_ammo = compute_bis(info, {"Oak shortbow": {"Store": "shop"}}, {}, rules={})
    with_ammo = compute_bis(
        info,
        {"Oak shortbow": {"Store": "shop"}, "Bronze arrow": {"Store": "shop"}},
        {},
        rules={},
    )

    assert "Ranged-weapon" not in no_ammo.picks
    assert with_ammo.picks["Ranged-weapon"] == "Oak shortbow"


def test_two_h_beats_one_h_and_shield_when_stronger() -> None:
    info = _chunk_info(
        equipment={
            "Dagger": {"slot": "weapon", "attack_speed": 4, "attack_stab": 10, "melee_strength": 10},
            "Kiteshield": {"slot": "shield", "defence_stab": 5},
            "Godsword": {"slot": "2h", "attack_speed": 6, "attack_slash": 100, "melee_strength": 100},
        }
    )
    items = {"Dagger": {"S": "shop"}, "Kiteshield": {"S": "shop"}, "Godsword": {"S": "shop"}}

    result = compute_bis(info, items, {}, rules={})

    assert result.picks["Melee-weapon"] == "Godsword"
    assert "Melee-shield" not in result.picks


def test_one_h_and_shield_wins_the_tie() -> None:
    info = _chunk_info(
        equipment={
            "Sword": {"slot": "weapon", "attack_speed": 4, "attack_slash": 20, "melee_strength": 20},
            "Kiteshield": {"slot": "shield", "defence_stab": 50},
            "Godsword": {"slot": "2h", "attack_speed": 4, "attack_slash": 20, "melee_strength": 20},
        }
    )
    items = {"Sword": {"S": "shop"}, "Kiteshield": {"S": "shop"}, "Godsword": {"S": "shop"}}

    result = compute_bis(info, items, {}, rules={})

    assert result.picks["Melee-weapon"] == "Sword"
    assert result.picks["Melee-shield"] == "Kiteshield"


def test_prayer_style_only_active_when_the_rule_is_on() -> None:
    info = _chunk_info(equipment={"Proselyte sallet": {"slot": "head", "prayer": 3}})
    items = {"Proselyte sallet": {"Store": "shop"}}

    off = compute_bis(info, items, {}, rules={})
    on = compute_bis(info, items, {}, rules={"Show Best in Slot Prayer Tasks": True})

    assert "Prayer-head" not in off.picks
    assert on.picks["Prayer-head"] == "Proselyte sallet"


def test_prayer_style_ignores_zero_prayer_items() -> None:
    info = _chunk_info(equipment={"Iron platebody": {"slot": "body", "prayer": 0}})
    items = {"Iron platebody": {"Store": "shop"}}

    result = compute_bis(info, items, {}, rules={"Show Best in Slot Prayer Tasks": True})

    assert "Prayer-body" not in result.picks


def test_weight_style_only_considers_items_with_a_weight_field() -> None:
    info = _chunk_info(
        equipment={
            "Graceful boots": {"slot": "feet", "weight": -4.5},
            "Rune boots": {"slot": "feet"},
        }
    )
    items = {"Graceful boots": {"Store": "shop"}, "Rune boots": {"Store": "shop"}}

    result = compute_bis(info, items, {}, rules={"Show Best in Slot Weight Tasks": True})

    assert result.picks["Weight_Reducing-feet"] == "Graceful boots"


def test_multi_style_winner_joins_labels_with_the_zero_width_separator() -> None:
    # The sole "neck" candidate wins every active style by default (nothing
    # else competes), so its label must join all of them with the U+200B
    # separator rather than only recording the last style to pick it.
    info = _chunk_info(equipment={"Amulet of power": {"slot": "neck", "prayer": 1}})
    items = {"Amulet of power": {"Store": "shop"}}

    result = compute_bis(info, items, {}, rules={"Show Best in Slot Prayer Tasks": True})

    task_name = "Obtain an ~|amulet of power|~"
    assert task_name in result.tasks
    label = result.tasks[task_name]
    assert label.endswith(" BiS neck")
    styles = label[: -len(" BiS neck")].split("/​")
    assert set(styles) == {"Melee", "Ranged", "Magic", "Prayer"}


def test_task_name_and_label_are_generated() -> None:
    # A whip has no ranged/magic stats, but as the sole "weapon" candidate it
    # still wins those styles by default (nothing else competes) - so its
    # label covers all three, not just Melee.
    info = _chunk_info(equipment={"Abyssal whip": {"slot": "weapon", "attack_speed": 4, "attack_slash": 82, "melee_strength": 82}})
    items = {"Abyssal whip": {"Abyssal demon": "secondary-drop"}}

    result = compute_bis(info, items, {}, rules={})

    assert result.tasks == {
        "Obtain an ~|abyssal whip|~": "Melee/​Ranged/​Magic BiS weapon"
    }


def test_completed_bis_item_is_excluded_from_active() -> None:
    info = _chunk_info(
        equipment={
            "Abyssal whip": {
                "slot": "weapon",
                "attack_speed": 4,
                "attack_slash": 82,
                "melee_strength": 82,
            }
        }
    )
    items = {"Abyssal whip": {"Abyssal demon": "secondary-drop"}}

    result = compute_bis(info, items, {}, rules={}, completed_bis={"Obtain an ~|abyssal whip|~": True})

    assert "Obtain an ~|abyssal whip|~" in result.completed
    assert "Obtain an ~|abyssal whip|~" not in result.active
    assert result.tasks == result.completed


def test_not_yet_completed_bis_item_is_active() -> None:
    info = _chunk_info(
        equipment={
            "Abyssal whip": {
                "slot": "weapon",
                "attack_speed": 4,
                "attack_slash": 82,
                "melee_strength": 82,
            }
        }
    )
    items = {"Abyssal whip": {"Abyssal demon": "secondary-drop"}}

    result = compute_bis(info, items, {}, rules={})

    assert result.completed == {}
    assert "Obtain an ~|abyssal whip|~" in result.active


def test_outdated_note_when_a_better_item_has_since_become_reachable() -> None:
    info = _chunk_info(
        equipment={
            "Bronze scimitar": {
                "slot": "weapon",
                "attack_speed": 4,
                "attack_slash": 5,
                "melee_strength": 4,
            },
            "Abyssal whip": {
                "slot": "weapon",
                "attack_speed": 4,
                "attack_slash": 82,
                "melee_strength": 82,
            },
        }
    )
    items = {"Abyssal whip": {"Abyssal demon": "secondary-drop"}}
    completed_bis = {"Obtain a ~|bronze scimitar|~": True}

    result = compute_bis(info, items, {}, rules={}, completed_bis=completed_bis)

    assert "Obtain a ~|bronze scimitar|~" in result.outdated
    assert "Abyssal whip" in result.outdated["Obtain a ~|bronze scimitar|~"]


def test_no_outdated_note_when_the_completed_item_is_still_best() -> None:
    info = _chunk_info(
        equipment={
            "Abyssal whip": {
                "slot": "weapon",
                "attack_speed": 4,
                "attack_slash": 82,
                "melee_strength": 82,
            }
        }
    )
    items = {"Abyssal whip": {"Abyssal demon": "secondary-drop"}}

    result = compute_bis(info, items, {}, rules={}, completed_bis={"Obtain an ~|abyssal whip|~": True})

    assert result.outdated == {}


def test_as_dict_shape() -> None:
    info = _chunk_info(equipment={"Abyssal whip": {"slot": "weapon", "attack_speed": 4, "attack_slash": 82, "melee_strength": 82}})
    items = {"Abyssal whip": {"Abyssal demon": "secondary-drop"}}

    result = compute_bis(info, items, {}, rules={})

    assert result.as_dict() == {
        "picks": {
            "Melee-weapon": "Abyssal whip",
            "Ranged-weapon": "Abyssal whip",
            "Magic-weapon": "Abyssal whip",
        },
        "tasks": {"Obtain an ~|abyssal whip|~": "Melee/​Ranged/​Magic BiS weapon"},
        "completed": {},
        "active": {"Obtain an ~|abyssal whip|~": "Melee/​Ranged/​Magic BiS weapon"},
        "outdated": {},
    }


@pytest.mark.skipif(not _REAL_CHUNKINFO, reason="set FRAY_CHUNKINFO to a real export to run this")
def test_melee_bis_weapon_matches_the_live_oracle() -> None:
    """Opt-in oracle: the cached `fray` map's `chunkinfo.activeTasks.BiS`
    records upstream's own last-computed Melee BiS weapon as `Abyssal whip`
    (via `Slayer/Abyssal demon`, whose chunk is unlocked on this map) - the
    one entry of that snapshot independently verified still consistent with
    the currently-unlocked chunk set (the other five reference monsters in
    chunks that are locked right now, so aren't used as an oracle here; see
    CLAUDE.md/the stage-5 plan for how that was established).
    """
    assert _REAL_CHUNKINFO is not None
    from fray_claude.cache import project_root, read_cache
    from fray_claude.pipeline import derive, load_map_state

    data = json.loads(Path(_REAL_CHUNKINFO).read_text(encoding="utf-8"))
    info = ChunkInfo(data)
    envelope = read_cache("fray", project_root())
    state, unlocked = load_map_state(envelope["data"], info)
    derived = derive(state, unlocked)

    result = compute_bis(
        info,
        derived.source_index.items,
        derived.challenges.valid,
        rules=state.rules,
        max_skill=state.max_skill,
        passive_skill=state.passive_skill,
    )

    assert result.picks["Melee-weapon"] == "Abyssal whip"


@pytest.mark.skipif(not _REAL_CHUNKINFO, reason="set FRAY_CHUNKINFO to a real export to run this")
def test_a_real_completed_bis_item_is_never_shown_as_active() -> None:
    """Opt-in oracle: unlike skill-level `activeTasks` (sparse - see
    `active_tasks.py`'s module docstring), `completedChallenges.BiS` is
    well-populated on the cached map (70 real entries).

    Regression guard for a real reported bug: `Black cape` shows as a
    completed BiS task on the live site, but was listed as still-to-obtain
    here, because `completedChallenges.BiS` stores it under the interned id
    `t_10226` and `decode_challenge_keyed` was special-casing `BiS` to skip
    `t_N` resolution entirely. The item is *still* the current cape pick, so
    it must land in `completed` - not `active`, and not `outdated` either
    (nothing has superseded it).
    """
    assert _REAL_CHUNKINFO is not None
    from fray_claude.cache import project_root, read_blob, read_cache
    from fray_claude.firebase import reverse_tasks_map
    from fray_claude.pipeline import derive, load_map_state

    data = json.loads(Path(_REAL_CHUNKINFO).read_text(encoding="utf-8"))
    info = ChunkInfo(data)
    root = project_root()
    envelope = read_cache("fray", root)
    tasks_map = reverse_tasks_map(read_blob("tasks_map", root)["data"])
    state, unlocked = load_map_state(envelope["data"], info, tasks_map)
    derived = derive(state, unlocked)

    task_name = "Obtain a ~|black cape|~"
    assert task_name in derived.bis.completed
    assert task_name not in derived.bis.active
    assert task_name not in derived.bis.outdated

    # And nothing anywhere should still be an unresolved raw id.
    assert not [name for name in state.completed_challenges["BiS"] if name.startswith("t_")]
