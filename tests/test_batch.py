"""Tests for the batch driver: seeding, persistence, and parallel equivalence.

Every test builds a tiny hand-made chunkinfo blob in a `tmp_path` root and
passes that root explicitly, so nothing here reads the project's own `cache/`
or depends on the working directory - which is also what lets the `--jobs 2`
test work, since a worker process resolves its inputs from the spec rather
than from where it happened to start.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fray_claude.batch import derive_seeds, run_batch
from fray_claude.cache import (
    BATCH_META_FILE_NAME,
    read_cache,
    read_sim_batch,
    sims_root,
    write_blob,
)
from fray_claude.chunkinfo import ChunkInfo
from fray_claude.derived_cache import CacheBehaviour
from fray_claude.pipeline import load_map_state
from fray_claude.simulate import simulate_rolls

#: 100 starts unlocked; 99/101/356 are its grid neighbours (id +/- 1, +/- 256)
#: and each declares a connection back to it, so a roll has three candidates
#: and different seeds visibly diverge.
_CHUNKINFO: dict[str, Any] = {
    "sections": {
        "99": {"0": ["100"]},
        "101": {"0": ["100"]},
        "356": {"0": ["100"]},
        "98": {"0": ["99"]},
        "102": {"0": ["101"]},
        "612": {"0": ["356"]},
    }
}

_PAYLOAD: dict[str, Any] = {"chunks": {"unlocked": {"100": "100"}}}


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A cache root holding just enough chunkinfo to roll against."""
    monkeypatch.delenv("FRAY_CHUNKINFO", raising=False)
    write_blob("chunkinfo", _CHUNKINFO, "test", root=tmp_path)
    return tmp_path


def _rolls(root: Path, name: str) -> list[list[str]]:
    summary = read_sim_batch(name, root)
    return [run["rolls"] for run in summary["runs"]]


def test_a_batch_writes_one_run_directory_per_run(root: Path) -> None:
    batch = run_batch(
        name="Demo", payload=_PAYLOAD, base_map="fray", rolls=2, runs=3, seed=7, root=root
    )

    assert [run.name for run in batch.runs] == ["run-001", "run-002", "run-003"]
    for run in batch.runs:
        directory = batch.directory / run.name
        assert (directory / "map.json").is_file()
        assert (directory / "rolls.json").is_file()
        assert (directory / "run.json").is_file()
    assert (batch.directory / BATCH_META_FILE_NAME).is_file()


def test_a_cached_run_reads_back_as_a_map_with_its_rolls_applied(root: Path) -> None:
    batch = run_batch(
        name="Demo", payload=_PAYLOAD, base_map="fray", rolls=2, runs=1, seed=7, root=root
    )
    rolled = batch.runs[0].rolls

    envelope = read_cache("Demo/run-001", root)
    unlocked = envelope["data"]["chunks"]["unlocked"]

    assert envelope["is_simulated"] is True
    assert set(unlocked) == {"100", *rolled}
    # Stored in the payload's own `{id: id}` form, not as booleans.
    assert all(unlocked[chunk] == chunk for chunk in rolled)


def test_a_single_run_batch_is_readable_by_its_bare_name(root: Path) -> None:
    run_batch(name="Demo", payload=_PAYLOAD, base_map="fray", rolls=1, runs=1, seed=7, root=root)

    assert read_cache("Demo", root)["map_id"] == "Demo/run-001"


def test_the_same_seed_reproduces_the_same_rolls(root: Path) -> None:
    first = run_batch(
        name="A", payload=_PAYLOAD, base_map="fray", rolls=3, runs=3, seed=99, root=root
    )
    second = run_batch(
        name="B", payload=_PAYLOAD, base_map="fray", rolls=3, runs=3, seed=99, root=root
    )

    assert [run.rolls for run in first.runs] == [run.rolls for run in second.runs]


def test_each_run_in_a_batch_gets_its_own_seed(root: Path) -> None:
    batch = run_batch(
        name="Demo", payload=_PAYLOAD, base_map="fray", rolls=1, runs=4, seed=7, root=root
    )

    seeds = [run.seed for run in batch.runs]
    assert len(set(seeds)) == 4


def test_a_recorded_run_seed_reproduces_that_run_on_its_own(root: Path) -> None:
    """The point of recording per-run seeds: any one run is reproducible
    without replaying the batch it came from."""
    batch = run_batch(
        name="Demo", payload=_PAYLOAD, base_map="fray", rolls=3, runs=3, seed=7, root=root
    )
    target = batch.runs[2]

    state, unlocked = load_map_state(_PAYLOAD, ChunkInfo(_CHUNKINFO))
    ledger = simulate_rolls(state, unlocked, rolls=3, seed=target.seed)

    assert target.rolls
    assert tuple(record.chunk_id for record in ledger) == target.rolls


def test_jobs_changes_where_runs_execute_and_nothing_else(root: Path) -> None:
    """The parallelism guarantee: `--jobs` must not move a single roll."""
    serial = run_batch(
        name="Serial", payload=_PAYLOAD, base_map="fray", rolls=3, runs=4, seed=5, jobs=1, root=root
    )
    parallel = run_batch(
        name="Pool", payload=_PAYLOAD, base_map="fray", rolls=3, runs=4, seed=5, jobs=2, root=root
    )

    assert [(r.name, r.seed, r.rolls) for r in serial.runs] == [
        (r.name, r.seed, r.rolls) for r in parallel.runs
    ]
    assert _rolls(root, "Serial") == _rolls(root, "Pool")


def test_a_name_clash_saves_alongside_rather_than_overwriting(root: Path) -> None:
    first = run_batch(
        name="Demo", payload=_PAYLOAD, base_map="fray", rolls=1, runs=1, seed=1, root=root
    )
    second = run_batch(
        name="Demo", payload=_PAYLOAD, base_map="fray", rolls=1, runs=1, seed=2, root=root
    )

    assert (first.name, second.name) == ("Demo", "Demo-2")
    assert read_cache("Demo", root)["simulation"]["seed"] == first.runs[0].seed
    assert read_cache("Demo-2", root)["simulation"]["seed"] == second.runs[0].seed


def test_an_interrupted_batch_still_lists_and_reads_its_runs(root: Path) -> None:
    """No `batch.json` means the parent died mid-batch; the runs it did finish
    are complete maps and must stay usable."""
    batch = run_batch(
        name="Demo", payload=_PAYLOAD, base_map="fray", rolls=1, runs=2, seed=7, root=root
    )
    (batch.directory / BATCH_META_FILE_NAME).unlink()

    summary = read_sim_batch("Demo", root)

    assert summary["complete"] is False
    assert [run["run"] for run in summary["runs"]] == ["run-001", "run-002"]
    assert read_cache("Demo/run-002", root)["is_simulated"] is True


def test_the_ledger_is_written_alongside_the_payload(root: Path) -> None:
    batch = run_batch(
        name="Demo", payload=_PAYLOAD, base_map="fray", rolls=2, runs=1, seed=7, root=root
    )

    ledger = json.loads((batch.directory / "run-001" / "rolls.json").read_text(encoding="utf-8"))

    assert [entry["chunk_id"] for entry in ledger["rolls"]] == list(batch.runs[0].rolls)
    assert [entry["order"] for entry in ledger["rolls"]] == [1, 2]


def test_batch_metadata_records_every_run_for_later_reduction(root: Path) -> None:
    """`batch.json` is the analysis surface: one small read answers "how often
    was chunk X rolled" without opening a single payload."""
    batch = run_batch(
        name="Demo", payload=_PAYLOAD, base_map="fray", rolls=3, runs=5, seed=7, root=root
    )
    summary = json.loads(
        (batch.directory / BATCH_META_FILE_NAME).read_text(encoding="utf-8")
    )

    assert summary["base_map"] == "fray"
    assert summary["rolls_requested"] == 3
    assert [run["rolls"] for run in summary["runs"]] == [list(r.rolls) for r in batch.runs]


def test_derive_seeds_is_deterministic_and_distinct() -> None:
    assert derive_seeds(7, 3) == derive_seeds(7, 3)
    assert derive_seeds(7, 3) != derive_seeds(8, 3)
    assert len(set(derive_seeds(7, 50))) == 50


def test_an_unseeded_batch_still_records_the_seeds_it_used(root: Path) -> None:
    batch = run_batch(
        name="Demo", payload=_PAYLOAD, base_map="fray", rolls=1, runs=2, seed=None, root=root
    )

    assert all(isinstance(run.seed, int) for run in batch.runs)
    assert json.loads(
        (sims_root(root) / "Demo" / BATCH_META_FILE_NAME).read_text(encoding="utf-8")
    )["seed"] is None


@pytest.mark.parametrize(("rolls", "runs", "jobs"), [(0, 1, 1), (1, 0, 1), (1, 1, 0)])
def test_batch_rejects_nonsense_counts(root: Path, rolls: int, runs: int, jobs: int) -> None:
    with pytest.raises(ValueError):
        run_batch(
            name="Demo",
            payload=_PAYLOAD,
            base_map="fray",
            rolls=rolls,
            runs=runs,
            jobs=jobs,
            root=root,
        )


def test_cache_behaviour_reaches_the_workers(root: Path) -> None:
    """It travels in the `RunSpec`, so it has to survive being pickled into a
    worker process - `--jobs` must not quietly change what gets stored."""
    run_batch(
        name="Kept",
        payload=_PAYLOAD,
        base_map="fray",
        rolls=2,
        runs=2,
        jobs=2,
        seed=7,
        root=root,
        cache_behaviour=CacheBehaviour.NONE,
    )
    assert not (root / "cache" / "derived").exists()

    run_batch(
        name="Stored",
        payload=_PAYLOAD,
        base_map="fray",
        rolls=2,
        runs=2,
        jobs=2,
        seed=7,
        root=root,
        cache_behaviour=CacheBehaviour.ALL,
    )
    assert list((root / "cache" / "derived").iterdir())


def test_caching_states_does_not_change_the_rolls(root: Path) -> None:
    """The guarantee that matters: a cached state is the same state."""
    uncached = run_batch(
        name="Cold", payload=_PAYLOAD, base_map="fray", rolls=3, runs=3, seed=11,
        root=root, cache_behaviour=CacheBehaviour.NONE,
    )
    warm = run_batch(
        name="Warm", payload=_PAYLOAD, base_map="fray", rolls=3, runs=3, seed=11,
        root=root, cache_behaviour=CacheBehaviour.ALL,
    )
    # Third time every state is a hit rather than a computation.
    reused = run_batch(
        name="Reused", payload=_PAYLOAD, base_map="fray", rolls=3, runs=3, seed=11,
        root=root, cache_behaviour=CacheBehaviour.ALL,
    )

    assert [r.rolls for r in uncached.runs] == [r.rolls for r in warm.runs]
    assert [r.rolls for r in uncached.runs] == [r.rolls for r in reused.runs]
