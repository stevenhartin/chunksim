"""Tests for best-in-slot equipment synthesis."""

from __future__ import annotations

from typing import Any

import pytest

from chunksim.derive.bis import (
    _STYLE_SEPARATOR,
    article_for,
    bis_display_name,
    bis_task_name,
    build_ammo_index,
    compute_bis,
    format_equip,
)
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.derive.pipeline import Derived, MapState



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
        "slots": {"Obtain an ~|abyssal whip|~": "weapon"},
        "current_chunk": [],
    }


def _whip_info() -> ChunkInfo:
    return _chunk_info(
        equipment={
            "Abyssal whip": {"slot": "weapon", "attack_speed": 4, "attack_slash": 82, "melee_strength": 82}
        }
    )


_WHIP_TASK = "Obtain an ~|abyssal whip|~"


def test_display_name_prefixes_the_slot() -> None:
    assert bis_display_name(_WHIP_TASK, "weapon") == "[weapon] Obtain an abyssal whip"


def test_display_name_omits_the_prefix_without_a_slot() -> None:
    assert bis_display_name(_WHIP_TASK) == "Obtain an abyssal whip"


def test_display_name_marks_a_pick_obtained_this_chunk() -> None:
    assert bis_display_name(_WHIP_TASK, "weapon", current_chunk=True) == (
        "[weapon] Obtain an abyssal whip (Active)"
    )


def test_compute_bis_records_each_tasks_slot() -> None:
    items = {"Abyssal whip": {"Abyssal demon": "secondary-drop"}}

    result = compute_bis(_whip_info(), items, {}, rules={})

    assert result.slots == {_WHIP_TASK: "weapon"}
    assert result.display_name(_WHIP_TASK) == "[weapon] Obtain an abyssal whip"


def test_a_checked_pick_is_completed_and_flagged_as_this_chunks() -> None:
    """`checkedChallenges` is a strict subset of the merged completed view,
    so a checked pick counts as obtained *and* gets the current-chunk mark."""
    items = {"Abyssal whip": {"Abyssal demon": "secondary-drop"}}

    result = compute_bis(
        _whip_info(),
        items,
        {},
        rules={},
        completed_bis={_WHIP_TASK: True},
        checked_bis={_WHIP_TASK: True},
    )

    assert result.completed == {_WHIP_TASK: "Melee/​Ranged/​Magic BiS weapon"}
    assert result.active == {}
    assert result.current_chunk == frozenset({_WHIP_TASK})
    assert result.display_name(_WHIP_TASK) == "[weapon] Obtain an abyssal whip (Active)"


def test_a_pick_completed_in_an_earlier_chunk_is_not_flagged() -> None:
    items = {"Abyssal whip": {"Abyssal demon": "secondary-drop"}}

    result = compute_bis(
        _whip_info(), items, {}, rules={}, completed_bis={_WHIP_TASK: True}, checked_bis={}
    )

    assert result.completed == {_WHIP_TASK: "Melee/​Ranged/​Magic BiS weapon"}
    assert result.current_chunk == frozenset()
    assert result.display_name(_WHIP_TASK) == "[weapon] Obtain an abyssal whip"


def test_a_checked_entry_this_result_never_shows_is_not_flagged() -> None:
    """A `checkedChallenges` entry naming neither a current pick nor a
    resolvable outdated one has nowhere to be labelled, so it stays out of
    `current_chunk` rather than sitting there unmatched."""
    items = {"Abyssal whip": {"Abyssal demon": "secondary-drop"}}

    result = compute_bis(
        _whip_info(),
        items,
        {},
        rules={},
        completed_bis={"Obtain a ~|nonexistent trinket|~": True},
        checked_bis={"Obtain a ~|nonexistent trinket|~": True},
    )

    assert result.current_chunk == frozenset()


def test_display_sorted_puts_this_chunks_acquisitions_first() -> None:
    """Within each group the order stays alphabetical - it's only the
    this-chunk/earlier split that overrides it, so `Zamorak` sorting ahead
    of `Ahrim's` here can only come from the current-chunk grouping.
    """
    equipment = {
        "Ahrim's hood": {"slot": "head", "magic_damage": 5},
        "Zamorak monk top": {"slot": "body", "magic_damage": 9},
    }
    items = {name: {"Shop": "primary-shop"} for name in equipment}
    zamorak = "Obtain a ~|zamorak monk top|~"

    result = compute_bis(
        _chunk_info(equipment=equipment),
        items,
        {},
        rules={},
        completed_bis={zamorak: True, "Obtain an ~|ahrim's hood|~": True},
        checked_bis={zamorak: True},
    )

    assert result.display_sorted(result.completed) == [
        "[body] Obtain a zamorak monk top (Active)",
        "[head] Obtain an ahrim's hood",
    ]


@pytest.mark.real_cache
def test_every_bis_pick_matches_the_live_oracle(
    real_export: ChunkInfo, real_tasks_map: dict[str, str]
) -> None:
    """Opt-in oracle: `chunkinfo.activeTasks.BiS` is upstream's *own* last
    computed BiS pick per (style, slot), so every entry must reproduce
    exactly.

    **Every fetched map in the cache, not just `fray`.** A map is a set of
    rules a player chose, so a second one is a second set of inputs rather
    than more of the same - and this test hard-coded `fray` while `verf` had
    two rules on that nothing in the repo had ever run. Fetch another map and
    it is covered here for free.

    Getting here found six real bugs. Four on `fray`, each a mismatch on
    exactly one entry: named-area unlocks were unported (`dragon boots`,
    `granite gloves`), challenge `Output` items never reached BiS (`granite
    ring (i)`), `skillItems` activities keyed off a challenge's `Output` were
    unported (`master wand`), and `backloggedSources` wasn't honoured when
    seeding those. Two more on `verf`: the `Show Best in Slot 1H and 2H`
    rule's second slot, and the obsidian set effect.

    An earlier version asserted only the one entry that happened to pass and
    dismissed the rest as a stale snapshot. They were not stale - the tool
    was wrong. Assert all of them, on every map.
    """
    from chunksim.store.cache import list_maps, project_root, read_cache
    from chunksim.model.firebase import decode_challenge_keyed
    from chunksim.derive.pipeline import derive, load_map_state

    info, tasks_map = real_export, real_tasks_map
    root = project_root()
    equipment = info.data["equipment"]
    fetched = [m.map_id for m in list_maps(root) if m.kind == "fetched"]
    assert fetched, "no fetched maps cached to compare against"

    checked = 0
    for map_id in fetched:
        envelope = read_cache(map_id, root)
        oracle = decode_challenge_keyed(
            envelope["data"]["chunkinfo"].get("activeTasks"), tasks_map
        ).get("BiS", {})
        if not oracle:
            continue
        state, unlocked = load_map_state(envelope["data"], info, tasks_map)
        derived = derive(state, unlocked)
        for task_name, label in oracle.items():
            style, _, slot = label.partition(" BiS ")
            # **A label can name several styles.** Upstream merges styles
            # that share a winner into one entry joined by a zero-width
            # separator (`Prayer/\u200bMagic BiS 2h`), so a whole-string
            # lookup finds nothing and reads as a missing pick.
            candidates = [
                derived.bis.picks.get(f"{one.strip().replace(' ', '_')}-{slot}")
                for one in style.split(_STYLE_SEPARATOR)
            ]
            named = [
                bis_task_name(pick, equipment.get(pick, {}))
                for pick in candidates
                if pick is not None
            ]
            assert named, f"{map_id}: no pick for {label}"
            assert task_name in named, f"{map_id}: {label} -> {named} (want {task_name})"
            checked += 1
    assert checked, "every cached map had an empty BiS oracle"



@pytest.mark.real_cache
def test_a_real_completed_bis_item_is_never_shown_as_active(
    real_state: tuple[MapState, dict[str, bool]], real_derived: Derived
) -> None:
    """Opt-in oracle: unlike skill-level `activeTasks` (sparse - see
    `active_tasks.py`'s module docstring), `completedChallenges.BiS` is
    well-populated on the cached map (70 real entries).

    Regression guard for a real reported bug: `Black cape` shows as a
    completed BiS task on the live site, but was listed as still-to-obtain
    here, because `completedChallenges.BiS` stores it under the interned id
    `t_10226` and `decode_challenge_keyed` was special-casing `BiS` to skip
    `t_N` resolution entirely.

    The invariant asserted is "recognised as obtained", not a specific
    bucket: whether it lands in `completed` or `outdated` depends on whether
    it is *still* the cape pick, and that legitimately moves as better items
    become reachable (it is currently beaten by `Defence cape(t)`, which only
    exists as a challenge `Output`). Pinning the bucket would make this test
    fail on a correct improvement - what must never happen is it reappearing
    as something still to obtain.
    """
    state, _unlocked = real_state
    derived = real_derived

    task_name = "Obtain a ~|black cape|~"
    assert task_name not in derived.bis.active
    assert task_name in {**derived.bis.completed, **derived.bis.outdated}

    # And nothing anywhere should still be an unresolved raw id.
    assert not [name for name in state.completed_challenges["BiS"] if name.startswith("t_")]


def test_a_scoring_tie_resolves_to_an_already_completed_item() -> None:
    # Upstream builds its candidate pool as `{...completedEquipment,
    # ...equipment}`, and ties are first-seen-wins - so an item you already
    # have beats an identical one you don't. Real case: `Defence cape(t)`
    # and `Hitpoints cape(t)` have identical stats, and the export lists the
    # unobtained one first.
    stats = {"slot": "cape", "melee_strength": 5}
    info = _chunk_info(equipment={"Unowned cape": dict(stats), "Owned cape": dict(stats)})
    items = {"Unowned cape": {"S": "shop"}, "Owned cape": {"S": "shop"}}

    without = compute_bis(info, items, {}, rules={})
    with_completed = compute_bis(
        info, items, {}, rules={}, completed_bis={"Obtain an ~|owned cape|~": True}
    )

    assert without.picks["Melee-cape"] == "Unowned cape"
    assert with_completed.picks["Melee-cape"] == "Owned cape"
    # ...and having it means nothing is proposed for that slot.
    assert with_completed.active == {}


def test_completed_ordering_never_beats_a_strictly_better_item() -> None:
    info = _chunk_info(
        equipment={
            "Weak cape": {"slot": "cape", "melee_strength": 1},
            "Strong cape": {"slot": "cape", "melee_strength": 9},
        }
    )
    items = {"Weak cape": {"S": "shop"}, "Strong cape": {"S": "shop"}}

    result = compute_bis(
        info, items, {}, rules={}, completed_bis={"Obtain a ~|weak cape|~": True}
    )

    assert result.picks["Melee-cape"] == "Strong cape"


def test_ammo_slot_follows_the_winning_launcher() -> None:
    # Upstream overwrites the ammo slot with the ammo paired to whichever
    # weapon won, rather than picking ammo independently - otherwise a
    # Ranged build is told to obtain the highest-strength ammo in the game
    # even when its bow cannot fire it.
    info = _chunk_info(
        equipment={
            "Oak shortbow": {"slot": "2h", "attack_speed": 6, "attack_ranged": 8},
            "Bronze arrow": {"slot": "ammo", "ranged_strength": 7},
            "Dragon javelin": {"slot": "ammo", "ranged_strength": 150},
        },
        codeItems={"ammoTools": {"Bronze arrow": {"Oak shortbow": True}}},
    )
    items = {n: {"S": "shop"} for n in ("Oak shortbow", "Bronze arrow", "Dragon javelin")}

    result = compute_bis(info, items, {}, rules={})

    assert result.picks["Ranged-weapon"] == "Oak shortbow"
    # Dragon javelin scores far higher but no reachable launcher fires it.
    assert result.picks["Ranged-ammo"] == "Bronze arrow"


def test_ammo_slot_is_absent_when_the_winning_weapon_takes_none() -> None:
    info = _chunk_info(
        equipment={
            "Rune knife": {"slot": "weapon", "attack_speed": 3, "attack_ranged": 25},
            "Dragon javelin": {"slot": "ammo", "ranged_strength": 150},
        },
        codeItems={"ammoTools": {}},
    )
    items = {"Rune knife": {"S": "shop"}, "Dragon javelin": {"S": "shop"}}

    result = compute_bis(info, items, {}, rules={})

    assert result.picks["Ranged-weapon"] == "Rune knife"
    assert not [k for k in result.picks if k.endswith("-ammo")]


def test_two_handed_wins_when_stronger_than_one_hand_plus_shield() -> None:
    # Both sides must be scored with the *weapon* formula. Adding the
    # shield's armour score (scaled by 100000) to a DPS-scale number made
    # 1H+shield win essentially always, which wrongly deleted every 2H pick.
    info = _chunk_info(
        equipment={
            "Godsword": {"slot": "2h", "attack_speed": 6, "attack_slash": 132, "melee_strength": 132},
            "Dagger": {"slot": "weapon", "attack_speed": 4, "attack_slash": 5, "melee_strength": 5},
            "Kiteshield": {"slot": "shield", "defence_slash": 60, "defence_stab": 60},
        }
    )
    items = {n: {"S": "shop"} for n in ("Godsword", "Dagger", "Kiteshield")}

    result = compute_bis(info, items, {}, rules={})

    assert result.picks["Melee-weapon"] == "Godsword"
    # A winning 2H removes the shield slot entirely.
    assert "Melee-shield" not in result.picks


def test_one_hand_plus_shield_wins_on_combined_offence() -> None:
    # The shield's *offensive* stats do count, summed into the 1H side.
    info = _chunk_info(
        equipment={
            "Weak 2h": {"slot": "2h", "attack_speed": 4, "attack_slash": 10, "melee_strength": 10},
            "Sword": {"slot": "weapon", "attack_speed": 4, "attack_slash": 40, "melee_strength": 40},
            "Offensive shield": {"slot": "shield", "attack_slash": 20, "melee_strength": 20},
        }
    )
    items = {n: {"S": "shop"} for n in ("Weak 2h", "Sword", "Offensive shield")}

    result = compute_bis(info, items, {}, rules={})

    assert result.picks["Melee-weapon"] == "Sword"
    assert result.picks["Melee-shield"] == "Offensive shield"


# --- the 1H/2H rule and set effects ----------------------------------------


def _weapon(**stats: Any) -> dict[str, Any]:
    return {"slot": "weapon", "attack_speed": 4, **stats}


#: The export's own numbers, because invented ones do not settle this. The
#: obsidian armour carries 3/3/1 strength, and leaving that out was enough to
#: make the set lose a comparison it wins on the real map.
_OBSIDIAN = {
    "Obsidian helmet": {"slot": "head", "melee_strength": 3},
    "Obsidian platebody": {"slot": "body", "melee_strength": 3},
    "Obsidian platelegs": {"slot": "legs", "melee_strength": 1},
    "Toktz-xil-ak": _weapon(
        attack_crush=-2, attack_slash=38, attack_stab=47, melee_strength=49
    ),
    "Berserker necklace": {
        "slot": "neck",
        "attack_crush": -10,
        "attack_slash": -10,
        "attack_stab": -10,
        "melee_strength": 7,
    },
}

#: Beats the berserker necklace on raw strength (10 against 7), exactly as it
#: does in the export. Without the set effect it wins the neck slot, so its
#: presence is what makes "the necklace won" mean "the set applied".
_RIVAL_NECK = {"Amulet of strength": {"slot": "neck", "melee_strength": 10}}

#: The slots the set does not claim still contribute, and the comparison is
#: close enough that they decide it - `verf`'s melee loadout, verbatim.
_REST = {
    "Infernal cape": {
        "slot": "cape", "attack_crush": 4, "attack_slash": 4, "attack_stab": 4,
        "melee_strength": 8,
    },
    "Regen bracelet": {
        "slot": "hands", "attack_crush": 8, "attack_slash": 8, "attack_stab": 8,
        "melee_strength": 7,
    },
    "Rune boots": {"slot": "feet", "melee_strength": 2},
    "Toktz-ket-xil": {"slot": "shield", "melee_strength": 5},
}

_LOADOUT = {**_OBSIDIAN, **_RIVAL_NECK, **_REST}
_SOURCES = {name: {"Store": "shop"} for name in _LOADOUT}


def test_a_set_takes_its_slots_when_the_whole_loadout_scores_better() -> None:
    """**A strictly worse weapon can be the right pick.** The set's
    multiplier applies to the loadout, not the item, so upstream picks
    toktz-xil-ak over a whip that beats it on every raw stat - which is only
    reachable by scoring the whole thing."""
    info = _chunk_info(
        equipment={**_LOADOUT, "Abyssal whip": _weapon(attack_slash=82, melee_strength=82)}
    )
    items = {**_SOURCES, "Abyssal whip": {"Store": "shop"}}

    result = compute_bis(info, items, {}, rules={})

    assert result.picks["Melee-weapon"] == "Toktz-xil-ak"
    # The necklace is what lifts the multiplier, so it comes with the set.
    assert result.picks["Melee-neck"] == "Berserker necklace"
    assert result.picks["Melee-head"] == "Obsidian helmet"


def test_a_set_missing_a_piece_confers_nothing() -> None:
    """Upstream's `validWearable` short-circuits on the first piece it cannot
    wear: three quarters of a set is not a set."""
    equipment = {k: v for k, v in _LOADOUT.items() if k != "Obsidian platelegs"}
    info = _chunk_info(
        equipment={**equipment, "Abyssal whip": _weapon(attack_slash=82, melee_strength=82)}
    )
    items = {
        **{name: {"Store": "shop"} for name in equipment},
        "Abyssal whip": {"Store": "shop"},
    }

    result = compute_bis(info, items, {}, rules={})

    assert result.picks["Melee-weapon"] == "Abyssal whip"
    # The necklace is only ever the pick *as part of the set*: on its own
    # merits the amulet's 10 strength beats its 7.
    assert result.picks["Melee-neck"] == "Amulet of strength"


def test_a_set_that_loses_on_dps_does_not_apply() -> None:
    """The comparison is real, not a preference for sets."""
    info = _chunk_info(
        equipment={**_LOADOUT, "Godsword": _weapon(attack_slash=900, melee_strength=900)}
    )
    items = {**_SOURCES, "Godsword": {"Store": "shop"}}

    result = compute_bis(info, items, {}, rules={})

    assert result.picks["Melee-weapon"] == "Godsword"
    assert result.picks["Melee-neck"] == "Amulet of strength"


def test_the_1h_and_2h_rule_keeps_both_weapons() -> None:
    """**With the rule off a 2H replaces weapon+shield**, which is what this
    always did; with it on the loser is kept under its own slot, which is how
    upstream records a `2h` pick beside a `weapon` one."""
    info = _chunk_info(
        equipment={
            "Rune scimitar": _weapon(attack_slash=45, melee_strength=44),
            "Rune 2h sword": {
                "slot": "2h",
                "attack_speed": 7,
                "attack_slash": 69,
                "melee_strength": 71,
            },
        }
    )
    items = {"Rune scimitar": {"Store": "shop"}, "Rune 2h sword": {"Store": "shop"}}

    off = compute_bis(info, items, {}, rules={})
    on = compute_bis(info, items, {}, rules={"Show Best in Slot 1H and 2H": True})

    assert "Melee-2h" not in off.picks
    assert off.picks["Melee-weapon"] in {"Rune scimitar", "Rune 2h sword"}
    # On: both survive, each in its own slot.
    assert on.picks["Melee-2h"] == "Rune 2h sword"
    assert on.picks["Melee-weapon"] == "Rune scimitar"


def test_the_losing_weapon_does_not_inflate_the_set_comparison() -> None:
    """**The order is load-bearing.** Upstream deletes the losing weapon
    before the set chain and merges it back after, so the loadout scored is
    the one actually worn. Leaving it in adds a second weapon's bonuses to
    the non-set baseline - measured at 28% on `verf`, which was enough to
    stop the obsidian set ever winning.
    """
    info = _chunk_info(
        equipment={
            **_LOADOUT,
            "Abyssal whip": _weapon(attack_slash=82, melee_strength=82),
            "Dragon spear": {
                "slot": "2h",
                "attack_speed": 5,
                "attack_stab": 55,
                "melee_strength": 40,
            },
        }
    )
    items = {**_SOURCES, "Abyssal whip": {"Store": "shop"}, "Dragon spear": {"Store": "shop"}}

    result = compute_bis(info, items, {}, rules={"Show Best in Slot 1H and 2H": True})

    assert result.picks["Melee-weapon"] == "Toktz-xil-ak"
    assert result.picks["Melee-2h"] == "Dragon spear"
