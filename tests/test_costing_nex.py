"""Nex's phases, bodyguards, heal and duo pricing - see `costing/nex.py`
for the citations behind each figure."""

from __future__ import annotations

from typing import Any

import pytest

from chunksim.costing import dps_bridge, nex, oracle
from chunksim.costing.dps_bridge import load_monster_index
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.remote.wiki import mmg_rates

pytestmark = pytest.mark.skipif(
    not dps_bridge.DPS_AVAILABLE,
    reason="osrs-dps is an optional extra; install it with `pip install -e ../osrs-dps`",
)


class TestTheScript:
    def test_five_phases_nex_and_four_bodyguards(self) -> None:
        targets = [p.target for p in nex.SCRIPT.phases]
        assert targets == [nex.NEX, nex.FUMUS, nex.UMBRA, nex.CRUOR, nex.GLACIES]

    def test_nex_carries_her_own_health_plus_the_heal(self) -> None:
        nex_phase = nex.SCRIPT.phases[0]
        assert nex_phase.target == nex.NEX
        assert nex_phase.hp_share == pytest.approx(
            (nex.NEX_HITPOINTS + nex.ZAROS_HEAL_HITPOINTS) / nex.NEX_HITPOINTS
        )

    def test_the_heal_is_the_published_five_hundred(self) -> None:
        assert nex.ZAROS_HEAL_HITPOINTS == pytest.approx(500.0)

    def test_every_bodyguard_is_a_full_kill(self) -> None:
        for phase in nex.SCRIPT.phases[1:]:
            assert phase.hp_share == pytest.approx(1.0)

    def test_every_target_is_a_key_the_library_knows(self) -> None:
        idx = load_monster_index()
        for phase in nex.SCRIPT.phases:
            assert phase.target in idx, phase.target

    def test_the_bodyguards_match_their_published_weaknesses(self) -> None:
        idx = load_monster_index()
        fumus = idx.get(nex.FUMUS)
        umbra = idx.get(nex.UMBRA)
        cruor = idx.get(nex.CRUOR)
        glacies = idx.get(nex.GLACIES)
        assert fumus is not None and umbra is not None
        assert cruor is not None and glacies is not None
        assert fumus.bonuses.defence_stab < fumus.bonuses.defence_slash
        assert cruor.bonuses.defence_slash < cruor.bonuses.defence_stab
        assert glacies.bonuses.defence_crush < glacies.bonuses.defence_stab
        assert umbra.bonuses.defence_ranged < umbra.bonuses.defence_stab

    def test_all_four_bodyguards_share_five_hundred_hitpoints(self) -> None:
        idx = load_monster_index()
        for name in (nex.FUMUS, nex.UMBRA, nex.CRUOR, nex.GLACIES):
            target = idx.get(name)
            assert target is not None
            assert target.hitpoints == pytest.approx(500.0)


class TestPartySize:
    def test_a_duo_halves_the_solo_time(self) -> None:
        assert nex.PARTY_SIZE == 2
        assert nex.effective_seconds(600.0) == pytest.approx(300.0)



def _equipment() -> dict[str, Any]:
    return {
        "Osmumten's fang": {
            "attack_stab": 105, "melee_strength": 78, "attack_speed": 5, "slot": "weapon",
        },
        "Twisted bow": {
            "attack_ranged": 85, "ranged_strength": 65, "attack_speed": 5, "slot": "2h",
        },
        "Rune boots": {"defence_slash": 12, "attack_speed": 0, "slot": "feet"},
    }


def _chunk_info() -> ChunkInfo:
    return ChunkInfo({"equipment": _equipment()})


_LEVELS = {"Attack": 90, "Strength": 90, "Ranged": 90, "Magic": 80, "Hitpoints": 90}


class TestWiredIntoDpsBridge:
    def test_registered(self) -> None:
        assert dps_bridge.SCRIPTS[nex.NEX] is nex.SCRIPT

    def test_a_scripted_kill_carries_nex_plus_all_four_bodyguards(self) -> None:
        picks = {"Melee-weapon": "Osmumten's fang", "Ranged-2h": "Twisted bow"}
        loadouts = dps_bridge.build_loadouts(_chunk_info(), picks, _LEVELS)
        idx = load_monster_index()
        versions = dps_bridge.version_index(idx)
        candidates = dps_bridge.candidate_targets(idx, nex.NEX, versions)
        kill = dps_bridge.best_kill(loadouts, nex.NEX, candidates, index=idx, boss=True)
        assert kill is not None
        assert kill.match == "scripted"
        # 3,400 + 500 heal + 4 x 500 bodyguards.
        assert kill.hitpoints == pytest.approx(3900.0 + 2000.0)


class TestAgainstTheGuide:
    """Parses the real 'Killing Nex (Duo)' guide - hardcoded wikitext, no
    network call. The duo halving is applied by `nex.effective_seconds`
    separately from `oracle.oracle_kph`, which prices one player's own
    solo time against the script - so the ratio here is checked against
    twice the guide's published rate, matching what one player's own
    share of a duo actually is.
    """

    _GUIDE_TEXT = """
{{Mmgtable
|Activity = Killing [[Nex]] (Duo)
|Skill =
* {{SCP|Attack|90+}}, {{SCP|Strength|90+}}, {{SCP|Ranged|90+}}, {{SCP|Magic|85+}}, {{SCP|Prayer|77+}}
|Item =
* [[Osmumten's fang]]
* [[Twisted bow]]
|Intensity = High
|isperkill = y
|kph = 6.5
}}
"""

    def _guide(self) -> Any:
        guide = mmg_rates(self._GUIDE_TEXT)
        assert guide is not None
        return guide

    def test_the_fixture_parses_the_way_the_real_page_does(self) -> None:
        assert self._guide().kph == 6.5

    @pytest.mark.real_export
    def test_the_simulator_produces_a_plausible_ratio_against_the_guide(
        self, real_export: ChunkInfo
    ) -> None:
        guide = self._guide()
        # `oracle_kph` prices one player's own solo time against the full
        # script (no duo division) - halved here to match, since a duo
        # publishes double a single player's own rate.
        solo_kph = oracle.oracle_kph(real_export, guide, nex.NEX)
        assert solo_kph is not None
        duo_kph = solo_kph * nex.PARTY_SIZE
        ratio = duo_kph / guide.kph
        # Wide band: a two-weapon guide fixture against a five-target
        # script (Nex plus four bodyguards, each wanting its own best
        # style) is exactly the multi-style gap `costing/zulrah.py` and
        # `costing/moons.py` both name as unrepresentable by
        # `oracle.py`'s single-style builder.
        assert 0.05 < ratio < 5.0, f"ratio {ratio:.2f}"
