"""The Blast Mine: a published distribution, and a count derived from it."""

from __future__ import annotations

import pytest

from chunksim.costing import blastmine as bm


class TestTheTwoStatedFigures:
    def test_the_blast_count_is_confirmed_twice(self) -> None:
        # "Assuming 330 dynamite used per hour", and separately "Firemaking
        # experience is gained at 16,500 per hour" against 50 a light.
        assert bm.BLASTS_PER_HOUR == 330.0
        assert 16_500.0 / 50.0 == bm.BLASTS_PER_HOUR

    def test_the_distribution_is_the_pages(self) -> None:
        assert {ore: entry[2] for ore, entry in bm.ORES.items()} == {
            "Coal": 4.5,
            "Gold ore": 14.3,
            "Mithril ore": 31.4,
            "Adamantite ore": 38.6,
            "Runite ore": 11.2,
        }
        assert sum(entry[2] for entry in bm.ORES.values()) == pytest.approx(100.0)

    def test_the_levels_are_ten_below_the_rocks_own(self) -> None:
        # "the blast mine allows players to obtain ores as though their Mining
        # level were 10 levels higher (e.g. runite with only 75 instead of 85)".
        assert bm.ORES["Runite ore"][0] == 75
        assert bm.ORES["Adamantite ore"][0] == 60


class TestTheDerivedCount:
    """**`ores_per_blast` is derived, not guessed.**"""

    def test_it_reproduces_the_pages_hourly_anchor(self) -> None:
        # The only unknown left once the blasts, the digging experience and
        # every ore's experience are known.
        got = (
            bm.BLASTS_PER_HOUR * bm.EXCAVATE_EXPERIENCE
            + bm.ores_per_hour() * bm.experience_per_ore(bm.ANCHOR_LEVEL)
        )
        assert got == pytest.approx(bm.ANCHOR_EXPERIENCE_PER_HOUR)

    def test_it_is_about_one_ore_a_blast(self) -> None:
        assert bm.ores_per_blast() == pytest.approx(1.068, abs=0.002)
        assert bm.ores_per_hour() == pytest.approx(352.5, abs=0.5)


class TestALockedOreRedistributes:
    def test_runite_is_absent_below_seventy_five(self) -> None:
        assert "Runite ore" not in bm.shares(74)
        assert "Runite ore" in bm.shares(75)

    def test_the_shares_always_sum_to_one(self) -> None:
        for level in (43, 60, 74, 75, 99):
            assert sum(bm.shares(level).values()) == pytest.approx(1.0)

    def test_the_same_activity_pays_more_once_runite_unlocks(self) -> None:
        # 137.3 an ore at 70 against 151.1 at 75, which is the whole reason a
        # locked ore has to redistribute rather than vanish.
        assert bm.experience_per_ore(70) == pytest.approx(137.3, abs=0.1)
        assert bm.experience_per_ore(75) == pytest.approx(151.1, abs=0.1)


class TestWhatAnOreCosts:
    def test_runite_is_ninety_odd_seconds(self) -> None:
        # **And that is the point: the Blast Mine really is the best runite in
        # the game.** 91 seconds an ore against 240 for mining the rock, so
        # the fix is a number rather than a refusal - the walk was wrong by a
        # factor of fourteen, not wrong to prefer it.
        seconds = bm.action_seconds(99)
        assert seconds[bm.OBTAIN["Runite ore"]] == pytest.approx(91.2, abs=0.5)
        assert 91.2 < 240.0

    def test_an_ore_below_its_level_gets_no_entry(self) -> None:
        assert bm.OBTAIN["Runite ore"] not in bm.action_seconds(74)
        assert bm.OBTAIN["Adamantite ore"] not in bm.action_seconds(59)

    def test_adamantite_is_cheaper_than_mithril(self) -> None:
        # **Counter-intuitive and real.** The table is tuned to give
        # adamantite most often - 38.6% against mithril's 31.4% - so the
        # richer ore is the *commoner* one here. Only runite is scarce.
        seconds = bm.action_seconds(99)
        assert (
            seconds[bm.OBTAIN["Adamantite ore"]]
            < seconds[bm.OBTAIN["Mithril ore"]]
            < seconds[bm.OBTAIN["Runite ore"]]
        )
        assert bm.ORES["Adamantite ore"][2] > bm.ORES["Mithril ore"][2]

    def test_it_is_wired_into_the_gathering_seam(self) -> None:
        import pathlib

        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "blastmine.action_seconds(" in source
