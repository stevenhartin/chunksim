"""Tests for the estimator's bucketing and its item walk."""

from __future__ import annotations

from typing import Any

from chunksim.model.experience import xp_for_level

import pathlib

import pytest

from chunksim.derive.active_tasks import SkillClassification, TaskClassification
from chunksim.derive.bis import BisResult
from chunksim.derive.challenges import ChallengeResult
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.model.summary import _mapping
from chunksim.costing.estimate import (
    DEFAULT_ACTION_SECONDS,
    DRILLABLE_ROUTES,
    SHOP_RESTOCK_CUTOFF_SECONDS,
    SHOP_TRIP_SECONDS,
    WORLD_HOP_SECONDS,
    _item_hours,
    estimate,
    item_routes,
    material_seconds,
    priced_candidate,
)
from chunksim.costing import recipe_rates
from chunksim.costing.training import training_options
from chunksim.costing.levels import (
    TaskGate,
    goal_levels,
    infer_levels,
    reachable_providers,
    task_gated_monsters,
)
from chunksim.remote.stores import ShopPrice
from chunksim.remote.combat import MonsterStats
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
    """A `_Walk` over `info` with everything it stocks reachable, **every**
    chunk and section included.

    The walk's gates are exercised elsewhere; these tests are about what a
    route *costs* once it is reachable. `_location_reachable`'s own gate is
    the one exception - see `test_a_spawn_in_a_chunk_this_map_never_opened_is_refused`,
    which passes its own `unlocked_chunks`/`reachable_sections` to exercise it.
    """
    from chunksim.costing.estimate import _Walk

    world = build_world_index(info)
    return _Walk(
        chunk_info=info,
        world=world,
        heuristics=heuristics or Heuristics(),
        by_lower={item.lower(): item for item in world.item_sources},
        reachable_items=frozenset(world.item_sources),
        unlocked_chunks=frozenset(info.chunks),
        reachable_sections={
            chunk_id: {section_id: True for section_id in _mapping(entry, "Sections")}
            for chunk_id, entry in info.chunks.items()
            if isinstance(entry, dict)
        },
    )


def _walk_with_chunks(
    info: ChunkInfo,
    unlocked_chunks: frozenset[str],
    reachable_sections: dict[str, dict[str, bool]] | None = None,
    heuristics: Heuristics | None = None,
) -> Any:
    """A `_Walk` with a *specific* unlocked-chunk/reachable-section set, for
    exercising `_location_reachable`/`_shop_reachable` rather than bypassing
    them."""
    from chunksim.costing.estimate import _Walk

    world = build_world_index(info)
    return _Walk(
        chunk_info=info,
        world=world,
        heuristics=heuristics or Heuristics(),
        by_lower={item.lower(): item for item in world.item_sources},
        reachable_items=frozenset(world.item_sources),
        unlocked_chunks=unlocked_chunks,
        reachable_sections=reachable_sections or {},
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


def test_a_raid_named_provider_prices_by_its_run_not_default_kph() -> None:
    """**A `skillItems` table can be keyed by the raid itself, not a monster
    inside it.** Theatre of Blood's own `Sanguine dust`/`Sanguine ornament
    kit` sit in a `skillItems.Nonskill` table named "Theatre of Blood" - the
    same string as the *object* you click in Ver Sinhaza to start the raid,
    which the walk correctly treats as reachable (you really can walk up to
    it). Asking `kills_per_hour("Theatre of Blood")` for the table's own
    items then read as `DEFAULT_KPH`'s 150 an hour, because nothing scrapes
    a kills-per-hour for a raid's own name - the same bug
    `raids.item_seconds` already keeps out of the items it covers,
    reappearing for the ones it does not. `_provider_kills_per_hour`
    recognises a `RUN_ONLY_PLACES` member and substitutes the run's own
    published duration (1200s, 3/hr) instead; `_provider_knob` points the
    correction at `runs/<place>`, not `monsters/<place>`, to match."""
    from chunksim.costing.estimate import _provider_kills_per_hour, _provider_knob

    walk = _walk_for(ChunkInfo({}))

    rate = _provider_kills_per_hour(walk, "Theatre of Blood")

    assert rate.value == pytest.approx(3.0)
    assert rate.source == "runs:Theatre of Blood"
    assert _provider_knob("Theatre of Blood") == "runs/Theatre of Blood"
    # An ordinary monster is untouched - this only substitutes for a place.
    assert _provider_knob("Goblin") == "monsters/Goblin"
    goblin_rate = _provider_kills_per_hour(walk, "Goblin")
    assert goblin_rate.value == pytest.approx(150.0)
    assert goblin_rate.source == "default:regular"


def test_a_hand_override_still_beats_the_run_duration() -> None:
    """A `monsters/<place>` correction is still the top of the stack - this
    only substitutes for the *absence* of one, never overrides a real
    number somebody set."""
    from chunksim.costing.estimate import _provider_kills_per_hour

    walk = _walk_for(ChunkInfo({}), Heuristics(monsters={"Theatre of Blood": Rate(5.0, "hand", "exact")}))

    rate = _provider_kills_per_hour(walk, "Theatre of Blood")

    assert rate.value == pytest.approx(5.0)
    assert rate.source == "hand"


def test_a_monster_only_reachable_inside_a_raid_is_not_priced_as_a_kill() -> None:
    """**The kill route had the same "reachable is not farmable" gap
    `combat_xp.farmable_providers` already exists to close.** `Skeletal
    Mystic` is a real, chunk-placed Chambers of Xeric monster with no scraped
    `kills_per_hour` of its own - priced through the ordinary route it read
    as `DEFAULT_KPH`'s 150 kills an hour, the exact figure `_setup`'s own
    docstring already names as the bug this module exists to keep out of the
    *drop* route, reappearing through the *kill* route instead (`Long bone`
    and `Curved bone` are real `Extra` tasks on the real map). `providers`
    now excludes anything whose every chunk is `instanced.run_only`, so this
    reads as unpriced rather than as a plausible-looking wrong number."""
    info = ChunkInfo(
        {
            "drops": {"Skeletal Mystic": {"Long bone": {"1": "1/10"}}},
            "challenges": {"Extra": {"Obtain a ~|long bone|~": {"Items": ["Long bone"]}}},
        }
    )
    derived = _derived(
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra", groups=(TaskGroup(name="X", active=("Obtain a ~|long bone|~",)),)
                )
            }
        ),
        source_index=SourceIndex(
            items={},
            objects={},
            npcs={},
            shops={},
            drop_rates={},
            monsters={"Skeletal Mystic": {"Chambers of Xeric": True}},
        ),
    )

    result = _run(info, derived, Heuristics())

    assert result.items == ()
    assert result.unpriced == ("Long bone",)


def test_a_group_boss_yields_to_its_soloable_alternative() -> None:
    """`The Nightmare` is `dps_bridge.GROUP_BOSSES` - "the wiki's rates for
    these describe a team, so comparing against them is meaningless too" -
    but before `_GROUP_BOSS_SOLO_ALTERNATIVE`, nothing kept that team-only
    guide rate out of the *kill route* the way `dps_bridge` already kept it
    out of the DPS simulation. `Phosani's Nightmare` shares the drop table
    and is a real, DPS-modelled solo fight, so once both are reachable the
    walk should price off her rather than off a number that describes a
    party."""
    info = ChunkInfo(
        {
            "drops": {
                "The Nightmare": {"Nightmare staff": {"1": "1/300"}},
                "Phosani's Nightmare": {"Nightmare staff": {"1": "1/533"}},
            },
            "challenges": {
                "Extra": {"Obtain a ~|nightmare staff|~": {"Items": ["Nightmare staff"]}}
            },
        }
    )
    derived = _derived(
        monsters=("The Nightmare", "Phosani's Nightmare"),
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra",
                    groups=(TaskGroup(name="X", active=("Obtain a ~|nightmare staff|~",)),),
                )
            }
        ),
    )
    heuristics = Heuristics(
        monsters={
            "The Nightmare": Rate(12.0, "mmg:Money making guide/Killing The Nightmare", "exact"),
            "Phosani's Nightmare": Rate(5.8, "dps", "scripted"),
        }
    )

    result = _run(info, derived, heuristics)

    assert result.items[0].source == "Phosani's Nightmare"
    assert result.items[0].hours == pytest.approx(533.0 / 5.8, rel=1e-3)


def test_the_group_boss_is_still_priced_without_its_alternative() -> None:
    """The exclusion only fires when the solo sibling is also reachable - a
    map somehow reaching the team fight without Phosani's still gets the
    (bad) guide number rather than nothing at all."""
    info = ChunkInfo(
        {
            "drops": {"The Nightmare": {"Nightmare staff": {"1": "1/300"}}},
            "challenges": {
                "Extra": {"Obtain a ~|nightmare staff|~": {"Items": ["Nightmare staff"]}}
            },
        }
    )
    derived = _derived(
        monsters=("The Nightmare",),
        other_tasks=OtherTasks(
            categories={
                "Extra": CategoryTasks(
                    category="Extra",
                    groups=(TaskGroup(name="X", active=("Obtain a ~|nightmare staff|~",)),),
                )
            }
        ),
    )
    heuristics = Heuristics(
        monsters={
            "The Nightmare": Rate(12.0, "mmg:Money making guide/Killing The Nightmare", "exact"),
        }
    )

    result = _run(info, derived, heuristics)

    assert result.items[0].source == "The Nightmare"


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
    # No "make: " prefix - the challenge name is already a full sentence.
    assert result.items[0].detail == "Carve a ~|bone ring|~"
    # Bones' own 0.1h clears `_DOMINANT_MATERIAL_SHARE` against the four-tick
    # action fee, so the source propagates to `Goblin` rather than staying a
    # one-off `make:...` heading - see
    # `test_a_recipe_dominated_by_one_material_takes_its_source`.
    assert result.items[0].source == "Goblin"


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


def test_a_skill_already_past_its_goal_is_not_a_row() -> None:
    """`Mine a ~|rune ore|~` wants level 85; a level override of 99 clears it
    before this ever asks a rate for it. **Hidden, not a zero-hour row** -
    `xp` reaching 0 means nothing is left to charge for, whether the level
    came from a hand override, a linked account's real XP, or a quest
    grant, and a row with nothing behind it is noise rather than a naming of
    what already happened."""
    result = _run(
        _skilling_info(), _skilling_derived(), Heuristics(), level_overrides={"Mining": 99}
    )

    assert result.skills == ()


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

    assert gates == {
        "Grotesque Guardians": TaskGate(
            task="Gargoyles", place="Grotesque Guardians' Lair"
        )
    }


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
        "Aberrant spectre": TaskGate(
            task="Aberrant spectres", place="Stronghold Slayer Cave"
        )
    }


def test_a_task_gated_kill_includes_the_wait_for_the_task() -> None:
    # Vannaka: P(Gargoyles) = 1/10, and the only *other* task is Bats at
    # 100/100 = 1h - Gargoyles' own hours must not enter that average, or
    # its fight gets counted once inside the wait and once again where its
    # own kill time is added (`MasterRate.hours_to_be_assigned`'s docstring
    # on the double-count this replaced). Downtime = (1-0.1)/0.1 * 1h = 9h.
    # One assignment of 100 covers the 100 kills needed, and killing them
    # takes 100/20 = 5h. Total 9 + 5 = 14h - against 5h if the task were
    # ignored.
    result = _run(_gated_info(), _gated_derived(), _gated_heuristics())

    assert result.items[0].hours == pytest.approx(14.0)
    assert "on Gargoyles task" in result.items[0].detail


def test_an_unreachable_master_cannot_supply_the_task() -> None:
    # Duradel assigns gargoyles nine times as often, but is not in any
    # unlocked chunk - picking him would price a task you can never be given.
    result = _run(_gated_info(), _gated_derived(), _gated_heuristics())

    assert result.items[0].hours == pytest.approx(14.0)  # Vannaka's 9h wait, not Duradel's


def test_the_knob_list_names_wait_not_slayer() -> None:
    """`wait/{master}/{task}` is what the item's own knob list carries -
    not `slayer/{master}/{task}`, whose `kills_per_hour` this item's price
    no longer reads at all. See `gui.knobs.BRANCH_NOTES["wait"]` for why
    the split exists."""
    result = _run(_gated_info(), _gated_derived(), _gated_heuristics())

    assert "wait/Vannaka/Gargoyles" in result.items[0].knobs
    assert not any(knob.startswith("slayer/") for knob in result.items[0].knobs)


def test_a_wait_override_replaces_the_computed_downtime() -> None:
    """The one real lever for the figure `hours_to_be_assigned` computes -
    see `Heuristics.wait_hours`'s own docstring for why it has to be a
    knob of its own rather than reusing `slayer`'s."""
    from dataclasses import replace

    heuristics = replace(
        _gated_heuristics(), wait_hours={"Vannaka": {"Gargoyles": 2.0}}
    )

    result = _run(_gated_info(), _gated_derived(), heuristics)

    # The computed 9h downtime is gone; 2h (override) + 5h (the kill itself,
    # unchanged) = 7h, against the 14h `test_a_task_gated_kill_includes_
    # the_wait_for_the_task` pins without the override.
    assert result.items[0].hours == pytest.approx(7.0)


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


def test_a_recipe_dominated_by_one_material_takes_its_source() -> None:
    """The `fray` map case this rule was written for: `Imbue a granite ring`
    needs nothing but a `Granite ring` and a shop trip, so its cost *is*
    Grotesque Guardians' own grind, not a second one. Before
    `_route_hours` propagated the dominant material's source, the imbue
    priced under its own `make:...` heading and added its hours - here,
    `Bandos hilt`'s 14.11h - on top of the boss-drops clamp instead of
    folding into it, double-charging a grind that was already paid for.

    `Bandos chestplate` at 1/2000 is the longer pole so the clamp's answer
    (74.07h) does not incidentally equal the imbued item's own hours, which
    would leave the double-count this test exists to catch invisible."""
    info = ChunkInfo(
        {
            "drops": {
                "General Graardor": {
                    "Bandos chestplate": {"1": "1/2000"},
                    "Bandos hilt": {"1": "1/381"},
                }
            },
            "codeItems": {"bossMonsters": {"General Graardor": True}},
            "challenges": {
                "Extra": {
                    "Obtain a ~|bandos chestplate|~": {"Items": ["Bandos chestplate"]},
                    "Obtain a ~|bandos hilt|~": {"Items": ["Bandos hilt"]},
                    "Imbue a ~|bandos hilt|~": {
                        "Items": ["Bandos hilt"],
                        "Output": "Bandos hilt (i)",
                    },
                    "Obtain a ~|bandos hilt (i)|~": {"Items": ["Bandos hilt (i)"]},
                }
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
                        TaskGroup(
                            name="Boss",
                            active=(
                                "Obtain a ~|bandos chestplate|~",
                                "Obtain a ~|bandos hilt|~",
                                "Obtain a ~|bandos hilt (i)|~",
                            ),
                        ),
                    ),
                )
            }
        ),
    )
    heuristics = Heuristics(monsters={"General Graardor": Rate(27.0, "mmg:x", "exact")})

    result = _run(info, derived, heuristics)

    imbued = next(item for item in result.items if item.item == "Bandos hilt (i)")
    assert imbued.source == "General Graardor"
    assert imbued.bucket == "boss drops"
    # The clamp's answer is the longest single item off this source
    # (`Bandos chestplate`'s 74.07h) - not that plus the imbued hilt's 14.11h
    # again, which is what the bug this test pins looked like.
    assert result.buckets["boss drops"] == pytest.approx(2000 / 27)


def test_a_leaf_item_groups_under_its_diary_task() -> None:
    """`Coif` has no real repeatable source of its own - it is *made* - so
    its display should roll up under the Diary task that wants it rather
    than stand as its own `make:...` heading.

    **The weave itself is given a real cost.** Left at the default four
    ticks, Wool's own 360s would clear `_DOMINANT_MATERIAL_SHARE` and
    `_route_hours` would propagate `Goblin` as Coif's source instead - the
    behaviour `test_a_recipe_dominated_by_one_material_takes_its_source`
    pins - which is a different mechanism from the one this test targets and
    would take Coif out of the `group` path entirely. A costed weave keeps
    Wool below the threshold so this test isolates the `group` rollup.
    """
    info = ChunkInfo(
        {
            "drops": {"Goblin": {"Wool": {"1": "1/10"}}},
            "challenges": {
                "Crafting": {"Weave a ~|coif|~": {"Items": ["Wool"], "Output": "Coif"}},
                "Diary": {"~|Varrock Diary#Medium|~ Task 10": {"Items": ["Coif"]}},
            },
        }
    )
    derived = _derived(
        monsters=("Goblin",),
        other_tasks=OtherTasks(
            categories={
                "Diary": CategoryTasks(
                    category="Diary",
                    groups=(
                        TaskGroup(
                            name="Varrock Diary - Medium",
                            active=("~|Varrock Diary#Medium|~ Task 10",),
                        ),
                    ),
                )
            }
        ),
    )

    result = _run(
        info,
        derived,
        Heuristics(
            monsters={"Goblin": Rate(100.0)},
            action_seconds={"Weave a ~|coif|~": 60.0},
        ),
    )

    (coif,) = [item for item in result.items if item.item == "Coif"]
    assert coif.source.startswith("make:")
    assert coif.group == "Varrock Diary - Medium"
    groups = result.sources_in("activities")
    assert len(groups) == 1
    assert groups[0][0] == "Varrock Diary - Medium"


def test_two_unrelated_leaf_items_cluster_under_one_task_and_add_up() -> None:
    """Craft a coif *and* buy a raw thing, both wanted by the same Diary
    task: neither is earned by doing the other, so the group's heading is
    their sum and not the longer of the two - the same rule
    `test_items_from_different_sources_still_add_up` pins for unrelated
    monster sources, now applied inside one Diary/CA cluster.

    The weave is given a real cost so Wool stays under
    `_DOMINANT_MATERIAL_SHARE` - see
    `test_a_leaf_item_groups_under_its_diary_task` for why."""
    info = ChunkInfo(
        {
            "drops": {"Goblin": {"Wool": {"1": "1/10"}}},
            "shopItems": {"Fish Shop": {"Raw thing": True}},
            "challenges": {
                "Crafting": {"Weave a ~|coif|~": {"Items": ["Wool"], "Output": "Coif"}},
                "Diary": {
                    "~|Varrock Diary#Medium|~ Task 10": {"Items": ["Coif", "Raw thing"]}
                },
            },
        }
    )
    derived = _derived(
        monsters=("Goblin",),
        challenges=ChallengeResult(
            valid={}, unsupported=frozenset(), available_items={"Raw thing": {}}
        ),
        other_tasks=OtherTasks(
            categories={
                "Diary": CategoryTasks(
                    category="Diary",
                    groups=(
                        TaskGroup(
                            name="Varrock Diary - Medium",
                            active=("~|Varrock Diary#Medium|~ Task 10",),
                        ),
                    ),
                )
            }
        ),
    )
    heuristics = Heuristics(
        monsters={"Goblin": Rate(100.0)},
        currency_per_hour={"Coins": 500_000.0},
        shop_prices={"Fish Shop": {"Raw thing": ShopPrice(price=100.0, currency="Coins")}},
        action_seconds={"Weave a ~|coif|~": 60.0},
    )

    result = _run(info, derived, heuristics)

    coif = next(item for item in result.items if item.item == "Coif")
    raw_thing = next(item for item in result.items if item.item == "Raw thing")
    assert coif.group == raw_thing.group == "Varrock Diary - Medium"
    assert coif.source != raw_thing.source

    groups = result.sources_in("activities")
    assert len(groups) == 1
    source, hours, entries = groups[0]
    assert source == "Varrock Diary - Medium"
    assert len(entries) == 2
    assert hours == pytest.approx(coif.hours + raw_thing.hours)
    assert result.buckets["activities"] == pytest.approx(coif.hours + raw_thing.hours)


def test_a_leaf_group_maxes_within_a_shared_source_and_sums_across_sources() -> None:
    """Two items bought on the same shop trip, plus a third that is made:
    the two shop items max together (one trip buys both), and the made item
    adds on top - `_group_total`'s "max within a source, sum across
    sources" rule, exercised inside one Diary/CA cluster.

    The weave is given a real cost so Wool stays under
    `_DOMINANT_MATERIAL_SHARE` - see
    `test_a_leaf_item_groups_under_its_diary_task` for why."""
    info = ChunkInfo(
        {
            "drops": {"Goblin": {"Wool": {"1": "1/10"}}},
            "shopItems": {"Fish Shop": {"Raw thing": True, "Raw other thing": True}},
            "challenges": {
                "Crafting": {"Weave a ~|coif|~": {"Items": ["Wool"], "Output": "Coif"}},
                "Diary": {
                    "~|Varrock Diary#Medium|~ Task 10": {
                        "Items": ["Coif", "Raw thing", "Raw other thing"]
                    }
                },
            },
        }
    )
    derived = _derived(
        monsters=("Goblin",),
        challenges=ChallengeResult(
            valid={},
            unsupported=frozenset(),
            available_items={"Raw thing": {}, "Raw other thing": {}},
        ),
        other_tasks=OtherTasks(
            categories={
                "Diary": CategoryTasks(
                    category="Diary",
                    groups=(
                        TaskGroup(
                            name="Varrock Diary - Medium",
                            active=("~|Varrock Diary#Medium|~ Task 10",),
                        ),
                    ),
                )
            }
        ),
    )
    heuristics = Heuristics(
        monsters={"Goblin": Rate(100.0)},
        currency_per_hour={"Coins": 500_000.0},
        shop_prices={
            "Fish Shop": {
                "Raw thing": ShopPrice(price=100.0, currency="Coins"),
                "Raw other thing": ShopPrice(price=1_000_000.0, currency="Coins"),
            }
        },
        action_seconds={"Weave a ~|coif|~": 60.0},
    )

    result = _run(info, derived, heuristics)

    coif = next(item for item in result.items if item.item == "Coif")
    raw_thing = next(item for item in result.items if item.item == "Raw thing")
    raw_other = next(item for item in result.items if item.item == "Raw other thing")
    assert raw_thing.source == raw_other.source
    assert coif.source != raw_thing.source

    groups = result.sources_in("activities")
    assert len(groups) == 1
    _, hours, entries = groups[0]
    assert len(entries) == 3
    assert hours == pytest.approx(coif.hours + max(raw_thing.hours, raw_other.hours))


def test_a_leaf_item_with_no_challenge_task_keeps_its_own_heading() -> None:
    """A BiS pick has no challenge behind it (`bis.py` synthesises the
    name), so there is no Diary/CA group to roll a made item up under - it
    keeps standing as its own `make:...` heading, same as before `group`
    existed.

    The weave is given a real cost so Wool stays under
    `_DOMINANT_MATERIAL_SHARE` - see
    `test_a_leaf_item_groups_under_its_diary_task` for why."""
    info = ChunkInfo(
        {
            "drops": {"Goblin": {"Wool": {"1": "1/10"}}},
            "challenges": {
                "Crafting": {"Weave a ~|coif|~": {"Items": ["Wool"], "Output": "Coif"}},
            },
        }
    )
    derived = _derived(
        monsters=("Goblin",),
        bis=BisResult(picks={}, active={"Obtain a ~|coif|~": "melee"}),
    )

    result = _run(
        info,
        derived,
        Heuristics(
            monsters={"Goblin": Rate(100.0)},
            action_seconds={"Weave a ~|coif|~": 60.0},
        ),
    )

    (coif,) = [item for item in result.items if item.item == "Coif"]
    assert coif.group == ""
    assert coif.source.startswith("make:")


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


def test_larrans_chest_prices_off_krystilias_key_rate_not_the_default() -> None:
    """Neither chest has a stat block, so without `costing/larran.py`'s
    injection this priced identically to `test_an_object_can_provide_an_item`
    above - `DEFAULT_KPH["regular"]`, 150/hr, as though the chest opened on
    demand. With one Krystilia task feeding a real key rate, it must not."""
    info = ChunkInfo(
        {
            "skillItems": {"Nonskill": {"Larran's small chest": {"Uncut ruby": {"1": "1/12"}}}},
            "challenges": {
                "Extra": {"Obtain an ~|uncut ruby|~": {"Items": ["Uncut ruby"]}}
            },
            "slayerMasterTasks": {"Krystilia": {"Cows": {"Weight": 1}}},
            "codeItems": {"slayerTasks": {"Cows": {"Cow": True}}},
        }
    )
    derived = Derived(
        reachable_sections={},
        expanded_chunks={"100": True},
        source_index=SourceIndex(
            items={},
            objects={"Larran's small chest": {"100": True}},
            monsters={"Cow": {"100": True}},
            npcs={"Krystilia": {"100": True}},
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
                    groups=(TaskGroup(name="Extra", active=("Obtain an ~|uncut ruby|~",)),),
                )
            }
        ),
    )
    heuristics = Heuristics(
        slayer={
            "Krystilia": {
                "Cows": SlayerTask(mean_count=10.0, xp_per_kill=1.0, kills_per_hour=100.0)
            }
        },
        monster_stats={"Cow": MonsterStats(name="Cow", hitpoints=8, combat_level=2)},
    )

    result = _run(info, derived, heuristics)

    (ruby,) = [item for item in result.items if item.item == "Uncut ruby"]
    # `DEFAULT_KPH["regular"]` (150/hr) is what an unpriced chest falls back
    # to - one open in 1/12 chance of a ruby is 12 opens, so 12/150 hours.
    # The real number must not land there: this map's one Krystilia task
    # earns keys far slower than an ordinary "kill" defaults to.
    default_hours = 12.0 / 150.0
    assert ruby.hours != pytest.approx(default_hours)


def test_material_seconds_exposes_the_walks_own_enriched_heuristics() -> None:
    """**The bug this pins.** `_setup` derives Larran's and the brimstone
    chest's own opens-per-hour into a *local* `heuristics` only its own
    `_Walk` closure ever saw - `material_seconds`'s caller (`costing/inputs.
    py`'s `recipe_priced`) kept its own, pre-`_setup` copy, so a correctly
    priced chest still read `DEFAULT_KPH`'s bare 150/hr through anything
    reading `Heuristics.monsters` directly rather than through the walk -
    the GUI's `monsters/Brimstone chest` knob among them. `_MaterialWalk.
    heuristics` is what `recipe_priced` now folds back in; this pins that it
    is the walk's own enriched copy and not the one passed in."""
    info = ChunkInfo(
        {
            "slayerMasterTasks": {
                "Krystilia": {"Cows": {"Weight": 1}},
                "Konar quo Maten": {"Cows": {"Weight": 1}},
            },
            "codeItems": {"slayerTasks": {"Cows": {"Cow": True}}},
        }
    )
    derived = _derived(
        monsters=("Cow",),
        source_index=SourceIndex(
            items={}, objects={}, monsters={"Cow": {"100": True}},
            npcs={"Krystilia": {"100": True}, "Konar quo Maten": {"100": True}},
            shops={}, drop_rates={},
        ),
    )
    heuristics = Heuristics(
        slayer={
            "Krystilia": {"Cows": SlayerTask(mean_count=10.0, xp_per_kill=1.0, kills_per_hour=100.0)},
            "Konar quo Maten": {"Cows": SlayerTask(mean_count=10.0, xp_per_kill=1.0, kills_per_hour=100.0)},
        },
        monster_stats={"Cow": MonsterStats(name="Cow", hitpoints=8, combat_level=2)},
    )

    walked = material_seconds(_state(info), derived, build_world_index(info), heuristics)

    small = walked.heuristics.kills_per_hour("Larran's small chest")
    chest = walked.heuristics.kills_per_hour("Brimstone chest")
    assert small.value > 0 and not small.source.startswith("default")
    assert chest.value > 0 and not chest.source.startswith("default")


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
    """Trading sticks and the various point currencies have no exchange rate
    anyone would agree on, so an item sold only for those is refused.

    **Castle Wars tickets used to be the example and are not any more**: they
    have a rate now (a scored draw is 2 tickets in 22 minutes), and once
    `currency_rate` folded case they were found through this spelling too.
    Which is the behaviour wanted - the refusal is about a currency nothing
    rates, not about how a `{{StoreLine}}` capitalises one.
    """
    heuristics = Heuristics(
        shop_prices={"Shop": {"Thing": ShopPrice(price=10.0, currency="Trading sticks")}}
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


def test_a_low_stock_shop_line_costs_a_hop_per_extra_world() -> None:
    """Lumbridge General Store's tinderbox: stock 2, 60s restock - real wiki
    figures, nowhere near `SHOP_RESTOCK_CUTOFF_SECONDS`. Filling a 27-item
    trip needs 13 more worlds once the first one's two are gone, and each of
    those is a `WORLD_HOP_SECONDS` hop the old model never charged."""
    info = ChunkInfo(
        {
            "shopItems": {"Lumbridge General Store": {"Tinderbox": True}},
            "challenges": {
                "Extra": {"Obtain a ~|tinderbox|~": {"Items": ["Tinderbox"]}}
            },
        }
    )
    heuristics = Heuristics(
        shop_prices={
            "Lumbridge General Store": {
                "Tinderbox": ShopPrice(
                    price=1.0, currency="Coins", stock=2, restock_seconds=60.0
                )
            }
        },
        currency_per_hour={"Coins": 3_600_000.0},
    )
    walk = _walk_for(info, heuristics)

    priced = _item_hours(walk, "Tinderbox", quantity=27.0)

    assert priced is not None
    earning = 1.0 * 27.0 * 3600.0 / 3_600_000.0
    travel = SHOP_TRIP_SECONDS
    hops = 13.0 * WORLD_HOP_SECONDS
    assert priced.hours == pytest.approx((earning + travel + hops) / 3600.0)


def test_a_generous_stock_costs_no_hops_at_all() -> None:
    """A trip that never exhausts the shop's own stock is the old behaviour -
    the hop model must not tax a route it does not apply to."""
    info = ChunkInfo(
        {
            "shopItems": {"Sawmill": {"Oak plank": True}},
            "challenges": {
                "Extra": {"Obtain an ~|oak plank|~": {"Items": ["Oak plank"]}}
            },
        }
    )
    heuristics = Heuristics(
        shop_prices={
            "Sawmill": {
                "Oak plank": ShopPrice(
                    price=500.0, currency="Coins", stock=1000, restock_seconds=60.0
                )
            }
        },
        currency_per_hour={"Coins": 500_000.0},
    )
    walk = _walk_for(info, heuristics)

    priced = _item_hours(walk, "Oak plank", quantity=1.0)

    assert priced is not None
    assert "hops" not in priced.detail
    assert priced.hours == pytest.approx((3.6 + SHOP_TRIP_SECONDS) / 3600.0)


def test_a_restock_over_an_hour_refuses_the_shop_route() -> None:
    """Toci's Gem Store's uncut ruby: 1 in stock, six hours to refill - split
    across roughly two hundred worlds, all competing for the same shelf. "No
    good way to estimate" that contention, so past
    `SHOP_RESTOCK_CUTOFF_SECONDS` this is refused outright rather than priced
    as though a private shop restocked for one player."""
    info = ChunkInfo(
        {
            "shopItems": {"Toci's Gem Store": {"Uncut ruby": True}},
            "challenges": {
                "Extra": {"Obtain an ~|uncut ruby|~": {"Items": ["Uncut ruby"]}}
            },
        }
    )
    heuristics = Heuristics(
        shop_prices={
            "Toci's Gem Store": {
                "Uncut ruby": ShopPrice(
                    price=100.0, currency="Coins", stock=1, restock_seconds=21_600.0
                )
            }
        },
        currency_per_hour={"Coins": 500_000.0},
    )
    walk = _walk_for(info, heuristics)

    assert _item_hours(walk, "Uncut ruby", quantity=1.0) is None


def test_a_zero_stock_shop_line_has_no_route_either() -> None:
    """`store_stock` of zero is the wiki stating outright that the shop does
    not proactively stock the line at all - a shelf a shop only refills from
    players selling it in is not a route to the first one."""
    info = ChunkInfo(
        {
            "shopItems": {"Toci's Gem Store": {"Uncut diamond": True}},
            "challenges": {
                "Extra": {"Obtain an ~|uncut diamond|~": {"Items": ["Uncut diamond"]}}
            },
        }
    )
    heuristics = Heuristics(
        shop_prices={
            "Toci's Gem Store": {
                "Uncut diamond": ShopPrice(
                    price=200.0, currency="Coins", stock=0, restock_seconds=7_200.0
                )
            }
        },
        currency_per_hour={"Coins": 500_000.0},
    )
    walk = _walk_for(info, heuristics)

    assert _item_hours(walk, "Uncut diamond", quantity=1.0) is None


def _tzhaar_gem_store_info() -> ChunkInfo:
    return ChunkInfo(
        {
            "chunks": {
                "9834": {
                    "Sections": {
                        "1": {"Shop": {"TzHaar-Hur-Rin's Ore and Gem Store": True}}
                    }
                },
            },
            "shopItems": {
                "TzHaar-Hur-Rin's Ore and Gem Store": {"Uncut ruby": True}
            },
            "challenges": {
                "Extra": {"Obtain an ~|uncut ruby|~": {"Items": ["Uncut ruby"]}}
            },
        }
    )


def _tzhaar_gem_store_heuristics() -> Heuristics:
    return Heuristics(
        shop_prices={
            "TzHaar-Hur-Rin's Ore and Gem Store": {
                "Uncut ruby": ShopPrice(
                    price=130.0, currency="Tokkul", stock=8, restock_seconds=300.0
                )
            }
        }
    )


def test_a_shop_in_a_chunk_this_map_never_opened_is_refused() -> None:
    """**The follow-up bug to the spawn one**: TzHaar-Hur-Rin's Ore and Gem
    Store priced an uncut ruby as cheap and plentiful once the spawn fix
    stopped masking it, on a map that had never opened the chunk the shop
    itself stands in - the same item-level-only gap `_location_reachable`
    closed for spawns, just not yet for shops."""
    info = _tzhaar_gem_store_info()
    walk = _walk_with_chunks(
        info, unlocked_chunks=frozenset(), heuristics=_tzhaar_gem_store_heuristics()
    )

    assert _item_hours(walk, "Uncut ruby", quantity=1.0) is None


def test_a_shop_in_an_unopened_section_of_an_unlocked_chunk_is_refused() -> None:
    """The chunk alone is not enough - the shop sits in section `1`, and
    unlocking the chunk only opens section `0` for free."""
    info = _tzhaar_gem_store_info()
    walk = _walk_with_chunks(
        info,
        unlocked_chunks=frozenset({"9834"}),
        heuristics=_tzhaar_gem_store_heuristics(),
    )

    assert _item_hours(walk, "Uncut ruby", quantity=1.0) is None


def test_a_shop_in_a_reachable_section_is_priced() -> None:
    """The positive case: once the section the shop stands in is reachable,
    the route prices exactly as it would with no chunk gate at all."""
    info = _tzhaar_gem_store_info()
    walk = _walk_with_chunks(
        info,
        unlocked_chunks=frozenset({"9834"}),
        reachable_sections={"9834": {"1": True}},
        heuristics=_tzhaar_gem_store_heuristics(),
    )

    assert _item_hours(walk, "Uncut ruby", quantity=1.0) is not None


def test_a_shop_with_no_stated_chunk_at_all_is_not_gated() -> None:
    """`derive.search.HAND_SHOP_SOURCES` exists for a shop the export never
    places in any chunk at all (Malignius Mortifer) - an empty location set
    means "nothing to check", not "unreachable", so this must stay priced."""
    info = ChunkInfo(
        {
            "shopItems": {"Malignius Mortifer": {"Magic secateurs": True}},
            "challenges": {
                "Extra": {
                    "Obtain a ~|magic secateurs|~": {"Items": ["Magic secateurs"]}
                }
            },
        }
    )
    heuristics = Heuristics(
        shop_prices={
            "Malignius Mortifer": {
                "Magic secateurs": ShopPrice(price=40_000.0, currency="Coins")
            }
        },
        currency_per_hour={"Coins": 500_000.0},
    )
    walk = _walk_with_chunks(info, unlocked_chunks=frozenset(), heuristics=heuristics)

    assert _item_hours(walk, "Magic secateurs", quantity=1.0) is not None


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


def test_a_spawn_in_a_chunk_this_map_never_opened_is_refused() -> None:
    """**The bug this was written for**: chunk `12581` section `1` (The
    Summer Shore) holds an uncut ruby spawn, but `reachable_lower`'s
    item-level check only asks "does an uncut ruby exist reachable
    *somewhere*" - true the moment any other route to it is - so the spawn
    priced as though this map had opened that chunk when it never had."""
    info = ChunkInfo(
        {
            "chunks": {
                "12581": {"Sections": {"1": {"Spawn": {"Uncut ruby": 1}}}},
            },
            "challenges": {
                "Extra": {"Obtain an ~|uncut ruby|~": {"Items": ["Uncut ruby"]}}
            },
        }
    )
    walk = _walk_with_chunks(info, unlocked_chunks=frozenset())

    assert _item_hours(walk, "Uncut ruby", quantity=1.0) is None


def test_a_spawn_in_an_unopened_section_of_an_unlocked_chunk_is_refused() -> None:
    """Unlocking chunk `12581` only opens section `0` for free - section `1`
    needs its own connectivity, which `derive/sections.py` computes into
    `reachable_sections` and this map's is empty."""
    info = ChunkInfo(
        {
            "chunks": {
                "12581": {"Sections": {"1": {"Spawn": {"Uncut ruby": 1}}}},
            },
            "challenges": {
                "Extra": {"Obtain an ~|uncut ruby|~": {"Items": ["Uncut ruby"]}}
            },
        }
    )
    walk = _walk_with_chunks(info, unlocked_chunks=frozenset({"12581"}))

    assert _item_hours(walk, "Uncut ruby", quantity=1.0) is None


def test_a_spawn_in_a_reachable_section_is_priced() -> None:
    """The positive case: once `reachable_sections` says section `1` is open,
    the same spawn prices exactly as an unsectioned one would."""
    info = ChunkInfo(
        {
            "chunks": {
                "12581": {"Sections": {"1": {"Spawn": {"Uncut ruby": 1}}}},
            },
            "challenges": {
                "Extra": {"Obtain an ~|uncut ruby|~": {"Items": ["Uncut ruby"]}}
            },
        }
    )
    walk = _walk_with_chunks(
        info,
        unlocked_chunks=frozenset({"12581"}),
        reachable_sections={"12581": {"1": True}},
    )

    priced = _item_hours(walk, "Uncut ruby", quantity=360.0)

    assert priced is not None
    # One per hop at 360 hops an hour is 360 an hour, so 360 takes an hour -
    # and reading the real per-section count is `_spawn_block`'s own fix:
    # the old lookup never found this chunk-and-section key at all.
    assert priced.hours == pytest.approx(1.0)


def test_a_spawn_in_section_zero_needs_no_reachable_sections_entry() -> None:
    """Section `"0"` is never a key in `reachable_sections` -
    `derive/sections.py` treats it as free the moment the chunk itself is
    unlocked, and this must not read the absence as *unreachable*."""
    info = ChunkInfo(
        {
            "chunks": {
                "12581": {"Sections": {"0": {"Spawn": {"Uncut ruby": 1}}}},
            },
            "challenges": {
                "Extra": {"Obtain an ~|uncut ruby|~": {"Items": ["Uncut ruby"]}}
            },
        }
    )
    walk = _walk_with_chunks(info, unlocked_chunks=frozenset({"12581"}))

    assert _item_hours(walk, "Uncut ruby", quantity=1.0) is not None


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
                "Woodcutting": {
                    "Cut ~|logs|~": {
                        "Output": "Logs",
                        "Items": [],
                        # A real ordinary Woodcutting action states this
                        # explicitly (every one of the export's 122 does) -
                        # unlike a minigame byproduct, which is exactly what
                        # `DEFAULT_ACTION_SECONDS` is a fair stand-in for. See
                        # `_UNGUIDED_GATHERING_SKILLS`.
                        "Primary": True,
                    }
                }
            },
            "chunks": {},
        }
    )
    walk = _walk_for(info)

    priced = _item_hours(walk, "Logs", quantity=10.0)

    assert priced is not None
    assert priced.hours == pytest.approx(10 * DEFAULT_ACTION_SECONDS / 3600)


def test_a_gathering_skills_unstated_byproduct_is_refused_not_defaulted() -> None:
    """`Catch a ~|raw manta ray|~` names no monster and is `Always`-certain,
    so the gate above (a monster beside a matching `Output`) never saw it -
    and it fell through to `DEFAULT_ACTION_SECONDS`, a 4-tick "fair stand-in"
    that was never a claim about a Fishing Trawler minigame byproduct.
    Priced anyway, `Cook a ~|manta ray|~` read as the whole climb's best
    Cooking method on a "catch" costing 2.4s - see `_UNGUIDED_GATHERING_SKILLS`.
    """
    info = ChunkInfo(
        {
            "challenges": {
                "Fishing": {
                    "Catch a ~|raw manta ray|~": {
                        "Category": ["Minigame"],
                        "Objects": ["Trawler boat"],
                        "Output": "Raw manta ray",
                        "Primary": False,
                    }
                }
            },
            "chunks": {},
        }
    )
    walk = _walk_for(info)

    assert _item_hours(walk, "Raw manta ray", quantity=1.0) is None


def test_an_ordinary_primary_gathering_task_still_gets_the_default() -> None:
    """The gate above is about *byproducts*, not about the five skills
    themselves - an ordinary `Primary` Fishing method with no stated pace
    still reads the plain `DEFAULT_ACTION_SECONDS`, the same as any other
    skill's."""
    info = ChunkInfo(
        {
            "challenges": {
                "Fishing": {
                    "Catch a ~|raw shrimps|~": {
                        "Output": "Raw shrimps",
                        "Primary": True,
                    }
                }
            },
            "chunks": {},
        }
    )
    walk = _walk_for(info)

    priced = _item_hours(walk, "Raw shrimps", quantity=1.0)

    assert priced is not None
    assert priced.hours == pytest.approx(DEFAULT_ACTION_SECONDS / 3600)


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


class TestItemRoutes:
    """`item_routes` is the Find panel's "Show sources" button: every way
    `_best_route` would consider for one item, kept rather than reduced to
    the single winner - see its own docstring for why a `[+]` family and a
    recipe/yield fallback are each handled differently from an ordinary
    kill/shop/spawn/task candidate."""

    def test_a_family_expands_into_one_row_per_member(self) -> None:
        info = ChunkInfo(
            {
                "codeItems": {
                    "itemsPlus": {"Air rune[+]": ["Air rune", "Dust rune", "Mist rune"]}
                },
                "chunks": {"1": {"Spawn": {"Air rune": 1, "Dust rune": 6}}},
            }
        )
        walk = _walk_for(info)
        object.__setattr__(
            walk, "item_families", {"Air rune[+]": ["Air rune", "Dust rune", "Mist rune"]}
        )

        routes = item_routes(walk, "Air rune[+]", quantity=6.0)

        assert [r.route for r in routes] == ["family", "family"]
        # Six dust runes a hop beats one air rune a hop - see the sibling
        # test this mirrors, `test_an_or_equivalent_item_is_priced_by_its_
        # cheapest_member`.
        assert routes[0].provider == "Dust rune"
        assert [r.priced.hours for r in routes] == sorted(r.priced.hours for r in routes)

    def test_every_kill_shop_and_spawn_candidate_is_kept(self) -> None:
        import dataclasses

        info = ChunkInfo(
            {
                "drops": {"Goblin": {"Widget": {"1": "1/10"}}},
                "shopItems": {"Bob's Shop": {"Widget": True}},
                "chunks": {"1": {"Spawn": {"Widget": 4}}},
            }
        )
        heuristics = Heuristics(
            monsters={"Goblin": Rate(100.0, "test", "exact")},
            shop_prices={"Bob's Shop": {"Widget": ShopPrice(price=1.0, currency="Coins")}},
            currency_per_hour={"Coins": 500_000.0},
        )
        walk = dataclasses.replace(
            _walk_for(info, heuristics), available=frozenset({"Goblin"})
        )

        routes = item_routes(walk, "Widget")

        assert {r.route for r in routes} == {"kill", "shop", "spawn"}
        assert [r.priced.hours for r in routes] == sorted(r.priced.hours for r in routes)

    def test_a_stacked_drop_is_priced_by_its_average_yield(self) -> None:
        """**The user's own bug report.** Revenant demons drop 8-16 Mahogany
        planks (mean 12) at 1/58, 230 kills/hr. The goal question - how long
        until the *first* plank - is a real 15.2 minutes, but that reads as
        the source's speed on a panel titled "sorted by time to obtain", and
        makes a high-stack drop look sixty times slower than it really
        supplies the material. The amortised answer divides the drop's own
        kills by its mean stack: `58 kills / 12 = 4.83` kills per plank, at
        230/hr that is 75.6 seconds - not the 15.2-minute floor."""
        import dataclasses

        info = ChunkInfo({"drops": {"Revenant demon": {"Mahogany plank": {"8-16": "1/58"}}}})
        heuristics = Heuristics(monsters={"Revenant demon": Rate(230.0, "test", "exact")})
        walk = dataclasses.replace(
            _walk_for(info, heuristics), available=frozenset({"Revenant demon"})
        )

        routes = item_routes(walk, "Mahogany plank")

        assert len(routes) == 1
        assert routes[0].priced.hours == pytest.approx((58 / 12) / 230.0)
        assert routes[0].priced.hours < (58 / 230.0)

    def test_a_recipe_is_hidden_behind_a_real_route(self) -> None:
        """**`Mahogany plank`'s own bug.** The export's `Process mahogany
        logs` challenge and the wiki's `{{Recipe}}` for the same page
        describe the identical sawmill trip - showing both as though a
        reader could choose between them is exactly the "unjoined method
        outranks its own charged twin" shape this project has been burned by
        before. Only the real route may appear once one exists."""
        import dataclasses

        from chunksim.remote.recipes import Recipe

        info = ChunkInfo(
            {
                "challenges": {
                    "Extra": {
                        "Make a ~|widget|~": {
                            "Objects": ["Bench"],
                            "Output": "Widget",
                        }
                    }
                },
            }
        )
        walk = _walk_for(info)
        recipe = Recipe(
            page="Widget", output="Widget", output_quantity=1.0, skill="Crafting",
            level=1, experience=0.0, ticks=1.0, materials=(),
        )
        walk = dataclasses.replace(walk, recipes={"widget": (recipe,)})

        routes = item_routes(walk, "Widget")

        assert [r.route for r in routes] == ["make"]

    def test_a_recipe_still_prices_when_nothing_else_does(self) -> None:
        import dataclasses

        from chunksim.remote.recipes import Recipe

        info = ChunkInfo({"chunks": {}, "challenges": {}})
        walk = _walk_for(info)
        recipe = Recipe(
            page="Widget", output="Widget", output_quantity=1.0, skill="Crafting",
            level=1, experience=0.0, ticks=1.0, materials=(),
        )
        walk = dataclasses.replace(walk, recipes={"widget": (recipe,)})

        routes = item_routes(walk, "Widget")

        assert [r.route for r in routes] == ["recipe"]

    def test_nothing_the_world_provides_is_an_empty_tuple(self) -> None:
        walk = _walk_for(ChunkInfo({"chunks": {}, "challenges": {}}))

        assert item_routes(walk, "Nothing at all") == ()


def test_best_route_amortises_a_stacked_kill_drop_through_the_fact_cache() -> None:
    """**`_kill_facts`/`_fact_hours` is a hot-path duplicate of `_kill_hours`,
    and it had drifted.** `item_routes` prices a "kill" row by calling
    `_kill_hours` directly and got the amortise fix; `_best_route` - what
    `chunksim estimate` and every nested production-chain material actually
    spend - prices the *same* kill route through `_fact_hours` instead,
    which kept flooring every kill at `1/chance` regardless of `amortise`.
    A stacked drop then priced far slower than it really supplies the item,
    and a "make" chain built from slower, unstacked ingredients could look
    cheaper than a kill route that was actually faster - exactly what the
    Find panel's drill-down surfaced for `Diamond amulet`: `_best_route`
    picked a 395s sawmill-style chain over a genuine 168s Magpie impling
    kill because the impling's own stacked drop was never amortised in this
    path, only in `item_routes`' independent one."""
    import dataclasses

    info = ChunkInfo({"drops": {"Goblin": {"Widget": {"3": "1/10"}}}})
    heuristics = Heuristics(monsters={"Goblin": Rate(100.0, "test", "exact")})
    walk = dataclasses.replace(_walk_for(info, heuristics), available=frozenset({"Goblin"}))

    priced = _item_hours(walk, "Widget", quantity=1.0, amortise=True)

    assert priced is not None
    # 1/10 chance, stack of 3: expected yield 0.3/kill, so 1/0.3 kills per
    # widget at 100/hr - not the 10-kill `1/chance` floor.
    assert priced.hours == pytest.approx((1 / 0.3) / 100.0)
    assert priced.hours < (10 / 100.0)


class TestPricedCandidate:
    """`priced_candidate` is the Find panel's drill-down side panel: one
    `item_routes` "make"/"recipe" row, re-priced with its own materials kept
    - see `costing/estimate.py`'s own docstring for why only those two route
    kinds are a production chain to drill into."""

    def test_a_make_route_keeps_its_own_materials(self) -> None:
        info = ChunkInfo(
            {
                "challenges": {
                    "Extra": {
                        "Make a ~|widget|~": {
                            "Objects": ["Bench"],
                            "Items": ["Cog", "Widget metal"],
                            "Output": "Widget",
                        }
                    }
                },
                "chunks": {"1": {"Spawn": {"Cog": 1, "Widget metal": 1}}},
            }
        )
        walk = _walk_for(info)

        step = priced_candidate(walk, "Widget", "make", "Make a ~|widget|~")

        assert step is not None
        assert step.label == "Widget"
        assert step.hours > 0
        assert {child.label for child in step.children} == {"Cog", "Widget metal"}

    def test_a_recipe_route_keeps_its_own_materials(self) -> None:
        import dataclasses

        from chunksim.remote.recipes import Material, Recipe

        info = ChunkInfo({"chunks": {"1": {"Spawn": {"Bar": 1}}}, "challenges": {}})
        walk = _walk_for(info)
        recipe = Recipe(
            page="Widget", output="Widget", output_quantity=1.0, skill="Crafting",
            level=1, experience=0.0, ticks=1.0,
            materials=(Material(name="Bar", quantity=2.0),),
        )
        walk = dataclasses.replace(walk, recipes={"widget": (recipe,)})

        step = priced_candidate(walk, "Widget", "recipe", "Widget")

        assert step is not None
        assert step.label == "Widget"
        assert [child.label for child in step.children] == ["Bar"]

    def test_a_nested_material_s_own_make_route_recurses(self) -> None:
        """`priced_candidate` calls `_item_hours(..., trace=True)` for each
        material, so a material whose own cheapest route is itself another
        real challenge keeps *its* materials too, without a second request -
        `Amulet of power`'s own worked example on the real map."""
        info = ChunkInfo(
            {
                "challenges": {
                    "Extra": {
                        "Make a ~|widget|~": {
                            "Objects": ["Bench"],
                            "Items": ["Cog"],
                            "Output": "Widget",
                        },
                        "Make a ~|cog|~": {
                            "Objects": ["Lathe"],
                            "Items": ["Metal bar"],
                            "Output": "Cog",
                        },
                    }
                },
                "chunks": {"1": {"Spawn": {"Metal bar": 1}}},
            }
        )
        walk = _walk_for(info)

        step = priced_candidate(walk, "Widget", "make", "Make a ~|widget|~")

        assert step is not None
        cog = next(child for child in step.children if child.label == "Cog")
        assert [grandchild.label for grandchild in cog.children] == ["Metal bar"]

    def test_only_make_and_recipe_are_drillable(self) -> None:
        assert DRILLABLE_ROUTES == frozenset({"make", "recipe"})

    def test_a_kill_route_has_nothing_to_drill_into(self) -> None:
        import dataclasses

        info = ChunkInfo({"drops": {"Goblin": {"Widget": {"1": "1/10"}}}})
        heuristics = Heuristics(monsters={"Goblin": Rate(100.0, "test", "exact")})
        walk = dataclasses.replace(
            _walk_for(info, heuristics), available=frozenset({"Goblin"})
        )

        assert priced_candidate(walk, "Widget", "kill", "Goblin") is None

    def test_a_make_route_no_longer_priceable_refuses(self) -> None:
        walk = _walk_for(ChunkInfo({"chunks": {}, "challenges": {}}))

        assert priced_candidate(walk, "Widget", "make", "Make a ~|widget|~") is None


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
    from chunksim.store.cache import data_root
    from chunksim.store.cache import file_digest
    from chunksim.store.derived_cache import Digests
    from chunksim.store import cache as cache_module

    state, unlocked = real_state
    digests = Digests(
        chunkinfo=file_digest(cache_module.chunkinfo_source(None, data_root())),
        tasks_map=file_digest(
            cache_module.blob_path(cache_module.TASKS_MAP_BLOB_NAME, data_root())
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


def test_a_monster_named_beside_a_different_output_is_a_kill_not_an_action() -> None:
    """**The ent, and why a four-tick default is the wrong shape for a kill.**

    `Cut magic logs from an ~|ent|~` names `Monsters: ["Ent"]` and outputs
    `Magic logs`, so the item walk priced a magic log at 3.6 seconds - the same
    3.6 as an oak log, because `DEFAULT_ACTION_SECONDS` knows nothing about
    either - against 25.6 for chopping one. An ent is a Forestry event, not
    something available every four ticks.

    `_route_hours` already made this argument for `Output != item`: "a kill has
    a route of its own (`_kill_hours`, with the gear and the gates), so
    refusing here loses nothing". It had never been applied when the output
    *is* the item asked for.

    Measured over the whole export the rule refuses 17 routes, 12 of them
    already priced above 250 seconds by their own inputs; what moves is the
    five ent challenges, and Fletching 1-99 with them - 41.3h to 84.4h,
    because Vale Totems had been fed magic logs at an oak log's price.
    """
    info = ChunkInfo(
        {
            "chunks": {"1": {"Monsters": {"Ent": True}, "Objects": {"Magic tree": True}}},
            "challenges": {
                "Woodcutting": {
                    "Cut magic logs from an ~|ent|~": {
                        "Monsters": ["Ent"],
                        "Output": "Magic logs",
                        "Primary": False,
                    },
                    "Chop ~|magic logs|~": {
                        "Objects": ["Magic tree"],
                        "Output": "Magic logs",
                        "Primary": True,
                    },
                }
            },
        }
    )
    # Chopping is timed; the ent is not, which is the whole distinction.
    walk = _walk_for(info, Heuristics(action_seconds={"Chop ~|magic logs|~": 25.6}))

    priced = _item_hours(walk, "Magic logs", quantity=1.0)

    assert priced is not None
    assert priced.hours * 3600 == pytest.approx(25.6)
    assert "ent" not in priced.detail


def test_a_consumed_secondary_beside_monsters_is_priced_off_it() -> None:
    """**The exception to the ent rule.** `Chest (Bryophyta's lair)*` also
    names `Monsters: ["Bryophyta"]` beside its `Output`, but unlike the ent
    it carries a real `Items: ["Mossy key*"]` - `*` marks a consumed
    secondary ingredient (`challenges._is_secondary`'s docstring), not a
    tool like the ent's unmarked `Axe[+]`. The certainty gate must let this
    one through and price the chest off the key's own cheapest source
    (Bryophyta here) plus one default action, rather than falling to
    `DEFAULT_KPH["regular"]` for something that is not a walk-up monster.
    """
    from chunksim.costing.estimate import _Walk

    info = ChunkInfo(
        {
            "chunks": {"1": {"Monsters": {"Bryophyta": True}}},
            "drops": {"Bryophyta": {"Mossy key": {"1": "1/16"}}},
            "challenges": {
                "Nonskill": {
                    "Chest (Bryophyta's lair)*": {
                        "Items": ["Mossy key*"],
                        "Monsters": ["Bryophyta"],
                        "Output": "Chest (Bryophyta's lair)",
                    },
                }
            },
        }
    )
    world = build_world_index(info)
    # `_walk_for` leaves `available` empty, which is fine for routes that
    # never take a kill fact - this one needs "Bryophyta" reachable so the
    # key itself can price, so the walk is built by hand instead.
    walk = _Walk(
        chunk_info=info,
        world=world,
        heuristics=Heuristics(monsters={"Bryophyta": Rate(3600.0 / 100.0)}),
        by_lower={item.lower(): item for item in world.item_sources},
        reachable_items=frozenset(world.item_sources),
        available=frozenset({"Bryophyta"}),
    )

    priced = _item_hours(walk, "Chest (Bryophyta's lair)", quantity=1.0)

    assert priced is not None
    # 16 kills at 100s each for the key, plus one default action to open it.
    assert priced.hours * 3600 == pytest.approx(16 * 100.0 + DEFAULT_ACTION_SECONDS)
    # The key's own 1,600s clears `_DOMINANT_MATERIAL_SHARE` against the
    # four-tick action fee, so the chest's source propagates to `Bryophyta`
    # rather than staying its own one-off `make:...` heading - the chest
    # really is "kill Bryophyta", same as the key it opens with.
    assert priced.source == "Bryophyta"


def test_a_tool_beside_monsters_does_not_open_the_gate() -> None:
    """An unmarked `Items` entry is a tool (`Axe[+]`, never consumed) and
    must not be read as the ent rule's exception - only a `*`-marked entry
    says the item walk actually knows the real cost."""
    info = ChunkInfo(
        {
            "chunks": {"1": {"Monsters": {"Ent": True}, "Objects": {"Magic tree": True}}},
            "challenges": {
                "Woodcutting": {
                    "Cut magic logs from an ~|ent|~": {
                        "Items": ["Axe[+]"],
                        "Monsters": ["Ent"],
                        "Output": "Magic logs",
                        "Primary": False,
                    },
                    "Chop ~|magic logs|~": {
                        "Objects": ["Magic tree"],
                        "Output": "Magic logs",
                        "Primary": True,
                    },
                }
            },
        }
    )
    walk = _walk_for(info, Heuristics(action_seconds={"Chop ~|magic logs|~": 25.6}))

    priced = _item_hours(walk, "Magic logs", quantity=1.0)

    assert priced is not None
    assert priced.hours * 3600 == pytest.approx(25.6)
    assert "ent" not in priced.detail


def test_an_output_that_is_the_monster_is_left_alone() -> None:
    """**What `item not in monsters` keeps.** `Slay a ~|bloodveld|~` outputs
    `Bloodveld` - a slayer token rather than a drop to price - and refusing it
    would take the four-tick stand-in away from a hundred of them for nothing.
    """
    info = ChunkInfo(
        {
            "chunks": {"1": {"Monsters": {"Bloodveld": True}}},
            "challenges": {
                "Slayer": {
                    "Slay a ~|bloodveld|~": {
                        "Monsters": ["Bloodveld"],
                        "Output": "Bloodveld",
                        "Primary": True,
                    }
                }
            },
        }
    )
    walk = _walk_for(info)

    priced = _item_hours(walk, "Bloodveld", quantity=1.0)

    assert priced is not None
    assert priced.hours * 3600 == pytest.approx(DEFAULT_ACTION_SECONDS)


def test_a_potion_dose_is_priced_off_another_dose() -> None:
    """**Doses are fungible and nothing else in the walk knew it.** No action
    in the game *makes* a two-dose potion - you brew a three or a four and
    drink one, or decant - so `Attack potion(2)` had no route at all while
    `Attack potion(3)` priced in a second. Eighteen Herblore methods were
    dropped for it, which is why a published xp/hour survived on 26 of them.

    A dose is a dose, so `N` of them cost `N/M` of an `M`-dose potion.
    """
    from chunksim.costing.estimate import _DOSE

    found = _DOSE.match("Attack potion(2)")
    assert found is not None
    assert (found.group("name"), found.group("dose")) == ("Attack potion", "2")
    assert _DOSE.match("Attack potion") is None
    assert _DOSE.match("Bucket of sand") is None


def test_the_walk_carries_no_depth_budget() -> None:
    """**The bound is gone, and it must not creep back as a parameter.** Three
    mechanisms existed only to manage it - `partial_products`, dose hops
    "spending no depth", the budget half of the memo's reuse rule - and each
    was a work-around for the unmemoised walk's cost, not a statement about
    the game. Cycles are the visited set's job: a path that closes on itself
    is discarded, and the item still prices through any acyclic chain that
    reaches it."""
    import inspect

    from chunksim.costing import estimate as module
    from chunksim.costing.estimate import _best_route, _dose_hours, _item_hours

    assert not hasattr(module, "_MAX_DEPTH")
    for walker in (_item_hours, _best_route, _dose_hours):
        assert "depth" not in inspect.signature(walker).parameters
        # And no visited set either: cycles are the fixpoint table's job, so
        # a `seen` parameter reappearing would mean the path search is back.
        assert "seen" not in inspect.signature(walker).parameters


def test_a_recipe_is_the_last_resort_route() -> None:
    """**The export lists what pays experience, not everything you can make.**
    Chiselling a dark essence block into fragments pays *Crafting*, so upstream
    carries no Runecraft challenge for it - and `Dark essence fragments` had no
    route at all on a map holding the Dark Altar. That cost the second cache
    its two best Runecraft methods: blood runes read 11,118/hr off pure essence
    where the same altar does 31,316 off fragments, and soul runes were
    refused outright.

    Tried only when every other route has failed, so nothing that already
    prices can change.
    """
    import inspect

    from chunksim.costing.estimate import _best_route, _recipe_hours

    # `_best_route` is `_item_hours` past its guard and subtree memo - the
    # route ordering lives there now.
    source = inspect.getsource(_best_route)
    assert "if best is None:" in source, "the recipe route must be a last resort"
    assert source.index("_route_hours") < source.index("_recipe_hours")
    assert "output_quantity" in inspect.getsource(_recipe_hours), "one chisel makes four"


def test_a_stated_duration_reaches_the_walk_before_the_default_does() -> None:
    """**`DEFAULT_ACTION_SECONDS` is the last word here, not the first.** An
    untimed recipe has to fall back to something, but where somebody has
    actually counted the action the count must arrive first - which means the
    stated durations are applied to the corpus `_setup` flattens, not left
    to `recipe_rates`. Chiselling a dark essence block is the case that forced
    it: it is done *while running* to the altar, so it costs nothing, and the
    default charged 0.6s a fragment. Blood runes on the second cache went
    25,802/hr to 31,316 and soul runes 32,035 to 38,880."""
    import dataclasses
    import inspect

    from chunksim.costing import chisel
    from chunksim.costing.estimate import _recipe_hours, _setup

    source = inspect.getsource(_setup)
    assert "recipe_rates.stated_ticks" in source, "one merge, not three copies"
    assert source.index("stated_ticks") < source.index("by_output[key]"), (
        "the durations must be applied before the corpus is flattened"
    )

    # And the walk spends the zero rather than reading it as a missing figure,
    # which is the whole difference between a stated duration and an unknown.
    from chunksim.costing.estimate import DEFAULT_ACTION_SECONDS
    from chunksim.remote.recipes import Recipe

    def _priced(ticks: float | None) -> Any:
        recipe = Recipe(
            page="Thing", output="Thing", output_quantity=4.0, skill="Crafting",
            level=1, experience=8.0, ticks=ticks, materials=(),
        )
        walk = dataclasses.replace(
            _walk_for(ChunkInfo({"chunks": {}, "sections": {}, "challenges": {}})),
            recipes={"thing": (recipe,)},
        )
        return _recipe_hours(walk, "Thing", 4.0, amortise=False)

    free, unknown = _priced(float(chisel.CHISEL_TICKS)), _priced(None)
    assert free is not None and free.hours == 0.0
    assert unknown is not None
    assert unknown.hours == pytest.approx(DEFAULT_ACTION_SECONDS / 3600.0)


def test_a_chain_prices_however_long_it_is() -> None:
    """**The pies were the depth bound's last casualty and now need no
    special case.** `Raw fish pie` is `Part fish pie (cod)` <- `Part fish pie
    (trout)` <- `Pie shell` <- `Pastry dough` <- its materials - six recipe
    hops - and under `_MAX_DEPTH = 5` it priced only because upstream's
    `Partial Products` category exempted the assembly stages. With the bound
    gone the chain prices on its own arithmetic, and so does anything
    longer: the walk's limit is the cheapest acyclic derivation, not a
    hop count."""
    chunks = {"1111": {"Spawn": {"Link 9": 1}}}
    challenges: dict[str, Any] = {}
    for step in range(9):
        challenges[f"Make link {step}"] = {
            "Items": [f"Link {step + 1}"],
            "Output": f"Link {step}",
            "Primary": True,
        }
    info = ChunkInfo({"challenges": {"Crafting": challenges}, "chunks": chunks})

    priced = _item_hours(_walk_for(info), "Link 0")

    assert priced is not None, "nine hops, every one of them acyclic"
    # One spawn pickup plus nine defaulted actions - the chain is charged in
    # full, not waved through.
    assert priced.hours * 3600.0 > 9 * DEFAULT_ACTION_SECONDS


class TestTheFixpointWalk:
    """**A cycle is a discarded path, never a discarded item.**

    The walk settles each `(item, quantity, amortise)` question into a table;
    a route that closes on a key still being evaluated reads last round's
    belief instead of exploring around itself. These pin the semantics the
    user asked for by name: a chain that closes on itself contributes
    nothing, and an item reachable by any acyclic chain still prices.
    """

    def _chain_info(self) -> ChunkInfo:
        """`Deep 0` is made from `Deep 1` is made from ... `Deep 5`, which is
        a spawn."""
        chunks = {"1111": {"Spawn": {"Deep 5": 1}}}
        challenges: dict[str, Any] = {}
        for step in range(5):
            challenges[f"Make deep {step}"] = {
                "Items": [f"Deep {step + 1}"],
                "Output": f"Deep {step}",
                "Primary": True,
            }
        return ChunkInfo({"challenges": {"Crafting": challenges}, "chunks": chunks})

    def test_a_pure_cycle_refuses(self) -> None:
        """Two items each made only from the other is no route at all - the
        first round's empty beliefs discard both paths, and no later round
        can improve on a system with no leaf anywhere."""
        info = ChunkInfo(
            {
                "chunks": {},
                "challenges": {
                    "Crafting": {
                        "Make an egg": {"Items": ["Chicken"], "Output": "Egg", "Primary": True},
                        "Make a chicken": {"Items": ["Egg"], "Output": "Chicken", "Primary": True},
                    }
                },
            }
        )
        walk = _walk_for(info)

        assert _item_hours(walk, "Egg") is None
        assert _item_hours(walk, "Chicken") is None

    def test_a_cycle_with_a_leaf_prices_both_members(self) -> None:
        """The user's own statement of the semantics: discarding a cyclic
        path must not discard the item - anything an acyclic chain reaches
        still prices. Here the egg also spawns, so the chicken prices through
        it and the egg never prices through the chicken."""
        info = ChunkInfo(
            {
                "chunks": {"1111": {"Spawn": {"Egg": 1}}},
                "challenges": {
                    "Crafting": {
                        "Make an egg": {"Items": ["Chicken"], "Output": "Egg", "Primary": True},
                        "Make a chicken": {"Items": ["Egg"], "Output": "Chicken", "Primary": True},
                    }
                },
            }
        )
        walk = _walk_for(info)

        egg = _item_hours(walk, "Egg")
        chicken = _item_hours(walk, "Chicken")

        assert egg is not None and egg.source.startswith("spawn:")
        assert chicken is not None and chicken.hours > egg.hours

    def test_the_dose_cycle_still_prices_every_strength(self) -> None:
        """The case the old visited set handled and the table must too: no
        action makes a two-dose potion, so `(2)` prices as doses of the
        spawned `(3)` while `(3)` never prices through `(2)`."""
        info = ChunkInfo(
            {"challenges": {}, "chunks": {"1111": {"Spawn": {"Attack potion(3)": 1}}}}
        )
        walk = _walk_for(info)

        three = _item_hours(walk, "Attack potion(3)")
        two = _item_hours(walk, "Attack potion(2)")

        assert three is not None and three.source.startswith("spawn:")
        assert two is not None
        assert "doses" in two.detail

    def test_a_question_that_never_met_a_cycle_settles_in_one_round(self) -> None:
        """`_Fixpoint.consulted` stays False down an acyclic chain, which is
        what keeps the convergence loop off the common path."""
        walk = _walk_for(self._chain_info())

        assert _item_hours(walk, "Deep 0") is not None
        assert not walk.fixpoint.reads, "an acyclic chain reads no beliefs"
        assert ("Deep 0", 1.0, False, False) in walk.fixpoint.settled

    def test_settled_answers_are_shared_across_questions(self) -> None:
        """The table is the memo: the second question reads what the first
        settled rather than walking the chain again."""
        walk = _walk_for(self._chain_info())
        _item_hours(walk, "Deep 0")

        before = dict(walk.fixpoint.settled)
        again = _item_hours(walk, "Deep 3")

        assert again == before[("Deep 3", 1.0, False, False)]

    def test_replacing_walk_fields_that_move_answers_resets_the_caches(self) -> None:
        """`dataclasses.replace` shares field references, so the two sites
        that swap `recipes`/`made_experience` must hand the new walk a fresh
        fixpoint - settled answers embed experience credits and corpus
        routing."""
        import inspect

        from chunksim.costing import estimate as module

        source = inspect.getsource(module)
        for site in ("recipes=by_output", "made_experience=made_experience"):
            at = source.index(site)
            window = source[at : at + 200]
            assert "fixpoint=_Fixpoint()" in window, site
            assert "leaf_routes={}" in window, site


class TestTheTraceFlag:
    """`trace=True` keeps `_route_hours`' own `inputs` list on `_Priced.children`
    instead of discarding it - see `training.trace_option`. Pinned here, not
    in `test_training.py`, because the flag is `estimate.py`'s own surgery and
    `training.py` never touches `_item_hours` directly."""

    def _chain_info(self) -> ChunkInfo:
        """`Deep 0` is made from `Deep 1` is made from `Deep 2`, which spawns -
        the shortest chain with a real two-hop `children` tree to check."""
        chunks = {"1111": {"Spawn": {"Deep 2": 1}}}
        challenges: dict[str, Any] = {}
        for step in range(2):
            challenges[f"Make deep {step}"] = {
                "Items": [f"Deep {step + 1}"],
                "Output": f"Deep {step}",
                "Primary": True,
            }
        return ChunkInfo({"challenges": {"Crafting": challenges}, "chunks": chunks})

    def test_untraced_is_a_leaf_regardless_of_depth(self) -> None:
        """The default - every existing call site in the project - must keep
        seeing a flat answer, not a tree nobody asked for."""
        walk = _walk_for(self._chain_info())

        priced = _item_hours(walk, "Deep 0")

        assert priced is not None
        assert priced.children == ()

    def test_traced_keeps_the_whole_chain(self) -> None:
        walk = _walk_for(self._chain_info())

        priced = _item_hours(walk, "Deep 0", trace=True)

        assert priced is not None
        assert len(priced.children) == 1
        middle = priced.children[0]
        assert middle.source == "make:Make deep 1"
        assert middle.label == "Deep 1"
        assert len(middle.children) == 1
        leaf = middle.children[0]
        assert leaf.source.startswith("spawn:")
        assert leaf.label == "Deep 2"
        assert leaf.children == ()
        assert priced.label == "", "the root has nothing to label itself with"

    def test_children_sum_back_to_the_parents_own_hours(self) -> None:
        """Not an independent number: the parent's `.hours` is its own action
        overhead (`DEFAULT_ACTION_SECONDS`, unstated here) plus its children's
        `.hours`, which is what makes the tree an honest breakdown of the flat
        figure rather than a second answer beside it."""
        walk = _walk_for(self._chain_info())

        priced = _item_hours(walk, "Deep 0", trace=True)

        assert priced is not None
        overhead = DEFAULT_ACTION_SECONDS / 3600.0
        middle = priced.children[0]
        assert middle.hours == pytest.approx(
            sum(child.hours for child in middle.children) + overhead
        )
        assert priced.hours == pytest.approx(middle.hours + overhead)

    def test_tracing_does_not_move_the_untraced_answer(self) -> None:
        """The regression this flag must never cause: asking the traced
        question first must not change what the untraced question - the one
        every existing caller asks - settles to. The two are different
        fixpoint keys (`(item, quantity, amortise, trace)`), so they must
        never collide."""
        walk = _walk_for(self._chain_info())

        traced = _item_hours(walk, "Deep 0", trace=True)
        untraced = _item_hours(walk, "Deep 0")

        assert traced is not None and untraced is not None
        assert traced.hours == untraced.hours
        assert traced.detail == untraced.detail
        assert traced.source == untraced.source
        assert untraced.children == ()
        assert traced.children != ()


class TestKillFactsMatchKillHours:
    """**Two expressions of one arithmetic, pinned against each other.**

    The leaf scan prices kill routes off hoisted `_KillFact`s - gates, drop
    rates and master waits resolved once per item - while `_kill_hours` stays
    as the live path for superiors and any direct caller. If the two ever
    disagree, a tie against a live route resolves differently and the winner
    changes silently, which is exactly the class of bug an exact optimisation
    must not have.
    """

    def _info(self) -> ChunkInfo:
        return ChunkInfo(
            {
                "chunks": {"1111": {"Monsters": ["Goblin"]}},
                "drops": {"Goblin": {"Bones": {"1": "Always"}, "Goblin mail": {"1": "1/8"}}},
                "challenges": {},
            }
        )

    def test_an_ungated_kill_agrees_to_the_float(self) -> None:
        from chunksim.costing.estimate import _fact_hours, _fact_priced, _kill_facts, _kill_hours

        walk = _walk_for(
            self._info(), Heuristics(monsters={"Goblin": Rate(60.0, "mmg:x", "exact")})
        )
        walk = __import__("dataclasses").replace(walk, available=frozenset({"Goblin"}))

        for quantity in (1.0, 3.0, 40.0):
            live = _kill_hours(walk, "Goblin", "Goblin mail", quantity)
            facts, _ = _kill_facts(
                walk, "Goblin mail", walk.world.item_sources.get("Goblin mail", ())
            )
            assert live is not None and len(facts) == 1
            hours, _, _key = _fact_hours(facts[0], quantity)
            assert hours == live.hours, "not approx - the tie-break needs the bits"
            assert _fact_priced(facts[0], quantity, "") == live

    def test_a_source_that_cannot_price_is_dropped_once(self) -> None:
        """Unreachable monsters produce no fact, matching `_kill_hours`'
        `None` - and none of the per-quantity work it used to pay."""
        from chunksim.costing.estimate import _kill_facts, _kill_hours

        walk = _walk_for(self._info())  # nothing in `available`

        assert _kill_hours(walk, "Goblin", "Goblin mail") is None
        facts, live = _kill_facts(
            walk, "Goblin mail", walk.world.item_sources.get("Goblin mail", ())
        )
        assert facts == () and live == ()


class TestMaterialAliases:
    """A recipe's own material is the wiki's vocabulary; `world.item_sources`
    is built entirely from the export's `Output` strings. Where the two
    disagree, the literal name has no route even though the export plainly
    provides the thing - see `recipe_rates.MATERIAL_ALIASES`."""

    def _info(self) -> ChunkInfo:
        return ChunkInfo(
            {
                "shopItems": {"Jalsavrah": {"Pharaoh's sceptre": True}},
                "challenges": {
                    "Extra": {
                        "Obtain a ~|pharaoh's sceptre|~": {"Items": ["Pharaoh's sceptre"]}
                    }
                },
            }
        )

    def _walked(
        self, info: ChunkInfo, *, material_aliases: dict[str, str] = {}
    ) -> Any:
        derived = _derived(
            challenges=ChallengeResult(
                valid={"Extra": {"Obtain a ~|pharaoh's sceptre|~": True}},
                unsupported=frozenset(),
                available_items={
                    "Pharaoh's sceptre": {
                        "Obtain a ~|pharaoh's sceptre|~": "primary-Extra"
                    }
                },
            )
        )
        return material_seconds(
            _state(info),
            derived,
            build_world_index(info),
            self._heuristics(),
            material_aliases=material_aliases,
        )

    def _heuristics(self) -> Heuristics:
        return Heuristics(
            shop_prices={
                "Jalsavrah": {
                    "Pharaoh's sceptre": ShopPrice(price=100.0, currency="Coins")
                }
            },
            currency_per_hour={"Coins": 500_000.0},
        )

    def test_the_literal_wiki_name_has_no_route(self) -> None:
        walked = self._walked(self._info())

        assert walked.seconds("Pharaoh's sceptre (uncharged)", 1.0) is None

    def test_the_alias_finds_the_export_s_route(self) -> None:
        walked = self._walked(
            self._info(), material_aliases=dict(recipe_rates.MATERIAL_ALIASES)
        )

        assert walked.seconds("Pharaoh's sceptre (uncharged)", 1.0) is not None

    def test_a_name_the_export_already_knows_never_reaches_the_alias(self) -> None:
        """The alias is a fallback, tried only once the literal name fails -
        so a material the export *does* recognise is priced on its own route
        rather than being silently redirected."""
        walked = self._walked(
            self._info(),
            material_aliases={"Pharaoh's sceptre": "Something else entirely"},
        )

        assert walked.seconds("Pharaoh's sceptre", 1.0) is not None


class TestAnItemPackIsAHundred:
    """**Upstream models a pack conversion as one-for-one and it is not.**
    Every `<X> pack` challenge states `Items: ["<X> pack*"]` and an `Output` of
    the bare item, so the walk charged a whole pack - ten marks of grace, half
    an hour - for a single amylase crystal. The count is stated on each pack's
    own page ("A pack containing 100 feathers") and is 100 on all twenty-three
    the export carries - each checked against its own page - which is why it
    is a constant rather than a table.
    """

    def test_a_pack_yields_a_hundred(self) -> None:
        from chunksim.costing.estimate import PACK_UNITS, _pack_units

        challenge = {"Items": ["Amylase pack*"], "Output": "Amylase crystal"}

        assert _pack_units(challenge) == PACK_UNITS == 100.0

    def test_an_ordinary_challenge_yields_one(self) -> None:
        from chunksim.costing.estimate import _pack_units

        challenge = {"Items": ["Iron ore*", "Coal*"], "Output": "Steel bar"}

        assert _pack_units(challenge) == 1.0

    def test_a_loot_table_is_a_roll_rather_than_a_hundred(self) -> None:
        """Six `Open a ... pack*` challenges name a table instead - `Herb pack
        loot`, `Seed pack loot`. Those are rolls, and dividing one by a hundred
        would claim an open hands over a hundred of whatever came out."""
        from chunksim.costing.estimate import _pack_units

        challenge = {"Items": ["Herb pack*"], "Output": "Herb pack loot"}

        assert _pack_units(challenge) == 1.0

    def test_the_pack_itself_is_still_whole(self) -> None:
        """**The division is the contents, not the price.** `heuristics.
        SHOP_BUNDLES` divides a scraped shop price where a `{{StoreLine}}`
        sells a stack under one name; reusing it here would say a pack costs a
        tenth of a mark, where the truth is that it costs ten and holds a
        hundred."""
        from chunksim.costing.estimate import _pack_units

        assert _pack_units({"Items": ["Bucket pack*"], "Output": "Bucket"}) == 100.0
        assert _pack_units({"Items": [], "Output": "Amylase pack"}) == 1.0


@pytest.mark.real_export
def test_every_item_pack_upstream_carries_is_the_same_shape(
    real_export: ChunkInfo,
) -> None:
    """**The measurement behind `PACK_UNITS` being a constant.** 23 challenges
    turn a `<X> pack` into a plain item and every one of their packs states
    "A pack containing 100 ..." on its own page - checked by hand across all
    23 when this was written. Six more name a loot table instead and are the
    reason `_pack_units` looks at the `Output`.
    """
    from chunksim.costing.estimate import _pack_units

    units: list[str] = []
    loot: list[str] = []
    for challenges in real_export.challenges.values():
        if not isinstance(challenges, dict):
            continue
        for entry in challenges.values():
            if not isinstance(entry, dict):
                continue
            made = entry.get("Output")
            if not isinstance(made, str):
                continue
            if not any(
                isinstance(item, str)
                and item.replace("*", "").strip().lower().endswith(" pack")
                for item in entry.get("Items") or ()
            ):
                continue
            (loot if made.endswith(" loot") else units).append(made)
            assert _pack_units(entry) == (1.0 if made.endswith(" loot") else 100.0)

    assert len(set(units)) == len(units) == 23, sorted(units)
    assert len(loot) == 6, sorted(loot)


class TestAGatedKillIsPricedAsOne:
    """**The third layer to learn that a kill can need sending for.** The
    drop route and the superior route both paid the wait; the kill-goal route
    priced `1 / kills_per_hour` flat, so `Alchemical Hydra` - which you may
    only fight on a Hydras task - read as three minutes for four Combat
    Achievements.
    """

    def test_all_three_routes_go_through_one_function(self) -> None:
        """`_task_hours` is the single answer, so the drop, superior and
        kill-goal routes cannot disagree about what being assigned costs."""
        import chunksim.costing.estimate as module

        source = pathlib.Path(module.__file__).read_text()
        # The kill-goal branch, the drop branch and the superior branch.
        assert source.count("_task_hours(walk,") >= 3

    def test_the_gate_carries_its_place(self) -> None:
        """Without it the join to a location-keyed master is a prefix match,
        which shortens the wait for an assignment that may not qualify."""
        gate = TaskGate(task="Hydras", place="Karuulm Slayer Dungeon")
        assert gate.task == "Hydras"
        assert gate.place == "Karuulm Slayer Dungeon"


@pytest.mark.real_export
def test_the_pooled_herb_scan_matches_asking_one_herb_at_a_time(
    real_state: tuple[Any, dict[str, bool]], real_derived: Any, real_export: ChunkInfo
) -> None:
    """**`_pooled_yields` is `_drop_rates`' second component, in one scan**, and
    the two must not drift apart.

    It exists because the herb pool asked every (provider, herb) pair
    separately and re-read every drop source per herb. Two routes to one answer
    is the shape that drifts silently here: a pool that quietly loses a
    provider reads as a slower Herblore, never as an error. So this asserts
    them equal over the real export, for every provider, rather than sampling.
    """
    from chunksim.costing import herbs
    from chunksim.costing.estimate import _drop_rates, _pooled_yields, material_walk
    from chunksim.derive.search import build_world_index

    state, _ = real_state
    heuristics, _scraped = load_heuristics(state.chunk_info)
    walk = material_walk(
        state, real_derived, build_world_index(real_export), heuristics
    )
    grimy = herbs.herb_items(real_derived.source_index.items)
    assert grimy, "the real map reaches no herbs; this asserts nothing"
    wanted = frozenset(grimy)

    checked = 0
    for provider in walk.available:
        pooled = _pooled_yields(walk, provider, wanted)
        for herb in grimy:
            one = (_drop_rates(walk, provider, herb) or (0.0, 0.0))[1]
            assert pooled.get(herb, 0.0) == one, (provider, herb)
            checked += 1
    assert checked, "no provider was walked"
