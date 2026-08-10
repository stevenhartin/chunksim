"""Tests for `cli/derived.py`: `fray derived list|clean`.

`project`, `cached_map`, `simulatable` and `derived_entries` come from
`conftest.py`, so the cache under test is a temporary one rather than the
project's own.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fray_claude.cli.app import main


def test_derived_list_on_an_empty_cache_says_so(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["derived"]) == 0
    assert "no cached derivations" in capsys.readouterr().out
