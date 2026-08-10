"""Tests for `costing/combat_xp.py` and `remote/combat.py`.

The arithmetic is small and the constants are the wiki's, so these mostly pin
the things that were easy to get wrong: Magic being 2 per damage rather than 4,
a default kill rate not being multiplied by real hitpoints, and an icon column
not being read as a spell name.
"""

from __future__ import annotations

import pytest

from fray_claude.costing.combat_xp import (
    CAST_SECONDS,
    HITPOINTS_XP_PER_DAMAGE,
    MAGIC_XP_PER_DAMAGE,
    XP_PER_DAMAGE,
    best_spell,
    best_target,
    combat_rates,
    farmable_providers,
    hitpoints_credit,
    spawn_caps,
)
from fray_claude.costing.heuristics import Heuristics, Rate
from fray_claude.remote.combat import (
    AttackSpell,
    MonsterStats,
    parse_attack_spells,
    parse_monster_stats,
)
from fray_claude.derive.active_tasks import TaskClassification
from fray_claude.derive.bis import BisResult
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.derive.challenges import ChallengeResult
from fray_claude.derive.other_tasks import OtherTasks
from fray_claude.derive.pipeline import Derived
from fray_claude.derive.sources import SourceIndex


def _derived(monsters: tuple[str, ...]) -> Derived:
    return Derived(
        reachable_sections={},
        expanded_chunks={"100": True},
        source_index=SourceIndex(
            items={},
            objects={},
            monsters={name: {"100": True} for name in monsters},
            npcs={},
            shops={},
            drop_rates={},
        ),
        challenges=ChallengeResult(valid={}, unsupported=frozenset()),
        bis=BisResult(picks={}),
        task_classification=TaskClassification(),
        other_tasks=OtherTasks(),
    )


_STATS = {
    "Wolf": MonsterStats(name="Wolf", hitpoints=69.0),
    "Mithril dragon": MonsterStats(name="Mithril dragon", hitpoints=254.0, experience_bonus=5.0),
}


def test_damage_per_hour_is_kills_times_hitpoints() -> None:
    derived = _derived(("Wolf",))
    heuristics = Heuristics(monsters={"Wolf": Rate(1000.0, "test", "exact")})

    target = best_target(derived, heuristics, _STATS)

    assert target is not None
    assert target.damage_per_hour == pytest.approx(1000.0 * 69.0)


def test_an_xp_multiplier_is_a_percentage() -> None:
    """`experience_bonus` of 5 means 5% more, not 5x. Reading it as a factor
    would make a Mithril dragon five times the trainer it is."""
    derived = _derived(("Mithril dragon",))
    heuristics = Heuristics(monsters={"Mithril dragon": Rate(10.0, "test", "exact")})

    target = best_target(derived, heuristics, _STATS)

    assert target is not None
    assert target.xp_multiplier == pytest.approx(1.05)
    assert target.damage_per_hour == pytest.approx(10.0 * 254.0 * 1.05)


def test_a_monster_with_only_a_default_kill_rate_is_refused() -> None:
    """**A guessed rate must not be multiplied by real hitpoints.** The
    product looks like a measurement and is not one."""
    derived = _derived(("Wolf",))

    assert best_target(derived, Heuristics(), _STATS) is None


def test_magic_is_two_experience_per_damage_and_the_rest_are_four() -> None:
    """The mistake this exists to prevent: the wiki is explicit that Magic is
    2 per damage where melee and Ranged are 4, and it is a factor of two on
    the whole climb."""
    derived = _derived(("Wolf",))
    heuristics = Heuristics(monsters={"Wolf": Rate(100.0, "test", "exact")})
    damage = 100.0 * 69.0

    rates, _ = combat_rates(derived, heuristics, _STATS, (), {"Magic": 1})

    assert rates["Strength"].value == pytest.approx(damage * XP_PER_DAMAGE)
    assert rates["Ranged"].value == pytest.approx(damage * XP_PER_DAMAGE)
    assert rates["Magic"].value == pytest.approx(damage * MAGIC_XP_PER_DAMAGE)
    assert rates["Hitpoints"].value == pytest.approx(damage * HITPOINTS_XP_PER_DAMAGE)


def test_a_cast_pays_its_base_experience_on_top_of_the_damage() -> None:
    """Two thirds of a Magic rate is the casting, so leaving it out is not a
    rounding error."""
    derived = _derived(("Wolf",))
    heuristics = Heuristics(monsters={"Wolf": Rate(100.0, "test", "exact")})
    spells = (AttackSpell(name="Ice Barrage", level=94, experience=52.0),)

    rates, _ = combat_rates(derived, heuristics, _STATS, spells, {"Magic": 94})

    expected = 100.0 * 69.0 * MAGIC_XP_PER_DAMAGE + 52.0 * 3600.0 / CAST_SECONDS
    assert rates["Magic"].value == pytest.approx(expected)
    assert "Ice Barrage" in rates["Magic"].source


def test_the_best_spell_is_the_one_that_pays_most_not_the_highest_level() -> None:
    """Fire Surge is level 95 and 50.5 xp; Ice Barrage is 94 and 52. Taking
    the highest castable *level* quietly takes the worse one."""
    spells = (
        AttackSpell(name="Ice Barrage", level=94, experience=52.0),
        AttackSpell(name="Fire Surge", level=95, experience=50.5),
    )

    assert best_spell(spells, 99) is not None
    assert best_spell(spells, 99).name == "Ice Barrage"  # type: ignore[union-attr]
    assert best_spell(spells, 94).name == "Ice Barrage"  # type: ignore[union-attr]
    assert best_spell(spells, 50) is None


def test_a_monster_with_no_hitpoints_is_dropped_rather_than_zeroed() -> None:
    """A zero would make it free to kill and infinitely fast to train on."""
    parsed = parse_monster_stats(
        [
            {"name": "Ghost", "hitpoints": 0},
            {"name": "Nothing", "hitpoints": None},
            {"name": "Wolf", "hitpoints": 69, "experience_bonus": 0},
        ]
    )

    assert set(parsed) == {"Wolf"}


def test_the_first_version_of_a_monster_wins() -> None:
    """`TzHaar-Xil` has three rows. Whichever the iteration ends on is not a
    decision anyone made."""
    parsed = parse_monster_stats(
        [
            {"name": "TzHaar-Xil", "hitpoints": 120},
            {"name": "TzHaar-Xil", "hitpoints": 999},
        ]
    )

    assert parsed["TzHaar-Xil"].hitpoints == 120.0


def test_an_icon_column_is_not_a_spell_name() -> None:
    """Ancient Magicks leads with two image columns, and `[[File:Ice
    Barrage.png]]` is a perfectly good link target - it just names a picture."""
    page = """
{| class="wikitable"
!class="unsortable"|Icon
!class="unsortable" |Mobile icon
!Spell
!Level
!class="unsortable"|Runes
!Coins
!XP
!Base max hit
!Effect
|-
|[[File:Ice Barrage.png]]
|[[File:Ice Barrage (mobile).png]]
|[[Ice Barrage]]
|94
|{{RuneReq|Blood=2|Ice=6|Death=4}}
|1000
|52
|30
|Freezes.
|}
"""
    (spell,) = parse_attack_spells({"Ancient Magicks": page})

    assert (spell.name, spell.level, spell.experience) == ("Ice Barrage", 94, 52.0)


def test_a_table_with_no_max_hit_column_contributes_nothing() -> None:
    """**The filter that keeps Charge out.** `infobox_spell` cannot tell an
    attack spell from a utility one - Fire Surge, Charge and Vengeance have
    identical infoboxes - so the attack table is identified by its max-hit
    column, and a utility table has none."""
    page = """
{| class="wikitable"
!colspan=2|Spell
!Level
!class="unsortable"|Runes
!XP
!Members
|-
|{{plinkt|Charge}}
|80
|{{RuneReq|Air=3}}
|180
|{{members|yes}}
|}
"""
    assert parse_attack_spells({"Standard spellbook": page}) == ()


def test_hitpoints_is_credited_with_what_the_other_climbs_earn() -> None:
    """**Hitpoints is not a climb you make.** Every point of damage paying 4 XP
    to Strength pays 1.33 to Hitpoints at the same instant, so charging for
    both in full bills the same hours twice."""
    hours = {"Strength": 10.0, "Ranged": 5.0}
    damage = {"Strength": 40_000.0, "Ranged": 30_000.0}

    credit = hitpoints_credit(hours, damage)

    assert credit == pytest.approx((10.0 * 40_000 + 5.0 * 30_000) * HITPOINTS_XP_PER_DAMAGE)


def test_the_hitpoints_climb_does_not_credit_itself() -> None:
    """Its own hours are the thing being reduced; counting them would be
    circular and would zero the skill outright."""
    credit = hitpoints_credit({"Hitpoints": 100.0}, {"Hitpoints": 50_000.0})

    assert credit == 0.0


def test_a_monster_you_can_only_meet_inside_a_raid_is_not_a_training_target() -> None:
    """**Reachable is not farmable.** The export places 21 monsters in
    `Chambers of Xeric` and the derivation rightly calls them reachable - you
    really can get their drops by doing the raid. What you cannot do is kill
    Muttadile over and over to train Strength."""
    derived = _derived(("Muttadile#Small", "Bloodveld"))
    object.__setattr__(
        derived.source_index,
        "monsters",
        {
            "Muttadile#Small": {"Chambers of Xeric": True},
            "Bloodveld": {"Chambers of Xeric": True, "Catacombs of Kourend": True},
        },
    )

    farmable = farmable_providers(derived)

    assert "Muttadile#Small" not in farmable
    # Reachable in a raid *and* somewhere you can stand: still farmable.
    assert "Bloodveld" in farmable


def test_a_spawn_cap_bounds_a_kill_rate_by_what_the_map_holds() -> None:
    """A chunk holding two of something cannot supply 900 kills an hour
    whatever the gear says."""
    info = ChunkInfo({"chunks": {"100": {"Monster": {"Wolf": 2}}}})
    derived = _derived(("Wolf",))

    caps = spawn_caps(info, derived, respawn=30.0)

    assert caps["Wolf"] == pytest.approx(2 * 3600 / 30)


def test_a_monster_with_no_counted_spawn_is_not_capped_at_zero() -> None:
    """`skillItems` activities and superiors are reachable providers with no
    square of their own; capping those at nothing would delete them."""
    info = ChunkInfo({"chunks": {"100": {}}})

    assert spawn_caps(info, _derived(("Wolf",))) == {}
