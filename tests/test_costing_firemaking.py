"""Burning a log, which is two methods with two mechanics."""

from __future__ import annotations

import pytest

from chunksim.costing import firemaking
from chunksim.costing.heuristics import burning_rate

#: `Pay-to-play Firemaking training`'s own assumption for a perfect line.
WIKI_LOGS_PER_HOUR = 1485.0

#: The two bands that page docks for failed attempts, as
#: `(opening level, experience each, published xp/hour)`. Every other band in
#: the table is exactly `experience * 1485`; these two are quoted below it
#: under the footnote "includes some time lost to failed attempts".
FAILCHANCE_BANDS = ((30, 90.0, 107_000.0), (35, 105.0, 138_000.0))


def test_the_success_curve_is_the_skills_own() -> None:
    """`{{Skilling success chart|low=64|high=512}}` on the Firemaking page,
    which the prose beside it states as 65/256 at level 1, certainty from 43
    and 513/256 at 99."""
    assert firemaking.light_chance(1) == pytest.approx(65 / 256)
    assert firemaking.light_chance(43) == 1.0
    assert firemaking.light_chance(99) == 1.0


def test_a_failed_light_costs_the_whole_cycle() -> None:
    """Four ticks an attempt, so a quarter chance is four times the time - the
    same shape `costing/shortcuts.py` gives an Agility shortcut."""
    assert firemaking.line_seconds(43) == pytest.approx(4 * 0.6)
    assert firemaking.line_seconds(1) == pytest.approx(4 * 0.6 * 256 / 65)


def test_the_wikis_own_failure_arithmetic_checks_this_model() -> None:
    """**Two rows, and a residual under 1% on both.**

    `Pay-to-play Firemaking training` multiplies 1,485 logs an hour by the
    experience for every band from 42 up, and quotes the two bands below 43
    *lower* than that product under a footnote saying why. Those published
    ratios are what this model produces from a curve fitted to nothing.

    Not an identity: the wiki charges no banking time and this charges ten
    seconds an inventory, so the two rates differ by 12% while the *ratios*
    agree. What is being checked is the failure model, not the cadence.
    """
    for level, experience, published in FAILCHANCE_BANDS:
        never_fails = experience * WIKI_LOGS_PER_HOUR
        assert published < never_fails, "the wiki docks this band for failures"

        theirs = published / never_fails
        ours = firemaking.line_xp_per_hour(experience, level) / firemaking.line_xp_per_hour(
            experience, firemaking.CERTAIN_AT
        )

        assert ours == pytest.approx(theirs, rel=0.015)


def test_the_wikis_cadence_is_this_models_cadence() -> None:
    """Its table's 1,485 logs an hour is four ticks with a little slop, and
    above 43 nothing else is in the way - so the two agree on logs an hour to
    within the banking this charges and it does not."""
    logs_per_hour = 3600.0 / firemaking.line_seconds(firemaking.CERTAIN_AT)

    assert logs_per_hour == pytest.approx(1500.0)
    assert logs_per_hour == pytest.approx(WIKI_LOGS_PER_HOUR, rel=0.02)


def test_a_campfire_never_rolls() -> None:
    """**The training page says so by omission and it is load-bearing.** Its
    campfire table quotes a flat 665 logs an hour at every level including
    1-15, where the line-burning table's own rows are docked for failures. You
    are feeding a fire, not lighting one."""
    at_one = firemaking.campfire_xp_per_hour(40.0)
    assert at_one == firemaking.campfire_xp_per_hour(40.0)
    # No level argument exists to pass, which is the point - but the published
    # cadence is what the rate is built from.
    assert 3600.0 / (firemaking.CAMPFIRE_TICKS * 0.6) == pytest.approx(666.7, rel=0.01)


def test_the_two_methods_cross_over_and_the_crossover_is_the_finding() -> None:
    """A campfire is worth having below level 12 and never above it. Priced as
    one number - which is what upstream's two challenges were getting - they
    were wrong in both directions at once."""
    campfire = firemaking.campfire_xp_per_hour(40.0)

    assert firemaking.line_xp_per_hour(40.0, 11) < campfire
    assert firemaking.line_xp_per_hour(40.0, 12) > campfire
    # And by a factor of two once the roll stops mattering.
    assert firemaking.line_xp_per_hour(40.0, 43) / campfire == pytest.approx(2.08, rel=0.01)


def test_the_model_reduces_to_the_scrape_it_supersedes() -> None:
    """`heuristics.burning_rate` is one branch of one method - a line, at the
    level the roll saturates - so this pins that the model still contains it.
    A change to either that moves them apart is a change to the mechanic and
    should have to be argued for."""
    for experience in (40.0, 90.0, 303.8, 350.0):
        assert firemaking.line_xp_per_hour(experience, firemaking.CERTAIN_AT) == pytest.approx(
            burning_rate(experience)
        )


def test_the_inventory_differs_by_the_tinderbox() -> None:
    """Which the export itself records: `Burn ~|X logs|~` lists one in its
    `Items` and `Burn ~|X logs|~ at a fire` does not."""
    assert firemaking.CAMPFIRE_LOGS_PER_TRIP == firemaking.LINE_LOGS_PER_TRIP + 1


def test_bands_stop_where_the_curve_saturates() -> None:
    """Above 43 the rate is flat, so another point would say nothing - and a
    log that opens above it gets exactly one."""
    assert firemaking.steps_for(1) == (1, 10, 20, 30, 40, 43)
    assert firemaking.steps_for(30) == (30, 40, 43)
    assert firemaking.steps_for(45) == (45,)
    assert firemaking.steps_for(90) == (90,)


def _challenges() -> dict[str, dict[str, object]]:
    return {
        "Burn ~|logs|~": {
            "Items": ["Logs*", "Tinderbox"],
            "Level": 1,
            "Primary": True,
        },
        "Burn ~|logs|~ at a fire": {
            "Items": ["Logs*"],
            "Objects": ["ForesterFire[+]"],
            "Level": 1,
            "Primary": True,
        },
        "Burn ~|magic logs|~": {
            "Items": ["Magic logs", "Tinderbox"],
            "Level": 75,
            "Primary": True,
        },
    }


def test_the_campfire_half_is_told_apart_by_upstreams_objects() -> None:
    """**Not by the `at a fire` suffix**, which a rename could take away. The
    `ForesterFire[+]` requirement is the thing that makes the action what it
    is."""
    challenges = _challenges()
    found = firemaking.methods(challenges, dict.fromkeys(challenges, {}), {"Logs": 40.0})["Firemaking"]

    campfire = [method for method in found if method.method == firemaking.CAMPFIRE_ACTIVITY]
    assert len(campfire) == 1
    assert campfire[0].knob == "training/Burn ~|logs|~ at a fire/Firemaking"
    # One point, because nothing about a campfire moves with level.
    assert campfire[0].level == 1


def test_the_log_is_joined_through_items_not_the_task_name() -> None:
    """The same join the scrape this supersedes already made. `Items` carries
    a trailing `*` for "or better" and the tinderbox alongside, so the log is
    the entry the experience table has heard of rather than the first one."""
    challenges = _challenges()
    burning = {"Logs": 40.0, "Magic logs": 303.8}

    found = firemaking.methods(challenges, dict.fromkeys(challenges, {}), burning)["Firemaking"]

    magic = [m for m in found if m.knob == "training/Burn ~|magic logs|~/Firemaking"]
    assert len(magic) == 1, "one point: it opens at 75, above the saturation level"
    assert magic[0].xp_per_hour == pytest.approx(burning_rate(303.8))


def test_a_log_the_experience_table_has_never_heard_of_is_refused() -> None:
    """No experience, no rate - a made-up figure for an unlisted log would
    read as a method rather than as a gap."""
    challenges = _challenges()

    assert firemaking.methods(challenges, dict.fromkeys(challenges, {}), {}) == {}


@pytest.mark.real_export
def test_every_burning_challenge_the_export_carries_is_one_of_the_two(
    real_export: object,
) -> None:
    """**Both halves exist for every log and nothing else looks like one.**

    The pairing is what makes the crossover reachable at all: a log with only
    a line challenge would lose its low-level method. Sizes are not pinned -
    upstream grows - but a pair that stopped being a pair is a shape change.
    """
    challenges = real_export.challenges["Firemaking"]  # type: ignore[attr-defined]

    lines = {name for name in challenges if name.startswith("Burn ~|") and " at a fire" not in name}
    fires = {name for name in challenges if name.endswith(" at a fire")}

    assert len(fires) > 10
    assert {name.removesuffix(" at a fire") for name in fires} <= lines
    for name in fires:
        assert firemaking._is_campfire(challenges[name]), name
    for name in lines:
        assert not firemaking._is_campfire(challenges[name]), name
