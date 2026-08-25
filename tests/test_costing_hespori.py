"""Hespori's 32-hour grow gate - see `costing/hespori.py` for the citations
behind each figure."""

from __future__ import annotations

import pytest

from chunksim.costing import hespori


class TestTheGrowTime:
    def test_thirty_two_hours_exactly(self) -> None:
        """The hespori seed's own farming recipe: '1,920 minutes (3x640
        min = 32 hours)' - not this project's own figure."""
        assert hespori.GROW_SECONDS == pytest.approx(32.0 * 3600.0)

    def test_dwarfs_an_ordinary_kill(self) -> None:
        """The defect this module exists to fix, stated as a ratio: a
        combat-only rate is off by roughly three orders of magnitude
        against the real gated one."""
        fast_kill = 60.0
        total = hespori.effective_seconds(fast_kill)
        assert total / fast_kill > 1000


class TestEffectiveSeconds:
    def test_adds_the_grow_time_on_top_of_the_kill(self) -> None:
        assert hespori.effective_seconds(45.0) == pytest.approx(hespori.GROW_SECONDS + 45.0)

    def test_a_slower_kill_still_reads_close_to_the_grow_time(self) -> None:
        """The fight is a rounding error beside the grow - a five-minute
        kill moves the total by well under 1%."""
        fast = hespori.effective_seconds(30.0)
        slow = hespori.effective_seconds(300.0)
        assert slow / fast == pytest.approx(1.0, abs=0.01)
