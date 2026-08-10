"""Tests for `cli/maps.py`: `fray maps list|rm|clean`.

`project`, `cached_map`, `simulatable` and `derived_entries` come from
`conftest.py`, so the cache under test is a temporary one rather than the
project's own.
"""

from __future__ import annotations

import json
from pathlib import Path
from collections.abc import Callable

import pytest

from fray_claude.cli.app import main


def test_maps_rm_guards_a_fetched_map(
    project: Path, simulatable: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    simulatable()
    capsys.readouterr()

    assert main(["maps", "rm", "fray"]) == 1
    assert "--include-fetched" in capsys.readouterr().err
    assert (project / "cache" / "maps" / "fetched" / "fray.json").is_file()

    assert main(["maps", "rm", "fray", "--include-fetched"]) == 0
    assert not (project / "cache" / "maps" / "fetched" / "fray.json").exists()


def test_maps_on_an_empty_cache_says_so(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["maps"]) == 0
    assert "no cached maps" in capsys.readouterr().out
