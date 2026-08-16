"""Underwater Agility and Thieving: a parabola, and four figures that check it."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import swimming as sw


class TestTheParabola:
    """`Glistening tear` tabulates five levels; one coefficient makes them all."""

    #: (level, Agility alone, Thieving alone, Agility both, Thieving both)
    TABLE = [
        (25, 16.9, 61.9, 11.3, 41.3),
        (40, 43.2, 158.4, 28.8, 105.6),
        (60, 97.2, 356.4, 64.8, 237.6),
        (80, 172.8, 633.6, 115.2, 422.4),
        (99, 264.6, 970.2, 176.4, 646.8),
    ]

    @pytest.mark.parametrize("row", TABLE, ids=lambda row: f"lvl{row[0]}")
    def test_the_both_columns_come_out_of_the_coefficients(
        self, row: tuple[int, float, float, float, float]
    ) -> None:
        level, _alone_a, _alone_t, both_a, both_t = row
        # **The table is quoted to one decimal and does not round
        # consistently** - 16.875 is shown as 16.9 and 970.299 as 970.2 - so
        # the tolerance is a decimal place rather than a ratio. At level 25
        # that is 0.6% and at 99 it is 0.01%, which is why a relative one
        # cannot serve both ends.
        assert sw.experience_per_tear("Agility", level) == pytest.approx(
            both_a, abs=0.1
        )
        assert sw.experience_per_tear("Thieving", level) == pytest.approx(
            both_t, abs=0.1
        )

    @pytest.mark.parametrize("row", TABLE, ids=lambda row: f"lvl{row[0]}")
    def test_the_single_skill_columns_do_too(
        self, row: tuple[int, float, float, float, float]
    ) -> None:
        level, alone_a, alone_t, _both_a, _both_t = row
        assert sw.PER_TEAR_ALONE["Agility"] * level**2 == pytest.approx(
            alone_a, abs=0.1
        )
        assert sw.PER_TEAR_ALONE["Thieving"] * level**2 == pytest.approx(
            alone_t, abs=0.1
        )

    def test_both_is_two_thirds_of_alone(self) -> None:
        for skill in sw.PER_TEAR:
            assert sw.PER_TEAR[skill] == pytest.approx(
                sw.PER_TEAR_ALONE[skill] * 2.0 / 3.0
            )

    def test_it_is_quadratic_and_not_linear(self) -> None:
        # "the experience rates scale quadratically with the player's skill
        # levels" - doubling the level quadruples the tear.
        assert sw.experience_per_tear("Thieving", 80) == pytest.approx(
            sw.experience_per_tear("Thieving", 40) * 4.0
        )


class TestAgainstThePublishedRates:
    """**Four published figures, one `TEARS_PER_HOUR`.**"""

    @pytest.mark.parametrize(
        "skill,published", [("Agility", 38_800.0), ("Thieving", 142_300.0)]
    )
    def test_the_both_mode_hourly_figures(self, skill: str, published: float) -> None:
        turn_in = sw.experience_per_tear(skill, 99) * sw.TEARS_PER_HOUR
        assert turn_in == pytest.approx(published, rel=0.001)

    @pytest.mark.parametrize(
        "skill,published", [("Agility", 58_200.0), ("Thieving", 213_400.0)]
    )
    def test_the_single_mode_figures_check_the_same_tear_count(
        self, skill: str, published: float
    ) -> None:
        # Not priced, but they are what makes 220 tears an hour a measurement
        # rather than a pick from the page's "roughly 170-230".
        alone = sw.PER_TEAR_ALONE[skill] * 99**2 * sw.TEARS_PER_HOUR
        assert alone == pytest.approx(published, rel=0.001)

    def test_the_tear_count_sits_inside_the_published_range(self) -> None:
        assert 170.0 <= sw.TEARS_PER_HOUR <= 230.0


class TestTheSearching:
    def test_a_search_pays_both_skills(self) -> None:
        assert sw.SEARCH_EXPERIENCE == 4.5

    def test_it_is_added_on_top_of_the_turn_in(self) -> None:
        turn_in = sw.experience_per_tear("Thieving", 99) * sw.TEARS_PER_HOUR
        assert sw.rate_at("Thieving", 99) > turn_in
        assert sw.rate_at("Thieving", 99) - turn_in == pytest.approx(
            sw.SEARCH_EXPERIENCE * sw.TEARS_PER_HOUR
        )

    def test_it_is_the_whole_rate_at_level_one(self) -> None:
        # The shape a flat term takes under a parabola: everything at 1, a
        # fifth of a percent at 99.
        flat = sw.SEARCH_EXPERIENCE * sw.TEARS_PER_HOUR
        assert sw.rate_at("Agility", 1) == pytest.approx(flat, rel=0.01)
        assert sw.rate_at("Thieving", 99) / flat > 100


class TestOneHourCountedOnce:
    """The reason the slower exchange is the one priced."""

    def test_the_priced_mode_is_the_one_that_is_true_twice(self) -> None:
        # Pricing the single-skill exchanges would let the estimate spend the
        # same hour in both columns.
        for skill in sw.PER_TEAR:
            assert sw.PER_TEAR[skill] < sw.PER_TEAR_ALONE[skill]

    def test_each_skill_reads_only_its_own_level(self) -> None:
        assert sw.rate_at("Agility", 99) != sw.rate_at("Thieving", 99)
        assert sw.rate_at("Cooking", 99) == 0.0


class TestReachability:
    _VALID: dict[str, dict[str, object]] = {
        skill: {task: {}} for skill, task in sw.TASKS.items()
    }

    def test_both_skills_when_the_area_is_reachable(self) -> None:
        assert set(sw.methods(self._VALID)) == {"Agility", "Thieving"}

    def test_nothing_when_it_is_not(self) -> None:
        assert sw.methods({}) == {}

    def test_one_skill_alone_is_offered_alone(self) -> None:
        assert set(sw.methods({"Thieving": self._VALID["Thieving"]})) == {"Thieving"}

    def test_it_is_banded_because_a_parabola_needs_it(self) -> None:
        bands = sw.methods(self._VALID)["Thieving"]
        rates = [band.xp_per_hour for band in bands]
        assert len(bands) > 5
        assert rates == sorted(rates)
        assert rates[-1] / rates[0] > 100

    def test_a_band_names_the_task_it_would_be_overridden_through(self) -> None:
        for skill, bands in sw.methods(self._VALID).items():
            assert all(band.knob == f"training/{sw.TASKS[skill]}/{skill}" for band in bands)


class TestItIsWiredIn:
    """Neither cached map has the area, so the seam needs its own test."""

    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "swimming.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(sw.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`swimming.py`" in listing
