"""Tests for `cli/estimate.py`: buckets, warnings and the DPS layer.

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

from chunksim.store.cache import write_blob
from chunksim.cli.app import main


def _estimate_fixture(
    cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
) -> None:
    chunkinfo_data = {
        "chunks": {"100": {"Monster": {"Goblin": True}}},
        "drops": {"Goblin": {"Bones": {"1": "1/10"}}},
        "challenges": {"Extra": {"Obtain ~|bones|~": {"Items": ["Bones"]}}},
    }
    cached_map({"chunks": {"unlocked": {"100": True}}}, chunkinfo_data)


def test_estimate_reports_hours_per_bucket(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _estimate_fixture(cached_map)
    capsys.readouterr()

    assert main(["estimate"]) == 0

    out = capsys.readouterr().out
    assert "boss drops" in out and "skilling" in out and "total" in out


def test_estimate_works_without_a_scraped_config(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Everything falls back to a default, which announces itself - better than
    # refusing to answer until a ~18-request scrape has been run.
    _estimate_fixture(cached_map)
    capsys.readouterr()

    assert main(["estimate"]) == 0
    assert not (project / "cache" / "reference" / "wiki_rates.json").exists()


def test_estimate_rejects_an_unknown_bucket(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _estimate_fixture(cached_map)
    capsys.readouterr()

    assert main(["estimate", "nope"]) == 1
    assert "unknown bucket 'nope'" in capsys.readouterr().err


def test_estimate_export_json_to_stdout_replaces_the_summary(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _estimate_fixture(cached_map)
    capsys.readouterr()

    assert main(["estimate", "--export-json", "-"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert set(result["buckets"]) == {
        "quests", "boss drops", "monster drops", "activities", "skilling",
    }
    assert "unpriced" in result


def test_an_override_beats_the_scraped_rate(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _estimate_fixture(cached_map)
    # Where `cache.overrides_path` looks inside a checkout - the corrections
    # ship with the code now, so a throwaway checkout carries its own.
    overrides = project / "src" / "chunksim" / "heuristics"
    overrides.mkdir(parents=True, exist_ok=True)
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
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Without the scrape the total is quietly light - no superior mappings and
    # no slayer assignment sizes - so the command has to say so.
    _estimate_fixture(cached_map)
    capsys.readouterr()

    main(["estimate"])

    assert "no cached wiki rates" in capsys.readouterr().out


def test_estimate_is_quiet_about_rates_it_has(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _estimate_fixture(cached_map)
    write_blob("wiki_rates", {"monsters": {"Goblin": {"value": 100.0}}}, "test")
    capsys.readouterr()

    main(["estimate"])

    assert "no cached wiki rates" not in capsys.readouterr().out


def test_estimate_skilling_lists_every_slayer_master(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    chunkinfo_data = {
        "chunks": {"100": {"NPC": {"Vannaka": 1, "Mazchna": 1}}},
        "slayerMasterTasks": {
            "Vannaka": {"Bats": {"Weight": 1}},
            "Mazchna": {"Bats": {"Weight": 1}},
        },
    }
    cached_map({"chunks": {"unlocked": {"100": True}}}, chunkinfo_data)
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
