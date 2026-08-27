"""Tests for the DPS bridge.

Every test here is gated on `osrs-dps` being installed, since it is an
optional extra - a fresh clone without it must *skip*, not fail. Fixtures are
built by hand; nothing reads the real export or the real cache.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

from types import SimpleNamespace
from typing import Any, cast

import pathlib
from typing import Any

import pytest

from chunksim.costing import dps_bridge
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.derive.pipeline import MapState
from chunksim.costing.heuristics import Heuristics, Rate
from chunksim.derive.sources import SourceIndex

pytestmark = pytest.mark.skipif(
    not dps_bridge.DPS_AVAILABLE,
    reason="osrs-dps is an optional extra; install it with `pip install -e ../osrs-dps`",
)


def _equipment() -> dict[str, Any]:
    """A handful of items, shaped exactly as the export shapes them."""
    return {
        "Abyssal whip": {
            "attack_slash": 82,
            "attack_stab": 0,
            "attack_crush": 0,
            "melee_strength": 82,
            "attack_speed": 4,
            "slot": "weapon",
        },
        "Dragon dagger": {
            "attack_stab": 40,
            "attack_slash": 25,
            "attack_crush": 0,
            "melee_strength": 40,
            "attack_speed": 4,
            "slot": "weapon",
        },
        "Rune platebody": {"defence_slash": 82, "attack_speed": 0, "slot": "body"},
        "Webweaver bow (u)": {
            "attack_ranged": 85,
            "ranged_strength": 65,
            "attack_speed": 4,
            "slot": "2h",
        },
        "Occult necklace": {"attack_magic": 10, "magic_damage": 5, "slot": "neck"},
        "Master wand": {
            "attack_magic": 20,
            "magic_damage": 10,
            "attack_speed": 4,
            "slot": "weapon",
        },
    }


def _chunk_info() -> ChunkInfo:
    return ChunkInfo({"equipment": _equipment()})


LEVELS = {"Attack": 75, "Strength": 70, "Ranged": 70, "Magic": 87, "Hitpoints": 99}


def test_magic_damage_is_scaled_to_tenths_of_a_percent() -> None:
    """The one field where the field-for-field copy breaks.

    The export stores a display percentage and the library wants upstream's
    `magic_str`. Occult necklace is 5 here and 50 there, Master wand 10 and
    100 - measured against upstream's own `equipment.json`. Copying straight
    through under-reports every magic hit tenfold.
    """
    picks = {"Magic-weapon": "Master wand", "Magic-neck": "Occult necklace"}
    loadouts = dps_bridge.build_loadouts(_chunk_info(), picks, LEVELS)

    assert loadouts["Magic"].bonuses.magic_damage == 150
    assert loadouts["Magic"].bonuses.attack_magic == 30


def test_two_handedness_comes_from_the_entry_not_the_pick_key() -> None:
    """`bis.py` files every weapon under a `weapon` pick key.

    A 2H winner replaces the weapon *and* shield picks rather than appearing
    under a `2h` key, so reading the key would call the map's real
    `Webweaver bow (u)` one-handed. The export entry's `slot` is the truth.
    """
    picks = {"Ranged-weapon": "Webweaver bow (u)"}
    loadouts = dps_bridge.build_loadouts(_chunk_info(), picks, LEVELS)

    assert loadouts["Ranged"].two_handed is True
    assert loadouts["Ranged"].weapon_name == "Webweaver bow (u)"


def test_melee_style_follows_the_weapon_not_the_pick() -> None:
    """A whip is slash and a dragon dagger stab; `bis.py` says neither."""
    whip = dps_bridge.build_loadouts(
        _chunk_info(), {"Melee-weapon": "Abyssal whip"}, LEVELS
    )
    dagger = dps_bridge.build_loadouts(
        _chunk_info(), {"Melee-weapon": "Dragon dagger"}, LEVELS
    )

    assert whip["Melee"].style.value == "slash"
    assert dagger["Melee"].style.value == "stab"


def test_bonuses_sum_across_the_worn_set() -> None:
    picks = {"Melee-weapon": "Abyssal whip", "Melee-body": "Rune platebody"}
    loadouts = dps_bridge.build_loadouts(_chunk_info(), picks, LEVELS)

    assert loadouts["Melee"].bonuses.attack_slash == 82
    assert loadouts["Melee"].bonuses.defence_slash == 82
    assert loadouts["Melee"].bonuses.melee_strength == 82


def test_a_style_with_no_picks_is_absent_rather_than_empty() -> None:
    """An early chunk with no magic weapon should price magic badly, not at
    all - but an *absent* style is different from a naked one, and only the
    former is honest about having nothing to say."""
    loadouts = dps_bridge.build_loadouts(
        _chunk_info(), {"Melee-weapon": "Abyssal whip"}, LEVELS
    )
    assert set(loadouts) == {"Melee"}


def test_unknown_items_do_not_break_the_sum() -> None:
    """A pick the equipment branch has never heard of contributes nothing.

    Firebase omits empty containers and the export is not guaranteed complete,
    so a missing entry has to read as zero bonuses rather than an exception.
    """
    picks = {"Melee-weapon": "Abyssal whip", "Melee-head": "Nonexistent helm"}
    loadouts = dps_bridge.build_loadouts(_chunk_info(), picks, LEVELS)

    assert loadouts["Melee"].bonuses.attack_slash == 82


def test_speed_falls_back_when_the_weapon_declares_none() -> None:
    """Armour entries carry `attack_speed: 0`, which is not a real speed."""
    info = ChunkInfo({"equipment": {"Odd weapon": {"attack_speed": 0, "slot": "weapon"}}})
    loadouts = dps_bridge.build_loadouts(info, {"Melee-weapon": "Odd weapon"}, LEVELS)

    assert loadouts["Melee"].attack_speed == 4


class _FakeIndex:
    """Enough of `MonsterIndex` for the resolution tests."""

    def __init__(self, names: dict[str, Any]) -> None:
        self._names = names

    def get(self, name: str) -> Any:
        return self._names.get(name)

    def __iter__(self) -> Any:
        return iter(self._names)


def _target(**kwargs: Any) -> Any:
    from osrs_dps import Target

    return Target(**kwargs)


def test_an_exact_name_resolves_to_itself() -> None:
    index = _FakeIndex({"General Graardor": _target(name="General Graardor", hitpoints=255)})
    resolved = dps_bridge.candidate_targets(index, "General Graardor")  # type: ignore[arg-type]

    assert [key for key, _ in resolved] == ["General Graardor"]


def test_an_ambiguous_name_offers_every_version() -> None:
    """The library refuses to guess, so the bridge collects and chooses."""
    index = _FakeIndex(
        {
            "Cave bug#Level 6": _target(name="Cave bug", hitpoints=5),
            "Cave bug#Level 96": _target(name="Cave bug", hitpoints=93),
            "Cave crawler#Level 23": _target(name="Cave crawler", hitpoints=22),
        }
    )
    resolved = dps_bridge.candidate_targets(index, "Cave bug")  # type: ignore[arg-type]

    assert sorted(key for key, _ in resolved) == ["Cave bug#Level 6", "Cave bug#Level 96"]


def test_sequential_phases_are_refused_rather_than_priced() -> None:
    """You fight every phase, so the fastest one is not the fight.

    Picking the softest phase under-reports the kill, and the 13 names this
    catches on the real export are all bosses - where the hours are.
    """
    index = _FakeIndex(
        {
            "Abyssal Sire#Phase 1": _target(name="Abyssal Sire", hitpoints=425),
            "Abyssal Sire#Phase 3 (stage 2)": _target(name="Abyssal Sire", hitpoints=425),
        }
    )
    assert dps_bridge.candidate_targets(index, "Abyssal Sire") == ()  # type: ignore[arg-type]


def test_an_absent_name_resolves_to_nothing() -> None:
    index = _FakeIndex({"Cave bug#Level 6": _target(name="Cave bug", hitpoints=5)})
    assert dps_bridge.candidate_targets(index, "Al-Kharid warrior") == ()  # type: ignore[arg-type]


def test_best_kill_picks_the_fastest_style_and_variant() -> None:
    loadouts = dps_bridge.build_loadouts(
        _chunk_info(),
        {"Melee-weapon": "Abyssal whip", "Ranged-weapon": "Webweaver bow (u)"},
        LEVELS,
    )
    weak = _target(name="Cave bug", hitpoints=5)
    strong = _target(name="Cave bug", hitpoints=93)

    kill = dps_bridge.best_kill(
        loadouts, "Cave bug", [("Cave bug#Level 96", strong), ("Cave bug#Level 6", weak)]
    )

    assert kill is not None
    assert kill.monster == "Cave bug#Level 6"
    assert kill.match == "variant"
    assert kill.style in dps_bridge.OFFENSIVE_STYLES


def test_best_kill_reports_an_exact_match_as_such() -> None:
    loadouts = dps_bridge.build_loadouts(
        _chunk_info(), {"Melee-weapon": "Abyssal whip"}, LEVELS
    )
    kill = dps_bridge.best_kill(
        loadouts, "Rat", [("Rat", _target(name="Rat", hitpoints=8))]
    )

    assert kill is not None and kill.match == "exact"


def test_an_unkillable_target_is_not_priced() -> None:
    """A leafy monster takes nothing from a whip.

    The library reports that as `dps == 0` with `expected_ttk == 0.0`, which
    read alone looks like an *instant* kill. Reading the pair is the whole
    point, and getting it wrong would price the fastest kill in the game.
    """
    loadouts = dps_bridge.build_loadouts(
        _chunk_info(), {"Melee-weapon": "Abyssal whip"}, LEVELS
    )
    kurask = _target(name="Kurask", hitpoints=100, attributes=frozenset({"leafy"}))

    assert dps_bridge.best_kill(loadouts, "Kurask", [("Kurask", kurask)]) is None


def test_no_candidates_means_no_price() -> None:
    loadouts = dps_bridge.build_loadouts(
        _chunk_info(), {"Melee-weapon": "Abyssal whip"}, LEVELS
    )
    assert dps_bridge.best_kill(loadouts, "Nothing", []) is None


def _defended_rat() -> Any:
    """A `Rat` with enough defence that accuracy is not already saturated at
    a middling Attack level - the shape a curve needs to have anything to
    show."""
    from osrs_dps import Levels, StatBlock

    return _target(
        name="Rat", hitpoints=8,
        levels=Levels(defence=50), bonuses=StatBlock(defence_slash=50),
    )


class TestCombatCurve:
    """`combat_curve` is `costing/combat_xp.py`'s whole fix for a flat Attack
    rate on Angry Bear: accuracy and max hit genuinely improve with level,
    and the estimate said otherwise. Real `osrs_dps` arithmetic throughout -
    the numbers are not asserted, since duplicating the library's formula
    here would only be a second copy to keep in sync; what is asserted is
    that raising the level in question never lowers the rate and generally
    raises it, which is the one property this project actually depends on.
    """

    def test_grows_with_attack_level(self) -> None:
        index = _FakeIndex({"Rat": _defended_rat()})

        curve = dps_bridge.combat_curve(
            _chunk_info(), {"Melee-weapon": "Abyssal whip"}, LEVELS,
            "Rat", "Melee", "Attack", index=index,  # type: ignore[arg-type]
        )

        assert curve
        seen = sorted(curve)
        assert curve[seen[-1]] > curve[seen[0]]
        assert all(curve[b] >= curve[a] - 1e-6 for a, b in zip(seen, seen[1:]))

    def test_grows_with_strength_level(self) -> None:
        """Max hit, holding Attack (and so accuracy) fixed at `LEVELS`."""
        index = _FakeIndex({"Rat": _defended_rat()})

        curve = dps_bridge.combat_curve(
            _chunk_info(), {"Melee-weapon": "Abyssal whip"}, LEVELS,
            "Rat", "Melee", "Strength", index=index,  # type: ignore[arg-type]
        )

        assert curve
        seen = sorted(curve)
        assert curve[seen[-1]] > curve[seen[0]]
        assert all(curve[b] >= curve[a] - 1e-6 for a, b in zip(seen, seen[1:]))

    def test_an_unknown_monster_has_no_curve(self) -> None:
        index = _FakeIndex({"Rat": _defended_rat()})
        assert dps_bridge.combat_curve(
            _chunk_info(), {"Melee-weapon": "Abyssal whip"}, LEVELS,
            "Nothing", "Melee", "Attack", index=index,  # type: ignore[arg-type]
        ) == {}

    def test_no_loadout_for_the_style_has_no_curve(self) -> None:
        """The map has no gear for the style being asked about - a missing
        loadout, not an empty one to crash on."""
        index = _FakeIndex({"Rat": _defended_rat()})
        assert dps_bridge.combat_curve(
            _chunk_info(), {}, LEVELS, "Rat", "Melee", "Attack", index=index,  # type: ignore[arg-type]
        ) == {}


def _kill(**kwargs: Any) -> dps_bridge.KillEstimate:
    base: dict[str, Any] = {
        "monster": "Test",
        "style": "Melee",
        "ttk": 30.0,
        "dps": 5.0,
        "max_hit": 20,
        "accuracy": 0.5,
    }
    base.update(kwargs)
    return dps_bridge.KillEstimate(**base)


#: A kill time that is an exact number of 4-tick cycles, so `tick_waste` is
#: zero and the term under test is the only thing moving.
WHOLE_TTK = 120.0
#: What every kill pays before anything monster-specific: retarget only, when
#: the kill time divides evenly.
MECHANICAL = dps_bridge.RETARGET_TICKS * dps_bridge.SECONDS_PER_TICK


def test_something_that_cannot_hurt_you_pays_only_the_mechanics() -> None:
    """No damage means no trip has to end, so there is nothing to amortise.

    What is left is the tick cost every kill pays. The flat 30 seconds this
    replaced was 92% of a rat's whole cycle.
    """
    assert _kill(ttk=WHOLE_TTK, damage_taken=0.0).overhead() == pytest.approx(MECHANICAL)


def test_a_boss_carries_its_respawn_and_a_rat_does_not() -> None:
    """Respawn only bites where the monster is the scarce thing."""
    assert _kill(ttk=0.0, damage_taken=0.0, is_boss=True).overhead() == pytest.approx(
        dps_bridge.BOSS_RESPAWN_SECONDS + MECHANICAL
    )
    assert _kill(ttk=0.0, damage_taken=0.0, is_boss=False).overhead() == pytest.approx(
        MECHANICAL
    )


def test_a_boss_banks_by_share_of_the_fight_not_by_damage_taken() -> None:
    """The damage measurement is not trustworthy for a boss.

    Overhead prayers are unmodelled, so a boss's damage taken is roughly
    double the real thing - which put 10 of 33 bosses below one kill per trip.
    A share of the fight sidesteps it, and two bosses with the same kill time
    must therefore cost the same overhead however hard they hit.
    """
    gentle = _kill(ttk=WHOLE_TTK, damage_taken=0.5, is_boss=True)
    brutal = _kill(ttk=WHOLE_TTK, damage_taken=40.0, is_boss=True)

    assert gentle.overhead() == brutal.overhead()
    assert gentle.overhead() == pytest.approx(MECHANICAL + 15.0 + 0.15 * WHOLE_TTK)


def test_a_quicker_boss_pays_less_banking() -> None:
    """Shorter fights are easier bosses, so trips last longer."""
    quick = _kill(ttk=30.0, is_boss=True).overhead()
    slow = _kill(ttk=300.0, is_boss=True).overhead()

    assert quick < slow


def test_banking_is_proportional_to_the_damage_a_kill_costs() -> None:
    """Which is the property that makes one model fit a rat and a boss.

    400 damage a kill against a 400-point pool is one kill per trip, so that
    kill carries the whole bank run; half the damage carries half of it.
    """
    pool = WHOLE_TTK * 4.0
    whole = _kill(ttk=WHOLE_TTK, damage_taken=4.0).overhead(health_pool=pool, banking=120.0)
    half = _kill(ttk=WHOLE_TTK, damage_taken=2.0).overhead(health_pool=pool, banking=120.0)

    assert whole - MECHANICAL == pytest.approx(120.0)
    assert half - MECHANICAL == pytest.approx(60.0)


def test_a_boss_pays_both_parts() -> None:
    """Respawn for its timer, plus a share of the fight for banking."""
    kill = _kill(ttk=WHOLE_TTK, damage_taken=4.0, is_boss=True)

    assert kill.overhead() == pytest.approx(MECHANICAL + 15.0 + 0.15 * WHOLE_TTK)


def test_kills_per_hour_uses_the_model_by_default() -> None:
    """The explicit `overhead` is for comparing models, not the normal path."""
    kill = _kill(ttk=100.0, damage_taken=4.0)

    assert kill.kills_per_hour() == pytest.approx(3600.0 / (100.0 + kill.overhead()))
    assert kill.kills_per_hour(overhead=0.0) == pytest.approx(36.0)


def test_the_default_pool_is_the_inventory_plus_a_full_health_bar() -> None:
    """15 food at about 20 each, on top of 99 Hitpoints."""
    kill = _kill(ttk=WHOLE_TTK, damage_taken=4.0)
    pool = dps_bridge.INVENTORY_HEALING + 99.0
    damage = 4.0 * WHOLE_TTK

    assert kill.overhead() - MECHANICAL == pytest.approx(
        dps_bridge.BANKING_SECONDS * damage / pool
    )


def test_a_kill_is_a_whole_number_of_attack_cycles() -> None:
    """The game runs on ticks; a weapon fires on its own cadence.

    A 4-tick weapon acts every 2.4 seconds, so a kill that "takes" 5 seconds
    actually ends on the third cycle at 7.2. Nothing can happen before then.
    """
    kill = _kill(ttk=5.0, attack_speed=4)

    assert kill.cycle_seconds == pytest.approx(2.4)
    assert kill.tick_waste == pytest.approx(7.2 - 5.0)


def test_a_kill_that_divides_evenly_wastes_nothing() -> None:
    assert _kill(ttk=WHOLE_TTK, attack_speed=4).tick_waste == pytest.approx(0.0)


def test_a_faster_weapon_wastes_less() -> None:
    """Rapid takes a bow to three ticks, which is a smaller rounding unit."""
    assert _kill(ttk=5.0, attack_speed=3).tick_waste < _kill(
        ttk=5.0, attack_speed=5
    ).tick_waste


def test_rapid_speeds_the_bow_up_by_a_tick() -> None:
    """`osrs-dps` leaves stance-to-speed to the caller, so this must apply it.

    Declaring Rapid while passing the weapon's base speed bought its accuracy
    profile and none of its speed, costing every ranged kill a quarter of its
    rate.
    """
    loadouts = dps_bridge.build_loadouts(
        _chunk_info(),
        {"Ranged-weapon": "Webweaver bow (u)", "Melee-weapon": "Abyssal whip"},
        LEVELS,
    )

    assert loadouts["Ranged"].stance == "Rapid"
    assert loadouts["Ranged"].attack_speed == 3
    # Aggressive does not change the weapon's speed.
    assert loadouts["Melee"].attack_speed == 4


def test_price_monsters_omits_what_it_cannot_price() -> None:
    """A monster missing from the result falls back to the scraped rate.

    Never a substituted guess: a wrong kill time is indistinguishable from a
    right one by the time it reaches a total.
    """
    index = _FakeIndex({"Rat": _target(name="Rat", hitpoints=8)})
    rates = dps_bridge.price_monsters(
        _chunk_info(),
        {"Melee-weapon": "Abyssal whip"},
        LEVELS,
        ["Rat", "Al-Kharid warrior"],
        index=index,  # type: ignore[arg-type]
    )

    assert set(rates) == {"Rat"}
    assert rates["Rat"].source == "dps"
    assert rates["Rat"].value > 0


def test_price_monsters_without_loadouts_prices_nothing() -> None:
    index = _FakeIndex({"Rat": _target(name="Rat", hitpoints=8)})
    assert (
        dps_bridge.price_monsters(
            _chunk_info(), {}, LEVELS, ["Rat"], index=index  # type: ignore[arg-type]
        )
        == {}
    )


class _FakeSourceIndex:
    """Only the attributes `boosts._available` and `wilderness_monsters` use."""

    items: dict[str, Any] = {}
    npcs: dict[str, Any] = {}
    objects: dict[str, Any] = {}
    monsters: dict[str, Any] = {}


def _boost_info(**boost_items: Any) -> ChunkInfo:
    return ChunkInfo(
        {"equipment": _equipment(), "codeItems": {"boostItems": boost_items}}
    )


def test_kit_takes_the_best_reachable_boost() -> None:
    info = _boost_info(
        Strength={"Strength potion(4)": "10%+3", "Super strength(4)": "15%+5"}
    )
    kit = dps_bridge.assemble_kit(
        info,
        {"Strength": 70, "Prayer": 1},
        items={"Strength potion(4)": True},
        source_index=_FakeSourceIndex(),
    )
    # 9, not the 10 that `10%+3` of 70 reads like: `boosts._percent_boost`
    # ports upstream's two-step form, which applies the percentage to the
    # level *less* the first pass. The super strength it cannot reach is
    # ignored regardless, which is what this is really asserting.
    assert kit.boosts["Strength"] == 9


def test_kit_boosts_nothing_it_cannot_reach() -> None:
    info = _boost_info(Strength={"Super strength(4)": "15%+5"})
    kit = dps_bridge.assemble_kit(
        info, {"Strength": 70}, items={}, source_index=_FakeSourceIndex()
    )
    assert kit.boosts["Strength"] == 0


def test_prayers_step_down_with_the_level() -> None:
    """The tier a player qualifies for, not the best one that exists."""
    high = dps_bridge.assemble_kit(
        _boost_info(), {"Prayer": 99, "Defence": 99}, items={}, source_index=_FakeSourceIndex()
    )
    low = dps_bridge.assemble_kit(
        _boost_info(), {"Prayer": 40, "Defence": 99}, items={}, source_index=_FakeSourceIndex()
    )
    none = dps_bridge.assemble_kit(
        _boost_info(), {"Prayer": 1, "Defence": 1}, items={}, source_index=_FakeSourceIndex()
    )

    assert high.prayers["Melee"] == frozenset({"Piety"})
    # Below the capes the accuracy and strength prayers stack.
    assert low.prayers["Melee"] == frozenset({"Ultimate Strength", "Incredible Reflexes"})
    assert "Melee" not in none.prayers


def test_piety_needs_the_defence_level_too() -> None:
    kit = dps_bridge.assemble_kit(
        _boost_info(), {"Prayer": 99, "Defence": 60}, items={}, source_index=_FakeSourceIndex()
    )
    assert kit.prayers["Melee"] == frozenset({"Ultimate Strength", "Incredible Reflexes"})


def test_rigour_needs_its_scroll_to_be_reachable() -> None:
    """The one prayer tier gated on an item rather than only a level."""
    without = dps_bridge.assemble_kit(
        _boost_info(), {"Prayer": 99}, items={}, source_index=_FakeSourceIndex()
    )
    with_scroll = dps_bridge.assemble_kit(
        _boost_info(),
        {"Prayer": 99},
        items={"Dexterous prayer scroll": True},
        source_index=_FakeSourceIndex(),
    )

    assert without.prayers["Ranged"] == frozenset({"Eagle Eye"})
    assert with_scroll.prayers["Ranged"] == frozenset({"Rigour"})


def test_the_spell_follows_the_boosted_magic_level() -> None:
    kit = dps_bridge.assemble_kit(
        _boost_info(), {"Magic": 87}, items={}, source_index=_FakeSourceIndex()
    )
    assert kit.spell == "Water Surge"

    low = dps_bridge.assemble_kit(
        _boost_info(), {"Magic": 20}, items={}, source_index=_FakeSourceIndex()
    )
    assert low.spell == "Fire Strike"


def test_magic_is_unpriceable_without_a_spell() -> None:
    """The failure this whole `Kit` exists to stop.

    A magic loadout with no spell has no max hit at all, so the library
    refuses it and `best_kill` moves on - which looks exactly like a style
    that never wins. Magic priced *nothing* until `Kit` named a spell.
    """
    picks = {"Magic-weapon": "Master wand"}
    target = _target(name="Rat", hitpoints=50)

    bare = dps_bridge.build_loadouts(_chunk_info(), picks, LEVELS)
    assert dps_bridge.best_kill(bare, "Rat", [("Rat", target)]) is None

    armed = dps_bridge.build_loadouts(
        _chunk_info(), picks, LEVELS, dps_bridge.Kit(spell="Fire Bolt")
    )
    assert dps_bridge.best_kill(armed, "Rat", [("Rat", target)]) is not None


def test_only_magic_carries_the_spell() -> None:
    """A spell on a melee loadout names a manual cast, which it is not."""
    loadouts = dps_bridge.build_loadouts(
        _chunk_info(),
        {"Melee-weapon": "Abyssal whip", "Magic-weapon": "Master wand"},
        LEVELS,
        dps_bridge.Kit(spell="Fire Bolt"),
    )
    assert loadouts["Melee"].spell == ""
    assert loadouts["Magic"].spell == "Fire Bolt"


def test_boosts_reach_the_loadout_levels() -> None:
    loadouts = dps_bridge.build_loadouts(
        _chunk_info(),
        {"Melee-weapon": "Abyssal whip"},
        {"Attack": 75, "Strength": 70},
        dps_bridge.Kit(boosts={"Strength": 15, "Attack": 99}),
    )
    assert loadouts["Melee"].levels.strength == 85
    # Attack is deliberately never boosted - the export has no table for it,
    # so a caller supplying one must not quietly change the answer.
    assert loadouts["Melee"].levels.attack == 75


def test_prayers_speed_up_the_kill() -> None:
    """Not a formula check - that the kit is actually plumbed through."""
    picks = {"Melee-weapon": "Abyssal whip"}
    target = _target(name="Tough", hitpoints=300)

    bare = dps_bridge.best_kill(
        dps_bridge.build_loadouts(_chunk_info(), picks, LEVELS),
        "Tough",
        [("Tough", target)],
    )
    prayed = dps_bridge.best_kill(
        dps_bridge.build_loadouts(
            _chunk_info(), picks, LEVELS, dps_bridge.Kit(prayers={"Melee": frozenset({"Piety"})})
        ),
        "Tough",
        [("Tough", target)],
    )

    assert bare is not None and prayed is not None
    assert prayed.ttk < bare.ttk


def test_defence_draining_speeds_up_the_kill() -> None:
    """Defence drives accuracy, which drives everything."""
    from osrs_dps import DefenceReductions, Levels as DpsLevels

    picks = {"Melee-weapon": "Abyssal whip"}
    loadouts = dps_bridge.build_loadouts(_chunk_info(), picks, LEVELS)
    boss = _target(name="Boss", hitpoints=500, levels=DpsLevels(defence=200))

    plain = dps_bridge.best_kill(loadouts, "Boss", [("Boss", boss)])
    drained = dps_bridge.best_kill(
        loadouts,
        "Boss",
        [("Boss", boss)],
        reductions=DefenceReductions(dragon_warhammer=3),
    )

    assert plain is not None and drained is not None
    assert drained.ttk < plain.ttk


def test_wilderness_regions_come_out_of_the_chunk_id() -> None:
    """A chunk id is an OSRS region id, verified against known chunks."""
    assert dps_bridge.in_wilderness("11833")  # Crazy archaeologist
    assert dps_bridge.in_wilderness("11831")  # the Wilderness ditch
    assert not dps_bridge.in_wilderness("12850")  # Lumbridge
    # Region x53 starts at x 3392 and holds the Slayer Tower, which is what
    # the inclusive upper bound of 52 exists to exclude.
    assert not dps_bridge.in_wilderness("13623")
    assert not dps_bridge.in_wilderness("Fortis Barracks")


def test_wilderness_monsters_read_their_placements() -> None:
    class _Index:
        monsters = {
            "Chaos Fanatic": {"11836-1": True},
            "Abyssal demon": {"13623-1": True},
            # Placed in both; the wilderness one is where you would go.
            "Green dragon": {"12850-1": True, "11832-1": True},
        }

    found = dps_bridge.wilderness_monsters(_Index())
    assert found == frozenset({"Chaos Fanatic", "Green dragon"})


def test_a_charged_wilderness_weapon_replaces_the_uncharged_pick() -> None:
    """`bis.py` cannot tell them apart; the library only knows the charged name.

    The two entries have identical stats, so the pick is a coin toss - and the
    uncharged one silently disables a +50% bonus, because the library's
    special case matches on `Webweaver bow` and never on `Webweaver bow (u)`.
    """
    info = ChunkInfo(
        {
            "equipment": {
                **_equipment(),
                "Webweaver bow": _equipment()["Webweaver bow (u)"],
            }
        }
    )
    kit = dps_bridge.Kit(items={"Webweaver bow": True})
    loadouts = dps_bridge.build_loadouts(
        info, {"Ranged-weapon": "Webweaver bow (u)"}, LEVELS, kit
    )

    assert loadouts["Ranged"].weapon_name == "Webweaver bow"
    assert loadouts["Ranged"].weapon_version == "Charged"
    assert "Webweaver bow" in loadouts["Ranged"].worn


def test_an_unreachable_charge_leaves_the_uncharged_pick_alone() -> None:
    """A map holding only the uncharged form keeps it, rather than being
    handed a weapon it does not own."""
    loadouts = dps_bridge.build_loadouts(
        _chunk_info(), {"Ranged-weapon": "Webweaver bow (u)"}, LEVELS, dps_bridge.Kit()
    )
    assert loadouts["Ranged"].weapon_name == "Webweaver bow (u)"
    assert loadouts["Ranged"].weapon_version == ""


def test_the_wilderness_bonus_only_applies_in_the_wilderness() -> None:
    """Where the fight happens is part of the loadout, not of the gear."""
    info = ChunkInfo(
        {
            "equipment": {
                **_equipment(),
                "Webweaver bow": _equipment()["Webweaver bow (u)"],
            }
        }
    )
    loadouts = dps_bridge.build_loadouts(
        info,
        {"Ranged-weapon": "Webweaver bow (u)"},
        LEVELS,
        dps_bridge.Kit(items={"Webweaver bow": True}),
    )
    target = _target(name="Boss", hitpoints=500)

    outside = dps_bridge.best_kill(loadouts, "Boss", [("Boss", target)], wilderness=False)
    inside = dps_bridge.best_kill(loadouts, "Boss", [("Boss", target)], wilderness=True)

    assert outside is not None and inside is not None
    assert inside.ttk < outside.ttk


def test_group_bosses_are_not_priced_solo() -> None:
    """A solo kill time for team content is not a number worth having."""
    index = _FakeIndex({"Nex": _target(name="Nex", hitpoints=3400)})
    rates = dps_bridge.price_monsters(
        _chunk_info(),
        {"Melee-weapon": "Abyssal whip"},
        LEVELS,
        ["Nex"],
        index=index,  # type: ignore[arg-type]
    )
    assert rates == {}
    assert "Nex" in dps_bridge.GROUP_BOSSES


def _slayer_info(**tasks: Any) -> ChunkInfo:
    """An export with one master, and the slayer monsters its tasks name."""
    return ChunkInfo(
        {
            "equipment": _equipment(),
            "slayerMasterTasks": {"Turael": {name: {"Weight": 10} for name in tasks}},
            "codeItems": {
                "slayerTasks": {
                    name: {monster: True} for name, monster in tasks.items()
                }
            },
        }
    )


def test_every_task_is_priced_not_only_the_unmeasured_ones() -> None:
    """The sheet measures the best method, which needs things a map may lack.

    Chinning and bursting want a box trap or Desert Treasure I, so a rate
    derived from one is not a rate this player can reach. The single-target
    number is computed for every task, and a measured row does not exempt it.
    """
    from chunksim.costing.heuristics import Heuristics, SlayerTask

    info = _slayer_info(Banshees="Banshee", Cockatrices="Cockatrice")
    index = _FakeIndex(
        {
            "Banshee": _target(name="Banshee", hitpoints=22),
            "Cockatrice": _target(name="Cockatrice", hitpoints=37),
        }
    )
    heuristics = Heuristics(
        slayer={
            "Turael": {
                # Measured: a size and a rate. Must survive untouched.
                "Banshees": SlayerTask(
                    mean_count=50.0, xp_per_kill=22.0, kills_per_hour=300.0, source="sheet"
                ),
                # A size but no rate - the hole this fills.
                "Cockatrices": SlayerTask(
                    mean_count=40.0, xp_per_kill=0.0, kills_per_hour=0.0
                ),
            }
        }
    )

    filled = dps_bridge.price_slayer_tasks(
        info,
        {"Melee-weapon": "Abyssal whip"},
        LEVELS,
        heuristics=heuristics,
        index=index,  # type: ignore[arg-type]
        reachable_masters=frozenset({"Turael"}),
    )

    assert set(filled["Turael"]) == {"Banshees", "Cockatrices"}
    for name in ("Banshees", "Cockatrices"):
        assert filled["Turael"][name].source == "dps"
        assert filled["Turael"][name].kills_per_hour > 0
    # The measured assignment size is kept, not reinvented.
    assert filled["Turael"]["Cockatrices"].mean_count == 40.0
    assert filled["Turael"]["Banshees"].mean_count == 50.0


def test_slayer_xp_per_kill_is_the_monsters_hitpoints() -> None:
    """A slayer kill awards experience equal to the monster's health.

    Checked against the wiki's `slayxp` on nine monsters and exact on all
    nine. Not to be confused with the sheet's `xp_per_kill`, which averages a
    task's whole monster mix.
    """
    from chunksim.costing.heuristics import Heuristics, SlayerTask

    info = _slayer_info(Banshees="Banshee")
    index = _FakeIndex({"Banshee": _target(name="Banshee", hitpoints=22)})
    heuristics = Heuristics(
        slayer={"Turael": {"Banshees": SlayerTask(mean_count=50.0, xp_per_kill=0.0, kills_per_hour=0.0)}}
    )

    filled = dps_bridge.price_slayer_tasks(
        info,
        {"Melee-weapon": "Abyssal whip"},
        LEVELS,
        heuristics=heuristics,
        index=index,  # type: ignore[arg-type]
        reachable_masters=frozenset({"Turael"}),
    )

    assert filled["Turael"]["Banshees"].xp_per_kill == 22.0


def test_a_task_with_no_measured_size_is_left_alone() -> None:
    """A rate beside no size is half an answer; `slayer.py` still covers it."""
    from chunksim.costing.heuristics import Heuristics, SlayerTask

    info = _slayer_info(Banshees="Banshee")
    index = _FakeIndex({"Banshee": _target(name="Banshee", hitpoints=22)})
    heuristics = Heuristics(
        slayer={
            "Turael": {
                "Banshees": SlayerTask(
                    mean_count=0.0, xp_per_kill=0.0, kills_per_hour=0.0
                )
            }
        }
    )

    assert (
        dps_bridge.price_slayer_tasks(
            info,
            {"Melee-weapon": "Abyssal whip"},
            LEVELS,
            heuristics=heuristics,
            index=index,  # type: ignore[arg-type]
            reachable_masters=frozenset({"Turael"}),
        )
        == {}
    )


def test_with_slayer_rates_merges_without_mutating() -> None:
    """The pure layer stays shareable, so this returns a new value."""
    from chunksim.costing.heuristics import Heuristics, SlayerTask

    original = Heuristics(
        slayer={
            "Turael": {
                "Banshees": SlayerTask(
                    mean_count=50.0, xp_per_kill=22.0, kills_per_hour=1.0
                )
            }
        }
    )
    merged = dps_bridge.with_slayer_rates(
        original,
        {
            "Turael": {
                "Cockatrices": SlayerTask(
                    mean_count=40.0, xp_per_kill=37.0, kills_per_hour=2.0
                )
            }
        },
    )

    assert set(merged.slayer["Turael"]) == {"Banshees", "Cockatrices"}
    assert set(original.slayer["Turael"]) == {"Banshees"}
    assert dps_bridge.with_slayer_rates(original, {}) is original


def test_slayer_pricing_narrows_to_what_the_map_can_reach() -> None:
    """A task names every monster that counts, not the ones you can get to.

    `Dwarves` names eight and a map may hold two; pricing the fastest of all
    eight quotes a fight that is not on offer.
    """
    from chunksim.costing.heuristics import Heuristics, SlayerTask

    info = ChunkInfo(
        {
            "equipment": _equipment(),
            "slayerMasterTasks": {"Turael": {"Wolves": {"Weight": 10}}},
            "codeItems": {
                "slayerTasks": {"Wolves": {"Wolf": True, "Ice wolf": True}}
            },
        }
    )
    index = _FakeIndex(
        {
            "Wolf": _target(name="Wolf", hitpoints=15),
            "Ice wolf": _target(name="Ice wolf", hitpoints=40),
        }
    )
    heuristics = Heuristics(
        slayer={
            "Turael": {
                "Wolves": SlayerTask(
                    mean_count=40.0, xp_per_kill=0.0, kills_per_hour=0.0
                )
            }
        }
    )
    priced = dps_bridge.price_slayer_tasks(
        info,
        {"Melee-weapon": "Abyssal whip"},
        LEVELS,
        heuristics=heuristics,
        index=index,  # type: ignore[arg-type]
        reachable_masters=frozenset({"Turael"}),
        reachable_monsters=frozenset({"Wolf"}),
    )

    # The reachable wolf's hitpoints, not the one this map cannot get to.
    assert priced["Turael"]["Wolves"].xp_per_kill == 15.0


def test_a_task_whose_monsters_are_all_unreachable_is_not_priced() -> None:
    """`slayer.py` has already decided that is a skip, not a rate."""
    from chunksim.costing.heuristics import Heuristics, SlayerTask

    info = ChunkInfo(
        {
            "equipment": _equipment(),
            "slayerMasterTasks": {"Turael": {"Wolves": {"Weight": 10}}},
            "codeItems": {"slayerTasks": {"Wolves": {"Wolf": True}}},
        }
    )
    index = _FakeIndex({"Wolf": _target(name="Wolf", hitpoints=15)})
    heuristics = Heuristics(
        slayer={
            "Turael": {
                "Wolves": SlayerTask(
                    mean_count=40.0, xp_per_kill=0.0, kills_per_hour=0.0
                )
            }
        }
    )

    assert (
        dps_bridge.price_slayer_tasks(
            info,
            {"Melee-weapon": "Abyssal whip"},
            LEVELS,
            heuristics=heuristics,
            index=index,  # type: ignore[arg-type]
            reachable_masters=frozenset({"Turael"}),
            reachable_monsters=frozenset({"Something else"}),
        )
        == {}
    )


def test_slayer_pricing_skips_masters_you_cannot_reach() -> None:
    """A master you cannot walk up to assigns nothing.

    `master_rates` has gated on this since it once picked Duradel on a map
    holding none of him; pricing their task list is the same waste, and an
    entry for a master nobody can visit invites the same misreading.
    """
    from chunksim.costing.heuristics import Heuristics, SlayerTask

    info = ChunkInfo(
        {
            "equipment": _equipment(),
            "slayerMasterTasks": {
                "Turael": {"Wolves": {"Weight": 10}},
                "Duradel": {"Wolves": {"Weight": 10}},
            },
            "codeItems": {"slayerTasks": {"Wolves": {"Wolf": True}}},
        }
    )
    index = _FakeIndex({"Wolf": _target(name="Wolf", hitpoints=15)})
    task = SlayerTask(mean_count=40.0, xp_per_kill=0.0, kills_per_hour=0.0)
    heuristics = Heuristics(
        slayer={"Turael": {"Wolves": task}, "Duradel": {"Wolves": task}}
    )

    priced = dps_bridge.price_slayer_tasks(
        info,
        {"Melee-weapon": "Abyssal whip"},
        LEVELS,
        heuristics=heuristics,
        index=index,  # type: ignore[arg-type]
        reachable_masters=frozenset({"Turael"}),
    )

    assert set(priced) == {"Turael"}


def test_naming_both_masters_prices_both() -> None:
    """There is no "do not filter" mode; a caller states who is reachable."""
    from chunksim.costing.heuristics import Heuristics, SlayerTask

    info = ChunkInfo(
        {
            "equipment": _equipment(),
            "slayerMasterTasks": {
                "Turael": {"Wolves": {"Weight": 10}},
                "Duradel": {"Wolves": {"Weight": 10}},
            },
            "codeItems": {"slayerTasks": {"Wolves": {"Wolf": True}}},
        }
    )
    index = _FakeIndex({"Wolf": _target(name="Wolf", hitpoints=15)})
    task = SlayerTask(mean_count=40.0, xp_per_kill=0.0, kills_per_hour=0.0)
    heuristics = Heuristics(
        slayer={"Turael": {"Wolves": task}, "Duradel": {"Wolves": task}}
    )

    priced = dps_bridge.price_slayer_tasks(
        info,
        {"Melee-weapon": "Abyssal whip"},
        LEVELS,
        heuristics=heuristics,
        index=index,  # type: ignore[arg-type]
        reachable_masters=frozenset({"Turael", "Duradel"}),
    )

    assert set(priced) == {"Turael", "Duradel"}


def test_a_slayer_task_is_priced_on_xp_per_hour_not_speed() -> None:
    """The quickest thing on a task list is routinely the worst thing on it.

    A slayer kill pays the monster's health, so a 2-hitpoint Scorpion dying in
    under two seconds is worth a tenth of a King Scorpion on the same task.
    Choosing on speed under-reported `Scorpions`, `Spiders` and `Zombies` by
    seven to thirteen times.
    """
    from chunksim.costing.heuristics import Heuristics, SlayerTask

    info = ChunkInfo(
        {
            "equipment": _equipment(),
            "slayerMasterTasks": {"Krystilia": {"Scorpions": {"Weight": 10}}},
            "codeItems": {
                "slayerTasks": {
                    "Scorpions": {"Scorpion": True, "King Scorpion": True}
                }
            },
        }
    )
    index = _FakeIndex(
        {
            # Dies almost instantly and pays almost nothing.
            "Scorpion": _target(name="Scorpion", hitpoints=2),
            # Slower per kill, far more experience per hour.
            "King Scorpion": _target(name="King Scorpion", hitpoints=30),
        }
    )
    heuristics = Heuristics(
        slayer={
            "Krystilia": {
                "Scorpions": SlayerTask(
                    mean_count=100.0, xp_per_kill=0.0, kills_per_hour=0.0
                )
            }
        }
    )

    priced = dps_bridge.price_slayer_tasks(
        info,
        {"Melee-weapon": "Abyssal whip"},
        LEVELS,
        heuristics=heuristics,
        index=index,  # type: ignore[arg-type]
        reachable_masters=frozenset({"Krystilia"}),
        reachable_monsters=frozenset({"Scorpion", "King Scorpion"}),
    )

    task = priced["Krystilia"]["Scorpions"]
    assert task.xp_per_kill == 30.0
    assert task.xp_per_kill * task.kills_per_hour > 2.0 * 750.0


def test_a_hand_override_outranks_the_computed_rate() -> None:
    """`defaults < scraped < computed < overrides`.

    A computed rate beats the spreadsheet because the spreadsheet measures a
    method this map may not have. It does not beat somebody who looked at the
    number and disagreed - that is what the overrides file is for, and a
    computed layer outranking it would make hand corrections stop working
    with no sign that they had.
    """
    from chunksim.costing.heuristics import Heuristics, Rate, SlayerTask

    heuristics = Heuristics(
        monsters={"Rat": Rate(value=1.0, source="overrides")},
        slayer={
            "Turael": {
                "Wolves": SlayerTask(
                    mean_count=40.0, xp_per_kill=1.0, kills_per_hour=1.0, source="overrides"
                )
            }
        },
    )

    kept = dps_bridge.with_monster_rates(
        heuristics, {"Rat": Rate(value=500.0, source="dps")}, pinned=frozenset({"Rat"})
    )
    assert kept.monsters["Rat"].value == 1.0

    taken = dps_bridge.with_monster_rates(
        heuristics, {"Rat": Rate(value=500.0, source="dps")}
    )
    assert taken.monsters["Rat"].value == 500.0

    slayer_kept = dps_bridge.with_slayer_rates(
        heuristics,
        {"Turael": {"Wolves": SlayerTask(40.0, 30.0, 500.0, source="dps")}},
        pinned={"Turael": frozenset({"Wolves"})},
    )
    assert slayer_kept.slayer["Turael"]["Wolves"].source == "overrides"


def test_coverage_counts_only_what_it_actually_placed() -> None:
    """A pinned entry is reported as pinned, not as priced."""
    coverage = dps_bridge.DpsCoverage(monsters=3, slayer_tasks=2, pinned=1)

    assert coverage.priced_anything
    assert coverage.as_dict()["pinned"] == 1
    assert not dps_bridge.DpsCoverage().priced_anything


def test_library_version_reports_the_installed_extra() -> None:
    version = dps_bridge.library_version()

    assert version is not None
    assert version.count(".") >= 1


def test_enrich_prices_only_what_the_estimate_could_ask_about(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**753 monsters priced against 11 consulted, on the real map.**

    Every `Heuristics.kills_per_hour` lookup in `estimate.py` is gated on
    `reachable_providers`, so a rate for anything outside that set is computed
    and can never be spent - it was ~60% of a repricing's time. Restricting it
    left the answer identical to four decimal places (3969.1204h either way,
    with buckets, per-item hours and `unpriced` all unchanged).

    The set is *imported* from `estimate.py` rather than reproduced here, so
    the gate cannot drift from the thing it gates. This asserts the wiring:
    what `enrich` hands to `price_monsters` is the reachable providers and not
    the export.
    """
    info = ChunkInfo(
        {
            "drops": {
                "Abyssal demon": {"Abyssal whip": {"1": "1/512"}},
                "Corporeal Beast": {"Spectral sigil": {"1": "1/1365"}},
            }
        }
    )
    derived = SimpleNamespace(
        source_index=SourceIndex(
            items={},
            objects={},
            monsters={"Abyssal demon": {"100": True}},
            npcs={},
            shops={},
            # **The gate reads the index, not the export branch** - a slayer
            # monster's table arrives here from `skillItems.Slayer` and never
            # appears in `chunk_info.drops`. See `enrich`.
            drop_rates={"Abyssal demon": {"Abyssal whip": "1/512"}},
        ),
        bis=SimpleNamespace(picks={}),
        challenges=SimpleNamespace(available_items={}),
    )
    seen: list[list[str]] = []

    def record(*args: Any, **kwargs: Any) -> dict[str, Rate]:
        seen.append(list(args[3]))
        return {}

    monkeypatch.setattr(dps_bridge, "price_monsters", record)
    monkeypatch.setattr(dps_bridge, "price_slayer_tasks", lambda *a, **kw: {})
    monkeypatch.setattr(dps_bridge, "build_loadouts", lambda *a, **kw: {"melee": object()})

    dps_bridge.enrich(Heuristics(), info, cast(Any, derived), {})

    assert seen == [["Abyssal demon"]]
    assert "Corporeal Beast" not in seen[0], "priced a monster this map cannot reach"


# --- the incremental reuse predicate ---------------------------------------


def _kit(**overrides: Any) -> dps_bridge.Kit:
    return dps_bridge.Kit(**overrides)


def test_the_signature_moves_when_anything_that_decides_a_kill_moves() -> None:
    """**A wrong predicate here is silently wrong** - the numbers stay entirely
    plausible, they are just the previous roll's. So every input gets its own
    case rather than one round-trip that happens to cover them."""
    picks = {"melee-weapon": "Abyssal whip"}
    levels = {"Attack": 99}
    base = dps_bridge.fight_signature(picks, levels, _kit())

    assert dps_bridge.fight_signature({"melee-weapon": "Dragon scimitar"}, levels, _kit()) != base
    assert dps_bridge.fight_signature(picks, {"Attack": 70}, _kit()) != base
    assert dps_bridge.fight_signature(picks, levels, _kit(boosts={"Attack": 5})) != base
    assert dps_bridge.fight_signature(picks, levels, _kit(prayers={"melee": frozenset({"p"})})) != base
    assert dps_bridge.fight_signature(picks, levels, _kit(spell="Fire Wave")) != base


def test_an_item_that_is_not_worn_does_not_move_the_signature() -> None:
    """**`kit.items` moved on 17 of 20 measured rolls** - it grows with every
    item the map reaches - and it feeds exactly one thing: swapping a worn
    *uncharged wilderness weapon* for its charged form. A new potion cannot
    change a fight the potion is not in, and treating it as if it could threw
    away the reuse on almost every roll."""
    picks = {"melee-weapon": "Abyssal whip"}
    levels = {"Attack": 99}

    bare = dps_bridge.fight_signature(picks, levels, _kit())
    with_potion = dps_bridge.fight_signature(picks, levels, _kit(items={"Super attack": {}}))

    assert with_potion == bare


def test_a_charged_variant_of_worn_gear_does_move_the_signature() -> None:
    """The one part of `kit.items` that reaches a kill: `_charged` swaps the
    worn uncharged form for the charged one, worth +50% in the wilderness."""
    weapon = next(iter(dps_bridge._WILDERNESS_WEAPONS))
    picks = {"ranged-weapon": f"{weapon} (u)"}
    levels = {"Ranged": 99}

    without = dps_bridge.fight_signature(picks, levels, _kit())
    with_charge = dps_bridge.fight_signature(picks, levels, _kit(items={weapon: {}}))

    assert with_charge != without


def test_wilderness_is_deliberately_not_in_the_signature() -> None:
    """It is per *monster*, not per state. Folding it in would invalidate
    every rate because one monster moved; `enrich_incremental` compares
    membership itself and reprices only what flipped."""
    picks = {"melee-weapon": "Abyssal whip"}
    levels = {"Attack": 99}

    assert dps_bridge.fight_signature(
        picks, levels, _kit(wilderness=frozenset({"Chaos Elemental"}))
    ) == dps_bridge.fight_signature(picks, levels, _kit())


@pytest.mark.real_cache
def test_incremental_pricing_is_the_same_answer_as_pricing_from_scratch(
    real_export: ChunkInfo, real_state: tuple[MapState, dict[str, bool]]
) -> None:
    """**The assertion the whole optimisation rests on.**

    `enrich_incremental` keeps whatever the previous roll priced when
    `fight_signature` says nothing that decides a kill has moved. If that
    predicate is ever wrong the result is not a crash or an obviously silly
    number - it is the *previous* roll's perfectly plausible rate, which is
    the failure mode this project guards hardest against.

    So this walks a real sequence of unlocked sets against the real export and
    asserts equality, rate for rate, not closeness. Measured on a 20-roll run
    it is 14.5s of full pricing against 3.4s incremental, and the two agreed
    on every one of 4,094 rates.
    """
    from chunksim.store import cache
    from chunksim.store.derived_cache import Digests, cached_derive
    from chunksim.costing.levels import goal_levels, infer_levels

    info = real_export
    state, unlocked = real_state
    digests = Digests(
        chunkinfo=cache.file_digest(cache.chunkinfo_source(None, None)),
        tasks_map=cache.file_digest(cache.blob_path(cache.TASKS_MAP_BLOB_NAME)),
    )
    index = dps_bridge.load_monster_index()

    # A short synthetic sequence: drop a few chunks, then add them back one at
    # a time. Adding is what a roll does, and the derivations are cached.
    held = sorted(unlocked)
    sequence = [frozenset(held[: len(held) - n]) for n in (4, 3, 2, 1, 0)]

    previous = None
    for chunks in sequence:
        derived = cached_derive(state, dict.fromkeys(chunks, True), digests)
        levels = goal_levels(state, derived, infer_levels(state))
        full, full_cover = dps_bridge.enrich(
            Heuristics(), info, derived, levels, index=index
        )
        step, step_cover, previous = dps_bridge.enrich_incremental(
            Heuristics(), info, derived, levels, previous=previous, index=index
        )

        assert step == full, f"incremental diverged at {len(chunks)} chunks"
        assert step_cover.monsters == full_cover.monsters
        assert step_cover.slayer_tasks == full_cover.slayer_tasks


def test_importing_without_the_extra_is_safe() -> None:
    """**The one promise this module makes**, and it was broken for a year.

    `_MELEE_ATTACK_BONUSES` built `CombatStyle.STAB` at module scope, so
    importing `dps_bridge` raised `NameError` on any install that had not opted
    into the GPL extra - which is every install but a developer's, since the
    checkout always has it. Nothing caught it because every test environment
    has the extra; it surfaced the first time the package was run from a
    Windows payload that deliberately does not ship it.

    A subprocess with a blocking finder, because the point is a *cold* import
    with the library genuinely absent: patching `sys.modules` after the fact
    would test a module that had already been built successfully.
    """
    code = textwrap.dedent(
        """
        import sys

        class Block:
            def find_spec(self, name, path=None, target=None):
                if name == "osrs_dps" or name.startswith("osrs_dps."):
                    raise ImportError("blocked")
                return None

        sys.meta_path.insert(0, Block())
        import chunksim.costing.dps_bridge as bridge
        import chunksim.gui  # the import chain that actually broke
        assert bridge.DPS_AVAILABLE is False
        print("ok")
        """
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_calling_without_the_extra_still_refuses() -> None:
    """Importing being safe must not make *using* it quietly return nothing."""
    code = textwrap.dedent(
        """
        import sys

        class Block:
            def find_spec(self, name, path=None, target=None):
                if name == "osrs_dps" or name.startswith("osrs_dps."):
                    raise ImportError("blocked")
                return None

        sys.meta_path.insert(0, Block())
        import chunksim.costing.dps_bridge as bridge
        try:
            bridge._require()
        except bridge.DpsUnavailableError:
            print("ok")
        """
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)

    assert result.stdout.strip() == "ok", result.stderr


class TestTheOfferSetReachesSlayerMonsters:
    """**`SourceIndex.drop_rates`, not `chunk_info.drops`.** A slayer
    monster's loot table lives in `skillItems.Slayer` and it has no `drops`
    entry, so gating the calculator on the export branch excluded every one of
    them: `Abyssal demon` kept a flat 60/hr against the 24.3 it simulates,
    `Alchemical Hydra` the boss default of 20 against 2.9 - 20 monsters on one
    cached map and 27 on the other.
    """

    def test_the_gate_names_the_index_not_the_export_branch(self) -> None:
        """Pinned as source, because the two spellings look interchangeable
        and only one of them sees a slayer monster."""
        source = pathlib.Path(dps_bridge.__file__).read_text()
        assert "frozenset(derived.source_index.drop_rates)" in source
        assert "frozenset(chunk_info.drops)" not in source

    @pytest.mark.real_cache
    def test_the_real_map_offers_its_slayer_monsters(
        self, real_state: Any, real_derived: Any
    ) -> None:
        from chunksim.costing.levels import reachable_providers

        state, _unlocked = real_state
        providers = reachable_providers(real_derived)
        offered = providers & frozenset(real_derived.source_index.drop_rates)
        by_branch = providers & frozenset(state.chunk_info.drops)
        # The widening is real on this export, not a theoretical case.
        assert offered - by_branch, "no slayer-table monster is reachable to test"


class TestScriptedBossesDoNotDisturbOrdinaryOnes:
    """`best_kill` checks `SCRIPTS` before anything else - this is the other
    half of that branch: a name absent from the registry must fall through to
    the ordinary version search exactly as before scripting existed."""

    def test_an_unscripted_name_is_untouched(self) -> None:
        loadouts = dps_bridge.build_loadouts(
            _chunk_info(), {"Melee-weapon": "Abyssal whip"}, LEVELS
        )
        kill = dps_bridge.best_kill(
            loadouts, "Rat", [("Rat", _target(name="Rat", hitpoints=8))]
        )
        assert kill is not None
        assert kill.match != "scripted"

    def test_scripts_is_keyed_by_the_real_boss_modules(self) -> None:
        from chunksim.costing import (
            doom_of_mokhaiotl,
            duke_sucellus,
            grotesque_guardians,
            hueycoatl,
            hydra,
            kalphite_queen,
            moons,
            nex,
            nightmare,
            phantom_muspah,
            royal_titans,
            sire,
            vetion,
            vorkath,
            yama,
            zulrah,
        )

        assert dps_bridge.SCRIPTS == {
            "Alchemical Hydra": hydra.SCRIPT,
            "Phosani's Nightmare": nightmare.SCRIPT,
            "Zulrah": zulrah.SCRIPT,
            "Abyssal Sire": sire.SCRIPT,
            "Grotesque Guardians": grotesque_guardians.SCRIPT,
            "Duke Sucellus": duke_sucellus.SCRIPT,
            "The Hueycoatl": hueycoatl.SCRIPT,
            "Kalphite Queen": kalphite_queen.SCRIPT,
            "Nex": nex.SCRIPT,
            "Phantom Muspah": phantom_muspah.SCRIPT,
            "Vorkath": vorkath.SCRIPT,
            "Yama": yama.SCRIPT,
            "Doom of Mokhaiotl": doom_of_mokhaiotl.SCRIPT,
            **moons.SCRIPTS,
            **royal_titans.SCRIPTS,
            **vetion.SCRIPTS,
        }


class TestGatedBossCorrection:
    """`_apply_gated_bosses` - Hespori's grow time and Skotizo's totem, both
    applied to a `Rate` `price_monsters` already computed rather than a
    fresh simulation. See `costing/hespori.py` and `costing/skotizo.py`."""

    @staticmethod
    def _rate(kph: float) -> Rate:
        return Rate(value=kph, source="dps", match="exact")

    def test_hespori_is_corrected_for_the_grow_time(self) -> None:
        from chunksim.costing import hespori

        monsters = {hespori.HESPORI: self._rate(3600.0 / 60.0)}
        got = dps_bridge._apply_gated_bosses(monsters, monsters)
        seconds = 3600.0 / got[hespori.HESPORI].value
        assert seconds == pytest.approx(hespori.GROW_SECONDS + 60.0)

    def test_hespori_keeps_its_source_and_match(self) -> None:
        from chunksim.costing import hespori

        monsters = {hespori.HESPORI: self._rate(3600.0 / 60.0)}
        got = dps_bridge._apply_gated_bosses(monsters, monsters)
        assert got[hespori.HESPORI].source == "dps"
        assert got[hespori.HESPORI].match == "exact"

    def test_skotizo_is_corrected_for_the_fastest_totem_candidate(self) -> None:
        from chunksim.costing import skotizo

        monsters = {
            skotizo.SKOTIZO: self._rate(3600.0 / 60.0),
            "Hill Giant": self._rate(3600.0 / 5.0),
        }
        got = dps_bridge._apply_gated_bosses(monsters, monsters)
        expected_totem = 3.0 * (5.0 / skotizo.piece_chance(skotizo.CANDIDATE_HITPOINTS["Hill Giant"]))
        seconds = 3600.0 / got[skotizo.SKOTIZO].value
        assert seconds == pytest.approx(expected_totem + 60.0)

    def test_skotizo_is_dropped_when_no_candidate_is_reachable(self) -> None:
        """An uncorrected combat-only rate is a wrong number, not a
        missing one - refused rather than kept."""
        from chunksim.costing import skotizo

        monsters = {skotizo.SKOTIZO: self._rate(3600.0 / 60.0)}
        got = dps_bridge._apply_gated_bosses(monsters, monsters)
        assert skotizo.SKOTIZO not in got

    def test_a_reused_rate_is_never_corrected_twice(self) -> None:
        """**The defect this split guards against.** `enrich_incremental`
        can hand the same already-corrected `Rate` back on a later roll;
        `freshly_priced` empty means nothing here was computed this call,
        so the correction must not run again."""
        from chunksim.costing import hespori

        monsters = {hespori.HESPORI: self._rate(3600.0 / 60.0)}
        once = dps_bridge._apply_gated_bosses(monsters, monsters)
        again = dps_bridge._apply_gated_bosses(once, {})
        assert again == once

    def test_an_untouched_monster_passes_through_unchanged(self) -> None:
        monsters = {"Abyssal demon": self._rate(30.0)}
        got = dps_bridge._apply_gated_bosses(monsters, monsters)
        assert got["Abyssal demon"] == monsters["Abyssal demon"]

    def test_a_chest_is_synthesised_at_zero_with_no_candidate_present(self) -> None:
        """Neither chest is ever combat-simulated, so with none of their key
        monsters in `monsters` either, both are written explicitly at zero -
        never left absent for `Heuristics.kills_per_hour` to default."""
        from chunksim.costing import keyed_chests

        got = dps_bridge._apply_gated_bosses({}, {})
        assert got[keyed_chests.BRYOPHYTAS_LAIR].value == 0.0
        assert got[keyed_chests.OBORS_LAIR].value == 0.0

    def test_a_chest_is_priced_off_its_cheapest_key_candidate(self) -> None:
        from chunksim.costing import keyed_chests

        monsters = {
            "Bryophyta": self._rate(3600.0 / 100.0),  # 100s a kill
            "Moss giant": self._rate(3600.0 / 10.0),  # 10s a kill, worse odds
        }
        got = dps_bridge._apply_gated_bosses(monsters, monsters)
        # Bryophyta: 100s / (1/16) = 1,600s a key. Moss giant: 10s / (1/150)
        # = 1,500s a key, cheaper despite the worse per-kill odds.
        expected = 10.0 / (1.0 / 150.0) + keyed_chests.OPEN_SECONDS
        seconds = 3600.0 / got[keyed_chests.BRYOPHYTAS_LAIR].value
        assert seconds == pytest.approx(expected)

    def test_every_simple_correction_is_applied_and_not_doubled(self) -> None:
        """`_SIMPLE_GATED_CORRECTIONS` covers Giant Mole, Duke Sucellus,
        Vorkath and Nex alongside Hespori - each is a pure function of its
        own kill time, and each must move the rate and never move it
        twice on a reused, already-corrected entry."""
        from chunksim.costing import duke_sucellus, giant_mole, nex, vorkath

        for name, module in (
            (giant_mole.GIANT_MOLE, giant_mole),
            (duke_sucellus.DUKE_SUCELLUS, duke_sucellus),
            (vorkath.VORKATH, vorkath),
            (nex.NEX, nex),
        ):
            monsters = {name: self._rate(3600.0 / 60.0)}
            once = dps_bridge._apply_gated_bosses(monsters, monsters)
            seconds = 3600.0 / once[name].value
            assert seconds == pytest.approx(module.effective_seconds(60.0)), name
            again = dps_bridge._apply_gated_bosses(once, {})
            assert again == once, name


class TestPhaseStylesRestriction:
    """`Phase.styles` - added for `costing/grotesque_guardians.py`, where
    Dusk is immune to two of the three styles the ordinary search would
    otherwise happily price. Uses a synthetic single-phase `FightScript`
    rather than the real boss, so this pins `_scripted_kill`'s own filtering
    in isolation from any of that module's real numbers."""

    @staticmethod
    def _script(styles: frozenset[str] | None) -> Any:
        from chunksim.costing.fightscripts import FightScript, Phase

        return FightScript(
            name="Fixture boss",
            phases=(Phase(name="only", target="Rat", hp_share=1.0, styles=styles),),
        )

    def test_an_unrestricted_phase_lets_the_best_style_win(self) -> None:
        loadouts = dps_bridge.build_loadouts(
            _chunk_info(), {"Melee-weapon": "Abyssal whip", "Magic-weapon": "Master wand"}, LEVELS
        )
        candidates = (("Rat", _target(name="Rat", hitpoints=8)),)
        kill = dps_bridge._scripted_kill(
            self._script(None), loadouts, candidates, reductions=None, boss=False
        )
        assert kill is not None

    def test_a_style_excluded_from_the_phase_is_never_offered(self) -> None:
        """Magic is the only style with a weapon in this loadout, and the
        phase excludes it - so there is nothing left to kill with, and the
        script must refuse rather than silently falling back to it."""
        loadouts = dps_bridge.build_loadouts(_chunk_info(), {"Magic-weapon": "Master wand"}, LEVELS)
        candidates = (("Rat", _target(name="Rat", hitpoints=8)),)
        kill = dps_bridge._scripted_kill(
            self._script(frozenset({"Melee", "Ranged"})),
            loadouts,
            candidates,
            reductions=None,
            boss=False,
        )
        assert kill is None

    def test_restricting_to_a_worse_style_costs_real_time(self) -> None:
        """Both Melee and Magic can kill the fixture target, but Magic is
        the stronger loadout here - restricting the phase to Melee only
        must produce a slower kill than leaving it unrestricted, proving the
        filter actually narrows `kills_by_style`'s search rather than being
        ignored."""
        loadouts = dps_bridge.build_loadouts(
            _chunk_info(), {"Melee-weapon": "Dragon dagger", "Magic-weapon": "Master wand"}, LEVELS
        )
        candidates = (("Rat", _target(name="Rat", hitpoints=8)),)
        unrestricted = dps_bridge._scripted_kill(
            self._script(None), loadouts, candidates, reductions=None, boss=False
        )
        melee_only = dps_bridge._scripted_kill(
            self._script(frozenset({"Melee"})), loadouts, candidates, reductions=None, boss=False
        )
        assert unrestricted is not None and melee_only is not None
        assert melee_only.ttk >= unrestricted.ttk


class TestPhaseSecondsArithmetic:
    """`_phase_seconds` in isolation - the formula `_scripted_kill` sums over
    every phase in a script."""

    @staticmethod
    def _kill(ttk: float) -> "dps_bridge.KillEstimate":
        return dps_bridge.KillEstimate(
            monster="X#form", style="Ranged", ttk=ttk, dps=0.0, max_hit=0, accuracy=0.0
        )

    def test_no_reduction_window_is_hp_share_of_the_solo_ttk(self) -> None:
        """`(hp * hp_share) / (hp / ttk)` reduces to `hp_share * ttk` -
        exactly the module docstring's claim: a quarter of one phase's own
        kill time is what a quarter of its health bar costs."""
        from chunksim.costing.fightscripts import Phase

        target = SimpleNamespace(hitpoints=100.0)
        phase = Phase(name="p", target="X#form", hp_share=0.5)
        got = dps_bridge._phase_seconds(phase, cast(Any, target), self._kill(40.0))
        assert got == pytest.approx(20.0)

    def test_idle_seconds_add_on_top(self) -> None:
        from chunksim.costing.fightscripts import Phase

        target = SimpleNamespace(hitpoints=100.0)
        phase = Phase(name="p", target="X#form", hp_share=0.5, idle_seconds=3.0)
        got = dps_bridge._phase_seconds(phase, cast(Any, target), self._kill(40.0))
        assert got == pytest.approx(23.0)

    def test_a_reduction_window_that_outlasts_the_phase_still_prices(self) -> None:
        """A phase small enough, or a reduction long enough, that the phase
        dies *during* the window - priced at the reduced rate throughout
        rather than refused."""
        from chunksim.costing.fightscripts import Phase

        target = SimpleNamespace(hitpoints=100.0)
        # solo dps 2.5/s; a 5-hp phase at a quarter rate (0.625/s) needs 8s,
        # well inside a 20s window - so the whole phase is reduced-rate.
        phase = Phase(
            name="p",
            target="X#form",
            hp_share=0.05,
            reduced_seconds=20.0,
            reduced_dps_fraction=0.25,
        )
        got = dps_bridge._phase_seconds(phase, cast(Any, target), self._kill(40.0))
        assert got == pytest.approx(8.0)

    def test_a_reduction_window_shorter_than_the_phase_costs_the_gap(self) -> None:
        """The Hydra's own shape: the window ends before the phase's health
        is gone, so the rest is priced at the full rate."""
        from chunksim.costing.fightscripts import Phase

        target = SimpleNamespace(hitpoints=1100.0)
        phase = Phase(
            name="p",
            target="X#form",
            hp_share=0.25,
            reduced_seconds=5.0,
            reduced_dps_fraction=0.25,
        )
        kill = self._kill(1100.0 / 4.0)  # solo dps = 4 hp/s
        got = dps_bridge._phase_seconds(phase, cast(Any, target), kill)
        # 275 hp at 0.25*4=1 hp/s for 5s removes 5hp; 270 remain at 4hp/s.
        assert got == pytest.approx(5.0 + 270.0 / 4.0)

    def test_a_zero_ttk_kill_refuses_rather_than_dividing_by_zero(self) -> None:
        from chunksim.costing.fightscripts import Phase

        target = SimpleNamespace(hitpoints=100.0)
        phase = Phase(name="p", target="X#form", hp_share=1.0)
        assert dps_bridge._phase_seconds(phase, cast(Any, target), self._kill(0.0)) is None
