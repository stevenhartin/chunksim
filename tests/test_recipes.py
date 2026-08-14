"""Tests for `remote/recipes.py`: the wiki's per-action facts, parsed.

The shapes here are all taken from real Bucket rows - the double-encoded JSON,
the numbers-as-strings, the empty tick field, the two recipes on one page. No
test touches the network; `fetch_bucket` is `api.py`'s and is tested there.
"""

from __future__ import annotations

import json
from typing import Any

from chunksim.remote.recipes import parse_recipes, recipe_query


def _row(page: str, **production: Any) -> dict[str, Any]:
    """A Bucket row, with `production_json` encoded the way the wiki sends it."""
    return {"page_name": page, "production_json": json.dumps(production)}


_ATTACK_POTION = _row(
    "Attack potion",
    ticks="2",
    materials=[
        {"quantity": "1", "name": "Guam potion (unf)"},
        {"quantity": "1", "name": "Eye of newt"},
    ],
    skills=[{"experience": "25", "level": "3", "name": "Herblore", "boostable": "No"}],
    output={"cost": 4, "quantity": "1", "name": "Attack potion(3)"},
)


def test_a_recipe_carries_the_two_numbers_the_export_lacks() -> None:
    """Experience per action and the action's duration - the whole reason this
    module exists. Everything else about an attack potion is already in the
    export."""
    (recipe,) = parse_recipes([_ATTACK_POTION], "Herblore")

    assert (recipe.level, recipe.experience, recipe.ticks) == (3, 25.0, 2)
    assert recipe.output == "Attack potion(3)"
    assert [(m.name, m.quantity) for m in recipe.materials] == [
        ("Guam potion (unf)", 1.0),
        ("Eye of newt", 1.0),
    ]


def test_an_unknown_tick_cost_is_none_rather_than_zero() -> None:
    """`"ticks": ""` means the wiki does not say. Zero would make it the
    fastest method on the map."""
    row = _row(
        "Mystery",
        ticks="",
        skills=[{"experience": "10", "level": "1", "name": "Cooking"}],
        output={"name": "Something", "quantity": "1"},
    )

    (recipe,) = parse_recipes([row], "Cooking")

    assert recipe.ticks is None


def test_only_the_skill_asked_about_is_returned() -> None:
    """A recipe paying two skills is two different training methods, and the
    caller asked about one of them."""
    row = _row(
        "Noxious halberd",
        ticks="3",
        skills=[
            {"experience": "100", "level": "72", "name": "Crafting"},
            {"experience": "80", "level": "72", "name": "Smithing"},
        ],
        output={"name": "Noxious halberd", "quantity": "1"},
    )

    (crafting,) = parse_recipes([row], "Crafting")
    (smithing,) = parse_recipes([row], "Smithing")

    assert (crafting.skill, crafting.experience) == ("Crafting", 100.0)
    assert (smithing.skill, smithing.experience) == ("Smithing", 80.0)
    assert parse_recipes([row], "Herblore") == ()


def test_two_recipes_on_one_page_are_told_apart_by_their_variant() -> None:
    """`Bronze bar` has a normal-furnace recipe and a Blast Furnace one, and
    the output's `subtxt` is the only thing separating them. Keyed on the page
    alone, whichever came last would win."""
    rows = [
        _row(
            "Bronze bar",
            ticks="5",
            skills=[{"experience": "6.2", "level": "1", "name": "Smithing"}],
            output={"name": "Bronze bar", "quantity": "1", "subtxt": "Normal furnace"},
        ),
        _row(
            "Bronze bar",
            ticks="2",
            skills=[{"experience": "6.2", "level": "1", "name": "Smithing"}],
            output={"name": "Bronze bar", "quantity": "1", "subtxt": "Blast Furnace"},
        ),
    ]

    recipes = parse_recipes(rows, "Smithing")

    assert {recipe.key for recipe in recipes} == {
        ("Bronze bar", "Normal furnace"),
        ("Bronze bar", "Blast Furnace"),
    }
    assert {recipe.ticks for recipe in recipes} == {5, 2}


def test_fractional_experience_survives_being_a_string() -> None:
    """`"6.2"` is a real value: a bronze bar is 6.2 Smithing xp."""
    (recipe,) = parse_recipes([json.loads(json.dumps(_ATTACK_POTION)) | {
        "production_json": json.dumps(
            {
                "ticks": "5",
                "skills": [{"experience": "6.2", "level": "1", "name": "Smithing"}],
                "output": {"name": "Bronze bar", "quantity": "1"},
            }
        )
    }], "Smithing")

    assert recipe.experience == 6.2


def test_a_row_that_cannot_be_read_is_dropped_rather_than_defaulted() -> None:
    """Reference data imported wholesale: a zeroed row would be
    indistinguishable from a real one."""
    rows = [
        {"page_name": "No production"},
        {"page_name": "Not JSON", "production_json": "{"},
        _row("No output", skills=[{"experience": "1", "level": "1", "name": "Cooking"}]),
        _row("No experience", skills=[{"name": "Cooking"}], output={"name": "x"}),
    ]

    assert parse_recipes(rows, "Cooking") == ()


def test_the_query_asks_for_one_skill() -> None:
    query = recipe_query("Herblore")

    assert "bucket('recipe')" in query
    assert "where('uses_skill','Herblore')" in query
    assert "production_json" in query
