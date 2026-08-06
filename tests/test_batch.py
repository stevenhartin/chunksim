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

from fray_claude.batch import derive_seeds, run_batch, save_unlock
from fray_claude.cache import (
    BATCH_META_FILE_NAME,
    UNLOCKED,
    CacheMissError,
    read_batch,
    read_cache,
    read_timeline,
    read_sim_batch,
    sims_root,
    write_blob,
)
from fray_claude.chunkinfo import ChunkInfo
from fray_claude.derived_cache import CacheBehaviour
from fray_claude.pipeline import load_map_state
from fray_claude.simulate import simulate_rolls
from fray_claude.unlock import UnlockDelta

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


def test_every_run_of_a_batch_carries_the_same_batch_id(root: Path) -> None:
    """**What makes several runs one job.**

    The directory name cannot answer it: a clash renames the batch and a
    rename severs the link. The id is minted before any run starts and written
    into every one of them, so a run answers on its own - and two batches from
    the same base map and the same seed do not collide.
    """
    first = run_batch(name="a", payload=_PAYLOAD, base_map="fray", rolls=1, runs=3, seed=7, root=root)
    second = run_batch(name="b", payload=_PAYLOAD, base_map="fray", rolls=1, runs=1, seed=7, root=root)

    a = read_sim_batch("a", root)
    b = read_sim_batch("b", root)
    ids = {run["batch_id"] for run in a["runs"]}

    assert len(ids) == 1, "runs of one batch disagree about which batch they are"
    assert a["batch_id"] in ids
    assert all(run["batch"] == "a" for run in a["runs"])
    assert all(run["runs_in_batch"] == 3 for run in a["runs"])
    assert b["batch_id"] != a["batch_id"]
    assert len(first.runs) == 3 and len(second.runs) == 1


def test_an_interrupted_batch_still_knows_it_is_one(root: Path) -> None:
    """A batch with runs but no summary is what an interrupted one leaves.

    Those runs are perfectly good maps, so the summary is rebuilt from them -
    and the rebuild has to recover the identity too, or the runs of a killed
    batch stop being recognisable as siblings.
    """
    run_batch(name="killed", payload=_PAYLOAD, base_map="fray", rolls=1, runs=2, seed=1, root=root)
    (sims_root(root) / "killed" / BATCH_META_FILE_NAME).unlink()

    summary = read_sim_batch("killed", root)

    assert summary["complete"] is False
    assert summary["batch_id"]
    assert len({run["batch_id"] for run in summary["runs"]}) == 1


def _delta(chunk_id: str) -> UnlockDelta:
    """A delta with nothing in it but the chunk. `simulated_payload` reads only
    `chunk_id` from a record, so the rest is what the caller would have had."""
    return UnlockDelta(
        chunk_id=chunk_id,
        new_sections={},
        new_tasks={},
        new_unsupported=frozenset(),
        bis_upgrades={},
    )


def test_saving_an_unlock_writes_a_batch_of_one(root: Path) -> None:
    """**One writer, because two apps save an unlock and one metadata shape
    reads it back.** `fray unlock --cache-map` and the GUI's chunk panel both
    land here, and `maps list`, the picker and `read_batch` all read what it
    writes - so a key added on one path and not the other is a row that goes
    blank on half the maps in the list.
    """
    saved = save_unlock(name="hand", payload=_PAYLOAD, delta=_delta("101"),
                        base_map="fray", root=root)

    assert saved.name == "hand"
    assert saved.chunk_id == "101"
    assert saved.unlocked_chunks == 2

    envelope = read_cache("hand", root)
    assert envelope["kind"] == UNLOCKED
    assert set(envelope["data"]["chunks"]["unlocked"]) == {"100", "101"}

    summary = read_batch("hand", root, kind=UNLOCKED)
    assert summary["origin"] == "unlock" and summary["batch_id"]
    run = summary["runs"][0]
    # The same keys `run_batch` writes, so one reader serves both kinds.
    assert run["batch"] == "hand" and run["batch_id"] == summary["batch_id"]
    assert run["runs_in_batch"] == 1 and run["rolls"] == ["101"]
    assert run["base_map"] == "fray" and run["unlocked_chunks"] == 2


def test_two_unlocks_of_one_name_do_not_overwrite(root: Path) -> None:
    """The clash suffix is `claim_batch`'s, and the *claimed* name is what
    comes back - which is why both apps report it rather than what was asked."""
    first = save_unlock(name="hand", payload=_PAYLOAD, delta=_delta("101"),
                        base_map="fray", root=root)
    second = save_unlock(name="hand", payload=_PAYLOAD, delta=_delta("99"),
                         base_map="fray", root=root)

    assert (first.name, second.name) == ("hand", "hand-2")
    assert set(read_cache("hand-2", root)["data"]["chunks"]["unlocked"]) == {"100", "99"}


def test_a_run_is_born_with_its_timeline(root: Path) -> None:
    """**Pricing a state the run has already derived is free, so it happens
    there.** Measured under 5ms against the ~0.82s `derive` the roll pays
    anyway; rebuilding the series afterwards means paying that again per step.
    """
    write_blob("wiki_rates", {}, "test", root=root)
    batch = run_batch(name="t", payload=_PAYLOAD, base_map="fray", rolls=3, seed=2, root=root)

    stored = read_timeline(f"{batch.name}/{batch.runs[0].name}", root)

    # One total per state: the one it started on, plus one per roll.
    assert len(stored["totals"]) == len(batch.runs[0].rolls) + 1
    assert all(isinstance(v, float) for v in stored["totals"])
    # Wiki rates, not gear - `enrich` is ~1.29s a roll and is the upgrade.
    assert stored["stamp"]["enriched"] is False
    assert stored["stamp"]["chunkinfo"] and stored["stamp"]["rates"]


def test_without_a_rate_scrape_a_run_stores_no_timeline(root: Path) -> None:
    """**No hours beats wrong hours.** Without `wiki_rates` every number falls
    to a default and the total is thousands of hours light - which `fray show`
    at least prints a caveat beside. A graph carries no caveat, so there
    isn't one."""
    batch = run_batch(name="t", payload=_PAYLOAD, base_map="fray", rolls=2, seed=2, root=root)

    with pytest.raises(CacheMissError):
        read_timeline(f"{batch.name}/{batch.runs[0].name}", root)


def test_pricing_does_not_change_what_was_rolled(root: Path) -> None:
    """The callback observes; it must not steer. A seeded batch has to roll the
    same chunks whether or not this machine can price them."""
    unpriced = run_batch(name="a", payload=_PAYLOAD, base_map="f", rolls=4, seed=8, root=root)
    write_blob("wiki_rates", {}, "test", root=root)
    priced = run_batch(name="b", payload=_PAYLOAD, base_map="f", rolls=4, seed=8, root=root)

    assert unpriced.runs[0].rolls == priced.runs[0].rolls
