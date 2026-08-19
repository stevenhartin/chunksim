"""The Hallowed Sepulchre, counted in ticks rather than quoted in rates."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import sepulchre as sp
from chunksim.costing.gathering import GUESS

#: Every floor's challenge, as a map that reaches all of them.
_ALL: dict[str, dict[str, object]] = {
    "Agility": {task: {} for task in sp.TASKS.values()},
    "Thieving": {sp.COFFIN_TASK: {}, sp.GRAND_TASK: {}},
}


class TestThePublishedTableIsTheOracle:
    """**The wiki's `Realistic No looting XP/hour` column is a check on this
    model rather than its source** - the relationship `costing/barracuda.py`
    describes. It is realistic where this is tick-perfect, so the model should
    sit above it by a modest factor and never below."""

    @pytest.mark.parametrize(
        "floor,level,no_loot,loot",
        [
            (1, 52, 40_000.0, 30_000.0),
            (2, 62, 50_000.0, 40_000.0),
            (3, 72, 71_700.0, 63_000.0),
            (4, 77, 81_000.0, 73_000.0),
            (5, 87, 88_500.0, 75_800.0),
        ],
    )
    def test_a_row_is_the_wikis(
        self, floor: int, level: int, no_loot: float, loot: float
    ) -> None:
        """Floor 5's pair moved under this project and nothing caught it: the
        module carried 90,000/98,500, where 90,000 is a *footnote* about
        looting only the Grand Hallowed Coffin."""
        assert sp.level_for(floor) == level
        assert sp.FLOORS[floor][3] == no_loot
        assert sp.FLOORS[floor][2] == loot

    def test_the_levels_are_the_exports_own(self) -> None:
        # 52, 62, 72, 77, 87 in both, which is what makes the floor-to-challenge
        # join structural rather than a guess at which one means which.
        assert [sp.level_for(f) for f in sorted(sp.FLOORS)] == [52, 62, 72, 77, 87]

    def test_the_model_lands_near_the_realistic_column(self) -> None:
        """Not on it - the twenty seconds between laps is a third of a
        floor-1 lap and 4% of a floor-5 one, so the short floors read below
        their published rows and the deep ones just above."""
        for floor in sorted(sp.FLOORS):
            ratio = sp.agility_rate(floor) / sp.FLOORS[floor][3]
            assert 0.8 < ratio < 1.1, floor

    def test_the_top_floor_is_what_a_good_player_sustains(self) -> None:
        """What `MISTAKE_FACTOR` is calibrated on: 90,000-95,000 for five
        floors, no looting."""
        assert 90_000.0 < sp.agility_rate(5) < 95_000.0

    def test_and_that_is_within_four_percent_of_the_wikis_own_figure(self) -> None:
        """The independent half of the check - the calibration targets a
        sustainable rate and lands beside a published one."""
        assert sp.agility_rate(5) / sp.FLOORS[5][3] == pytest.approx(1.04, abs=0.01)

    def test_perfect_play_clears_the_pages_own_note(self) -> None:
        """"It is possible to reach rates above 100,000 XP/hr at maximum
        efficiency without mistakes" - the only quantitative statement the page
        makes about perfect play, and so the check on the raw arithmetic
        underneath `MISTAKE_FACTOR` rather than on the rate this spends."""
        perfect = sp.agility_xp(5) * 3600.0 / (
            sp.lap_seconds(5) - sp.BETWEEN_LAPS_SECONDS
            - sum(sp.floor_seconds(f) for f in sp.FLOORS) * (sp.MISTAKE_FACTOR - 1.0)
        )
        assert perfect > 100_000.0

    def test_no_constant_overhead_reconciles_the_two(self) -> None:
        """**The finding that settles they are different quantities.** Solving
        the published column for a per-floor overhead gives 21.8, 19.5, 10.8,
        12.8 and 27.9 seconds - so the gap is mistakes, which do not scale with
        the count of staircases, and a term could never have expressed it."""
        solved = []
        for floor in sorted(sp.FLOORS):
            lap = sp.agility_xp(floor) * 3600.0 / sp.FLOORS[floor][3]
            running = sum(sp.floor_seconds(f) for f in range(1, floor + 1))
            solved.append((lap - running) / floor)
        assert max(solved) / min(solved) > 2.0


class TestTheLap:
    def test_a_floor_time_is_the_mean_of_the_rows(self) -> None:
        # Which entrance a run gets is not the player's choice, so an hour is
        # a mix of them and the fastest row would be a claim about luck.
        assert sp.floor_seconds(1) == pytest.approx(30.0)
        assert sp.floor_seconds(3) == pytest.approx(54.24)

    def test_a_range_contributes_its_midpoint(self) -> None:
        # Floor 4 states `1:22 - 1:34` and `1:30 - 1:38` rather than times.
        assert sp.floor_seconds(4) == pytest.approx(91.0)

    def test_every_floor_carries_the_descent_into_it(self) -> None:
        gap = sp.BETWEEN_FLOORS_TICKS * sp.TICK_SECONDS
        one = sp.floor_seconds(1) * sp.MISTAKE_FACTOR + gap
        assert sp.lap_seconds(1) == pytest.approx(one + sp.BETWEEN_LAPS_SECONDS)
        assert sp.lap_seconds(2) - sp.lap_seconds(1) == pytest.approx(
            sp.floor_seconds(2) * sp.MISTAKE_FACTOR + gap
        )

    def test_a_lap_is_charged_the_return_to_the_lobby_once(self) -> None:
        # The timer runs out and puts you back; it is per lap, not per floor,
        # which is what makes a shallow lap expensive rather than free.
        bare = sum(
            sp.floor_seconds(f) * sp.MISTAKE_FACTOR
            + sp.BETWEEN_FLOORS_TICKS * sp.TICK_SECONDS
            for f in range(1, 6)
        )
        assert sp.lap_seconds(5) - bare == pytest.approx(sp.BETWEEN_LAPS_SECONDS)

    def test_only_the_running_is_inflated_by_mistakes(self) -> None:
        """A mistake is a tick lost inside a floor; the staircase and the
        lobby are already estimates of a whole action."""
        overheads = 5 * sp.BETWEEN_FLOORS_TICKS * sp.TICK_SECONDS + sp.BETWEEN_LAPS_SECONDS
        running = sum(sp.floor_seconds(f) for f in range(1, 6))
        assert sp.lap_seconds(5) == pytest.approx(
            running * sp.MISTAKE_FACTOR + overheads
        )

    def test_looting_adds_the_detour_once_per_floor(self) -> None:
        detour = sp.COFFIN_DETOUR_TICKS * sp.COFFINS_PER_FLOOR * sp.TICK_SECONDS
        assert sp.lap_seconds(5, looting=True) - sp.lap_seconds(5) == pytest.approx(
            5 * detour
        )

    def test_a_lap_pays_the_cumulative_experience(self) -> None:
        # `Cumulative Exp` in the wiki's own table: you cannot start on floor 5.
        assert sp.agility_xp(5) == 11_700.0
        assert sp.agility_xp(3) == 3_100.0

    def test_a_deeper_lap_is_worth_more_an_hour(self) -> None:
        rates = [sp.agility_rate(f) for f in sorted(sp.FLOORS)]
        assert rates == sorted(rates)


class TestTheCoffin:
    def test_its_experience_is_the_wikis_flat_two_hundred(self) -> None:
        """Stated on both coffin pages and again in the Strategies page's
        skill-challenge note. It does not vary by floor - what varies by floor
        is hallowed marks."""
        assert sp.COFFIN_XP == 200.0

    def test_the_chance_is_charted_and_the_plain_series_is_spent(self) -> None:
        # 41.8% where it opens, 74.6% at 99, no lockpick.
        assert sp.coffin_xp(66) == pytest.approx(83.6, abs=0.1)
        assert sp.coffin_xp(99) == pytest.approx(149.2, abs=0.1)

    def test_a_map_that_cannot_enter_gets_no_rate(self) -> None:
        assert sp.deepest_floor({}) == 0
        assert sp.thieving_rate(99, 0) == 0.0

    def test_the_depth_is_upstreams_own_gate(self) -> None:
        """Read off the `Access the Nth floor` challenges rather than off an
        Agility level - the export census infers none, and `1 < 52` there
        reports a priced method as unpriced."""
        assert sp.deepest_floor({sp.TASKS[1]: {}, sp.TASKS[3]: {}}) == 3
        assert sp.deepest_floor({task: {} for task in sp.TASKS.values()}) == 5

    def test_the_depth_is_taken_and_not_maximised_over(self) -> None:
        """**A shallow lap opens more coffins an hour and is not offered**,
        because what makes it possible - getting back to the lobby and starting
        again - is not published, and charging nothing for it would make the
        shallowest lap win by default. The consequence is real and stated: a
        map with Agility 87 reads a lower coffin rate than one with 52."""
        assert sp.thieving_rate(99, 1) > sp.thieving_rate(99, 5)
        # **And `BETWEEN_LAPS_SECONDS` is most of what closes the gap**, which
        # is why twenty seconds matters more than its size suggests: without a
        # lobby return a shallow lap is nearly free to repeat.
        assert sp.thieving_rate(99, 1) / sp.thieving_rate(99, 5) < 1.5

    def test_the_grand_coffin_is_one_per_lap(self) -> None:
        # It sits at the end of floor 5, so it is one two-hundred-experience
        # roll over the whole four hundred seconds - not a training method, and
        # priced so a reader can see that rather than see a blank.
        deep = sp.thieving_rate(84, 5)
        assert sp.thieving_rate(84, 5, coffins=1.0) == pytest.approx(deep / 5.0)


class TestEveryRateIsAGuess:
    """One invented factor makes the product invented, however many of the
    others are read off a page - `costing/tempoross.py`'s rule."""

    def test_the_invented_factors_are_named(self) -> None:
        assert sp.BETWEEN_FLOORS_TICKS == 6.0
        assert sp.BETWEEN_LAPS_SECONDS == 20.0
        assert sp.MISTAKE_FACTOR == 1.25
        assert sp.COFFIN_DETOUR_TICKS == 15.0
        assert sp.COFFINS_PER_FLOOR == 1.0

    def test_no_band_claims_better(self) -> None:
        for bands in sp.methods(_ALL).values():
            for band in bands:
                assert band.match == GUESS


class TestReachability:
    def test_every_floor_a_map_reaches(self) -> None:
        bands = sp.methods(_ALL)["Agility"]
        assert [b.level for b in bands] == [52, 62, 72, 77, 87]

    def test_only_the_floors_it_reaches(self) -> None:
        one: dict[str, dict[str, object]] = {"Agility": {sp.TASKS[3]: {}}}
        bands = sp.methods(one)["Agility"]
        assert len(bands) == 1 and bands[0].level == 72

    def test_nothing_when_it_reaches_none(self) -> None:
        assert sp.methods({}) == {}
        assert sp.methods({"Agility": {}}) == {}

    def test_the_coffin_bands_carry_the_thieving_level(self) -> None:
        # Upstream gates the challenge on Thieving; Agility decides the lap.
        bands = sp.methods(_ALL)["Thieving"]
        levels = [
            b.level
            for b in bands
            if b.knob.startswith(f"training/{sp.COFFIN_TASK}") and b.level is not None
        ]
        assert levels[0] == sp.COFFIN_LEVEL
        assert levels == sorted(levels)

    def test_the_grand_coffin_needs_the_fifth_floor(self) -> None:
        shallow: dict[str, dict[str, object]] = {
            "Agility": {sp.TASKS[4]: {}},
            "Thieving": {sp.GRAND_TASK: {}},
        }
        assert "Thieving" not in sp.methods(shallow)
        assert sp.methods(_ALL)["Thieving"]

    def test_a_band_names_the_task_it_would_be_overridden_through(self) -> None:
        for skill, bands in sp.methods(_ALL).items():
            for band in bands:
                assert band.knob.startswith("training/")
                assert band.knob.endswith(f"/{skill}")


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "sepulchre.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(sp.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`sepulchre.py`" in listing
