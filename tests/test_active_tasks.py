"""Tests for the active/obsolete/completed skill-task classifier."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from fray_claude.active_tasks import SkillClassification, TaskClassification, classify_tasks
from fray_claude.chunkinfo import ChunkInfo

_REAL_CHUNKINFO = os.environ.get("FRAY_CHUNKINFO")
_REAL_MAP = os.environ.get("FRAY_MAP_CACHE")


def _chunk_info(**data: Any) -> ChunkInfo:
    return ChunkInfo(data)


def test_primary_challenge_with_highest_level_wins() -> None:
    info = _chunk_info(
        challenges={
            "Woodcutting": {
                "Chop with a bronze axe": {"Level": 1, "Primary": True},
                "Chop with a rune axe": {"Level": 41, "Primary": True},
            }
        }
    )
    valid = {"Woodcutting": {"Chop with a bronze axe": 1, "Chop with a rune axe": 41}}

    result = classify_tasks(
        valid, info, completed_challenges={}, manual_tasks={}, backlog={}, passive_skill={}
    )

    classification = result.skills["Woodcutting"]
    assert classification.active == "Chop with a rune axe"
    assert classification.obsolete == frozenset({"Chop with a bronze axe"})
    assert classification.completed == frozenset()


def test_a_trainable_skill_can_pick_a_non_primary_challenge() -> None:
    """Eligibility keys off `checkPrimaryMethod(skill)` - one boolean for the
    whole skill - not the challenge's own `Primary` field. Real `Slayer`
    challenges are almost all `Primary: false`, and upstream still picks the
    highest of them once the skill is trainable at all.
    """
    info = _chunk_info(
        challenges={
            "Woodcutting": {
                "Chop with a bronze axe": {"Level": 1, "Primary": True},
                "Some secondary route": {"Level": 99},
            }
        }
    )
    valid = {"Woodcutting": {"Chop with a bronze axe": 1, "Some secondary route": 99}}

    result = classify_tasks(
        valid, info, completed_challenges={}, manual_tasks={}, backlog={}, passive_skill={}
    )

    classification = result.skills["Woodcutting"]
    assert classification.active == "Some secondary route"
    assert classification.obsolete == frozenset({"Chop with a bronze axe"})


def test_an_untrainable_skill_offers_nothing_above_its_passive_floor() -> None:
    """With no `Level == 1` Primary route the skill isn't trainable here, so
    nothing above the passive floor competes - the real `Herblore` case,
    where a Level 90 potion was being proposed for a skill locked behind a
    quest the account hasn't done.
    """
    info = _chunk_info(challenges={"Herblore": {"Mix a super combat potion": {"Level": 90}}})
    valid = {"Herblore": {"Mix a super combat potion": 90}}

    result = classify_tasks(
        valid, info, completed_challenges={}, manual_tasks={}, backlog={}, passive_skill={}
    )

    assert result.skills["Herblore"].active is None


def test_passive_skill_floor_makes_a_challenge_eligible() -> None:
    info = _chunk_info(challenges={"Farming": {"Grow herbs": {"Level": 32}}})
    valid = {"Farming": {"Grow herbs": 32}}

    without = classify_tasks(
        valid, info, completed_challenges={}, manual_tasks={}, backlog={}, passive_skill={}
    )
    with_passive = classify_tasks(
        valid, info, completed_challenges={}, manual_tasks={}, backlog={}, passive_skill={"Farming": 40}
    )

    assert without.skills["Farming"].active is None
    assert without.skills["Farming"].obsolete == frozenset({"Grow herbs"})
    assert with_passive.skills["Farming"].active == "Grow herbs"


def test_manual_tasks_entry_makes_a_challenge_eligible() -> None:
    info = _chunk_info(challenges={"Hunter": {"Catch chinchompas": {"Level": 63}}})
    valid = {"Hunter": {"Catch chinchompas": 63}}

    without = classify_tasks(
        valid, info, completed_challenges={}, manual_tasks={}, backlog={}, passive_skill={}
    )
    with_manual = classify_tasks(
        valid,
        info,
        completed_challenges={},
        manual_tasks={"Hunter": {"Catch chinchompas": True}},
        backlog={},
        passive_skill={},
    )

    assert without.skills["Hunter"].active is None
    assert with_manual.skills["Hunter"].active == "Catch chinchompas"


def test_priority_breaks_a_level_tie() -> None:
    info = _chunk_info(
        challenges={
            "Smithing": {
                "Smith a bronze dagger": {"Level": 1, "Primary": True, "Priority": 2},
                "Smith a bronze axe": {"Level": 1, "Primary": True, "Priority": 1},
            }
        }
    )
    valid = {"Smithing": {"Smith a bronze dagger": 1, "Smith a bronze axe": 1}}

    result = classify_tasks(
        valid, info, completed_challenges={}, manual_tasks={}, backlog={}, passive_skill={}
    )

    assert result.skills["Smithing"].active == "Smith a bronze axe"


def test_completed_names_are_excluded_from_obsolete_and_active() -> None:
    info = _chunk_info(
        challenges={
            "Woodcutting": {
                "Chop with a bronze axe": {"Level": 1, "Primary": True},
                "Chop with a rune axe": {"Level": 41, "Primary": True},
            }
        }
    )
    valid = {"Woodcutting": {"Chop with a bronze axe": 1, "Chop with a rune axe": 41}}

    result = classify_tasks(
        valid,
        info,
        completed_challenges={"Woodcutting": {"Chop with a bronze axe": True}},
        manual_tasks={},
        backlog={},
        passive_skill={},
    )

    classification = result.skills["Woodcutting"]
    assert classification.completed == frozenset({"Chop with a bronze axe"})
    assert classification.active == "Chop with a rune axe"
    assert classification.obsolete == frozenset()


def test_backlogged_winner_is_not_picked_active() -> None:
    info = _chunk_info(
        challenges={"Woodcutting": {"Chop with a rune axe": {"Level": 41, "Primary": True}}}
    )
    valid = {"Woodcutting": {"Chop with a rune axe": 41}}

    result = classify_tasks(
        valid,
        info,
        completed_challenges={},
        manual_tasks={},
        backlog={"Woodcutting": {"Chop with a rune axe": ""}},
        passive_skill={},
    )

    classification = result.skills["Woodcutting"]
    assert classification.active is None
    assert classification.obsolete == frozenset({"Chop with a rune axe"})


def test_trivial_non_primary_winner_is_discarded() -> None:
    info = _chunk_info(challenges={"Fishing": {"Catch a shrimp": {"Level": 1}}})
    valid = {"Fishing": {"Catch a shrimp": 1}}

    result = classify_tasks(
        valid, info, completed_challenges={}, manual_tasks={}, backlog={}, passive_skill={}
    )

    classification = result.skills["Fishing"]
    assert classification.active is None
    assert classification.obsolete == frozenset({"Catch a shrimp"})


def test_non_skill_categories_are_excluded() -> None:
    info = _chunk_info(challenges={"Quest": {"Do a quest": {}}})
    valid = {"Quest": {"Do a quest": True}}

    result = classify_tasks(
        valid, info, completed_challenges={}, manual_tasks={}, backlog={}, passive_skill={}
    )

    assert result.skills == {}


def test_a_skill_with_no_valid_entries_is_absent_not_empty() -> None:
    info = _chunk_info()

    result = classify_tasks(
        {"Woodcutting": {}}, info, completed_challenges={}, manual_tasks={}, backlog={}, passive_skill={}
    )

    assert "Woodcutting" not in result.skills


def test_task_classification_as_dict_shape() -> None:
    classification = SkillClassification(active="A", obsolete=frozenset({"B"}), completed=frozenset({"C"}))
    result = TaskClassification(skills={"Woodcutting": classification})

    assert result.as_dict() == {"Woodcutting": {"active": "A", "obsolete": ["B"], "completed": ["C"]}}


def test_a_completed_higher_level_task_rules_out_every_lower_candidate() -> None:
    """The reported Agility bug: `Revenant Caves jump (hard)` (89) was
    completed with a temporary boost, yet the panel proposed the Level 81
    ivy shortcut as the current goal. Beating 89 settles everything easier.
    """
    info = _chunk_info(
        challenges={
            "Agility": {
                "Revenant Caves jump (hard)": {"Level": 89},
                "Slayer Tower ivy": {"Level": 81, "Primary": True},
                "Varrock Rooftop Course": {"Level": 30, "Primary": True},
            }
        }
    )
    valid = {"Agility": {"Slayer Tower ivy": 81, "Varrock Rooftop Course": 30}}

    result = classify_tasks(
        valid,
        info,
        completed_challenges={"Agility": {"Revenant Caves jump (hard)": True}},
        manual_tasks={},
        backlog={},
        passive_skill={},
    )

    classification = result.skills["Agility"]
    assert classification.active is None
    assert classification.obsolete == frozenset({"Slayer Tower ivy", "Varrock Rooftop Course"})


def test_the_ceiling_also_rules_out_an_equal_level_candidate() -> None:
    """Upstream requires `realLevel > highestChallengeLevelArr`, so a
    candidate at exactly the completed ceiling is settled too. Both real
    reports of this were equal-level: `Burn magic logs` completed while
    `Burn magic logs at a fire` (also 75) was proposed, and `rune platebody`
    completed while `rune plateskirt` (also 99) was.
    """
    info = _chunk_info(
        challenges={
            "Firemaking": {
                "Burn magic logs": {"Level": 75},
                "Burn magic logs at a fire": {"Level": 75, "Primary": True},
                "Burn yew logs": {"Level": 60, "Primary": True},
                "Light a candle": {"Level": 1, "Primary": True},
            }
        }
    )
    valid = {
        "Firemaking": {
            "Burn magic logs at a fire": 75,
            "Burn yew logs": 60,
            "Light a candle": 1,
        }
    }

    result = classify_tasks(
        valid,
        info,
        completed_challenges={"Firemaking": {"Burn magic logs": True}},
        manual_tasks={},
        backlog={},
        passive_skill={},
    )

    classification = result.skills["Firemaking"]
    assert classification.active is None
    assert classification.obsolete == frozenset(
        {"Burn magic logs at a fire", "Burn yew logs", "Light a candle"}
    )


def test_a_completed_task_still_wins_the_ceiling_when_it_is_no_longer_valid() -> None:
    """Completion is evidence of the level whether or not the present chunk
    set still makes that task reachable, so the ledger is read whole rather
    than intersected with `valid` first."""
    info = _chunk_info(
        challenges={
            "Mining": {
                "Buy the Mining cape": {"Level": 99},
                "Mine runite ore": {"Level": 85, "Primary": True},
            }
        }
    )
    valid = {"Mining": {"Mine runite ore": 85}}

    result = classify_tasks(
        valid,
        info,
        completed_challenges={"Mining": {"Buy the Mining cape": True}},
        manual_tasks={},
        backlog={},
        passive_skill={},
    )

    assert result.skills["Mining"].active is None
    # Not currently valid, so it isn't reported as completed either - the
    # ledger entry only ever fed the ceiling.
    assert result.skills["Mining"].completed == frozenset()


def test_a_completed_entry_with_no_level_sets_no_ceiling() -> None:
    """Real data files diary tasks under a skill (`Woodcutting`'s completed
    set holds a `Wilderness Diary` entry absent from `challenges`), and some
    challenges carry no `Level` at all. Neither may suppress a candidate."""
    info = _chunk_info(
        challenges={
            "Woodcutting": {
                "Do a thing": {},
                "Chop a regular tree": {"Level": 1, "Primary": True},
                "Chop magic logs": {"Level": 75, "Primary": True},
            }
        }
    )
    valid = {"Woodcutting": {"Chop a regular tree": 1, "Chop magic logs": 75}}

    result = classify_tasks(
        valid,
        info,
        completed_challenges={
            "Woodcutting": {"Do a thing": True, "Wilderness Diary Task 2": True}
        },
        manual_tasks={},
        backlog={},
        passive_skill={},
    )

    assert result.skills["Woodcutting"].active == "Chop magic logs"


@pytest.mark.skipif(
    not (_REAL_CHUNKINFO and _REAL_MAP),
    reason="set FRAY_CHUNKINFO and FRAY_MAP_CACHE to real data to run this",
)
def test_active_slayer_task_matches_the_live_oracle() -> None:
    """Opt-in oracle: `chunkinfo.activeTasks.Slayer` is upstream's *own* last
    computed active Slayer task, so it must reproduce exactly.

    An earlier stage of this project recorded this entry as "an unrelated
    slayer-master assignment" and therefore ignored it. It is nothing of the
    sort - it is the one real oracle this module has, and it was failing.
    Getting it to pass found the eligibility bug: the candidacy gate keys off
    `checkPrimaryMethod(skill)`, one boolean for the whole skill, and this
    module was reading each challenge's own `Primary` field instead. Real
    Slayer challenges are almost all `Primary: false`, so nothing above the
    Level 45 passive floor could ever be picked and `Slay an Infernal Mage`
    (45) won instead of the Level 92 araxyte.

    The stored value is `"92{5}"` - Level 92 less a 5-point `Wild pie` boost.
    Only the *name* is asserted: boosting isn't modelled (see the module
    docstring), and this challenge wins on raw level regardless.
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
    ).get("Slayer", {})
    recorded = next(iter(oracle), None)

    assert recorded is not None, "the map no longer records an active Slayer task"
    assert derived.task_classification.skills["Slayer"].active == recorded
