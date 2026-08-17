"""Cleaning a grimy herb, which the wiki does not time."""

from __future__ import annotations

import pytest

from chunksim.costing import herblore
from chunksim.costing.recipe_rates import rate_for
from chunksim.remote.recipes import Material, Recipe


def _recipe(output: str, materials: tuple[str, ...], ticks: int | None) -> Recipe:
    return Recipe(
        page=output, output=output, output_quantity=1.0, skill="Herblore",
        level=1, experience=10.0, ticks=ticks,
        materials=tuple(Material(name=name, quantity=1.0) for name in materials),
    )


def test_the_clean_cycle_is_eighteen_ticks_an_inventory() -> None:
    """Open the bank, deposit, withdraw 28, close - four ticks - then fourteen
    cleaning two a tick. Eighteen ticks for 28 herbs, so 18/28 of a tick each.
    A stated figure like `heuristics.DART_CYCLE_SECONDS`, for the same reason:
    the action is not tick-gated, so nothing publishes a rate for it."""
    assert herblore.CLEAN_TICKS == pytest.approx(18.0 / 28.0)


def test_only_an_untimed_single_grimy_recipe_is_a_cleaning_action() -> None:
    """**Detected, not listed**, so a new herb needs no code change - and the
    `Degrime` variants are excluded because they consume runes as well. Those
    are the Arceuus spell rather than the click, and a different action."""
    recipes = [
        _recipe("Ranarr weed", ("Grimy ranarr weed",), None),
        _recipe("Avantoe", ("Grimy avantoe", "Earth rune", "Nature rune"), None),
        _recipe("Attack potion(3)", ("Guam potion (unf)", "Eye of newt"), 2),
        _recipe("Toadflax", ("Grimy toadflax",), 3),
    ]

    found = herblore.cleaning_ticks(recipes)

    assert found == {"Ranarr weed": herblore.CLEAN_TICKS}, (
        "the degrime variant, the mix and the already-timed recipe are all out"
    )


def test_a_published_tick_cost_is_never_overwritten() -> None:
    """A stated duration fills a gap; it does not compete. `Toadflax` above
    carries three ticks and keeps them."""
    timed = _recipe("Toadflax", ("Grimy toadflax",), 3)

    assert herblore.cleaning_ticks([timed]) == {}


def test_an_untimed_recipe_prices_once_a_duration_is_stated() -> None:
    """The whole point: `rate_for` refuses an untimed recipe, which cost
    Herblore eighteen methods, and takes one that is stated."""
    untimed = _recipe("Ranarr weed", ("Grimy ranarr weed",), None)

    def seconds(name: str, quantity: float) -> float | None:
        return 19.2 * quantity

    assert rate_for([untimed], seconds) is None
    priced = rate_for([untimed], seconds, {"Ranarr weed": herblore.CLEAN_TICKS})
    assert priced is not None
    assert priced[1] > 0


def test_the_stated_tick_is_not_truncated_to_zero() -> None:
    """**18/28 of a tick is not an `int`.** `ActionRate.ticks` was one, and
    truncating the clean cycle to zero made the action free - which in the item
    walk is the fastest method in the game."""
    assert 0.0 < herblore.CLEAN_TICKS < 1.0
