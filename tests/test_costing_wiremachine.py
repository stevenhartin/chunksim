"""The Dorgesh-Kaan wire machine, which is a stall that can fail."""

from __future__ import annotations

import pytest

from chunksim.costing import wiremachine


def test_the_cycle_is_the_pages_own_ten_ticks() -> None:
    """"After 8 ticks, 5 seconds, the wire respawns and can be grabbed again
    (a total of 10 ticks per wire stolen)" - stated outright, so the ceiling is
    22 experience every six seconds and nothing has to be assumed about it."""
    assert wiremachine.CYCLE_TICKS == 10.0
    ceiling = wiremachine.TICKS_PER_HOUR / wiremachine.CYCLE_TICKS * wiremachine.EXPERIENCE

    assert ceiling == pytest.approx(13_200.0)


def test_the_curve_is_the_current_one_and_the_rebalance_note_says_so() -> None:
    """**The sharp check.** The change of 8 May 2024 states "Thieving success
    rates have been increased slightly, from 94.1% at level 99 to 98.0%", and
    the chart read here gives 98.05% at 99. The pre-rebalance figure is still
    quoted in a hidden comment on the same page and would give 94%, so this
    also pins that the *right* number on the page was taken."""
    assert wiremachine.steal_chance(99) == pytest.approx(0.980, abs=0.001)
    assert wiremachine.steal_chance(99) != pytest.approx(0.941, abs=0.005)


def test_the_ceiling_the_page_quotes_is_the_level_99_rate() -> None:
    """"capping out at around 13,000 experience per hour, assuming no downtime
    and no failures" - which is the top of the curve rather than a fiction: at
    98% success the model reads 12,943."""
    assert wiremachine.xp_per_hour(99) == pytest.approx(13_000, rel=0.01)


def test_the_realistic_figure_the_page_quotes_is_mid_climb() -> None:
    """"a more realistic experience rate is somewhere around 9,000" - which the
    model reaches around level 62, and which is what a *flat* 9,240/hr guide
    figure was quoting for the whole skill."""
    assert wiremachine.xp_per_hour(62) == pytest.approx(9_000, rel=0.01)


def test_a_guide_quotes_the_middle_of_a_curve() -> None:
    """Which is the whole reason to displace it: the rate nearly doubles across
    the climb, from where the method opens to 99."""
    opens = wiremachine.xp_per_hour(wiremachine.LEVEL)

    assert opens == pytest.approx(7_167, rel=0.001)
    assert wiremachine.xp_per_hour(99) / opens == pytest.approx(1.81, rel=0.01)
    # The guide's flat figure sits between the two ends, as a guide should.
    assert opens < 9_240 < wiremachine.xp_per_hour(99)


def test_the_join_is_the_exports_own_object() -> None:
    """`Steal a ~|cave goblin wire|~` names `Wire machine` in its `Objects`,
    which is also the wiki's page title - so the join is a string equality
    rather than a read of the task's words."""
    challenges = {
        "Steal a ~|cave goblin wire|~": {"Objects": ["Wire machine"], "Primary": True},
        "Steal from a ~|silk stall|~": {"Objects": ["Silk stall"], "Primary": True},
    }
    valid: dict[str, dict[str, object]] = dict.fromkeys(challenges, {})

    found = wiremachine.methods(challenges, valid)["Thieving"]

    assert {method.knob for method in found} == {
        "training/Steal a ~|cave goblin wire|~/Thieving"
    }
    assert all(method.method == wiremachine.ACTIVITY for method in found)
    assert all(method.match == "modelled" for method in found)


def test_a_map_without_the_machine_gets_nothing() -> None:
    challenges = {"Steal from a ~|silk stall|~": {"Objects": ["Silk stall"], "Primary": True}}

    assert wiremachine.methods(challenges, dict.fromkeys(challenges, {})) == {}


def test_the_bands_open_where_the_machine_does_and_carry_no_saturation() -> None:
    """This curve never reaches certainty - 98.05% at 99 is where it ends - so
    there is no corner to add, unlike a pickpocket's."""
    assert wiremachine.steps_for() == (44, 50, 60, 70, 80, 90, 99)
    assert wiremachine.steal_chance(99) < 1.0


@pytest.mark.real_export
def test_the_export_still_carries_the_machine_under_this_object(
    real_export: object,
) -> None:
    """A rename upstream would silently unprice the method, so it fails here
    instead. Also pins the level, which is stated in this module and read from
    the wiki rather than from the export."""
    challenges = real_export.challenges["Thieving"]  # type: ignore[attr-defined]

    named = [
        name
        for name, challenge in challenges.items()
        if isinstance(challenge, dict) and wiremachine.OBJECT in (challenge.get("Objects") or ())
    ]

    assert named == ["Steal a ~|cave goblin wire|~"]
    assert challenges[named[0]]["Level"] == wiremachine.LEVEL
    assert challenges[named[0]]["Primary"] is True
