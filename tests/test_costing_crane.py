"""Repairing a Port Piscarilius fishing crane, which pays two skills at once."""

from __future__ import annotations

import pytest

from chunksim.costing import crane


class TestTheCurveIsTheWikisOwn:
    """The `{{Skilling success chart}}` parameters and the page's prose are two
    separate statements, and `gathering.success_chance` turns the first into
    the second - nothing here was tuned to make that happen."""

    def test_it_reproduces_the_published_range(self) -> None:
        """"ranging from approximately 20% at level 30 to 30% at level 99"."""
        assert crane.chance(30) == pytest.approx(0.20, abs=0.005)
        assert crane.chance(99) == pytest.approx(0.30, abs=0.005)

    def test_below_the_requirement_reads_the_requirement(self) -> None:
        """Upstream's own `Level` and the chart's `req1` agree on 30, so there
        is no curve below it to read."""
        assert crane.chance(1) == crane.chance(crane.OPENS_AT)


class TestOneSuccessIsOneRepair:
    """"At least nine nails are required" reads as nine placements and is not:
    the crane "is fixed on the same tick they made the attempt", and the nine
    nails are the price of that one success rather than its length."""

    def test_attempts_are_the_geometric_mean(self) -> None:
        assert crane.attempts_per_repair(99) == pytest.approx(1 / crane.chance(99))

    def test_nine_nails_plus_one_per_failure(self) -> None:
        """"Each failed attempt will lead to one nail being bent" - and the
        successful attempt is not a failure, hence the minus one."""
        expected = crane.NAILS_PER_REPAIR + (crane.attempts_per_repair(70) - 1.0)
        assert crane.nails_per_repair(70) == pytest.approx(expected)

    def test_the_bent_nails_are_never_negative(self) -> None:
        """The real curve never reaches certainty, but the `max(..., 0)` is
        what stops a hypothetical `p == 1` bending minus one nail."""
        assert crane.nails_per_repair(99) > crane.NAILS_PER_REPAIR
        assert crane.NAILS_PER_REPAIR == 9.0
        assert crane.PLANKS_PER_REPAIR == 3.0

    def test_ten_ticks_an_attempt(self) -> None:
        """"made on the first tick, and then every ten ticks thereafter"."""
        assert crane.repair_seconds(99) == pytest.approx(
            crane.attempts_per_repair(99) * 10.0 * 0.6
        )


class TestTheTwoSkillsAreIndependent:
    """The experience scales on the skill being paid and the chance on the
    higher of the two, so they are the same number only when the levels are."""

    def test_experience_is_four_times_the_paid_skills_level(self) -> None:
        """At 30 Crafting and 40 Construction the wiki says 120 and 160."""
        # Same gate either way, so the ratio is purely the experience.
        assert crane.rate_at(40, 40) / crane.rate_at(30, 40) == pytest.approx(160 / 120)

    def test_the_chance_reads_the_higher_level(self) -> None:
        """A level-30 Construction climber with 99 Crafting rolls the level-99
        curve, which is what "whichever is higher" means."""
        assert crane.rate_at(30, 99) > crane.rate_at(30, 30)

    def test_a_band_opens_at_the_requirement(self) -> None:
        valid = {"Construction": {crane.TASK: True}, "Crafting": {crane.TASK: True}}

        found = crane.methods(valid, {"Construction": 99, "Crafting": 99})

        assert set(found) == {"Construction", "Crafting"}
        assert min(band.level or 0 for band in found["Construction"]) == crane.OPENS_AT

    def test_a_skill_whose_task_is_unreachable_is_not_offered(self) -> None:
        found = crane.methods({"Crafting": {crane.TASK: True}}, {"Crafting": 99})

        assert set(found) == {"Crafting"}

    def test_nothing_when_the_crane_is_unreachable(self) -> None:
        assert crane.methods({}, {"Crafting": 99}) == {}


class TestMaterialsAreChargedInsideTheRate:
    """Nine nails and three planks a repair is not free, and the table that
    would normally carry it is keyed by task alone - upstream files one task
    name under both skills, so a single entry would be wrong for one of them."""

    def test_charging_them_slows_the_rate(self) -> None:
        free = crane.rate_at(99, 99)
        charged = crane.rate_at(99, 99, lambda item, quantity: 1.0 * quantity)

        assert 0 < charged < free

    def test_no_route_to_a_nail_is_no_rate(self) -> None:
        """The same refusal `recipe_rates.rate_for` makes: tick-math over
        inputs nothing can price is a made-up number."""
        assert crane.rate_at(99, 99, lambda item, quantity: None) == 0.0

    def test_a_refused_material_drops_the_band(self) -> None:
        valid = {"Construction": {crane.TASK: True}}

        found = crane.methods(
            valid, {"Construction": 99}, lambda item, quantity: None
        )

        assert found == {}
