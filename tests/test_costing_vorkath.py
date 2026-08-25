"""Vorkath's version fix and freeze/acid cycle - see `costing/vorkath.py`
for the citations behind each figure."""

from __future__ import annotations

import pytest

from chunksim.costing import dps_bridge, vorkath
from chunksim.costing.dps_bridge import load_monster_index
from chunksim.model.chunkinfo import ChunkInfo

pytestmark = pytest.mark.skipif(
    not dps_bridge.DPS_AVAILABLE,
    reason="osrs-dps is an optional extra; install it with `pip install -e ../osrs-dps`",
)


class TestTheScript:
    def test_targets_the_post_quest_version(self) -> None:
        assert vorkath.SCRIPT.phases[0].target == "Vorkath#Post-quest"

    def test_the_target_is_a_key_the_library_knows(self) -> None:
        idx = load_monster_index()
        assert vorkath.SCRIPT.phases[0].target in idx

    def test_the_quest_only_version_is_smaller(self) -> None:
        """The defect this script fixes: an unscripted resolution would
        pick whichever version dies fastest, which is the one-time quest
        fight."""
        idx = load_monster_index()
        quest = idx.get("Vorkath#Dragon Slayer II")
        post_quest = idx.get("Vorkath#Post-quest")
        assert quest is not None and post_quest is not None
        assert quest.hitpoints < post_quest.hitpoints


class TestTheCycle:
    def test_attack_speed_matches_the_infobox(self) -> None:
        assert vorkath.ATTACK_SPEED_SECONDS == pytest.approx(3.0)

    def test_six_attacks_before_a_special(self) -> None:
        assert vorkath.ATTACKS_BEFORE_SPECIAL == 6
        assert vorkath.NORMAL_SECONDS_PER_BLOCK == pytest.approx(18.0)

    def test_acid_reduction_is_the_published_fifty_percent(self) -> None:
        assert vorkath.ACID_DPS_FRACTION == pytest.approx(0.5)


class TestEffectiveSeconds:
    def test_always_slower_than_the_plain_kill(self) -> None:
        for kill_seconds in (30.0, 120.0, 600.0):
            assert vorkath.effective_seconds(kill_seconds) > kill_seconds

    def test_zero_or_negative_kill_time_passes_through(self) -> None:
        assert vorkath.effective_seconds(0.0) == 0.0
        assert vorkath.effective_seconds(-1.0) == -1.0

    def test_matches_the_hand_derived_closed_form(self) -> None:
        """Independently re-derives the steady-state cycle formula rather
        than transcribing `effective_seconds`'s own arithmetic, so a
        mistake in either shows up as a mismatch."""
        kill_seconds = 200.0
        cycle_seconds = (
            2 * vorkath.NORMAL_SECONDS_PER_BLOCK + vorkath.FREEZE_SECONDS + vorkath.ACID_SECONDS
        )
        expected = (
            kill_seconds
            * cycle_seconds
            / (2 * vorkath.NORMAL_SECONDS_PER_BLOCK + vorkath.ACID_DPS_FRACTION * vorkath.ACID_SECONDS)
        )
        assert vorkath.effective_seconds(kill_seconds) == pytest.approx(expected)


class TestWiredIntoDpsBridge:
    def test_registered(self) -> None:
        assert dps_bridge.SCRIPTS[vorkath.VORKATH] is vorkath.SCRIPT

    def test_a_scripted_kill_targets_post_quest(self) -> None:
        picks = {"Melee-weapon": "Abyssal whip", "Melee-head": "Rune full helm"}
        loadouts = dps_bridge.build_loadouts(
            _chunk_info(), picks, {"Attack": 90, "Strength": 90, "Hitpoints": 90}
        )
        idx = load_monster_index()
        versions = dps_bridge.version_index(idx)
        candidates = dps_bridge.candidate_targets(idx, vorkath.VORKATH, versions)
        kill = dps_bridge.best_kill(loadouts, vorkath.VORKATH, candidates, index=idx, boss=True)
        assert kill is not None
        assert kill.match == "scripted"
        target = idx.get("Vorkath#Post-quest")
        assert target is not None
        assert kill.hitpoints == pytest.approx(target.hitpoints)


def _chunk_info() -> ChunkInfo:
    return ChunkInfo(
        {
            "equipment": {
                "Abyssal whip": {
                    "attack_slash": 82, "melee_strength": 82,
                    "attack_speed": 4, "slot": "weapon",
                },
                "Rune full helm": {"defence_slash": 30, "attack_speed": 0, "slot": "head"},
            }
        }
    )
