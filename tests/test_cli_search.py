"""Tests for `cli/search.py`: the world-wide index behind `fray search`.

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

from fray_claude.cli.app import main


def test_search_reports_hits(
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

    assert main(["search", "bones"]) == 0

    out = capsys.readouterr().out
    assert "ITEM     Bones  [available]" in out
    assert "drop: Goblin" in out


def test_search_strips_markup_from_task_names_and_task_routes(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A task hit's own name and the `task:<category>` route behind an item
    that only exists as a challenge `Output` both carry challenge markup."""
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "chunks": {"100": {"Monster": {"Goblin": True}}},
        "challenges": {"Nonskill": {"Earn ~|Pizazz points|~": {"Output": "Pizazz points loot"}}},
    }
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["search", "pizazz"]) == 0

    out = capsys.readouterr().out
    assert "TASK     Earn Pizazz points" in out
    assert "task:Nonskill: Earn Pizazz points" in out
    assert "~|" not in out


def test_search_leaves_a_non_task_name_that_really_uses_tildes_alone(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`~ Uglug's stuffsies ~` is a real shop name, not markup - stripping
    is scoped to task names precisely so this survives."""
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "chunks": {"100": {"Shop": {"~ Uglug's stuffsies ~": True}}},
        "shopItems": {"~ Uglug's stuffsies ~": {"Rope": {}}},
    }
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["search", "uglug"]) == 0

    assert "~ Uglug's stuffsies ~" in capsys.readouterr().out


def test_search_type_filters_results(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "chunks": {"100": {"Monster": {"Whip seller": True}}},
        "drops": {"Whip seller": {"Whip": {"1": "Always"}}},
    }
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["search", "whip", "--type", "monster"]) == 0

    out = capsys.readouterr().out
    assert "MONSTER  Whip seller" in out
    assert "ITEM" not in out


def test_search_without_a_cached_map_exits_one(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["search", "whip"]) == 1
    assert "no maps cached" in capsys.readouterr().err


def test_search_export_json_to_stdout_replaces_the_summary(
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

    assert main(["search", "bones", "--export-json", "-"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["query"] == "bones"
    assert result["hits"][0]["name"] == "Bones"
    assert result["hits"][0]["available"] is True
