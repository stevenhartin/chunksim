"""What the panel is handed, given what `derive` produced.

Fixtures are built by hand: `panels.py` reads `as_dict()` output and nothing
else, so a real export would only make the expected value harder to read.
"""

from __future__ import annotations

from typing import Any, cast

from fray_claude.gui import panels
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
