"""Giant Mole's burrow mechanic - see `costing/giant_mole.py` for the
citations behind each figure."""

from __future__ import annotations

import pytest

from chunksim.costing import giant_mole


class TestThePublishedMechanic:
    def test_the_window_is_fifty_to_five_percent(self) -> None:
        assert giant_mole.WINDOW_HP_SHARE == pytest.approx(0.45)

    def test_the_chance_is_one_quarter(self) -> None:
        """Cited to Mod Ash: '1/4 when its health is between 5% and 50%.'"""
        assert giant_mole.BURROW_CHANCE_PER_ATTACK == pytest.approx(0.25)


class TestExpectedBurrows:
    def test_scales_with_kill_time(self) -> None:
        assert giant_mole.expected_burrows(200.0) > giant_mole.expected_burrows(100.0)

    def test_zero_for_a_zero_or_negative_kill(self) -> None:
        assert giant_mole.expected_burrows(0.0) == 0.0
        assert giant_mole.expected_burrows(-5.0) == 0.0

    def test_matches_the_stated_formula(self) -> None:
        kill_seconds = 120.0
        attacks = kill_seconds / giant_mole.ASSUMED_ATTACK_SPEED_SECONDS
        expected = attacks * giant_mole.WINDOW_HP_SHARE * giant_mole.BURROW_CHANCE_PER_ATTACK
        assert giant_mole.expected_burrows(kill_seconds) == pytest.approx(expected)


class TestEffectiveSeconds:
    def test_adds_chase_time_for_each_expected_burrow(self) -> None:
        kill_seconds = 90.0
        expected = kill_seconds + giant_mole.expected_burrows(kill_seconds) * (
            giant_mole.CHASE_SECONDS_PER_BURROW
        )
        assert giant_mole.effective_seconds(kill_seconds) == pytest.approx(expected)

    def test_never_reads_faster_than_the_plain_kill(self) -> None:
        for kill_seconds in (10.0, 60.0, 300.0):
            assert giant_mole.effective_seconds(kill_seconds) >= kill_seconds

    def test_a_faster_kill_still_burrows_less_in_absolute_terms(self) -> None:
        """A faster kill crosses the 45%-health window in fewer attacks,
        so its overhead is smaller, even though it is not literally
        proportional to kill speed."""
        slow_overhead = giant_mole.effective_seconds(300.0) - 300.0
        fast_overhead = giant_mole.effective_seconds(60.0) - 60.0
        assert fast_overhead < slow_overhead
