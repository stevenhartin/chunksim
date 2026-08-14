"""Tests for `cli/io.py`: `fetch`, `show`, `chunkinfo` and `heuristics`.

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

from fray_claude.remote.api import DEFAULT_TIMEOUT, FetchError
from fray_claude.cli.app import main


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


def test_fetch_writes_the_cache(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch_map(map_id: str, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
        return {"chunks": {"unlocked": {"50_50": True}}}

    monkeypatch.setattr("fray_claude.cli.io_commands.fetch_map", fake_fetch_map)

    assert main(["fetch", "--map", "fray"]) == 0
    assert (project / "cache" / "maps" / "fetched" / "fray.json").is_file()


def test_show_summarises_the_cached_map(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {
        "chunks": {"unlocked": {"50_50": True, "50_51": True}},
        "rules": {"All Shops": True, "Boosting": False},
    }
    monkeypatch.setattr(
        "fray_claude.cli.io_commands.fetch_map", lambda map_id, timeout=DEFAULT_TIMEOUT: payload
    )
    main(["fetch", "--map", "fray"])
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
        "fray_claude.cli.io_commands.fetch_map",
        lambda map_id, timeout=DEFAULT_TIMEOUT: {"chunks": {"unlocked": {"50_50": True}}},
    )
    main(["fetch", "--map", "fray"])
    capsys.readouterr()

    monkeypatch.setattr("fray_claude.costing.dps_bridge.library_version", lambda: "9.9.9")
    main(["show"])
    assert "dps calc       osrs-dps 9.9.9" in capsys.readouterr().out

    monkeypatch.setattr("fray_claude.costing.dps_bridge.library_version", lambda: None)
    main(["show"])
    assert "dps calc       not installed" in capsys.readouterr().out


def test_show_without_a_cache_exits_one(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["show"]) == 1
    assert "no maps cached" in capsys.readouterr().err


def test_fetch_failure_exits_one(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_fetch_map(map_id: str, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
        raise FetchError(f"no such map: {map_id!r}")

    monkeypatch.setattr("fray_claude.cli.io_commands.fetch_map", fake_fetch_map)

    assert main(["fetch", "--map", "nope"]) == 1
    # `endswith` rather than `==`: the provenance line shares this stream.
    assert capsys.readouterr().err.endswith("error: no such map: 'nope'\n")


def test_chunkinfo_fetches_and_caches_both_blobs(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "fray_claude.cli.io_commands.fetch_chunkinfo", lambda timeout=DEFAULT_TIMEOUT: {"chunks": {}}
    )
    monkeypatch.setattr(
        "fray_claude.cli.io_commands.fetch_tasks_map",
        lambda timeout=DEFAULT_TIMEOUT: {"Obtain a whip": "t_1"},
    )

    assert main(["chunkinfo"]) == 0
    assert (project / "cache" / "reference" / "chunkinfo.json").is_file()
    assert (project / "cache" / "reference" / "tasks_map.json").is_file()


def test_a_changed_map_is_not_served_the_old_derivation(
    project: Path, simulatable: Callable[[], None],
    derived_entries: Callable[[Path], list[Path]],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The one failure that would matter: a re-fetch must invalidate."""
    simulatable()
    main(["sections"])
    capsys.readouterr()

    monkeypatch.setattr(
        "fray_claude.cli.io_commands.fetch_map",
        lambda map_id, timeout=DEFAULT_TIMEOUT: {
            "chunks": {"unlocked": {"100": "100", "101": "101"}}
        },
    )
    main(["fetch", "--map", "fray"])
    capsys.readouterr()

    assert main(["sections"]) == 0
    assert "unlocked chunks    2" in capsys.readouterr().out
    assert len(derived_entries(project)) == 2


def test_heuristics_writes_the_config_and_reports_coverage(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    chunkinfo_data = {
        "challenges": {
            "Quest": {"~|Cook's Assistant|~ 1": {"BaseQuest": "Cook's Assistant"}},
            "Mining": {"Mine ~|sunstone rocks|~": {"Primary": True, "Level": 50}},
        },
        "drops": {"General Graardor": {"Bandos chestplate": {"1": "1/381"}}},
    }
    cached_map({"chunks": {"unlocked": {}}}, chunkinfo_data)
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
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A third-party document; losing it should cost the Slayer bucket, not
    # the command, and must say so rather than pricing it at zero silently.
    cached_map({"chunks": {"unlocked": {}}}, {})
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
