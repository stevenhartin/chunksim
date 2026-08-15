"""`costing/rumours.py`: an exact formula and one invented constant."""

from __future__ import annotations

import pytest

from chunksim.costing import rumours
from chunksim.costing.gathering import GUESS

VALID = {"Hunter": {task: True for task, _mod, _opens in rumours.TIERS}}


class TestExperience:
    @pytest.mark.parametrize("level,paid", [(91, 5760.0), (99, 6240.0)])
    def test_it_reproduces_the_wikis_own_master_range(self, level: int, paid: float) -> None:
        # The page quotes a Master rumour as 5,760-6,240, which is the formula
        # at its two ends rather than a measurement of anything.
        assert rumours.experience_at(level, 60.0) == paid

    def test_the_tier_only_changes_the_multiplier(self) -> None:
        assert rumours.experience_at(99, 50.0) < rumours.experience_at(99, 55.0)
        assert rumours.experience_at(99, 55.0) < rumours.experience_at(99, 60.0)

    def test_the_level_bonus_is_applied_before_the_multiplier(self) -> None:
        assert rumours.experience_at(0, 1.0) == rumours.LEVEL_BONUS


class TestMethods:
    def test_every_band_is_marked_a_guess(self) -> None:
        # The pace is invented and decides the whole answer, so nothing here
        # may look like a reading.
        (found,) = rumours.methods(VALID).values()
        assert {method.match for method in found} == {GUESS}

    def test_a_tier_the_map_cannot_reach_is_absent(self) -> None:
        one = {"Hunter": {rumours.TIERS[0][0]: True}}
        (found,) = rumours.methods(one).values()
        assert {method.method for method in found} == {"novice rumour"}

    def test_no_reachable_tier_prices_nothing(self) -> None:
        assert rumours.methods({"Hunter": {}}) == {}

    def test_a_tier_opens_where_the_export_says(self) -> None:
        (found,) = rumours.methods(VALID).values()
        master = [m for m in found if m.method == "master rumour"]
        assert min(m.level or 0 for m in master) == 91

    def test_the_pace_scales_every_tier_together(self) -> None:
        (found,) = rumours.methods(VALID).values()
        top = max(m.xp_per_hour for m in found)
        assert top == pytest.approx(
            rumours.experience_at(99, 60.0) * rumours.RUMOURS_PER_HOUR
        )
