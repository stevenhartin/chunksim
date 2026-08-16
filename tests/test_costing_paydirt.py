"""Pay-dirt: which ore a pay-dirt turns out to be, and what that costs."""

from __future__ import annotations

import pytest

from chunksim.costing import paydirt as pd


class TestTheCascade:
    """**`cascade=yes` is the mechanic, not a presentation flag.**

    Mod Ash: "pay-dirt rolls for each ore in descending order, starting from
    the top tier you're eligible to get" - so an ore's chance is its own roll
    times the chance every richer one failed.
    """

    #: The wiki's own published percentages at 99.
    PUBLISHED = {
        "Golden nugget": 3.13,
        "Runite ore": 2.27,
        "Mithril ore": 26.93,
        "Gold ore": 24.22,
        "Coal": 24.6,
    }

    @pytest.mark.parametrize("ore,published", sorted(PUBLISHED.items()))
    def test_an_ore_matches_the_published_share(
        self, ore: str, published: float
    ) -> None:
        assert pd.ore_chance(ore, 99) * 100 == pytest.approx(published, abs=0.02)

    def test_adamantite_follows_the_chart_over_the_prose(self) -> None:
        # **The page disagrees with itself.** Its chart gives 18.85% and a
        # sentence beside it says 18.18%; the chart is what the other five
        # rows come from and is what this follows.
        assert pd.ore_chance("Adamantite ore", 99) * 100 == pytest.approx(
            18.85, abs=0.02
        )

    def test_the_shares_sum_to_one(self) -> None:
        for level in (30, 45, 60, 75, 90, 99):
            assert sum(pd.ore_chances(level).values()) == pytest.approx(1.0)

    def test_coal_is_the_remainder(self) -> None:
        # Its series is 226/325, which is already certain at its own level-30
        # requirement - that is what makes it the catch-all rather than a
        # seventh outcome, and why the shares sum to one.
        from chunksim.costing.gathering import success_chance

        ore, low, high, needs = pd.CASCADE[-1]
        assert ore == "Coal"
        assert needs == 30
        assert success_chance(needs, low, high) == 1.0
        assert success_chance(99, low, high) == 1.0


class TestLevelGates:
    @pytest.mark.parametrize(
        "level,absent",
        [(50, "Mithril ore"), (60, "Adamantite ore"), (80, "Runite ore")],
    )
    def test_an_ore_below_its_requirement_never_appears(
        self, level: int, absent: str
    ) -> None:
        assert pd.ore_chance(absent, level) == 0.0
        assert absent not in pd.ore_chances(level)

    def test_the_requirements_are_the_charts(self) -> None:
        needs = {ore: req for ore, _lo, _hi, req in pd.CASCADE}
        assert needs["Runite ore"] == 85
        assert needs["Adamantite ore"] == 70
        assert needs["Mithril ore"] == 55
        assert needs["Gold ore"] == 40

    def test_a_locked_ore_leaves_the_rest_a_whole_pay_dirt(self) -> None:
        # A level-84 player rolls no runite at all, and the shares still sum
        # to one - the roll simply is not made rather than failing.
        below, above = pd.ore_chances(84), pd.ore_chances(85)
        assert "Runite ore" not in below and "Runite ore" in above
        assert sum(below.values()) == pytest.approx(1.0)
        # Adamantite does not gain from it, which is worth pinning because it
        # is the intuitive-but-wrong reading: its own roll improves with the
        # level faster than runite takes from it.
        assert below["Adamantite ore"] < above["Adamantite ore"]


class TestWhatAnOreCosts:
    def test_it_is_a_paydirt_over_the_chance_of_that_ore(self) -> None:
        seconds = pd.action_seconds(20.0, 99)
        assert seconds[pd.OBTAIN["Runite ore"]] == pytest.approx(
            20.0 / pd.ore_chance("Runite ore", 99)
        )

    def test_runite_is_the_dearest_by_far(self) -> None:
        seconds = pd.action_seconds(20.0, 99)
        assert seconds[pd.OBTAIN["Runite ore"]] > 800.0
        assert seconds[pd.OBTAIN["Mithril ore"]] < 100.0

    def test_an_unreachable_ore_gets_no_entry_rather_than_a_default(self) -> None:
        # **The defect this module exists for.** A missing entry reads as "no
        # stated pace"; an entry of zero or infinity would be a number the
        # walk could act on.
        assert pd.OBTAIN["Runite ore"] not in pd.action_seconds(20.0, 80)
        assert pd.OBTAIN["Adamantite ore"] not in pd.action_seconds(20.0, 60)

    def test_a_free_paydirt_prices_nothing(self) -> None:
        assert pd.action_seconds(0.0, 99) == {}


class TestTheSeamWithTheGatheringModel:
    def test_it_takes_the_models_own_paydirt_figure(self) -> None:
        # One model owns how fast a pay-dirt is mined and this owns what comes
        # out of it, so the two cannot drift.
        got = pd.timed({pd.PAYDIRT_TASK: 20.0}, 99)
        assert got == pd.action_seconds(20.0, 99)

    def test_no_paydirt_figure_means_no_entries(self) -> None:
        assert pd.timed({}, 99) == {}

    def test_it_is_wired_into_the_gathering_seam(self) -> None:
        import pathlib

        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "paydirt.timed(" in source
