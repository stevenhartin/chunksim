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
