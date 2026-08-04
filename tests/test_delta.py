"""Tests for the symmetric two-map delta.

The last two tests are the load-bearing ones: `unlock.py` projects the same
primitives down to its one-directional view, so if these two ever disagree
the project has two answers to "what changed" and no way to tell which.
"""

from __future__ import annotations

from typing import Any

import pytest

from fray_claude.active_tasks import SkillClassification, TaskClassification
from fray_claude.bis import BisResult
from fray_claude.challenges import ChallengeResult
from fray_claude.chunkinfo import ChunkInfo
from fray_claude.delta import (
    BRANCHES,
    BranchDelta,
    MapSide,
    compare,
    compare_maps,
    diff_names,
    diff_nested,
    diff_picks,
)
from fray_claude.other_tasks import CategoryTasks, OtherTasks, TaskGroup
from fray_claude.pipeline import Derived, MapState, derive
from fray_claude.sources import SourceIndex
from fray_claude.unlock import delta_from


def _chunk_info(**data: Any) -> ChunkInfo:
    return ChunkInfo(data)


def _state(**overrides: Any) -> MapState:
    defaults: dict[str, Any] = {
        "chunk_info": _chunk_info(),
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


def _sources(**overrides: Any) -> SourceIndex:
    defaults: dict[str, Any] = {
        "items": {},
        "objects": {},
        "monsters": {},
        "npcs": {},
        "shops": {},
        "drop_rates": {},
    }
    defaults.update(overrides)
    return SourceIndex(**defaults)


def _derived(**overrides: Any) -> Derived:
    defaults: dict[str, Any] = {
        "reachable_sections": {},
        "expanded_chunks": {},
        "source_index": _sources(),
        "challenges": ChallengeResult(valid={}, unsupported=frozenset()),
        "bis": BisResult(picks={}),
        "task_classification": TaskClassification(),
        "other_tasks": OtherTasks(),
    }
    defaults.update(overrides)
    return Derived(**defaults)


# --- the primitives -------------------------------------------------------


def test_diff_names_reports_both_directions() -> None:
    branch = diff_names({"a": True, "b": True}, {"b": True, "c": True})

    assert branch.added == {"c": True}
    assert branch.removed == frozenset({"a"})


def test_diff_names_accepts_a_bare_name_set() -> None:
    branch = diff_names(frozenset({"a"}), frozenset({"b"}))

    assert branch.added == {"b": True}
    assert branch.removed == frozenset({"a"})


def test_diff_names_treats_a_falsy_value_as_absent_under_truthy_only() -> None:
    # `reachable_sections` records unreachable sections as `False`, so a
    # section flipping True -> False is a loss, not an unchanged key.
    branch = diff_names({"1": True}, {"1": False}, truthy_only=True)

    assert branch.added == {}
    assert branch.removed == frozenset({"1"})


def test_diff_names_keeps_the_after_value_only_when_asked() -> None:
    assert diff_names({}, {"Chop a tree": 30}).added == {"Chop a tree": True}
    assert diff_names({}, {"Chop a tree": 30}, keep_values=True).added == {"Chop a tree": 30}


def test_diff_nested_walks_the_union_of_both_sides() -> None:
    before = {"Woodcutting": {"a": True}, "Mining": {"b": True}}
    after = {"Woodcutting": {"a": True}, "Fishing": {"c": True}}

    deltas = diff_nested(before, after)

    # Woodcutting agrees and is dropped; Mining is present only in `before`
    # and must still report its loss, which the one-directional helpers can't.
    assert set(deltas) == {"Mining", "Fishing"}
    assert deltas["Mining"].removed == frozenset({"b"})
    assert deltas["Fishing"].added == {"c": True}


def test_diff_picks_reports_a_slot_that_lost_its_pick() -> None:
    assert diff_picks({"Melee-weapon": "Rune scimitar"}, {}) == {
        "Melee-weapon": ("Rune scimitar", None)
    }


# --- compare --------------------------------------------------------------


def test_comparing_a_state_with_itself_is_empty() -> None:
    state = _derived(
        reachable_sections={"100": {"1": True}},
        challenges=ChallengeResult(valid={"Nonskill": {"a": True}}, unsupported=frozenset({"x"})),
        source_index=_sources(items={"Bones": {"Goblin": "primary-drop"}}),
        bis=BisResult(picks={"Melee-weapon": "Rune scimitar"}, active={"Get one": "weapon"}),
    )

    delta = compare(state, state, unlocked=({"100": True}, {"100": True}))

    assert delta.empty
    assert all(counts == (0, 0) for counts in delta.counts().values())


def test_compare_is_symmetric() -> None:
    before = _derived(
        reachable_sections={"100": {"1": True}},
        challenges=ChallengeResult(valid={"Nonskill": {"a": True}}, unsupported=frozenset()),
        source_index=_sources(monsters={"Goblin": {"100": True}}),
    )
    after = _derived(
        reachable_sections={"100": {"2": True}},
        challenges=ChallengeResult(valid={"Nonskill": {"b": True}}, unsupported=frozenset({"y"})),
        source_index=_sources(monsters={"Imp": {"200": True}}),
    )

    forward = compare(before, after, unlocked=({"100": True}, {"200": True}))
    backward = compare(after, before, unlocked=({"200": True}, {"100": True}))

    assert set(forward.chunks.added) == set(backward.chunks.removed)
    assert set(forward.chunks.removed) == set(backward.chunks.added)
    assert set(forward.tasks["Nonskill"].added) == set(backward.tasks["Nonskill"].removed)
    assert set(forward.unsupported.added) == set(backward.unsupported.removed)
    assert set(forward.sections["100"].added) == set(backward.sections["100"].removed)
    assert set(forward.sources["monsters"].added) == set(backward.sources["monsters"].removed)


def test_compare_keeps_an_added_tasks_value() -> None:
    before = _derived(challenges=ChallengeResult(valid={}, unsupported=frozenset()))
    after = _derived(
        challenges=ChallengeResult(
            valid={"Woodcutting": {"Chop a tree": 30}}, unsupported=frozenset()
        )
    )

    assert compare(before, after).tasks["Woodcutting"].added == {"Chop a tree": 30}


def test_compare_reports_a_bis_pick_lost_as_well_as_gained() -> None:
    before = _derived(bis=BisResult(picks={"Melee-weapon": "Bronze sword"}))
    after = _derived(bis=BisResult(picks={"Melee-shield": "Rune kiteshield"}))

    assert compare(before, after).bis_picks == {
        "Melee-weapon": ("Bronze sword", None),
        "Melee-shield": (None, "Rune kiteshield"),
    }


def test_compare_pairs_a_skills_changed_goal() -> None:
    before = _derived(
        task_classification=TaskClassification(
            skills={
                "Woodcutting": SkillClassification(
                    active="Chop an oak", obsolete=frozenset(), completed=frozenset({"Chop a log"})
                )
            }
        )
    )
    after = _derived(
        task_classification=TaskClassification(
            skills={
                "Woodcutting": SkillClassification(
                    active="Chop a yew",
                    obsolete=frozenset({"Chop an oak"}),
                    completed=frozenset({"Chop a log"}),
                )
            }
        )
    )

    change = compare(before, after).skills["Woodcutting"]

    assert change.active == ("Chop an oak", "Chop a yew")
    assert change.obsolete.added == {"Chop an oak": True}
    assert change.completed.empty


def test_compare_flattens_other_tasks_groups() -> None:
    before = _derived(
        other_tasks=OtherTasks(
            categories={
                "Diary": CategoryTasks(
                    category="Diary", groups=(TaskGroup(name="Varrock", active=("Easy 1",)),)
                )
            }
        )
    )
    after = _derived(
        other_tasks=OtherTasks(
            categories={
                "Diary": CategoryTasks(
                    category="Diary",
                    groups=(
                        TaskGroup(name="Varrock", active=("Easy 1", "Easy 2")),
                        TaskGroup(name="Falador", completed=("Easy 3",)),
                    ),
                )
            }
        )
    )

    branches = compare(before, after).other["Diary"]

    # Which group renders a task is display state; the delta is over names.
    assert branches["active"].added == {"Easy 2": True}
    assert branches["completed"].added == {"Easy 3": True}


def test_the_chunks_branch_is_empty_without_the_unlocked_sets() -> None:
    # `Derived` doesn't carry the unlocked set, so a caller that omits it
    # gets an empty branch rather than a wrong one.
    assert compare(_derived(), _derived()).chunks.empty


def test_branches_restricts_the_work() -> None:
    before = _derived(challenges=ChallengeResult(valid={}, unsupported=frozenset()))
    after = _derived(
        challenges=ChallengeResult(valid={"Nonskill": {"a": True}}, unsupported=frozenset()),
        source_index=_sources(items={"Bones": {"Goblin": "primary-drop"}}),
    )

    delta = compare(before, after, branches=frozenset({"tasks"}))

    assert delta.tasks["Nonskill"].added == {"a": True}
    assert delta.sources == {}


def test_an_unknown_branch_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown delta branch"):
        compare(_derived(), _derived(), branches=frozenset({"nope"}))


def test_counts_exclude_the_paired_branches() -> None:
    # A changed BiS pick or skill goal is not an addition, so folding it into
    # the per-branch totals would overstate them.
    before = _derived(bis=BisResult(picks={"Melee-weapon": "Bronze sword"}))
    after = _derived(bis=BisResult(picks={"Melee-weapon": "Rune scimitar"}))

    delta = compare(before, after)

    assert delta.counts()["bis"] == (0, 0)
    assert delta.bis_picks == {"Melee-weapon": ("Bronze sword", "Rune scimitar")}
    assert not delta.empty


# --- compare_maps ---------------------------------------------------------


def test_compare_maps_derives_each_side_against_its_own_state() -> None:
    # The case `unlock.tasks_added_by` structurally cannot express: identical
    # unlocked sets, different `MapState`s. A shared-state implementation
    # would report nothing here.
    info = _chunk_info(
        chunks={"100": {"Monster": {"Goblin": True}}},
        drops={"Goblin": {"Bones": {"1": "Always"}}},
        challenges={"Extra": {"Use bones": {"Items": ["Bones"]}}},
    )
    unlocked = {"100": True}
    plain = MapSide(_state(chunk_info=info), unlocked, "plain")
    done = MapSide(
        _state(chunk_info=info, completed_challenges={"Extra": {"Use bones": True}}),
        unlocked,
        "done",
    )

    delta = compare_maps(plain, done)

    assert delta.before_map == "plain"
    assert delta.after_map == "done"
    assert delta.chunks.empty
    assert delta.other["Extra"]["active"].removed == frozenset({"Use bones"})
    assert delta.other["Extra"]["completed"].added == {"Use bones": True}


def test_compare_maps_routes_both_sides_through_derive_with() -> None:
    calls: list[frozenset[str]] = []

    def recording(state: MapState, unlocked: Any) -> Derived:
        calls.append(frozenset(unlocked))
        return derive(state, unlocked)

    state = _state()
    compare_maps(
        MapSide(state, {"100": True}),
        MapSide(state, {"200": True}),
        derive_with=recording,
    )

    assert calls == [frozenset({"100"}), frozenset({"200"})]


# --- the anti-drift checks ------------------------------------------------


def test_the_added_half_matches_the_unlock_delta() -> None:
    info = _chunk_info(
        chunks={"100": {"Monster": {"Goblin": True}}},
        drops={"Goblin": {"Rune scimitar": {"1": "Always"}}},
        challenges={"Nonskill": {"Wield it": {"Items": ["Rune scimitar"]}}},
        sections={"200": {"1": ["100"]}},
        equipment={
            "Rune scimitar": {
                "slot": "weapon",
                "attack_speed": 4,
                "attack_slash": 45,
                "melee_strength": 44,
            }
        },
    )
    state = _state(chunk_info=info)
    before = derive(state, {"200": True})
    after = derive(state, {"200": True, "100": True})

    symmetric = compare(before, after)
    one_way = delta_from(before, after, "100")

    assert {skill: branch.added for skill, branch in symmetric.tasks.items()} == one_way.new_tasks
    assert {
        chunk: {name: True for name in branch.added}
        for chunk, branch in symmetric.sections.items()
    } == one_way.new_sections
    assert symmetric.bis_picks == dict(one_way.bis_upgrades)
    assert set(symmetric.unsupported.added) == one_way.new_unsupported


def test_the_unlock_delta_drops_what_the_symmetric_one_keeps() -> None:
    # The BackupParent case in miniature: something valid before and not
    # after. `fray unlock` is entitled to omit it; `fray diff` is not.
    before = _derived(
        challenges=ChallengeResult(
            valid={"Hunter": {"Catch it barehanded": True}}, unsupported=frozenset()
        ),
        bis=BisResult(picks={"Melee-weapon": "Bronze sword"}),
    )
    after = _derived(challenges=ChallengeResult(valid={}, unsupported=frozenset()))

    symmetric = compare(before, after)
    one_way = delta_from(before, after, "100")

    assert symmetric.tasks["Hunter"].removed == frozenset({"Catch it barehanded"})
    assert one_way.new_tasks == {}
    assert symmetric.bis_picks == {"Melee-weapon": ("Bronze sword", None)}
    assert one_way.bis_upgrades == {}


def test_every_branch_name_is_rendered_by_the_counts() -> None:
    # `BRANCHES` is what `fray diff`'s positional accepts; a name that never
    # reaches `counts()` would accept an argument and then print nothing.
    counts = compare(_derived(), _derived()).counts()

    assert set(counts) == set(BRANCHES)
    assert BranchDelta().empty
