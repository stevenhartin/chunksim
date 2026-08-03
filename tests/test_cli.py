"""Tests for the argparse layer.

Each test chdirs into a `tmp_path` holding a `pyproject.toml`, so the cache the
CLI resolves is the temporary one rather than the project's own.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fray_claude.api import DEFAULT_TIMEOUT, FetchError
from fray_claude.cli import _format_age, build_parser, main


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway project root that `cache.project_root()` will find."""
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_parser_defaults_to_the_fray_map() -> None:
    args = build_parser().parse_args(["fetch"])

    assert (args.map_id, args.timeout) == ("fray", DEFAULT_TIMEOUT)


def test_parser_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_fetch_writes_the_cache(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch_map(map_id: str, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
        return {"chunks": {"unlocked": {"50_50": True}}}

    monkeypatch.setattr("fray_claude.cli.fetch_map", fake_fetch_map)

    assert main(["fetch"]) == 0
    assert (project / "cache" / "fray.json").is_file()


def test_show_summarises_the_cached_map(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {
        "chunks": {"unlocked": {"50_50": True, "50_51": True}},
        "rules": {"All Shops": True, "Boosting": False},
    }
    monkeypatch.setattr(
        "fray_claude.cli.fetch_map", lambda map_id, timeout=DEFAULT_TIMEOUT: payload
    )
    main(["fetch"])
    capsys.readouterr()

    assert main(["show"]) == 0

    out = capsys.readouterr().out
    assert "unlocked       2 chunks" in out
    assert "rules          1 of 2 enabled" in out
    assert "active tasks   0" in out


def test_show_without_a_cache_exits_one(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["show"]) == 1
    assert "no cached data for map 'fray'" in capsys.readouterr().err


def test_fetch_failure_exits_one(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_fetch_map(map_id: str, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
        raise FetchError(f"no such map: {map_id!r}")

    monkeypatch.setattr("fray_claude.cli.fetch_map", fake_fetch_map)

    assert main(["fetch", "--map", "nope"]) == 1
    assert capsys.readouterr().err == "error: no such map: 'nope'\n"


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=5), "5s ago"),
        (timedelta(minutes=3), "3m ago"),
        (timedelta(hours=5), "5h ago"),
        (timedelta(days=2), "2d ago"),
        (timedelta(seconds=-30), "0s ago"),
    ],
)
def test_format_age_buckets(delta: timedelta, expected: str) -> None:
    assert _format_age((datetime.now(UTC) - delta).isoformat()) == expected


def test_format_age_assumes_utc_for_a_naive_timestamp() -> None:
    naive = datetime.now(UTC).replace(tzinfo=None).isoformat()

    assert _format_age(naive) == "0s ago"


@pytest.mark.parametrize("value", ["not a timestamp", None, 1709907279995])
def test_format_age_reports_unusable_input_as_unknown(value: object) -> None:
    assert _format_age(value) == "unknown"


def test_chunkinfo_fetches_and_caches_both_blobs(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "fray_claude.cli.fetch_chunkinfo", lambda timeout=DEFAULT_TIMEOUT: {"chunks": {}}
    )
    monkeypatch.setattr(
        "fray_claude.cli.fetch_tasks_map",
        lambda timeout=DEFAULT_TIMEOUT: {"Obtain a whip": "t_1"},
    )

    assert main(["chunkinfo"]) == 0
    assert (project / "cache" / "chunkinfo.json").is_file()
    assert (project / "cache" / "tasks_map.json").is_file()


def _cache_map_and_chunkinfo(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any], chunkinfo_data: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        "fray_claude.cli.fetch_map", lambda map_id, timeout=DEFAULT_TIMEOUT: payload
    )
    main(["fetch"])
    monkeypatch.setattr(
        "fray_claude.cli.read_chunkinfo",
        lambda override=None, root=None: chunkinfo_data,
    )


def test_sections_reports_reachable_sections(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True, "200": True}}}
    _cache_map_and_chunkinfo(monkeypatch, payload, {"sections": {"100": {"1": ["200"]}}})
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
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True, "200": True}}}
    _cache_map_and_chunkinfo(monkeypatch, payload, {"sections": {"100": {"1": ["200"]}}})
    capsys.readouterr()

    assert main(["sections", "--export-json", "-"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result == {"map_id": "fray", "unlocked_chunks": 2, "sections": {"100": {"1": True}}}


def test_sections_export_json_to_a_file_also_prints_the_summary(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True, "200": True}}}
    _cache_map_and_chunkinfo(monkeypatch, payload, {"sections": {"100": {"1": ["200"]}}})
    capsys.readouterr()
    destination = project / "out.json"

    assert main(["sections", "--export-json", str(destination)]) == 0

    out = capsys.readouterr().out
    assert "reachable sections 1" in out
    assert json.loads(destination.read_text(encoding="utf-8"))["unlocked_chunks"] == 2


def test_sources_reports_availability_counts(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "chunks": {"100": {"Monster": {"Goblin": True}, "Object": {"Anvil": True}}},
        "drops": {"Goblin": {"Bones": {"1": "Always"}}},
    }
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
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
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "chunks": {"100": {"Monster": {"Goblin": True}}},
        "drops": {"Goblin": {"Bones": {"1": "Always"}}},
    }
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["sources", "--export-json", "-"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["monsters"] == {"Goblin": {"100": True}}
    assert result["items"] == {"Bones": {"Goblin": "primary-drop"}}


def test_sources_reports_the_key_item_bosses_gap_as_an_error(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}, "rules": {"KeyItem Bosses": True}}
    _cache_map_and_chunkinfo(monkeypatch, payload, {})
    capsys.readouterr()

    assert main(["sources"]) == 1
    assert "KeyItem Bosses" in capsys.readouterr().err


def test_tasks_reports_valid_counts_per_skill(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "chunks": {"100": {"Monster": {"Goblin": True}}},
        "drops": {"Goblin": {"Bones": {"1": "Always"}}},
        "challenges": {"Nonskill": {"Use bones": {"Items": ["Bones"]}}},
    }
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["tasks"]) == 0

    out = capsys.readouterr().out
    assert "valid tasks  1" in out
    assert "Nonskill     1" in out
    assert "unsupported  0 individual tasks" in out
    assert "BiS          0" in out


def test_tasks_without_a_cached_map_exits_one(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["tasks"]) == 1
    assert "no cached data for map 'fray'" in capsys.readouterr().err


def test_tasks_export_json_to_stdout_replaces_the_summary(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
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
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["tasks", "--export-json", "-"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["valid"]["Nonskill"] == {"Use bones": True}
    assert result["unsupported"] == ["Nonskill/Earn points"]


def test_unlock_reports_new_tasks_and_sections(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "chunks": {"101": {"Monster": {"Goblin": True}}},
        "sections": {"101": {"0": ["100"]}},
        "drops": {"Goblin": {"Bones": {"1": "Always"}}},
        "challenges": {"Nonskill": {"Use bones": {"Items": ["Bones"]}}},
    }
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["unlock", "--chunk", "101"]) == 0

    out = capsys.readouterr().out
    assert "chunk        101" in out
    assert "new tasks    1" in out
    assert "Nonskill     1" in out


def test_unlock_without_a_cached_map_exits_one(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["unlock", "--chunk", "101"]) == 1
    assert "no cached data for map 'fray'" in capsys.readouterr().err


def test_unlock_export_json_to_stdout_replaces_the_summary(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "chunks": {"101": {"Monster": {"Goblin": True}}},
        "sections": {"101": {"0": ["100"]}},
        "drops": {"Goblin": {"Bones": {"1": "Always"}}},
        "challenges": {"Nonskill": {"Use bones": {"Items": ["Bones"]}}},
    }
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["unlock", "--chunk", "101", "--export-json", "-"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["chunk_id"] == "101"
    assert result["new_tasks"] == {"Nonskill": {"Use bones": True}}


def test_simulate_reports_each_roll(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {"sections": {"101": {"0": ["100"]}}}
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["simulate", "--rolls", "5", "--seed", "1"]) == 0

    out = capsys.readouterr().out
    assert "rolls        1 of 5 requested (seed 1)" in out
    assert "1 101" in out


def test_simulate_without_a_cached_map_exits_one(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["simulate", "--rolls", "1"]) == 1
    assert "no cached data for map 'fray'" in capsys.readouterr().err


def test_simulate_is_deterministic_given_the_same_seed(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "sections": {
            "101": {"0": ["100"]},
            "102": {"0": ["100"]},
            "103": {"0": ["100"]},
        }
    }
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    main(["simulate", "--rolls", "3", "--seed", "9", "--export-json", "-"])
    first = json.loads(capsys.readouterr().out)

    main(["simulate", "--rolls", "3", "--seed", "9", "--export-json", "-"])
    second = json.loads(capsys.readouterr().out)

    assert first["rolls"] == second["rolls"]


def test_simulate_export_json_to_stdout_replaces_the_summary(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {"sections": {"101": {"0": ["100"]}}}
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["simulate", "--rolls", "1", "--seed", "1", "--export-json", "-"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["seed"] == 1
    assert result["rolls_requested"] == 1
    assert [r["chunk_id"] for r in result["rolls"]] == ["101"]


def test_sections_list_reports_every_unlocked_chunk(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True, "200": True}}}
    chunkinfo_data = {"chunks": {"100": {"Nickname": "Home"}, "200": {"Nickname": "Away"}}}
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["sections", "list"]) == 0

    out = capsys.readouterr().out
    assert "unlocked chunks 2" in out
    assert "100" in out and "Home" in out
    assert "200" in out and "Away" in out


def test_sections_drill_down_reports_reachable_and_locked(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "chunks": {"100": {"Nickname": "Home"}},
        "sections": {"100": {"1": [], "2": []}},
    }
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["sections", "100"]) == 0

    out = capsys.readouterr().out
    assert "chunk     100" in out
    assert "name      Home" in out
    assert "reachable 0" in out
    assert "locked    1, 2" in out


def test_sections_drill_down_unknown_chunk_exits_one(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    _cache_map_and_chunkinfo(monkeypatch, payload, {})
    capsys.readouterr()

    assert main(["sections", "999"]) == 1
    assert "not unlocked" in capsys.readouterr().err


def test_sources_category_lists_names_with_a_limit(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {"chunks": {"100": {"Shop": {"A Shop": True, "B Shop": True}}}}
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["sources", "shops"]) == 0

    out = capsys.readouterr().out
    assert "category shops" in out
    assert "count    2" in out
    assert "A Shop" in out
    assert "B Shop" in out


def test_sources_category_export_json(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {"chunks": {"100": {"Shop": {"A Shop": True}}}}
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["sources", "shops", "--export-json", "-"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["category"] == "shops"
    assert result["shops"] == {"A Shop": {"100": True}}


def test_sources_unknown_category_is_rejected_by_argparse(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload: dict[str, Any] = {"chunks": {"unlocked": {}}}
    _cache_map_and_chunkinfo(monkeypatch, payload, {})
    capsys.readouterr()

    with pytest.raises(SystemExit):
        main(["sources", "bogus"])


def test_tasks_category_lists_valid_task_names(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data: dict[str, Any] = {"challenges": {"Nonskill": {"Do a thing": {}}}}
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["tasks", "Nonskill"]) == 0

    out = capsys.readouterr().out
    assert "category Nonskill" in out
    assert "valid    1" in out
    assert "Do a thing" in out


def test_tasks_skill_category_shows_active_obsolete_and_completed(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from fray_claude.cache import write_blob

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
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
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


def test_tasks_skill_category_reports_a_cached_active_task_match(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from fray_claude.cache import write_blob

    payload: dict[str, Any] = {
        "chunks": {"unlocked": {}},
        "chunkinfo": {"activeTasks": {"Woodcutting": {"t_1": "41"}}},
    }
    chunkinfo_data = {"challenges": {"Woodcutting": {"Chop with a rune axe": {"Level": 41, "Primary": True}}}}
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    write_blob("tasks_map", {"Chop with a rune axe": "t_1"}, "https://example/tasksMap.json")
    capsys.readouterr()

    assert main(["tasks", "Woodcutting"]) == 0

    out = capsys.readouterr().out
    assert "matches cached active task" in out


def test_tasks_unknown_category_exits_one(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload: dict[str, Any] = {"chunks": {"unlocked": {}}}
    _cache_map_and_chunkinfo(monkeypatch, payload, {})
    capsys.readouterr()

    assert main(["tasks", "Bogus"]) == 1
    assert "unknown task category" in capsys.readouterr().err


def test_tasks_bis_category_reports_computed_gear(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
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
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["tasks", "BiS"]) == 0

    out = capsys.readouterr().out
    assert "category  BiS" in out
    assert "active    1" in out
    assert "completed 0" in out
    assert "Obtain a ~|rune scimitar|~" in out


def test_search_reports_hits(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "chunks": {"100": {"Monster": {"Goblin": True}}},
        "drops": {"Goblin": {"Bones": {"1": "Always"}}},
    }
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["search", "bones"]) == 0

    out = capsys.readouterr().out
    assert "ITEM     Bones  [available]" in out
    assert "drop: Goblin" in out


def test_search_type_filters_results(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "chunks": {"100": {"Monster": {"Whip seller": True}}},
        "drops": {"Whip seller": {"Whip": {"1": "Always"}}},
    }
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["search", "whip", "--type", "monster"]) == 0

    out = capsys.readouterr().out
    assert "MONSTER  Whip seller" in out
    assert "ITEM" not in out


def test_search_without_a_cached_map_exits_one(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["search", "whip"]) == 1
    assert "no cached data for map 'fray'" in capsys.readouterr().err


def test_search_export_json_to_stdout_replaces_the_summary(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "chunks": {"100": {"Monster": {"Goblin": True}}},
        "drops": {"Goblin": {"Bones": {"1": "Always"}}},
    }
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["search", "bones", "--export-json", "-"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["query"] == "bones"
    assert result["hits"][0]["name"] == "Bones"
    assert result["hits"][0]["available"] is True
