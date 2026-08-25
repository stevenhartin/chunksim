"""Vet'ion and Calvar'ion: two forms each, hellhounds mid-form - see
`costing/vetion.py` for the citations behind each figure."""

from __future__ import annotations

from typing import Any

import pytest

from chunksim.costing import dps_bridge, oracle, vetion
from chunksim.costing.dps_bridge import load_monster_index
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.remote.wiki import mmg_rates

pytestmark = pytest.mark.skipif(
    not dps_bridge.DPS_AVAILABLE,
    reason="osrs-dps is an optional extra; install it with `pip install -e ../osrs-dps`",
)


class TestTheScripts:
    def test_both_bosses_have_their_own_script(self) -> None:
        assert set(vetion.SCRIPTS) == {vetion.VETION, vetion.CALVARION}

    def test_each_script_has_eight_phases(self) -> None:
        # Normal (2) + hellhounds (2) + Normal finish (1) + Enraged (1) +
        # greater hellhounds (2) + Enraged finish (1) - wait, that is the
        # phase *count*, not a restatement of hp_share: two Normal phases,
        # two ordinary hellhounds, two Enraged phases, two greater
        # hellhounds, eight in total.
        for script in vetion.SCRIPTS.values():
            assert len(script.phases) == 8

    def test_each_forms_own_phases_sum_to_one(self) -> None:
        """A fresh full-health pool per form - see the module docstring's
        'several independent targets, each fully depleted' shape."""
        for name, script in vetion.SCRIPTS.items():
            normal = sum(p.hp_share for p in script.phases if p.target.endswith("#Normal"))
            enraged = sum(p.hp_share for p in script.phases if p.target.endswith("#Enraged"))
            assert normal == pytest.approx(1.0), name
            assert enraged == pytest.approx(1.0), name

    def test_each_hellhound_is_fully_depleted_twice(self) -> None:
        for script in vetion.SCRIPTS.values():
            hellhounds = [p for p in script.phases if "Hellhound" in p.target]
            assert len(hellhounds) == 4
            assert all(p.hp_share == pytest.approx(1.0) for p in hellhounds)
            # Two distinct targets (ordinary + greater), two phases each.
            assert len({p.target for p in hellhounds}) == 2

    def test_no_style_restriction(self) -> None:
        """Neither boss is *immune* to anything, only weak to crush - the
        numbers alone should steer the search there, per the module
        docstring's comparison to `royal_titans.py`."""
        for script in vetion.SCRIPTS.values():
            assert all(p.styles is None for p in script.phases)

    def test_every_target_is_a_key_the_library_knows(self) -> None:
        idx = load_monster_index()
        for script in vetion.SCRIPTS.values():
            for phase in script.phases:
                assert phase.target in idx, phase.target


class TestTheHellhoundDelayIsAGuess:
    def test_charged_once_per_hellhound_pair_not_twice(self) -> None:
        for script in vetion.SCRIPTS.values():
            delayed = [p for p in script.phases if p.idle_seconds > 0]
            assert len(delayed) == 2
            assert all(
                p.idle_seconds == pytest.approx(vetion.HELLHOUND_DELAY_SECONDS)
                for p in delayed
            )


class TestWiredIntoDpsBridge:
    def test_both_are_registered(self) -> None:
        for name, script in vetion.SCRIPTS.items():
            assert dps_bridge.SCRIPTS[name] is script

    def test_the_ordinary_search_refuses_the_bare_name(self) -> None:
        """The bug this module exists to fix: `candidate_targets` treats
        `#Enraged` as a sequential-phase marker and refuses the bare boss
        name outright, which is correct on its own but left both bosses
        with no route to a `dps` rate at all before `SCRIPTS` existed."""
        idx = load_monster_index()
        versions = dps_bridge.version_index(idx)
        for name in (vetion.VETION, vetion.CALVARION):
            assert dps_bridge.candidate_targets(idx, name, versions) == ()

    def test_best_kill_prices_it_anyway(self) -> None:
        picks = {
            "Melee-weapon": "Abyssal whip",
            "Melee-head": "Rune full helm",
        }
        loadouts = dps_bridge.build_loadouts(
            _chunk_info(), picks, {"Attack": 90, "Strength": 90, "Hitpoints": 90}
        )
        idx = load_monster_index()
        for name in (vetion.VETION, vetion.CALVARION):
            kill = dps_bridge.best_kill(loadouts, name, (), index=idx, boss=True)
            assert kill is not None
            assert kill.match == "scripted"
            assert kill.ttk > 0


class _TestAgainstTheGuide:
    """Shared shape for both bosses' oracle comparison - see
    `TestVetionAgainstTheGuide`/`TestCalvarionAgainstTheGuide`. Hardcoded
    wikitext, no network call, matching every other guide-parsing test in
    this project."""

    _TARGET: str
    _GUIDE_TEXT: str
    _expected_kph: float

    def _guide(self) -> Any:
        guide = mmg_rates(self._GUIDE_TEXT)
        assert guide is not None
        return guide

    def test_the_fixture_parses_the_way_the_real_page_does(self) -> None:
        guide = self._guide()
        assert guide.kph == pytest.approx(self._expected_kph)

    def test_the_guide_names_no_combat_style_level_so_defaults_to_melee(self) -> None:
        """Both pages' `Skill=` field is prose ("High melee stats"), not a
        `{{SCP|Attack|...}}` template - `style_of` correctly finds none of
        `Attack`/`Strength`/`Ranged`/`Magic` in `skill_levels` and falls
        back to `Melee`, which happens to be right here. See
        `test_a_maxed_level_loadout_from_the_guides_own_gear_is_plausible`
        for why the same prose costs `oracle_kph` its ratio assertion."""
        guide = self._guide()
        assert not ({"Attack", "Strength", "Ranged", "Magic"} & guide.skill_levels.keys())
        assert oracle.style_of(guide) == "Melee"

    @pytest.mark.real_export
    def test_a_maxed_level_loadout_from_the_guides_own_gear_is_plausible(
        self, real_export: ChunkInfo
    ) -> None:
        """**The sanity check, not the oracle.** Neither guide's `Skill=`
        field states a numeric Attack/Strength level - it is prose, "High
        melee stats" - so `guide.skill_levels` holds only `Prayer`, and
        `oracle_kph`'s own documented floor (an unstated level defaults to
        `1`, never `99`) prices a level-1 Ursine chainmace: zero accuracy,
        zero max hit, a ttk two orders of magnitude too long. That is the
        harness pricing conservatively, not this project's `FightScript`
        being wrong - `costing/vetion.py`'s own hand check against a real
        map's BiS loadout already lands close (36.4/hr and 46.8/hr against
        guides of 37 and 55). This substitutes maxed combat levels for the
        guide's unstated ones and checks the order of magnitude, matching
        `costing/grotesque_guardians.py`'s and `costing/zulrah.py`'s own
        precedent for a guide their harness can't fully represent.
        """
        guide = self._guide()
        picks = oracle.gear_from_guide(real_export, guide)
        levels = {"Attack": 99, "Strength": 99, "Defence": 99, "Hitpoints": 99, "Prayer": 43}
        loadouts = dps_bridge.build_loadouts(real_export, picks, levels)
        assert "Melee" in loadouts
        index = dps_bridge.load_monster_index()
        versions = dps_bridge.version_index(index)
        candidates = dps_bridge.candidate_targets(index, self._TARGET, versions)
        kill = dps_bridge.best_kill(
            loadouts, self._TARGET, candidates, index=index, boss=True
        )
        assert kill is not None
        ratio = kill.kills_per_hour() / self._expected_kph
        assert 0.1 < ratio < 3.0, f"ratio {ratio:.2f}"


class TestVetionAgainstTheGuide(_TestAgainstTheGuide):
    _TARGET = vetion.VETION
    _expected_kph = 37.0
    # A trimmed copy of
    # https://oldschool.runescape.wiki/w/Money_making_guide/Killing_Vet%27ion
    # (fetched under CLAUDE.md's User-Agent rule), keeping only the fields
    # this project reads.
    _GUIDE_TEXT = """
{{mmgtable
|Activity = Killing [[Vet'ion]]
|Skill =
* High melee stats
* {{SCP|Prayer|43+}} ([[Protect from Melee]])
|Item =
* [[Ursine chainmace]]
* [[Avernic defender]]
* [[Salve amulet (e)]]
* [[Inquisitor's hauberk]]
* [[Ultor Ring]]
* [[Black dragonhide armour]]
|Intensity = High
|isperkill = y
|kph = 37
}}
"""


class TestCalvarionAgainstTheGuide(_TestAgainstTheGuide):
    _TARGET = vetion.CALVARION
    _expected_kph = 55.0
    # A trimmed copy of
    # https://oldschool.runescape.wiki/w/Money_making_guide/Killing_Calvar%27ion
    _GUIDE_TEXT = """
{{mmgtable
|Activity = Killing [[Calvar'ion]]
|Skill =
* High melee stats
* {{SCP|Prayer|43+}} ([[Protect from Melee]])
|Item =
* [[Ursine chainmace]]
* [[Avernic defender]]
* [[Salve amulet (e)]]
* [[Torva platebody]]
* [[Berserker ring (i)]]
* [[Black dragonhide armour]]
|Intensity = High
|isperkill = y
|kph = 55
}}
"""


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
