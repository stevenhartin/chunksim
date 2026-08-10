"""Tests for the non-skill task categories: Quest, Diary and Extra."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from fray_claude.cache import read_chunkinfo
from fray_claude.chunkinfo import ChunkInfo
from fray_claude.other_tasks import (
    classify_other_tasks,
    display_name,
    group_of,
    task_text,
)


def _chunk_info(**data: Any) -> ChunkInfo:
    return ChunkInfo(data)


def _classify(
    valid: dict[str, Any],
    info: ChunkInfo,
    *,
    completed: dict[str, Any] | None = None,
    checked: dict[str, Any] | None = None,
    backlog: dict[str, Any] | None = None,
) -> Any:
    return classify_other_tasks(
        valid,
        info,
        completed_challenges=completed or {},
        checked_challenges=checked or {},
        backlog=backlog or {},
    )


def test_display_name_renames_extra_to_other() -> None:
    assert display_name("Extra") == "Other"
    assert display_name("Diary") == "Diary"
    assert display_name("Quest") == "Quest"


def test_a_diary_group_is_its_diary_and_tier() -> None:
    assert group_of("Diary", "~|Morytania Diary#Elite|~ Task 5", {}) == "Morytania Diary - Elite"


def test_a_diary_group_falls_back_to_base_quest_without_a_tier() -> None:
    assert group_of("Diary", "Some odd name", {"BaseQuest": "Varrock Diary"}) == "Varrock Diary"


def test_a_quest_group_is_its_base_quest() -> None:
    assert group_of("Quest", "~|Below Ice Mountain|~ 1", {"BaseQuest": "Below Ice Mountain"}) == (
        "Below Ice Mountain"
    )


def test_an_extra_group_is_its_label() -> None:
    challenge = {"Label": "Collection Log", "Category": ["Collection Log"]}
    assert group_of("Extra", "(Abyssal Sire) Obtain an ~|abyssal whip|~", challenge) == (
        "Collection Log"
    )


def test_task_text_prefers_the_description() -> None:
    assert task_text("~|X|~ 1", {"Description": "Talk to Willow"}) == "Talk to Willow"


def test_task_text_falls_back_to_the_stripped_name() -> None:
    assert task_text("(Abyssal Sire) Obtain an ~|abyssal whip|~", {}) == (
        "(Abyssal Sire) Obtain an abyssal whip"
    )


def test_every_valid_uncompleted_task_is_active() -> None:
    """Unlike a skill category there is no single winner: the panel shows all
    of them (index.js:6744)."""
    info = _chunk_info(
        challenges={
            "Diary": {
                "~|Varrock Diary#Easy|~ Task 1": {"Description": "One"},
                "~|Varrock Diary#Easy|~ Task 2": {"Description": "Two"},
            }
        }
    )

    result = _classify({"Diary": {"~|Varrock Diary#Easy|~ Task 1": True,
                                  "~|Varrock Diary#Easy|~ Task 2": True}}, info)

    diary = result.categories["Diary"]
    assert diary.active_total == 2
    assert diary.groups[0].name == "Varrock Diary - Easy"
    assert diary.groups[0].active == (
        "~|Varrock Diary#Easy|~ Task 1",
        "~|Varrock Diary#Easy|~ Task 2",
    )


def test_a_completed_task_is_not_active() -> None:
    info = _chunk_info(challenges={"Extra": {"Obtain a thing": {"Label": "Collection Log"}}})

    result = _classify(
        {"Extra": {"Obtain a thing": True}},
        info,
        completed={"Extra": {"Obtain a thing": True}},
    )

    extra = result.categories["Extra"]
    assert extra.active_total == 0
    assert extra.completed_total == 1


def test_a_task_ticked_this_chunk_is_completed_and_marked() -> None:
    """Upstream's panel keeps a ticked task in the active list with its box
    set (index.js:6663/6745); a terminal has no box, so it moves to completed
    with a marker instead - the same treatment `bis.py` gives its own.
    """
    info = _chunk_info(
        challenges={
            "Extra": {
                "Obtain a thing": {"Label": "Collection Log"},
                "Obtain another": {"Label": "Collection Log"},
            }
        }
    )

    result = _classify(
        {"Extra": {"Obtain a thing": True, "Obtain another": True}},
        # `completed_challenges` is the merged view, so a ticked task is in
        # both branches.
        info,
        completed={"Extra": {"Obtain a thing": True}},
        checked={"Extra": {"Obtain a thing": True}},
    )

    extra = result.categories["Extra"]
    assert extra.active_total == 1
    assert extra.current_chunk == frozenset({"Obtain a thing"})
    # The panel's own count is still recoverable.
    assert extra.active_total + len(extra.current_chunk) == 2
    assert extra.completed_text("Obtain a thing", {}) == "Obtain a thing (Active)"
    assert extra.completed_text("Obtain another", {}) == "Obtain another"


def test_this_chunks_completions_sort_to_the_front() -> None:
    info = _chunk_info(
        challenges={
            "Diary": {
                "~|Wilderness Diary#Hard|~ Task 1": {"Description": "Aaa first alphabetically"},
                "~|Wilderness Diary#Hard|~ Task 9": {"Description": "Zzz last alphabetically"},
                "~|Ardougne Diary#Easy|~ Task 1": {"Description": "Another group"},
            }
        }
    )

    result = _classify(
        {"Diary": {}},
        info,
        completed={
            "Diary": {
                "~|Wilderness Diary#Hard|~ Task 1": True,
                "~|Wilderness Diary#Hard|~ Task 9": True,
                "~|Ardougne Diary#Easy|~ Task 1": True,
            }
        },
        checked={"Diary": {"~|Wilderness Diary#Hard|~ Task 9": True}},
    )

    diary = result.categories["Diary"]
    # The group holding this chunk's work comes first, ahead of Ardougne...
    assert diary.groups[0].name == "Wilderness Diary - Hard"
    # ... and within it, the ticked task leads despite sorting last by text.
    assert diary.groups[0].completed[0] == "~|Wilderness Diary#Hard|~ Task 9"


def test_a_backlogged_task_is_not_active() -> None:
    info = _chunk_info(challenges={"Quest": {"~|A Quest|~ 1": {"BaseQuest": "A Quest"}}})

    result = _classify(
        {"Quest": {"~|A Quest|~ 1": True}},
        info,
        backlog={"Quest": {"~|A Quest|~ 1": True}},
    )

    assert result.categories["Quest"].active_total == 0


def test_a_completion_is_reported_even_when_no_longer_valid() -> None:
    """Same rule as the skill categories: a requirement added by a later game
    update must not erase the fact that the task was done."""
    info = _chunk_info(challenges={"Extra": {"Obtain a thing": {"Label": "Untracked Uniques"}}})

    result = _classify({"Extra": {}}, info, completed={"Extra": {"Obtain a thing": True}})

    extra = result.categories["Extra"]
    assert extra.completed_total == 1
    assert extra.groups[0].name == "Untracked Uniques"
    assert extra.groups[0].completed == ("Obtain a thing",)


def test_a_completion_missing_from_the_export_is_grouped_as_ungrouped() -> None:
    """Real data carries ledger entries whose challenge the export no longer
    defines; they still count, with nowhere better to file them."""
    info = _chunk_info(challenges={"Extra": {}})

    result = _classify({"Extra": {}}, info, completed={"Extra": {"Some retired task": True}})

    assert result.categories["Extra"].groups[0].name == "Ungrouped"


def test_every_category_is_present_even_when_empty() -> None:
    result = _classify({}, _chunk_info())

    assert set(result.categories) == {"Diary", "Quest", "Extra"}
    assert all(tasks.active_total == 0 for tasks in result.categories.values())


def test_completing_a_quest_implies_its_whole_chain() -> None:
    """A quest is a step chain and ticking it off records only the final
    entry, so `~|Gertrude's Cat|~ Complete the quest` has to carry steps 1-7
    with it - otherwise a finished quest keeps showing every step as active.
    """
    steps: dict[str, Any] = {"~|Cat|~ 1": {"BaseQuest": "Cat", "Description": "One"}}
    for n in range(2, 5):
        steps[f"~|Cat|~ {n}"] = {
            "BaseQuest": "Cat",
            "Description": f"Step {n}",
            "Tasks": {f"~|Cat|~ {n - 1}": "Quest"},
        }
    steps["~|Cat|~ Complete the quest"] = {
        "BaseQuest": "Cat",
        "Tasks": {"~|Cat|~ 4": "Quest"},
    }
    info = _chunk_info(challenges={"Quest": steps})

    result = _classify(
        {"Quest": dict.fromkeys(steps, True)},
        info,
        completed={"Quest": {"~|Cat|~ Complete the quest": True}},
    )

    quest = result.categories["Quest"]
    assert quest.active_total == 0
    assert quest.completed_total == 5


def test_a_partly_done_quest_keeps_its_later_steps_active() -> None:
    steps: dict[str, Any] = {
        "~|Cat|~ 1": {"BaseQuest": "Cat", "Description": "One"},
        "~|Cat|~ 2": {"BaseQuest": "Cat", "Description": "Two", "Tasks": {"~|Cat|~ 1": "Quest"}},
        "~|Cat|~ 3": {"BaseQuest": "Cat", "Description": "Three", "Tasks": {"~|Cat|~ 2": "Quest"}},
    }
    info = _chunk_info(challenges={"Quest": steps})

    result = _classify(
        {"Quest": dict.fromkeys(steps, True)},
        info,
        completed={"Quest": {"~|Cat|~ 2": True}},
    )

    quest = result.categories["Quest"]
    assert quest.active_total == 1
    assert quest.groups[0].active == ("~|Cat|~ 3",)
    assert quest.completed_total == 2


def test_completing_a_diary_tier_implies_all_of_its_tasks() -> None:
    """A tier completion carries a `Reward` and lists every task in its tier,
    so recording it settles them all. Real data had ten of Morytania Easy's
    eleven tasks marked individually and the tier itself marked, leaving
    `Task 8` looking outstanding.
    """
    tasks = {f"~|D#Easy|~ Task {n}": {"BaseQuest": "D", "Description": f"T{n}"} for n in (1, 2)}
    info = _chunk_info(
        challenges={
            "Diary": {
                **tasks,
                "~|D#Easy|~ Complete the Easy Diary": {
                    "BaseQuest": "D",
                    "Reward": ["A cloak"],
                    "Tasks": {name: "Diary" for name in tasks},
                },
            }
        }
    )

    result = _classify(
        {"Diary": dict.fromkeys(tasks, True)},
        info,
        completed={"Diary": {"~|D#Easy|~ Complete the Easy Diary": True}},
    )

    assert result.categories["Diary"].active_total == 0


def test_an_ordinary_diary_task_implies_nothing() -> None:
    """Only tier completions imply: one diary task's `Tasks` are ordinary
    requirements (a quest, or the tier below), not steps walked through."""
    info = _chunk_info(
        challenges={
            "Diary": {
                "~|D#Easy|~ Task 1": {"BaseQuest": "D", "Description": "One"},
                "~|D#Easy|~ Task 2": {
                    "BaseQuest": "D",
                    "Description": "Two",
                    "Tasks": {"~|D#Easy|~ Task 1": "Diary"},
                },
            }
        }
    )

    result = _classify(
        {"Diary": {"~|D#Easy|~ Task 1": True, "~|D#Easy|~ Task 2": True}},
        info,
        completed={"Diary": {"~|D#Easy|~ Task 2": True}},
    )

    assert result.categories["Diary"].active_total == 1


def test_the_chain_rule_does_not_apply_to_other_categories() -> None:
    """`Extra` has no chain at all, so a `Tasks` edge there implies nothing."""
    info = _chunk_info(
        challenges={
            "Extra": {
                "Obtain a thing": {"Label": "Collection Log"},
                "Obtain another": {
                    "Label": "Collection Log",
                    "Tasks": {"Obtain a thing": "Extra"},
                },
            }
        }
    )

    result = _classify(
        {"Extra": {"Obtain a thing": True, "Obtain another": True}},
        info,
        completed={"Extra": {"Obtain another": True}},
    )

    assert result.categories["Extra"].active_total == 1


def test_a_quest_step_does_not_imply_a_dependency_in_another_category() -> None:
    info = _chunk_info(
        challenges={
            "Quest": {
                "~|Cat|~ 1": {"BaseQuest": "Cat", "Tasks": {"Some diary task": "Diary"}},
            },
            "Diary": {"Some diary task": {"Description": "A diary task"}},
        }
    )

    result = _classify(
        {"Quest": {"~|Cat|~ 1": True}, "Diary": {"Some diary task": True}},
        info,
        completed={"Quest": {"~|Cat|~ 1": True}},
    )

    assert result.categories["Diary"].active_total == 1


def test_a_cyclic_chain_terminates() -> None:
    info = _chunk_info(
        challenges={
            "Quest": {
                "~|Cat|~ 1": {"BaseQuest": "Cat", "Tasks": {"~|Cat|~ 2": "Quest"}},
                "~|Cat|~ 2": {"BaseQuest": "Cat", "Tasks": {"~|Cat|~ 1": "Quest"}},
            }
        }
    )

    result = _classify(
        {"Quest": {"~|Cat|~ 1": True, "~|Cat|~ 2": True}},
        info,
        completed={"Quest": {"~|Cat|~ 1": True}},
    )

    assert result.categories["Quest"].active_total == 0


_REAL_CHUNKINFO = os.environ.get("FRAY_CHUNKINFO")
_REAL_MAP = os.environ.get("FRAY_MAP_CACHE")


#: Both categories now reproduce the map's own `activeTasks` exactly, so this
#: is empty. It stays as a named, asserted-against constant rather than being
#: deleted: an earlier version of this test compared *totals* and passed on
#: `Extra` at 37 == 37 while seven entries were wrong in each direction, and
#: pinning the set is what stops that recurring.
_KNOWN_ORACLE_DELTA: dict[str, frozenset[str]] = {
    "Diary": frozenset(),
    "Extra": frozenset(),
}


@pytest.mark.skipif(
    not (_REAL_CHUNKINFO and _REAL_MAP),
    reason=(
        "set FRAY_CHUNKINFO to a raw export and FRAY_MAP_CACHE to anything; the map "
        "itself is read from the repo's own cache/, so FRAY_MAP_CACHE's value is unused"
    ),
)
@pytest.mark.parametrize("category", ["Diary", "Extra"])
def test_active_tasks_match_the_live_oracle(category: str) -> None:
    """Opt-in oracle: `chunkinfo.activeTasks` records what the panel last
    showed for `Diary` and `Extra`.

    Compared as a *set*, against `active` plus `current_chunk` - the latter is
    what upstream still lists as active and this module reports as
    completed-with-a-marker, so the panel's own view is the union.

    The residual disagreement is pinned in `_KNOWN_ORACLE_DELTA` rather than
    waved through with a count: an earlier version compared totals and passed
    on `Extra` at 37 == 37 while seven entries were wrong in each direction.
    """
    assert _REAL_CHUNKINFO is not None
    from fray_claude.cache import project_root, read_blob, read_cache
    from fray_claude.firebase import decode_challenge_keyed, reverse_tasks_map
    from fray_claude.pipeline import derive, load_map_state

    data = read_chunkinfo(override=Path(_REAL_CHUNKINFO))
    info = ChunkInfo(data)
    root = project_root()
    envelope = read_cache("fray", root)
    tasks_map = reverse_tasks_map(read_blob("tasks_map", root)["data"])
    state, unlocked = load_map_state(envelope["data"], info, tasks_map)
    derived = derive(state, unlocked)

    oracle = set(
        decode_challenge_keyed(
            envelope["data"]["chunkinfo"].get("activeTasks"), tasks_map
        ).get(category, {})
    )
    assert oracle, f"the map no longer records active {category} tasks"

    tasks = derived.other_tasks.categories[category]
    ours = {name for group in tasks.groups for name in group.active} | tasks.current_chunk

    assert ours ^ oracle == _KNOWN_ORACLE_DELTA[category]
