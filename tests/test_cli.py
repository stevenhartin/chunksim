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

from fray_claude.remote.api import DEFAULT_TIMEOUT, FetchError
from fray_claude.cache import write_blob
from fray_claude.cli import build_parser, main
from fray_claude.model.summary import format_age


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
    assert (project / "cache" / "maps" / "fetched" / "fray.json").is_file()


def test_every_command_stamps_which_install_answered(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """**`pipx install` without `--force` is a silent no-op**, so `fray` on
    `PATH` can be an older build than the checkout and nothing says so. The
    line goes to **stderr**, because nine subcommands can write their whole
    answer to stdout with `--export-json -`.
    """
    monkeypatch.delenv("FRAY_NO_WATERMARK", raising=False)
    monkeypatch.setattr(
        "fray_claude.cli.fetch_map",
        lambda map_id, timeout=DEFAULT_TIMEOUT: {"chunks": {"unlocked": {"50_50": True}}},
    )

    assert main(["fetch"]) == 0

    captured = capsys.readouterr()
    assert captured.err.startswith("fray ")
    assert "fray " not in captured.out.split("\n")[0]


def test_the_stamp_stays_off_the_stream_the_answer_goes_to(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`fray maps list --export-json -` has to stay pipeable into `jq`."""
    monkeypatch.delenv("FRAY_NO_WATERMARK", raising=False)
    monkeypatch.setattr(
        "fray_claude.cli.fetch_map",
        lambda map_id, timeout=DEFAULT_TIMEOUT: {"chunks": {"unlocked": {"50_50": True}}},
    )
    main(["fetch"])
    capsys.readouterr()

    assert main(["maps", "list", "--export-json", "-"]) == 0

    assert json.loads(capsys.readouterr().out)  # not "fray 0.1.0 ...{"


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


def test_show_reports_whether_the_dps_calculator_is_installed(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Not a property of the map, but an estimate computed with it differs.

    Nothing else on that screen would say which of the two numbers you are
    about to get, so the line is there whichever way it falls.
    """
    monkeypatch.setattr(
        "fray_claude.cli.fetch_map",
        lambda map_id, timeout=DEFAULT_TIMEOUT: {"chunks": {"unlocked": {"50_50": True}}},
    )
    main(["fetch"])
    capsys.readouterr()

    monkeypatch.setattr("fray_claude.dps_bridge.library_version", lambda: "9.9.9")
    main(["show"])
    assert "dps calc       osrs-dps 9.9.9" in capsys.readouterr().out

    monkeypatch.setattr("fray_claude.dps_bridge.library_version", lambda: None)
    main(["show"])
    assert "dps calc       not installed" in capsys.readouterr().out


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
    # `endswith` rather than `==`: the provenance line shares this stream.
    assert capsys.readouterr().err.endswith("error: no such map: 'nope'\n")


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
    assert format_age((datetime.now(UTC) - delta).isoformat()) == expected


def test_format_age_assumes_utc_for_a_naive_timestamp() -> None:
    naive = datetime.now(UTC).replace(tzinfo=None).isoformat()

    assert format_age(naive) == "0s ago"


@pytest.mark.parametrize("value", ["not a timestamp", None, 1709907279995])
def test_format_age_reports_unusable_input_as_unknown(value: object) -> None:
    assert format_age(value) == "unknown"


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
    assert (project / "cache" / "reference" / "chunkinfo.json").is_file()
    assert (project / "cache" / "reference" / "tasks_map.json").is_file()


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


def test_tasks_overview_summarises_without_the_per_category_valid_breakdown(
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
    assert "unsupported  0 individual tasks" in out
    # Totals stay; the per-category enumeration of mostly-superseded valid
    # tasks is gone, and the summary reads active -> completed -> obsolete.
    assert "Nonskill" not in out
    assert "skill tasks  active 0, completed 0, obsolete 0" in out


def test_tasks_overview_lists_the_active_task_of_each_category(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
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
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
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
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
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
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
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


def test_unlock_cache_map_saves_a_readable_map(
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

    assert main(["unlock", "--chunk", "101", "--cache-map", "Candidate"]) == 0

    out = capsys.readouterr().out
    assert "saved as     Candidate" in out
    # **Its own kind**, not filed under `simulated`: a map made by adding one
    # chunk by hand is not a simulation, and the picker has to say which.
    envelope = json.loads(
        (project / "cache" / "maps" / "unlocked" / "Candidate" / "run-001" / "map.json").read_text()
    )
    assert envelope["kind"] == "unlocked"
    assert envelope["source"] == "unlock 101 from 'fray'"
    assert envelope["simulation"]["origin"] == "unlock"
    assert set(envelope["data"]["chunks"]["unlocked"]) == {"100", "101"}

    # The saved world is a cached map like any other, so `--map` reaches it.
    assert main(["sections", "--map", "Candidate"]) == 0
    assert "unlocked chunks    2" in capsys.readouterr().out


def test_unlock_cache_map_suffixes_a_name_already_taken(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    _cache_map_and_chunkinfo(monkeypatch, payload, {"sections": {"101": {"0": ["100"]}}})
    capsys.readouterr()

    main(["unlock", "--chunk", "101", "--cache-map", "Candidate"])
    capsys.readouterr()
    assert main(["unlock", "--chunk", "101", "--cache-map", "Candidate"]) == 0

    out = capsys.readouterr().out
    assert "'Candidate' was taken; saved as 'Candidate-2'" in out
    assert (project / "cache" / "maps" / "unlocked" / "Candidate-2" / "run-001" / "map.json").is_file()


def test_unlock_cache_map_export_json_reports_the_name(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    _cache_map_and_chunkinfo(monkeypatch, payload, {"sections": {"101": {"0": ["100"]}}})
    capsys.readouterr()

    assert main(["unlock", "--chunk", "101", "--cache-map", "Kept", "--export-json", "-"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["cached_map"] == "Kept"


def _cache_two_maps(
    monkeypatch: pytest.MonkeyPatch,
    first: dict[str, Any],
    second: dict[str, Any],
    chunkinfo_data: dict[str, Any],
) -> None:
    payloads = {"a": first, "b": second}
    monkeypatch.setattr(
        "fray_claude.cli.fetch_map", lambda map_id, timeout=DEFAULT_TIMEOUT: payloads[map_id]
    )
    main(["fetch", "--map", "a"])
    main(["fetch", "--map", "b"])
    monkeypatch.setattr(
        "fray_claude.cli.read_chunkinfo",
        lambda override=None, root=None: chunkinfo_data,
    )


_DIFF_CHUNKINFO: dict[str, Any] = {
    "chunks": {"101": {"Monster": {"Goblin": True}}, "102": {"Monster": {"Imp": True}}},
    "drops": {"Goblin": {"Bones": {"1": "Always"}}, "Imp": {"Beads": {"1": "Always"}}},
    "challenges": {
        "Nonskill": {"Use bones": {"Items": ["Bones"]}, "Use beads": {"Items": ["Beads"]}}
    },
}


def test_diff_reports_both_directions(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _cache_two_maps(
        monkeypatch,
        {"chunks": {"unlocked": {"101": True}}},
        {"chunks": {"unlocked": {"102": True}}},
        _DIFF_CHUNKINFO,
    )
    capsys.readouterr()

    assert main(["diff", "--map1", "a", "--map2", "b"]) == 0

    out = capsys.readouterr().out
    assert "map1         a" in out
    assert "map2         b" in out
    # Neither map contains the other, so both halves are non-empty - the case
    # `fray unlock` structurally cannot report.
    assert "chunks       +1 -1" in out
    assert "tasks        +1 -1" in out


def test_diff_of_a_map_with_itself_reports_nothing(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"101": True}}}
    _cache_two_maps(monkeypatch, payload, payload, _DIFF_CHUNKINFO)
    capsys.readouterr()

    assert main(["diff", "--map1", "a", "--map2", "b"]) == 0

    out = capsys.readouterr().out
    assert "tasks        +0 -0" in out
    assert "bis picks" not in out


def test_diff_lists_one_branch(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _cache_two_maps(
        monkeypatch,
        {"chunks": {"unlocked": {"101": True}}},
        {"chunks": {"unlocked": {"102": True}}},
        _DIFF_CHUNKINFO,
    )
    capsys.readouterr()

    assert main(["diff", "--map1", "a", "--map2", "b", "tasks"]) == 0

    out = capsys.readouterr().out
    assert "+ Use beads" in out
    assert "- Use bones" in out
    # The other branches weren't computed, so they aren't reported as zeroes.
    assert "sources" not in out


def test_diff_rejects_an_unknown_branch(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"101": True}}}
    _cache_two_maps(monkeypatch, payload, payload, _DIFF_CHUNKINFO)
    capsys.readouterr()

    assert main(["diff", "--map1", "a", "--map2", "b", "nope"]) == 1
    assert "unknown branch 'nope'" in capsys.readouterr().err


def test_diff_export_json_to_stdout_replaces_the_summary(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _cache_two_maps(
        monkeypatch,
        {"chunks": {"unlocked": {"101": True}}},
        {"chunks": {"unlocked": {"102": True}}},
        _DIFF_CHUNKINFO,
    )
    capsys.readouterr()

    assert main(["diff", "--map1", "a", "--map2", "b", "--export-json", "-"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert (result["before_map"], result["after_map"]) == ("a", "b")
    assert result["tasks"]["Nonskill"]["added"] == {"Use beads": True}
    assert result["tasks"]["Nonskill"]["removed"] == ["Use bones"]


def test_diff_needs_both_maps() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["diff", "--map1", "a"])


def test_diff_without_a_cached_map_exits_one(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["diff", "--map1", "a", "--map2", "b"]) == 1
    assert "no cached data for map 'a'" in capsys.readouterr().err


def test_diff_against_a_saved_unlock_matches_what_unlock_reported(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The loop the two halves of this feature close: saving an unlock and then
    # diffing against it must reproduce the unlock's own numbers.
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "chunks": {"101": {"Monster": {"Goblin": True}}},
        "sections": {"101": {"0": ["100"]}},
        "drops": {"Goblin": {"Bones": {"1": "Always"}}},
        "challenges": {"Nonskill": {"Use bones": {"Items": ["Bones"]}}},
    }
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    main(["unlock", "--chunk", "101", "--cache-map", "Candidate", "--export-json", "-"])
    unlocked = json.loads(capsys.readouterr().out)

    main(["diff", "--map1", "fray", "--map2", "Candidate", "--export-json", "-"])
    difference = json.loads(capsys.readouterr().out)

    assert difference["tasks"]["Nonskill"]["added"] == unlocked["new_tasks"]["Nonskill"]
    assert difference["chunks"]["added"] == {"101": True}
    assert difference["tasks"]["Nonskill"]["removed"] == []


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
    # Sections read active -> completed -> obsolete.
    assert out.index("active   ") < out.index("completed ") < out.index("obsolete ")


def test_tasks_skill_category_strips_markup_from_every_section(
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
                "Chop a ~|regular tree|~": {"Level": 1, "Primary": True},
                "Chop a ~|magic tree|~": {"Level": 75, "Primary": True},
                "Chop a ~|yew tree|~": {"Level": 60, "Primary": True},
            }
        }
    }
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    write_blob("tasks_map", {"Chop a ~|regular tree|~": "t_1"}, "https://example/tasksMap.json")
    capsys.readouterr()

    assert main(["tasks", "Woodcutting"]) == 0

    out = capsys.readouterr().out
    assert "active   Chop a magic tree" in out
    assert "  Chop a regular tree" in out
    assert "  Chop a yew tree" in out
    assert "~|" not in out


def test_tasks_flat_category_strips_markup(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload: dict[str, Any] = {"chunks": {"unlocked": {}}}
    chunkinfo_data: dict[str, Any] = {"challenges": {"Quest": {"Complete ~|Dragon Slayer|~": {}}}}
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["tasks", "Quest"]) == 0

    out = capsys.readouterr().out
    assert "  Complete Dragon Slayer" in out
    assert "~|" not in out


def test_tasks_skill_category_reports_a_cached_active_task_match(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from fray_claude.cache import write_blob

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
    # Slot-prefixed and markup-free: the terminal never shows `~|...|~`.
    assert "[weapon] Obtain a rune scimitar" in out
    assert "~|" not in out


def test_tasks_bis_lists_this_chunks_completions_first(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
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
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["tasks", "BiS"]) == 0

    completed = capsys.readouterr().out.split("completed ", 1)[1].splitlines()[1:3]
    assert completed == [
        "  [weapon] Obtain a rune scimitar (Active)",
        "  [cape] Obtain a black cape",
    ]


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


def test_search_strips_markup_from_task_names_and_task_routes(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A task hit's own name and the `task:<category>` route behind an item
    that only exists as a challenge `Output` both carry challenge markup."""
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "chunks": {"100": {"Monster": {"Goblin": True}}},
        "challenges": {"Nonskill": {"Earn ~|Pizazz points|~": {"Output": "Pizazz points loot"}}},
    }
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["search", "pizazz"]) == 0

    out = capsys.readouterr().out
    assert "TASK     Earn Pizazz points" in out
    assert "task:Nonskill: Earn Pizazz points" in out
    assert "~|" not in out


def test_search_leaves_a_non_task_name_that_really_uses_tildes_alone(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`~ Uglug's stuffsies ~` is a real shop name, not markup - stripping
    is scoped to task names precisely so this survives."""
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "chunks": {"100": {"Shop": {"~ Uglug's stuffsies ~": True}}},
        "shopItems": {"~ Uglug's stuffsies ~": {"Rope": {}}},
    }
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["search", "uglug"]) == 0

    assert "~ Uglug's stuffsies ~" in capsys.readouterr().out


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


def test_tasks_overview_lists_the_other_categories(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload, chunkinfo_data = _other_payload()
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
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
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload, chunkinfo_data = _other_payload()
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["tasks", "Other"]) == 0

    out = capsys.readouterr().out
    assert "category Other (Extra)" in out
    assert "  Collection Log\n    Obtain a thing" in out
    assert "  Permanent Unlockables\n    Obtain a cape" in out


def test_tasks_accepts_extra_as_an_alias_for_other(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload, chunkinfo_data = _other_payload()
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["tasks", "Extra"]) == 0
    from_extra = capsys.readouterr().out

    assert main(["tasks", "other"]) == 0
    from_other = capsys.readouterr().out

    assert from_extra == from_other
    assert "category Other (Extra)" in from_extra


def test_tasks_other_category_export_json_keeps_the_real_key(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload, chunkinfo_data = _other_payload()
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["tasks", "Other", "--export-json", "-"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["category"] == "Extra"
    assert result["label"] == "Other"
    assert result["active_total"] == 1


def _neighbour_fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    # 101 and 356 are grid-adjacent to the unlocked 100 (±1 and ±256), and
    # both connect plainly back to it.
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "sections": {"101": {"0": ["100"]}, "356": {"0": ["100"]}},
        "chunks": {"101": {"Nickname": "Next Door"}, "356": {"Nickname": "Upstairs"}},
    }
    return payload, chunkinfo_data


def test_neighbours_lists_eligible_chunks_with_their_numbers(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload, chunkinfo_data = _neighbour_fixture()
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["neighbours"]) == 0

    out = capsys.readouterr().out
    assert "eligible chunks 2" in out
    # Number 1 is the highest chunk id (`sortSelectedChunks`).
    assert "1  356" in out
    assert "Upstairs" in out
    assert "via 100" in out


def test_neighbours_without_a_cached_map_exits_one(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["neighbours"]) == 1
    assert "no cached data for map 'fray'" in capsys.readouterr().err


def test_neighbours_export_json_to_stdout_replaces_the_summary(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload, chunkinfo_data = _neighbour_fixture()
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["neighbours", "--export-json", "-"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["map_id"] == "fray"
    assert result["unlocked_chunks"] == 1
    assert result["neighbours"] == [
        {
            "number": 1,
            "chunk_id": "356",
            "nickname": "Upstairs",
            "via_section": "0",
            "via_ref": "100",
        },
        {
            "number": 2,
            "chunk_id": "101",
            "nickname": "Next Door",
            "via_section": "0",
            "via_ref": "100",
        },
    ]


def test_neighbours_limit_caps_the_listing(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload, chunkinfo_data = _neighbour_fixture()
    _cache_map_and_chunkinfo(monkeypatch, payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["neighbours", "--limit", "1"]) == 0

    out = capsys.readouterr().out
    assert "1  356" in out
    assert "Next Door" not in out
    assert "... and 1 more (--limit 2 to see all)" in out


def test_neighbours_limit_defaults_to_showing_everything() -> None:
    args = build_parser().parse_args(["neighbours"])

    assert args.limit is None


# --- simulated map caches ----------------------------------------------------


def _cache_map_and_chunkinfo_blob(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any], chunkinfo_data: dict[str, Any]
) -> None:
    """Like `_cache_map_and_chunkinfo`, but writes the chunkinfo to the cache
    rather than monkeypatching the reader - `batch.run_one` resolves its own
    copy, which is the whole point of the worker design.
    """
    monkeypatch.delenv("FRAY_CHUNKINFO", raising=False)
    monkeypatch.setattr(
        "fray_claude.cli.fetch_map", lambda map_id, timeout=DEFAULT_TIMEOUT: payload
    )
    main(["fetch"])
    write_blob("chunkinfo", chunkinfo_data, "test")


def _simulatable(monkeypatch: pytest.MonkeyPatch) -> None:
    _cache_map_and_chunkinfo_blob(
        monkeypatch,
        {"chunks": {"unlocked": {"100": "100"}}},
        {"sections": {"101": {"0": ["100"]}, "102": {"0": ["101"]}}},
    )


def test_simulate_cache_map_writes_a_readable_map(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _simulatable(monkeypatch)
    capsys.readouterr()

    assert main(["simulate", "--rolls", "2", "--seed", "1", "--cache-map", "Demo"]) == 0

    out = capsys.readouterr().out
    assert "batch        Demo" in out
    assert "fray tasks --map Demo" in out
    assert (project / "cache" / "maps" / "simulated" / "Demo" / "run-001" / "map.json").is_file()

    # The saved state is a map like any other.
    assert main(["sections", "--map", "Demo"]) == 0
    assert "unlocked chunks    3" in capsys.readouterr().out


def test_simulate_cache_map_suffixes_a_taken_name(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _simulatable(monkeypatch)
    main(["simulate", "--rolls", "1", "--seed", "1", "--cache-map", "Demo"])
    capsys.readouterr()

    assert main(["simulate", "--rolls", "1", "--seed", "2", "--cache-map", "Demo"]) == 0

    out = capsys.readouterr().out
    assert "was taken; saved as 'Demo-2'" in out
    assert (project / "cache" / "maps" / "simulated" / "Demo-2").is_dir()


def test_simulate_runs_need_a_cache_to_go_into(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _simulatable(monkeypatch)
    capsys.readouterr()

    assert main(["simulate", "--rolls", "1", "--runs", "3"]) == 1
    assert "--runs needs --cache-map" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--rolls", "--runs", "--jobs"])
def test_simulate_rejects_counts_below_one(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], flag: str
) -> None:
    _simulatable(monkeypatch)
    capsys.readouterr()
    argv = ["simulate", "--rolls", "1", flag, "0"]

    assert main(argv) == 1
    assert f"{flag} must be at least 1" in capsys.readouterr().err


def test_simulate_export_json_describes_the_whole_batch(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _simulatable(monkeypatch)
    capsys.readouterr()

    assert (
        main(
            ["simulate", "--rolls", "1", "--runs", "2", "--seed", "3", "--cache-map", "D",
             "--export-json", "-"]
        )
        == 0
    )

    result = json.loads(capsys.readouterr().out)
    assert [run["run"] for run in result["runs"]] == ["run-001", "run-002"]
    assert result["seed"] == 3


def test_maps_lists_fetched_and_simulated_maps(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _simulatable(monkeypatch)
    main(["simulate", "--rolls", "1", "--seed", "1", "--cache-map", "Demo"])
    capsys.readouterr()

    assert main(["maps"]) == 0

    out = capsys.readouterr().out
    assert "fray" in out and "fetched" in out
    assert "Demo" in out and "simulated" in out


def test_maps_can_expand_runs_and_export_json(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _simulatable(monkeypatch)
    main(["simulate", "--rolls", "1", "--runs", "2", "--seed", "1", "--cache-map", "Demo"])
    capsys.readouterr()

    assert main(["maps", "list", "--runs", "--export-json", "-"]) == 0

    listed = json.loads(capsys.readouterr().out)["maps"]
    assert [entry["map_id"] for entry in listed] == [
        "fray",
        "Demo",
        "Demo/run-001",
        "Demo/run-002",
    ]


def test_maps_rm_removes_a_simulated_batch(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _simulatable(monkeypatch)
    main(["simulate", "--rolls", "1", "--seed", "1", "--cache-map", "Demo"])
    capsys.readouterr()

    assert main(["maps", "rm", "Demo"]) == 0
    assert not (project / "cache" / "maps" / "simulated" / "Demo").exists()


def test_maps_rm_guards_a_fetched_map(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _simulatable(monkeypatch)
    capsys.readouterr()

    assert main(["maps", "rm", "fray"]) == 1
    assert "--include-fetched" in capsys.readouterr().err
    assert (project / "cache" / "maps" / "fetched" / "fray.json").is_file()

    assert main(["maps", "rm", "fray", "--include-fetched"]) == 0
    assert not (project / "cache" / "maps" / "fetched" / "fray.json").exists()


def test_maps_clean_removes_only_simulations(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _simulatable(monkeypatch)
    main(["simulate", "--rolls", "1", "--seed", "1", "--cache-map", "Demo"])
    main(["simulate", "--rolls", "1", "--seed", "2", "--cache-map", "Other"])
    capsys.readouterr()

    assert main(["maps", "clean"]) == 0

    out = capsys.readouterr().out
    assert "removed 2 cached maps" in out
    assert (project / "cache" / "maps" / "fetched" / "fray.json").is_file()
    assert (project / "cache" / "reference" / "chunkinfo.json").is_file()
    assert list((project / "cache" / "maps" / "simulated").iterdir()) == []


def test_maps_clean_can_take_the_fetched_maps_too(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _simulatable(monkeypatch)
    main(["simulate", "--rolls", "1", "--seed", "1", "--cache-map", "Demo"])
    capsys.readouterr()

    assert main(["maps", "clean", "--include-fetched"]) == 0

    assert not (project / "cache" / "maps" / "fetched" / "fray.json").exists()
    # The 10MB blobs are never in scope: re-downloading them is the expensive part.
    assert (project / "cache" / "reference" / "chunkinfo.json").is_file()


def test_maps_on_an_empty_cache_says_so(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["maps"]) == 0
    assert "no cached maps" in capsys.readouterr().out


# --- the derived cache -------------------------------------------------------


def _derived_entries(project: Path) -> list[Path]:
    directory = project / "cache" / "derived"
    return sorted(directory.iterdir()) if directory.is_dir() else []


def test_a_second_command_reuses_the_first_ones_derivation(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The key is the derivation's *inputs*, so unrelated commands over the
    same state share one entry rather than each keeping their own."""
    _simulatable(monkeypatch)
    main(["tasks"])
    assert len(_derived_entries(project)) == 1
    capsys.readouterr()

    calls: list[int] = []
    monkeypatch.setattr(
        "fray_claude.derived_cache.derive",
        lambda *a, **k: calls.append(1),  # never reached on a hit
    )

    assert main(["sections"]) == 0
    assert main(["sources"]) == 0
    assert calls == []
    assert len(_derived_entries(project)) == 1


def test_recompute_ignores_the_cached_derivation(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _simulatable(monkeypatch)
    main(["tasks"])
    capsys.readouterr()
    fresh = main(["tasks", "--recompute", "--export-json", "-"])
    recomputed = capsys.readouterr().out

    cached = main(["tasks", "--export-json", "-"])

    assert (fresh, cached) == (0, 0)
    assert capsys.readouterr().out == recomputed


def test_a_changed_map_is_not_served_the_old_derivation(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The one failure that would matter: a re-fetch must invalidate."""
    _simulatable(monkeypatch)
    main(["sections"])
    capsys.readouterr()

    monkeypatch.setattr(
        "fray_claude.cli.fetch_map",
        lambda map_id, timeout=DEFAULT_TIMEOUT: {
            "chunks": {"unlocked": {"100": "100", "101": "101"}}
        },
    )
    main(["fetch"])
    capsys.readouterr()

    assert main(["sections"]) == 0
    assert "unlocked chunks    2" in capsys.readouterr().out
    assert len(_derived_entries(project)) == 2


def test_derived_list_summarises_the_cache(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _simulatable(monkeypatch)
    main(["tasks"])
    capsys.readouterr()

    assert main(["derived", "list", "--verbose"]) == 0

    out = capsys.readouterr().out
    assert "entries      1" in out
    assert ".pkl" in out


def test_derived_list_on_an_empty_cache_says_so(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["derived"]) == 0
    assert "no cached derivations" in capsys.readouterr().out


def test_derived_clean_all_empties_the_cache(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _simulatable(monkeypatch)
    main(["tasks"])
    capsys.readouterr()

    assert main(["derived", "clean", "--all"]) == 0

    assert "removed 1 cached derivations" in capsys.readouterr().out
    assert _derived_entries(project) == []


def test_derived_clean_keeps_recently_read_entries(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _simulatable(monkeypatch)
    main(["tasks"])
    capsys.readouterr()

    assert main(["derived", "clean"]) == 0

    assert "nothing to clean" in capsys.readouterr().out
    assert len(_derived_entries(project)) == 1


@pytest.mark.parametrize(
    ("behaviour", "expected"),
    [
        # The fixture leaves one candidate per roll, so all three runs walk the
        # same two states: start, +101, +102.
        ("all", 3),
        # Start and finish only - and the finish is the state the saved map
        # holds, so `--map S/run-001` is served from disk afterwards.
        ("extremities", 2),
        ("none", 0),
    ],
)
def test_cache_behaviour_decides_which_roll_states_are_kept(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    behaviour: str,
    expected: int,
) -> None:
    _simulatable(monkeypatch)
    capsys.readouterr()

    assert (
        main(
            ["simulate", "--rolls", "2", "--runs", "3", "--seed", "1",
             "--cache-map", "S", "--cache-behaviour", behaviour]
        )
        == 0
    )

    assert len(_derived_entries(project)) == expected


def test_simulate_caches_every_state_by_default(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _simulatable(monkeypatch)
    capsys.readouterr()

    assert main(["simulate", "--rolls", "2", "--seed", "1", "--cache-map", "S"]) == 0

    assert len(_derived_entries(project)) == 3


def test_a_simulated_maps_own_state_is_cached_by_its_run(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The point of always keeping the finishing state: the map the run saved
    is derived from it, so reading that map back costs nothing."""
    _simulatable(monkeypatch)
    main(["simulate", "--rolls", "2", "--seed", "1", "--cache-map", "S", "--cache-behaviour",
          "extremities"])
    capsys.readouterr()
    stored = len(_derived_entries(project))

    monkeypatch.setattr(
        "fray_claude.derived_cache.derive",
        lambda *a, **k: pytest.fail("the saved map's own state should already be cached"),
    )

    assert main(["tasks", "--map", "S"]) == 0
    assert len(_derived_entries(project)) == stored


# --- heuristics and estimate ------------------------------------------------


def _patch_wiki_sources(
    monkeypatch: pytest.MonkeyPatch,
    *,
    quest_pages: dict[str, str] | None = None,
    guides: dict[str, str] | None = None,
    sheet: str = '"Task","XP/Kill","Raw Kills/Hour"\n"Bats","5","800"\n',
) -> None:
    """Stand in for every network source `fray heuristics` reaches."""
    pages = {**(quest_pages or {}), **(guides or {})}
    monkeypatch.setattr(
        "fray_claude.remote.scrape.fetch_wiki_pages", lambda titles, timeout=DEFAULT_TIMEOUT: {
            title: pages[title] for title in titles if title in pages
        }
    )
    monkeypatch.setattr(
        "fray_claude.remote.scrape.fetch_wiki_page_titles",
        lambda prefix, timeout=DEFAULT_TIMEOUT: sorted(guides or {}),
    )
    monkeypatch.setattr(
        "fray_claude.remote.scrape.fetch_text", lambda url, timeout=DEFAULT_TIMEOUT, what="": sheet
    )


def test_heuristics_writes_the_config_and_reports_coverage(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    chunkinfo_data = {
        "challenges": {
            "Quest": {"~|Cook's Assistant|~ 1": {"BaseQuest": "Cook's Assistant"}},
            "Mining": {"Mine ~|sunstone rocks|~": {"Primary": True, "Level": 50}},
        },
        "drops": {"General Graardor": {"Bandos chestplate": {"1": "1/381"}}},
    }
    _cache_map_and_chunkinfo(monkeypatch, {"chunks": {"unlocked": {}}}, chunkinfo_data)
    _patch_wiki_sources(
        monkeypatch,
        quest_pages={"Cook's Assistant": "{{Quest details|length = Very Short}}"},
        guides={
            "Money making guide/Killing General Graardor": "{{Mmgtable|Activity = Killing "
            "[[General Graardor]]|kph = 27}}"
        },
    )
    capsys.readouterr()

    assert main(["heuristics"]) == 0

    out = capsys.readouterr().out
    assert "quest pages      1/1" in out
    assert "100% from the wiki" in out
    config = json.loads((project / "cache" / "reference" / "wiki_rates.json").read_text())["data"]
    assert config["quests"]["Cook's Assistant"]["hours"] == 0.17
    assert config["monsters"]["General Graardor"]["value"] == 27.0


def test_heuristics_survives_the_slayer_sheet_being_unavailable(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A third-party document; losing it should cost the Slayer bucket, not
    # the command, and must say so rather than pricing it at zero silently.
    _cache_map_and_chunkinfo(monkeypatch, {"chunks": {"unlocked": {}}}, {})
    _patch_wiki_sources(monkeypatch)
    monkeypatch.setattr(
        "fray_claude.remote.scrape.fetch_text",
        lambda url, timeout=DEFAULT_TIMEOUT, what="": (_ for _ in ()).throw(
            FetchError("HTTP 404 fetching slayer sheet")
        ),
    )
    capsys.readouterr()

    assert main(["heuristics"]) == 0

    assert "slayer sheet     unavailable" in capsys.readouterr().err


def _estimate_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    chunkinfo_data = {
        "chunks": {"100": {"Monster": {"Goblin": True}}},
        "drops": {"Goblin": {"Bones": {"1": "1/10"}}},
        "challenges": {"Extra": {"Obtain ~|bones|~": {"Items": ["Bones"]}}},
    }
    _cache_map_and_chunkinfo(monkeypatch, {"chunks": {"unlocked": {"100": True}}}, chunkinfo_data)


def test_estimate_reports_hours_per_bucket(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _estimate_fixture(monkeypatch)
    capsys.readouterr()

    assert main(["estimate"]) == 0

    out = capsys.readouterr().out
    assert "boss drops" in out and "skilling" in out and "total" in out


def test_estimate_works_without_a_scraped_config(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Everything falls back to a default, which announces itself - better than
    # refusing to answer until a ~18-request scrape has been run.
    _estimate_fixture(monkeypatch)
    capsys.readouterr()

    assert main(["estimate"]) == 0
    assert not (project / "cache" / "reference" / "wiki_rates.json").exists()


def test_estimate_rejects_an_unknown_bucket(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _estimate_fixture(monkeypatch)
    capsys.readouterr()

    assert main(["estimate", "nope"]) == 1
    assert "unknown bucket 'nope'" in capsys.readouterr().err


def test_estimate_export_json_to_stdout_replaces_the_summary(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _estimate_fixture(monkeypatch)
    capsys.readouterr()

    assert main(["estimate", "--export-json", "-"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert set(result["buckets"]) == {"quests", "boss drops", "activities", "skilling"}
    assert "unpriced" in result


def test_an_override_beats_the_scraped_rate(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _estimate_fixture(monkeypatch)
    overrides = project / "heuristics"
    overrides.mkdir()
    (overrides / "overrides.json").write_text(
        json.dumps({"monsters": {"Goblin": {"value": 1.0}}}), encoding="utf-8"
    )
    capsys.readouterr()

    main(["estimate", "--export-json", "-"])
    slow = json.loads(capsys.readouterr().out)

    (overrides / "overrides.json").write_text(
        json.dumps({"monsters": {"Goblin": {"value": 100.0}}}), encoding="utf-8"
    )
    main(["estimate", "--export-json", "-"])
    fast = json.loads(capsys.readouterr().out)

    assert fast["total_hours"] < slow["total_hours"]


def test_estimate_says_when_it_has_no_wiki_rates(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Without the scrape the total is quietly light - no superior mappings and
    # no slayer assignment sizes - so the command has to say so.
    _estimate_fixture(monkeypatch)
    capsys.readouterr()

    main(["estimate"])

    assert "no cached wiki rates" in capsys.readouterr().out


def test_estimate_is_quiet_about_rates_it_has(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _estimate_fixture(monkeypatch)
    write_blob("wiki_rates", {"monsters": {"Goblin": {"value": 100.0}}}, "test")
    capsys.readouterr()

    main(["estimate"])

    assert "no cached wiki rates" not in capsys.readouterr().out


def test_estimate_skilling_lists_every_slayer_master(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    chunkinfo_data = {
        "chunks": {"100": {"NPC": {"Vannaka": 1, "Mazchna": 1}}},
        "slayerMasterTasks": {
            "Vannaka": {"Bats": {"Weight": 1}},
            "Mazchna": {"Bats": {"Weight": 1}},
        },
    }
    _cache_map_and_chunkinfo(monkeypatch, {"chunks": {"unlocked": {"100": True}}}, chunkinfo_data)
    write_blob(
        "wiki_rates",
        {
            "slayer": {
                "Vannaka": {"Bats": {"mean_count": 100, "xp_per_kill": 50, "kills_per_hour": 100}},
                "Mazchna": {"Bats": {"mean_count": 100, "xp_per_kill": 10, "kills_per_hour": 100}},
            }
        },
        "test",
    )
    capsys.readouterr()

    assert main(["estimate", "skilling"]) == 0

    out = capsys.readouterr().out
    assert "slayer master" in out
    assert "Vannaka" in out and "Mazchna" in out
    assert "used by the estimate" in out
