"""Tests for `costing/keyed_chests.py` - see its module docstring for the
mechanic and where `CANDIDATE_CHANCE`'s numbers come from."""

from __future__ import annotations

import pytest

from chunksim.costing import keyed_chests


class TestKeySeconds:
    def test_picks_the_cheapest_candidate(self) -> None:
        # Bryophyta: 100s / (1/16) = 1,600s a key.
        # Moss giant: 10s / (1/150) = 1,500s a key - cheaper despite the
        # worse per-kill odds, which is the whole point of comparing them.
        seconds = {"Bryophyta": 100.0, "Moss giant": 10.0}.get
        got = keyed_chests.key_seconds(keyed_chests.BRYOPHYTAS_LAIR, seconds)
        assert got == pytest.approx(1500.0)

    def test_an_unreachable_candidate_is_skipped_not_zero(self) -> None:
        seconds = {"Bryophyta": None, "Moss giant": 10.0}.get
        got = keyed_chests.key_seconds(keyed_chests.BRYOPHYTAS_LAIR, seconds)
        assert got == pytest.approx(10.0 / (1.0 / 150.0))

    def test_no_candidate_reachable_is_none(self) -> None:
        got = keyed_chests.key_seconds(keyed_chests.BRYOPHYTAS_LAIR, lambda name: None)
        assert got is None

    def test_an_unknown_chest_has_no_candidates(self) -> None:
        got = keyed_chests.key_seconds("Chest (nowhere)", lambda name: 10.0)
        assert got is None

    def test_obor_and_bryophyta_do_not_share_candidates(self) -> None:
        """Hill Giant answers for Obor's lair and must never leak into
        Bryophyta's, or a map with only Hill Giants would price a Mossy
        key off a monster that has never dropped one."""
        seconds = {"Hill Giant": 5.0}.get
        assert keyed_chests.key_seconds(keyed_chests.BRYOPHYTAS_LAIR, seconds) is None
        assert keyed_chests.key_seconds(keyed_chests.OBORS_LAIR, seconds) is not None


class TestEffectiveSeconds:
    def test_adds_the_open_action_on_top_of_the_key(self) -> None:
        seconds = {"Obor": 160.0}.get  # 160 / (1/16) = 2,560s a key
        got = keyed_chests.effective_seconds(keyed_chests.OBORS_LAIR, seconds)
        assert got == pytest.approx(2560.0 + keyed_chests.OPEN_SECONDS)

    def test_none_when_no_key_route_exists(self) -> None:
        got = keyed_chests.effective_seconds(keyed_chests.OBORS_LAIR, lambda name: None)
        assert got is None
