"""Tests for the estimator's bucketing and its item walk."""

from __future__ import annotations

from typing import Any

import pytest

from fray_claude.derive.active_tasks import SkillClassification, TaskClassification
from fray_claude.derive.bis import BisResult
from fray_claude.derive.challenges import ChallengeResult
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.costing.estimate import estimate
from fray_claude.costing.training import training_options
from fray_claude.costing.levels import goal_levels, infer_levels, reachable_providers, task_gated_monsters
from fray_claude.costing.heuristics import (
    DEFAULT_XP_PER_HOUR,
    Heuristics,
    QuestRate,
    Rate,
    SlayerTask,
    Superior,
)
from fray_claude.derive.other_tasks import CategoryTasks, OtherTasks, TaskGroup
from fray_claude.derive.pipeline import Derived, MapState
from fray_claude.derive.search import build_world_index
from fray_claude.derive.sources import SourceIndex


def _state(info: ChunkInfo, **overrides: Any) -> MapState:
    defaults: dict[str, Any] = {
        "chunk_info": info,
        "rules": {},
        "settings": {},
        "manual_sections": {},
        "manual_areas": {},
        "manual_monsters": {},
        "manual_equipment": {},
        "backlogged_sources": {},
        "max_skill": {},
        "passive_skill": {},
        "completed_challenges": {},
        "checked_challenges": {},
        "manual_tasks": {},
        "backlog": {},
        "active_tasks": {},
    }
    defaults.update(overrides)
    return MapState(**defaults)


def _derived(*, monsters: tuple[str, ...] = (), **overrides: Any) -> Derived:
    """`monsters` are the ones reachable on this map - the estimator prices
    nothing it cannot reach, so a fixture that omits them prices nothing."""
    defaults: dict[str, Any] = {
        "reachable_sections": {},
        "expanded_chunks": {"100": True},
        "source_index": SourceIndex(
            items={},
            objects={},
            monsters={name: {"100": True} for name in monsters},
            npcs={},
            shops={},
            drop_rates={},
        ),
        "challenges": ChallengeResult(valid={}, unsupported=frozenset()),
        "bis": BisResult(picks={}),
        "task_classification": TaskClassification(),
        "other_tasks": OtherTasks(),
    }
    defaults.update(overrides)
    return Derived(**defaults)


def _run(info: ChunkInfo, derived: Derived, heuristics: Heuristics, **kwargs: Any) -> Any:
    state = _state(info, **{k: v for k, v in kwargs.items() if k == "passive_skill"})
    return estimate(
        state,
        derived,
        build_world_index(info),
        heuristics,
        level_overrides=kwargs.get("level_overrides"),
    )


# --- the item walk ---------------------------------------------------------


def test_a_boss_drop_costs_one_over_the_rate_divided_by_kills_per_hour() -> None:
    # 1/381 at 27 kills an hour is 381/27 = 14.11 hours - the worked example
    # this estimator was specified against.
    info = ChunkInfo(
        {
            "drops": {"General Graardor": {"Bandos chestplate": {"1": "1/381"}}},
            "codeItems": {"bossMonsters": {"General Graardor": True}},
            "challenges": {"Extra": {"Obtain a ~|bandos chestplate|~": {"Items": ["Bandos chestplate"]}}},
        }
    )
    derived = _derived(
        monsters=("General Graardor",),
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra",
                    groups=(TaskGroup(name="Boss", active=("Obtain a ~|bandos chestplate|~",)),),
                )
            }
        ),
    )
    heuristics = Heuristics(monsters={"General Graardor": Rate(27.0, "mmg:x", "exact")})

    result = _run(info, derived, heuristics)

    assert result.items[0].hours == pytest.approx(381 / 27)
    assert result.items[0].bucket == "boss drops"


def test_a_non_boss_provider_lands_in_activities() -> None:
    info = ChunkInfo(
        {
            "drops": {"Goblin": {"Bones": {"1": "1/10"}}},
            "challenges": {"Extra": {"Obtain ~|bones|~": {"Items": ["Bones"]}}},
        }
    )
    derived = _derived(
        monsters=("Goblin",),
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra", groups=(TaskGroup(name="X", active=("Obtain ~|bones|~",)),)
                )
            }
        ),
    )

    result = _run(info, derived, Heuristics(monsters={"Goblin": Rate(100.0)}))

    assert result.items[0].bucket == "activities"
    assert result.items[0].hours == pytest.approx(10 / 100)


def test_a_worded_rate_is_priced_through_the_config() -> None:
    # `Always` and friends are 1,197 of the export's rate entries and parse
    # to `nan`; the config is what turns them into a number.
    info = ChunkInfo(
        {
            "drops": {"Goblin": {"Bones": {"1": "Always"}}},
            "challenges": {"Extra": {"Obtain ~|bones|~": {"Items": ["Bones"]}}},
        }
    )
    derived = _derived(
        monsters=("Goblin",),
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra", groups=(TaskGroup(name="X", active=("Obtain ~|bones|~",)),)
                )
            }
        ),
    )

    result = _run(info, derived, Heuristics(monsters={"Goblin": Rate(50.0)}))

    assert result.items[0].hours == pytest.approx(1 / 50)


def test_an_item_with_no_priceable_route_is_reported_unpriced() -> None:
    # `Varies`/`Unknown` say nothing, so the task is admitted as a gap rather
    # than dropped or guessed at.
    info = ChunkInfo(
        {
            "drops": {"Goblin": {"Bones": {"1": "Varies"}}},
            "challenges": {"Extra": {"Obtain ~|bones|~": {"Items": ["Bones"]}}},
        }
    )
    derived = _derived(
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra", groups=(TaskGroup(name="X", active=("Obtain ~|bones|~",)),)
                )
            }
        )
    )

    result = _run(info, derived, Heuristics())

    assert result.unpriced == ("Bones",)
    assert result.items == ()


def test_a_made_item_costs_its_inputs() -> None:
    info = ChunkInfo(
        {
            "drops": {"Goblin": {"Bones": {"1": "1/10"}}},
            "challenges": {
                "Crafting": {"Carve a ~|bone ring|~": {"Items": ["Bones"], "Output": "Bone ring"}},
                "Extra": {"Obtain a ~|bone ring|~": {"Items": ["Bone ring"]}},
            },
        }
    )
    derived = _derived(
        monsters=("Goblin",),
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra",
                    groups=(TaskGroup(name="X", active=("Obtain a ~|bone ring|~",)),),
                )
            }
        ),
    )

    result = _run(info, derived, Heuristics(monsters={"Goblin": Rate(100.0)}))

    assert result.items[0].hours == pytest.approx(10 / 100)
    assert result.items[0].detail.startswith("make:")


def test_a_cycle_of_made_items_is_unpriced_rather_than_recursing() -> None:
    # A needs B needs A. Without the visited set this never returns.
    info = ChunkInfo(
        {
            "challenges": {
                "Crafting": {
                    "Make ~|a|~": {"Items": ["B"], "Output": "A"},
                    "Make ~|b|~": {"Items": ["A"], "Output": "B"},
                },
                "Extra": {"Obtain ~|A|~": {"Items": ["A"]}},
            }
        }
    )
    derived = _derived(
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra", groups=(TaskGroup(name="X", active=("Obtain ~|A|~",)),)
                )
            }
        )
    )

    result = _run(info, derived, Heuristics())

    assert result.unpriced == ("A",)


# --- quests ----------------------------------------------------------------


def test_a_part_done_quest_costs_the_remaining_fraction() -> None:
    # 2 of 8 steps left on a 4-hour quest is one hour.
    info = ChunkInfo({})
    derived = _derived(
        challenges=ChallengeResult(
            valid={"Quest": {f"~|Big Quest|~ {n}": True for n in range(1, 9)}},
            unsupported=frozenset(),
        ),
        other_tasks=OtherTasks(
            categories={
                "Quest": CategoryTasks(
                    category="Quest",
                    groups=(
                        TaskGroup(name="Big Quest", active=("~|Big Quest|~ 7", "~|Big Quest|~ 8")),
                    ),
                )
            }
        ),
    )
    heuristics = Heuristics(
        quests={"Big Quest": QuestRate(hours=4.0, length="Long", source="wiki")}
    )

    result = _run(info, derived, heuristics)

    assert result.buckets["quests"] == pytest.approx(1.0)
    assert "2/8 steps" in result.tasks[0].detail


# --- skilling --------------------------------------------------------------


def _skilling_info() -> ChunkInfo:
    return ChunkInfo(
        {
            "challenges": {
                "Mining": {
                    "Mine a ~|rune ore|~": {"Level": 85},
                    "Mine ~|slow rocks|~": {"Primary": True, "Level": 1},
                    "Mine ~|fast rocks|~": {"Primary": True, "Level": 40},
                    "Mine ~|locked rocks|~": {"Primary": True, "Level": 1},
                }
            }
        }
    )


def _skilling_derived() -> Derived:
    return _derived(
        challenges=ChallengeResult(
            valid={
                "Mining": {
                    "Mine a ~|rune ore|~": 85,
                    "Mine ~|slow rocks|~": 1,
                    "Mine ~|fast rocks|~": 40,
                }
            },
            unsupported=frozenset(),
        ),
        task_classification=TaskClassification(
            skills={
                "Mining": SkillClassification(
                    active="Mine a ~|rune ore|~", obsolete=frozenset(), completed=frozenset()
                )
            }
        ),
    )


def test_the_fastest_reachable_method_sets_the_rate() -> None:
    heuristics = Heuristics(
        training={
            "Mine ~|slow rocks|~": {"Mining": Rate(10_000.0, "mmg:a", "exact")},
            "Mine ~|fast rocks|~": {"Mining": Rate(50_000.0, "mmg:b", "exact")},
        }
    )

    result = _run(
        _skilling_info(), _skilling_derived(), heuristics, level_overrides={"Mining": 50}
    )

    skill = result.skills[0]
    assert skill.xp_per_hour == 50_000.0
    assert skill.method == "fast rocks"
    assert skill.hours == pytest.approx(skill.xp / 50_000.0)


def test_a_method_above_the_current_level_starts_its_own_band() -> None:
    """**This test is the defect, inverted.**

    It used to assert that a method needing level 40 was "passed over" at level
    30 - and it was, for the *whole* climb to 85, which is how a skill came to
    be priced at a rate it would outgrow within a few hours. You do not train
    to 85 at the level-30 method; you train to 40 at it and then switch.

    So the level-40 method is not passed over, it opens the second band.
    """
    heuristics = Heuristics(
        training={
            "Mine ~|slow rocks|~": {"Mining": Rate(10_000.0, "mmg:a", "exact")},
            "Mine ~|fast rocks|~": {"Mining": Rate(50_000.0, "mmg:b", "exact")},
        }
    )

    result = _run(
        _skilling_info(), _skilling_derived(), heuristics, level_overrides={"Mining": 30}
    )

    mining = result.skills[0]
    assert [(band.level_from, band.level_to, band.method) for band in mining.bands] == [
        (30, 40, "slow rocks"),
        (40, 85, "fast rocks"),
    ]
    # The blended rate is neither method's, and the hours are the sum.
    assert mining.hours == sum(band.hours for band in mining.bands)
    assert 10_000 < mining.xp_per_hour < 50_000
    # `method` names the band that trains the most XP, so the row still reads
    # as one line for anyone not opening the bands.
    assert mining.method == "fast rocks"


def test_a_method_that_is_not_valid_is_never_considered() -> None:
    # `locked rocks` is Primary and Level 1 but absent from `valid`, i.e. not
    # reachable on this map. Accessibility is read, not assumed.
    heuristics = Heuristics(
        training={
            "Mine ~|slow rocks|~": {"Mining": Rate(10_000.0, "mmg:a", "exact")},
            "Mine ~|locked rocks|~": {"Mining": Rate(99_000.0, "mmg:c", "exact")},
        }
    )

    result = _run(
        _skilling_info(), _skilling_derived(), heuristics, level_overrides={"Mining": 50}
    )

    assert result.skills[0].method == "slow rocks"


def test_a_skill_with_no_joined_method_is_flagged_as_defaulted() -> None:
    result = _run(
        _skilling_info(), _skilling_derived(), Heuristics(), level_overrides={"Mining": 50}
    )

    assert result.skills[0].defaulted is True
    assert result.skills[0].xp_per_hour == DEFAULT_XP_PER_HOUR


def test_the_level_override_beats_the_passive_floor() -> None:
    # The map records no current level; `passive_skill` is the floor and an
    # override replaces it. See the module docstring.
    lower = _run(_skilling_info(), _skilling_derived(), Heuristics(), passive_skill={"Mining": 1})
    higher = _run(
        _skilling_info(),
        _skilling_derived(),
        Heuristics(),
        passive_skill={"Mining": 1},
        level_overrides={"Mining": 84},
    )

    assert higher.skills[0].current_level == 84
    assert higher.skills[0].xp < lower.skills[0].xp


# --- reachability and slayer-task gates -------------------------------------


def _bones_task(info: ChunkInfo, **derived_kwargs: Any) -> Derived:
    return _derived(
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra", groups=(TaskGroup(name="X", active=("Obtain ~|bones|~",)),)
                )
            }
        ),
        **derived_kwargs,
    )


def test_a_monster_outside_the_unlocked_chunks_is_not_priced() -> None:
    # The bug this gate exists for: `Colossal Hydra` is a skillItems.Slayer
    # activity with 43 drops and no chunk anywhere, and was being costed as
    # though you could go and fight one.
    info = ChunkInfo(
        {
            "drops": {"Goblin": {"Bones": {"1": "1/10"}}},
            "challenges": {"Extra": {"Obtain ~|bones|~": {"Items": ["Bones"]}}},
        }
    )

    result = _run(info, _bones_task(info), Heuristics(monsters={"Goblin": Rate(100.0)}))

    assert result.unpriced == ("Bones",)


def _gated_info() -> ChunkInfo:
    return ChunkInfo(
        {
            "drops": {"Grotesque Guardians": {"Granite maul": {"1": "1/100"}}},
            "challenges": {"Extra": {"Obtain a ~|granite maul|~": {"Items": ["Granite maul"]}}},
            "codeItems": {"slayerTasks": {"Gargoyles": {"Grotesque Guardians": True}}},
            "taskUnlocks": {
                "Monsters": {
                    "Grotesque Guardians": {
                        "Grotesque Guardians' Lair": [{"Gargoyle task": "Nonskill"}]
                    }
                }
            },
            "slayerMasterTasks": {
                "Vannaka": {"Gargoyles": {"Weight": 1}, "Bats": {"Weight": 9}},
                "Duradel": {"Gargoyles": {"Weight": 9}, "Bats": {"Weight": 1}},
            },
        }
    )


def _gated_derived() -> Derived:
    derived = _derived(
        monsters=("Grotesque Guardians",),
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra",
                    groups=(TaskGroup(name="X", active=("Obtain a ~|granite maul|~",)),),
                )
            }
        ),
    )
    # Vannaka is the only master whose NPC is in an unlocked chunk.
    return Derived(
        reachable_sections=derived.reachable_sections,
        expanded_chunks=derived.expanded_chunks,
        source_index=SourceIndex(
            items={},
            objects={},
            monsters=derived.source_index.monsters,
            npcs={"Vannaka": {"100": True}},
            shops={},
            drop_rates={},
        ),
        challenges=derived.challenges,
        bis=derived.bis,
        task_classification=derived.task_classification,
        other_tasks=derived.other_tasks,
    )


def _gated_heuristics() -> Heuristics:
    return Heuristics(
        monsters={"Grotesque Guardians": Rate(20.0)},
        slayer={
            master: {
                "Gargoyles": SlayerTask(mean_count=100, xp_per_kill=10, kills_per_hour=20),
                "Bats": SlayerTask(mean_count=100, xp_per_kill=10, kills_per_hour=100),
            }
            for master in ("Vannaka", "Duradel")
        },
    )


def test_task_gated_monsters_are_read_out_of_task_unlocks() -> None:
    info = _gated_info()
    gates = task_gated_monsters(info, build_world_index(info), frozenset({"100"}))

    assert gates == {"Grotesque Guardians": "Gargoyles"}


def test_a_monster_reachable_somewhere_ungated_is_not_gated() -> None:
    # Aberrant spectres need a task in the Stronghold Slayer Cave and nowhere
    # else; gating the monster outright made a 1/512 drop off them cost 1,707
    # hours instead of 8.
    info = ChunkInfo(
        {
            "chunks": {
                "13623": {"Monster": {"Aberrant spectre": 1}},
                "Stronghold Slayer Cave": {"Monster": {"Aberrant spectre": 1}},
            },
            "codeItems": {"slayerTasks": {"Aberrant spectres": {"Aberrant spectre": True}}},
            "taskUnlocks": {
                "Monsters": {
                    "Aberrant spectre": {
                        "Stronghold Slayer Cave": [{"Aberrant spectre task": "Nonskill"}]
                    }
                }
            },
        }
    )
    world = build_world_index(info)

    # The Slayer Tower chunk is open, so no task is needed.
    assert task_gated_monsters(info, world, frozenset({"13623"})) == {}
    # With only the gated cave reachable, the task is unavoidable again.
    assert task_gated_monsters(info, world, frozenset({"Stronghold Slayer Cave"})) == {
        "Aberrant spectre": "Aberrant spectres"
    }


def test_a_task_gated_kill_includes_the_wait_for_the_task() -> None:
    # Vannaka: P(Gargoyles) = 1/10 and an average task of
    # (1*100/20 + 9*100/100)/10 = (5 + 9)/10 = 1.4h, so the wait is 14h.
    # One assignment of 100 covers the 100 kills needed, and killing them
    # takes 100/20 = 5h. Total 19h - against 5h if the task were ignored.
    result = _run(_gated_info(), _gated_derived(), _gated_heuristics())

    assert result.items[0].hours == pytest.approx(19.0)
    assert "on Gargoyles task" in result.items[0].detail


def test_an_unreachable_master_cannot_supply_the_task() -> None:
    # Duradel assigns gargoyles nine times as often, but is not in any
    # unlocked chunk - picking him would price a task you can never be given.
    result = _run(_gated_info(), _gated_derived(), _gated_heuristics())

    assert result.items[0].hours == pytest.approx(19.0)  # Vannaka's 14h wait, not Duradel's


def test_a_task_gated_kill_with_no_reachable_master_is_unpriced() -> None:
    derived = _derived(
        monsters=("Grotesque Guardians",),
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra",
                    groups=(TaskGroup(name="X", active=("Obtain a ~|granite maul|~",)),),
                )
            }
        ),
    )

    result = _run(_gated_info(), derived, _gated_heuristics())

    # No master NPC reachable, so no way to be assigned - not a free kill.
    assert result.unpriced == ("Granite maul",)


def test_a_superior_is_priced_through_its_base_monster() -> None:
    # 1/200 spawn, then a 1/10 drop off the superior: 2,000 base kills at
    # 100/hr = 20h.
    info = ChunkInfo(
        {
            "skillItems": {"Slayer": {"Marble gargoyle": {"Granite maul": {"1": "1/10"}}}},
            "challenges": {"Extra": {"Obtain a ~|granite maul|~": {"Items": ["Granite maul"]}}},
        }
    )
    derived = _derived(
        monsters=("Gargoyle",),
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra",
                    groups=(TaskGroup(name="X", active=("Obtain a ~|granite maul|~",)),),
                )
            }
        ),
    )
    heuristics = Heuristics(
        monsters={"Gargoyle": Rate(100.0)},
        superiors={"Marble gargoyle": Superior("Marble gargoyle", "Gargoyle", 1 / 200)},
    )

    result = _run(info, derived, heuristics)

    assert result.items[0].hours == pytest.approx(20.0)
    assert "(superior) <- Gargoyle" in result.items[0].detail


def test_a_superior_whose_base_is_unreachable_is_unpriced() -> None:
    info = ChunkInfo(
        {
            "skillItems": {"Slayer": {"Colossal Hydra": {"Granite maul": {"1": "1/10"}}}},
            "challenges": {"Extra": {"Obtain a ~|granite maul|~": {"Items": ["Granite maul"]}}},
        }
    )
    derived = _derived(
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra",
                    groups=(TaskGroup(name="X", active=("Obtain a ~|granite maul|~",)),),
                )
            }
        )
    )
    heuristics = Heuristics(
        superiors={"Colossal Hydra": Superior("Colossal Hydra", "Hydra", 1 / 200)}
    )

    result = _run(info, derived, heuristics)

    assert result.unpriced == ("Granite maul",)


def test_one_item_wanted_by_several_tasks_is_costed_once() -> None:
    # The real shape: an abyssal whip answers a BiS pick, a Slayer log entry
    # and the Abyssal Sire's own log entry. It is obtained once.
    info = ChunkInfo(
        {
            "drops": {"Abyssal demon": {"Abyssal whip": {"1": "1/512"}}},
            "challenges": {
                "Extra": {
                    "(Abyssal Sire) Obtain an ~|abyssal whip|~": {"Items": ["Abyssal whip"]},
                    "(Slayer) Obtain an ~|abyssal whip|~": {"Items": ["Abyssal whip"]},
                }
            },
        }
    )
    derived = _derived(
        monsters=("Abyssal demon",),
        bis=BisResult(picks={}, active={"Obtain an ~|abyssal whip|~": "weapon"}),
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra",
                    groups=(
                        TaskGroup(
                            name="X",
                            active=(
                                "(Abyssal Sire) Obtain an ~|abyssal whip|~",
                                "(Slayer) Obtain an ~|abyssal whip|~",
                            ),
                        ),
                    ),
                )
            }
        ),
    )

    result = _run(info, derived, Heuristics(monsters={"Abyssal demon": Rate(100.0)}))

    assert len(result.items) == 1
    assert result.items[0].item == "Abyssal whip"
    assert len(result.items[0].tasks) == 3
    # Charged once, not three times.
    assert result.total_hours == pytest.approx(512 / 100)


def test_a_task_needing_two_items_pays_for_both() -> None:
    # Two items from *different* sources, so nothing is earned in parallel
    # and the costs genuinely add. (Same-source items are clamped instead -
    # see `test_items_from_one_source_are_earned_together`.)
    info = ChunkInfo(
        {
            "drops": {"Goblin": {"Bones": {"1": "1/10"}}, "Imp": {"Beads": {"1": "1/20"}}},
            "challenges": {"Extra": {"Obtain ~|both|~": {"Items": ["Bones", "Beads"]}}},
        }
    )
    derived = _derived(
        monsters=("Goblin", "Imp"),
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra", groups=(TaskGroup(name="X", active=("Obtain ~|both|~",)),)
                )
            }
        ),
    )

    result = _run(
        info, derived, Heuristics(monsters={"Goblin": Rate(100.0), "Imp": Rate(100.0)})
    )

    assert {item.item for item in result.items} == {"Bones", "Beads"}
    assert result.total_hours == pytest.approx(10 / 100 + 20 / 100)


def _two_drops(rate_a: str, rate_b: str, *, same_monster: bool = True) -> tuple[Any, Any]:
    monsters = ("Abyssal demon",) if same_monster else ("Abyssal demon", "Goblin")
    drops: dict[str, Any] = {"Abyssal demon": {"Abyssal dagger": {"1": rate_a}}}
    if same_monster:
        drops["Abyssal demon"]["Abyssal head"] = {"1": rate_b}
    else:
        drops["Goblin"] = {"Abyssal head": {"1": rate_b}}
    info = ChunkInfo(
        {
            "drops": drops,
            "challenges": {
                "Extra": {
                    "Obtain a ~|abyssal dagger|~": {"Items": ["Abyssal dagger"]},
                    "Obtain a ~|abyssal head|~": {"Items": ["Abyssal head"]},
                }
            },
        }
    )
    derived = _derived(
        monsters=monsters,
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra",
                    groups=(
                        TaskGroup(
                            name="X",
                            active=(
                                "Obtain a ~|abyssal dagger|~",
                                "Obtain a ~|abyssal head|~",
                            ),
                        ),
                    ),
                )
            }
        ),
    )
    return info, derived


def test_items_from_one_source_are_earned_together() -> None:
    # 1/1000 at 100/hr is 10h; 1/100 is 1h. You get the second on the way to
    # the first, so the source costs 10h and not 11.
    info, derived = _two_drops("1/1000", "1/100")

    result = _run(info, derived, Heuristics(monsters={"Abyssal demon": Rate(100.0)}))

    assert result.buckets["activities"] == pytest.approx(10.0)
    assert result.total_hours == pytest.approx(10.0)


def test_the_individual_hours_are_still_reported() -> None:
    # "How long for this one thing" and "how long for all of it" are
    # different questions; clamping the total must not erase the first.
    info, derived = _two_drops("1/1000", "1/100")

    result = _run(info, derived, Heuristics(monsters={"Abyssal demon": Rate(100.0)}))

    assert {item.item: item.hours for item in result.items} == {
        "Abyssal dagger": pytest.approx(10.0),
        "Abyssal head": pytest.approx(1.0),
    }


def test_items_from_different_sources_still_add_up() -> None:
    # Nothing is earned in parallel here, so the clamp must not apply.
    info, derived = _two_drops("1/1000", "1/100", same_monster=False)
    heuristics = Heuristics(
        monsters={"Abyssal demon": Rate(100.0), "Goblin": Rate(100.0)}
    )

    result = _run(info, derived, heuristics)

    assert result.buckets["activities"] == pytest.approx(11.0)


def test_sources_in_groups_items_under_what_earns_them() -> None:
    info, derived = _two_drops("1/1000", "1/100")

    result = _run(info, derived, Heuristics(monsters={"Abyssal demon": Rate(100.0)}))
    groups = result.sources_in("activities")

    assert len(groups) == 1
    source, hours, items = groups[0]
    assert source == "Abyssal demon"
    assert hours == pytest.approx(10.0)
    assert len(items) == 2


def test_a_superior_shares_its_base_monsters_source() -> None:
    # You are killing the base monster either way, so its own drops and the
    # superior's accrue at the same time.
    info = ChunkInfo(
        {
            "drops": {"Gargoyle": {"Granite maul": {"1": "1/100"}}},
            "skillItems": {"Slayer": {"Marble gargoyle": {"Granite ring": {"1": "1/10"}}}},
            "challenges": {
                "Extra": {
                    "Obtain a ~|granite maul|~": {"Items": ["Granite maul"]},
                    "Obtain a ~|granite ring|~": {"Items": ["Granite ring"]},
                }
            },
        }
    )
    derived = _derived(
        monsters=("Gargoyle",),
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra",
                    groups=(
                        TaskGroup(
                            name="X",
                            active=(
                                "Obtain a ~|granite maul|~",
                                "Obtain a ~|granite ring|~",
                            ),
                        ),
                    ),
                )
            }
        ),
    )
    heuristics = Heuristics(
        monsters={"Gargoyle": Rate(100.0)},
        superiors={"Marble gargoyle": Superior("Marble gargoyle", "Gargoyle", 1 / 200)},
    )

    result = _run(info, derived, heuristics)

    assert {item.source for item in result.items} == {"Gargoyle"}
    # 1/200 spawn then 1/10 drop = 2,000 kills at 100/hr = 20h, which covers
    # the maul's 1h along the way.
    assert result.buckets["activities"] == pytest.approx(20.0)


def test_the_shared_superior_table_is_one_source_across_a_master() -> None:
    # You never hunt a particular superior: you take a master's assignments
    # and price what turns up. Both items come off the same rolls, so they
    # are one source and the bucket takes the longer.
    info = ChunkInfo(
        {
            "slayerMasterTasks": {"Vannaka": {"Abyssal demons": {"Weight": 1}}},
            "slayerMonsters": {"Abyssal demon": 85},
            "codeItems": {
                "dropTables": {
                    "SuperiorDropTable+": {"Imbued heart": "1/8@1", "Dust battlestaff": "3/8@1"}
                }
            },
            "skillItems": {
                "Slayer": {"Greater abyssal demon": {"SuperiorDropTable+": {"1": "1/2"}}}
            },
            "challenges": {
                "Extra": {
                    "Obtain an ~|imbued heart|~": {"Items": ["Imbued heart"]},
                    "Obtain a ~|dust battlestaff|~": {"Items": ["Dust battlestaff"]},
                }
            },
        }
    )
    derived = Derived(
        reachable_sections={},
        expanded_chunks={"100": True},
        source_index=SourceIndex(
            items={},
            objects={},
            monsters={"Abyssal demon": {"100": True}},
            npcs={"Vannaka": {"100": True}},
            shops={},
            drop_rates={},
        ),
        challenges=ChallengeResult(valid={}, unsupported=frozenset()),
        bis=BisResult(picks={}),
        task_classification=TaskClassification(),
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra",
                    groups=(
                        TaskGroup(
                            name="X",
                            active=(
                                "Obtain an ~|imbued heart|~",
                                "Obtain a ~|dust battlestaff|~",
                            ),
                        ),
                    ),
                )
            }
        ),
    )
    heuristics = Heuristics(
        slayer={"Vannaka": {"Abyssal demons": SlayerTask(100, 10, 100)}},
        superiors={
            "Greater abyssal demon": Superior("Greater abyssal demon", "Abyssal demon", 1 / 200)
        },
    )

    result = _run(info, derived, heuristics)

    # 100 kills an assignment at 1/200 supers rolling 1/2 = 0.25 rolls an
    # assignment, over 1h, so 0.25 rolls an hour. The heart is 1/8 of a roll
    # (8 rolls = 32h) and the staff 3/8 (2.67 rolls = 10.67h).
    by_item = {item.item: item.hours for item in result.items}
    assert by_item["Imbued heart"] == pytest.approx(32.0)
    assert by_item["Dust battlestaff"] == pytest.approx(32.0 / 3)
    assert {item.source for item in result.items} == {"superiors:Vannaka"}
    # One pool, so the bucket is the longer of the two and not their sum.
    assert result.buckets["activities"] == pytest.approx(32.0)


def test_every_reachable_slayer_master_is_reported() -> None:
    # XP rate is not the only reason to pick a master, so the estimate names
    # the one it used and shows the rest to compare against.
    info = ChunkInfo(
        {
            "slayerMasterTasks": {
                "Vannaka": {"Bats": {"Weight": 1}},
                "Mazchna": {"Bats": {"Weight": 1}},
                "Duradel": {"Bats": {"Weight": 1}},
            },
            "challenges": {},
        }
    )
    derived = Derived(
        reachable_sections={},
        expanded_chunks={"100": True},
        source_index=SourceIndex(
            items={},
            objects={},
            monsters={},
            npcs={"Vannaka": {"100": True}, "Mazchna": {"100": True}},
            shops={},
            drop_rates={},
        ),
        challenges=ChallengeResult(valid={}, unsupported=frozenset()),
        bis=BisResult(picks={}),
        task_classification=TaskClassification(),
        other_tasks=OtherTasks(),
    )
    heuristics = Heuristics(
        slayer={
            "Vannaka": {"Bats": SlayerTask(100, 50, 100)},
            "Mazchna": {"Bats": SlayerTask(100, 10, 100)},
            "Duradel": {"Bats": SlayerTask(100, 99, 100)},
        }
    )

    result = _run(info, derived, heuristics)

    # Duradel is faster but unreachable, so he is not offered at all.
    assert [rate.master for rate in result.slayer_masters] == ["Vannaka", "Mazchna"]
    assert result.slayer is not None and result.slayer.master == "Vannaka"


def test_levels_are_inferred_from_completed_challenges() -> None:
    # The ledger is the evidence: buying a Defence cape is not something a
    # player under 99 Defence has done, and `passiveSkill` names none of it.
    info = ChunkInfo(
        {
            "challenges": {
                "Defence": {
                    "Buy the ~|Defence cape|~": {"Level": 99},
                    "Wear melee ~|barrows armour|~": {"Level": 70},
                    "Wear ~|dragon armour|~": {"Level": 60},
                    "Wear something else": {"Level": 120},
                }
            }
        }
    )
    state = _state(
        info,
        passive_skill={"Slayer": 45},
        completed_challenges={
            "Defence": {
                "Buy the ~|Defence cape|~": True,
                "Wear melee ~|barrows armour|~": True,
                "Wear ~|dragon armour|~": True,
            }
        },
    )

    levels = infer_levels(state)

    assert levels["Defence"] == 99
    # passiveSkill still counts; the highest floor wins.
    assert levels["Slayer"] == 45


def test_an_uncompleted_challenge_proves_nothing() -> None:
    info = ChunkInfo({"challenges": {"Attack": {"Wield a ~|godsword|~": {"Level": 75}}}})
    state = _state(info, completed_challenges={})

    assert "Attack" not in infer_levels(state)


def test_goal_levels_raise_the_floor_to_what_the_chunk_is_working_towards() -> None:
    # Slayer inferred at 45 with an active goal needing 92: by the end of the
    # chunk it is 92, and that is the task list a master will be offering for
    # most of it.
    info = ChunkInfo(
        {"challenges": {"Slayer": {"Slay an ~|araxyte|~": {"Level": 92, "Primary": False}}}}
    )
    state = _state(info, passive_skill={"Slayer": 45})
    derived = _derived(
        task_classification=TaskClassification(
            skills={
                "Slayer": SkillClassification(
                    active="Slay an ~|araxyte|~", obsolete=frozenset(), completed=frozenset()
                )
            }
        )
    )

    assert infer_levels(state)["Slayer"] == 45
    assert goal_levels(state, derived, infer_levels(state))["Slayer"] == 92


def test_a_skill_with_no_active_goal_keeps_its_floor() -> None:
    info = ChunkInfo({"challenges": {}})
    state = _state(info, passive_skill={"Mining": 70})

    assert goal_levels(state, _derived(), infer_levels(state))["Mining"] == 70


def test_an_object_can_provide_an_item() -> None:
    # `skillItems` activities are only *usually* monsters. Larran's big chest
    # is an Object with 34 drops, and a monsters-only availability gate
    # refused all of them.
    info = ChunkInfo(
        {
            "skillItems": {"Nonskill": {"Larran's big chest": {"Dagon'hai robe bottom": {"1": "1/256"}}}},
            "challenges": {
                "Extra": {"Obtain a ~|robe|~": {"Items": ["Dagon'hai robe bottom"]}}
            },
        }
    )
    derived = Derived(
        reachable_sections={},
        expanded_chunks={"100": True},
        source_index=SourceIndex(
            items={},
            objects={"Larran's big chest": {"100": True}},
            monsters={},
            npcs={},
            shops={},
            drop_rates={},
        ),
        challenges=ChallengeResult(valid={}, unsupported=frozenset()),
        bis=BisResult(picks={}),
        task_classification=TaskClassification(),
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra",
                    groups=(TaskGroup(name="X", active=("Obtain a ~|robe|~",)),),
                )
            }
        ),
    )

    result = _run(info, derived, Heuristics())

    assert result.unpriced == ()
    assert result.items[0].source == "Larran's big chest"


def test_a_task_wanting_a_kill_rather_than_an_item_is_priced_as_one_kill() -> None:
    # "Kill an abyssal demon in the Slayer Tower" has Monsters and no Items.
    # Taking its `~|...|~` span produced a request for an item called
    # `Morytania Diary#Elite`, which had no route and read as unpriced.
    info = ChunkInfo(
        {
            "challenges": {
                "Diary": {
                    "~|Morytania Diary#Elite|~ Task 5": {"Monsters": ["Abyssal demon"]}
                }
            }
        }
    )
    derived = _derived(
        monsters=("Abyssal demon",),
        other_tasks=OtherTasks(
            categories={
                "Diary": CategoryTasks(
                    category="Diary",
                    groups=(
                        TaskGroup(name="X", active=("~|Morytania Diary#Elite|~ Task 5",)),
                    ),
                )
            }
        ),
    )

    result = _run(info, derived, Heuristics(monsters={"Abyssal demon": Rate(60.0)}))

    assert result.unpriced == ()
    assert result.items[0].item == "kill Abyssal demon"
    assert result.items[0].hours == pytest.approx(1 / 60)



def test_every_kill_rate_lookup_is_gated_on_the_providers_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**The property that makes restricting the DPS pricing safe.**

    `dps_bridge.enrich` prices only `reachable_providers(derived)` rather than
    every monster in the export - 188 against 753 on the real map, which is
    where most of a repricing's time went. That is sound only because *every*
    `Heuristics.kills_per_hour` call in this module is gated on the same set:
    `_kill_hours` takes its provider from it, `_superior_hours` refuses a base
    outside it, `_required_kills` skips a monster outside it.

    So the assertion is not "the total still matches" - it does, to four
    decimal places - but "nothing asked about a monster we stopped pricing".
    A new lookup site that forgot the gate would quietly start reading a
    scraped rate where it read a computed one, and the only symptom would be
    a number moving.
    """
    info = ChunkInfo(
        {
            "drops": {
                "General Graardor": {"Bandos chestplate": {"1": "1/381"}},
                "Corporeal Beast": {"Spectral sigil": {"1": "1/1365"}},
            },
            "codeItems": {"bossMonsters": {"General Graardor": True, "Corporeal Beast": True}},
            "challenges": {
                "Extra": {
                    "Obtain a ~|bandos chestplate|~": {"Items": ["Bandos chestplate"]},
                    "Obtain a ~|spectral sigil|~": {"Items": ["Spectral sigil"]},
                }
            },
        }
    )
    # Both tasks are active; only one of the two monsters is on this map.
    derived = _derived(
        monsters=("General Graardor",),
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra",
                    groups=(
                        TaskGroup(
                            name="Boss",
                            active=(
                                "Obtain a ~|bandos chestplate|~",
                                "Obtain a ~|spectral sigil|~",
                            ),
                        ),
                    ),
                )
            }
        ),
    )
    asked: list[str] = []
    original = Heuristics.kills_per_hour

    def spy(self: Heuristics, monster: str) -> Rate:
        asked.append(monster)
        return original(self, monster)

    monkeypatch.setattr(Heuristics, "kills_per_hour", spy)

    _run(info, derived, Heuristics(monsters={"General Graardor": Rate(27.0)}))

    assert asked, "nothing was priced at all, so this would prove nothing"
    assert not set(asked) - reachable_providers(derived)
    assert "Corporeal Beast" not in asked


def test_the_providers_set_is_the_three_source_branches() -> None:
    """Monsters alone is the tempting wrong answer and was the first one: a
    `skillItems` activity is only *usually* a monster, so a monsters-only gate
    refused `Larran's big chest` - an Object - and the 34 drops behind it."""
    derived = _derived(
        monsters=("Abyssal demon",),
        source_index=SourceIndex(
            items={},
            objects={"Larran's big chest": {"100": True}},
            monsters={"Abyssal demon": {"100": True}},
            npcs={"Zahur": {"100": True}},
            shops={},
            drop_rates={},
        ),
    )

    assert reachable_providers(derived) == frozenset(
        {"Abyssal demon", "Larran's big chest", "Zahur"}
    )


def test_a_skill_with_no_training_method_anywhere_is_refused_not_priced() -> None:
    """**Attack, Defence, Hitpoints and Ranged carry no `Primary` challenge in
    the whole export** - you train them by fighting, not by an activity the
    export lists.

    The old code divided by a zero rate and reported the climb as free: `verf`
    showed 288,199 Attack XP at 0.0 hours. Pricing it at the floor instead
    would say 288 hours, wrong the other way and in the headline. So it is
    refused, the way an item with no route is refused.
    """
    info = ChunkInfo({"challenges": {"Attack": {"Reach ~|Attack|~ 70": {"Level": 70}}}})
    derived = _derived(
        challenges=ChallengeResult(
            valid={"Attack": {"Reach ~|Attack|~ 70": 70}}, unsupported=frozenset()
        ),
        task_classification=TaskClassification(
            skills={
                "Attack": SkillClassification(
                    active="Reach ~|Attack|~ 70", obsolete=frozenset(), completed=frozenset()
                )
            }
        ),
    )

    result = _run(info, derived, Heuristics(), level_overrides={"Attack": 65})

    assert result.skills == ()
    assert [(s.skill, s.xp, s.reason) for s in result.unpriced_skills] == [
        ("Attack", 288_199, "no training method exists for this skill")
    ]
    assert result.buckets["skilling"] == 0.0


def test_a_shop_is_only_free_if_this_map_can_reach_it() -> None:
    """**`WorldIndex` spans the whole world, and a shop route did not check.**

    Every *kill* route is hard-gated on reachability - "availability is not
    negotiable" - but a shop or ground spawn priced at zero wherever it was, so
    an item stocked by any of the export's 435 shops beat every other route
    outright. It barely moved the item bucket, and it is decisive for anything
    priced per action: eye of newt, grimy guam leaf and snapdragon are all
    stocked or spawned *somewhere*, so an ingredient walk without this gate
    concludes that every recipe's inputs are instant.
    """
    info = ChunkInfo(
        {
            "shopItems": {"A shop far away": {"Eye of newt": True}},
            "challenges": {"Extra": {"Obtain an ~|eye of newt|~": {"Items": ["Eye of newt"]}}},
        }
    )
    derived = _derived(
        challenges=ChallengeResult(
            valid={"Extra": {"Obtain an ~|eye of newt|~": True}}, unsupported=frozenset()
        ),
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra",
                    groups=(TaskGroup(name="Extra", active=("Obtain an ~|eye of newt|~",)),),
                )
            }
        ),
    )

    result = _run(info, derived, Heuristics())

    # The shop exists in the export but not on this map, so the item has no
    # route at all - which is refused, not priced at zero.
    assert result.buckets["activities"] == 0.0
    assert "Eye of newt" in result.unpriced
