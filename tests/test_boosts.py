"""Tests for temporary skill-boost level adjustment."""

from __future__ import annotations

from typing import Any

from fray_claude.derive import boosts
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.derive.sources import SourceIndex

_ON = {"Boosting": True}


def _chunk_info(**code_items: Any) -> ChunkInfo:
    return ChunkInfo({"codeItems": code_items})


def _index(**categories: Any) -> SourceIndex:
    base: dict[str, Any] = {
        "items": {},
        "objects": {},
        "monsters": {},
        "npcs": {},
        "shops": {},
        "drop_rates": {},
    }
    base.update(categories)
    return SourceIndex(**base)


def _best(
    skill: str,
    challenge: dict[str, Any],
    level: float,
    *,
    info: ChunkInfo,
    items: dict[str, Any] | None = None,
    index: SourceIndex | None = None,
    rules: dict[str, Any] | None = None,
    name: str = "Do the thing",
) -> tuple[int, int]:
    return boosts.best_boost(
        skill,
        name,
        challenge,
        level,
        rules=_ON if rules is None else rules,
        chunk_info=info,
        items=items or {},
        source_index=index or _index(),
    )


def test_no_boost_when_the_rule_is_off() -> None:
    info = _chunk_info(boostItems={"Slayer": {"Wild pie": 5}})

    assert _best("Slayer", {}, 92, info=info, items={"Wild pie": {}}, rules={}) == (0, 0)


def test_a_flat_boost_applies_when_the_item_is_reachable() -> None:
    info = _chunk_info(boostItems={"Slayer": {"Wild pie": 5}})

    assert _best("Slayer", {}, 92, info=info, items={"Wild pie": {}}) == (5, 0)


def test_an_unreachable_boost_item_contributes_nothing() -> None:
    info = _chunk_info(boostItems={"Slayer": {"Wild pie": 5}})

    assert _best("Slayer", {}, 92, info=info, items={}) == (0, 0)


def test_the_largest_reachable_boost_wins() -> None:
    info = _chunk_info(boostItems={"Slayer": {"Slayer's respite": 2, "Wild pie": 5}})

    both = _best("Slayer", {}, 92, info=info, items={"Slayer's respite": {}, "Wild pie": {}})
    lesser_only = _best("Slayer", {}, 92, info=info, items={"Slayer's respite": {}})

    assert both == (5, 0)
    assert lesser_only == (2, 0)


def test_a_no_boost_challenge_is_never_boosted() -> None:
    """`hasOwnProperty('NoBoost')` - presence, so even a falsy value blocks."""
    info = _chunk_info(boostItems={"Slayer": {"Wild pie": 5}})

    assert _best("Slayer", {"NoBoost": True}, 92, info=info, items={"Wild pie": {}}) == (0, 0)
    assert _best("Slayer", {"NoBoost": False}, 92, info=info, items={"Wild pie": {}}) == (0, 0)


def test_a_boost_item_is_looked_up_in_the_named_category() -> None:
    """`"Oldak~npcs"` means "the NPC Oldak", not an item of that name."""
    info = _chunk_info(boostItems={"Magic": {"Oldak~npcs": 2}})

    as_npc = _best("Magic", {}, 50, info=info, index=_index(npcs={"Oldak": {}}))
    as_item = _best("Magic", {}, 50, info=info, items={"Oldak": {}})

    assert as_npc == (2, 0)
    assert as_item == (0, 0)


def test_a_banned_boost_is_skipped_for_that_challenge_only() -> None:
    info = _chunk_info(
        boostItems={"Thieving": {"Summer sq'irkjuice": 5}},
        boostTaskBans={"Thieving": {"Steal a summer sq'irk": ["Summer sq'irkjuice"]}},
    )
    items: dict[str, Any] = {"Summer sq'irkjuice": {}}

    banned = _best("Thieving", {}, 65, info=info, items=items, name="Steal a summer sq'irk")
    other = _best("Thieving", {}, 65, info=info, items=items, name="Steal something else")

    assert banned == (0, 0)
    assert other == (5, 0)


def test_a_percentage_boost_is_applied_twice() -> None:
    """Upstream computes the discount, then recomputes it against the
    already-discounted level (worker.js:8404-8405). For `"10%+3"` at level
    80 that is `floor(80*0.1+3) = 11`, then `floor((80-11)*0.1+3) = 9`.
    """
    info = _chunk_info(boostItems={"Strength": {"Strength potion(4)": "10%+3"}})

    assert _best("Strength", {}, 80, info=info, items={"Strength potion(4)": {}}) == (9, 0)


def test_a_percentage_boost_with_no_flat_part_contributes_nothing() -> None:
    """`"4%"` doesn't split on `'%+'`, so JS coerces it to NaN and it never
    beats the running best. `Strength`'s `Beer` is the real case.
    """
    info = _chunk_info(boostItems={"Strength": {"Beer": "4%"}})

    assert _best("Strength", {}, 80, info=info, items={"Beer": {}}) == (0, 0)


def test_the_crystal_saw_only_boosts_construction_tasks_that_use_a_saw() -> None:
    info = _chunk_info(boostItems={"Construction": {"Crystal saw": "3"}})
    items: dict[str, Any] = {"Crystal saw": {}}

    with_saw = _best("Construction", {"Items": ["Saw[+]"]}, 50, info=info, items=items)
    without = _best("Construction", {"Items": ["Hammer[+]"]}, 50, info=info, items=items)

    assert with_saw == (0, 3)
    assert without == (0, 0)


def test_the_crystal_saw_is_reported_apart_from_the_flat_boost() -> None:
    """They are clamped differently, so `best_boost` must not merge them."""
    info = _chunk_info(boostItems={"Construction": {"Cup of tea (trimmed)": 3, "Crystal saw": "3"}})

    assert _best(
        "Construction",
        {"Items": ["Saw[+]"]},
        50,
        info=info,
        items={"Cup of tea (trimmed)": {}, "Crystal saw": {}},
    ) == (3, 3)


def test_real_level_subtracts_the_boost() -> None:
    info = _chunk_info(boostItems={"Slayer": {"Wild pie": 5}})

    level = boosts.real_level(
        "Slayer",
        "Slay an araxyte",
        {},
        92,
        rules=_ON,
        chunk_info=info,
        items={"Wild pie": {}},
        source_index=_index(),
    )

    assert level == 87


def test_real_level_floors_at_one() -> None:
    info = _chunk_info(boostItems={"Herblore": {"Spicy stew": 5}})

    level = boosts.real_level(
        "Herblore",
        "Clean a grimy guam leaf",
        {},
        3,
        rules=_ON,
        chunk_info=info,
        items={"Spicy stew": {}},
        source_index=_index(),
    )

    assert level == 1


def test_completed_ceiling_agrees_with_real_level_in_the_ordinary_case() -> None:
    info = _chunk_info(boostItems={"Slayer": {"Wild pie": 5}})
    kwargs: dict[str, Any] = {
        "rules": _ON,
        "chunk_info": info,
        "items": {"Wild pie": {}},
        "source_index": _index(),
    }

    assert boosts.completed_ceiling("Slayer", "Slay it", {}, 92, **kwargs) == 87
    assert boosts.real_level("Slayer", "Slay it", {}, 92, **kwargs) == 87


def test_completed_ceiling_reproduces_the_crystal_saw_underflow() -> None:
    """The two clamps differ upstream: the candidate side floors at 1, the
    completed side rewrites `bestBoost` to `Level - 1` and recomputes, so a
    Construction `Saw[+]` challenge lands at `1 - 3`. Reproduced, not fixed -
    both sides of the same comparison genuinely behave this way.
    """
    info = _chunk_info(boostItems={"Construction": {"Crystal saw": "3"}})
    kwargs: dict[str, Any] = {
        "rules": _ON,
        "chunk_info": info,
        "items": {"Crystal saw": {}},
        "source_index": _index(),
    }
    challenge = {"Items": ["Saw[+]"]}

    assert boosts.completed_ceiling("Construction", "Build it", challenge, 2, **kwargs) == -2
    assert boosts.real_level("Construction", "Build it", challenge, 2, **kwargs) == 1


def test_a_skill_with_no_boost_table_is_unaffected() -> None:
    info = _chunk_info(boostItems={"Slayer": {"Wild pie": 5}})

    assert _best("Agility", {}, 89, info=info, items={"Wild pie": {}}) == (0, 0)
