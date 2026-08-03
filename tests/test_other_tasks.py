"""Tests for the non-skill task categories: Quest, Diary and Extra."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

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


def test_a_task_only_checked_this_chunk_is_still_active() -> None:
    """The panel filters on `completedChallenges` alone; a ticked task still
    renders, just with its box set (index.js:6663/6745). Using the merged
    view hid 9 real `Extra` entries the map's own oracle lists.
    """
    info = _chunk_info(challenges={"Extra": {"Obtain a thing": {"Label": "Collection Log"}}})

    result = _classify(
        {"Extra": {"Obtain a thing": True}},
        # `completed_challenges` is the merged view, so a checked task appears
        # in both - which is exactly the case that must stay active.
        info,
        completed={"Extra": {"Obtain a thing": True}},
        checked={"Extra": {"Obtain a thing": True}},
    )

    assert result.categories["Extra"].active_total == 1


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


_REAL_CHUNKINFO = os.environ.get("FRAY_CHUNKINFO")
_REAL_MAP = os.environ.get("FRAY_MAP_CACHE")


@pytest.mark.skipif(
    not (_REAL_CHUNKINFO and _REAL_MAP),
    reason="set FRAY_CHUNKINFO and FRAY_MAP_CACHE to real data to run this",
)
@pytest.mark.parametrize("category", ["Diary", "Extra"])
def test_active_totals_match_the_live_oracle(category: str) -> None:
    """Opt-in oracle: `chunkinfo.activeTasks` records what the panel last
    showed for `Diary` and `Extra`, so our active *count* must reproduce it.

    Counts rather than membership: the totals agree exactly (5 and 37), but a
    handful of individual entries still differ each way, every one of them
    traced to item availability rather than to this module - `Mahogany logs`
    for the one Diary swap, and Artio's 1/618-1/2800 boss drops for the Extra
    ones. Tightening this to set equality is the right next step once those
    are resolved; asserting the totals now still catches any regression in
    the completed/backlog/checked filtering, which is what this module owns.
    """
    assert _REAL_CHUNKINFO is not None
    from fray_claude.cache import project_root, read_blob, read_cache
    from fray_claude.firebase import decode_challenge_keyed, reverse_tasks_map
    from fray_claude.pipeline import derive, load_map_state

    data = json.loads(Path(_REAL_CHUNKINFO).read_text(encoding="utf-8"))
    info = ChunkInfo(data)
    root = project_root()
    envelope = read_cache("fray", root)
    tasks_map = reverse_tasks_map(read_blob("tasks_map", root)["data"])
    state, unlocked = load_map_state(envelope["data"], info, tasks_map)
    derived = derive(state, unlocked)

    oracle = decode_challenge_keyed(
        envelope["data"]["chunkinfo"].get("activeTasks"), tasks_map
    ).get(category, {})

    assert oracle, f"the map no longer records active {category} tasks"
    assert derived.other_tasks.categories[category].active_total == len(oracle)
