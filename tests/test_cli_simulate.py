"""Tests for `cli/simulate.py`: rolls, runs, jobs and what lands in the cache.

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


def test_simulate_reports_each_roll(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {"sections": {"101": {"0": ["100"]}}}
    cached_map(payload, chunkinfo_data)
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
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {
        "sections": {
            "101": {"0": ["100"]},
            "102": {"0": ["100"]},
            "103": {"0": ["100"]},
        }
    }
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    main(["simulate", "--rolls", "3", "--seed", "9", "--export-json", "-"])
    first = json.loads(capsys.readouterr().out)

    main(["simulate", "--rolls", "3", "--seed", "9", "--export-json", "-"])
    second = json.loads(capsys.readouterr().out)

    assert first["rolls"] == second["rolls"]


def test_simulate_export_json_to_stdout_replaces_the_summary(
    project: Path, cached_map: Callable[[dict[str, Any], dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"chunks": {"unlocked": {"100": True}}}
    chunkinfo_data = {"sections": {"101": {"0": ["100"]}}}
    cached_map(payload, chunkinfo_data)
    capsys.readouterr()

    assert main(["simulate", "--rolls", "1", "--seed", "1", "--export-json", "-"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["seed"] == 1
    assert result["rolls_requested"] == 1
    assert [r["chunk_id"] for r in result["rolls"]] == ["101"]


def test_simulate_cache_map_suffixes_a_taken_name(
    project: Path, simulatable: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    simulatable()
    main(["simulate", "--rolls", "1", "--seed", "1", "--cache-map", "Demo"])
    capsys.readouterr()

    assert main(["simulate", "--rolls", "1", "--seed", "2", "--cache-map", "Demo"]) == 0

    out = capsys.readouterr().out
    assert "was taken; saved as 'Demo-2'" in out
    assert (project / "cache" / "maps" / "simulated" / "Demo-2").is_dir()


def test_simulate_runs_need_a_cache_to_go_into(
    project: Path, simulatable: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    simulatable()
    capsys.readouterr()

    assert main(["simulate", "--rolls", "1", "--runs", "3"]) == 1
    assert "--runs needs --cache-map" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--rolls", "--runs"])
def test_simulate_rejects_counts_below_one(
    project: Path, simulatable: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], flag: str
) -> None:
    simulatable()
    capsys.readouterr()
    argv = ["simulate", "--rolls", "1", flag, "0"]

    assert main(argv) == 1
    assert f"{flag} must be at least 1" in capsys.readouterr().err


def test_simulate_reads_jobs_zero_as_every_core(
    project: Path, simulatable: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """**Zero is the default and means "use the machine", not "no workers".**

    A run is tens of seconds of `derive` and the runs are independent, so
    somebody who typed the command wants their cores; `--jobs 1` is how you
    ask for one process back. That makes zero the one count here that is not
    nonsense, which is why it is out of the rejection list above.
    """
    simulatable()
    capsys.readouterr()

    assert main(["simulate", "--rolls", "1", "--jobs", "0"]) == 0

    assert main(["simulate", "--rolls", "1", "--jobs", "-1"]) == 1
    assert "--jobs must not be negative" in capsys.readouterr().err


def test_simulate_export_json_describes_the_whole_batch(
    project: Path, simulatable: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    simulatable()
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
    project: Path, simulatable: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    simulatable()
    main(["simulate", "--rolls", "1", "--seed", "1", "--cache-map", "Demo"])
    capsys.readouterr()

    assert main(["maps"]) == 0

    out = capsys.readouterr().out
    assert "fray" in out and "fetched" in out
    assert "Demo" in out and "simulated" in out


def test_maps_can_expand_runs_and_export_json(
    project: Path, simulatable: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    simulatable()
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
    project: Path, simulatable: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    simulatable()
    main(["simulate", "--rolls", "1", "--seed", "1", "--cache-map", "Demo"])
    capsys.readouterr()

    assert main(["maps", "rm", "Demo"]) == 0
    assert not (project / "cache" / "maps" / "simulated" / "Demo").exists()


def test_maps_clean_removes_only_simulations(
    project: Path, simulatable: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    simulatable()
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
    project: Path, simulatable: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    simulatable()
    main(["simulate", "--rolls", "1", "--seed", "1", "--cache-map", "Demo"])
    capsys.readouterr()

    assert main(["maps", "clean", "--include-fetched"]) == 0

    assert not (project / "cache" / "maps" / "fetched" / "fray.json").exists()
    # The 10MB blobs are never in scope: re-downloading them is the expensive part.
    assert (project / "cache" / "reference" / "chunkinfo.json").is_file()


@pytest.mark.parametrize(
    ("behaviour", "expected"),
    [
        # **Two, not three, because carrying is the default.** The fixture
        # leaves one candidate per roll, so all three runs walk the same
        # states - start, +101, +102 - but a carried run only ever checks the
        # state it finishes on, so that and the start are the only two this
        # project is entitled to persist. `--no-carry-areas` derives every
        # roll the ordinary way and keeps all three; see `pipeline.derive`.
        ("all", 2),
        # Start and finish only - and the finish is the state the saved map
        # holds, so `--map S/run-001` is served from disk afterwards.
        ("extremities", 2),
        ("none", 0),
    ],
)
def test_cache_behaviour_decides_which_roll_states_are_kept(
    project: Path,
    simulatable: Callable[[], None],
    derived_entries: Callable[[Path], list[Path]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    behaviour: str,
    expected: int,
) -> None:
    simulatable()
    capsys.readouterr()

    assert (
        main(
            ["simulate", "--rolls", "2", "--runs", "3", "--seed", "1",
             "--cache-map", "S", "--cache-behaviour", behaviour]
        )
        == 0
    )

    assert len(derived_entries(project)) == expected


def test_simulate_caches_every_state_when_it_derives_them_cold(
    project: Path, simulatable: Callable[[], None],
    derived_entries: Callable[[Path], list[Path]],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--no-carry-areas` is what "keep every state" now means.

    Carrying trades those per-roll entries for roughly half the run time: only
    the finishing state is checked against a cold derivation, so it is the
    only one worth writing under a key that promises the cold answer. Anything
    that will later *reprice* a run wants them, since `batch.warm_slice` reads
    exactly these back - so that is the case for turning carrying off.
    """
    simulatable()
    capsys.readouterr()

    argv = ["simulate", "--rolls", "2", "--seed", "1", "--cache-map", "S"]
    assert main([*argv, "--no-carry-areas"]) == 0

    assert len(derived_entries(project)) == 3
