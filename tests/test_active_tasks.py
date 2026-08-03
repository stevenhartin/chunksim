"""Tests for the active/obsolete/completed skill-task classifier."""

from __future__ import annotations

from typing import Any

from fray_claude.active_tasks import SkillClassification, TaskClassification, classify_tasks
from fray_claude.chunkinfo import ChunkInfo


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


def test_ineligible_challenge_never_wins_even_at_a_higher_level() -> None:
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
    assert classification.active == "Chop with a bronze axe"
    assert classification.obsolete == frozenset({"Some secondary route"})


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


def test_the_ceiling_only_rules_out_strictly_lower_candidates() -> None:
    """Two tasks at the same level are alternatives, not tiers of one
    another - completing one leaves the other a legitimate goal."""
    info = _chunk_info(
        challenges={
            "Firemaking": {
                "Burn magic logs": {"Level": 75},
                "Burn magic logs at a fire": {"Level": 75, "Primary": True},
                "Burn yew logs": {"Level": 60, "Primary": True},
            }
        }
    )
    valid = {"Firemaking": {"Burn magic logs at a fire": 75, "Burn yew logs": 60}}

    result = classify_tasks(
        valid,
        info,
        completed_challenges={"Firemaking": {"Burn magic logs": True}},
        manual_tasks={},
        backlog={},
        passive_skill={},
    )

    classification = result.skills["Firemaking"]
    assert classification.active == "Burn magic logs at a fire"
    assert classification.obsolete == frozenset({"Burn yew logs"})


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
                "Chop magic logs": {"Level": 75, "Primary": True},
            }
        }
    )
    valid = {"Woodcutting": {"Chop magic logs": 75}}

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
