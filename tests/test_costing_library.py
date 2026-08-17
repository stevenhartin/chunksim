"""The Arceuus library, which pays a multiple of the level you already have."""

from __future__ import annotations

import pytest

from chunksim.costing import library


def test_a_tome_pays_a_multiple_of_the_level_held() -> None:
    """**Both stated on the page, and both raised at the same update**: Magic
    from 11x to 15x the player's level, Runecraft from 4x to 5x. Nothing about
    the activity gets faster as you climb - the reward does."""
    assert library.EXPERIENCE_PER_LEVEL == {"Magic": 15.0, "Runecraft": 5.0}
    assert library.xp_per_hour("Runecraft", 77) == pytest.approx(5 * 77 * 110)
    assert library.xp_per_hour("Magic", 99) == pytest.approx(15 * 99 * 110)


def test_one_book_is_one_tome() -> None:
    """"For finding and delivering the correct book, players will be given a
    book of arcane knowledge" - so the only unknown is books an hour, and 110
    is the measured middle of an observed 100-120."""
    assert library.BOOKS_PER_HOUR == 110.0


def test_a_skill_it_does_not_pay_earns_nothing() -> None:
    assert library.xp_per_hour("Herblore", 99) == 0.0
    assert library.xp_per_hour("Runecraft", 0) == 0.0


def test_both_challenges_are_priced_as_the_same_activity() -> None:
    """**One activity paying two skills**, like barbarian fishing - the export
    carries a challenge for each, so which you train is a choice rather than a
    split, and each is priced as though every tome went to it."""
    challenges = {
        "Runecraft": {
            "Turn in books at the ~|Arceuus Library|~ for Runecraft xp": {"Primary": True},
        },
        "Magic": {
            "Turn in books at the ~|Arceuus Library|~ for Magic xp": {"Primary": True},
            # Not the library, and must not be swept in by the phrase.
            "Cast ~|arceuus library teleport|~": {"Primary": True},
        },
    }
    valid: dict[str, dict[str, object]] = {
        skill: dict.fromkeys(tasks, {}) for skill, tasks in challenges.items()
    }

    found = library.methods(challenges, valid)

    assert set(found) == {"Runecraft", "Magic"}
    assert {m.method for bands in found.values() for m in bands} == {library.ACTIVITY}
    knobs = {m.knob for m in found["Magic"]}
    assert knobs == {
        "training/Turn in books at the ~|Arceuus Library|~ for Magic xp/Magic"
    }


def test_the_curve_is_a_straight_line_through_the_level() -> None:
    """A level-1 player is paid 5 experience a tome and a level-99 player 495,
    which is why this is banded rather than one number."""
    challenges = {
        "Runecraft": {"Turn in books at the ~|Arceuus Library|~ for Runecraft xp": {"Primary": True}}
    }
    valid: dict[str, dict[str, object]] = {"Runecraft": dict.fromkeys(challenges["Runecraft"], {})}

    bands = library.methods(challenges, valid)["Runecraft"]
    rates = {band.level: band.xp_per_hour for band in bands}

    assert rates[1] < rates[50] < rates[99]
    assert rates[99] / rates[1] == pytest.approx(99.0)
