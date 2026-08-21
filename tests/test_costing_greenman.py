"""`costing/greenman.py`: one blank cell in a two-recipe family."""

from __future__ import annotations

from chunksim.costing import greenman
from chunksim.remote.recipes import Recipe


def _recipe(output: str, ticks: float | None) -> Recipe:
    return Recipe(
        page=output,
        output=output,
        output_quantity=1.0,
        skill="Fletching",
        level=79,
        experience=70.0,
        ticks=ticks,
        materials=(),
    )


def test_the_untimed_carving_is_filled() -> None:
    found = greenman.stated_ticks({"Fletching": [_recipe("Greenman carving", None)]})

    assert found == {"Greenman carving": 4.0}


def test_a_published_duration_is_never_overwritten() -> None:
    """Every contributor to `recipe_rates.stated_ticks` fills only where the
    wiki says nothing - that is what lets the four merge in any order."""
    found = greenman.stated_ticks({"Fletching": [_recipe("Greenman carving", 9)]})

    assert found == {}


def test_the_construction_page_of_the_same_name_is_not_touched() -> None:
    """`Greenman carving (Construction)` is mounting the finished carving in a
    house - a different action on a different page, and it states its own 5."""
    found = greenman.stated_ticks(
        {"Construction": [_recipe("Greenman carving (Construction)", None)]}
    )

    assert found == {}


def test_the_statue_is_left_alone() -> None:
    """The sibling is the *check* on the measured figure, not its subject - the
    wiki times it already."""
    found = greenman.stated_ticks({"Fletching": [_recipe("Greenman statue", None)]})

    assert found == {}


def test_it_agrees_with_the_sibling_the_wiki_does_time() -> None:
    """Measured in game at 4 ticks; `Greenman statue`'s `{{Recipe}}` publishes
    4 for the same action one log tier down. Two independent figures, and this
    pins that they still match."""
    assert greenman.GREENMAN_CARVING_TICKS == 4
