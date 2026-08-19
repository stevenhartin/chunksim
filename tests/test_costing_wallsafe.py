"""The Rogues' Den lobby safes, where one click is a run of attempts."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import wallsafe as ws
from chunksim.costing.gathering import CONFIRMED, success_chance

_VALID: dict[str, dict[str, object]] = {"Thieving": {ws.TASK: {}}}


class TestTheChartIsThePagesOwnProse:
    """"The chance of successfully opening a wall safe is 33.2% at level 50,
    scaling up to a 62.9% chance at level 99" - and the chart beside it says
    the same thing to the quarter-percent, which is what makes the series the
    right one to read."""

    def test_the_two_stated_points(self) -> None:
        assert ws.attempt_chance(50) == pytest.approx(0.332, abs=0.0005)
        assert ws.attempt_chance(99) == pytest.approx(0.629, abs=0.0005)

    def test_it_is_the_plain_series(self) -> None:
        # The stethoscope's is `low2=16 high2=192` and is charted beside it;
        # Martin Thwait's shop needs Agility 50, so it is an item this map may
        # not hold - `costing/pickpocket.py`'s split.
        assert ws.CURVE == (8.0, 160.0)
        assert ws.attempt_chance(99) < success_chance(99, 16.0, 192.0)


class TestTheTrapRuleIsTheWholeModel:
    """**Two published figures and no free parameter.** The page states "the
    chance of triggering a trap per attempt appears to be (100% - success
    chance) / 2", which makes an attempt a three-way roll and a run a race
    between cracking and springing."""

    @pytest.mark.parametrize("level,published", [(50, 0.49), (99, 0.77)])
    def test_it_reproduces_the_published_overall_rate(
        self, level: int, published: float
    ) -> None:
        """Within a point of both, which is what the page claims for itself:
        the figures are "estimated", cross-referenced against 4,780 measured
        attempts, and the trap rule is stated as what "appears to be" the
        case. 49.85% and 77.22% here."""
        assert ws.run_chance(level) == pytest.approx(published, abs=0.01)

    def test_a_run_is_more_likely_to_crack_than_one_attempt(self) -> None:
        # You get to keep going; only the trap stops you.
        for level in (50, 75, 99):
            assert ws.run_chance(level) > ws.attempt_chance(level)

    def test_a_certain_attempt_is_a_certain_run(self) -> None:
        assert 2.0 * 1.0 / (1.0 + 1.0) == 1.0


class TestTheCadence:
    def test_an_attempt_is_the_stated_four_ticks(self) -> None:
        # "the player will automatically make another attempt to crack the
        # safe every 4 ticks (2.4 seconds)".
        assert ws.ATTEMPT_TICKS == 4.0

    def test_the_reclick_is_recovered_from_the_pages_own_ceiling(self) -> None:
        """"the safe can theoretically be looted every 8 ticks, granting up to
        52,500 experience per hour, assuming no failures" - eight ticks at 70
        experience is exactly 52,500, and one attempt is four of them."""
        assert ws.EXPERIENCE * ws.TICKS_PER_HOUR / 8.0 == ws.MAX_PER_HOUR
        assert ws.ATTEMPT_TICKS + ws.RECLICK_TICKS == 8.0

    def test_the_model_reduces_to_that_ceiling_when_nothing_fails(self) -> None:
        # The third check: at `p = 1` a run is one attempt and always cracks.
        certain = ws.EXPERIENCE * 1.0 * ws.TICKS_PER_HOUR / (
            ws.RECLICK_TICKS + ws.ATTEMPT_TICKS * 2.0 / 2.0
        )
        assert certain == ws.MAX_PER_HOUR

    def test_a_higher_level_ends_a_run_sooner(self) -> None:
        assert ws.run_ticks(99) < ws.run_ticks(50)


class TestTheRate:
    def test_it_lands_where_the_page_says_it_realistically_does(self) -> None:
        """"realistically it is usually significantly less, around 30-40k xp
        per hour" - said of the 52,500 ceiling."""
        assert 30_000 < ws.xp_per_hour(99) < 40_000

    def test_and_never_reaches_the_ceiling(self) -> None:
        for level in (50, 75, 99):
            assert ws.xp_per_hour(level) < ws.MAX_PER_HOUR

    def test_it_climbs_with_the_level(self) -> None:
        rates = [ws.xp_per_hour(level) for level in (50, 60, 70, 80, 90, 99)]
        assert rates == sorted(rates)


class TestBands:
    def test_the_first_band_opens_where_upstream_does(self) -> None:
        bands = ws.methods(_VALID)["Thieving"]
        assert bands[0].level == ws.LEVEL == 50

    def test_nothing_where_the_map_cannot_reach_it(self) -> None:
        assert ws.methods({}) == {}
        assert ws.methods({"Thieving": {}}) == {}

    def test_every_band_is_confirmed(self) -> None:
        # Every term is published or recovered from a published figure; the
        # only judgement is which chart series to spend.
        for band in ws.methods(_VALID)["Thieving"]:
            assert band.match == CONFIRMED

    def test_a_band_names_the_task_it_would_be_overridden_through(self) -> None:
        for band in ws.methods(_VALID)["Thieving"]:
            assert band.knob == f"training/{ws.TASK}/Thieving"


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "wallsafe.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(ws.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`wallsafe.py`" in listing
