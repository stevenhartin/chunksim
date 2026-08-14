"""Tests for the estimator's bucketing and its item walk."""

from __future__ import annotations

from typing import Any

from chunksim.model.experience import xp_for_level

import pytest

from chunksim.derive.active_tasks import SkillClassification, TaskClassification
from chunksim.derive.bis import BisResult
from chunksim.derive.challenges import ChallengeResult
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.costing.estimate import DEFAULT_ACTION_SECONDS, _item_hours, estimate
from chunksim.costing.training import training_options
from chunksim.costing.levels import goal_levels, infer_levels, reachable_providers, task_gated_monsters
from chunksim.remote.stores import ShopPrice
from chunksim.costing.heuristics import (
    DEFAULT_XP_PER_HOUR,
    Heuristics,
    QuestRate,
    Rate,
    SlayerTask,
    Superior,
)
from chunksim.derive.other_tasks import CategoryTasks, OtherTasks, TaskGroup
from chunksim.derive.pipeline import Derived, MapState
from chunksim.derive.search import build_world_index
from chunksim.costing.combat_xp import COMBAT_SKILLS
from chunksim.costing.inputs import load_heuristics
from chunksim.model.experience import xp_between
from chunksim.derive.sources import SourceIndex


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



def _walk_for(info: ChunkInfo, heuristics: Heuristics | None = None) -> Any:
    """A `_Walk` over `info` with everything it stocks reachable.

    The walk's gates are exercised elsewhere; these tests are about what a
    route *costs* once it is reachable.
    """
    from chunksim.costing.estimate import _Walk

    world = build_world_index(info)
    return _Walk(
        chunk_info=info,
        world=world,
        heuristics=heuristics or Heuristics(),
        by_lower={item.lower(): item for item in world.item_sources},
        reachable_items=frozenset(world.item_sources),
    )


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

    # Its inputs **and** the action itself: ten kills at 100/hr to gather the
    # ingredient, plus one default action to combine them. Performing a
    # conversion used to be free, which made every gathering chain free.
    assert result.items[0].hours == pytest.approx(10 / 100 + DEFAULT_ACTION_SECONDS / 3600)
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


def test_a_stacked_drop_still_has_to_pass_its_drop_rate() -> None:
    """**A goal is one drop event, however big the stack.** Hydra drops dragon
    knives at 1/10,000 and 200 to 400 at a time, but you still have to pass the
    1/10,000 - so it is ten thousand kills, not thirty-three. Dividing the
    kills by the stack size is the tempting reading of a quantity field and it
    is wrong for every goal this module walks, because each is satisfied by
    obtaining the item once.
    """
    info = ChunkInfo(
        {
            "drops": {"Hydra": {"Dragon knife": {"200-400": "1/10000"}}},
            "codeItems": {"bossMonsters": {}},
            "challenges": {
                "Extra": {"Obtain a ~|dragon knife|~": {"Items": ["Dragon knife"]}}
            },
        }
    )
    derived = _derived(
        monsters=("Hydra",),
        challenges=ChallengeResult(
            valid={"Extra": {"Obtain a ~|dragon knife|~": True}}, unsupported=frozenset()
        ),
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra",
                    groups=(TaskGroup(name="Extra", active=("Obtain a ~|dragon knife|~",)),),
                )
            }
        ),
    )
    heuristics = Heuristics(monsters={"Hydra": Rate(60.0, "test", "exact")})

    result = _run(info, derived, heuristics)

    (knife,) = [item for item in result.items if item.item == "Dragon knife"]
    assert knife.hours == pytest.approx(10_000 / 60)
    assert "at 1/10,000" in knife.detail


def test_a_shop_costs_the_money_and_the_walk() -> None:
    """**Buying is instant; the money is not, and neither is the trip.** A
    shop route priced at zero is how a Construction build reading
    `Coins x 10,000,000` became the fastest training in the game."""
    info = ChunkInfo(
        {
            "shopItems": {"Sawmill": {"Oak plank": True}},
            "challenges": {
                "Extra": {"Obtain an ~|oak plank|~": {"Items": ["Oak plank"]}}
            },
        }
    )
    heuristics = Heuristics(
        shop_prices={"Sawmill": {"Oak plank": ShopPrice(price=500.0, currency="Coins")}},
        currency_per_hour={"Coins": 500_000.0},
    )

    # 500 gp at 500,000/hr is 3.6s, plus one 30s trip.
    assert heuristics.shop_seconds("Sawmill", "Oak plank") == pytest.approx(3.6)


def test_a_currency_with_no_rate_has_no_price_rather_than_a_free_one() -> None:
    """Castle wars tickets and trading sticks have no exchange rate anyone
    would agree on, so an item sold only for those is refused."""
    heuristics = Heuristics(
        shop_prices={
            "Shop": {"Thing": ShopPrice(price=10.0, currency="Castle wars ticket")}
        }
    )

    assert heuristics.shop_seconds("Shop", "Thing") is None


def test_tokkul_is_slower_than_gold_because_it_is_earned_slower() -> None:
    """The point of keeping the currency: 375 Tokkul is not 375 coins."""
    heuristics = Heuristics(
        shop_prices={
            "TzHaar": {
                "Obsidian": ShopPrice(price=375.0, currency="Tokkul"),
                "Bronze": ShopPrice(price=375.0, currency="Coins"),
            }
        }
    )

    obsidian = heuristics.shop_seconds("TzHaar", "Obsidian")
    bronze = heuristics.shop_seconds("TzHaar", "Bronze")

    assert obsidian is not None and bronze is not None
    # 500,000 / 25,000 = twenty times as long for the same face value.
    assert obsidian == pytest.approx(bronze * 20)


def test_an_unpriced_shop_item_is_not_free() -> None:
    """"The wiki does not list it" and "it costs nothing" are the distinction
    this whole layer exists to preserve."""
    assert Heuristics().shop_seconds("Nowhere", "Anything") is None


def test_a_ground_spawn_is_cheap_but_not_free() -> None:
    """**Picking one up is a tick and it does not come back while you wait.**
    The cheap way to collect is to hop worlds, so the ceiling is how often you
    can stand at a fresh spawn - not how fast you can click. Left free, a
    `Spawn` of two planks priced a ten-plank wooden fence at nothing."""
    info = ChunkInfo(
        {
            "chunks": {"4912": {"Spawn": {"Plank": 2}}},
            "challenges": {"Extra": {"Obtain a ~|plank|~": {"Items": ["Plank"]}}},
        }
    )
    walk = _walk_for(info)

    priced = _item_hours(walk, "Plank", quantity=720.0)

    assert priced is not None
    # Two per hop at 360 hops an hour is 720 an hour, so 720 takes an hour.
    assert priced.hours == pytest.approx(1.0)


def test_the_pickup_tick_caps_a_generous_spawn() -> None:
    """One tick an item is 6,000 an hour however many lie on the floor."""
    info = ChunkInfo(
        {
            "chunks": {"1": {"Spawn": {"Coins pile": 1000}}},
            "challenges": {"Extra": {"Obtain a ~|coins pile|~": {"Items": ["Coins pile"]}}},
        }
    )
    walk = _walk_for(info)

    priced = _item_hours(walk, "Coins pile", quantity=6000.0)

    assert priced is not None and priced.hours == pytest.approx(1.0)


def test_performing_an_action_costs_time_even_with_no_inputs() -> None:
    """**The last free thing in the walk.** A `task:` route was charged for
    its inputs and never for performing it, so a chain bottoming out in a
    gathering action with nothing to consume cost zero: `Plank <- Process logs
    <- Logs <- Cut logs from roots <- (nothing)`."""
    info = ChunkInfo(
        {
            "challenges": {
                "Woodcutting": {"Cut ~|logs|~": {"Output": "Logs", "Items": []}}
            },
            "chunks": {},
        }
    )
    walk = _walk_for(info)

    priced = _item_hours(walk, "Logs", quantity=10.0)

    assert priced is not None
    assert priced.hours == pytest.approx(10 * DEFAULT_ACTION_SECONDS / 3600)


def test_a_known_action_time_beats_the_default() -> None:
    """A guide's `kph` and a recipe's tick cost both say how long an action
    takes; the default is only for when neither does."""
    info = ChunkInfo(
        {
            "challenges": {"Woodcutting": {"Cut ~|logs|~": {"Output": "Logs"}}},
            "chunks": {},
        }
    )
    walk = _walk_for(info, Heuristics(action_seconds={"Cut ~|logs|~": 12.0}))

    priced = _item_hours(walk, "Logs", quantity=10.0)

    assert priced is not None and priced.hours == pytest.approx(120 / 3600)


def test_an_or_equivalent_item_is_priced_by_its_cheapest_member() -> None:
    """**`[+]` means "or anything equivalent" and the item walk never read
    it.** A task wanting `Air rune[+]` found no item by that name and went
    unpriced, while `Air rune` itself priced in 2.4 seconds. 16 of the 75
    unpriced items on the benchmark map were this."""
    info = ChunkInfo(
        {
            "codeItems": {
                "itemsPlus": {"Air rune[+]": ["Air rune", "Dust rune", "Mist rune"]}
            },
            "chunks": {"1": {"Spawn": {"Air rune": 1, "Dust rune": 6}}},
            "challenges": {"Extra": {"Obtain an ~|air rune|~": {"Items": ["Air rune[+]"]}}},
        }
    )
    walk = _walk_for(info)
    object.__setattr__(
        walk,
        "item_families",
        {"Air rune[+]": ["Air rune", "Dust rune", "Mist rune"]},
    )

    family = _item_hours(walk, "Air rune[+]", quantity=6.0)
    dust = _item_hours(walk, "Dust rune", quantity=6.0)

    assert family is not None and dust is not None
    # Six dust runes a hop against one air rune, so the family takes the dust.
    assert family.hours == pytest.approx(dust.hours)


def test_a_family_whose_members_are_all_unreachable_stays_unpriced() -> None:
    """Refused, not guessed - the same rule every other route follows."""
    info = ChunkInfo({"codeItems": {"itemsPlus": {"Nothing[+]": ["Nowhere"]}}, "chunks": {}})
    walk = _walk_for(info)
    object.__setattr__(walk, "item_families", {"Nothing[+]": ["Nowhere"]})

    assert _item_hours(walk, "Nothing[+]") is None


def test_a_currency_can_be_qualified_by_the_shop_that_charges_it() -> None:
    """**`Points` is not one currency.** 127 store lines are priced in
    something called Points, and Mahogany Homes, Pest Control and Barbarian
    Assault each mean their own - so a rate may name the shop, and that is
    checked before the bare currency."""
    heuristics = Heuristics(
        shop_prices={
            "Mahogany Homes Reward Shop": {
                "Carpenter's helmet": ShopPrice(price=400.0, currency="Points")
            },
            "Other Shop": {"Thing": ShopPrice(price=400.0, currency="Points")},
        },
        currency_per_hour={"Mahogany Homes Reward Shop:Points": 100.0},
    )

    # 400 points at 100 an hour is four hours.
    assert heuristics.shop_seconds(
        "Mahogany Homes Reward Shop", "Carpenter's helmet"
    ) == pytest.approx(4 * 3600)
    # The same currency name elsewhere has no rate and is refused.
    assert heuristics.shop_seconds("Other Shop", "Thing") is None


def test_an_activity_a_valid_challenge_unlocks_is_a_provider() -> None:
    """**The export says "doing this gives you a roll on that".** The Evil
    chicken outfit is `Trade bird's eggs for nests*` at a Shrine, whose
    `Output` names a `skillItems` table holding the four pieces at 1/1200. The
    pieces are reachable the moment the trade is, and were unpriced because
    nothing put the *table* in the provider set beside monsters and objects.
    """
    info = ChunkInfo(
        {
            "skillItems": {
                "Nonskill": {"Egg loot": {"Evil chicken head": {"1": "1/1200"}}}
            },
            "challenges": {
                "Nonskill": {"Trade eggs": {"Output": "Egg loot"}},
                "Extra": {"Obtain an ~|evil chicken head|~": {"Items": ["Evil chicken head"]}},
            },
        }
    )
    derived = _derived(
        challenges=ChallengeResult(
            valid={"Nonskill": {"Trade eggs": True}}, unsupported=frozenset()
        ),
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra",
                    groups=(
                        TaskGroup(name="Extra", active=("Obtain an ~|evil chicken head|~",)),
                    ),
                )
            }
        ),
    )
    heuristics = Heuristics(monsters={"Egg loot": Rate(1.0, "hand", "exact")})

    result = _run(info, derived, heuristics)

    (head,) = [item for item in result.items if item.item == "Evil chicken head"]
    assert head.hours == pytest.approx(1200.0)


def test_an_unlocked_activity_with_no_stated_rate_is_still_refused() -> None:
    """**The gate that stops this pricing the other 322.** A minigame reward
    table handed the 60/hr default would make its rarest drop look cheap, and
    a guessed rate multiplied by a real drop chance is the same mistake
    `combat_xp.best_target` refuses."""
    info = ChunkInfo(
        {
            "skillItems": {"Nonskill": {"Egg loot": {"Rare thing": {"1": "1/1200"}}}},
            "challenges": {
                "Nonskill": {"Trade eggs": {"Output": "Egg loot"}},
                "Extra": {"Obtain a ~|rare thing|~": {"Items": ["Rare thing"]}},
            },
        }
    )
    derived = _derived(
        challenges=ChallengeResult(
            valid={"Nonskill": {"Trade eggs": True}}, unsupported=frozenset()
        ),
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra",
                    groups=(TaskGroup(name="Extra", active=("Obtain a ~|rare thing|~",)),),
                )
            }
        ),
    )

    result = _run(info, derived, Heuristics())

    assert "Rare thing" in result.unpriced


def test_sailing_is_refused_even_though_the_export_can_train_it() -> None:
    """**The other refusal, and the difference from Attack's is the point.**
    Attack has no training method anywhere in the export; Sailing has 27 of
    them and nobody has timed a single one - it is new enough that no
    money-making guide covers it, `{{Recipe}}` has no rows for it and no wiki
    table publishes a rate for any of its methods.

    So every method sits at the 1,000/hr floor and the climb reads as 13,034
    hours, which is not a conservative estimate but a made-up one wearing a
    number. Refused until something publishes rates - see `UNRATED_SKILLS`.
    """
    info = ChunkInfo(
        {
            "challenges": {
                "Sailing": {
                    "Reach ~|Sailing|~ 70": {"Level": 70},
                    "Complete ~|courier tasks|~": {"Primary": True, "Level": 1},
                }
            }
        }
    )
    derived = _derived(
        challenges=ChallengeResult(
            valid={
                "Sailing": {"Reach ~|Sailing|~ 70": 70, "Complete ~|courier tasks|~": 1}
            },
            unsupported=frozenset(),
        ),
        task_classification=TaskClassification(
            skills={
                "Sailing": SkillClassification(
                    active="Reach ~|Sailing|~ 70", obsolete=frozenset(), completed=frozenset()
                )
            }
        ),
    )

    result = _run(info, derived, Heuristics(), level_overrides={"Sailing": 1})

    assert result.skills == ()
    assert [(s.skill, s.reason) for s in result.unpriced_skills] == [
        ("Sailing", "no published rates for this skill yet")
    ]
    assert result.buckets["skilling"] == 0.0


@pytest.mark.real_cache
def test_a_slayer_climb_pays_for_the_combat_climbs_beside_it(
    real_state: tuple[MapState, dict[str, bool]], real_derived: Derived
) -> None:
    """**A Slayer task is a fight, and the estimate used to charge for it
    twice.** Slayer XP is the monster's hitpoints, so a Slayer rate in XP per
    hour *is* a damage rate - and on the benchmark map 394 hours of Slayer had
    already earned the Hitpoints, Defence and Attack climbs being priced in
    full beside it: 353 of 1,263 skilling hours.

    An oracle test rather than a fixture, because the credit only has anything
    to say on a map that holds a Slayer goal *and* a combat goal, and building
    one by hand would be building the answer. The invariants are in
    `tests/test_combat_xp.py`; this asserts the two are wired together at all.
    """
    state, unlocked = real_state
    heuristics, _ = load_heuristics(state.chunk_info)
    result = estimate(state, real_derived, build_world_index(state.chunk_info), heuristics)

    slayer = next((e for e in result.skills if e.skill == "Slayer"), None)
    combat = [e for e in result.skills if e.skill in COMBAT_SKILLS and e.xp > 0]
    # **Both halves are needed and the cached map may hold only one.** `fray`
    # has a Slayer goal and no combat goal, so there is genuinely nothing to
    # credit there; `verf-sim/run-001` has both and moves 353 hours.
    if slayer is None or slayer.hours <= 0 or not combat:
        pytest.skip("this map has no Slayer goal beside a combat goal")

    credited = [e for e in result.skills if e.skill in COMBAT_SKILLS and e.xp_from_combat > 0]
    assert credited, "a Slayer climb earned no combat experience for anything"
    for entry in credited:
        assert entry.xp_from_combat <= xp_between(entry.current_level, entry.target_level)


def _farming_plan() -> Any:
    """A one-crop schedule, shaped only to have a rate and a calendar."""
    from chunksim.costing.farming import FarmingPlan, FarmingRun

    return FarmingPlan(
        runs=(
            FarmingRun(
                key="Herb", crop="Ranarr weed", level=32,
                experience=100_000.0, harvests_per_day=1.0,
            ),
        )
    )


def test_the_farm_schedule_is_one_method_rather_than_the_whole_answer() -> None:
    """It used to be the whole answer, which hid Tithe Farm entirely - a
    minigame with no growing time at all that the map may or may not reach.

    With no minigame available nothing changes: the schedule wins every band
    and the calendar is charged for the whole climb, exactly as before.
    """
    from chunksim.costing.estimate import _farming_bands

    plan = _farming_plan()
    bands, days = _farming_bands(plan, (), 0, 99)

    assert [band.match for band in bands] == ["farming"]
    assert days == pytest.approx(plan.days_for(xp_for_level(99)))


def test_tithe_farm_is_preferred_above_its_level_though_it_is_slower() -> None:
    """**The axis that decides is the calendar, not the hour.** The schedule's
    blended rate counts only the clicking, so it reads several times higher
    than the minigame while taking months to deliver; a walk ranking on rate
    would therefore never pick the minigame.

    So above the level it opens at the schedule is left out rather than
    outranked, and below it the schedule keeps everything - which is also what
    a player does. Measured on `verf-sim/run-001`: 64.0h over 145 calendar
    days becomes 138.0h over 12.2, buying 133 days for 74 hours.
    """
    from chunksim.costing.estimate import _farming_bands
    from chunksim.costing.heuristics import TITHE_SOURCE
    from chunksim.costing.training import TrainingOption

    plan = _farming_plan()
    tithe = TrainingOption(
        method="logavano fruit",
        level=74,
        # Deliberately *slower* per hour than the schedule, which is the real
        # relationship and the reason this cannot be a max().
        xp_per_hour=plan.xp_per_day / plan.hours_per_day / 2.0,
        match="exact",
        source=TITHE_SOURCE,
    )
    bands, days = _farming_bands(plan, (tithe,), 0, 99)

    assert [band.match for band in bands] == ["farming", "exact"]
    assert bands[0].level_to == 74, "the schedule keeps everything below"
    assert bands[1].method == "logavano fruit"

    # **No calendar at all where the minigame is reachable.** It opens at 34,
    # so from there the growing time is a choice rather than a constraint and
    # what the player spends is hours; when it is locked the waiting *is* the
    # skill and the calendar stands.
    assert days == 0.0


def test_an_unrated_skill_is_rechecked_rather_than_refused_on_sight() -> None:
    """**Membership of `UNRATED_SKILLS` is a precondition, not the decision.**

    It used to be both, which made it a standing claim about the world that
    nothing ever rechecked - and the world moved: `Sailing training` now
    publishes figures for barracuda trials, courier tasks, salvaging and sea
    charting, where when the entry was written it published none.

    So the refusal holds only while no reachable method has a real rate. The
    pairing is needed in both directions: without the set, "nothing is rated"
    would refuse any skill the scrape has merely not reached yet, where the
    floor is honest and an improving scrape fixes it; without the recheck, a
    skill stays refused after its numbers arrive.
    """
    from chunksim.costing.estimate import UNRATED_SKILLS
    from chunksim.costing.training import TrainingOption, training_bands

    assert "Sailing" in UNRATED_SKILLS

    # With a rate joined, the skill is priced by the ordinary walk rather than
    # held back - no edit to the set required.
    rated = TrainingOption(
        method="The Gwenith Glide at Marlin rank",
        level=72,
        xp_per_hour=200_000.0,
        match="exact",
    )
    bands = training_bands((rated,), xp_for_level(72), 99)
    assert bands and bands[-1].method == "The Gwenith Glide at Marlin rank"
    assert all(band.match != "default" for band in bands)


# --- the reachability gate and the table route -----------------------------


def _table_map(*, rate: str, action_seconds: float | None) -> tuple[Any, Any, Any]:
    """A map that fishes one thing out of a `skillItems` table."""
    info = ChunkInfo(
        {
            "skillItems": {"Fishing": {"Fish loot": {"Raw thing": {"1": rate}}}},
            "challenges": {
                "Fishing": {"Catch a ~|raw thing|~": {"Output": "Fish loot"}},
                "Extra": {"Obtain a ~|raw thing|~": {"Items": ["Raw thing"]}},
            },
        }
    )
    derived = _derived(
        challenges=ChallengeResult(
            valid={"Fishing": {"Catch a ~|raw thing|~": True}},
            unsupported=frozenset(),
            available_items={"Raw thing": {}},
        ),
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra",
                    groups=(TaskGroup(name="Extra", active=("Obtain a ~|raw thing|~",)),),
                )
            }
        ),
    )
    seconds = {} if action_seconds is None else {"Catch a ~|raw thing|~": action_seconds}
    return info, derived, Heuristics(action_seconds=seconds)


def test_a_challenge_whose_output_is_a_table_prices_the_thing_in_it() -> None:
    """**223 challenges output a table rather than an item.** `Catch a ~|raw
    swordfish|~` yields `Raw swordfish loot`, which is `{"Raw swordfish":
    "Always", "Big swordfish": "1/2500"}` - so the fish had no task route at
    all, only `ItemSource("Fishing", "Raw swordfish loot")`, which
    `_kill_hours` refuses because a table is not a monster you can stand in
    front of.

    That made a fish the map plainly catches unpriceable, and an unpriceable
    material drops its *recipe* while the scraped rate survives - so
    `Cook a ~|swordfish|~` kept 182,000/hr with nothing charged and took
    45 -> 99 of Cooking.
    """
    info, derived, heuristics = _table_map(rate="Always", action_seconds=30.0)

    result = _run(info, derived, heuristics)

    (thing,) = [item for item in result.items if item.item == "Raw thing"]
    assert thing.hours == pytest.approx(30.0 / 3600.0)


def test_an_uncertain_table_row_is_refused_the_task_route() -> None:
    """**The gate that keeps this from pricing every reward table.** The time
    to perform a challenge is a default where nothing states it, and
    multiplying a defaulted pace by a real drop chance is the mistake
    `combat_xp.best_target` refuses and the Evil chicken test above pins.

    At `Always` there is no multiplication to get wrong - the action hands the
    thing over. Below it there is, so `Big swordfish` at 1/2500 keeps no route
    from the fishing action that catches its ordinary twin.
    """
    info, derived, heuristics = _table_map(rate="1/2500", action_seconds=30.0)

    result = _run(info, derived, heuristics)

    assert "Raw thing" in result.unpriced


def test_a_table_route_needs_a_stated_pace_not_a_defaulted_one() -> None:
    """`Slay the ~|Alchemical Hydra|~ alt` outputs a table holding `Hydra
    bones` at `Always`, and killing the Alchemical Hydra is not a four-tick
    action. Priced at `DEFAULT_ACTION_SECONDS` it made a hydra bone free and
    put Prayer at 11.3h off 1,155,000 xp/hr.

    A kill has a route of its own with the gear and the gates on it, so
    refusing here loses nothing.
    """
    info, derived, heuristics = _table_map(rate="Always", action_seconds=None)

    result = _run(info, derived, heuristics)

    assert "Raw thing" in result.unpriced


def test_the_walk_gates_on_available_items_not_on_the_source_index() -> None:
    """**The project's first cross-cutting rule, and this module was the third
    to break it** after `bis.py` and `boosts.py`. `SourceIndex.items` omits
    anything obtainable only by *making* it - 1,103 items against 1,918 on
    `fray` - so 815 reachable items were refused a shop or spawn route on the
    grounds that the map could not reach them.

    The fixture is the shape that exposed it: an item nothing on the map
    *drops*, stocked by a shop, which the derivation calls available.
    """
    info = ChunkInfo(
        {
            "shopItems": {"Fish Shop": {"Raw thing": True}},
            "challenges": {"Extra": {"Obtain a ~|raw thing|~": {"Items": ["Raw thing"]}}},
        }
    )
    derived = _derived(
        challenges=ChallengeResult(
            valid={},
            unsupported=frozenset(),
            # Reachable, and *not* in `source_index.items`, which `_derived`
            # leaves empty - exactly the case the old gate refused.
            available_items={"Raw thing": {}},
        ),
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra",
                    groups=(TaskGroup(name="Extra", active=("Obtain a ~|raw thing|~",)),),
                )
            }
        ),
    )
    heuristics = Heuristics(
        currency_per_hour={"Coins": 500_000.0},
        shop_prices={"Fish Shop": {"Raw thing": ShopPrice(price=100.0, currency="Coins")}},
    )

    result = _run(info, derived, heuristics)

    assert "Raw thing" not in result.unpriced


def test_a_priced_item_records_the_knobs_its_number_came_off() -> None:
    """**What makes an estimate arguable rather than merely stated.**

    `detail` says what was assumed in prose - "General Graardor at 1/381,
    27/hr" - which tells you the number is wrong but not where to go and fix
    it. The knob is the override path, recorded where the value was read: the
    join that found it can be fuzzy (`heuristics.py` owns `exact`/`contained`),
    so reconstructing which entry a number came from afterwards is exactly the
    mistake this exists to stop.
    """
    info = ChunkInfo(
        {
            "drops": {"General Graardor": {"Bandos chestplate": {"1": "1/381"}}},
            "codeItems": {"bossMonsters": {"General Graardor": True}},
            "challenges": {
                "Extra": {"Obtain a ~|bandos chestplate|~": {"Items": ["Bandos chestplate"]}}
            },
        }
    )
    derived = _derived(
        monsters=("General Graardor",),
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra",
                    groups=(
                        TaskGroup(name="Boss", active=("Obtain a ~|bandos chestplate|~",)),
                    ),
                )
            }
        ),
    )
    heuristics = Heuristics(monsters={"General Graardor": Rate(27.0, "mmg:x", "exact")})

    result = _run(info, derived, heuristics)

    assert result.items[0].knobs == ("monsters/General Graardor",)
    assert result.items[0].as_dict()["knobs"] == ["monsters/General Graardor"]


def test_a_route_with_no_heuristic_behind_it_claims_none() -> None:
    """**An empty tuple is the honest answer, not a gap.**

    A ground spawn is priced entirely out of constants - hops an hour, seconds
    to pick one up - so there is no entry anyone could correct. Pointing at the
    nearest branch anyway would send someone to change a number that has no
    bearing on it, which is worse than saying nothing.
    """
    info = ChunkInfo(
        {
            "chunks": {"4912": {"Spawn": {"Iron axe": 1}}},
            "challenges": {"Extra": {"Obtain an ~|iron axe|~": {"Items": ["Iron axe"]}}},
        }
    )
    walk = _walk_for(info)

    priced = _item_hours(walk, "Iron axe")

    assert priced is not None
    assert priced.hours > 0, "a spawn is cheap, not free"
    assert priced.knobs == ()


@pytest.mark.real_cache
def test_every_knob_a_real_estimate_emits_names_a_real_override_branch(
    real_state: Any, real_derived: Any
) -> None:
    """**A knob exists to say where to go and change something.**

    So a path that is not a branch of the override file is worse than no path:
    it reads like a working pointer, sends someone to edit a key nothing
    parses, and the number does not move. The first version of this recorded
    `Heuristics` *field* names, three of which the file does not use -
    `currency_per_hour` for `currencies`, `action_seconds` for `actions`,
    `shop_prices` for `shops`.

    Run against the real map because that is what exercises every route: a
    fixture reaches one at a time and would have missed all three. All three
    buckets that record knobs are swept, not just the items.
    """
    from chunksim.costing.heuristics import CONFIG_BRANCHES
    from chunksim.costing.inputs import estimate_answer
    from chunksim.store.cache import project_root
    from chunksim.store.cache import file_digest
    from chunksim.store.derived_cache import Digests
    from chunksim.store import cache as cache_module

    state, unlocked = real_state
    digests = Digests(
        chunkinfo=file_digest(cache_module.chunkinfo_source(None, project_root())),
        tasks_map=file_digest(
            cache_module.blob_path(cache_module.TASKS_MAP_BLOB_NAME, project_root())
        ),
    )
    answer = estimate_answer(state, unlocked, real_derived, digests)

    priced: list[tuple[str, ...]] = [
        row.knobs
        for group in (answer.result.items, answer.result.tasks, answer.result.skills)
        for row in group
    ]
    emitted = {knob.split("/")[0] for row in priced for knob in row}
    assert emitted, "the estimate priced nothing, so this proves nothing"
    assert emitted <= CONFIG_BRANCHES, f"not override branches: {sorted(emitted - CONFIG_BRANCHES)}"
    # And every one of them parses back to the entry it names - the guard that
    # a quest called `Recipe for Disaster/Freeing Evil Dave` needs.
    from chunksim.gui import knobs as knob_paths

    for row in priced:
        for knob in row:
            assert knob_paths.split(knob)[0] in CONFIG_BRANCHES


def test_a_quest_names_the_only_number_anyone_can_argue_with() -> None:
    """The step counts are the export's and the fraction is arithmetic; what
    is arguable is how long the quest takes.

    **Neither cached map has an outstanding quest**, so this is the only place
    the quest knob is exercised - which is the reason it is a fixture rather
    than an oracle.
    """
    info = ChunkInfo({"challenges": {"Quest": {"~|Cook's Assistant|~ 1": {"BaseQuest": "Cook's Assistant"}}}})
    derived = _derived(
        other_tasks=OtherTasks(
            categories={
                "Quest": CategoryTasks(
                    category="Quest",
                    groups=(
                        TaskGroup(name="Cook's Assistant", active=("~|Cook's Assistant|~ 1",)),
                    ),
                )
            }
        ),
    )

    result = _run(info, derived, Heuristics())

    (quest,) = result.tasks
    assert quest.knobs == ("quests/Cook's Assistant",)
    assert quest.as_dict()["knobs"] == ["quests/Cook's Assistant"]


def test_a_quest_whose_name_holds_a_separator_still_addresses_itself() -> None:
    """`Recipe for Disaster/Freeing Evil Dave` is one key of `quests`, and the
    path has to survive being read back - see `gui.knobs.split`."""
    from chunksim.gui import knobs

    info = ChunkInfo({})
    derived = _derived(
        other_tasks=OtherTasks(
            categories={
                "Quest": CategoryTasks(
                    category="Quest",
                    groups=(
                        TaskGroup(
                            name="Recipe for Disaster/Freeing Evil Dave",
                            active=("~|Recipe for Disaster|~ 1",),
                        ),
                    ),
                )
            }
        ),
    )

    (quest,) = _run(info, derived, Heuristics()).tasks

    (path,) = quest.knobs
    assert knobs.split(path) == ("quests", "Recipe for Disaster/Freeing Evil Dave")


def test_a_band_carries_the_knob_its_producer_chose() -> None:
    """**Collected, not inferred.** Working the path out from what a band
    carries was wrong four separate ways - see `_skill_knobs` - and each was
    silent: the path was accepted, written, and moved no number."""
    from chunksim.costing.estimate import _skill_knobs
    from chunksim.costing.training import TrainingBand

    def band(method: str, match: str, knob: str) -> TrainingBand:
        return TrainingBand(
            level_from=1, level_to=50, xp=100, xp_per_hour=1000.0,
            method=method, match=match, knob=knob,
        )

    bands = (
        band("Chop oak logs", "exact", "training/Chop ~|oak logs|~/Woodcutting"),
        band("Mutated Bloodveld", "computed", "monster_stats/Mutated Bloodveld"),
        band("Krystilia", "slayer", "slayer/Krystilia"),
        # A farming schedule and a Prayer bury rate each describe nothing the
        # file holds, so they carry nothing and contribute nothing.
        band("4 patches, 60,000 xp/day", "farming", ""),
        band("Bury ~|dragon bones|~", "computed", ""),
    )

    assert _skill_knobs(bands) == (
        "training/Chop ~|oak logs|~/Woodcutting",
        "monster_stats/Mutated Bloodveld",
        "slayer/Krystilia",
    )


def test_a_training_knob_names_the_challenge_not_its_display_name() -> None:
    """`TrainingOption.method` is `activity_name(...)`, which is not a key
    anywhere - so a path built from it addresses nothing."""
    from chunksim.costing.training import training_options

    info = ChunkInfo(
        {
            "challenges": {
                "Woodcutting": {
                    "Chop ~|oak logs|~": {"Primary": True, "Level": 15},
                }
            }
        }
    )
    derived = _derived(
        challenges=ChallengeResult(
            valid={"Woodcutting": {"Chop ~|oak logs|~": True}}, unsupported=frozenset()
        ),
    )
    heuristics = Heuristics(
        training={"Chop ~|oak logs|~": {"Woodcutting": Rate(40000.0, "wiki:x", "exact")}}
    )

    (option,) = training_options(derived, info, heuristics, "Woodcutting")

    assert option.knob == "training/Chop ~|oak logs|~/Woodcutting"
    assert option.method != "Chop ~|oak logs|~", "the display name is not the key"
