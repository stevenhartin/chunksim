"""Duke Sucellus's version fix and preparation-phase doubling - see
`costing/duke_sucellus.py` for the citations behind each figure."""

from __future__ import annotations

import pytest

from chunksim.costing import dps_bridge, duke_sucellus
from chunksim.costing.dps_bridge import load_monster_index
from chunksim.model.chunkinfo import ChunkInfo

pytestmark = pytest.mark.skipif(
    not dps_bridge.DPS_AVAILABLE,
    reason="osrs-dps is an optional extra; install it with `pip install -e ../osrs-dps`",
)


class TestTheScript:
    def test_targets_the_post_quest_version_specifically(self) -> None:
        assert duke_sucellus.SCRIPT.phases[0].target == "Duke Sucellus#Post-quest, Awake"

    def test_the_target_is_a_key_the_library_knows(self) -> None:
        idx = load_monster_index()
        assert duke_sucellus.SCRIPT.phases[0].target in idx

    def test_the_ambiguous_bare_name_would_have_picked_the_wrong_one(self) -> None:
        """**The defect this script exists to fix.** Without it, the
        330-hitpoint one-time quest fight - fought exactly once ever - is
        the fastest of the three ambiguous versions and would have been
        priced as the whole activity."""
        idx = load_monster_index()
        versions = {
            k[len("Duke Sucellus#") :]
            for k in idx
            if k.startswith("Duke Sucellus#")
        }
        assert "Quest, Awake" in versions
        quest = idx.get("Duke Sucellus#Quest, Awake")
        post_quest = idx.get("Duke Sucellus#Post-quest, Awake")
        assert quest is not None and post_quest is not None
        assert quest.hitpoints < post_quest.hitpoints


class TestEffectiveSeconds:
    def test_doubles_the_fight(self) -> None:
        """Prep takes about as long as the fight - this project's own
        stated estimate."""
        assert duke_sucellus.effective_seconds(60.0) == pytest.approx(120.0)

    def test_matches_the_prep_fraction_constant(self) -> None:
        assert duke_sucellus.effective_seconds(90.0) == pytest.approx(
            90.0 * (1.0 + duke_sucellus.PREP_FRACTION)
        )


class TestWiredIntoDpsBridge:
    def test_registered(self) -> None:
        assert dps_bridge.SCRIPTS[duke_sucellus.DUKE_SUCELLUS] is duke_sucellus.SCRIPT

    def test_a_scripted_kill_targets_post_quest(self) -> None:
        picks = {
            "Melee-weapon": "Abyssal whip",
            "Melee-head": "Rune full helm",
        }
        loadouts = dps_bridge.build_loadouts(
            _chunk_info(), picks, {"Attack": 90, "Strength": 90, "Hitpoints": 90}
        )
        idx = load_monster_index()
        versions = dps_bridge.version_index(idx)
        candidates = dps_bridge.candidate_targets(idx, duke_sucellus.DUKE_SUCELLUS, versions)
        kill = dps_bridge.best_kill(
            loadouts, duke_sucellus.DUKE_SUCELLUS, candidates, index=idx, boss=True
        )
        assert kill is not None
        assert kill.match == "scripted"
        target = idx.get("Duke Sucellus#Post-quest, Awake")
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
