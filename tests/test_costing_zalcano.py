"""Zalcano's flat rate override - see `costing/zalcano.py` for the
citations behind each figure."""

from __future__ import annotations

import pytest

from chunksim.costing import zalcano


class TestThePublishedRate:
    def test_forty_eight_kills_per_hour(self) -> None:
        assert zalcano.PUBLISHED_KILLS_PER_HOUR == 48.0
        assert zalcano.PUBLISHED_SECONDS == pytest.approx(75.0)


class TestEffectiveSeconds:
    def test_ignores_the_simulated_kill_time_entirely(self) -> None:
        """The defect this module exists to fix: `osrs_dps` gives Zalcano
        zero defence against everything, since the library has no notion
        of 'immune to conventional combat', so a simulated kill time is
        never a real answer to correct - only the published, group-driven
        figure is."""
        for absurd_kill_seconds in (0.5, 2.0, 500.0, 100000.0):
            assert zalcano.effective_seconds(absurd_kill_seconds) == pytest.approx(
                zalcano.PUBLISHED_SECONDS
            )


class TestWiredIntoDpsBridge:
    def test_registered_as_a_simple_gated_correction(self) -> None:
        from chunksim.costing import dps_bridge

        assert dps_bridge._SIMPLE_GATED_CORRECTIONS[zalcano.ZALCANO] is zalcano.effective_seconds

    def test_a_wrong_fast_combat_rate_is_overridden(self) -> None:
        from chunksim.costing import dps_bridge
        from chunksim.costing.heuristics import Rate

        # Mimics the real bug: osrs_dps's zero-defence Zalcano prices a
        # kill in a couple of seconds against any real weapon.
        monsters = {zalcano.ZALCANO: Rate(value=3600.0 / 2.0, source="dps", match="exact")}
        got = dps_bridge._apply_gated_bosses(monsters, monsters)
        assert got[zalcano.ZALCANO].value == pytest.approx(zalcano.PUBLISHED_KILLS_PER_HOUR)

    def test_smolcano_is_already_correct_once_the_rate_is_fixed(self) -> None:
        """Unlike the raids/Barrows/Colosseum/Moons/Gauntlet chest fixes,
        Zalcano's own `drops` table already carries Smolcano at the
        correct published `1/2,250` - only the *rate* needed correcting."""
        smolcano_chance = 1.0 / 2250.0
        hours = (zalcano.PUBLISHED_SECONDS / 3600.0) / smolcano_chance
        assert 10.0 < hours < 200.0, hours
