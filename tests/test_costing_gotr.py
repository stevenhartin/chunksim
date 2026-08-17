"""Guardians of the Rift as one minigame rather than twelve rune methods."""

from __future__ import annotations

import pytest

from chunksim.costing import gotr
from chunksim.costing.gathering import CURVE_STEPS

#: The twelve the minigame offers: `{rune: (own level, xp per guardian essence)}`.
_RUNES = {
    "Air rune": (1, 5.0), "Mind rune": (2, 5.5), "Water rune": (5, 6.0),
    "Earth rune": (9, 6.5), "Fire rune": (14, 7.0), "Body rune": (20, 7.5),
    "Cosmic rune": (27, 8.0), "Chaos rune": (35, 8.5), "Nature rune": (44, 9.0),
    "Law rune": (54, 9.5), "Death rune": (65, 10.0), "Blood rune": (77, 10.5),
}

#: `parse_gotr`'s published Runecraft bands.
_BANDS = {40: 25000.0, 50: 40000.0, 75: 50000.0, 85: 65000.0, 99: 70000.0}


def test_the_mix_weights_the_two_open_portals_equally() -> None:
    """**Only two portals are open, one elemental and one catalytic**, and the
    game decides which - so an essence is as likely to become the elemental
    rune as the catalytic one, and within each half the player takes whatever
    is up."""
    at_27 = gotr.rune_mix(_RUNES, 27)

    elemental = (5.0 + 6.0 + 6.5 + 7.0) / 4
    catalytic = (5.5 + 7.5 + 8.0) / 3
    assert at_27 == pytest.approx(0.5 * elemental + 0.5 * catalytic)


def test_the_mix_rises_only_when_a_rune_becomes_reachable() -> None:
    """Imbuing needs the same level as crafting normally, so what a level buys
    in *quality* is access to better runes - and nothing between two of them."""
    assert gotr.rune_mix(_RUNES, 30) == gotr.rune_mix(_RUNES, 34), "chaos opens at 35"
    assert gotr.rune_mix(_RUNES, 35) > gotr.rune_mix(_RUNES, 34)
    assert gotr.rune_mix(_RUNES, 99) == gotr.rune_mix(_RUNES, 77), "blood is the last"


def test_nobody_plays_below_the_minigames_own_requirement() -> None:
    """The rune's level is not the activity's. `Craft an ~|air rune|~ with
    guardian essence` is a level-1 challenge in the export and a level-27
    activity in the game, and pricing it at 1 would offer the minigame to a
    player who cannot enter."""
    assert gotr.GOTR_LEVEL == 27
    assert [level for level, _ in gotr.rates(_RUNES, _BANDS)] == [
        step for step in CURVE_STEPS if step >= 27
    ]


def test_throughput_is_recovered_from_the_published_bands() -> None:
    """**The split between what is modelled and what is calibrated.** Nothing
    publishes essence per hour, so the published experience bands are divided
    by the modelled mix to recover it - and the model has to reproduce the
    band it was calibrated on."""
    priced = dict(gotr.rates(_RUNES, _BANDS))

    assert priced[40] == pytest.approx(25_000.0)
    assert priced[50] == pytest.approx(40_000.0)
    assert priced[99] == pytest.approx(70_000.0)


def test_below_the_first_band_only_the_mix_moves() -> None:
    """The medium pouch covers 25 to 49, so a player at 30 and one at 40 carry
    the same essence and differ only in which runes they can imbue. That is the
    one extrapolation here and it is why it is narrow."""
    priced = dict(gotr.rates(_RUNES, _BANDS))

    assert priced[30] < priced[40]
    assert priced[30] / priced[40] == pytest.approx(
        gotr.rune_mix(_RUNES, 30) / gotr.rune_mix(_RUNES, 40)
    )


def test_every_challenge_gets_the_same_curve_under_one_name() -> None:
    """**One minigame.** All twelve share the bands, and they are labelled the
    activity rather than a rune - a climb spent inside the minigame used to
    read as "Craft an air rune with guardian essence" from 30 to 99."""
    challenges = {
        "Craft an ~|air rune|~ with guardian essence": {
            "Level": 1, "Primary": True, "Output": "Air rune",
        },
        "Craft a ~|law rune|~ with guardian essence": {
            "Level": 54, "Primary": True, "Output": "Law rune",
        },
        # The ordinary altar is a different activity and must not be included.
        "Craft a ~|law rune|~": {"Level": 54, "Primary": True, "Output": "Law rune"},
    }
    experience = {name: xp for name, (_, xp) in _RUNES.items()}

    found = gotr.methods(challenges, dict.fromkeys(challenges, {}), _BANDS, experience)

    assert set(found) == {"Runecraft"}
    knobs = {method.knob for method in found["Runecraft"]}
    assert knobs == {
        "training/Craft an ~|air rune|~ with guardian essence/Runecraft",
        "training/Craft a ~|law rune|~ with guardian essence/Runecraft",
    }
    assert {method.method for method in found["Runecraft"]} == {gotr.ACTIVITY}
