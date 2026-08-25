"""Skotizo's dark totem gate - see `costing/skotizo.py` for the citations
behind each figure."""

from __future__ import annotations

import pytest

from chunksim.costing import skotizo


class TestPieceChance:
    def test_matches_the_published_formula(self) -> None:
        """`[[Dark totem]]`: `1/(500-H)`."""
        assert skotizo.piece_chance(35.0) == pytest.approx(1.0 / (500.0 - 35.0))
        assert skotizo.piece_chance(0.0) == pytest.approx(1.0 / 500.0)

    def test_a_tougher_monster_gets_a_better_per_kill_chance(self) -> None:
        """Counter-intuitive but published: the formula rewards higher
        hitpoints, which is exactly why the *time* has to be optimised
        rather than the chance read off directly."""
        assert skotizo.piece_chance(130.0) > skotizo.piece_chance(35.0)


class TestCandidates:
    def test_six_low_hitpoint_candidates(self) -> None:
        """A curated subset, not the whole dungeon - see the module
        docstring on why the excluded majority can never win."""
        assert len(skotizo.CANDIDATE_HITPOINTS) == 6
        assert all(hp < 100 for hp in skotizo.CANDIDATE_HITPOINTS.values())

    def test_every_candidate_is_a_key_the_dps_library_knows(self) -> None:
        from chunksim.costing.dps_bridge import load_monster_index

        idx = load_monster_index()
        for name in skotizo.CANDIDATE_HITPOINTS:
            assert name in idx or any(
                k.startswith(f"{name}#") for k in idx
            ), name

    def test_hill_giant_is_among_them(self) -> None:
        """The wiki's own named example: 'dark totem pieces can be most
        quickly obtained by killing low HP monsters... such as hill
        giants.'"""
        assert "Hill Giant" in skotizo.CANDIDATE_HITPOINTS


class TestTotemSeconds:
    def test_three_pieces_at_the_winning_candidates_rate(self) -> None:
        """Sequential, not a coupon-collector problem - three independent
        waits at one rate, not three distinct items to collect."""
        kill_seconds = {"Hill Giant": 5.0}.get
        got = skotizo.totem_seconds(kill_seconds)
        expected_one_piece = 5.0 / skotizo.piece_chance(skotizo.CANDIDATE_HITPOINTS["Hill Giant"])
        assert got == pytest.approx(3.0 * expected_one_piece)

    def test_optimises_over_every_reachable_candidate(self) -> None:
        """Not a hardcoded 'always hill giants' - a slower Hill Giant kill
        against a faster alternative must lose."""

        def kill_seconds(name: str) -> float | None:
            return {"Hill Giant": 100.0, "Skeleton (Catacombs of Kourend)": 5.0}.get(name)

        got = skotizo.totem_seconds(kill_seconds)
        expected = 3.0 * (
            5.0 / skotizo.piece_chance(skotizo.CANDIDATE_HITPOINTS["Skeleton (Catacombs of Kourend)"])
        )
        assert got == pytest.approx(expected)

    def test_an_unreachable_candidate_is_skipped_not_fatal(self) -> None:
        def kill_seconds(name: str) -> float | None:
            return None if name != "Hill Giant" else 6.0

        got = skotizo.totem_seconds(kill_seconds)
        assert got is not None

    def test_no_reachable_candidate_refuses_rather_than_guessing(self) -> None:
        assert skotizo.totem_seconds(lambda _name: None) is None
