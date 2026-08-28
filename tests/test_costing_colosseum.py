"""The Fortis Colosseum: eleven waves and Sol Heredit - see
`costing/colosseum.py` for the citations behind each figure."""

from __future__ import annotations

import pytest

from chunksim.costing import colosseum, encounter
from chunksim.costing.dps_bridge import load_monster_index


def _seconds(target: str) -> float | None:
    return 5.0


class TestTheRoster:
    def test_the_fremennik_trio_is_eleven_waves_each(self) -> None:
        """Guaranteed on every wave but the twelfth - `Sol Heredit` alone."""
        for name in (
            "Fremennik warband berserker", "Fremennik warband seer", "Fremennik warband archer",
        ):
            assert colosseum.WAVE_ROSTER[name] == colosseum.WAVES

    def test_the_escalating_counts_match_the_strategy_pages_wave_breakdown(self) -> None:
        """Summed by hand off `Fortis Colosseum/Strategies`' own bullet
        list - see `costing/colosseum.py` for the per-wave table this
        totals."""
        assert colosseum.WAVE_ROSTER["Serpent shaman"] == 6
        assert colosseum.WAVE_ROSTER["Javelin Colossus"] == 13
        assert colosseum.WAVE_ROSTER["Manticore"] == 11
        assert colosseum.WAVE_ROSTER["Shockwave Colossus"] == 3

    def test_every_roster_entry_and_sol_heredit_are_keys_the_library_knows(self) -> None:
        idx = load_monster_index()
        for target in colosseum.WAVE_ROSTER:
            assert target in idx, target
        assert colosseum.FINAL_BOSS in idx

    def test_sol_heredit_needs_no_script(self) -> None:
        """One bare key, matching `Fortis Colosseum/Strategies`' own
        'Phase 1 (100% HP, 1500 HP)' - no `#`-suffixed sub-phases the way
        the Hydra or Zulrah have."""
        from chunksim.costing import dps_bridge

        assert colosseum.FINAL_BOSS not in dps_bridge.SCRIPTS
        idx = load_monster_index()
        target = idx.get(colosseum.FINAL_BOSS)
        assert target is not None
        assert target.hitpoints == pytest.approx(1500.0)


class TestTheChest:
    def test_the_guide_is_two_and_a_half_kills_per_hour(self) -> None:
        assert colosseum.PUBLISHED_RUNS_PER_HOUR == 2.5
        assert colosseum.PUBLISHED_SECONDS == pytest.approx(1440.0)

    def test_the_pet_is_two_rolls_not_one(self) -> None:
        """`1 - (1-p)^2`, matching `costing/tzhaar.pet_chance`'s own
        formula and reason: the quiver is kept once, then traded."""
        assert colosseum.pet_chance() == pytest.approx(
            1.0 - (1.0 - colosseum.PET_CHANCE_PER_ROLL) ** 2
        )

    def test_item_chances_matches_the_pages_own_cumulative_figures(self) -> None:
        """`[[Rewards Chest (Fortis Colosseum)]]`'s wave-12 row: armour
        `1/24.06`ish, Tonalztics `1/83.61`, echo crystal (at least one)
        `1/12.44` - this project's own sum of the guide's per-wave
        fractions lands within the page's own rounding of each."""
        chances = colosseum.item_chances()
        assert 1 / chances["Sunfire fanatic helm"] == pytest.approx(24.06, abs=0.1)
        assert 1 / chances["Tonalztics of ralos (uncharged)"] == pytest.approx(83.61, abs=0.5)
        assert 1 / chances["Echo crystal"] == pytest.approx(12.44, abs=0.5)

    def test_the_quiver_and_splinters_are_guaranteed(self) -> None:
        chances = colosseum.item_chances()
        assert chances["Dizana's quiver (uncharged)"] == pytest.approx(1.0)
        assert chances["Sunfire splinters"] == pytest.approx(1.0)


class TestTheSequencer:
    def test_a_run_prices_the_roster_and_sol_heredit_or_none_at_all(self) -> None:
        built = colosseum.run(_seconds)
        assert built is not None
        # One stage per roster entry, one for Sol Heredit, one puzzle.
        assert len(built.stages) == len(colosseum.WAVE_ROSTER) + 2

    def test_a_missing_boss_refuses_the_whole_run(self) -> None:
        def partial(target: str) -> float | None:
            return None if target == colosseum.FINAL_BOSS else 5.0

        assert colosseum.run(partial) is None

    def test_uptime_divides_every_fights_time_to_kill(self) -> None:
        """`Mechanic.seconds` is `ttk / uptime` - so a lower `UPTIME` must
        make the run longer, not shorter."""
        built = colosseum.run(_seconds)
        assert built is not None
        assert colosseum.UPTIME < 1.0
        naive_total = sum(colosseum.WAVE_ROSTER.values()) * 5.0 + 5.0
        assert built.seconds > naive_total


class TestRunSeconds:
    """`run_seconds` is what wires `costing/inputs.py`'s
    `_colosseum_run_seconds` into the item walk - see its own docstring on
    why `item_seconds` used to spend `PUBLISHED_SECONDS` flat, regardless of
    the map's own account, the same 150/hour-default shape
    `costing/brimstone.py`'s docstring names for a different chest."""

    def test_no_override_is_the_published_figure(self) -> None:
        assert colosseum.run_seconds() == colosseum.RUN_SECONDS

    def test_a_real_override_wins(self) -> None:
        assert colosseum.run_seconds({colosseum.FORTIS_COLOSSEUM: 900.0}) == 900.0

    def test_a_non_positive_or_wrong_typed_override_is_ignored(self) -> None:
        assert colosseum.run_seconds({colosseum.FORTIS_COLOSSEUM: 0.0}) == colosseum.RUN_SECONDS
        assert colosseum.run_seconds({colosseum.FORTIS_COLOSSEUM: -5.0}) == colosseum.RUN_SECONDS
        assert colosseum.run_seconds({colosseum.FORTIS_COLOSSEUM: True}) == colosseum.RUN_SECONDS


class TestTheItemWalk:
    def test_every_chest_reward_is_priced(self) -> None:
        priced = colosseum.item_seconds()
        assert set(priced) == set(colosseum.item_chances())

    def test_an_override_reprices_every_reward_from_the_same_run(self) -> None:
        default = colosseum.item_seconds()
        overridden = colosseum.item_seconds({colosseum.FORTIS_COLOSSEUM: 900.0})
        assert set(overridden) == set(default)
        for item in default:
            assert overridden[item] == pytest.approx(
                default[item] * (900.0 / colosseum.RUN_SECONDS)
            )

    def test_the_activity_is_named_for_the_run_that_earns_it(self) -> None:
        assert colosseum.activity_for("Sunfire fanatic helm") == colosseum.FORTIS_COLOSSEUM
        assert colosseum.activity_for("sunfire fanatic helm") == colosseum.FORTIS_COLOSSEUM
        assert colosseum.activity_for("Twisted bow") is None

    def test_nothing_collides_with_the_raids_barrows_tzhaar_or_moons(self) -> None:
        from chunksim.costing import barrows, moons, raids, tzhaar

        priced = set(colosseum.item_seconds())
        assert not priced & set(raids.item_seconds())
        assert not priced & set(tzhaar.item_seconds())
        assert not priced & set(barrows.item_seconds())
        assert not priced & set(moons.item_seconds())


class TestAnswer:
    def test_full_log_runs(self) -> None:
        got = colosseum.answer(_seconds)
        assert got is not None
        assert got.runs == pytest.approx(
            encounter.runs_for_all(list(colosseum.item_chances().values()))
        )

    def test_a_named_unique_uses_its_own_chance(self) -> None:
        from chunksim.costing.encounter import Objective

        got = colosseum.answer(_seconds, Objective.for_unique("Smol heredit"))
        assert got is not None
        assert got.runs == pytest.approx(encounter.expected_runs(colosseum.pet_chance()))

    def test_experience_is_refused_not_guessed(self) -> None:
        from chunksim.costing.encounter import Objective

        assert colosseum.answer(_seconds, Objective(kind="experience")) is None
