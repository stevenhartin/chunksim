"""Pickpocketing, where the wiki publishes the whole mechanic as an equation."""

from __future__ import annotations

import pytest

from chunksim.costing import pickpocket
from chunksim.costing.gathering import success_chance
from chunksim.store import cache

#: The Knight of Ardougne, which is the NPC every published figure is about.
KNIGHT_XP = 84.3
#: Its plain success curve, off its own page's `pickpocket chance` chart.
KNIGHT_PLAIN = (50.0, 240.0)
#: The same chart's `Ardougne Diary` series - which is what `Thieving training`
#: assumes, along with dodgy necklaces, for every rate it publishes.
KNIGHT_DIARY = (55.0, 264.0)
#: A dodgy necklace's chance to shrug off the stun.
DODGY_RESIST = 0.25


def test_the_tick_equation_is_the_wikis_own() -> None:
    """`Thieving` states it: "every pickpocket will take on average
    `2 + 8(1-p)` ticks". Both halves are published too - the stun is 8 ticks on
    `Stun (status)`, and a never-failing knight at 252,900 xp/hr is 3,000
    pickpockets an hour, which is a 2-tick attempt."""
    assert pickpocket.attempt_ticks(1.0) == 2.0
    assert pickpocket.attempt_ticks(0.0) == 10.0
    assert pickpocket.attempt_ticks(0.5) == 6.0


def test_the_tick_perfect_rate_is_the_published_one() -> None:
    """252,900 xp/hr, stated on `Thieving training` as the rate from level 95
    onwards. This is the one figure the model reproduces exactly, because it is
    the one with no success chance in it."""
    assert pickpocket.xp_per_hour(KNIGHT_XP, 99, *KNIGHT_DIARY) == pytest.approx(252_900.0)


def test_the_geared_figure_comes_out_within_two_percent() -> None:
    """**The check on the whole mechanic.** `Thieving training` quotes 86,000
    xp/hr at level 55 and says what it assumes: the medium Ardougne Diary and
    dodgy necklaces. Feeding the model that curve and that resist gives 84,630,
    from a curve fitted to nothing.

    Not what this module *spends* - see the next test - but it is the only way
    to check the arithmetic against a published number at all.
    """
    modelled = pickpocket.xp_per_hour(KNIGHT_XP, 55, *KNIGHT_DIARY, stun_resist=DODGY_RESIST)

    assert modelled == pytest.approx(86_000.0, rel=0.02)


def test_the_level_failing_stops_is_the_level_the_page_names() -> None:
    """"Players stop failing to pickpocket Knights of Ardougne at level 95 with
    the medium diary perk". The curve reaches certainty at exactly 95 and not
    at 94, which is a sharp check on `low`/`high` rather than a soft one."""
    assert success_chance(94, *KNIGHT_DIARY) < 1.0
    assert success_chance(95, *KNIGHT_DIARY) == 1.0


def test_what_is_spent_is_the_plain_curve_and_it_is_lower() -> None:
    """**No gloves, no diary, no cape, no necklace.** A chunk map may hold none
    of them, and the estimate is about this map - so a knight reads 60,141/hr at
    55 against the guide's geared 86,000."""
    plain = pickpocket.xp_per_hour(KNIGHT_XP, 55, *KNIGHT_PLAIN)

    assert plain == pytest.approx(60_141, rel=0.001)
    assert plain < 86_000.0


def test_the_flat_cycle_this_replaces_was_fast_on_every_npc_it_can_check() -> None:
    """**Which is why the seven uncharted NPCs keep no rate.** The constant was
    `experience * 3600 / 3.5`, calibrated on one geared figure and applied to
    every NPC at every level. Measured against the plain curve at each NPC's own
    opening level it is fast on all of them, by up to 3.6x.
    """
    from chunksim.costing.heuristics import PICKPOCKET_CYCLE_SECONDS

    charted = cache.read_blob(cache.WIKI_RATES_BLOB_NAME)["data"]["pickpockets"]
    assert len(charted) > 20

    ratios = []
    for entry in charted.values():
        level, experience = entry["level"], entry["experience"]
        modelled = pickpocket.xp_per_hour(experience, level, entry["low"], entry["high"])
        flat = experience * 3600.0 / PICKPOCKET_CYCLE_SECONDS
        assert modelled < flat, entry
        ratios.append(flat / modelled)

    assert max(ratios) > 3.0
    assert min(ratios) > 1.0


def test_a_borrowed_curve_would_not_be_evidence() -> None:
    """The spread is the argument for refusing rather than defaulting: the
    charted NPCs run from about a third to about seven tenths at their own
    opening level, so a median of that is not a claim about any one of them."""
    charted = cache.read_blob(cache.WIKI_RATES_BLOB_NAME)["data"]["pickpockets"]
    chances = [success_chance(e["level"], e["low"], e["high"]) for e in charted.values()]

    assert min(chances) < 0.36
    assert max(chances) > 0.70


def test_bands_carry_the_level_the_curve_saturates_at() -> None:
    """A real corner of the rate rather than a tenth level, and the one the
    wiki names. Above it another point would say nothing.

    **The plain curve does not always reach it**, which is itself the shape of
    the correction: an ungeared knight is 94.1% at level 99 and never certain,
    where the page's "stop failing at 95" is the medium diary's curve. So the
    saturation point is a step only when there is one.
    """
    plain = pickpocket.steps_for(55, *KNIGHT_PLAIN)
    assert plain == (55, 60, 70, 80, 90, 99)
    assert success_chance(99, *KNIGHT_PLAIN) < 1.0

    diary = pickpocket.steps_for(55, *KNIGHT_DIARY)
    assert 95 in diary
    assert success_chance(94, *KNIGHT_DIARY) < 1.0


def _challenges() -> dict[str, dict[str, object]]:
    return {
        "Pickpocket a ~|knight of Ardougne|~": {
            "NPCs": ["Knight of Ardougne"],
            "Level": 55,
            "Primary": True,
        },
        "Pickpocket a ~|cave goblin|~": {
            "NPCs": ["Cave goblin"],
            "Level": 36,
            "Primary": True,
        },
    }


CURVES = {"Knight of Ardougne": (55, KNIGHT_XP, *KNIGHT_PLAIN)}


def test_only_a_charted_npc_gets_a_method() -> None:
    """The cave goblin has a `{{Thieving info}}` box and no success chart
    anywhere, so nothing published says how often it fails."""
    challenges = _challenges()
    found = pickpocket.methods(challenges, dict.fromkeys(challenges, {}), CURVES)["Thieving"]

    knobs = {method.knob for method in found}
    assert knobs == {"training/Pickpocket a ~|knight of Ardougne|~/Thieving"}
    assert all(method.method == pickpocket.ACTIVITY for method in found)
    assert len(found) > 1, "a curve is bands, not one number"


def test_the_npc_is_joined_through_the_exports_own_npcs_branch() -> None:
    """A structural join, not a read of the task's words - and case-folded,
    since upstream writes `Fremennik citizen` where the wiki's table writes
    `Fremennik Citizen`."""
    challenge = {"NPCs": ["knight of ardougne"], "Primary": True}

    assert pickpocket._charted(challenge, CURVES) == (55, KNIGHT_XP, *KNIGHT_PLAIN)
    assert pickpocket._charted({"NPCs": ["Nobody"], "Primary": True}, CURVES) is None


class _Rate:
    def __init__(self, source: str) -> None:
        self.source = source


def test_an_uncharted_pickpocket_loses_its_flat_rate() -> None:
    """**Not a worse estimate but a known-wrong one**, which is why it is taken
    away rather than left as the conservative option."""
    challenges = _challenges()
    training = {
        "Pickpocket a ~|cave goblin|~": {"Thieving": _Rate("wiki:pickpockets")},
        "Pickpocket a ~|knight of Ardougne|~": {"Thieving": _Rate("wiki:pickpockets")},
    }

    kept = pickpocket.refuse_uncharted(
        training, CURVES, challenges, dict.fromkeys(challenges, {})
    )

    assert "Pickpocket a ~|cave goblin|~" not in kept
    assert "Pickpocket a ~|knight of Ardougne|~" in kept


def test_a_money_making_guide_and_a_hand_pin_both_survive() -> None:
    """Only the flat-cycle source is taken away. A guide about one NPC is a
    different claim, and `overrides.json` is the top of the layering."""
    challenges = _challenges()
    guided = {"Pickpocket a ~|cave goblin|~": {"Thieving": _Rate("mmg:Some guide")}}
    valid: dict[str, dict[str, object]] = dict.fromkeys(challenges, {})

    assert pickpocket.refuse_uncharted(guided, CURVES, challenges, valid) == guided

    flat = {"Pickpocket a ~|cave goblin|~": {"Thieving": _Rate("wiki:pickpockets")}}
    pinned = frozenset({"Pickpocket a ~|cave goblin|~"})
    assert pickpocket.refuse_uncharted(flat, CURVES, challenges, valid, pinned) == flat


def test_another_skill_on_the_same_task_is_left_alone() -> None:
    """Stripping a rate means stripping *this skill's* rate, not the entry."""
    challenges = _challenges()
    training = {
        "Pickpocket a ~|cave goblin|~": {
            "Thieving": _Rate("wiki:pickpockets"),
            "Strength": _Rate("wiki:something"),
        }
    }

    kept = pickpocket.refuse_uncharted(
        training, CURVES, challenges, dict.fromkeys(challenges, {})
    )

    assert set(kept["Pickpocket a ~|cave goblin|~"]) == {"Strength"}


def test_the_shipped_curves_cover_the_npcs_the_charts_exist_for() -> None:
    """The blob is checked in, so this needs no network and no export. What it
    pins is that the branch is *there* - a re-scrape that silently stopped
    writing it would leave every pickpocket refused."""
    charted = cache.read_blob(cache.WIKI_RATES_BLOB_NAME)["data"]["pickpockets"]

    assert "Knight of Ardougne" in charted
    assert charted["Knight of Ardougne"] == {
        "level": 55,
        "experience": KNIGHT_XP,
        "low": KNIGHT_PLAIN[0],
        "high": KNIGHT_PLAIN[1],
    }
    # An alias inherits its row's curve; see `skill_tables.pickpocket_rows`.
    assert charted["Elf"] == charted["Elf (Thieving)"]


def test_what_it_takes_away_is_reported_as_a_decision() -> None:
    """**The blank it leaves is not the same blank as "nothing reached this".**
    This module has positive evidence against the flat cycle, which is why the
    rate goes; reported as `unpriced` that reads as a gap somebody should close.
    See `coverage.REFUSED`."""
    challenges = _challenges()
    training = {"Pickpocket a ~|cave goblin|~": {"Thieving": _Rate("wiki:pickpockets")}}
    refused: dict[str, str] = {}

    pickpocket.refuse_uncharted(
        training, CURVES, challenges, dict.fromkeys(challenges, {}), frozenset(), refused
    )

    assert refused == {"Pickpocket a ~|cave goblin|~": pickpocket.REASON}
    assert "no success chart" in pickpocket.REASON


def test_a_charted_npc_is_not_reported_as_refused() -> None:
    """Nothing was taken away from it, so there is nothing to explain."""
    challenges = _challenges()
    training = {
        "Pickpocket a ~|knight of Ardougne|~": {"Thieving": _Rate("wiki:pickpockets")}
    }
    refused: dict[str, str] = {}

    pickpocket.refuse_uncharted(
        training, CURVES, challenges, dict.fromkeys(challenges, {}), frozenset(), refused
    )

    assert refused == {}
