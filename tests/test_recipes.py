"""Tests for `remote/recipes.py`: the wiki's per-action facts, parsed.

The shapes here are all taken from real Bucket rows - the double-encoded JSON,
the numbers-as-strings, the empty tick field, the two recipes on one page. No
test touches the network; `fetch_bucket` is `api.py`'s and is tested there.
"""

from __future__ import annotations

import json
from typing import Any

from chunksim.remote.recipes import Recipe, parse_recipes, recipe_query


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


def test_a_stated_zero_is_kept_and_is_not_a_published_duration() -> None:
    """**The two used to be the same thing here and are not.** `ticks = 0` is
    a claim - `Module:Recipe` renders it "0 (0s) per action", meaning the game
    imposes no delay - where `ticks = ""` means nobody has timed it. Collapsing
    the zero into `None` beside the blank threw away a published fact about
    448 of the table's 4,082 rows. `Recipe.timed` is what a caller asking
    "did the wiki give me a duration" wants, and it is false for both."""
    row = _row(
        "Instant",
        ticks="0",
        skills=[{"experience": "10", "level": "1", "name": "Crafting"}],
        output={"name": "Something", "quantity": "1"},
    )

    (recipe,) = parse_recipes([row], "Crafting")

    assert recipe.ticks == 0.0
    assert recipe.timed is False


def test_a_positive_tick_cost_is_timed() -> None:
    row = _row(
        "Timed",
        ticks="3",
        skills=[{"experience": "10", "level": "1", "name": "Crafting"}],
        output={"name": "Something", "quantity": "1"},
    )

    (recipe,) = parse_recipes([row], "Crafting")

    assert recipe.ticks == 3.0
    assert recipe.timed is True


def test_a_blank_is_untimed_and_is_not_a_zero() -> None:
    """The distinction the other way round: a caller must be able to tell
    "instant" from "unknown", because they get different answers."""
    row = _row(
        "Unknown",
        ticks="",
        skills=[{"experience": "10", "level": "1", "name": "Crafting"}],
        output={"name": "Something", "quantity": "1"},
    )

    (recipe,) = parse_recipes([row], "Crafting")

    assert recipe.ticks is None
    assert recipe.timed is False


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


class TestARecipeThatPaysNothingIsStillARoute:
    """**`{{Recipe}}` files a recipe under a skill only where it awards
    experience**, so `bucket('recipe').where('uses_skill', ...)` cannot see
    the assembly moves in the middle of a chain - pressing `Gianne dough` into
    a `Batta tin`, threading a `Spider carcass` onto a `Skewer stick`. Those
    outputs then had no route anywhere and everything behind them was dropped
    for want of an input."""

    def test_a_skill_less_row_becomes_a_zero_xp_recipe(self) -> None:
        from chunksim.remote.recipes import UNSKILLED, parse_unskilled

        row = _row(
            "Spider on stick (raw)",
            ticks="1",
            skills=[],
            output={"name": "Spider on stick (raw)", "quantity": "1"},
            materials=[
                {"name": "Skewer stick", "quantity": "1"},
                {"name": "Spider carcass", "quantity": "1"},
            ],
        )

        (recipe,) = parse_unskilled([row])

        assert recipe.output == "Spider on stick (raw)"
        assert recipe.skill == UNSKILLED
        assert (recipe.experience, recipe.level) == (0.0, 1)
        assert recipe.ticks == 1.0
        assert [m.name for m in recipe.materials] == ["Skewer stick", "Spider carcass"]

    def test_a_row_that_pays_a_skill_is_left_to_the_per_skill_sweep(self) -> None:
        from chunksim.remote.recipes import parse_unskilled

        row = _row(
            "Bread",
            ticks="1",
            skills=[{"experience": "40", "level": "1", "name": "Cooking"}],
            output={"name": "Bread", "quantity": "1"},
            materials=[{"name": "Bread dough", "quantity": "1"}],
        )

        assert parse_unskilled([row]) == ()

    def test_a_row_with_no_materials_is_not_a_route(self) -> None:
        """Nothing to charge and nothing to walk through."""
        from chunksim.remote.recipes import parse_unskilled

        row = _row(
            "Thing",
            ticks="1",
            skills=[],
            output={"name": "Thing", "quantity": "1"},
            materials=[],
        )

        assert parse_unskilled([row]) == ()

    def test_the_query_pages_past_the_row_cap(self) -> None:
        """Measured: `limit(6000)` yields 5,000 exactly where `limit(4000)`
        yields 4,000, so it is a server cap and the table is bigger."""
        from chunksim.remote.recipes import BUCKET_PAGE, unskilled_query

        first = unskilled_query(BUCKET_PAGE, 0)
        second = unskilled_query(BUCKET_PAGE, BUCKET_PAGE)

        assert "offset" not in first
        assert f".offset({BUCKET_PAGE})" in second
        assert "uses_skill" not in first

    def test_the_key_is_not_a_skill_any_challenge_answers_to(self) -> None:
        """Everything that reads the corpus by skill has to be inert for
        these: `computed_rates` looks challenges up under the key and finds
        none."""
        from chunksim.costing import coverage
        from chunksim.remote.recipes import UNSKILLED

        assert UNSKILLED not in coverage.SKILLS


class TestAgainstTheShippedCorpus:
    def test_the_unskilled_rows_are_there_and_pay_nothing(self) -> None:
        from chunksim.costing.inputs import load_reference
        from chunksim.remote.recipes import UNSKILLED

        rows = load_reference(None, None).recipes.get(UNSKILLED, ())

        assert len(rows) > 100
        assert {recipe.experience for recipe in rows} == {0.0}
        assert all(recipe.materials for recipe in rows)

    def test_the_three_that_prompted_it_are_present(self) -> None:
        from chunksim.costing.inputs import load_reference
        from chunksim.remote.recipes import UNSKILLED

        made = {
            recipe.output for recipe in load_reference(None, None).recipes.get(UNSKILLED, ())
        }

        assert {"Raw batta", "Spider on stick (raw)", "Spider on shaft (raw)"} <= made


class TestOnlyTheReachableUnskilledRecipesAreKept:
    """1,950 skill-less recipes exist and a corpus wants about a tenth. The
    walk only ever reaches one as the *material* of something, so the set that
    matters is the closure of "named by a skilled recipe, or by an unskilled
    one already in the set"."""

    def _recipe(self, output: str, materials: list[str], skill: str) -> Recipe:
        from chunksim.remote.recipes import Material

        return Recipe(
            page=output,
            output=output,
            output_quantity=1.0,
            skill=skill,
            level=1,
            experience=0.0,
            ticks=1.0,
            materials=tuple(Material(name, 1.0) for name in materials),
        )

    def test_a_material_a_skilled_recipe_wants_is_kept(self) -> None:
        from chunksim.remote.recipes import UNSKILLED, reachable_unskilled

        skilled = [self._recipe("Pie", ["Raw batta"], "Cooking")]
        unskilled = [self._recipe("Raw batta", ["Gianne dough"], UNSKILLED)]

        assert reachable_unskilled(skilled, unskilled) == tuple(unskilled)

    def test_the_closure_follows_the_chain(self) -> None:
        from chunksim.remote.recipes import UNSKILLED, reachable_unskilled

        skilled = [self._recipe("Pie", ["Shell"], "Cooking")]
        unskilled = [
            self._recipe("Shell", ["Dough"], UNSKILLED),
            self._recipe("Dough", ["Flour"], UNSKILLED),
        ]

        assert reachable_unskilled(skilled, unskilled) == tuple(unskilled)

    def test_what_no_chain_asks_for_is_dropped(self) -> None:
        from chunksim.remote.recipes import UNSKILLED, reachable_unskilled

        skilled = [self._recipe("Pie", ["Shell"], "Cooking")]
        unskilled = [
            self._recipe("Shell", ["Dough"], UNSKILLED),
            self._recipe("Toy", ["Wood"], UNSKILLED),
        ]

        assert [r.output for r in reachable_unskilled(skilled, unskilled)] == ["Shell"]

    def test_a_cycle_does_not_hang_it(self) -> None:
        from chunksim.remote.recipes import UNSKILLED, reachable_unskilled

        skilled = [self._recipe("Pie", ["A"], "Cooking")]
        unskilled = [
            self._recipe("A", ["B"], UNSKILLED),
            self._recipe("B", ["A"], UNSKILLED),
        ]

        assert len(reachable_unskilled(skilled, unskilled)) == 2

    def test_the_shipped_corpus_is_the_closure_rather_than_the_table(self) -> None:
        """Carrying all 1,950 doubled a cold every-rollable-chunk estimate and
        added 900KB to a blob that ships in the wheel."""
        from chunksim.costing.inputs import load_reference
        from chunksim.remote.recipes import UNSKILLED

        rows = load_reference(None, None).recipes.get(UNSKILLED, ())

        assert 100 < len(rows) < 800
