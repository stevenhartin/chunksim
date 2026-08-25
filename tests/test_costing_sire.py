"""The Abyssal Sire's `FightScript`, its wiring into `dps_bridge`, and the
guide comparison - see `costing/sire.py` for the citations behind each
figure."""

from __future__ import annotations

from typing import Any

import pytest

from chunksim.costing import dps_bridge, oracle, sire
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.remote.wiki import mmg_rates

pytestmark = pytest.mark.skipif(
    not dps_bridge.DPS_AVAILABLE,
    reason="osrs-dps is an optional extra; install it with `pip install -e ../osrs-dps`",
)


class TestTheScript:
    """The wiki's own published thresholds, pinned - see `costing/sire.py`
    for the citations behind each figure."""

    def test_the_lung_phase_kills_four_respiratory_systems(self) -> None:
        lungs = sire.SCRIPT.phases[0]
        assert lungs.target == "Respiratory system"
        assert lungs.hp_share == pytest.approx(4.0)

    def test_the_three_combat_thresholds_sum_to_the_whole_health_bar(self) -> None:
        """210 and 140 are the wiki's own published thresholds - not this
        project's arithmetic."""
        combat = sire.SCRIPT.phases[1:]
        shares = [p.hp_share for p in combat]
        assert shares == pytest.approx([215.0 / 425.0, 70.0 / 425.0, 140.0 / 425.0])
        assert sum(shares) == pytest.approx(1.0)

    def test_the_targets_are_the_librarys_own_phase_keys(self) -> None:
        targets = [phase.target for phase in sire.SCRIPT.phases]
        assert targets == [
            "Respiratory system",
            "Abyssal Sire#Phase 2",
            "Abyssal Sire#Phase 3 (stage 1)",
            "Abyssal Sire#Phase 3 (stage 2)",
        ]

    def test_every_target_is_a_key_the_library_knows(self) -> None:
        index = dps_bridge.load_monster_index()
        for phase in sire.SCRIPT.phases:
            assert phase.target in index, phase.target

    def test_every_combat_phase_is_transitioned_none_excepted(self) -> None:
        """Unlike the Hydra's 'barring the last phase', the Sire's own
        update log describes the 50% reduction in the plural - all three
        combat phases carry it."""
        for phase in sire.SCRIPT.phases[1:]:
            assert phase.reduced_seconds == sire.TRANSITION_SECONDS
            assert phase.reduced_dps_fraction == pytest.approx(0.5)
        assert sire.SCRIPT.phases[0].reduced_seconds == 0.0

    def test_the_lung_phase_carries_no_guessed_constant(self) -> None:
        """The four-kills mechanic is published outright; only the
        transition duration on the combat phases is this project's own
        figure."""
        assert sire.SCRIPT.phases[0].reduced_seconds == 0.0
        assert sire.SCRIPT.phases[0].idle_seconds == 0.0


def _equipment() -> dict[str, Any]:
    return {
        "Twisted bow": {
            "attack_ranged": 20,
            "ranged_strength": 20,
            "attack_speed": 5,
            "slot": "2h",
        },
        "Rune boots": {"defence_slash": 12, "attack_speed": 0, "slot": "feet"},
    }


def _chunk_info() -> ChunkInfo:
    return ChunkInfo({"equipment": _equipment()})


_LEVELS = {"Attack": 80, "Strength": 80, "Ranged": 90, "Magic": 80, "Hitpoints": 90}


class TestWiredIntoDpsBridge:
    """The registry interception in `dps_bridge.best_kill` - see its
    docstring on why a scripted boss is checked before ordinary version
    resolution."""

    def test_the_sire_is_registered(self) -> None:
        assert dps_bridge.SCRIPTS["Abyssal Sire"] is sire.SCRIPT

    def _kill(self) -> "dps_bridge.KillEstimate | None":
        picks = {"Ranged-2h": "Twisted bow", "Ranged-feet": "Rune boots"}
        loadouts = dps_bridge.build_loadouts(_chunk_info(), picks, _LEVELS)
        index = dps_bridge.load_monster_index()
        versions = dps_bridge.version_index(index)
        candidates = dps_bridge.candidate_targets(index, "Abyssal Sire", versions)
        return dps_bridge.best_kill(
            loadouts, "Abyssal Sire", candidates, index=index, boss=True
        )

    def test_a_scripted_kill_is_marked_as_one(self) -> None:
        kill = self._kill()
        assert kill is not None
        assert kill.match == "scripted"

    def test_without_the_index_the_lung_phase_cannot_resolve(self) -> None:
        """**Proves the `index` fallback is load-bearing, not cosmetic.**
        `candidate_targets(index, "Abyssal Sire", versions)` only ever
        returns `Abyssal Sire#...` keys - `Respiratory system` is a
        different monster and is never among them, so without `index` to
        fall back to, the lung phase's target can never be found and the
        whole script must refuse."""
        picks = {"Ranged-2h": "Twisted bow", "Ranged-feet": "Rune boots"}
        loadouts = dps_bridge.build_loadouts(_chunk_info(), picks, _LEVELS)
        index = dps_bridge.load_monster_index()
        versions = dps_bridge.version_index(index)
        candidates = dps_bridge.candidate_targets(index, "Abyssal Sire", versions)
        assert "Respiratory system" not in dict(candidates)
        kill = dps_bridge.best_kill(loadouts, "Abyssal Sire", candidates, boss=True)
        assert kill is None

    def test_the_full_fight_is_carried_lungs_and_all(self) -> None:
        """`hitpoints` on a `KillEstimate` is the sum of every phase's own
        `target.hitpoints * hp_share` - the four 50-hp respiratory systems
        (200) plus the Sire's own 425, not either alone."""
        kill = self._kill()
        assert kill is not None
        assert kill.hitpoints == pytest.approx(200.0 + 425.0)

    def test_candidates_missing_a_phase_key_refuses_rather_than_partial_prices(self) -> None:
        """`_scripted_kill` requires every phase's target present in
        `candidates` - a stale or incomplete index must not silently price
        three of the four phases as if that were the whole fight."""
        index = dps_bridge.load_monster_index()
        picks = {"Ranged-2h": "Twisted bow", "Ranged-feet": "Rune boots"}
        loadouts = dps_bridge.build_loadouts(_chunk_info(), picks, _LEVELS)
        partial = []
        for key in ("Respiratory system", "Abyssal Sire#Phase 2"):
            target = index.get(key)
            assert target is not None
            partial.append((key, target))
        # No `index=` here on purpose - this pins the candidates-only
        # refusal, not the index fallback `test_a_scripted_kill_is_marked_as_one`
        # already exercises.
        kill = dps_bridge.best_kill(loadouts, "Abyssal Sire", tuple(partial), boss=True)
        assert kill is None


class TestAgainstTheGuide:
    """Parses the real 'Killing the Abyssal Sire' guide, but stops short of
    a `kph` ratio assertion - see the class-level note below on why.

    Uses hardcoded wikitext, matching every other guide-parsing test in this
    project: no network call here.
    """

    # A trimmed copy of https://oldschool.runescape.wiki/w/Money_making_guide/Killing_the_Abyssal_Sire
    # (fetched under CLAUDE.md's User-Agent rule), keeping only the fields
    # this project reads.
    _GUIDE_TEXT = """
{{Mmgtable
|Activity = Killing the [[Abyssal Sire]]
|Skill =
* {{SCP|Slayer|85}}
* {{SCP|Attack|85+}}, {{SCP|Strength}}, {{SCP|Defence}} recommended
* {{SCP|Ranged|85+}} recommended
* {{SCP|Magic|92+}} recommended
* {{SCP|Prayer|70+}} recommended
* {{SCP|Construction|84+}} recommended for [[Fairy ring (Construction)|Fairy ring]] and [[Ornate rejuvenation pool]]
|Item =
* '''For recommended equipment and recommended inventory, see this page:'''
* [[Abyssal Sire/Strategies#Equipment|Abyssal Sire Strategies (Equipment)]]
|isperkill = y
|kph = 39
|Input1 = Divine super combat potion(4)
|Input1num = 3
}}
"""

    def _guide(self) -> Any:
        guide = mmg_rates(self._GUIDE_TEXT)
        assert guide is not None
        return guide

    def test_the_fixture_parses_the_way_the_real_page_does(self) -> None:
        guide = self._guide()
        assert guide.kph == 39.0
        assert guide.skill_levels == {
            "Slayer": 85,
            "Attack": 85,
            "Ranged": 85,
            "Magic": 92,
            "Prayer": 70,
            "Construction": 84,
        }

    def test_the_guide_is_read_as_a_ranged_guide(self) -> None:
        """Ranged is checked before Magic in `_STYLE_SKILLS`, and both are
        stated here - matches the guide's own primary strategy."""
        assert oracle.style_of(self._guide()) == "Ranged"

    @pytest.mark.real_export
    def test_the_guides_own_item_field_names_no_real_equipment(
        self, real_export: ChunkInfo
    ) -> None:
        """**The gap this test documents rather than works around.** Unlike
        every other boss guide in this subpackage, the Sire's own `Item=`
        field is not a gear list at all - it is a single sentence pointing
        at `Abyssal Sire/Strategies#Equipment`, a separate page laid out as
        a full phase-by-phase equipment table, a shape `oracle.py`'s
        `[[link]]`-scraping `gear_from_guide` was never built to parse (see
        that module's docstring on what it does and does not attempt).
        `gear_links` therefore resolves to no real armour or weapon at all,
        and `oracle_kph` is correctly `None` rather than a number computed
        from an empty, bare-handed loadout - checked here so a future
        `gear_from_guide` improvement that starts finding *something* is a
        deliberate decision to update this test, not a silent drift.
        """
        picks = oracle.gear_from_guide(real_export, self._guide())
        assert picks == {}
        kph = oracle.oracle_kph(real_export, self._guide(), "Abyssal Sire")
        assert kph is None
