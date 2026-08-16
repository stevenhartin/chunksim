"""Stealing valuables: the four checks that make a transcription worth having."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import valuables as v


class TestTheFourChecks:
    """**The reason a copied table is evidence here.**

    Nothing in the burgling loop is charted, so the table cannot be derived -
    but the same page states the activity four other ways, and each of them
    lands on it. If a future edit moves the table, these say which of the five
    statements it now disagrees with.
    """

    @pytest.mark.parametrize(
        "level,valuables", [(50, 1_600.0), (99, 2_333.0)]
    )
    def test_forty_five_a_valuable_gives_the_stated_haul(
        self, level: int, valuables: float
    ) -> None:
        # "players can expect to obtain about 1,600-2,300 valuables" an hour.
        assert v.rate_at(level) / v.VALUABLE_EXPERIENCE == pytest.approx(
            valuables, abs=1.0
        )
        assert 1_600.0 <= v.rate_at(level) / v.VALUABLE_EXPERIENCE <= 2_400.0

    @pytest.mark.parametrize("level,per_key", [(50, 3_900.0), (99, 5_700.0)])
    def test_one_key_a_house_gives_the_stated_key_value(
        self, level: int, per_key: float
    ) -> None:
        # "each key giving around 3900xp at level 50 and 5700xp at level 99".
        assert v.rate_at(level) / v.HOUSES_PER_HOUR == pytest.approx(
            per_key, rel=0.01
        )

    def test_the_house_cycle_gives_the_stated_house_count(self) -> None:
        # "the homeowner will return 180-190 seconds after they left", and
        # "18-19 houses per hour" - two statements, one number.
        assert 3600.0 / 190.0 <= 19.0
        assert 18.0 <= v.HOUSES_PER_HOUR <= 20.0

    def test_the_tables_ends_are_the_prose_range(self) -> None:
        # "Roughly 70,000-105,000 Thieving experience can be gained per hour".
        assert v.EXPERIENCE_PER_HOUR[-1][1] == 105_000.0
        assert 70_000.0 <= v.EXPERIENCE_PER_HOUR[0][1] <= 105_000.0


class TestTheCurve:
    def test_it_is_the_published_six_points(self) -> None:
        assert v.EXPERIENCE_PER_HOUR == (
            (50, 72_000.0), (60, 80_000.0), (70, 93_000.0),
            (80, 95_000.0), (90, 100_000.0), (99, 105_000.0),
        )

    def test_it_never_goes_backwards(self) -> None:
        rates = [paid for _level, paid in v.EXPERIENCE_PER_HOUR]
        assert rates == sorted(rates)

    def test_a_point_holds_until_the_next(self) -> None:
        assert v.rate_at(59) == 72_000.0
        assert v.rate_at(60) == 80_000.0
        assert v.rate_at(99) == 105_000.0

    def test_nothing_below_the_gate(self) -> None:
        # Every object's infobox states level 50, and so does the export.
        assert v.OPENS_AT == 50
        assert v.rate_at(49) == 0.0
        assert v.rate_at(1) == 0.0
        assert v.rate_at(50) > 0.0


class TestWhatIsNotInIt:
    def test_the_shiny_bonus_is_inside_the_table(self) -> None:
        # "as long as very few to no flashing arrows are missed" - the table is
        # measured with them, so adding 630 on top would count them twice.
        assert v.SHINY_EXPERIENCE == 630.0
        assert v.rate_at(99) == 105_000.0

    def test_the_pickpocketing_is_not(self) -> None:
        # The figures are "exclusively from the burgling portion". Getting keys
        # means pickpocketing wealthy citizens, which the node walk prices
        # separately - the same hour, and the band walk takes the better rather
        # than the sum.
        assert v.rate_at(99) < 137_501.0


class TestReachability:
    _VALID: dict[str, dict[str, object]] = {"Thieving": {v.TASK: {}}}

    def test_it_is_offered_where_the_task_is_valid(self) -> None:
        bands = v.methods(self._VALID)["Thieving"]
        assert len(bands) == len(v.EXPERIENCE_PER_HOUR)
        assert [band.level for band in bands] == [50, 60, 70, 80, 90, 99]

    def test_nothing_when_it_is_not(self) -> None:
        assert v.methods({}) == {}
        assert v.methods({"Thieving": {}}) == {}

    def test_upstream_names_it_by_region_not_by_activity(self) -> None:
        # The wiki article is `Stealing valuables`; the export says
        # `Varlamore thieving`. Worth pinning, because the name is the only
        # thing joining them and nothing else in the project would notice.
        assert v.TASK == "Participate in ~|Varlamore thieving|~"

    def test_a_band_names_the_task_it_would_be_overridden_through(self) -> None:
        for band in v.methods(self._VALID)["Thieving"]:
            assert band.knob == f"training/{v.TASK}/Thieving"


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "valuables.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(v.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`valuables.py`" in listing
