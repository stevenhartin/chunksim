"""Tests for `cli/neighbours.py`: eligibility and the canvas numbering.

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

from fray_claude.cli.app import build_parser, main


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
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload, chunkinfo_data = _neighbour_fixture()
    cached_map(payload, chunkinfo_data)
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
    assert "no maps cached" in capsys.readouterr().err


def test_neighbours_export_json_to_stdout_replaces_the_summary(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload, chunkinfo_data = _neighbour_fixture()
    cached_map(payload, chunkinfo_data)
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
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload, chunkinfo_data = _neighbour_fixture()
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["neighbours", "--limit", "1"]) == 0

    out = capsys.readouterr().out
    assert "1  356" in out
    assert "Next Door" not in out
    assert "... and 1 more (--limit 2 to see all)" in out


def test_neighbours_limit_defaults_to_showing_everything() -> None:
    args = build_parser().parse_args(["neighbours"])

    assert args.limit is None
