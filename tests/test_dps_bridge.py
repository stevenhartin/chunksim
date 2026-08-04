"""Tests for the DPS bridge.

Every test here is gated on `osrs-dps` being installed, since it is an
optional extra - a fresh clone without it must *skip*, not fail. Fixtures are
built by hand; nothing reads the real export or the real cache.
"""

from __future__ import annotations

from typing import Any

import pytest

from fray_claude import dps_bridge
from fray_claude.chunkinfo import ChunkInfo
from fray_claude.heuristics import Rate

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


def test_kills_per_hour_adds_the_overhead() -> None:
    """Fighting time is not a kill cycle; the difference is the overhead."""
    kill = dps_bridge.KillEstimate(
        monster="Rat", style="Melee", ttk=30.0, dps=1.0, max_hit=5, accuracy=0.5
    )

    assert kill.kills_per_hour(overhead=30.0) == pytest.approx(60.0)
    assert kill.kills_per_hour(overhead=0.0) == pytest.approx(120.0)


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


def test_measure_overhead_reports_samples_not_an_average() -> None:
    """Including the negative ones, which is the point.

    The wiki's rates assume near-max gear and these kill times come from
    chunk-restricted BiS, so where the map's gear is worse the implied
    overhead goes negative. Averaging that away would hide the gap.
    """
    index = _FakeIndex({"Rat": _target(name="Rat", hitpoints=8)})
    samples = dps_bridge.measure_overhead(
        _chunk_info(),
        {"Melee-weapon": "Abyssal whip"},
        LEVELS,
        {"Rat": Rate(value=100.0, source="wiki")},
        index=index,  # type: ignore[arg-type]
    )

    assert len(samples) == 1
    assert samples[0].monster == "Rat"
    assert samples[0].wiki_kph == 100.0
    assert samples[0].overhead == pytest.approx(36.0 - samples[0].ttk)
