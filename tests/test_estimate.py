"""Tests for the estimator's bucketing and its item walk."""

from __future__ import annotations

from typing import Any

import pytest

from fray_claude.active_tasks import SkillClassification, TaskClassification
from fray_claude.bis import BisResult
from fray_claude.challenges import ChallengeResult
from fray_claude.chunkinfo import ChunkInfo
from fray_claude.estimate import estimate
from fray_claude.heuristics import DEFAULT_XP_PER_HOUR, Heuristics, QuestRate, Rate
from fray_claude.other_tasks import CategoryTasks, OtherTasks, TaskGroup
from fray_claude.pipeline import Derived, MapState
from fray_claude.search import build_world_index
from fray_claude.sources import SourceIndex


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


def _derived(**overrides: Any) -> Derived:
    defaults: dict[str, Any] = {
        "reachable_sections": {},
        "source_index": SourceIndex(
            items={}, objects={}, monsters={}, npcs={}, shops={}, drop_rates={}
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
    # 1/381 at 27 kills an hour is 381/27 = 14.11 hours. The arithmetic from
    # `plan.md`'s own worked example.
    info = ChunkInfo(
        {
            "drops": {"General Graardor": {"Bandos chestplate": {"1": "1/381"}}},
            "codeItems": {"bossMonsters": {"General Graardor": True}},
            "challenges": {"Extra": {"Obtain a ~|bandos chestplate|~": {}}},
        }
    )
    derived = _derived(
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra",
                    groups=(TaskGroup(name="Boss", active=("Obtain a ~|bandos chestplate|~",)),),
                )
            }
        )
    )
    heuristics = Heuristics(monsters={"General Graardor": Rate(27.0, "mmg:x", "exact")})

    result = _run(info, derived, heuristics)

    assert result.tasks[0].hours == pytest.approx(381 / 27)
    assert result.tasks[0].bucket == "boss drops"


def test_a_non_boss_provider_lands_in_activities() -> None:
    info = ChunkInfo(
        {
            "drops": {"Goblin": {"Bones": {"1": "1/10"}}},
            "challenges": {"Extra": {"Obtain ~|bones|~": {}}},
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

    result = _run(info, derived, Heuristics(monsters={"Goblin": Rate(100.0)}))

    assert result.tasks[0].bucket == "activities"
    assert result.tasks[0].hours == pytest.approx(10 / 100)


def test_a_worded_rate_is_priced_through_the_config() -> None:
    # `Always` and friends are 1,197 of the export's rate entries and parse
    # to `nan`; the config is what turns them into a number.
    info = ChunkInfo(
        {
            "drops": {"Goblin": {"Bones": {"1": "Always"}}},
            "challenges": {"Extra": {"Obtain ~|bones|~": {}}},
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

    result = _run(info, derived, Heuristics(monsters={"Goblin": Rate(50.0)}))

    assert result.tasks[0].hours == pytest.approx(1 / 50)


def test_an_item_with_no_priceable_route_is_reported_unpriced() -> None:
    # `Varies`/`Unknown` say nothing, so the task is admitted as a gap rather
    # than dropped or guessed at.
    info = ChunkInfo(
        {
            "drops": {"Goblin": {"Bones": {"1": "Varies"}}},
            "challenges": {"Extra": {"Obtain ~|bones|~": {}}},
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

    assert result.unpriced == ("Obtain ~|bones|~",)
    assert result.tasks == ()


def test_a_made_item_costs_its_inputs() -> None:
    info = ChunkInfo(
        {
            "drops": {"Goblin": {"Bones": {"1": "1/10"}}},
            "challenges": {
                "Crafting": {"Carve a ~|bone ring|~": {"Items": ["Bones"], "Output": "Bone ring"}},
                "Extra": {"Obtain a ~|bone ring|~": {}},
            },
        }
    )
    derived = _derived(
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra",
                    groups=(TaskGroup(name="X", active=("Obtain a ~|bone ring|~",)),),
                )
            }
        )
    )

    result = _run(info, derived, Heuristics(monsters={"Goblin": Rate(100.0)}))

    assert result.tasks[0].hours == pytest.approx(10 / 100)
    assert result.tasks[0].detail.startswith("make:")


def test_a_cycle_of_made_items_is_unpriced_rather_than_recursing() -> None:
    # A needs B needs A. Without the visited set this never returns.
    info = ChunkInfo(
        {
            "challenges": {
                "Crafting": {
                    "Make ~|a|~": {"Items": ["B"], "Output": "A"},
                    "Make ~|b|~": {"Items": ["A"], "Output": "B"},
                },
                "Extra": {"Obtain ~|A|~": {}},
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

    assert result.unpriced == ("Obtain ~|A|~",)


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


def test_a_method_above_the_current_level_is_passed_over() -> None:
    heuristics = Heuristics(
        training={
            "Mine ~|slow rocks|~": {"Mining": Rate(10_000.0, "mmg:a", "exact")},
            "Mine ~|fast rocks|~": {"Mining": Rate(50_000.0, "mmg:b", "exact")},
        }
    )

    result = _run(
        _skilling_info(), _skilling_derived(), heuristics, level_overrides={"Mining": 30}
    )

    assert result.skills[0].method == "slow rocks"


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
