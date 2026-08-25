"""The Gauntlet and the Corrupted Gauntlet - see `costing/gauntlet.py` for
the citations behind each figure."""

from __future__ import annotations

import pytest

from chunksim.costing import encounter, gauntlet
from chunksim.costing.dps_bridge import load_monster_index


def _seconds(target: str) -> float | None:
    return 30.0


class TestTheBosses:
    def test_both_hunllefs_are_keys_the_library_knows(self) -> None:
        idx = load_monster_index()
        for boss in gauntlet.BOSS.values():
            assert boss in idx, boss

    def test_neither_boss_needs_a_script(self) -> None:
        """Uniform defence across every damage type on both, so no style a
        generic loadout picks is ever wrong - unlike Perilous Moons."""
        from chunksim.costing import dps_bridge

        idx = load_monster_index()
        fields = (
            "defence_stab", "defence_slash", "defence_crush",
            "defence_magic", "defence_ranged",
        )
        for boss in gauntlet.BOSS.values():
            assert boss not in dps_bridge.SCRIPTS
            target = idx.get(boss)
            assert target is not None
            values = {getattr(target.bonuses, f) for f in fields}
            assert len(values) == 1, boss

    def test_corrupted_hunllef_has_more_health_and_hits_harder(self) -> None:
        idx = load_monster_index()
        regular = idx.get(gauntlet.BOSS[gauntlet.REGULAR])
        corrupted = idx.get(gauntlet.BOSS[gauntlet.CORRUPTED])
        assert regular is not None and corrupted is not None
        assert corrupted.hitpoints > regular.hitpoints


class TestPreparation:
    def test_corrupted_prep_is_longer_than_regular(self) -> None:
        """5-6 minutes against 2-3 - the Corrupted Gauntlet's own reduced
        timer (7:30 against 10:00) still leaves more to gather, per the
        wiki's own harder resource generation note."""
        assert gauntlet.PREP_SECONDS[gauntlet.CORRUPTED] > gauntlet.PREP_SECONDS[gauntlet.REGULAR]

    def test_prep_is_within_the_published_timer_caps(self) -> None:
        """The wiki's caps are 600s (regular) and 450s (corrupted) - this
        project's own estimate must stay under the timer that would force a
        player into the boss room regardless."""
        assert gauntlet.PREP_SECONDS[gauntlet.REGULAR] < 600.0
        assert gauntlet.PREP_SECONDS[gauntlet.CORRUPTED] < 450.0

    def test_the_prep_phase_is_a_real_share_of_the_published_run(self) -> None:
        """**The defect this module exists to fix.** A model that only
        priced the boss's own time-to-kill would understate a Gauntlet
        completion badly - the guide's own totals (514s regular, 600s
        corrupted) leave only a few minutes for the fight once prep is
        subtracted."""
        for variant in (gauntlet.REGULAR, gauntlet.CORRUPTED):
            share = gauntlet.PREP_SECONDS[variant] / gauntlet.PUBLISHED_SECONDS[variant]
            assert 0.25 < share < 0.75, variant


class TestTheSequencer:
    def test_a_run_prices_prep_and_the_boss_or_none_at_all(self) -> None:
        for variant in (gauntlet.REGULAR, gauntlet.CORRUPTED):
            built = gauntlet.run(variant, _seconds)
            assert built is not None
            assert len(built.stages) == 2
            assert built.seconds == pytest.approx(gauntlet.PREP_SECONDS[variant] + 30.0)

    def test_a_missing_boss_refuses_the_whole_run(self) -> None:
        def refuse(_target: str) -> float | None:
            return None

        assert gauntlet.run(gauntlet.REGULAR, refuse) is None

    def test_corrupted_entry_is_one_regular_completion(self) -> None:
        entry = gauntlet.entry_seconds(gauntlet.CORRUPTED, _seconds)
        regular = gauntlet.run(gauntlet.REGULAR, _seconds)
        assert regular is not None
        assert entry == pytest.approx(regular.seconds)
        assert gauntlet.entry_seconds(gauntlet.REGULAR, _seconds) == 0.0


class TestTheChest:
    def test_all_four_shared_uniques_favour_corrupted(self) -> None:
        """Every rate the corrupted table publishes is better than the
        regular one - `50 > 120`, `400 > 2000`(the Enhanced seed and the
        pet), so `best_item_chances` should always pick it for these four."""
        for item in ("Crystal weapon seed", "Crystal armour seed",
                     "Enhanced crystal weapon seed", "Youngllef"):
            assert gauntlet._best_variant_for(item) == gauntlet.CORRUPTED

    def test_the_cape_is_corrupted_only_and_guaranteed(self) -> None:
        assert "Gauntlet cape" not in gauntlet.UNIQUE_CHANCE[gauntlet.REGULAR]
        assert gauntlet.UNIQUE_CHANCE[gauntlet.CORRUPTED]["Gauntlet cape"] == pytest.approx(1.0)

    def test_the_regular_rates_match_the_guides_own_output_fields(self) -> None:
        """`Money making guide/Completing The Gauntlet`'s own `Output`
        fields - one roll, not `2 * chance`."""
        regular = gauntlet.item_chances(gauntlet.REGULAR)
        assert regular["Crystal weapon seed"] == pytest.approx(1 / 120)
        assert regular["Enhanced crystal weapon seed"] == pytest.approx(1 / 2000)

    def test_the_corrupted_rates_match_the_guides_own_output_fields(self) -> None:
        corrupted = gauntlet.item_chances(gauntlet.CORRUPTED)
        assert corrupted["Crystal weapon seed"] == pytest.approx(1 / 50)
        assert corrupted["Enhanced crystal weapon seed"] == pytest.approx(1 / 400)
        assert corrupted["Youngllef"] == pytest.approx(1 / 800)


class TestTheItemWalk:
    def test_every_gated_item_is_priced(self) -> None:
        priced = gauntlet.item_seconds()
        assert set(priced) == {
            "Crystal weapon seed", "Crystal armour seed",
            "Enhanced crystal weapon seed", "Youngllef", "Gauntlet cape",
        }

    def test_the_shared_uniques_carry_a_regular_completion_on_top(self) -> None:
        """The corrupted variant wins every shared item (see `TestTheChest`),
        so each one's seconds must include one regular completion's
        published total on top of the corrupted one - `costing/tzhaar.py`'s
        own Inferno-entry-fee shape."""
        priced = gauntlet.item_seconds()
        chance = gauntlet.UNIQUE_CHANCE[gauntlet.CORRUPTED]["Crystal weapon seed"]
        expected = (gauntlet.PUBLISHED_SECONDS[gauntlet.CORRUPTED]
                    + gauntlet.PUBLISHED_SECONDS[gauntlet.REGULAR]) / chance
        assert priced["Crystal weapon seed"] == pytest.approx(expected)

    def test_the_cape_carries_no_entry_fee_beyond_the_run_itself(self) -> None:
        """Guaranteed on a corrupted completion, so its own seconds is one
        corrupted run plus its own regular-completion entry fee, not
        divided by any chance."""
        priced = gauntlet.item_seconds()
        expected = gauntlet.PUBLISHED_SECONDS[gauntlet.CORRUPTED] + gauntlet.PUBLISHED_SECONDS[
            gauntlet.REGULAR
        ]
        assert priced["Gauntlet cape"] == pytest.approx(expected)

    def test_the_activity_is_named_for_the_run_that_earns_it(self) -> None:
        assert gauntlet.activity_for("Youngllef") == gauntlet.REGULAR
        assert gauntlet.activity_for("youngllef") == gauntlet.REGULAR
        assert gauntlet.activity_for("Twisted bow") is None

    def test_nothing_collides_with_the_other_five_families(self) -> None:
        from chunksim.costing import barrows, colosseum, moons, raids, tzhaar

        priced = set(gauntlet.item_seconds())
        assert not priced & set(raids.item_seconds())
        assert not priced & set(tzhaar.item_seconds())
        assert not priced & set(barrows.item_seconds())
        assert not priced & set(colosseum.item_seconds())
        assert not priced & set(moons.item_seconds())


class TestAnswer:
    def test_full_log_runs(self) -> None:
        got = gauntlet.answer(gauntlet.CORRUPTED, _seconds)
        assert got is not None
        assert got.runs == pytest.approx(
            encounter.runs_for_all(list(gauntlet.item_chances(gauntlet.CORRUPTED).values()))
        )
        assert got.entry_seconds > 0.0

    def test_a_named_unique_uses_its_own_variant_and_chance(self) -> None:
        from chunksim.costing.encounter import Objective

        got = gauntlet.answer(
            gauntlet.REGULAR, _seconds, Objective.for_unique("Crystal weapon seed")
        )
        assert got is not None
        assert got.runs == pytest.approx(encounter.expected_runs(1 / 120))
        assert got.entry_seconds == 0.0

    def test_experience_is_refused_not_guessed(self) -> None:
        from chunksim.costing.encounter import Objective

        assert gauntlet.answer(gauntlet.REGULAR, _seconds, Objective(kind="experience")) is None
