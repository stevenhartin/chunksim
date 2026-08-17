"""Teleport tablets, which are the only repeatable way to cast a teleport."""

from __future__ import annotations

from chunksim.costing import lectern
from chunksim.remote.recipes import Material, Recipe


def _tablet(output: str, materials: tuple[str, ...]) -> Recipe:
    return Recipe(
        page=output, output=output, output_quantity=1.0, skill="Magic",
        level=25, experience=35.0, ticks=4,
        materials=tuple(Material(name=name, quantity=1.0) for name in materials),
    )


_VARROCK = _tablet("Varrock teleport (tablet)", ("Law rune", "Soft clay"))
_CAMELOT = _tablet("Camelot teleport (tablet)", ("Law rune", "Soft clay"))
_ANNAKARL = _tablet("Annakarl teleport (tablet)", ("Law rune", "Soft clay"))
_BARROWS = _tablet("Barrows teleport (tablet)", ("Law rune", "Dark essence block"))

_CHALLENGES = {
    "Cast ~|varrock teleport|~": {"Items": ["Law rune"], "Primary": True},
    "Cast ~|camelot teleport|~": {"Items": ["Law rune"], "Primary": True},
    "Cast ~|annakarl teleport|~": {"Items": ["Law rune"], "Primary": True},
    "Cast ~|barrows teleport|~": {"Items": ["Law rune"], "Primary": True},
}
_RECIPES = [_VARROCK, _CAMELOT, _ANNAKARL, _BARROWS]


def _valid(*lecterns: str) -> dict[str, dict[str, int]]:
    return {"Construction": {task: 1 for task in lecterns}}


def test_the_cheapest_lectern_gates_a_standard_tablet() -> None:
    """`Lectern space`'s own table: an oak lectern at Construction 40 makes
    Varrock and nothing else; Camelot needs the teak eagle one at 57."""
    found = lectern.tablet_recipes(
        _CHALLENGES, _RECIPES, _valid("Build an ~|oak lectern|~")
    )

    assert set(found) == {"Cast ~|varrock teleport|~", "Cast ~|barrows teleport|~"}


def test_the_marble_lectern_makes_every_standard_tablet() -> None:
    """"Players can create all standard magic tablets", so it stands in for
    each of the cheaper ones rather than being listed against every row."""
    found = lectern.tablet_recipes(
        _CHALLENGES, _RECIPES, _valid(lectern.MARBLE_LECTERN)
    )

    assert "Cast ~|camelot teleport|~" in found
    assert "Cast ~|varrock teleport|~" in found


def test_a_map_with_no_house_makes_no_standard_tablet() -> None:
    """The gate is the derivation's own Construction set, so a lectern this map
    cannot build for *any* reason is simply absent."""
    found = lectern.tablet_recipes(_CHALLENGES, _RECIPES, _valid())

    assert "Cast ~|varrock teleport|~" not in found


def test_an_arceuus_tablet_needs_no_lectern_gate_because_its_material_is_one() -> None:
    """Barrows is made from a **dark essence block** rather than soft clay, and
    a map that cannot route one already has the method refused by
    `recipe_rates.rate_for`. A second gate would be a worse copy of that."""
    found = lectern.tablet_recipes(_CHALLENGES, _RECIPES, _valid())

    assert "Cast ~|barrows teleport|~" in found


def test_an_ancient_tablet_is_refused_rather_than_assumed() -> None:
    """**A whitelist, failing closed.** Annakarl consumes soft clay like the
    standard tablets, so nothing about its materials says a player-owned house
    cannot make it - and `Lectern space` does not list it, which is the only
    evidence available. Letting it through would price a method on the strength
    of the wiki's silence."""
    found = lectern.tablet_recipes(
        _CHALLENGES, _RECIPES, _valid(lectern.MARBLE_LECTERN)
    )

    assert "Cast ~|annakarl teleport|~" not in found


def test_the_page_title_is_sentence_case() -> None:
    """`Cast ~|civitas illa fortis teleport|~` against a page called
    `Civitas illa fortis teleport (tablet)` - only the first word is lifted."""
    assert lectern._spell("Cast ~|civitas illa fortis teleport|~") == (
        "Civitas illa fortis teleport"
    )
