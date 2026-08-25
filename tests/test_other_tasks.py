"""Tests for the non-skill task categories: Quest, Diary and Extra."""

from __future__ import annotations

from typing import Any

import pytest

from chunksim.derive.pipeline import Derived
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.derive.other_tasks import (
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




#: The residual disagreement with each cached map's own `activeTasks`, per
#: `(map id, category)`. Pinned as a *set of names*, never a count: an earlier
#: version of this test compared totals and passed on `Extra` at 37 == 37
#: while seven entries were wrong in each direction.
#:
#: **The oracle map is empty and must stay that way**; it is the one whose
#: every rule this project has been tuned against. The second map is not, and
#: that is the point of running it - 41 of the oracle map's 104 rules are off,
#: so it can only ever check the two thirds that are on. Its 24 `Extra`
#: entries are one cluster (Slayer and boss collection-log drops, plus the
#: Combat Achievement contracts) and its 2 `Diary` entries another; both are
#: known-unexplained rather than accepted, and this number is expected to go
#: down and never up.
_KNOWN_ORACLE_DELTA: dict[tuple[str, str], frozenset[str]] = {
    ("fray", "Diary"): frozenset(),
    ("fray", "Extra"): frozenset(),
    # `Brutal, Big, Black and Firey` needs `Slay a ~|brutal black dragon|~`
    # (Level 77 against a passive floor of 48); it went when the level gate
    # moved into the walk - see `challenges._level_attainable`. The Punching
    # Bag needs `SlayBloodveld[+]`, satisfied by `Slay a ~|Mutated
    # Bloodveld|~` - Level 50, which clears the floor on the +5 this map's
    # `Wild pie` gives, by upstream's own boost term. Why upstream drops it
    # anyway is not known.
    # **Three more, and they are a real reachability improvement, not a
    # regression.** `sections.connected_sections` (port of worker.js:2110-
    # 2124's `ConnectsSections` handling, previously entirely unported)
    # opened `11317-1`/`11317-2` via two chained Agility shortcuts -
    # "escape the Water Obelisk Island" (`11317-6`, already reachable
    # through the `"???"` workaround, to `11317-1`) then "scale Catherby
    # cliffside" (`11317-1` to `11317-2`), both of which this map's own
    # Agility genuinely clears. `~|Kandarin Diary#Easy|~ Task 1`/`Task 8`
    # and `#Medium|~ Task 5` all need `11317-1`'s fishing spot. Traced by
    # hand: `_tasks_requirement_met`/`_level_gates_met` (unchanged by this
    # fix) already say both shortcuts are valid; `connected_sections` only
    # propagates that into section reachability, which nothing did before.
    # Upstream's own live snapshot not showing these as active is the
    # residual - possibly staleness (the oracle is a snapshot; the export
    # is live), possibly a real account never having walked the route
    # despite meeting the requirements. Either way, refusing to open a
    # section a real Agility level and a real shortcut both hand to a
    # player is the wrong side of this project's own "computed beats
    # scraped" rule to be wrong on.
    ("verf", "Diary"): frozenset({
        "~|Combat Achievements#Easy|~ The Demonic Punching Bag",
        "~|Kandarin Diary#Easy|~ Task 1",
        "~|Kandarin Diary#Easy|~ Task 8",
        "~|Kandarin Diary#Medium|~ Task 5",
    }),
    # **Eight, down from twenty-three.** The fifteen that went were the
    # `skillItems.Slayer` leak: a map that cannot train Slayer past its
    # passive floor was still offered abyssal whips. See
    # `challenges._level_attainable` and `sources._SlayerGate`.
    #
    # **The eight left are two different things, and only two of them are a
    # disagreement.** This oracle records what the panel last rendered, and
    # across both cached maps its `Extra` branch carries `Collection Log` and
    # nothing else bar a single `Fill Stashes` - no `Untracked Uniques`, no
    # `BIS Skilling`, no `Stuffables`, ever. So an entry this project makes
    # active in one of *those* groups is outside what the oracle can speak to:
    #
    # - the five `Untracked Uniques` contracts (**confirmed correct** - they
    #   drop from lesser/greater/black demons, not from Yama, and this map
    #   satisfies the `taskUnlocks` gate through `Chasm of fire demons`, the
    #   published alternative to completing `~|A Kingdom Divided|~`), and
    # - `Obtain a ~|herb sack|~`, the `BIS Skilling` half of an item this map
    #   buys from the Tithe Farm shop.
    #
    # The remaining two *are* `Collection Log`, the group the oracle does
    # record, so they are the real residue and the place to start next:
    # `(Tithe Farm) Obtain a ~|herb sack|~` and `Obtain a ~|Golden Gnome|~`.
    ("verf", "Extra"): frozenset(
        {
            "(Tithe Farm) Obtain a ~|herb sack|~",
            "Obtain a ~|Golden Gnome|~",
            "Obtain a ~|contract of bloodied blows|~",
            "Obtain a ~|contract of divine severance|~",
            "Obtain a ~|contract of forfeit breath|~",
            "Obtain a ~|contract of glyphic attenuation|~",
            "Obtain a ~|contract of sensory clouding|~",
            "Obtain a ~|herb sack|~",
        }
    ),
}


@pytest.mark.real_cache
@pytest.mark.parametrize("category", ["Diary", "Extra"])
def test_active_tasks_match_the_live_oracle(
    category: str,
    real_export: ChunkInfo,
    real_tasks_map: dict[str, str],
) -> None:
    """Opt-in oracle: `chunkinfo.activeTasks` records what the panel last
    showed for `Diary` and `Extra`.

    **Every fetched map in the cache, not just the one `conftest.ORACLE_MAP`
    names**, following `test_bis`'s lead for the same reason it gives: a map
    is a set of rules a player chose, so a second one is a second set of
    inputs rather than more of the same. The oracle map has 41 of its 104
    rules off, and every one of those is a stretch of upstream this suite
    could not see - `BIS Skilling` being off there is exactly how a whole
    unported `Set` sweep survived a category whose active set is asserted
    exactly. Fetch another map and it is covered here for free.

    Compared as a *set*, against `active` plus `current_chunk` - the latter is
    what upstream still lists as active and this module reports as
    completed-with-a-marker, so the panel's own view is the union.

    The residual disagreement is pinned per map in `_KNOWN_ORACLE_DELTA`
    rather than waved through with a count.
    """
    from chunksim.derive.pipeline import derive, load_map_state
    from chunksim.model.firebase import decode_challenge_keyed
    from chunksim.store.cache import data_root, list_maps, read_cache

    root = data_root()
    fetched = [entry.map_id for entry in list_maps(root) if entry.kind == "fetched"]
    assert fetched, "no fetched maps cached to compare against"

    checked = 0
    for map_id in fetched:
        payload = read_cache(map_id, root)["data"]
        oracle = set(
            decode_challenge_keyed(
                payload["chunkinfo"].get("activeTasks"), real_tasks_map
            ).get(category, {})
        )
        if not oracle:
            continue
        state, unlocked = load_map_state(payload, real_export, real_tasks_map)
        tasks = derive(state, unlocked).other_tasks.categories[category]
        ours = {name for group in tasks.groups for name in group.active} | tasks.current_chunk

        expected = _KNOWN_ORACLE_DELTA.get((map_id, category))
        assert expected is not None, (
            f"{map_id}/{category} has no pinned delta - add one (empty if it matches) "
            "rather than letting a new map quietly widen what this asserts"
        )
        assert ours ^ oracle == expected, map_id
        checked += 1
    assert checked, f"every cached map had an empty {category} oracle"
