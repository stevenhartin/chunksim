"""A cast priced from the wiki's own speed."""

from __future__ import annotations

import pytest

from chunksim.costing import spells
from chunksim.costing.heuristics import MaterialCost, Rate
from chunksim.model.chunkinfo import ChunkInfo

_ALCH = "Cast ~|high level alchemy|~"
_CAMELOT = "Cast ~|camelot teleport|~"
_BOLT = "Cast ~|fire bolt|~"
_BONES = "Cast ~|bones to bananas|~"

_COSTS = {
    _ALCH: MaterialCost(65.0, {"Fire rune": 5.0, "Nature rune": 1.0}, "Utility", 5.0),
    _CAMELOT: MaterialCost(55.5, {"Law rune": 1.0}, "Teleport", 3.0),
    _BOLT: MaterialCost(22.5, {"Fire rune": 4.0}, "Combat", 3.0),
    _BONES: MaterialCost(25.0, {"Nature rune": 1.0}, "Utility", 1.0),
}

_INFO = ChunkInfo(
    {
        "challenges": {
            "Magic": {
                _ALCH: {"Items": ["Fire rune[+]*", "Nature rune*"], "Primary": True},
                _BONES: {
                    "Items": ["Earth rune[+]*", "Water rune[+]*", "Nature rune*", "Big bones[+]"],
                    "Primary": True,
                },
            }
        }
    }
)
_VALID = {"Magic": {_ALCH: 55, _BONES: 15}}


def _seconds(name: str, quantity: float) -> float | None:
    return {"Big bones[+]": 20.0}.get(name, 0.1) * quantity


def test_a_teleport_alone_is_refused_on_its_kind() -> None:
    """**Upstream's own `type` decides it.** A teleport's speed is the
    animation and not the method - you have to get back somewhere you can cast
    again, which no page states - so it is answered by `costing/lectern.py` or
    not at all.

    A **combat** cast is priced, and the figure is the base experience it pays
    whether or not it lands: a floor, correct for splashing and conservative
    for fighting, where the damage half is `costing/combat_xp.py`'s."""
    found = spells.castable(_COSTS)

    assert set(found) == {_ALCH, _BONES, _BOLT}
    assert _CAMELOT not in found


@pytest.mark.parametrize("ticks", [None, 0.0])
def test_an_untimed_or_instant_spell_is_refused(ticks: float | None) -> None:
    """Magic Imbue states `0 ticks`, and an action priced at no time is the
    fastest method in the game - the same refusal `recipe_rates.rate_for`
    makes of an untimed recipe."""
    costs = {_ALCH: MaterialCost(65.0, {"Fire rune": 5.0}, "Utility", ticks)}

    assert spells.castable(costs) == {}


def test_high_alchemy_is_five_ticks_of_sixty_five() -> None:
    """The infobox's `|speed = 5 ticks` and `|exp = 65`, which is the wiki's
    own 78,000/hr before a chunk map pays for its runes."""
    rate = spells.rate_for(
        {"Items": []}, _COSTS[_ALCH], lambda name, quantity: 0.0
    )

    assert rate == pytest.approx(65.0 * 3600.0 / 3.0)


def test_the_materials_are_the_exports_and_include_the_target() -> None:
    """**The runes are not the whole cost.** `Cast ~|bones to bananas|~` eats a
    big bone, which `infobox_spell` never mentions and upstream's own `Items`
    does. Priced on runes alone it reads 150,000/hr, which is a spell that
    would have won the whole climb."""
    challenge = _INFO.challenges["Magic"][_BONES]

    runes_only = spells.rate_for({"Items": []}, _COSTS[_BONES], _seconds)
    charged = spells.rate_for(challenge, _COSTS[_BONES], _seconds)

    assert runes_only is not None and charged is not None
    assert runes_only == pytest.approx(25.0 * 3600.0 / 0.6)
    assert charged < runes_only / 20


def test_an_input_with_no_route_drops_the_method() -> None:
    """Tick-math over inputs nothing can price is a made-up number, and the
    inputs in question are exactly the ones too hard to price."""
    challenge = _INFO.challenges["Magic"][_BONES]

    assert spells.rate_for(challenge, _COSTS[_BONES], lambda name, q: None) is None


def test_only_reachable_primary_challenges_are_priced() -> None:
    found = spells.computed_rates(_INFO, _VALID, _COSTS, _seconds)

    assert set(found) == {_ALCH, _BONES}
    assert spells.computed_rates(_INFO, {"Magic": {}}, _COSTS, _seconds) == {}


def test_a_spell_fills_the_floor_and_beats_a_guide() -> None:
    computed = spells.computed_rates(_INFO, _VALID, _COSTS, _seconds)
    training = {
        _ALCH: {"Magic": Rate(1_000.0, "default", "default")},
        _BONES: {"Magic": Rate(7_771.0, "mmg:Casting bones to bananas", "exact")},
    }

    merged = spells.apply(training, computed)

    assert merged[_ALCH]["Magic"].source == spells.SPELL_SOURCE
    assert merged[_BONES]["Magic"].source == spells.SPELL_SOURCE


def test_a_recipe_keeps_the_method() -> None:
    """**Under the recipes, over the scrape.** A recipe knows which variant of
    an action it describes and carries its own tick cost, so where both reach
    a task the recipe is the more specific claim - and `REPLACEABLE` is shared
    rather than restated so the two layers cannot drift."""
    computed = spells.computed_rates(_INFO, _VALID, _COSTS, _seconds)
    training = {_ALCH: {"Magic": Rate(4_000.0, "recipe", "computed")}}

    merged = spells.apply(training, computed)

    assert merged[_ALCH]["Magic"].source == "recipe"


def test_a_hand_pin_outranks_it() -> None:
    computed = spells.computed_rates(_INFO, _VALID, _COSTS, _seconds)
    training = {_ALCH: {"Magic": Rate(1_000.0, "default", "default")}}

    merged = spells.apply(training, computed, frozenset({_ALCH}))

    assert merged[_ALCH]["Magic"].source == "default"


# --- a teleport with no lectern has no method ---------------------------


def test_an_untabled_teleport_loses_its_guide() -> None:
    """**A bare teleport cast is not a training method**, which is why
    `castable` refuses the kind at all - the cast moves you somewhere you
    cannot cast it again. So the only honest rate is a tablet rate, and a map
    that can build no lectern making that tablet has no method rather than a
    slow one. `mmg:Money making guide/Creating Camelot teleport tablets` is a
    real figure for a real method that map does not have."""
    training = {_CAMELOT: {"Magic": Rate(41_625.0, "mmg:Creating Camelot tablets", "contained")}}

    merged = spells.refuse_untabled(training, _COSTS, frozenset())

    assert merged[_CAMELOT] == {}


def test_a_tabled_teleport_keeps_what_it_has() -> None:
    training = {_CAMELOT: {"Magic": Rate(11_679.0, "recipe", "computed")}}

    merged = spells.refuse_untabled(training, _COSTS, frozenset({_CAMELOT}))

    assert merged[_CAMELOT]["Magic"].value == 11_679.0


def test_a_utility_spell_is_never_refused_this_way() -> None:
    """The rule is about teleports, and the infobox's own kind says which."""
    training = {_ALCH: {"Magic": Rate(78_000.0, "mmg:Alching", "exact")}}

    merged = spells.refuse_untabled(training, _COSTS, frozenset())

    assert merged[_ALCH]["Magic"].value == 78_000.0


def test_a_model_survives_where_a_scrape_does_not() -> None:
    """A `modelled` rate is a model's own answer about a whole activity rather
    than a claim about which lectern was built."""
    training = {_CAMELOT: {"Magic": Rate(9_000.0, "computed:something", "modelled")}}

    merged = spells.refuse_untabled(training, _COSTS, frozenset())

    assert merged[_CAMELOT]["Magic"].match == "modelled"


def test_a_hand_pin_survives_too() -> None:
    training = {_CAMELOT: {"Magic": Rate(41_625.0, "mmg:Creating Camelot tablets", "contained")}}

    merged = spells.refuse_untabled(training, _COSTS, frozenset(), frozenset({_CAMELOT}))

    assert merged[_CAMELOT]["Magic"].value == 41_625.0


def test_a_refused_cast_names_the_reagent_it_wanted() -> None:
    """The diagnosis behind a refusal, so `unpriced` can say which reagent it
    wanted - the same job `recipe_rates.unroutable` does for a recipe."""
    challenge = {"Items": ["Fire rune[+]*", "Death rune*", "Iban's staff"]}

    def priced(item: str, quantity: float) -> float | None:
        return None if item == "Iban's staff" else 1.0

    assert spells.unroutable(challenge, priced) == "Iban's staff"


def test_a_cast_whose_reagents_all_route_names_nothing() -> None:
    assert spells.unroutable({"Items": ["Fire rune*"]}, lambda i, q: 1.0) == ""


def test_computed_rates_records_what_it_dropped() -> None:
    """Only on failure, so the succeeding path pays nothing for it."""
    costs = {_ALCH: MaterialCost(65.0, {"Fire rune": 5.0}, "Utility", 5.0)}
    dropped: dict[str, str] = {}

    priced = spells.computed_rates(
        _INFO, _VALID, costs, lambda i, q: None, dropped
    )

    assert priced == {}
    assert dropped[_ALCH] == "Fire rune[+]"
