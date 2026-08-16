"""Pyramid Plunder: the published table, and the one number that is not."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import pyramid_plunder as pp
from chunksim.costing.gathering import success_chance


class TestTheWikisOwnTable:
    @pytest.mark.parametrize(
        "room,opens,urn,chest,door",
        [
            (1, 21, 60.0, 40.0, 40.0),
            (4, 51, 215.0, 140.0, 140.0),
            (8, 91, 825.0, 550.0, 0.0),
        ],
    )
    def test_a_row_is_the_tables(
        self, room: int, opens: int, urn: float, chest: float, door: float
    ) -> None:
        assert pp.ROOMS[room][:4] == (opens, urn, chest, door)

    def test_the_last_room_has_no_doors_to_pick(self) -> None:
        # "If a player tries to pick the doors in the final room, they will
        # instead cause the player to exit the minigame."
        assert pp.ROOMS[8][3] == 0.0

    def test_the_third_room_is_one_urn_short(self) -> None:
        # "Every room contains exactly 13 lootable urns (bar the third room,
        # which contains one fewer)."
        assert pp.urns_in(3) == 12
        assert {pp.urns_in(room) for room in pp.ROOMS if room != 3} == {13}

    def test_a_room_opens_every_ten_levels(self) -> None:
        assert [pp.ROOMS[room][0] for room in sorted(pp.ROOMS)] == [
            21, 31, 41, 51, 61, 71, 81, 91
        ]


class TestTopRoom:
    @pytest.mark.parametrize(
        "level,room", [(1, 0), (20, 0), (21, 1), (30, 1), (31, 2), (90, 7), (91, 8), (99, 8)]
    )
    def test_the_deepest_room_a_level_reaches(self, level: int, room: int) -> None:
        assert pp.top_room(level) == room

    def test_below_the_first_room_there_is_no_game(self) -> None:
        assert pp.thieving_per_game(20) == 0.0
        assert pp.thieving_rate(20) == 0.0


class TestAgainstThePublishedRates:
    """**One fitted number, two rows fitted, the third held out.**

    This is the evidence for `OVERHEAD_SECONDS` and the reason these rates are
    `CONFIRMED`. If a change moves any of these three, it has changed what the
    model claims about the game rather than tidied it.
    """

    PUBLISHED = {6: 125_000.0, 7: 190_000.0, 8: 270_000.0}

    @pytest.mark.parametrize("room,published", sorted(PUBLISHED.items()))
    def test_it_reproduces_the_guide(self, room: int, published: float) -> None:
        got = pp.thieving_rate(pp.ROOMS[room][0])
        assert got == pytest.approx(published, rel=0.05)

    def test_the_two_fitted_rows_are_the_close_ones(self) -> None:
        # Rooms 6 and 7 imply 35.4s and 34.7s of overhead independently, which
        # is what makes one constant defensible; room 8 implies 21.2s and is
        # the residual the docstring explains.
        for room in (6, 7):
            got = pp.thieving_rate(pp.ROOMS[room][0])
            assert got == pytest.approx(self.PUBLISHED[room], rel=0.01)
        held_out = pp.thieving_rate(pp.ROOMS[8][0])
        assert 0.94 < held_out / self.PUBLISHED[8] < 1.0

    def test_the_rate_climbs_with_every_room(self) -> None:
        rates = [pp.thieving_rate(pp.ROOMS[room][0]) for room in sorted(pp.ROOMS)]
        assert rates == sorted(rates)

    def test_an_hour_is_ten_and_a_bit_games(self) -> None:
        assert pp.games_per_hour() == pytest.approx(3600.0 / 335.1)


class TestTheTimerIsNotBinding:
    """Why no cadence is chosen: the answer does not depend on one.

    The plan needs 72 actions at level 91, which is 4.2 seconds each inside a
    five-minute game. Any cadence quicker than that finishes it, so the rate is
    flat across the whole plausible range and there is nothing to guess.
    """

    def test_the_plan_fits_a_five_minute_game_at_a_sane_pace(self) -> None:
        level = 91
        top = pp.top_room(level)
        urn = success_chance(level, *pp.URN_CURVE)
        door = success_chance(level, *pp.DOOR_CURVE)
        attempts = 0.0
        for room in range(1, top + 1):
            attempts += 1.0                                   # spear trap
            if room < top:
                attempts += pp.DOORS_OPENED / door
            if room >= pp.CHEST_FROM_ROOM:
                attempts += 1.0
            if room > top - pp.URN_ROOMS:
                attempts += pp.urns_in(room) / urn
        assert 60 < attempts < 85
        seconds_each = pp.GAME_SECONDS / attempts
        assert seconds_each > 3 * 0.6, "the plan would not fit at a sane pace"


class TestStrength:
    """The half that cannot be had at the same time as the other half."""

    def test_a_sarcophagus_pays_strength_and_the_urns_do_not(self) -> None:
        assert pp.ROOMS[8][4] == 275.0
        assert pp.strength_per_game(91, 99) == pytest.approx(
            sum(pp.ROOMS[room][4] for room in range(1, 9))
        )

    def test_the_chart_gets_harder_the_deeper_it_goes(self) -> None:
        # The only chart in the project that does. Room 1 opens at 59 and room
        # 8 at -11, so a low-Strength player cannot open the deep ones at all.
        lows = [pp.SARCOPHAGUS_CURVES[room][0] for room in sorted(pp.ROOMS)]
        assert lows == sorted(lows, reverse=True)
        assert success_chance(1, *pp.SARCOPHAGUS_CURVES[8]) == 0.0

    def test_a_room_it_cannot_open_pays_nothing(self) -> None:
        deep = pp.strength_per_game(91, 1)
        assert deep < pp.strength_per_game(91, 99)

    def test_it_is_small_enough_never_to_be_a_method(self) -> None:
        # 9,884/hr at 99 in both, against combat's hundreds of thousands. It is
        # here so the activity is described, not because anybody should do it.
        assert pp.strength_rate(99, 99) < 12_000

    def test_the_level_decides_whether_not_how_much(self) -> None:
        # **A property worth pinning because it looks like a bug.** A
        # sarcophagus always pays when it opens, so a low Strength level buys
        # retries rather than a smaller reward - and the retries cost time this
        # module does not price. The level shows up only where the chart clamps
        # to no chance, which is rooms 7 and 8 at Strength 1.
        assert pp.strength_rate(91, 40) == pp.strength_rate(91, 99)
        assert pp.strength_rate(91, 1) < pp.strength_rate(91, 2)

    def test_the_two_skills_read_their_own_levels(self) -> None:
        assert pp.strength_per_game(91, 99) > pp.strength_per_game(41, 99)
        assert pp.thieving_per_game(91) > pp.thieving_per_game(41)


class TestReachability:
    _VALID: dict[str, dict[str, object]] = {
        "Thieving": {pp.TASKS[room]: {} for room in (1, 2, 3)}
    }

    def test_only_the_rooms_a_map_reaches_are_offered(self) -> None:
        found = pp.methods(self._VALID, 99)
        assert len(found["Thieving"]) == 3
        assert {band.level for band in found["Thieving"]} == {21, 31, 41}

    def test_nothing_at_all_when_the_pyramid_is_unreachable(self) -> None:
        assert pp.methods({}, 99) == {}

    def test_strength_rides_on_the_deepest_room_reached(self) -> None:
        found = pp.methods(self._VALID, 99)
        assert found["Strength"][0].xp_per_hour == pytest.approx(
            pp.strength_rate(41, 99)
        )

    def test_a_thieving_band_names_the_task_it_would_be_overridden_through(
        self,
    ) -> None:
        bands = pp.methods(self._VALID, 99)["Thieving"]
        assert all(band.knob.startswith("training/Access the ") for band in bands)

    def test_strength_has_no_knob_because_it_has_no_task(self) -> None:
        # The export models no Strength training for the minigame, so there is
        # nothing `overrides.json` could name.
        assert pp.methods(self._VALID, 99)["Strength"][0].knob == ""


class TestItIsWiredIn:
    """Neither cached map reaches the pyramid, so the wiring needs its own test.

    `fray` and `verf` both have the Pyramid Plunder area locked, which means
    every other check here exercises `methods` directly and nothing exercises
    the call in `costing/inputs.py`. This asserts the seam: that the module is
    reached, and that it is handed the **Strength** level rather than the
    Thieving one, which is the mistake the sarcophagus chart invites.
    """

    def test_inputs_hands_it_the_strength_level(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "pyramid_plunder.methods(" in source
        # **The mistake the sarcophagus chart invites.** Its curve is against
        # Strength and every other level in this activity is Thieving, so
        # handing the wrong one through would read as a plausible number.
        call = source.split("pyramid_plunder.methods(", 1)[1].split(")", 1)[0]
        assert 'at_level.get("Strength"' in call

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(
            pp.__file__
        ).with_name("__init__.py").read_text(encoding="utf-8")
        assert "`pyramid_plunder.py`" in listing
