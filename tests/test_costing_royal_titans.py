"""The Royal Titans: two identical bosses, one shared encounter - see
`costing/royal_titans.py` for the citations behind each figure."""

from __future__ import annotations

import pytest

from chunksim.costing import dps_bridge, royal_titans
from chunksim.costing.dps_bridge import load_monster_index
from chunksim.model.chunkinfo import ChunkInfo

pytestmark = pytest.mark.skipif(
    not dps_bridge.DPS_AVAILABLE,
    reason="osrs-dps is an optional extra; install it with `pip install -e ../osrs-dps`",
)


class TestTheScripts:
    def test_both_titans_have_their_own_script(self) -> None:
        assert set(royal_titans.SCRIPTS) == {royal_titans.ELDRIC, royal_titans.BRANDA}

    def test_each_script_prices_twelve_hundred_hitpoints(self) -> None:
        """Both titans, 600 hitpoints each - `hp_share=2.0` against one
        stat block since the two are identical."""
        for name, script in royal_titans.SCRIPTS.items():
            assert len(script.phases) == 1
            assert script.phases[0].hp_share == pytest.approx(2.0)
            assert script.phases[0].target == name

    def test_both_targets_are_keys_the_library_knows(self) -> None:
        idx = load_monster_index()
        for name in (royal_titans.ELDRIC, royal_titans.BRANDA):
            assert name in idx, name

    def test_the_two_titans_are_genuinely_identical_stat_blocks(self) -> None:
        """The premise this module is built on - not assumed, checked."""
        idx = load_monster_index()
        eldric = idx.get(royal_titans.ELDRIC)
        branda = idx.get(royal_titans.BRANDA)
        assert eldric is not None and branda is not None
        assert eldric.hitpoints == branda.hitpoints == 600
        assert eldric.bonuses == branda.bonuses


class TestWiredIntoDpsBridge:
    def test_both_are_registered(self) -> None:
        for name, script in royal_titans.SCRIPTS.items():
            assert dps_bridge.SCRIPTS[name] is script

    def test_eldric_and_branda_price_identically(self) -> None:
        """Same stat blocks, same `hp_share=2.0` - a loadout must price
        both to the same kill time."""
        picks = {
            "Melee-weapon": "Abyssal whip",
            "Melee-head": "Rune full helm",
        }
        loadouts = dps_bridge.build_loadouts(
            _chunk_info(), picks, {"Attack": 90, "Strength": 90, "Hitpoints": 90}
        )
        index = load_monster_index()
        versions = dps_bridge.version_index(index)
        results = {}
        for name in (royal_titans.ELDRIC, royal_titans.BRANDA):
            candidates = dps_bridge.candidate_targets(index, name, versions)
            kill = dps_bridge.best_kill(loadouts, name, candidates, index=index, boss=True)
            assert kill is not None
            assert kill.match == "scripted"
            results[name] = kill
        assert results[royal_titans.ELDRIC].ttk == pytest.approx(
            results[royal_titans.BRANDA].ttk
        )
        assert results[royal_titans.ELDRIC].hitpoints == pytest.approx(1200.0)


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
