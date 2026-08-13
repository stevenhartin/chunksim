"""What the panel is handed, given what `derive` produced.

Fixtures are built by hand: `panels.py` reads `as_dict()` output and nothing
else, so a real export would only make the expected value harder to read.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from fray_claude.gui import panels
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.derive.pipeline import Derived


class _Stub:
    """Anything with an `as_dict`, which is all `task_panel` asks for."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def as_dict(self) -> dict[str, Any]:
        return self._payload


class _Stubbed:
    """The three branches `task_panel` reads, and nothing else.

    Cast to `Derived` at the call rather than constructed for real: building
    a genuine one needs the 10MB export, and every field this does not touch
    would be noise in the expected value.
    """

    def __init__(
        self,
        *,
        bis: dict[str, Any] | None = None,
        skills: dict[str, Any] | None = None,
        other: dict[str, Any] | None = None,
    ) -> None:
        self.bis = _Stub(bis or {})
        self.task_classification = _Stub(skills or {})
        self.other_tasks = _Stub(other or {})


def _derived(**branches: Any) -> Derived:
    return cast(Derived, _Stubbed(**branches))


def _section(panel: dict[str, Any], key: str) -> dict[str, Any]:
    return next(s for s in panel["sections"] if s["key"] == key)


def _quest_category(groups: list[dict[str, Any]]) -> dict[str, Any]:
    return {"Quest": {"category": "Quest", "groups": groups}}


def test_a_quest_keeps_only_its_furthest_completed_step() -> None:
    """Six rows saying "Cook's Assistant is done" is one row's worth of news."""
    panel = panels.task_panel(
        _derived(
            other=_quest_category(
                [
                    {
                        "name": "Cook's Assistant",
                        "active": [],
                        "completed": [
                            "~|Cook's Assistant|~ 1",
                            "~|Cook's Assistant|~ 2a",
                            "~|Cook's Assistant|~ 3",
                            "~|Cook's Assistant|~ Complete the quest",
                        ],
                    }
                ]
            )
        )
    )

    group = _section(panel, "Quest")["groups"][0]
    assert group["active"] == []
    assert [row["name"] for row in group["completed"]] == ["Cook's Assistant"]
    assert group["completed"][0]["note"] == "Complete the quest"


def test_quest_steps_order_by_number_not_by_text() -> None:
    """`2c10` comes after `2c4`, which a plain string sort gets backwards."""
    panel = panels.task_panel(
        _derived(
            other=_quest_category(
                [
                    {
                        "name": "Below Ice Mountain",
                        "active": [],
                        "completed": [
                            "~|Below Ice Mountain|~ 2c4",
                            "~|Below Ice Mountain|~ 2c10",
                            "~|Below Ice Mountain|~ 2c3",
                        ],
                    }
                ]
            )
        )
    )

    assert _section(panel, "Quest")["groups"][0]["completed"][0]["note"] == "2c10"


def test_a_quest_in_progress_is_not_also_reported_complete() -> None:
    """It is one quest and it is not finished; listing it twice says otherwise."""
    panel = panels.task_panel(
        _derived(
            other=_quest_category(
                [
                    {
                        "name": "Dragon Slayer",
                        "active": ["~|Dragon Slayer|~ 4"],
                        "completed": ["~|Dragon Slayer|~ 1", "~|Dragon Slayer|~ 2"],
                    }
                ]
            )
        )
    )

    group = _section(panel, "Quest")["groups"][0]
    assert [row["name"] for row in group["active"]] == ["Dragon Slayer"]
    assert group["active"][0]["note"] == "4"
    assert group["completed"] == []


def test_a_collection_log_row_splits_its_source_from_its_item() -> None:
    panel = panels.task_panel(
        _derived(
            other={
                "Extra": {
                    "category": "Extra",
                    "groups": [
                        {
                            "name": "Collection Log",
                            "active": ["(Barrows Chests) Obtain a ~|dharok's greataxe|~"],
                            "completed": [],
                        }
                    ],
                }
            }
        )
    )

    row = _section(panel, "Extra")["groups"][0]["active"][0]
    assert row["name"] == "Dharok's greataxe"
    assert row["note"] == "Barrows Chests"
    # The raw form is what everything else keys by, so it survives untouched.
    assert row["key"] == "(Barrows Chests) Obtain a ~|dharok's greataxe|~"


def test_an_ungrouped_extra_row_keeps_its_whole_sentence() -> None:
    """"Buy a Player-owned house" is not a source and an item."""
    panel = panels.task_panel(
        _derived(
            other={
                "Extra": {
                    "groups": [
                        {
                            "name": "Permanent Unlockables",
                            "active": ["Buy a ~|Player-owned house|~"],
                            "completed": [],
                        }
                    ]
                }
            }
        )
    )

    row = _section(panel, "Extra")["groups"][0]["active"][0]
    assert row["name"] == "Buy a Player-owned house"
    assert row["note"] is None


def test_bis_groups_by_combat_style_and_leads_with_the_item() -> None:
    panel = panels.task_panel(
        _derived(
            bis={
                "active": {"Obtain an ~|abyssal whip|~": "Melee BiS weapon"},
                "completed": {"Obtain ~|aranea boots|~": "Ranged BiS feet"},
                "slots": {
                    "Obtain an ~|abyssal whip|~": "weapon",
                    "Obtain ~|aranea boots|~": "feet",
                },
            }
        )
    )

    groups = {g["name"]: g for g in _section(panel, "bis")["groups"]}
    assert sorted(groups) == ["Melee", "Ranged"]
    assert groups["Melee"]["active"][0]["name"] == "Abyssal whip"
    assert groups["Melee"]["active"][0]["note"] == "weapon"
    assert groups["Ranged"]["completed"][0]["name"] == "Aranea boots"


def test_an_item_several_styles_wear_lands_in_one_shared_group() -> None:
    """Four labels holding one item each say the same thing four ways.

    The zero-width space is upstream's own, put between styles so the label
    wraps; it is invisible and must not reach a group name either.
    """
    panel = panels.task_panel(
        _derived(
            bis={
                "active": {
                    "Obtain a ~|ring|~": "Ranged/\u200bMagic BiS ring",
                    "Obtain a ~|cape|~": "Melee/\u200bRanged/\u200bMagic/\u200bPrayer BiS cape",
                }
            }
        )
    )

    groups = _section(panel, "bis")["groups"]
    assert [g["name"] for g in groups] == ["Shared"]
    assert len(groups[0]["active"]) == 2


def test_every_skill_lands_in_one_list_carrying_its_icon() -> None:
    """21 headings of one row each is not a list of what to do next."""
    panel = panels.task_panel(
        _derived(
            skills={
                "Attack": {"active": None, "completed": ["Reach ~|60 Attack|~"]},
                "Slayer": {"active": "Slay an ~|araxyte|~", "completed": []},
            }
        )
    )

    section = _section(panel, "skills")
    assert len(section["groups"]) == 1
    assert section["active_total"] == 1
    row = section["groups"][0]["active"][0]
    assert (row["name"], row["note"], row["icon"]) == ("Araxyte", "Slayer", "Slayer")
    assert section["groups"][0]["completed"][0]["icon"] == "Attack"


def test_an_empty_group_is_dropped_but_still_counted_nowhere() -> None:
    """A heading with nothing under it is noise, not information."""
    panel = panels.task_panel(
        _derived(other={"Diary": {"groups": [{"name": "Varrock", "active": [], "completed": []}]}})
    )

    section = _section(panel, "Diary")
    assert section["groups"] == []
    assert section["active_total"] == 0


def test_every_row_says_which_branch_a_tick_would_land_in() -> None:
    """**The section a row is drawn under is not the category it is stored
    under.** All 21 skills share one section, because a skill contributes at
    most one active task and 21 headings would be 21 lists of one - where the
    payload keys ticks by challenge category, one per skill. Edit mode writes
    a tick, so it needs the payload's answer.
    """
    panel = panels.task_panel(
        _derived(
            skills={"Mining": {"active": "Mine ~|iron ore|~", "completed": []}},
            bis={"active": {"~|abyssal whip|~": "Melee weapon"}, "slots": {}, "completed": {}},
            other={
                "Diary": {
                    "category": "Diary",
                    "groups": [
                        {"name": "Varrock Diary", "active": ["Varrock Diary#Easy 1"], "completed": []}
                    ],
                }
            },
        )
    )
    found = {
        row["category"]
        for section in panel["sections"]
        for group in section["groups"]
        for row in group["active"]
    }
    assert found == {"Mining", "BiS", "Diary"}
    # Every category named here is one the payload actually keys by.
    assert "skills" not in found and "bis" not in found


def test_a_diary_row_does_not_repeat_its_own_heading() -> None:
    """`Combat Achievements#Grandmaster Wasn't Event Close` under a heading
    that already says Combat Achievements - Grandmaster is the heading printed
    twice, once in every row under it."""
    panel = panels.task_panel(_derived(
        other={
            "Diary": {
                "groups": [
                    {
                        "name": "Combat Achievements - Grandmaster",
                        "active": ["~|Combat Achievements#Grandmaster|~ Wasn't Event Close"],
                        "completed": [],
                    }
                ]
            }
        }
    ))
    (group,) = _section(panel, "Diary")["groups"]

    assert group["active"][0]["name"] == "Wasn't Event Close"
    assert group["icon"] == "ca:grandmaster"


def test_diary_tiers_read_in_difficulty_order() -> None:
    """Alphabetically, Elite comes before Hard and Grandmaster before Master -
    which is every tier out of order in a list whose meaning is its order."""
    panel = panels.task_panel(_derived(
        other={
            "Diary": {
                "groups": [
                    {"name": f"Varrock Diary - {tier}", "active": ["x"], "completed": []}
                    for tier in ("Hard", "Easy", "Elite", "Medium")
                ]
            }
        }
    ))

    assert [g["name"] for g in _section(panel, "Diary")["groups"]] == [
        "Varrock Diary - Easy",
        "Varrock Diary - Medium",
        "Varrock Diary - Hard",
        "Varrock Diary - Elite",
    ]


def test_a_name_is_capitalised_and_otherwise_left_alone() -> None:
    """The export writes `unholy symbol` beside `Falador shield 1`, so a column
    of them starts in two cases. Only the first character is touched:
    lower-casing the rest destroys `TzHaar-Hur` and `Ardougne`."""
    from fray_claude.gui.panels import _display_name

    assert _display_name("unholy symbol") == "Unholy symbol"
    assert _display_name("Falador shield 1") == "Falador shield 1"
    assert _display_name("TzHaar-Hur") == "TzHaar-Hur"
    assert _display_name("") == ""


_CONSTRUCTION_ROLL = {
    "new_tasks": {
        "Construction": {
            "Build a ~|crude wooden chair|~": 1,
            "Build an ~|oak dining table|~": 22,
            "Build a ~|mahogany table|~": 52,
        },
        "Diary": {"~|Varrock Diary#Elite|~ Task 3": True},
        "Quest": {
            "~|Cook's Assistant|~ 1": True,
            "~|Cook's Assistant|~ Complete the quest": True,
        },
        "Extra": {"(Barrows Chests) Obtain ~|dharok's greataxe|~": "Collection Log"},
        "Nonskill": {"Pick onion*": True},
    },
    "bis_upgrades": {"Melee-shield": {"previous": "Rune kiteshield", "new": "Mooleta"}},
}


def test_a_roll_shows_one_task_per_skill_and_it_is_the_furthest() -> None:
    """**The complaint this exists for.** Unlocking a Construction chunk opens
    sixty builds and you care about the one at the top; the overlay listed all
    sixty, one heading per skill, where the Tasks tab shows a single row.
    """
    skills = _section(panels.roll_panel(_CONSTRUCTION_ROLL), "skills")

    assert skills["active_total"] == 1
    (group,) = skills["groups"]
    assert group["name"] == "Skills"
    assert group["active"][0]["name"] == "Mahogany table"
    assert group["active"][0]["note"] == "Construction"


def test_a_roll_is_shaped_by_the_panels_own_rules() -> None:
    """Not a second implementation: `roll_panel` rebuilds the *inputs* the
    panel's builders take, so a quest keeps only its furthest step, a diary
    row drops the heading it repeats, and `Extra` splits source from item."""
    panel = panels.roll_panel(_CONSTRUCTION_ROLL)

    (quests,) = _section(panel, "Quest")["groups"]
    assert [row["name"] for row in quests["active"]] == ["Cook's Assistant"]
    assert quests["active"][0]["note"] == "Complete the quest"

    (diary,) = _section(panel, "Diary")["groups"]
    assert diary["name"] == "Varrock Diary - Elite"
    assert diary["active"][0]["name"] == "Task 3"

    (extra,) = _section(panel, "Extra")["groups"]
    assert extra["name"] == "Collection Log"
    assert (extra["active"][0]["name"], extra["active"][0]["note"]) == (
        "Dharok's greataxe",
        "Barrows Chests",
    )

    (bis,) = _section(panel, "bis")["groups"]
    assert bis["name"] == "Melee"
    assert (bis["active"][0]["name"], bis["active"][0]["note"]) == ("Mooleta", "shield")


def test_a_roll_drops_nonskill_because_the_tasks_tab_does() -> None:
    """`other_tasks.CATEGORIES` is Diary/Quest/Extra, so there is no section
    for `Nonskill` to land in - and inventing one here would be the
    inconsistency this whole shape exists to remove."""
    panel = panels.roll_panel(_CONSTRUCTION_ROLL)

    assert [section["key"] for section in panel["sections"]] == [
        "skills", "bis", "Diary", "Quest", "Extra",
    ]
    assert all("Pick onion*" not in str(section) for section in panel["sections"])


def test_a_skill_already_past_the_new_task_shows_nothing() -> None:
    """**What makes a roll's list mean "news".**

    A Crafting chunk opens `Cook a ~|cup of tea (porcelain)|~` at Cooking 20;
    on a map that has already ticked the 99 Cooking cape that is not a Cooking
    goal, and the Tasks tab does not show it. The overlay listed it anyway.
    """
    roll = {"new_tasks": {"Cooking": {"Cook a ~|cup of tea (porcelain)|~": 20}}}

    assert _section(panels.roll_panel(roll), "skills")["active_total"] == 1
    assert _section(panels.roll_panel(roll, {"Cooking": 99.0}), "skills")["groups"] == []


def test_the_winner_is_the_furthest_task_still_ahead() -> None:
    """The ceiling filters *then* the highest of what is left wins - not the
    other way round, which would drop the skill whenever its top addition
    happened to be one you had already passed."""
    roll = {"new_tasks": {"Construction": {"a": 10, "b": 40, "c": 70}}}

    (group,) = _section(panels.roll_panel(roll, {"Construction": 40.0}), "skills")["groups"]

    assert [row["key"] for row in group["active"]] == ["c"]


def test_a_task_with_no_level_is_never_filtered_out() -> None:
    """A task with no `Level` is not a task at level 0 - it has **no ladder**,
    so nothing can be ahead of it. Collapsing the two hid every levelless
    skill task the moment a skill had any ceiling at all."""
    roll = {"new_tasks": {"Slayer": {"Slay something": True}}}

    (group,) = _section(panels.roll_panel(roll, {"Slayer": 99.0}), "skills")["groups"]

    assert [row["key"] for row in group["active"]] == ["Slay something"]


def test_a_newly_trainable_skill_contributes_its_standing_backlog() -> None:
    """The ledger's second branch, which the panel had no way to see.

    The additions are all low-level; the backlog holds the far one. Reading
    the additions alone named the level-65 task where the derivation named
    the level-85 one - see `unlock.newly_trainable_backlog`.
    """
    roll = {
        "new_tasks": {"Slayer": {"Wield ~|amethyst broad bolts|~": 65}},
        "newly_trainable": {"Slayer": {"Slay an ~|abyssal demon|~": 85}},
    }

    (group,) = _section(panels.roll_panel(roll), "skills")["groups"]

    assert [row["key"] for row in group["active"]] == ["Slay an ~|abyssal demon|~"]


def test_a_boosted_level_is_what_the_panel_ranks_on() -> None:
    """Two tasks the export calls 95 are not a tie if a boost reaches one.

    `NoBoost` bars the Alchemical Hydra, so the plain hydra is really a 90 and
    the pair is not tied at all - where ranking on the export's numbers tied
    them and `_wins_tie` handed it to the wrong one on `Priority`.
    """
    roll = {
        "new_tasks": {
            "Slayer": {"Slay a ~|hydra|~": 95, "Slay the ~|Alchemical Hydra|~": 95}
        },
        "boosted_levels": {"Slayer": {"Slay a ~|hydra|~": 90.0}},
    }
    challenges = {
        "Slayer": {
            "Slay a ~|hydra|~": {"Level": 95, "Priority": 1},
            "Slay the ~|Alchemical Hydra|~": {"Level": 95, "Priority": 2, "NoBoost": True},
        }
    }

    (group,) = _section(panels.roll_panel(roll, {}, challenges), "skills")["groups"]

    assert [row["key"] for row in group["active"]] == ["Slay the ~|Alchemical Hydra|~"]


def test_a_ledger_without_the_newer_branches_renders_as_it_always_did() -> None:
    """A run rolled before they existed is read, not refused."""
    panel = panels.roll_panel(_CONSTRUCTION_ROLL)

    assert _section(panel, "skills")["active_total"] == 1


#: How many rolls the ordinary oracle run replays. The whole 50 is ~58s,
#: which is not a price the everyday `FRAY_CHUNKINFO=... pytest` loop should
#: pay; twelve is ~14s and reaches every roll of `verf-sim/run-001` that has
#: ever caught something (`12849` at four, `5179` at five). The slow variant
#: below is the one that gets to say the equivalence holds *in general*.
_ORDINARY_ROLLS = 12


def _replay_and_compare(
    real_export: ChunkInfo, real_tasks_map: dict[str, str], limit: int | None
) -> int:
    """**The equivalence the roll panel exists to state.**

    A simulation projects a future in which you rolled these chunks and did
    the work each one opened. So the panel for roll k should name exactly what
    you would find if you played it: take the base map, tick off every task it
    is currently showing, unlock the chunk the run rolled, derive, and read the
    newly-active task per skill.

    Both sides derive with today's code. That matters: a *cached* run's ledger
    was written by whatever build rolled it, and `verf-sim`'s predates several
    derivation ports - re-deriving its sixth roll yields 71 new tasks against
    the 54 stored, `Chop ~|redwood logs|~` among them. Comparing against the
    stored ledger would therefore be a test of the cache's age. `delta_from`
    here is the same call `simulate.py` makes.

    Five real defects came out of this check and all five are asserted by it.
    Two are about what a completion proves: it proves a level even when the
    challenge lives in another category (`_level_proven_elsewhere`), and what
    it proves is boost-adjusted *downwards* (`boosts.completed_ceiling`) - a
    shortcut managed on a summer pie is not evidence of its face level. Two
    are about ranking: equal-level ties break on `Priority`/`Primary` rather
    than on the name, and the level being compared is the boosted one, so an
    export-equal pair where only one is boostable is not a tie at all. The
    fifth is eligibility - a roll that makes a skill *trainable* opens its
    whole standing backlog with no task's validity changing
    (`unlock.newly_trainable_backlog`).

    **Three defects hid behind one, all inside six rolls.** The prefix this
    ran over was already long enough to fail - roll four is where eligibility
    bites - but a failing comparison stops at the first disagreement, so
    fixing it revealed the next at roll five and that one revealed a third.
    Length is not what found them; re-running after each fix was. What length
    buys is the right to say the equivalence holds *generally*, which is why
    `limit` exists and why the slow variant below passes `None`.

    Returns the number of rolls compared, so a caller can assert it actually
    had something to compare rather than skipping silently.
    """
    from dataclasses import replace

    from fray_claude.derive import boosts
    from fray_claude.derive.active_tasks import _level_proven_elsewhere
    from fray_claude.derive.pipeline import derive, load_map_state
    from fray_claude.derive.unlock import delta_from
    from fray_claude.gui.routes_view import _raise_ceiling
    from fray_claude.store.cache import project_root, read_base_payload, read_rolls

    run = "verf-sim/run-001"
    base = read_base_payload(run, project_root())
    if base is None:
        pytest.skip(f"{run} records no base payload")
    rolls = [
        entry["chunk_id"]
        for entry in read_rolls(run, project_root())
        if isinstance(entry.get("chunk_id"), str)
    ][:limit]
    assert rolls, "the run rolled nothing to compare"

    state, unlocked = load_map_state(base, real_export, real_tasks_map)
    challenges = real_export.challenges

    def actives(derived: Any) -> dict[str, str]:
        return {
            skill: entry["active"]
            for skill, entry in derived.task_classification.as_dict().items()
            if isinstance(entry.get("active"), str) and entry["active"]
        }

    ceiling: dict[str, float] = {}
    #: The derivation the completed clamp is read against. `boosts` needs the
    #: reachable items, which move as the run rolls, so this is rebound each
    #: step rather than captured once.
    at: list[Any] = []

    def raise_to(skill: str, name: str) -> None:
        """`routes_view._completed_levels`' rule, over one completion."""
        known = challenges.get(skill) or {}
        challenge = known.get(name)
        level = challenge.get("Level") if isinstance(challenge, dict) else None
        if isinstance(challenge, dict) and isinstance(level, (int, float)) and not isinstance(
            level, bool
        ):
            level = boosts.completed_ceiling(
                skill,
                name,
                challenge,
                float(level),
                rules=state.rules,
                chunk_info=real_export,
                items=at[0].challenges.available_items,
                source_index=at[0].source_index,
            )
        elif not isinstance(level, (int, float)) or isinstance(level, bool):
            level = _level_proven_elsewhere(skill, name, challenges)
        if isinstance(level, (int, float)) and not isinstance(level, bool):
            ceiling[skill] = max(ceiling.get(skill, 0.0), float(level))

    rolled = derive(state, unlocked)
    at.append(rolled)
    completed = {skill: dict(names) for skill, names in state.completed_challenges.items()}
    for skill, names in completed.items():
        for name in names:
            raise_to(skill, name)
    before = actives(rolled)
    for skill, name in before.items():
        completed.setdefault(skill, {})[name] = True
        raise_to(skill, name)

    held = dict(unlocked)
    for chunk_id in rolls:
        held[chunk_id] = True
        after = derive(state, held)
        record = delta_from(rolled, after, chunk_id, state=state).as_dict()
        rolled = after

        played = derive(replace(state, completed_challenges=completed), held)
        now = actives(played)
        opened = {skill: name for skill, name in now.items() if before.get(skill) != name}

        section = _section(panels.roll_panel(record, ceiling, challenges), "skills")
        said = {row["note"]: row["key"] for g in section["groups"] for row in g["active"]}

        assert said == opened, f"roll on {chunk_id}"

        before = now
        at[0] = after
        for skill, name in now.items():
            completed.setdefault(skill, {})[name] = True
            raise_to(skill, name)
        # **The production fold, not a second copy of it.** An earlier version
        # inlined it, and the inline copy went on reading raw levels after
        # `_raise_ceiling` learned to read the clamped ones - so the test kept
        # passing against its own arithmetic.
        _raise_ceiling(ceiling, record)
    return len(rolls)


@pytest.mark.real_cache
def test_a_roll_panel_matches_playing_the_run_out(
    real_export: ChunkInfo, real_tasks_map: dict[str, str]
) -> None:
    """`_replay_and_compare` over the rolls that have ever caught something."""
    assert _replay_and_compare(real_export, real_tasks_map, _ORDINARY_ROLLS) > 1


@pytest.mark.real_cache
@pytest.mark.slow
def test_a_roll_panel_matches_playing_out_the_whole_run(
    real_export: ChunkInfo, real_tasks_map: dict[str, str]
) -> None:
    """The same equivalence, over all fifty rolls rather than a prefix.

    **A prefix is evidence about a prefix.** The three defects the prefix
    found were each invisible until the one before it was fixed, which is
    reason enough to distrust "it passes as far as I looked" - the only
    honest way to say the panel and the derivation agree is to have compared
    them everywhere. Gated on `FRAY_SLOW_ORACLES` because it is ~58s where
    the prefix is ~14s.
    """
    assert _replay_and_compare(real_export, real_tasks_map, None) > _ORDINARY_ROLLS


def test_a_qualifier_is_kept_and_only_a_heading_is_cut() -> None:
    """**Position decides what `#` means, and getting that wrong deleted
    names.**

    Opening a name it is a heading - `~|Combat Achievements#Grandmaster|~
    Wasn't Event Close` - repeated in every row of that group, so the column
    reads better without it. Anywhere else it says *which* thing: a mutated
    zygomite of a level, a hull of a class. The old rule cut at the first `#`
    wherever it sat and kept the tail, so those rows read `86` and `Raft` -
    the qualifier alone, with the thing it qualified thrown away.
    """
    assert panels._display_name("Slay a mutated ~|zygomite#Level 86|~") == (
        "Slay a mutated zygomite (Level 86)"
    )
    assert panels._display_name("Build a ~|wooden hull#Raft|~") == "Build a wooden hull (Raft)"
    # A heading still comes off, which is the behaviour this keeps.
    assert panels._display_name("~|Varrock Diary#Elite|~ Task 3") == "Task 3"
    assert panels._display_name("~|Combat Achievements#Medium|~ Big, Black and Fiery") == (
        "Big, Black and Fiery"
    )
    # And a name with no qualifier is untouched beyond the markup and the case.
    assert panels._display_name("Slay an ~|abyssal demon|~") == "Slay an abyssal demon"


def test_the_marked_name_is_the_display_name_before_the_spans_were_flattened() -> None:
    """The page turns each span into a link to what it names, which needs the
    words `strip_task_markup` throws away - so the heading comes off here and
    the markup does not."""
    assert panels._marked_name("Slay a mutated ~|zygomite#Level 86|~") == (
        "Slay a mutated ~|zygomite#Level 86|~"
    )
    assert panels._marked_name("~|Varrock Diary#Elite|~ Task 3") == "Task 3"
