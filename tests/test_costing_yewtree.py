"""A tick cost every sibling recipe states and this one page leaves blank."""

from __future__ import annotations

from chunksim.costing import yewtree
from chunksim.remote.recipes import Material, Recipe


def _recipe(
    output: str,
    skill: str,
    materials: tuple[str, ...],
    ticks: float | None,
) -> Recipe:
    return Recipe(
        page=output, output=output, output_quantity=1.0, skill=skill,
        level=60, experience=141.0, ticks=ticks,
        materials=tuple(Material(name=name, quantity=1.0) for name in materials),
    )


def test_the_yew_tree_is_five_ticks() -> None:
    """Read off every sibling on the same POH page - oak/willow/maple/magic/
    spirit tree (Construction) are all `ticks = 5`, and the mechanic is
    identical across the family."""
    assert yewtree.YEW_TREE_TICKS == 5


def test_only_the_yew_tree_is_stated() -> None:
    """**Named rather than inferred from the family.** 650 of the corpus's
    4,043 recipes carry no stated ticks, far too broad a net to trust without
    checking each one - so a magic tree left untimed stays untimed."""
    recipes = {
        "Construction": [
            _recipe("Yew tree (Construction)", "Construction", ("Bagged yew tree",), None),
            _recipe("Magic tree (Construction)", "Construction", ("Bagged magic tree",), None),
        ]
    }

    found = yewtree.stated_ticks(recipes)

    assert found == {"Yew tree (Construction)": 5.0}


def test_a_published_tick_cost_is_never_overwritten() -> None:
    recipes = {
        "Construction": [
            _recipe("Yew tree (Construction)", "Construction", ("Bagged yew tree",), 3.0),
        ]
    }

    assert yewtree.stated_ticks(recipes) == {}


def test_only_construction_is_asked() -> None:
    """A different skill's recipe of the same name is not this one."""
    recipes = {
        "Farming": [
            _recipe("Yew tree (Construction)", "Farming", ("Bagged yew tree",), None),
        ]
    }

    assert yewtree.stated_ticks(recipes) == {}
