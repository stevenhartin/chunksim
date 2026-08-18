"""Filling leaks on the Fishing Trawler, which is a ceiling rather than a rate."""

from __future__ import annotations

import pytest

from chunksim.costing import trawler


class TestTheBudgetIsThePublishedCap:
    def test_a_leak_is_one_point_per_experience(self) -> None:
        """Which is what makes it the best use of the budget - fixing a rail
        is the same 5 experience for 10 points."""
        assert trawler.LEAK_POINTS == 5
        assert trawler.LEAK_XP == 5.0

    def test_the_cap_spent_on_leaks_is_the_cap_in_experience(self) -> None:
        """"A maximum of 255 points may be earned per game", and at one point
        per experience that is 255 Construction."""
        assert trawler.POINT_CAP == 255
        assert trawler.leaks_per_game() == 51
        assert trawler.xp_per_game() == 255.0

    def test_the_leak_count_is_floored(self) -> None:
        """The cap is per game, so a part-paid leak is not a leak."""
        assert trawler.leaks_per_game() * trawler.LEAK_POINTS <= trawler.POINT_CAP

    def test_a_round_is_six_and_a_half_minutes(self) -> None:
        """"5 minutes of trawling, 1 minute of docking, and 15 seconds of
        cutscene at both the start and end of the trawl"."""
        assert trawler.ROUND_SECONDS == pytest.approx(390.0)
        assert 3600.0 / trawler.ROUND_SECONDS == pytest.approx(9.23, abs=0.01)

    def test_the_bare_ceiling(self) -> None:
        assert trawler.rate() == pytest.approx(2_353.8, abs=1.0)


class TestThePasteIsCharged:
    def test_one_paste_a_leak(self) -> None:
        asked: list[tuple[str, float]] = []

        def record(item: str, quantity: float) -> float:
            asked.append((item, quantity))
            return 0.0

        trawler.seconds_per_game(record)

        assert asked == [("Swamp paste", 51.0)]

    def test_charging_it_lowers_the_rate(self) -> None:
        assert 0 < trawler.rate(lambda i, q: 2.0 * q) < trawler.rate()

    def test_no_route_to_paste_is_no_rate(self) -> None:
        assert trawler.seconds_per_game(lambda i, q: None) is None
        assert trawler.rate(lambda i, q: None) == 0.0


class TestTheGate:
    _VALID = {
        "Fishing": {trawler.GATE_TASK: True},
        "Construction": {trawler.TASK: True},
    }

    def test_both_challenges_are_needed(self) -> None:
        assert set(trawler.methods(self._VALID)) == {"Construction"}

    def test_it_gates_on_the_fishing_challenge(self) -> None:
        """Upstream's Construction twin says `Level: 1`; the Fishing one
        carries the 15 Fishing needed to board at all."""
        assert trawler.methods({"Construction": self._VALID["Construction"]}) == {}

    def test_a_map_without_the_house_gets_nothing(self) -> None:
        """The house is upstream's own `Player-owned house` chunk on the
        Construction challenge, so its absence is its invalidity."""
        assert trawler.methods({"Fishing": self._VALID["Fishing"]}) == {}

    def test_the_band_is_flat_in_the_level(self) -> None:
        """The experience is a property of the action rather than the player,
        so a level-1 builder fills leaks at the same rate as a level-99 one."""
        (band,) = trawler.methods(self._VALID)["Construction"]

        assert band.level is None
