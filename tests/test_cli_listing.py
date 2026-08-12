"""Tests for `cli/listing.py`: `sections`, `sources` and the four-way `tasks` branch.

`project`, `cached_map`, `simulatable` and `derived_entries` come from
`conftest.py`, so the cache under test is a temporary one rather than the
project's own.
"""

from __future__ import annotations

import json
from pathlib import Path
from collections.abc import Callable
from typing import Any

import pytest

from fray_claude.store.cache import write_blob
from fray_claude.cli.app import main


def _other_payload() -> tuple[dict[str, Any], dict[str, Any]]:
    payload: dict[str, Any] = {
        "chunks": {"unlocked": {}},
        "chunkinfo": {"completedChallenges": {"Extra": {"Obtain a cape": True}}},
    }
    chunkinfo_data: dict[str, Any] = {
        "challenges": {
            "Diary": {"~|Varrock Diary#Easy|~ Task 1": {"Description": "Browse the shop"}},
            "Quest": {"~|Cook's Assistant|~ 1": {"BaseQuest": "Cook's Assistant",
                                                 "Description": "Talk to the cook"}},
            "Extra": {
                "Obtain a ~|thing|~": {"Label": "Collection Log"},
                "Obtain a cape": {"Label": "Permanent Unlockables"},
            },
        }
    }
    return payload, chunkinfo_data


def test_sections_reports_reachable_sections(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True, "200": True}}}
    cached_map(payload, {"sections": {"100": {"1": ["200"]}}})
    capsys.readouterr()

    assert main(["sections"]) == 0

    out = capsys.readouterr().out
    assert "unlocked chunks    2" in out
    assert "reachable sections 1" in out


def test_sections_without_a_cached_map_exits_one(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["sections"]) == 1
    assert "no cached data for map 'fray'" in capsys.readouterr().err


def test_sections_export_json_to_stdout_replaces_the_summary(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True, "200": True}}}
    cached_map(payload, {"sections": {"100": {"1": ["200"]}}})
    capsys.readouterr()

    assert main(["sections", "--export-json", "-"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result == {"map_id": "fray", "unlocked_chunks": 2, "sections": {"100": {"1": True}}}


def test_sections_export_json_to_a_file_also_prints_the_summary(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True, "200": True}}}
    cached_map(payload, {"sections": {"100": {"1": ["200"]}}})
    capsys.readouterr()
    destination = project / "out.json"

    assert main(["sections", "--export-json", str(destination)]) == 0

    out = capsys.readouterr().out
    assert "reachable sections 1" in out
    assert json.loads(destination.read_text(encoding="utf-8"))["unlocked_chunks"] == 2


def test_sources_reports_availability_counts(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "chunks": {"100": {"Monster": {"Goblin": True}, "Object": {"Anvil": True}}},
        "drops": {"Goblin": {"Bones": {"1": "Always"}}},
    }
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["sources"]) == 0

    out = capsys.readouterr().out
    assert "items      1" in out
    assert "objects    1" in out
    assert "monsters   1" in out


def test_sources_without_a_cached_map_exits_one(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["sources"]) == 1
    assert "no cached data for map 'fray'" in capsys.readouterr().err


def test_sources_export_json_to_stdout_replaces_the_summary(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "chunks": {"100": {"Monster": {"Goblin": True}}},
        "drops": {"Goblin": {"Bones": {"1": "Always"}}},
    }
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["sources", "--export-json", "-"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["monsters"] == {"Goblin": {"100": True}}
    assert result["items"] == {"Bones": {"Goblin": "primary-drop"}}


def test_sources_reports_the_key_item_bosses_gap_as_an_error(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}, "rules": {"KeyItem Bosses": True}}
    cached_map(payload, {})
    capsys.readouterr()

    assert main(["sources"]) == 1
    assert "KeyItem Bosses" in capsys.readouterr().err


def test_tasks_overview_summarises_without_the_per_category_valid_breakdown(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "chunks": {"100": {"Monster": {"Goblin": True}}},
        "drops": {"Goblin": {"Bones": {"1": "Always"}}},
        "challenges": {"Nonskill": {"Use bones": {"Items": ["Bones"]}}},
    }
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["tasks"]) == 0

    out = capsys.readouterr().out
    assert "valid tasks  1" in out
    assert "unsupported  0 individual tasks" in out
    # Totals stay; the per-category enumeration of mostly-superseded valid
    # tasks is gone, and the summary reads active -> completed -> obsolete.
    assert "Nonskill" not in out
    assert "skill tasks  active 0, completed 0, obsolete 0" in out


def test_tasks_overview_lists_the_active_task_of_each_category(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "chunks": {"100": {"Monster": {"Goblin": True}}},
        "drops": {"Goblin": {"Rune scimitar": {"1": "Always"}}},
        "equipment": {
            "Rune scimitar": {"slot": "weapon", "attack_speed": 4, "attack_slash": 45, "melee_strength": 44}
        },
        "challenges": {
            "Woodcutting": {
                "Chop with a ~|bronze axe|~": {"Level": 1, "Primary": True},
                "Chop with a ~|rune axe|~": {"Level": 41, "Primary": True},
            }
        },
    }
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["tasks"]) == 0

    out = capsys.readouterr().out
    # The winning pick per skill, markup-stripped - not the superseded tier.
    assert "  Woodcutting   Chop with a rune axe" in out
    assert "bronze axe" not in out
    # And BiS's own active picks, in the same `[slot] Obtain ...` form the
    # `fray tasks BiS` view uses.
    assert "BiS          active 1" in out
    assert "  [weapon] Obtain a rune scimitar" in out


def test_tasks_overview_active_breakdown_respects_the_limit(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "challenges": {
            # The Level 1 entries make each skill *trainable*
            # (`checkPrimaryMethod`), without which nothing above the passive
            # floor is eligible at all - see `active_tasks._is_eligible`.
            "Woodcutting": {
                "Chop a sapling": {"Level": 1, "Primary": True},
                "Chop a tree": {"Level": 5, "Primary": True},
            },
            "Mining": {
                "Mine a pebble": {"Level": 1, "Primary": True},
                "Mine a rock": {"Level": 5, "Primary": True},
            },
        }
    }
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["tasks", "--limit", "1"]) == 0

    out = capsys.readouterr().out
    assert "  Mining        Mine a rock" in out
    assert "Chop a tree" not in out
    assert "... and 1 more" in out


def test_tasks_without_a_cached_map_exits_one(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["tasks"]) == 1
    assert "no cached data for map 'fray'" in capsys.readouterr().err


def test_tasks_export_json_to_stdout_replaces_the_summary(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "chunks": {"100": {"Monster": {"Goblin": True}}},
        "drops": {"Goblin": {"Bones": {"1": "Always"}}},
        "challenges": {
            "Nonskill": {
                "Use bones": {"Items": ["Bones"]},
                "Earn points": {"QuestPointsNeeded": 5},
            }
        },
    }
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["tasks", "--export-json", "-"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["valid"]["Nonskill"] == {"Use bones": True}
    assert result["unsupported"] == ["Nonskill/Earn points"]


def test_unlock_cache_map_saves_a_readable_map(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "chunks": {"101": {"Monster": {"Goblin": True}}},
        "sections": {"101": {"0": ["100"]}},
        "drops": {"Goblin": {"Bones": {"1": "Always"}}},
        "challenges": {"Nonskill": {"Use bones": {"Items": ["Bones"]}}},
    }
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["unlock", "--chunk", "101", "--cache-map", "Candidate"]) == 0

    out = capsys.readouterr().out
    assert "saved as     Candidate" in out
    # **Its own kind**, not filed under `simulated`: a map made by adding one
    # chunk by hand is not a simulation, and the picker has to say which.
    envelope = json.loads(
        (project / "cache" / "maps" / "edited" / "Candidate" / "run-001" / "map.json").read_text()
    )
    assert envelope["kind"] == "edited"
    assert envelope["source"] == "unlock 101 from 'fray'"
    assert envelope["simulation"]["origin"] == "unlock"
    assert set(envelope["data"]["chunks"]["unlocked"]) == {"100", "101"}

    # The saved world is a cached map like any other, so `--map` reaches it.
    assert main(["sections", "--map", "Candidate"]) == 0
    assert "unlocked chunks    2" in capsys.readouterr().out


def test_sections_list_reports_every_unlocked_chunk(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True, "200": True}}}
    chunkinfo_data = {"chunks": {"100": {"Nickname": "Home"}, "200": {"Nickname": "Away"}}}
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["sections", "list"]) == 0

    out = capsys.readouterr().out
    assert "unlocked chunks 2" in out
    assert "100" in out and "Home" in out
    assert "200" in out and "Away" in out


def test_sections_drill_down_reports_reachable_and_locked(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "chunks": {"100": {"Nickname": "Home"}},
        "sections": {"100": {"1": [], "2": []}},
    }
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["sections", "100"]) == 0

    out = capsys.readouterr().out
    assert "chunk     100" in out
    assert "name      Home" in out
    assert "reachable 0" in out
    assert "locked    1, 2" in out


def test_sections_drill_down_unknown_chunk_exits_one(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    cached_map(payload, {})
    capsys.readouterr()

    assert main(["sections", "999"]) == 1
    assert "not unlocked" in capsys.readouterr().err


def test_sources_category_lists_names_with_a_limit(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {"chunks": {"100": {"Shop": {"A Shop": True, "B Shop": True}}}}
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["sources", "shops"]) == 0

    out = capsys.readouterr().out
    assert "category shops" in out
    assert "count    2" in out
    assert "A Shop" in out
    assert "B Shop" in out


def test_sources_category_export_json(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {"chunks": {"100": {"Shop": {"A Shop": True}}}}
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["sources", "shops", "--export-json", "-"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["category"] == "shops"
    assert result["shops"] == {"A Shop": {"100": True}}


def test_sources_unknown_category_is_rejected_by_argparse(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload: dict[str, Any] = {"chunks": {"unlocked": {}}}
    cached_map(payload, {})
    capsys.readouterr()

    with pytest.raises(SystemExit):
        main(["sources", "bogus"])


def test_tasks_category_lists_valid_task_names(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data: dict[str, Any] = {"challenges": {"Nonskill": {"Do a thing": {}}}}
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["tasks", "Nonskill"]) == 0

    out = capsys.readouterr().out
    assert "category Nonskill" in out
    assert "valid    1" in out
    assert "Do a thing" in out


def test_tasks_skill_category_shows_active_obsolete_and_completed(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from fray_claude.store.cache import write_blob

    payload: dict[str, Any] = {
        "chunks": {"unlocked": {}},
        "chunkinfo": {"completedChallenges": {"Woodcutting": {"t_1": True}}},
    }
    chunkinfo_data = {
        "challenges": {
            "Woodcutting": {
                "Chop with a bronze axe": {"Level": 1, "Primary": True},
                "Chop with a rune axe": {"Level": 41, "Primary": True},
                "Chop with a steel axe": {"Level": 6, "Primary": True},
            }
        }
    }
    cached_map(payload, chunkinfo_data)
    write_blob("tasks_map", {"Chop with a bronze axe": "t_1"}, "https://example/tasksMap.json")
    capsys.readouterr()

    assert main(["tasks", "Woodcutting"]) == 0

    out = capsys.readouterr().out
    assert "category Woodcutting" in out
    assert "active   Chop with a rune axe  [not cached]" in out
    assert "obsolete 1" in out
    assert "Chop with a steel axe" in out
    assert "completed 1" in out
    assert "Chop with a bronze axe" in out
    # Sections read active -> completed -> obsolete.
    assert out.index("active   ") < out.index("completed ") < out.index("obsolete ")


def test_tasks_skill_category_strips_markup_from_every_section(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from fray_claude.store.cache import write_blob

    payload: dict[str, Any] = {
        "chunks": {"unlocked": {}},
        "chunkinfo": {"completedChallenges": {"Woodcutting": {"t_1": True}}},
    }
    chunkinfo_data = {
        "challenges": {
            "Woodcutting": {
                "Chop a ~|regular tree|~": {"Level": 1, "Primary": True},
                "Chop a ~|magic tree|~": {"Level": 75, "Primary": True},
                "Chop a ~|yew tree|~": {"Level": 60, "Primary": True},
            }
        }
    }
    cached_map(payload, chunkinfo_data)
    write_blob("tasks_map", {"Chop a ~|regular tree|~": "t_1"}, "https://example/tasksMap.json")
    capsys.readouterr()

    assert main(["tasks", "Woodcutting"]) == 0

    out = capsys.readouterr().out
    assert "active   Chop a magic tree" in out
    assert "  Chop a regular tree" in out
    assert "  Chop a yew tree" in out
    assert "~|" not in out


def test_tasks_flat_category_strips_markup(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload: dict[str, Any] = {"chunks": {"unlocked": {}}}
    chunkinfo_data: dict[str, Any] = {"challenges": {"Quest": {"Complete ~|Dragon Slayer|~": {}}}}
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["tasks", "Quest"]) == 0

    out = capsys.readouterr().out
    assert "  Complete Dragon Slayer" in out
    assert "~|" not in out


def test_tasks_skill_category_reports_a_cached_active_task_match(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from fray_claude.store.cache import write_blob

    payload: dict[str, Any] = {
        "chunks": {"unlocked": {}},
        "chunkinfo": {"activeTasks": {"Woodcutting": {"t_1": "41"}}},
    }
    chunkinfo_data = {
        "challenges": {
            "Woodcutting": {
                "Chop with a bronze axe": {"Level": 1, "Primary": True},
                "Chop with a rune axe": {"Level": 41, "Primary": True},
            }
        }
    }
    cached_map(payload, chunkinfo_data)
    write_blob("tasks_map", {"Chop with a rune axe": "t_1"}, "https://example/tasksMap.json")
    capsys.readouterr()

    assert main(["tasks", "Woodcutting"]) == 0

    out = capsys.readouterr().out
    assert "matches cached active task" in out


def test_tasks_unknown_category_exits_one(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload: dict[str, Any] = {"chunks": {"unlocked": {}}}
    cached_map(payload, {})
    capsys.readouterr()

    assert main(["tasks", "Bogus"]) == 1
    assert "unknown task category" in capsys.readouterr().err


def test_tasks_bis_category_reports_computed_gear(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "chunks": {"100": {"Monster": {"Goblin": True}}},
        "drops": {"Goblin": {"Rune scimitar": {"1": "Always"}}},
        "equipment": {
            "Rune scimitar": {
                "slot": "weapon",
                "attack_speed": 4,
                "attack_slash": 45,
                "melee_strength": 44,
            }
        },
    }
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["tasks", "BiS"]) == 0

    out = capsys.readouterr().out
    assert "category  BiS" in out
    assert "active    1" in out
    assert "completed 0" in out
    # Slot-prefixed and markup-free: the terminal never shows `~|...|~`.
    assert "[weapon] Obtain a rune scimitar" in out
    assert "~|" not in out


def test_tasks_bis_lists_this_chunks_completions_first(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A pick still sitting in `checkedChallenges` was obtained during the
    chunk in play, so it sorts above earlier ones and carries the suffix -
    `rune scimitar` would otherwise sort after `black cape` alphabetically.
    """
    payload = {
        "chunks": {"unlocked": {"100": True}},
        "chunkinfo": {
            "completedChallenges": {"BiS": {"Obtain a ~|black cape|~": True}},
            "checkedChallenges": {"BiS": {"Obtain a ~|rune scimitar|~": True}},
        },
    }
    chunkinfo_data = {
        "chunks": {"100": {"Monster": {"Goblin": True}}},
        "drops": {"Goblin": {"Rune scimitar": {"1": "Always"}, "Black cape": {"1": "Always"}}},
        "equipment": {
            "Rune scimitar": {"slot": "weapon", "attack_speed": 4, "attack_slash": 45, "melee_strength": 44},
            "Black cape": {"slot": "cape", "melee_strength": 1},
        },
    }
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["tasks", "BiS"]) == 0

    completed = capsys.readouterr().out.split("completed ", 1)[1].splitlines()[1:3]
    assert completed == [
        "  [weapon] Obtain a rune scimitar (Active)",
        "  [cape] Obtain a black cape",
    ]


def test_tasks_overview_lists_the_other_categories(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload, chunkinfo_data = _other_payload()
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["tasks"]) == 0

    out = capsys.readouterr().out
    assert "Diary        active 1, completed 0" in out
    assert "Quest        active 1, completed 0" in out
    # `Extra` is displayed as `Other`, and the completed cape is not active.
    assert "Other        active 1, completed 1" in out
    assert "[Varrock Diary - Easy] Browse the shop" in out
    assert "[Collection Log] Obtain a thing" in out


def test_tasks_other_category_groups_with_headers(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload, chunkinfo_data = _other_payload()
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["tasks", "Other"]) == 0

    out = capsys.readouterr().out
    assert "category Other (Extra)" in out
    assert "  Collection Log\n    Obtain a thing" in out
    assert "  Permanent Unlockables\n    Obtain a cape" in out


def test_tasks_accepts_extra_as_an_alias_for_other(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload, chunkinfo_data = _other_payload()
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["tasks", "Extra"]) == 0
    from_extra = capsys.readouterr().out

    assert main(["tasks", "other"]) == 0
    from_other = capsys.readouterr().out

    assert from_extra == from_other
    assert "category Other (Extra)" in from_extra


def test_tasks_other_category_export_json_keeps_the_real_key(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload, chunkinfo_data = _other_payload()
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["tasks", "Other", "--export-json", "-"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["category"] == "Extra"
    assert result["label"] == "Other"
    assert result["active_total"] == 1


def test_simulate_cache_map_writes_a_readable_map(
    project: Path, simulatable: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    simulatable()
    capsys.readouterr()

    assert main(["simulate", "--rolls", "2", "--seed", "1", "--cache-map", "Demo"]) == 0

    out = capsys.readouterr().out
    assert "batch        Demo" in out
    assert "fray tasks --map Demo" in out
    assert (project / "cache" / "maps" / "simulated" / "Demo" / "run-001" / "map.json").is_file()

    # The saved state is a map like any other.
    assert main(["sections", "--map", "Demo"]) == 0
    assert "unlocked chunks    3" in capsys.readouterr().out


def test_a_second_command_reuses_the_first_ones_derivation(
    project: Path, simulatable: Callable[[], None],
    derived_entries: Callable[[Path], list[Path]],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The key is the derivation's *inputs*, so unrelated commands over the
    same state share one entry rather than each keeping their own."""
    simulatable()
    main(["tasks"])
    assert len(derived_entries(project)) == 1
    capsys.readouterr()

    calls: list[int] = []
    monkeypatch.setattr(
        "fray_claude.store.derived_cache.derive",
        lambda *a, **k: calls.append(1),  # never reached on a hit
    )

    assert main(["sections"]) == 0
    assert main(["sources"]) == 0
    assert calls == []
    assert len(derived_entries(project)) == 1


def test_recompute_ignores_the_cached_derivation(
    project: Path, simulatable: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    simulatable()
    main(["tasks"])
    capsys.readouterr()
    fresh = main(["tasks", "--recompute", "--export-json", "-"])
    recomputed = capsys.readouterr().out

    cached = main(["tasks", "--export-json", "-"])

    assert (fresh, cached) == (0, 0)
    assert capsys.readouterr().out == recomputed


def test_derived_list_summarises_the_cache(
    project: Path, simulatable: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    simulatable()
    main(["tasks"])
    capsys.readouterr()

    assert main(["derived", "list", "--verbose"]) == 0

    out = capsys.readouterr().out
    assert "entries      1" in out
    assert ".pkl" in out


def test_derived_clean_all_empties_the_cache(
    project: Path, simulatable: Callable[[], None],
    derived_entries: Callable[[Path], list[Path]],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    simulatable()
    main(["tasks"])
    capsys.readouterr()

    assert main(["derived", "clean", "--all"]) == 0

    assert "removed 1 cached derivations" in capsys.readouterr().out
    assert derived_entries(project) == []


def test_derived_clean_keeps_recently_read_entries(
    project: Path, simulatable: Callable[[], None],
    derived_entries: Callable[[Path], list[Path]],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    simulatable()
    main(["tasks"])
    capsys.readouterr()

    assert main(["derived", "clean"]) == 0

    assert "nothing to clean" in capsys.readouterr().out
    assert len(derived_entries(project)) == 1


def test_a_simulated_maps_own_state_is_cached_by_its_run(
    project: Path, simulatable: Callable[[], None],
    derived_entries: Callable[[Path], list[Path]],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The point of always keeping the finishing state: the map the run saved
    is derived from it, so reading that map back costs nothing."""
    simulatable()
    main(["simulate", "--rolls", "2", "--seed", "1", "--cache-map", "S", "--cache-behaviour",
          "extremities"])
    capsys.readouterr()
    stored = len(derived_entries(project))

    monkeypatch.setattr(
        "fray_claude.store.derived_cache.derive",
        lambda *a, **k: pytest.fail("the saved map's own state should already be cached"),
    )

    assert main(["tasks", "--map", "S"]) == 0
    assert len(derived_entries(project)) == stored
