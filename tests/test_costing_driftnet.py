"""`costing/driftnet.py`: two skills, and a ceiling at 70."""

from __future__ import annotations

import pytest

from chunksim.costing import driftnet
from chunksim.costing.gathering import Tables

TABLES = Tables(
    drift_net={
        44: (60145.0, 53130.0),
        50: (71875.0, 57500.0),
        60: (93150.0, 72450.0),
        70: (116725.0, 88550.0),
    }
)
VALID = {skill: {driftnet.DRIFT_NET_TASK: True} for skill in driftnet.DRIFT_NET_SKILLS}


class TestRate:
    def test_it_takes_the_last_row_at_or_below_the_level(self) -> None:
        assert driftnet.rate_at(TABLES, "Hunter", 55) == 71875.0

    def test_below_the_requirement_it_pays_nothing(self) -> None:
        assert driftnet.rate_at(TABLES, "Hunter", 43) == 0.0

    def test_it_stops_scaling_at_seventy(self) -> None:
        # A fact about the activity, not a gap in the table - so the climb is
        # flat above it where every other method here keeps rising.
        assert driftnet.rate_at(TABLES, "Hunter", 99) == driftnet.rate_at(
            TABLES, "Hunter", 70
        )

    def test_the_two_skills_are_paid_differently(self) -> None:
        assert driftnet.rate_at(TABLES, "Hunter", 70) > driftnet.rate_at(
            TABLES, "Fishing", 70
        )

    def test_a_skill_it_does_not_pay_earns_nothing(self) -> None:
        assert driftnet.rate_at(TABLES, "Woodcutting", 99) == 0.0


class TestMethods:
    def test_both_skills_get_a_climb(self) -> None:
        assert set(driftnet.methods(TABLES, VALID)) == {"Hunter", "Fishing"}

    def test_only_the_skills_the_map_holds_it_under(self) -> None:
        assert set(driftnet.methods(TABLES, {"Fishing": {driftnet.DRIFT_NET_TASK: True}})) == {
            "Fishing"
        }

    def test_the_first_band_opens_at_the_requirement(self) -> None:
        assert min(m.level or 0 for m in driftnet.methods(TABLES, VALID)["Hunter"]) == 44

    def test_a_map_without_the_activity_gets_nothing(self) -> None:
        assert driftnet.methods(TABLES, {"Hunter": {}}) == {}

    def test_no_table_prices_nothing(self) -> None:
        assert driftnet.methods(Tables(), VALID) == {}
