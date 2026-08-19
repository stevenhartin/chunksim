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


def test_every_timed_kind_is_priced() -> None:
    """All three of `infobox_spell`'s types carry a speed that is the whole
    cost of a cast, once a teleport's clicking overhead is allowed for.

    A **combat** cast is the base experience it pays whether or not it lands:
    a floor, correct for splashing and conservative for fighting, where the
    damage half is `costing/combat_xp.py`'s. A **teleport** is its animation
    plus `TELEPORT_OVERHEAD_SECONDS` - it used to be refused on the
    since-disproved claim that you cannot cast it again from where you land."""
    found = spells.castable(_COSTS)

    assert set(found) == {_ALCH, _BONES, _BOLT, _CAMELOT}


class TestTheTeleportOverhead:
    """One published figure, one parameter - so reproducing that figure is an
    **identity**, not agreement. What it buys is the *shape*: the overhead is
    the interface rather than the destination, so it carries to every teleport
    and to speeds the Camelot figure never saw."""

    def test_it_reproduces_the_figure_it_was_fitted_to(self) -> None:
        cost = MaterialCost(spells.CAMELOT_XP, {}, "Teleport", spells.CAMELOT_TICKS)

        hourly = spells.CAMELOT_XP * 3600.0 / spells.cast_seconds(cost)

        assert hourly == pytest.approx(spells.CAMELOT_HOURLY)

    def test_the_animation_alone_would_overstate(self) -> None:
        """111,000/hr against the observed 80,000 - a 39% gap, which is the
        0.7 seconds of clicking this constant carries."""
        animation = spells.CAMELOT_XP * 3600.0 / (spells.CAMELOT_TICKS * 0.6)

        assert animation == pytest.approx(111_000.0)
        assert spells.TELEPORT_OVERHEAD_SECONDS == pytest.approx(0.698, abs=0.001)

    def test_a_slower_teleport_pays_the_same_overhead(self) -> None:
        """It is the clicking, so a 4-tick teleport cycles in 3.098s."""
        cost = MaterialCost(50.0, {}, "Teleport", 4.0)

        assert spells.cast_seconds(cost) == pytest.approx(3.098, abs=0.001)

    def test_nothing_else_pays_it(self) -> None:
        cost = MaterialCost(65.0, {}, "Utility", 5.0)

        assert spells.cast_seconds(cost) == pytest.approx(3.0)


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


class TestSpellSacks:
    """A blighted sack replaces the runes and nothing else - the same spell,
    the same experience, the same cast speed - so the variant borrows all
    three from the cast it names and differs only in what it eats."""

    _SACK = "Cast ~|wind wave|~ from a blighted spell sack"
    _BASE = "Cast ~|wind wave|~"
    _CHALLENGES = {
        _BASE: {"Items": ["Air rune[+]*", "Blood rune*"], "Primary": True},
        _SACK: {"Items": ["Blighted surge sack*"], "Primary": True},
    }
    _COSTS = {_BASE: MaterialCost(36.0, {"Air rune": 5.0}, "Combat", 5.0)}

    def test_the_suffix_names_the_base_cast(self) -> None:
        assert spells.base_cast(self._SACK) == self._BASE
        assert spells.base_cast("Cast ~|snare|~ from a spell sack") == "Cast ~|snare|~"

    def test_a_plain_cast_is_not_a_variant(self) -> None:
        assert spells.base_cast(self._BASE) == ""

    def test_the_variant_takes_the_base_numbers(self) -> None:
        found = spells.with_sacks(self._COSTS, self._CHALLENGES)

        assert found[self._SACK].experience == 36.0
        assert found[self._SACK].ticks == 5.0
        assert found[self._SACK].kind == "Combat"

    def test_it_eats_the_sack_and_not_the_runes(self) -> None:
        """Nothing in this module prices with `items` - `rate_for` reads the
        challenge - but `inputs.spell_material_costs` does, and charging runes
        for a sack cast would bill the cost the method exists to avoid."""
        found = spells.with_sacks(self._COSTS, self._CHALLENGES)

        assert found[self._SACK].items == {"Blighted surge sack": 1.0}

    def test_a_variant_with_its_own_entry_keeps_it(self) -> None:
        """Never overwrites, for the reason `with_aliases` never displaces a
        real name."""
        mine = MaterialCost(1.0, {}, "Combat", 1.0)

        found = spells.with_sacks({**self._COSTS, self._SACK: mine}, self._CHALLENGES)

        assert found[self._SACK] is mine

    def test_a_variant_whose_base_is_unknown_is_skipped(self) -> None:
        assert self._SACK not in spells.with_sacks({}, self._CHALLENGES)


class TestAQuestPrizeIsHeldNotEaten:
    """`Cast ~|iban blast|~` needs Iban's staff and the nine resurrections a
    Book of the dead, and both are quest rewards - so the quest is already
    done, or the challenge would not be valid. Charging one per cast bills the
    whole quest every three seconds, which is why both refused outright."""

    _CHALLENGE = {
        "Items": ["Fire rune[+]*", "Death rune*", "Iban's staff"],
        "Primary": True,
    }
    _COST = MaterialCost(30.0, {"Fire rune": 5.0}, "Combat", 5.0)
    _REWARDS = frozenset({"Iban's staff"})

    def _refuses_the_staff(self, item: str, quantity: float) -> float | None:
        return None if "staff" in item else 1.0

    def test_the_prize_is_not_charged(self) -> None:
        rate = spells.rate_for(
            self._CHALLENGE, self._COST, self._refuses_the_staff, self._REWARDS
        )

        assert rate is not None and rate > 0

    def test_without_the_reward_set_it_still_refuses(self) -> None:
        """The exemption is the conjunction, not the marker - nothing is free
        merely for being listed."""
        assert spells.rate_for(self._CHALLENGE, self._COST, self._refuses_the_staff) is None

    def test_a_consumed_item_is_charged_even_if_it_is_a_prize(self) -> None:
        """**The marker alone is not enough and neither is the reward list.**
        Upstream writes `*` for what an action eats, and measured over the
        export not one quest prize carries it - but if one ever did, it would
        be a reagent and must be paid for."""
        challenge = {"Items": ["Iban's staff*"], "Primary": True}

        assert spells.rate_for(challenge, self._COST, self._refuses_the_staff, self._REWARDS) is None

    def test_the_diagnosis_does_not_blame_the_prize(self) -> None:
        """`unroutable` must skip it too, or an unpriced cast names a staff
        the player already owns."""
        assert spells.unroutable(self._CHALLENGE, self._refuses_the_staff, self._REWARDS) == ""
        assert spells.unroutable(self._CHALLENGE, self._refuses_the_staff) == "Iban's staff"

    def test_the_reward_set_is_read_off_the_export(self) -> None:
        info = ChunkInfo(
            {"challenges": {"Quest": {"~|Underground Pass|~ Complete the quest": {
                "Reward": ["Iban's staff", "Klank's gauntlets"]}}}}
        )

        assert spells.quest_rewards(info) == {"Iban's staff", "Klank's gauntlets"}


class TestAStatedCadence:
    """The spell layer's `recipe_rates.stated_ticks`, and held to the same
    rule: fills only where the wiki is blank, never overwrites."""

    def test_monster_examine_is_an_ordinary_manual_cast(self) -> None:
        """Neither instant nor on a cooldown - its infobox simply leaves
        `speed` blank where every other Combat and Utility spell fills it."""
        assert spells.STATED_TICKS["Cast ~|monster inspect|~"] == 5.0

    def test_it_fills_only_a_blank(self) -> None:
        task = "Cast ~|monster inspect|~"
        blank = {task: MaterialCost(30.5, {"Body rune": 2.0}, "Utility", None)}

        assert spells.timed(blank)[task].ticks == 5.0

    def test_a_published_figure_survives(self) -> None:
        task = "Cast ~|monster inspect|~"
        stated = {task: MaterialCost(30.5, {"Body rune": 2.0}, "Utility", 3.0)}

        assert spells.timed(stated)[task].ticks == 3.0

    def test_a_spell_it_does_not_name_is_untouched(self) -> None:
        costs = {_ALCH: MaterialCost(65.0, {}, "Utility", None)}

        assert spells.timed(costs)[_ALCH].ticks is None

    def test_the_supply_bound_spells_are_not_here(self) -> None:
        """The other five the wiki leaves untimed belong to
        `costing/oneoff.py`: their wait is a drop table's or a growth
        clock's, so a figure from the cast would answer the wrong question."""
        from chunksim.costing import oneoff

        for task in spells.STATED_TICKS:
            assert oneoff.reason(task) == ""
        assert oneoff.reason("Cast ~|basic reanimation|~")
        assert oneoff.reason("Cast ~|resurrect crops|~")
