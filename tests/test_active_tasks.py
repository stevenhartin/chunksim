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
    # And it *is* reported as completed, even though the skill no longer
    # carries it as a valid challenge - a recorded completion is proof the
    # requirements were met at the time.
    assert result.skills["Mining"].completed == frozenset({"Buy the Mining cape"})


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

    The stored value is `"92{5}"` - Level 92 less a 5-point `Wild pie` boost -
    and both halves are asserted: the name, and the boost `boosts.py` computes
    for it. The boost is independent confirmation, since nothing about
    reproducing the *name* depends on getting the boost table, the
    availability lookup or the arithmetic right.
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

    from fray_claude import boosts

    challenge = data["challenges"]["Slayer"][recorded]
    best, saw = boosts.best_boost(
        "Slayer",
        recorded,
        challenge,
        float(challenge["Level"]),
        rules=state.rules,
        chunk_info=info,
        items=derived.challenges.available_items,
        source_index=derived.source_index,
    )
    # `"92{5}"` -> the trailing `{N}` is the boost upstream applied.
    expected_boost = int(oracle[recorded].split("{")[1].rstrip("}"))
    assert best + saw == expected_boost


#: A Level 1 `Primary` route so `checkPrimaryMethod` reports the skill
#: trainable; without one nothing above the passive floor is eligible and
#: every tie-break below would collapse to "no active task".
_STARTER = {"Level": 1, "Primary": True}


def _tie_info(a: dict[str, Any], b: dict[str, Any]) -> ChunkInfo:
    return _chunk_info(
        challenges={"Mining": {"Mine a pebble": _STARTER, "Route A": a, "Route B": b}}
    )


def _tie_winner(a: dict[str, Any], b: dict[str, Any]) -> str | None:
    valid = {
        "Mining": {
            "Mine a pebble": 1,
            "Route A": a.get("Level", 1),
            "Route B": b.get("Level", 1),
        }
    }
    result = classify_tasks(
        valid,
        _tie_info(a, b),
        completed_challenges={},
        manual_tasks={},
        backlog={},
        passive_skill={},
    )
    return result.skills["Mining"].active


def test_at_equal_level_the_lower_priority_wins() -> None:
    winner = _tie_winner(
        {"Level": 50, "Primary": True, "Priority": 5},
        {"Level": 50, "Primary": True, "Priority": 2},
    )

    assert winner == "Route B"


def test_at_equal_level_a_challenger_beats_an_incumbent_with_no_priority() -> None:
    """Branch A: `!incumbent['Priority']` alone hands it over, whatever the
    challenger's own priority is."""
    winner = _tie_winner(
        {"Level": 50, "Primary": True},
        {"Level": 50, "Primary": True, "Priority": 9},
    )

    assert winner == "Route B"


def test_a_primary_challenger_with_no_priority_beats_one_that_has_it() -> None:
    """Branch B, which branch A alone would never allow: the challenger has
    no `Priority` key and the incumbent has a real one, so A's tests both
    fail - only `Primary` gets it through.
    """
    winner = _tie_winner(
        {"Level": 50, "Primary": True, "Priority": 3},
        {"Level": 50, "Primary": True},
    )

    assert winner == "Route B"


def test_a_non_primary_challenger_with_no_priority_does_not_displace() -> None:
    """The same shape as above without the `Primary` flag stays put - which
    is what makes that flag a tie-breaker in its own right."""
    winner = _tie_winner(
        {"Level": 50, "Primary": True, "Priority": 3},
        {"Level": 50},
    )

    assert winner == "Route A"


def test_a_completed_task_recorded_with_a_slash_variant_still_counts() -> None:
    """Upstream pairs every `completedChallenges`/`backlog` lookup with one
    on the `#` -> `/` spelling; a single-spelling check reports an
    already-completed task as still outstanding.
    """
    info = _chunk_info(
        challenges={
            "Woodcutting": {
                "Chop a sapling": {"Level": 1, "Primary": True},
                "~|Morytania Diary#Easy|~ Task 3": {"Level": 40, "Primary": True},
            }
        }
    )
    valid = {"Woodcutting": {"Chop a sapling": 1, "~|Morytania Diary#Easy|~ Task 3": 40}}

    result = classify_tasks(
        valid,
        info,
        completed_challenges={"Woodcutting": {"~|Morytania Diary/Easy|~ Task 3": True}},
        manual_tasks={},
        backlog={},
        passive_skill={},
    )

    classification = result.skills["Woodcutting"]
    # The canonical `#` spelling, once - not both forms.
    assert classification.completed == frozenset({"~|Morytania Diary#Easy|~ Task 3"})
    # The Level 1 `Primary` route still wins: upstream's *ceiling* loop does a
    # plain lookup with no `/` variant (worker.js:8393), so a slash-spelled
    # record contributes nothing there even though it counts as completed.
    assert classification.active == "Chop a sapling"


def test_combat_is_not_classified_as_a_display_skill() -> None:
    """`Combat` is in upstream's `skillNames`, but its per-skill view filters
    it out (index.js:9570) - it is a pseudo-skill whose challenges are
    slayer-master assignments existing to satisfy *other* categories. Left in,
    it produced a phantom `Receive a Slayer assignment from Vannaka` pick
    whose only requirement, `Skills: {Slayer: 1}`, Slayer's own Level 92 pick
    had long since exceeded.
    """
    info = _chunk_info(
        challenges={
            "Combat": {"Receive a Slayer assignment from Vannaka": {"Level": 40, "Primary": True}},
            "Slayer": {"Slay something": {"Level": 1, "Primary": True}},
        }
    )
    valid = {
        "Combat": {"Receive a Slayer assignment from Vannaka": 40},
        "Slayer": {"Slay something": 1},
    }

    result = classify_tasks(
        valid, info, completed_challenges={}, manual_tasks={}, backlog={}, passive_skill={}
    )

    assert "Combat" not in result.skills
    assert "Slayer" in result.skills


def test_a_completion_defined_in_another_category_proves_its_skill_level() -> None:
    """The reported `Thieving` case. `~|Wilderness Diary#Elite|~ Task 5` is
    recorded under `Thieving` but *defined* in `challenges.Diary`, as "Steal
    from the Chest (Rogues' Castle)" with `Skills: {Thieving: 84}`. Upstream's
    ceiling loop only looks in `challenges[skill]` and only reads `Level`, so
    it misses this; here a recorded completion counts as proof of the level it
    required, which settles the equal-level Rogues' Castle task.
    """
    info = _chunk_info(
        challenges={
            "Thieving": {
                "Pickpocket a man": {"Level": 1, "Primary": True},
                "Loot a chest (Rogues' Castle) without the diary": {"Level": 84, "Primary": True},
            },
            "Diary": {
                "Wilderness Diary Elite Task 5": {"Skills": {"Thieving": 84}},
            },
        }
    )
    valid = {
        "Thieving": {
            "Pickpocket a man": 1,
            "Loot a chest (Rogues' Castle) without the diary": 84,
        }
    }

    result = classify_tasks(
        valid,
        info,
        completed_challenges={"Thieving": {"Wilderness Diary Elite Task 5": True}},
        manual_tasks={},
        backlog={},
        passive_skill={},
    )

    classification = result.skills["Thieving"]
    assert classification.active is None
    assert "Wilderness Diary Elite Task 5" in classification.completed
    assert "Loot a chest (Rogues' Castle) without the diary" in classification.obsolete


def test_a_completion_with_no_level_anywhere_proves_nothing() -> None:
    info = _chunk_info(
        challenges={
            "Thieving": {
                "Pickpocket a man": {"Level": 1, "Primary": True},
                "Pickpocket a guard": {"Level": 40, "Primary": True},
            },
            "Diary": {"Some diary task": {"Objects": ["Chest"]}},
        }
    )
    valid = {"Thieving": {"Pickpocket a man": 1, "Pickpocket a guard": 40}}

    result = classify_tasks(
        valid,
        info,
        completed_challenges={"Thieving": {"Some diary task": True}},
        manual_tasks={},
        backlog={},
        passive_skill={},
    )

    assert result.skills["Thieving"].active == "Pickpocket a guard"
