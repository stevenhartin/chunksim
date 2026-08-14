"""Tests for `cli/diff.py`: two maps, both directions.

`project`, `cached_map`, `simulatable` and `derived_entries` come from
`conftest.py`, so the cache under test is a temporary one rather than the
project's own.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from chunksim.remote.api import DEFAULT_TIMEOUT
from chunksim.cli.app import build_parser, main


_DIFF_CHUNKINFO: dict[str, Any] = {
    "chunks": {"101": {"Monster": {"Goblin": True}}, "102": {"Monster": {"Imp": True}}},
    "drops": {"Goblin": {"Bones": {"1": "Always"}}, "Imp": {"Beads": {"1": "Always"}}},
    "challenges": {
        "Nonskill": {"Use bones": {"Items": ["Bones"]}, "Use beads": {"Items": ["Beads"]}}
    },
}


def _cache_two_maps(
    monkeypatch: pytest.MonkeyPatch,
    first: dict[str, Any],
    second: dict[str, Any],
    chunkinfo_data: dict[str, Any],
) -> None:
    payloads = {"a": first, "b": second}
    monkeypatch.setattr(
        "chunksim.cli.io_commands.fetch_map", lambda map_id, timeout=DEFAULT_TIMEOUT: payloads[map_id]
    )
    main(["fetch", "--map", "a"])
    main(["fetch", "--map", "b"])
    # **Two readers, and both must be patched** - see `conftest.cached_map`.
    # This one cannot use that fixture: it caches two maps under two names,
    # which is the whole point of `chunksim diff`.
    for module in ("io_commands", "common"):
        monkeypatch.setattr(
            f"chunksim.cli.{module}.read_chunkinfo",
            lambda override=None, root=None: chunkinfo_data,
        )


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
    # `chunksim unlock` structurally cannot report.
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
