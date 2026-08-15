"""`costing/bats.py`: the best bat two levels allow."""

from __future__ import annotations

import pytest

from chunksim.costing import bats
from chunksim.costing.gathering import Tables

TABLES = Tables(
    hunter_info={
        "raw guanic bat (0)": (1, 5.0),
        "raw prael bat (1)": (15, 9.0),
        "raw giral bat (2)": (30, 13.0),
        "raw phluxia bat (3)": (45, 17.0),
        "raw kryket bat (4)": (60, 21.0),
        "raw murng bat (5)": (75, 25.0),
        "raw psykk bat (6)": (90, 29.0),
    }
)
VALID = {"Hunter": {f"Catch a ~|{name}|~": True for name, _page in bats.BATS}}


class TestBestBat:
    def test_the_lower_of_the_two_levels_decides(self) -> None:
        # "99 hunter and 89 cooking" is a level-89 bat hunter.
        assert bats.best_bat(TABLES, 99, 89) == ("murng bat", 25.0)
        assert bats.best_bat(TABLES, 89, 99) == ("murng bat", 25.0)

    def test_both_at_ninety_reaches_the_best(self) -> None:
        assert bats.best_bat(TABLES, 90, 90) == ("psykk bat", 29.0)

    def test_a_low_cooking_caps_the_whole_climb(self) -> None:
        assert bats.best_bat(TABLES, 99, 44) == ("giral bat", 13.0)

    def test_nothing_at_all_below_the_first(self) -> None:
        assert bats.best_bat(Tables(), 99, 99) is None


class TestMethods:
    def test_four_ticks_is_fifteen_hundred_an_hour(self) -> None:
        assert bats.catches_per_hour() == 1500.0

    def test_the_top_tier_is_its_experience_times_that(self) -> None:
        (found,) = bats.methods(TABLES, VALID, 99).values()
        assert max(m.xp_per_hour for m in found) == pytest.approx(29.0 * 1500.0)

    def test_the_climb_steps_through_the_tiers(self) -> None:
        (found,) = bats.methods(TABLES, VALID, 99).values()
        assert [m.method for m in found if (m.level or 0) in (1, 30, 60, 90)] == [
            "guanic bat",
            "giral bat",
            "kryket bat",
            "psykk bat",
        ]

    def test_a_capped_cooking_flattens_the_top(self) -> None:
        (found,) = bats.methods(TABLES, VALID, 60).values()
        top = [m for m in found if (m.level or 0) >= 60]
        assert {m.method for m in top} == {"kryket bat"}

    def test_a_map_that_cannot_reach_the_raid_gets_nothing(self) -> None:
        assert bats.methods(TABLES, {"Hunter": {}}, 99) == {}

    def test_only_the_tiers_the_map_holds_are_offered(self) -> None:
        one = {"Hunter": {"Catch a ~|guanic bat|~": True}}
        (found,) = bats.methods(TABLES, one, 99).values()
        assert {m.method for m in found} == {"guanic bat"}
