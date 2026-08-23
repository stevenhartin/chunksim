"""`costing/chambers.py`: the best bat two levels allow."""

from __future__ import annotations

import pytest

from chunksim.costing import chambers
from chunksim.costing.gathering import Tables

BATS = chambers.FAMILIES[0]
FISH = chambers.FAMILIES[1]

TABLES = Tables(
    skill_info={"Hunter": {
        "raw guanic bat (0)": (1, 5.0),
        "raw prael bat (1)": (15, 9.0),
        "raw giral bat (2)": (30, 13.0),
        "raw phluxia bat (3)": (45, 17.0),
        "raw kryket bat (4)": (60, 21.0),
        "raw murng bat (5)": (75, 25.0),
        "raw psykk bat (6)": (90, 29.0),
    },
    "Fishing": {
        "raw pysk fish (0)": (1, 20.0),
        "raw kyren fish (6)": (90, 38.0),
    }}
)
VALID = {
    "Hunter": {f"Catch a ~|{name}|~": True for name, _page in BATS.members},
    "Fishing": {f"Catch a ~|{name}|~": True for name, _page in FISH.members},
}


class TestBestBat:
    def test_the_catching_level_alone_decides(self) -> None:
        """**One skill, not two.** `Psykk bat` states "they require a Hunter
        level of 90 **to catch** ... Once caught, raw psykk bats can be
        **cooked** ... requiring a Cooking level of 90" - two requirements for
        two actions, which this module used to read as a compound gate."""
        assert chambers.best(TABLES, BATS, 89) == ("murng bat", 25.0)
        assert chambers.best(TABLES, BATS, 99) == ("psykk bat", 29.0)

    def test_ninety_reaches_the_best(self) -> None:
        assert chambers.best(TABLES, BATS, 90) == ("psykk bat", 29.0)

    def test_a_low_level_caps_the_climb(self) -> None:
        assert chambers.best(TABLES, BATS, 44) == ("giral bat", 13.0)

    def test_cooking_does_not_hold_the_catch_back(self) -> None:
        """The regression this replaced: a map whose Cooking lagged got no
        band for the higher tiers at all, so their challenges had no knob and
        read `unpriced` - "nothing reached this" about a method this module
        prices exactly."""
        assert chambers.best(TABLES, BATS, 99) == ("psykk bat", 29.0)

    def test_nothing_at_all_below_the_first(self) -> None:
        assert chambers.best(Tables(), BATS, 99) is None

    def test_the_fish_ladder_works_the_same_way(self) -> None:
        assert chambers.best(TABLES, FISH, 90) == ("kyren fish", 38.0)
        assert chambers.best(TABLES, FISH, 20) == ("pysk fish", 20.0)


class TestMethods:
    def test_four_ticks_is_fifteen_hundred_an_hour(self) -> None:
        assert chambers.catches_per_hour() == 1500.0

    def test_the_top_tier_is_its_experience_times_that(self) -> None:
        found = chambers.methods(TABLES, VALID)["Hunter"]
        assert max(m.xp_per_hour for m in found) == pytest.approx(29.0 * 1500.0)

    def test_the_climb_steps_through_the_tiers(self) -> None:
        found = chambers.methods(TABLES, VALID)["Hunter"]
        assert [m.method for m in found if (m.level or 0) in (1, 30, 60, 90)] == [
            "guanic bat",
            "giral bat",
            "kryket bat",
            "psykk bat",
        ]

    def test_every_reachable_tier_gets_a_band(self) -> None:
        """**Which is what the report needs.** A tier with no band has no
        knob, and a challenge with no knob reads `unpriced` however well this
        module knows how to price it."""
        found = chambers.methods(TABLES, VALID)["Hunter"]
        knobs = {m.knob for m in found}

        assert knobs == {
            f"training/Catch a ~|{name}|~/Hunter" for name, _page in BATS.members
        }

    def test_a_map_that_cannot_reach_the_raid_gets_nothing(self) -> None:
        assert chambers.methods(TABLES, {"Hunter": {}}) == {}

    def test_only_the_tiers_the_map_holds_are_offered(self) -> None:
        one = {"Hunter": {"Catch a ~|guanic bat|~": True}}
        found = chambers.methods(TABLES, one)["Hunter"]
        assert {m.method for m in found} == {"guanic bat"}
