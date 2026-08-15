"""`costing/aerial.py`: one action, two skills, no failure.

The formula and both anchors are the wiki's, so the tests are about the shape -
which fish a level buys, and that a task belonging to two skills keeps both
rates - plus the two ends the training guide states independently.
"""

from __future__ import annotations

import pytest

from chunksim.costing import aerial
from chunksim.costing.gathering import Tables

FISH = (
    ("Bluegill", 43, 11.5, 35, 16.5),
    ("Common tench", 56, 40.0, 51, 45.0),
    ("Mottled eel", 73, 65.0, 68, 90.0),
    ("Greater siren", 91, 100.0, 87, 130.0),
)
TABLES = Tables(aerial_fish=FISH)
VALID = {
    skill: {f"Catch a ~|{name.lower()}|~": True for name, *_ in FISH}
    for skill in ("Fishing", "Hunter")
}


class TestMix:
    def test_below_the_first_requirement_nothing_is_caught(self) -> None:
        assert aerial.catch_mix(FISH, 42, 35) == {}

    def test_the_opening_level_catches_only_bluegill(self) -> None:
        assert aerial.catch_mix(FISH, 43, 43) == {"Bluegill": 1.0}

    def test_better_levels_buy_better_fish_not_a_better_chance(self) -> None:
        mix = aerial.catch_mix(FISH, 99, 99)
        assert set(mix) == {"Bluegill", "Common tench", "Mottled eel", "Greater siren"}
        # X = 99, so the thresholds carve it exactly: 82+ siren is 17 of 99.
        assert mix["Greater siren"] == pytest.approx(17 / 99)
        assert mix["Bluegill"] == pytest.approx(52 / 99)

    def test_a_fish_rolled_but_not_yet_catchable_falls_through(self) -> None:
        # "Small values above the requirements give a very small chance for
        # newly unlocked fish" - the roll can reach 82 before the levels do.
        mix = aerial.catch_mix(FISH, 88, 88)
        assert "Greater siren" not in mix
        assert mix["Mottled eel"] > 0

    def test_the_roll_ceiling_weights_fishing_twice(self) -> None:
        # Mod Ash: X = (Fishing x 2 + Hunter) / 3, which is why the page notes
        # a Fishing boost is worth more than the same Hunter one.
        assert aerial.roll_ceiling(99, 60) > aerial.roll_ceiling(60, 99)


class TestRates:
    def _at(self, skill: str, level: int) -> float:
        mix = aerial.catch_mix(FISH, level, level)
        return aerial.experience_per_catch(FISH, mix, skill) * aerial.CATCHES_PER_HOUR

    def test_it_reproduces_the_guides_low_end(self) -> None:
        # "between 25,000-80,000 Hunter experience per hour"
        assert self._at("Hunter", 43) == pytest.approx(26_400, rel=0.06)

    def test_it_reproduces_the_guides_high_end(self) -> None:
        assert self._at("Hunter", 99) == pytest.approx(80_000, rel=0.04)

    def test_a_catch_never_fails(self) -> None:
        # "Unlike Falconry, a catch is guaranteed each time the bird is sent."
        for rate in aerial.methods(TABLES, VALID)["Catch a ~|bluegill|~"]:
            assert rate.chance == 1.0


class TestMethods:
    def test_one_task_carries_both_skills(self) -> None:
        # The export names `Catch a ~|bluegill|~` under Fishing and under
        # Hunter; keying by task alone lost one of them.
        rates = aerial.methods(TABLES, VALID)["Catch a ~|bluegill|~"]
        assert {rate.skill for rate in rates} == {"Fishing", "Hunter"}

    def test_every_task_prices_the_same_action(self) -> None:
        found = aerial.methods(TABLES, VALID)
        tops = {
            task: max(r.xp_per_hour for r in rates if r.skill == "Hunter")
            for task, rates in found.items()
        }
        assert len(set(round(value, 6) for value in tops.values())) == 1

    def test_it_opens_where_both_requirements_are_met(self) -> None:
        rates = aerial.methods(TABLES, VALID)["Catch a ~|bluegill|~"]
        assert min(rate.level for rate in rates) == 43

    def test_a_map_with_no_aerial_challenge_gets_nothing(self) -> None:
        assert aerial.methods(TABLES, {"Fishing": {}, "Hunter": {}}) == {}

    def test_no_table_prices_nothing(self) -> None:
        assert aerial.methods(Tables(), VALID) == {}
