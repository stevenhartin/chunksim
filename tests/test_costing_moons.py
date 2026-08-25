"""Perilous Moons: three scripted bosses and their shared chest - see
`costing/moons.py` for the citations behind each figure."""

from __future__ import annotations

from typing import Any

import pytest

from chunksim.costing import dps_bridge, encounter, moons
from chunksim.model.chunkinfo import ChunkInfo

pytestmark = pytest.mark.skipif(
    not dps_bridge.DPS_AVAILABLE,
    reason="osrs-dps is an optional extra; install it with `pip install -e ../osrs-dps`",
)


def _seconds(target: str) -> float | None:
    return 10.0


class TestTheScripts:
    def test_each_moon_is_one_unsplit_phase(self) -> None:
        for name, script in moons.SCRIPTS.items():
            assert script.name == name
            assert len(script.phases) == 1
            assert script.phases[0].hp_share == pytest.approx(1.0)

    def test_each_moon_is_restricted_to_its_own_weak_substyle(self) -> None:
        """Blue Moon crush, Blood Moon slash, Eclipse Moon stab - published
        on each Moon's own wiki page and matched by the library's `0`-vs-
        `100` defence split."""
        for name, style in moons.WEAK_TO.items():
            assert moons.SCRIPTS[name].phases[0].styles == frozenset({style})

    def test_every_phase_target_is_a_key_the_library_knows(self) -> None:
        index = dps_bridge.load_monster_index()
        for script in moons.SCRIPTS.values():
            for phase in script.phases:
                assert phase.target in index, phase.target

    def test_the_eclipse_moon_targets_its_regular_form_not_the_bare_name(self) -> None:
        """`osrs_dps` has no bare `Eclipse Moon` key - only `#Regular` and
        `#Clone` (the Mimic special attack's decoys) - so the phase must
        name the real one explicitly."""
        assert moons.SCRIPTS[moons.ECLIPSE_MOON].phases[0].target == "Eclipse Moon#Regular"

    def test_the_defences_actually_match_the_published_weaknesses(self) -> None:
        """Independent confirmation against the raw library data, not just
        against this module's own `WEAK_TO` table."""
        index = dps_bridge.load_monster_index()
        checks = {
            "Blue Moon": ("defence_crush", "Crush"),
            "Blood Moon": ("defence_slash", "Slash"),
            "Eclipse Moon#Regular": ("defence_stab", "Stab"),
        }
        for key, (weak_field, style) in checks.items():
            target = index.get(key)
            assert target is not None
            assert getattr(target.bonuses, weak_field) == 0
            others = {"defence_stab", "defence_slash", "defence_crush"} - {weak_field}
            for field in others:
                assert getattr(target.bonuses, field) > 0


def _equipment() -> dict[str, Any]:
    return {
        "Abyssal whip": {
            "attack_slash": 82, "melee_strength": 82, "attack_speed": 4, "slot": "weapon",
        },
        "Dragon dagger": {
            "attack_stab": 40, "attack_slash": 25, "melee_strength": 40,
            "attack_speed": 4, "slot": "weapon",
        },
        "Abyssal bludgeon": {
            "attack_crush": 102, "melee_strength": 85, "attack_speed": 5, "slot": "2h",
        },
    }


def _chunk_info() -> ChunkInfo:
    return ChunkInfo({"equipment": _equipment()})


_LEVELS = {"Attack": 90, "Strength": 90, "Ranged": 1, "Magic": 1, "Hitpoints": 90}

#: A synthetic `derived.bis.picks`-shaped mapping - the substyle winners a
#: real map's BiS derivation would have already computed alongside the
#: generic `Melee` one.
_PICKS = {
    "Melee-weapon": "Abyssal whip",
    "Stab-weapon": "Dragon dagger",
    "Slash-weapon": "Abyssal whip",
    "Crush-2h": "Abyssal bludgeon",
}


class TestWiredIntoDpsBridge:
    def test_all_three_are_registered(self) -> None:
        for name, script in moons.SCRIPTS.items():
            assert dps_bridge.SCRIPTS[name] is script

    def test_each_moon_resolves_through_its_own_substyle(self) -> None:
        """**The defect this module exists to fix.** Without
        `MELEE_SUBSTYLES`, a single generic `Melee` loadout (one weapon)
        would price two of the three Moons against a style their own
        `defence_*=100` actively resists."""
        loadouts = dps_bridge.build_loadouts(_chunk_info(), _PICKS, _LEVELS)
        index = dps_bridge.load_monster_index()
        versions = dps_bridge.version_index(index)
        got = {}
        for name in moons.SCRIPTS:
            candidates = dps_bridge.candidate_targets(index, name, versions)
            kill = dps_bridge.best_kill(loadouts, name, candidates, index=index, boss=True)
            assert kill is not None, name
            assert kill.match == "scripted"
            got[name] = kill.style
        assert got == {
            moons.BLUE_MOON: "Crush",
            moons.BLOOD_MOON: "Slash",
            moons.ECLIPSE_MOON: "Stab",
        }

    def test_a_ranged_or_magic_only_loadout_cannot_kill_any_moon(self) -> None:
        """All three refuse Ranged and Magic outright - `defence_ranged =
        defence_magic = 500` on every one, and `Phase.styles` says so
        rather than letting the search discover it the slow way."""
        picks = {"Melee-weapon": "Abyssal whip"}  # no Ranged/Magic weapon at all
        loadouts = dps_bridge.build_loadouts(_chunk_info(), picks, _LEVELS)
        # Even the generic Melee loadout is refused: none of the three
        # Moons' `styles` includes "Melee" itself, only the substyles.
        index = dps_bridge.load_monster_index()
        versions = dps_bridge.version_index(index)
        for name in moons.SCRIPTS:
            candidates = dps_bridge.candidate_targets(index, name, versions)
            kill = dps_bridge.best_kill(loadouts, name, candidates, index=index, boss=True)
            assert kill is None, name


class TestTheChest:
    def test_twelve_uniques_four_per_moon(self) -> None:
        assert sum(len(items) for items in moons.UNIQUE_TABLE.values()) == 12
        for name, items in moons.UNIQUE_TABLE.items():
            assert len(items) == 4, name

    def test_the_unique_chance_matches_the_guides_own_output_fields(self) -> None:
        """`Money making guide/Moons of Peril`: every `Output` is
        `1*(1/224)`."""
        assert moons.UNIQUE_CHANCE == pytest.approx(1 / 224)

    def test_the_guide_is_ten_kills_per_hour_for_a_full_clear(self) -> None:
        assert moons.PUBLISHED_RUNS_PER_HOUR == 10.0
        assert moons.PUBLISHED_SECONDS == pytest.approx(360.0)


class TestTheSequencer:
    def test_a_run_prices_all_three_bosses_or_none_at_all(self) -> None:
        built = moons.run(_seconds)
        assert built is not None
        assert len(built.stages) == 3

    def test_a_missing_boss_refuses_the_whole_run(self) -> None:
        def partial(target: str) -> float | None:
            return None if target == moons.BLOOD_MOON else 10.0

        assert moons.run(partial) is None


class TestTheItemWalk:
    def test_every_unique_and_atlatl_dart_are_priced(self) -> None:
        priced = moons.item_seconds()
        assert set(priced) == set(moons.item_chances())
        assert "Atlatl dart" in priced

    def test_the_activity_is_named_for_the_run_that_earns_it(self) -> None:
        assert moons.activity_for("Blue moon spear") == moons.PERILOUS_MOONS
        assert moons.activity_for("blue moon spear") == moons.PERILOUS_MOONS
        assert moons.activity_for("Twisted bow") is None

    def test_nothing_collides_with_the_raids_barrows_or_tzhaar(self) -> None:
        from chunksim.costing import barrows, raids, tzhaar

        priced = set(moons.item_seconds())
        assert not priced & set(raids.item_seconds())
        assert not priced & set(tzhaar.item_seconds())
        assert not priced & set(barrows.item_seconds())


class TestAnswer:
    def test_full_log_is_the_coupon_collector_over_twelve_symmetric_items(self) -> None:
        got = moons.answer(_seconds)
        assert got is not None
        assert got.runs == pytest.approx(
            encounter.runs_for_all(list(moons.item_chances().values()))
        )

    def test_a_named_unique_uses_its_own_chance(self) -> None:
        from chunksim.costing.encounter import Objective

        got = moons.answer(_seconds, Objective.for_unique("Dual macuahuitl"))
        assert got is not None
        assert got.runs == pytest.approx(encounter.expected_runs(moons.UNIQUE_CHANCE))

    def test_experience_is_refused_not_guessed(self) -> None:
        from chunksim.costing.encounter import Objective

        assert moons.answer(_seconds, Objective(kind="experience")) is None
