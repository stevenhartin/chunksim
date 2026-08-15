"""`costing/herbiboar.py`: a puzzle priced as a table times a constant."""

from __future__ import annotations

import pytest

from chunksim.costing import herbiboar
from chunksim.costing.gathering import Tables

TABLES = Tables(herbiboar_xp={80: 1950.0, 90: 2250.0, 99: 2461.0})
VALID = {"Hunter": {herbiboar.HERBIBOAR_TASK: True}}


class TestExperience:
    def test_a_published_level_is_a_lookup(self) -> None:
        assert herbiboar.experience_at(TABLES.herbiboar_xp, 80) == 1950.0

    def test_a_level_the_table_does_not_cover_pays_nothing(self) -> None:
        # Interpolating between two published figures would be a guess wearing
        # a citation; the real table is exhaustive from 74 to 99.
        assert herbiboar.experience_at(TABLES.herbiboar_xp, 85) == 0.0


class TestMethods:
    def test_the_rate_is_the_table_times_the_catch_rate(self) -> None:
        (found,) = herbiboar.methods(TABLES, VALID).values()
        by_level = {method.level or 0: method.xp_per_hour for method in found}
        assert by_level[99] == pytest.approx(2461.0 * herbiboar.CATCHES_PER_HOUR)

    def test_it_climbs_with_level_where_the_guide_was_flat(self) -> None:
        # The whole reason this exists: the scraped figure is one number across
        # twenty levels over which a catch pays 26% more.
        (found,) = herbiboar.methods(TABLES, VALID).values()
        rates = [method.xp_per_hour for method in sorted(found, key=lambda m: m.level or 0)]
        assert rates == sorted(rates)
        assert rates[-1] > rates[0]

    def test_it_never_opens_below_the_challenges_level(self) -> None:
        (found,) = herbiboar.methods(TABLES, VALID).values()
        assert min(method.level or 0 for method in found) == herbiboar.HERBIBOAR_OPENS

    def test_a_map_without_the_island_gets_nothing(self) -> None:
        assert herbiboar.methods(TABLES, {"Hunter": {}}) == {}

    def test_no_table_prices_nothing(self) -> None:
        assert herbiboar.methods(Tables(), VALID) == {}

    def test_it_stays_out_of_the_node_model(self) -> None:
        # There is no chance, no interval and no tool here, so nothing about
        # herbiboar belongs in a `SkillProfile`.
        from chunksim.costing.gathering import PROFILES

        profile = PROFILES["Hunter"]
        assert "Tracking" not in profile.roll_ticks_by_kind
        assert "herbiboar" not in profile.fixed_chances
