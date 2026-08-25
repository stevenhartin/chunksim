"""Zulrah's `FightScript` and its wiring into `dps_bridge`.

No `TestAgainstTheGuide` class here - see `costing/zulrah.py`'s own `note`
on why: her guide recommends a hybrid Magic/Ranged loadout switched per
form, which `costing/oracle.py`'s one-style-per-guide gear builder cannot
construct at all. What is tested instead is the tally the three `hp_share`s
come from, pinned against the wiki's own phase-by-phase rotation text so a
transcription slip is a test failure rather than a silent drift.
"""

from __future__ import annotations

from typing import Any

import pytest

from chunksim.costing import dps_bridge, zulrah

pytestmark = pytest.mark.skipif(
    not dps_bridge.DPS_AVAILABLE,
    reason="osrs-dps is an optional extra; install it with `pip install -e ../osrs-dps`",
)

#: Every published rotation's phases as `(form, attack_count)`, transcribed
#: from `Zulrah/Strategies`' own "Rotation overview" section. `0` where a
#: phase states no attack count at all (a pure venom-cloud or snakeling-orb
#: phase) - see `costing/zulrah.py`'s "What is not modelled".
#:
#: This is the source data `zulrah.WAVE_TALLY` is derived from; kept here
#: rather than only in the module so a future re-check against the wiki has
#: something to diff against phase by phase, not just a final sum.
_ROTATIONS: dict[str, tuple[tuple[str, int], ...]] = {
    "1": (
        ("Serpentine", 0), ("Magma", 2), ("Tanzanite", 4), ("Serpentine", 5),
        ("Magma", 2), ("Tanzanite", 5), ("Serpentine", 0), ("Tanzanite", 5),
        ("Serpentine", 10), ("Magma", 2), ("Serpentine", 5),
    ),
    "2": (
        ("Serpentine", 0), ("Magma", 2), ("Tanzanite", 4), ("Serpentine", 0),
        ("Tanzanite", 5), ("Magma", 2), ("Serpentine", 5), ("Tanzanite", 5),
        ("Serpentine", 10), ("Magma", 2), ("Serpentine", 5),
    ),
    "3": (
        ("Serpentine", 0), ("Serpentine", 5), ("Magma", 2), ("Tanzanite", 5),
        ("Serpentine", 5), ("Tanzanite", 5), ("Serpentine", 0), ("Serpentine", 5),
        ("Tanzanite", 5), ("Serpentine", 10), ("Tanzanite", 0), ("Serpentine", 5),
    ),
    "4": (
        ("Serpentine", 0), ("Tanzanite", 6), ("Serpentine", 4), ("Tanzanite", 4),
        ("Magma", 2), ("Serpentine", 4), ("Serpentine", 0), ("Tanzanite", 5),
        ("Serpentine", 4), ("Tanzanite", 4), ("Serpentine", 8), ("Tanzanite", 0),
        ("Serpentine", 5),
    ),
}


class TestTheTally:
    """`WAVE_TALLY` against an independent re-summation of the same
    per-phase source, so the module's own constant cannot silently drift
    from the transcription this test carries."""

    def test_every_rotation_sums_to_the_published_tally(self) -> None:
        totals: dict[str, int] = {"Serpentine": 0, "Magma": 0, "Tanzanite": 0}
        for phases in _ROTATIONS.values():
            for form, count in phases:
                totals[form] += count
        assert totals == zulrah.WAVE_TALLY

    def test_rotations_1_and_2_are_identical_totals(self) -> None:
        """'Crimson A & B' share a structure per the wiki's own section
        heading - a sanity check on the transcription, not a new fact."""

        def totals(name: str) -> dict[str, int]:
            found: dict[str, int] = {"Serpentine": 0, "Magma": 0, "Tanzanite": 0}
            for form, count in _ROTATIONS[name]:
                found[form] += count
            return found

        assert totals("1") == totals("2")

    def test_every_rotation_ends_the_same_way_it_started(self) -> None:
        """Every rotation's first and last phase are both Serpentine -
        matching the page's own statement that the wraparound phase "counts
        as the first phase of the new rotation"."""
        for name, phases in _ROTATIONS.items():
            assert phases[0][0] == "Serpentine", name
            assert phases[-1][0] == "Serpentine", name

    def test_magma_phases_are_always_exactly_two_attacks(self) -> None:
        """Every crimson/Magma phase across all four rotations is "attacking
        twice with Melee" - her own attacks, not the player's, but a
        consistent proxy for how long the phase lasts."""
        for phases in _ROTATIONS.values():
            for form, count in phases:
                if form == "Magma":
                    assert count == 2


class TestTheScript:
    def test_three_phases_summing_to_one(self) -> None:
        shares = [phase.hp_share for phase in zulrah.SCRIPT.phases]
        assert sum(shares) == pytest.approx(1.0)
        assert len(shares) == 3

    def test_every_target_is_a_key_the_library_knows(self) -> None:
        index = dps_bridge.load_monster_index()
        for phase in zulrah.SCRIPT.phases:
            assert phase.target in index, phase.target

    def test_serpentine_has_the_largest_share(self) -> None:
        """95 of 173 published attacks - just over half the fight, matching
        her being the default form every rotation opens and closes on."""
        by_name = {phase.name: phase for phase in zulrah.SCRIPT.phases}
        serpentine = next(p for p in zulrah.SCRIPT.phases if "Serpentine" in p.name)
        assert serpentine.hp_share > 0.5
        assert serpentine.hp_share == pytest.approx(95 / 173)

    def test_magma_has_the_smallest_share(self) -> None:
        """16 of 173 - always a brief two-melee-attack interlude."""
        magma = next(p for p in zulrah.SCRIPT.phases if "Magma" in p.name)
        others = [p.hp_share for p in zulrah.SCRIPT.phases if p is not magma]
        assert all(magma.hp_share < share for share in others)

    def test_only_serpentine_carries_the_dive_overhead(self) -> None:
        """Booked on one phase for bookkeeping, not because the dives
        themselves happen only around that form - see the module docstring."""
        serpentine = next(p for p in zulrah.SCRIPT.phases if "Serpentine" in p.name)
        others = [p for p in zulrah.SCRIPT.phases if p is not serpentine]
        assert serpentine.reduced_seconds == pytest.approx(zulrah.DIVE_SECONDS)
        assert serpentine.reduced_dps_fraction == 0.0
        assert all(p.reduced_seconds == 0.0 for p in others)


def _equipment() -> dict[str, Any]:
    # **Evenly matched on raw power, deliberately.** The point of
    # `test_each_form_picks_its_own_optimal_style` is that the *defensive*
    # swing between forms decides the winner - Serpentine's magic bonus,
    # Tanzanite's ranged-only opening - not that one weapon simply
    # outdamages the other everywhere. A weak wand against a strong bow
    # proved nothing except that the bow was stronger.
    return {
        "Master wand": {
            "attack_magic": 65,
            "magic_damage": 50,
            "attack_speed": 4,
            "slot": "weapon",
        },
        "Webweaver bow (u)": {
            "attack_ranged": 65,
            "ranged_strength": 50,
            "attack_speed": 4,
            "slot": "2h",
        },
    }


def _chunk_info() -> Any:
    from chunksim.model.chunkinfo import ChunkInfo

    return ChunkInfo({"equipment": _equipment()})


_LEVELS = {"Attack": 80, "Strength": 80, "Ranged": 90, "Magic": 90, "Hitpoints": 90}


def _loadouts() -> dict[str, Any]:
    """A mixed Magic+Ranged loadout - see `_equipment`'s docstring on why
    the two weapons are power-matched. `spell="Fire Wave"` is required:
    without one a magic loadout has no max hit at all and the library
    refuses it outright, which is what a bare `Kit()` would have done here."""
    from chunksim.costing.dps_bridge import Kit

    picks = {"Magic-weapon": "Master wand", "Ranged-2h": "Webweaver bow (u)"}
    kit = Kit(spell="Fire Wave")
    return dps_bridge.build_loadouts(_chunk_info(), picks, _LEVELS, kit)


class TestWiredIntoDpsBridge:
    def test_zulrah_is_registered(self) -> None:
        assert dps_bridge.SCRIPTS["Zulrah"] is zulrah.SCRIPT

    def _kill(self) -> "dps_bridge.KillEstimate | None":
        loadouts = _loadouts()
        index = dps_bridge.load_monster_index()
        versions = dps_bridge.version_index(index)
        candidates = dps_bridge.candidate_targets(index, "Zulrah", versions)
        return dps_bridge.best_kill(loadouts, "Zulrah", candidates, boss=True)

    def test_a_scripted_kill_is_marked_as_one(self) -> None:
        kill = self._kill()
        assert kill is not None
        assert kill.match == "scripted"

    def test_the_full_health_is_carried(self) -> None:
        kill = self._kill()
        assert kill is not None
        assert kill.hitpoints == pytest.approx(500.0)

    def test_each_form_picks_its_own_optimal_style(self) -> None:
        """**The point of the whole exercise.** A mixed Magic+Ranged loadout
        should let Magic win Serpentine and Magma - both weak to it - and
        Ranged win Tanzanite, exactly matching the strategy guide's own
        advice, since each phase runs its own independent style search."""
        loadouts = _loadouts()
        index = dps_bridge.load_monster_index()

        won: dict[str, str] = {}
        for phase in zulrah.SCRIPT.phases:
            candidates = dps_bridge.candidate_targets(
                index, phase.target, dps_bridge.version_index(index)
            )
            styled = dps_bridge.kills_by_style(loadouts, phase.target, candidates, boss=True)
            best = min(styled.values(), key=lambda k: k.ttk)
            won[phase.target] = best.style

        assert won["Zulrah#Serpentine"] == "Magic"
        assert won["Zulrah#Magma"] == "Magic"
        assert won["Zulrah#Tanzanite"] == "Ranged"

    def test_the_total_time_matches_the_hand_computed_sum(self) -> None:
        """Independently recomputes every phase's contribution, pinning the
        arithmetic rather than only checking the wiring runs - the same
        pattern `tests/test_costing_hydra.py` uses."""
        loadouts = _loadouts()
        index = dps_bridge.load_monster_index()

        expected = 0.0
        for phase in zulrah.SCRIPT.phases:
            target = index.get(phase.target)
            assert target is not None
            candidates = dps_bridge.candidate_targets(
                index, phase.target, dps_bridge.version_index(index)
            )
            styled = dps_bridge.kills_by_style(loadouts, phase.target, candidates, boss=True)
            solo = min(styled.values(), key=lambda k: k.ttk)
            base_dps = target.hitpoints / solo.ttk
            expected += phase.hp_share * solo.ttk + phase.reduced_seconds

        kill = self._kill()
        assert kill is not None
        assert kill.ttk == pytest.approx(expected, rel=1e-9)
