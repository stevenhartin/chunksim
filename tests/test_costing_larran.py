"""Tests for `costing/larran.py` - see its module docstring for the mechanic,
the wiki formula it ports and what it deliberately does not model."""

from __future__ import annotations

import pytest

from chunksim.costing import larran
from chunksim.costing.heuristics import Heuristics, Superior
from chunksim.costing.slayer import MasterRate, TaskRate
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.remote.combat import MonsterStats


class TestKeyDropChance:
    def test_the_wikis_own_worked_points(self) -> None:
        # https://oldschool.runescape.wiki/w/Larran%27s_key - "1/1972 at
        # level 1 to 1/100 at level 80", and the two pieces agree at the seam.
        assert larran.key_drop_chance(1.0) == pytest.approx(1.0 / 1972.0)
        assert larran.key_drop_chance(80.0) == pytest.approx(1.0 / 100.0)
        assert larran.key_drop_chance(81.0) == pytest.approx(1.0 / 100.0)
        assert larran.key_drop_chance(350.0) == pytest.approx(1.0 / 50.0)

    def test_capped_at_1_50_past_level_350(self) -> None:
        assert larran.key_drop_chance(1000.0) == pytest.approx(1.0 / 50.0)

    def test_an_unknown_level_is_zero_not_a_guess(self) -> None:
        assert larran.key_drop_chance(0.0) == 0.0
        assert larran.key_drop_chance(-5.0) == 0.0


def _info(
    slayer_monsters: dict[str, int] | None = None,
    slayer_tasks: dict[str, dict[str, bool]] | None = None,
) -> ChunkInfo:
    """`slayer_tasks` is the authoritative `task -> {monster: ...}` join
    (`codeItems.slayerTasks`), kept separate from `slayer_monsters` (the
    Slayer-level-requirement list) so a test can put a monster on a task
    without also, as a side effect, making it "require a Slayer level"."""
    return ChunkInfo(
        {
            "slayerMonsters": slayer_monsters or {},
            "codeItems": {"slayerTasks": slayer_tasks or {}},
        }
    )


class TestRequiresSlayerLevel:
    def test_a_bare_name_matches(self) -> None:
        info = _info({"Abyssal demon": 85})
        assert larran._requires_slayer_level(info, "Abyssal demon")

    def test_a_variant_suffixed_name_still_matches_the_bare_monster(self) -> None:
        info = _info({"Cave bug#Level 96": 7})
        assert larran._requires_slayer_level(info, "Cave bug")

    def test_an_unlisted_monster_does_not(self) -> None:
        info = _info({"Abyssal demon": 85})
        assert not larran._requires_slayer_level(info, "Cow")


class TestMonsterKeyChance:
    def test_matches_the_widely_quoted_abyssal_demon_figure(self) -> None:
        """Abyssal demon: combat level 124, Slayer-gated. Unmodified that is
        `1/92`; with the wiki's own +20% it is `1/76.67`, matching the
        community's "roughly 1 in 76" without either number being hand fed."""
        info = _info({"Abyssal demon": 85})
        heuristics = Heuristics(
            monster_stats={"Abyssal demon": MonsterStats(name="Abyssal demon", hitpoints=150, combat_level=124)}
        )
        chance = larran._monster_key_chance(info, heuristics, "Abyssal demon")
        assert chance == pytest.approx((1.0 / 92.0) * 1.20)

    def test_no_slayer_requirement_gets_no_bonus(self) -> None:
        info = _info({})
        heuristics = Heuristics(
            monster_stats={"Cow": MonsterStats(name="Cow", hitpoints=8, combat_level=2)}
        )
        chance = larran._monster_key_chance(info, heuristics, "Cow")
        assert chance == pytest.approx(larran.key_drop_chance(2.0))

    def test_no_stated_combat_level_is_none_not_zero(self) -> None:
        info = _info({})
        heuristics = Heuristics(
            monster_stats={"Ghost": MonsterStats(name="Ghost", hitpoints=1)}
        )
        assert larran._monster_key_chance(info, heuristics, "Ghost") is None

    def test_an_unscraped_monster_is_none(self) -> None:
        assert larran._monster_key_chance(_info(), Heuristics(), "Nothing") is None


def _krystilia(*tasks: TaskRate) -> MasterRate:
    return MasterRate(master="Krystilia", xp_per_hour=0.0, tasks=tasks)


class TestKeysPerHour:
    def test_a_single_task_matches_hand_arithmetic(self) -> None:
        """One task, one monster: `weight/total * mean_count * chance /
        average_hours` should equal the direct kills-per-hour-implied rate,
        since with one task `average_hours` is just that task's own."""
        info = _info(
            {"Abyssal demon": 85},
            slayer_tasks={"Abyssal demons": {"Abyssal demon": True}},
        )
        heuristics = Heuristics(
            monster_stats={
                "Abyssal demon": MonsterStats(name="Abyssal demon", hitpoints=150, combat_level=124)
            }
        )
        task = TaskRate(
            task="Abyssal demons", weight=100.0, mean_count=100.0,
            xp_per_kill=150.0, kills_per_hour=100.0,
        )
        master = _krystilia(task)

        rate = larran.keys_per_hour(master, info, heuristics, frozenset({"Abyssal demon"}))

        chance = (1.0 / 92.0) * 1.20
        kills_per_hour = task.mean_count / task.hours
        assert rate == pytest.approx(chance * kills_per_hour)

    def test_weighted_across_two_tasks_by_time_not_by_count(self) -> None:
        """A slow task's kills matter for longer than a fast one's - the same
        time-weighted shape `slayer.superior_rolls_per_hour` already uses."""
        info = _info(
            slayer_tasks={"Cows": {"Cow": True}, "Jellies": {"Jelly": True}},
        )
        heuristics = Heuristics(
            monster_stats={
                "Cow": MonsterStats(name="Cow", hitpoints=8, combat_level=2),
                "Jelly": MonsterStats(name="Jelly", hitpoints=55, combat_level=61),
            }
        )
        cows = TaskRate(task="Cows", weight=1.0, mean_count=10.0, xp_per_kill=1.0, kills_per_hour=100.0)
        jellies = TaskRate(task="Jellies", weight=1.0, mean_count=10.0, xp_per_kill=1.0, kills_per_hour=10.0)
        master = _krystilia(cows, jellies)

        rate = larran.keys_per_hour(master, info, heuristics, frozenset({"Cow", "Jelly"}))

        cow_chance = larran.key_drop_chance(2.0)
        jelly_chance = larran.key_drop_chance(61.0)
        per_assignment = 0.5 * 10.0 * cow_chance + 0.5 * 10.0 * jelly_chance
        assert rate == pytest.approx(per_assignment / master.average_hours)

    def test_an_unreachable_monster_contributes_nothing(self) -> None:
        info = _info({})
        heuristics = Heuristics(
            monster_stats={"Cow": MonsterStats(name="Cow", hitpoints=8, combat_level=2)}
        )
        task = TaskRate(task="Cows", weight=1.0, mean_count=10.0, xp_per_kill=1.0, kills_per_hour=100.0)
        master = _krystilia(task)

        assert larran.keys_per_hour(master, info, heuristics, frozenset()) == 0.0

    def test_no_tasks_at_all_is_zero(self) -> None:
        master = _krystilia()
        assert larran.keys_per_hour(master, _info(), Heuristics(), frozenset()) == 0.0

    def test_a_superior_spawn_adds_a_guaranteed_key_on_top(self) -> None:
        """"Superior slayer monsters... will always drop a key on death" -
        `slayer.superior_spawns_per_hour` is exactly that rate, added flat."""
        info = _info(slayer_tasks={"Cows": {"Cow": True}})
        heuristics = Heuristics(
            monster_stats={"Cow": MonsterStats(name="Cow", hitpoints=8, combat_level=2)},
            superiors={"Cowier": Superior(name="Cowier", base="Cow", spawn_rate=0.01)},
        )
        task = TaskRate(task="Cows", weight=1.0, mean_count=10.0, xp_per_kill=1.0, kills_per_hour=100.0)
        master = _krystilia(task)

        without_superior = larran.keys_per_hour(
            master, info, Heuristics(monster_stats=heuristics.monster_stats), frozenset({"Cow"})
        )
        with_superior = larran.keys_per_hour(master, info, heuristics, frozenset({"Cow"}))

        assert with_superior > without_superior


class TestEffectiveSeconds:
    def test_adds_the_open_action_on_top_of_the_key(self) -> None:
        got = larran.effective_seconds(2.0)  # one key every half hour
        assert got == pytest.approx(1800.0 + larran.OPEN_SECONDS)

    def test_a_non_positive_rate_is_none(self) -> None:
        assert larran.effective_seconds(0.0) is None
        assert larran.effective_seconds(-1.0) is None


class TestPriced:
    def test_no_master_is_a_no_op(self) -> None:
        heuristics = Heuristics()
        assert larran.priced(heuristics, None, _info(), frozenset()) is heuristics

    def test_both_chests_get_the_identical_rate(self) -> None:
        info = _info(
            {"Abyssal demon": 85},
            slayer_tasks={"Abyssal demons": {"Abyssal demon": True}},
        )
        heuristics = Heuristics(
            monster_stats={
                "Abyssal demon": MonsterStats(name="Abyssal demon", hitpoints=150, combat_level=124)
            }
        )
        task = TaskRate(
            task="Abyssal demons", weight=1.0, mean_count=100.0,
            xp_per_kill=150.0, kills_per_hour=100.0,
        )
        master = _krystilia(task)

        result = larran.priced(heuristics, master, info, frozenset({"Abyssal demon"}))

        small = result.kills_per_hour(larran.SMALL_CHEST)
        big = result.kills_per_hour(larran.BIG_CHEST)
        assert small.value > 0
        assert small == big
        assert not small.source.startswith("default")

    def test_no_reachable_candidate_still_writes_an_explicit_zero(self) -> None:
        """Written explicitly rather than left absent - the same rule
        `dps_bridge._apply_gated_bosses` follows, so a reader never mistakes
        "no route" for "nothing asked"."""
        task = TaskRate(task="Cows", weight=1.0, mean_count=10.0, xp_per_kill=1.0, kills_per_hour=100.0)
        master = _krystilia(task)

        result = larran.priced(Heuristics(), master, _info(), frozenset())

        assert larran.SMALL_CHEST in result.monsters
        assert result.monsters[larran.SMALL_CHEST].value == 0.0
