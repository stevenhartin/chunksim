"""Barrows: six brothers, one chest - see `costing/barrows.py` for the
citations behind each figure."""

from __future__ import annotations

import pytest

from chunksim.costing import barrows, encounter
from chunksim.costing.dps_bridge import load_monster_index


def _seconds(target: str) -> float | None:
    return 5.0


class TestTheBrothers:
    def test_six_brothers_no_more_no_less(self) -> None:
        assert len(barrows.BROTHERS) == 6
        assert set(barrows.BROTHERS) == set(barrows.UNIQUE_TABLE)

    def test_every_brother_is_a_key_the_dps_library_knows(self) -> None:
        idx = load_monster_index()
        for brother in barrows.BROTHERS:
            assert brother in idx, brother

    def test_every_brother_has_exactly_four_pieces(self) -> None:
        for brother, pieces in barrows.UNIQUE_TABLE.items():
            assert len(pieces) == 4, brother

    def test_twenty_four_pieces_total(self) -> None:
        all_pieces = [p for pieces in barrows.UNIQUE_TABLE.values() for p in pieces]
        assert len(all_pieces) == 24
        assert len(set(all_pieces)) == 24


class TestTheChest:
    def test_the_per_item_chance_matches_the_guides_own_arithmetic(self) -> None:
        """`Money making guide/Barrows`'s own `Output` fields: `1*(7/2448)`
        for every one of the twenty-four pieces."""
        assert barrows.UNIQUE_CHANCE == pytest.approx(7 / 2448)

    def test_the_per_item_chance_matches_the_pages_stated_approximation(self) -> None:
        """`[[Chest (Barrows)]]`: "approximately 1/350.14"."""
        assert 1 / barrows.UNIQUE_CHANCE == pytest.approx(350.14, abs=0.5)

    def test_item_chances_covers_all_twenty_five_collection_log_entries(self) -> None:
        """Twenty-four unique pieces plus `Bolt rack` - the export's own
        `(Barrows Chests)` task set, no more."""
        chances = barrows.item_chances()
        assert len(chances) == 25
        assert "Bolt rack" in chances

    def test_the_bolt_rack_chance_matches_the_pages_main_table(self) -> None:
        assert barrows.BOLT_RACK_CHANCE == pytest.approx(7 * 125 / 1012)

    def test_the_expected_completions_for_the_full_set_matches_the_wiki(self) -> None:
        """`[[Chest (Barrows)]]`: "All 6 sets is 1319.26 chests." Computed
        independently here via `barrows._full_log_runs`'s closed form,
        rather than transcribed, so a mistake in either the per-item chance
        or the coupon-collector arithmetic shows up as a mismatch."""
        assert barrows._full_log_runs() == pytest.approx(1319.26, rel=0.01)

    def test_the_closed_form_agrees_with_the_brute_force_on_a_small_case(self) -> None:
        """`_full_log_runs` is a specialised reduction of
        `encounter.runs_for_all` - checked against the general, brute-force
        formula directly, on a small fixture rather than the real 25-item
        table (see `_full_log_runs`'s own docstring on why the real table
        cannot use the brute-force path at all)."""
        p, q = 0.1, 0.2
        n = 4
        brute = encounter.runs_for_all([p] * n + [q])

        from math import comb

        total = 0.0
        for k in range(1, n + 1):
            sign = 1.0 if k % 2 == 1 else -1.0
            total += sign * comb(n, k) / (k * p)
        for k in range(0, n + 1):
            sign = 1.0 if k % 2 == 0 else -1.0
            total += sign * comb(n, k) / (k * p + q)
        assert total == pytest.approx(brute)


class TestTheSequencer:
    def test_a_run_prices_every_brother_or_none_at_all(self) -> None:
        built = barrows.run(_seconds)
        assert built is not None
        assert built.seconds > 0

    def test_a_missing_brother_refuses_the_whole_run(self) -> None:
        def partial(target: str) -> float | None:
            return None if target == "Ahrim the Blighted" else 5.0

        assert barrows.run(partial) is None

    def test_the_overhead_puzzle_is_the_crypt_and_the_dig(self) -> None:
        built = barrows.run(_seconds)
        assert built is not None
        overhead = [s for s in built.stages if s.target == ""]
        assert len(overhead) == 1
        assert overhead[0].seconds == pytest.approx(barrows.CRYPT_OVERHEAD_SECONDS)

    def test_the_published_run_is_a_floor_at_an_ordinary_kill_speed(self) -> None:
        """A sanity check, not a proof against real map gear the way
        `costing/theatre.py`'s own `@pytest.mark.real_cache` floor test is:
        at a plausible, unremarkable 20-second-per-brother kill time (100
        hitpoints at a moderate ~5 damage per second), six brothers plus the
        crypt overhead should not read faster than the guide's published
        300-second run."""

        def ordinary(_target: str) -> float | None:
            return 20.0

        built = barrows.run(ordinary)
        assert built is not None
        assert built.seconds >= barrows.PUBLISHED_SECONDS


class TestTheItemWalk:
    def test_every_collection_log_item_is_priced(self) -> None:
        priced = barrows.item_seconds()
        assert set(priced) == set(barrows.item_chances())

    def test_the_activity_is_named_for_the_run_that_earns_it(self) -> None:
        assert barrows.activity_for("Karil's coif") == barrows.BARROWS
        assert barrows.activity_for("karil's coif") == barrows.BARROWS
        assert barrows.activity_for("Bolt rack") == barrows.BARROWS
        assert barrows.activity_for("Twisted bow") is None

    def test_nothing_collides_with_the_raids_or_tzhaar(self) -> None:
        from chunksim.costing import raids, tzhaar

        priced = set(barrows.item_seconds())
        assert not priced & set(raids.item_seconds())
        assert not priced & set(tzhaar.item_seconds())


class TestAnswer:
    def test_full_log_is_bound_by_the_slowest_set(self) -> None:
        got = barrows.answer(_seconds)
        assert got is not None
        assert got.runs == pytest.approx(barrows._full_log_runs())

    def test_a_named_unique_uses_its_own_chance(self) -> None:
        from chunksim.costing.encounter import Objective

        got = barrows.answer(_seconds, Objective.for_unique("Karil's coif"))
        assert got is not None
        assert got.runs == pytest.approx(encounter.expected_runs(barrows.UNIQUE_CHANCE))

    def test_experience_is_refused_not_guessed(self) -> None:
        from chunksim.costing.encounter import Objective

        assert barrows.answer(_seconds, Objective(kind="experience")) is None
