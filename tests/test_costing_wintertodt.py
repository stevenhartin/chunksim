"""Wintertodt: the wiki's multipliers, and the loop they are counted over."""

from __future__ import annotations

import pytest

from chunksim.costing import wintertodt


class TestTheWikisOwnTable:
    """Four rows of it, and each is asserted where it is spent."""

    @pytest.mark.parametrize(
        "skill,multiplier",
        [("Woodcutting", 0.3), ("Fletching", 0.6), ("Firemaking", 3.8)],
    )
    def test_a_multiplier_is_the_table_s(self, skill: str, multiplier: float) -> None:
        assert wintertodt.ACTIONS[skill][1] == multiplier

    def test_the_subdual_bonus_pays_firemaking_alone(self) -> None:
        # "Succeeding in subduing the Wintertodt with a minimum of 500 points
        # will reward players with Firemaking experience (Firemaking level *
        # 100)." Woodcutting and Fletching earn nothing for the kill.
        assert wintertodt.SUBDUAL_SKILL == "Firemaking"
        assert wintertodt.SUBDUAL_MULTIPLIER == 100.0
        assert wintertodt.experience_per_game(
            "Woodcutting", 99
        ) == pytest.approx(20 * 0.3 * 99)


class TestOneGame:
    """The worked example, at 99 in all three."""

    @pytest.mark.parametrize(
        "skill,paid",
        [("Woodcutting", 594.0), ("Fletching", 1188.0), ("Firemaking", 17424.0)],
    )
    def test_a_game_pays_what_the_arithmetic_says(self, skill: str, paid: float) -> None:
        assert wintertodt.experience_per_game(skill, 99) == pytest.approx(paid)

    def test_firemaking_is_the_kindling_and_the_bonus(self) -> None:
        # 7,524 from twenty kindling and 9,900 for the subdual - and the second
        # is why hopping beats staying, since a longer game earns the same.
        assert wintertodt.experience_per_game("Firemaking", 99) == pytest.approx(
            20 * 3.8 * 99 + 100 * 99
        )

    def test_twenty_kindling_is_the_point_cap(self) -> None:
        # 25 points each, so twenty is exactly the 500 the reward caps at.
        assert wintertodt.KINDLING_PER_GAME * 25 == 500


class TestAnHour:
    @pytest.mark.parametrize(
        "skill,rate",
        [
            ("Woodcutting", 14256.0),
            ("Fletching", 28512.0),
            ("Firemaking", 418176.0),
        ],
    )
    def test_the_hour_at_99(self, skill: str, rate: float) -> None:
        assert wintertodt.rate_at(skill, 99) == pytest.approx(rate)

    def test_every_skill_is_linear_in_its_own_level(self) -> None:
        # Which is what makes these three independent curves and why nothing
        # here has to be told what else the player has trained.
        for skill in wintertodt.ACTIONS:
            assert wintertodt.rate_at(skill, 50) == pytest.approx(
                wintertodt.rate_at(skill, 100) / 2
            )

    def test_it_reads_no_other_skills_level(self) -> None:
        assert wintertodt.rate_at("Woodcutting", 99) != pytest.approx(
            wintertodt.rate_at("Firemaking", 99)
        )


class TestReachability:
    """Upstream's gate, one challenge per skill."""

    _VALID: dict[str, dict[str, object]] = {
        "Woodcutting": {"Chop ~|bruma roots|~": {}},
        "Fletching": {"Fletch ~|bruma kindling|~": {}},
        "Firemaking": {"Burn wood at ~|Wintertodt|~": {}},
    }

    def test_all_three_when_all_three_are_valid(self) -> None:
        found = wintertodt.methods(self._VALID)
        assert set(found) == {"Woodcutting", "Fletching", "Firemaking"}

    def test_a_skill_whose_task_is_unreachable_is_not_offered(self) -> None:
        found = wintertodt.methods({"Firemaking": self._VALID["Firemaking"]})
        assert set(found) == {"Firemaking"}

    def test_nothing_at_all_when_the_boss_is_unreachable(self) -> None:
        assert wintertodt.methods({}) == {}

    def test_it_is_banded_rather_than_one_number(self) -> None:
        # The defect it replaced: 400,000/hr was right at 99 and half wrong at
        # 50, where Firemaking opens the boss.
        bands = wintertodt.methods(self._VALID)["Firemaking"]
        assert len(bands) > 1
        assert {band.level for band in bands} >= {1, 50, 99}
        rates = [band.xp_per_hour for band in bands]
        assert rates == sorted(rates)

    def test_a_band_points_at_the_task_it_would_be_overridden_through(self) -> None:
        bands = wintertodt.methods(self._VALID)["Woodcutting"]
        assert all(
            band.knob == "training/Chop ~|bruma roots|~/Woodcutting" for band in bands
        )
