"""Chiselling a dark essence block, which costs nothing because it is done on the run."""

from __future__ import annotations

from chunksim.costing import chisel
from chunksim.remote.recipes import Material, Recipe


def _recipe(
    output: str,
    skill: str,
    materials: tuple[str, ...],
    ticks: float | None,
    quantity: float = 1.0,
) -> Recipe:
    return Recipe(
        page=output, output=output, output_quantity=quantity, skill=skill,
        level=1, experience=8.0, ticks=ticks,
        materials=tuple(Material(name=name, quantity=1.0) for name in materials),
    )


def test_the_chisel_is_free() -> None:
    """Zero, and it is a claim about *this* action's geography: the blocks are
    chiselled while running from the Dark Altar to the blood or soul altar, on
    a trip the rune's own recipe is already paying for."""
    assert chisel.CHISEL_TICKS == 0


def test_only_the_dark_essence_chisel_is_stated() -> None:
    """**Named rather than inferred from the verb.** A gem cut into bolt tips is
    a bank action, tick-gated and emphatically not free, and a rule over chisels
    would hand it the same zero."""
    recipes = {
        "Crafting": [
            _recipe("Dark essence fragments", "Crafting", ("Dark essence block",), None, 4.0),
            _recipe("Ruby bolt tips", "Crafting", ("Ruby",), None, 12.0),
        ]
    }

    assert chisel.stated_ticks(recipes) == {"Dark essence fragments": 0.0}


def test_a_published_tick_cost_is_never_overwritten() -> None:
    """A stated duration fills a gap; it does not compete. Were the wiki to time
    the chisel, that figure would win - which is the same rule
    `herblore.cleaning_ticks` follows."""
    timed = _recipe("Dark essence fragments", "Crafting", ("Dark essence block",), 3, 4.0)

    assert chisel.stated_ticks({"Crafting": [timed]}) == {}


def test_the_skill_is_crafting_not_runecraft() -> None:
    """Why the export has no challenge for it, and so why the fragments had no
    route at all: upstream lists what pays experience in the skill owning the
    challenge, and chiselling pays Crafting while the runes are Runecraft."""
    fragments = _recipe(
        "Dark essence fragments", "Runecraft", ("Dark essence block",), None, 4.0
    )

    assert chisel.stated_ticks({"Runecraft": [fragments]}) == {}
