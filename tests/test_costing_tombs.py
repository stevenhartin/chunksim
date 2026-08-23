"""The Tombs of Amascut: an invocation dial, and where it stops paying."""

from __future__ import annotations

import math
import pathlib

import pytest

from chunksim.costing import encounter, tombs
from chunksim.costing.dps_bridge import load_monster_index


def _stats(seconds: float = 60.0, hitpoints: float = 500.0) -> tombs.StatsFor:
    def inner(target: str) -> tuple[float, float] | None:
        return (seconds, hitpoints)

    return inner


class TestTheDial:
    def test_the_bands_the_game_names(self) -> None:
        assert tombs.tier_of(0) == tombs.ENTRY
        assert tombs.tier_of(149) == tombs.ENTRY
        assert tombs.tier_of(150) == tombs.NORMAL
        assert tombs.tier_of(299) == tombs.NORMAL
        assert tombs.tier_of(300) == tombs.EXPERT

    def test_the_scaled_level_flattens_twice(self) -> None:
        """Above 310 and again above 430, which is what makes a very high
        invocation worth less than it looks."""
        assert tombs.scaled_raid_level(300) == 300
        assert tombs.scaled_raid_level(400) == pytest.approx(340)
        assert tombs.scaled_raid_level(500) == pytest.approx(350 + 70 / 6)

    def test_the_wikis_own_worked_example(self) -> None:
        """"At raid level 400, players will have a 1% chance for every
        10,500 - 20(310 + 90/3) = 3,700 points earned"."""
        assert tombs.points_per_percent(400) == pytest.approx(3_700)


class TestPointsAreDamageHere:
    def test_the_published_multipliers_are_applied(self) -> None:
        """**The contrast with the Chambers.** "1 damage dealt equates to 1
        room point" with a tabulated exception list, so this derives its points
        instead of taking a guide's total."""
        by_target = {target: multiplier for _r, target, multiplier in tombs.ROOMS}
        assert by_target["Ba-Ba"] == 2.0
        assert by_target["Zebak#Normal"] == 1.5
        assert by_target["Elidinis' Warden#Enraged"] == 2.5

    def test_the_starting_points_come_back_off(self) -> None:
        """"At the end of the raid, the starting 5,000 points are subtracted
        when calculating loot"."""
        stats = {target: (60.0, 100.0) for _r, target, _m in tombs.ROOMS}
        raw = sum(100.0 * m for _r, _t, m in tombs.ROOMS)
        assert tombs.points_for(stats) == pytest.approx(raw)

    def test_the_room_cap_binds_before_the_total(self) -> None:
        stats = {target: (60.0, 1_000_000.0) for _r, target, _m in tombs.ROOMS}
        assert tombs.points_for(stats) == pytest.approx(
            tombs.TOTAL_POINT_CAP - tombs.STARTING_POINTS
        )

    def test_a_room_that_cannot_be_priced_scores_nothing(self) -> None:
        assert tombs.points_for({}) == 0.0


class TestTheChest:
    def test_the_chance_is_capped_and_never_rolls_twice(self) -> None:
        """Unlike the Chambers: "excess points will not contribute towards a
        second roll"."""
        assert tombs.unique_chance(10_000_000, 600) == tombs.MAX_UNIQUE_CHANCE

    def test_every_published_row_sums_to_one(self) -> None:
        for level, weights in tombs.WEIGHTS.items():
            assert sum(weights.values()) == pytest.approx(1.0, abs=1e-3), level

    def test_the_table_is_the_nearest_row_and_not_a_curve(self) -> None:
        """Five rows is a set of measurements; a curve through them would
        invent weights the game never stated."""
        assert weights_key(tombs.weights_at(150)) == weights_key(tombs.WEIGHTS[150])
        assert weights_key(tombs.weights_at(340)) == weights_key(tombs.WEIGHTS[150])
        assert weights_key(tombs.weights_at(360)) == weights_key(tombs.WEIGHTS[350])

    def test_the_rare_items_thicken_with_the_level(self) -> None:
        """"The weightings of Osmumten's fang and the Lightbearer decrease
        while the relative weightings of other uniques increase"."""
        low = tombs.WEIGHTS[150]["Tumeken's shadow (uncharged)"]
        high = tombs.WEIGHTS[500]["Tumeken's shadow (uncharged)"]
        assert high > low


def weights_key(weights: object) -> object:
    return sorted(dict(weights).items())  # type: ignore[call-overload]


class TestTheShroudBinds:
    def test_entry_raids_can_never_close_the_log(self) -> None:
        """The shroud is a collection log entry and entry mode does not
        advance it, so a faster raid below 150 buys a log that never closes."""
        got = tombs.answer(100, _stats())
        assert got is not None and got.runs == math.inf
        assert got.bound_by == "cape"

    def test_a_high_level_is_bound_by_the_cape(self) -> None:
        got = tombs.answer(600, _stats(hitpoints=20_000.0))
        assert got is not None
        assert got.runs == tombs.CAPE_COMPLETIONS
        assert got.bound_by == "cape"

    def test_a_named_unique_ignores_the_cape(self) -> None:
        got = tombs.answer(
            600, _stats(hitpoints=20_000.0),
            encounter.Objective.for_unique("Tumeken's shadow (uncharged)"),
        )
        assert got is not None and got.runs < tombs.CAPE_COMPLETIONS

    def test_experience_is_declined_rather_than_guessed(self) -> None:
        assert tombs.answer(
            300, _stats(), encounter.Objective(kind=encounter.EXPERIENCE)
        ) is None

    def test_an_unpriceable_room_drops_the_level(self) -> None:
        assert tombs.answer(300, lambda target: None) is None


@pytest.mark.real_export
class TestAgainstTheLibrary:
    def test_every_room_is_a_target_osrs_dps_knows(self) -> None:
        index = load_monster_index()
        for room, target, _multiplier in tombs.ROOMS:
            assert target in index, f"{room}: {target}"

    def test_the_invocation_level_is_an_input_and_scales_health(self) -> None:
        """**Which is why `best` takes a factory per level**: every level is
        the same monsters at different health, so one lookup would price them
        all alike."""
        from osrs_dps import RaidInputs, scale

        from chunksim.costing import dps_bridge

        index = load_monster_index()
        versions = dps_bridge.version_index(index)
        target = dps_bridge.candidate_targets(index, "Ba-Ba", versions)[0][1]
        low = scale(target, RaidInputs(party_size=1, toa_invocation_level=150))
        high = scale(target, RaidInputs(party_size=1, toa_invocation_level=600))
        assert high.hitpoints > low.hitpoints


class TestItIsListed:
    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = (
            pathlib.Path(tombs.__file__)
            .with_name("__init__.py")
            .read_text(encoding="utf-8")
        )
        assert "`tombs.py`" in listing
