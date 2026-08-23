"""The generic sequencer: a run of fights and puzzles, priced as one unit."""

from __future__ import annotations

import math

import pytest

from chunksim.costing import encounter
from chunksim.costing.encounter import (
    FightPlan,
    Mechanic,
    Objective,
    PuzzlePlan,
)

_TIMES = {"boss": 100.0, "adds": 20.0}


def _seconds(target: str) -> float | None:
    return _TIMES.get(target)


class TestBuildingARun:
    def test_fights_and_puzzles_sum(self) -> None:
        run = encounter.build(
            "r", [FightPlan("a", "boss"), PuzzlePlan("maze", 30.0)], _seconds
        )
        assert run is not None
        assert run.seconds == 130.0

    def test_a_room_holding_several_multiplies(self) -> None:
        run = encounter.build("r", [FightPlan("a", "adds", count=4)], _seconds)
        assert run is not None and run.seconds == 80.0

    def test_one_unpriceable_fight_drops_the_whole_run(self) -> None:
        """**All or nothing.** A raid missing one room's duration is not a
        raid that takes slightly less time - `costing/crane.py`'s refusal one
        layer up, and the hole would otherwise be invisible."""
        assert encounter.build("r", [FightPlan("a", "nobody")], _seconds) is None

    def test_points_come_along(self) -> None:
        run = encounter.build(
            "r", [FightPlan("a", "boss", points=5), PuzzlePlan("p", 1.0, points=2)],
            _seconds,
        )
        assert run is not None and run.points == 7.0


class TestMechanics:
    def test_uptime_divides_the_kill_and_idle_does_not(self) -> None:
        """Two numbers because a fight is not a damage race: a phase the boss
        spends immune scales with the kill, a walk to the next platform does
        not."""
        assert Mechanic(uptime=0.5).seconds(100.0) == 200.0
        assert Mechanic(idle_seconds=30.0).seconds(100.0) == 130.0
        assert Mechanic(uptime=0.5, idle_seconds=30.0).seconds(100.0) == 230.0

    def test_an_unknown_target_is_a_plain_damage_race(self) -> None:
        run = encounter.build("r", [FightPlan("a", "boss")], _seconds, {})
        assert run is not None and run.seconds == 100.0


class TestTheParty:
    def test_attackers_divide_the_kill_only(self) -> None:
        """**The line between a party helping and a party making a raid
        free.** Three players halve a health bar; they do not halve a maze or
        a phase the boss spends invulnerable."""
        run = encounter.build(
            "r",
            [FightPlan("a", "boss"), PuzzlePlan("maze", 30.0)],
            _seconds,
            {"boss": Mechanic(idle_seconds=12.0)},
            attackers=4,
        )
        assert run is not None
        assert run.seconds == 100.0 / 4 + 12.0 + 30.0

    def test_no_attackers_is_no_run(self) -> None:
        assert encounter.build("r", [FightPlan("a", "boss")], _seconds, attackers=0) is None


class TestObjectives:
    def test_the_default_is_the_whole_log(self) -> None:
        """A unique is a means to a collection log, and experience is a
        by-product - so the goal a chunk map actually has is the default."""
        assert encounter.FULL_LOG.kind == encounter.GREEN_LOG

    def test_a_unique_objective_must_name_one(self) -> None:
        with pytest.raises(ValueError):
            Objective(kind=encounter.UNIQUE)
        assert Objective.for_unique("Scythe").item == "Scythe"


class TestExpectations:
    def test_one_drop_is_its_own_reciprocal(self) -> None:
        assert encounter.expected_runs(0.1) == 10.0
        assert encounter.expected_runs(0.0) == math.inf

    def test_the_green_log_is_not_the_slowest_item(self) -> None:
        """**Coupon collector, and neither of the two obvious answers.** The
        others are still being collected while the rarest is awaited, so the
        total is more than any one expectation and far less than their sum."""
        chances = [0.1, 0.1, 0.02]
        every = encounter.runs_for_all(chances)
        assert every > max(1 / p for p in chances)
        assert every < sum(1 / p for p in chances)

    def test_equal_chances_reproduce_the_harmonic_form(self) -> None:
        """With `n` equally likely coupons at `p` each the answer is
        `(1/p) * H(n)`, which is the closed form worth checking against."""
        n, p = 4, 0.05
        harmonic = sum(1 / k for k in range(1, n + 1))
        assert encounter.runs_for_all([p] * n) == pytest.approx(harmonic / p)

    def test_an_impossible_drop_never_closes_the_log(self) -> None:
        assert encounter.runs_for_all([0.1, 0.0]) == math.inf
