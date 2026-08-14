"""Tests for `cli/unlock.py`: what one candidate chunk adds, and saving it.

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

from chunksim.cli.app import main


def test_unlock_reports_new_tasks_and_sections(
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

    assert main(["unlock", "--chunk", "101"]) == 0

    out = capsys.readouterr().out
    assert "chunk        101" in out
    assert "new tasks    1" in out
    assert "Nonskill     1" in out


def test_unlock_without_a_cached_map_exits_one(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["unlock", "--chunk", "101"]) == 1
    assert "no maps cached" in capsys.readouterr().err


def test_unlock_export_json_to_stdout_replaces_the_summary(
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

    assert main(["unlock", "--chunk", "101", "--export-json", "-"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["chunk_id"] == "101"
    assert result["new_tasks"] == {"Nonskill": {"Use bones": True}}


def test_unlock_cache_map_suffixes_a_name_already_taken(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    cached_map(payload, {"sections": {"101": {"0": ["100"]}}})
    capsys.readouterr()

    main(["unlock", "--chunk", "101", "--cache-map", "Candidate"])
    capsys.readouterr()
    assert main(["unlock", "--chunk", "101", "--cache-map", "Candidate"]) == 0

    out = capsys.readouterr().out
    assert "'Candidate' was taken; saved as 'Candidate-2'" in out
    assert (project / "cache" / "maps" / "edited" / "Candidate-2" / "run-001" / "map.json").is_file()


def test_unlock_cache_map_export_json_reports_the_name(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    cached_map(payload, {"sections": {"101": {"0": ["100"]}}})
    capsys.readouterr()

    assert main(["unlock", "--chunk", "101", "--cache-map", "Kept", "--export-json", "-"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["cached_map"] == "Kept"


def test_diff_against_a_saved_unlock_matches_what_unlock_reported(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
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
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    main(["unlock", "--chunk", "101", "--cache-map", "Candidate", "--export-json", "-"])
    unlocked = json.loads(capsys.readouterr().out)

    main(["diff", "--map1", "fray", "--map2", "Candidate", "--export-json", "-"])
    difference = json.loads(capsys.readouterr().out)

    assert difference["tasks"]["Nonskill"]["added"] == unlocked["new_tasks"]["Nonskill"]
    assert difference["chunks"]["added"] == {"101": True}
    assert difference["tasks"]["Nonskill"]["removed"] == []
