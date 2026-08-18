"""Actions upstream files as training methods and nobody trains with."""

from __future__ import annotations

from chunksim.costing import coverage, oneoff


def test_the_four_mounts_and_three_cosmetics_are_named() -> None:
    """**Named individually, never inferred.** Upstream flags all seven
    `Primary: True`, exactly as it flags `Build a ~|wooden fence|~`, so there
    is no property of the export to key a rule on."""
    assert set(oneoff.ONE_OFF) == {
        "Build a ~|mounted bass|~",
        "Build a ~|mounted swordfish|~",
        "Build a ~|mounted shark|~",
        "Build an ~|alchemical hydra heads (mounted)|~",
        "Build one of the boat ~|flags|~",
        "Apply a ~|boat paint|~ to a boat",
        "Apply a ~|sail colour|~ to a sail",
    }


def test_every_entry_says_why() -> None:
    """The reason is the whole content of the status - it is printed in the
    column a priced method uses for its source."""
    assert all(reason.strip() for reason in oneoff.ONE_OFF.values())


def test_a_sword_mount_is_not_swept_in() -> None:
    """A rule over `(mounted)` names would take the three sword mounts, which
    are a real build-and-destroy loop: the wiki says the sword is returned
    when the object is destroyed (`recipe_rates.RETURNED_MATERIALS`)."""
    for task in (
        "Build a ~|darklight (mounted)|~",
        "Build a ~|silverlight (mounted)|~",
        "Build an ~|excalibur (mounted)|~",
    ):
        assert oneoff.reason(task) == ""


def test_ordinary_furniture_is_not_swept_in() -> None:
    assert oneoff.reason("Build a ~|wooden fence|~") == ""


def test_the_status_beats_every_priced_tier() -> None:
    """A decoration a map can reach is exempt from being priced at all, rather
    than priced badly - the mounts come out at ~3 xp/hr if walked."""
    assert coverage.status_of("modelled", one_off=True) == coverage.ONE_OFF
    assert coverage.status_of("exact", one_off=True) == coverage.ONE_OFF
    assert coverage.status_of("default", one_off=True) == coverage.ONE_OFF
    assert coverage.status_of("modelled", pinned=True, one_off=True) == coverage.ONE_OFF


def test_unreachable_still_wins() -> None:
    """A decoration a map cannot reach is first of all unreachable: the report
    is about one world, and `one-off` is a claim about the challenge."""
    assert (
        coverage.status_of("default", reachable=False, one_off=True)
        == coverage.UNREACHABLE
    )
    assert (
        coverage.status_of(
            "default", reachable=False, one_off=True, absent=coverage.UNCOMPLETABLE
        )
        == coverage.UNCOMPLETABLE
    )
