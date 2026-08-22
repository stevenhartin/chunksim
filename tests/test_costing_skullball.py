"""Werewolf Skullball: a published lap, an unpublished reset, one guess."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import skullball as sb
from chunksim.model.chunkinfo import ChunkInfo


class TestThePagesOwnDecayRule:
    """"750 Agility experience if you complete the game in under 4 minutes.
    For every 3 seconds over 4 minutes, you'll lose 8 experience." Carried
    rather than asserted as a constant, because it is what makes all three
    published lap rows pay the same."""

    def test_inside_four_minutes_is_full_marks(self) -> None:
        assert sb.experience_for(105.0) == 750.0
        assert sb.experience_for(239.0) == 750.0
        assert sb.experience_for(240.0) == 750.0

    def test_it_steps_every_three_seconds(self) -> None:
        assert sb.experience_for(242.9) == 750.0
        assert sb.experience_for(243.0) == 742.0
        assert sb.experience_for(246.0) == 734.0

    def test_it_never_goes_negative(self) -> None:
        assert sb.experience_for(10_000.0) == 0.0

    def test_every_published_lap_pays_the_maximum(self) -> None:
        """Which is the check on the table rather than a second fact: all
        three rows are inside the window, so the 750 column is not a
        coincidence of the wiki's formatting."""
        for _, fast, slow in sb.LAPS:
            assert sb.experience_for(fast) == 750.0
            assert sb.experience_for(slow) == 750.0
        assert sb.experience_for(sb.OPTIMAL_SECONDS) == 750.0


class TestWhichLapIsPriced:
    def test_it_is_the_run_recommended_route(self) -> None:
        assert sb.PRICED_LAP[0] == "Run recommended route"

    def test_it_takes_the_slow_end_of_the_band(self) -> None:
        """`costing/pyramid.py`'s rule for a hedged published range."""
        name, fast, slow = sb.PRICED_LAP
        assert sb.LAP_SECONDS == slow
        assert fast < slow

    def test_the_optimal_route_is_recorded_and_not_spent(self) -> None:
        """"With more effort, times as fast as 1:45 can be achieved" - a
        tooled regime (tile markers, mid-flight redirection) rather than the
        route the page presents, so it is the ceiling."""
        assert sb.OPTIMAL_SECONDS < min(fast for _, fast, _ in sb.LAPS)
        assert sb.rate_for(sb.OPTIMAL_SECONDS) > sb.xp_per_hour()

    def test_walking_and_scrambling_are_carried_and_slower(self) -> None:
        assert len(sb.LAPS) == 3
        for _, _, slow in sb.LAPS[1:]:
            assert sb.rate_for(slow) < sb.xp_per_hour()


class TestTheOneInventedNumber:
    """**The run back is measurable and the rest is not**, which is the whole
    of why this module is a `GUESS`."""

    def test_the_run_back_comes_off_the_wikis_own_tile_markers(self) -> None:
        # `Module:Tile markers/Werewolf Skullball recommended route.json`:
        # `End` at region (43, 8), goal 1 at (35, 13), so max(8, 5) tiles.
        assert sb.RUN_BACK_TILES == max(abs(43 - 35), abs(8 - 13))
        assert sb.RUN_BACK_SECONDS == pytest.approx(2.4)

    def test_the_reset_is_much_larger_than_the_part_that_is_published(
        self,
    ) -> None:
        """Which is the honest shape of it: the measurable component is 8% of
        the invented one, so calling the reset "derived" would be a fiction."""
        assert sb.RESET_SECONDS > 10 * sb.RUN_BACK_SECONDS

    def test_the_guess_is_bounded_because_the_lap_dominates(self) -> None:
        """Unlike most guesses here, the answer cannot move far: a whole
        minute of reset is only 27% off no reset at all."""
        none = sb.rate_for(sb.LAP_SECONDS, reset_seconds=0.0)
        minute = sb.rate_for(sb.LAP_SECONDS, reset_seconds=60.0)
        assert none == pytest.approx(16_364.0, abs=1.0)
        assert minute == pytest.approx(12_000.0, abs=1.0)
        assert minute / none > 0.7

    def test_the_conservative_end_was_taken(self) -> None:
        assert sb.xp_per_hour() == pytest.approx(13_846.0, abs=1.0)
        assert sb.xp_per_hour() < sb.rate_for(sb.LAP_SECONDS, reset_seconds=15.0)

    def test_the_band_it_decides_is_named(self) -> None:
        """**Said plainly rather than hidden**: the Edgeville monkey bars are
        15,000/hr from level 15 and this opens at 25, so a reset under 15
        seconds would take `fray`'s 25-40 band off them and 30 does not. It is
        the one place on any cached map the guess changes an answer."""
        monkey_bars = 15_000.0
        assert sb.xp_per_hour() < monkey_bars
        assert sb.rate_for(sb.LAP_SECONDS, reset_seconds=14.0) > monkey_bars
        assert sb.rate_for(sb.LAP_SECONDS, reset_seconds=16.0) < monkey_bars


class TestTheMethod:
    _VALID: dict[str, dict[str, object]] = {"Agility": {sb.TASK: {}}}

    def test_it_opens_where_upstream_says(self) -> None:
        bands = sb.methods(self._VALID)["Agility"]
        assert [b.level for b in bands] == [25]

    def test_it_is_one_band_because_nothing_here_moves_with_level(self) -> None:
        """A lap time is a lap time - the reward is a stopwatch, not a success
        chance, so there is no curve to band."""
        assert len(sb.methods(self._VALID)["Agility"]) == 1

    def test_every_band_is_a_guess(self) -> None:
        from chunksim.costing.gathering import GUESS

        assert {b.match for b in sb.methods(self._VALID)["Agility"]} == {GUESS}

    def test_nothing_when_unreachable(self) -> None:
        assert sb.methods({}) == {}
        assert sb.methods({"Agility": {}}) == {}

    def test_the_band_names_its_own_task(self) -> None:
        band = sb.methods(self._VALID)["Agility"][0]
        assert band.knob == f"training/{sb.TASK}/Agility"


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "skullball.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(sb.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`skullball.py`" in listing

    @pytest.mark.real_export
    def test_the_task_exists_and_upstream_gates_it_where_this_says(
        self, real_export: ChunkInfo
    ) -> None:
        """**A key that matches nothing is silently inert.** The quest and the
        `Ring of Charos` are upstream's to enforce and are not compared here -
        a challenge reaching this module is one the derivation already called
        valid, which is `costing/wintertodt.py`'s rule."""
        entry = real_export.challenges["Agility"].get(sb.TASK)
        assert isinstance(entry, dict)
        assert entry.get("Primary") is True
        assert entry.get("Level") == sb.OPENS_AT
