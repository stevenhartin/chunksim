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

from fray_claude.batch import derive_seeds, price_steps, run_batch, save_unlock
from fray_claude.store.cache import (
    BATCH_META_FILE_NAME,
    UNLOCKED,
    CacheMissError,
    read_base_payload,
    read_batch,
    read_cache,
    read_rolls,
    read_sim_batch,
    read_timeline,
    sims_root,
    write_blob,
    write_cache,
)
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.store.derived_cache import CacheBehaviour
from fray_claude.derive.pipeline import load_map_state
from fray_claude.simulate import simulate_rolls
from fray_claude.timeline import replay
from fray_claude.derive.unlock import UnlockDelta

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
def root(tmp_path: Path, no_ambient_chunkinfo: None) -> Path:
    """A cache root holding just enough chunkinfo to roll against."""
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

    # One entry per state: the one it started on, plus one per roll.
    assert len(stored["totals"]) == len(batch.runs[0].rolls) + 1
    assert len(stored["added"]) == len(stored["totals"])
    assert all(isinstance(v, float) for v in stored["totals"])
    # A roll never *removes* work under this model.
    assert all(v >= 0 for v in stored["added"])
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


def test_slices_are_contiguous_and_overlap_by_one() -> None:
    """**Contiguous, reversing the striding this used to do.**

    Striding was right when every step was priced from scratch: cost grew
    along a run, so contiguous slices handed one worker the expensive tail.
    Incremental pricing inverts that - only a slice's *head* is expensive - and
    a strided slice never holds two consecutive rolls, so no reuse is possible
    at all.

    The overlap is the baseline: a slice starting mid-run needs the roll
    before its head to know what its head added.
    """
    from fray_claude.batch import _slices

    parts = _slices([["a"], ["b"], ["c"], ["d"], ["e"]], 2)

    assert [[order for order, _ in part] for part in parts] == [[0, 1, 2], [2, 3, 4]]
    # Every step is owned by exactly one slice; step 2 is carried twice but
    # reported once - see `price_slice`.
    owned = sorted(part[0][0] if i == 0 else part[1][0] for i, part in enumerate(parts))
    assert min(o for part in parts for o, _ in part) == 0
    assert max(o for part in parts for o, _ in part) == 4


def test_more_slices_than_steps_is_not_an_error() -> None:
    """Asking for 16 slices of a 3-step run produces 3, not 13 empty ones."""
    from fray_claude.batch import _slices

    parts = _slices([["a"], ["b"], ["c"]], 16)

    assert len(parts) == 3
    assert all(part for part in parts)


def test_pricing_a_run_is_the_same_answer_on_one_core_or_several(root: Path) -> None:
    """**The parallelism guarantee, for the second pool.** `--jobs` decides
    which process a step is priced in and nothing else.

    Equality, not closeness: these are sums of floats computed in a fixed
    order per step, so any difference would mean the steps had been mixed up
    rather than that arithmetic had drifted.
    """
    write_blob("wiki_rates", {}, "test", root=root)
    batch = run_batch(name="p", payload=_PAYLOAD, base_map="fray", rolls=3, seed=6, root=root)
    map_id = f"{batch.name}/{batch.runs[0].name}"
    steps = replay(read_cache(map_id, root)["data"]["chunks"]["unlocked"],
                   read_rolls(map_id, root))
    held = [sorted(step.unlocked) for step in steps]

    serial = price_steps(map_id=map_id, held=held, jobs=1, root=root)
    pooled = price_steps(map_id=map_id, held=held, jobs=2, root=root)

    assert len(serial[0]) == len(held) and len(serial[1]) == len(held)
    assert serial == pooled


def test_pricing_reports_progress_per_slice(root: Path) -> None:
    """A worker cannot report from inside a slice, so the count is of slices.
    `k/N` is the shape `app.js` parses into a real bar."""
    write_blob("wiki_rates", {}, "test", root=root)
    batch = run_batch(name="p", payload=_PAYLOAD, base_map="fray", rolls=2, seed=6, root=root)
    map_id = f"{batch.name}/{batch.runs[0].name}"
    steps = replay(read_cache(map_id, root)["data"]["chunks"]["unlocked"],
                   read_rolls(map_id, root))
    seen: list[tuple[int, int]] = []

    price_steps(
        map_id=map_id,
        held=[sorted(s.unlocked) for s in steps],
        jobs=1,
        root=root,
        on_progress=lambda done, total: seen.append((done, total)),
    )

    assert seen, "nothing reported"
    assert [done for done, _ in seen] == list(range(1, len(seen) + 1))
    assert all(total == seen[-1][0] for _, total in seen)


def test_pricing_nothing_is_not_an_error(root: Path) -> None:
    """An empty run has no steps and no pool to spin up for them."""
    assert price_steps(map_id="whatever", held=[], root=root) == ([], [])


def test_the_three_ways_of_finding_a_base_all_price_the_same(root: Path) -> None:
    """**The property that makes the fallback a speed decision, not a
    semantic one.**

    A reprice derives against the payload the run was rolled *from*, found in
    one of three places: the batch's own `base_payload`, the `base_map` read
    by name, or - failing both - the run's own saved payload. Only the last
    misses the derivations the simulation already cached (0 hits against
    13/13 measured), because `simulated_payload` merges `checkedChallenges`
    and drops `activeTasks` so the state hashes differently.

    It must be *only* slower. Equality here, not closeness, is what says so.
    """
    write_blob("wiki_rates", {}, "test", root=root)
    write_cache("base", _PAYLOAD, root=root)
    batch = run_batch(name="p", payload=_PAYLOAD, base_map="base", rolls=3, seed=6, root=root)
    map_id = f"{batch.name}/{batch.runs[0].name}"
    steps = replay(read_cache(map_id, root)["data"]["chunks"]["unlocked"], read_rolls(map_id, root))
    held = [sorted(step.unlocked) for step in steps]
    meta_path = sims_root(root) / batch.name / BATCH_META_FILE_NAME
    stored = json.loads(meta_path.read_text())

    with_payload = price_steps(map_id=map_id, held=held, jobs=1, root=root)

    # Drop the stored payload: now it must find the base map by name.
    meta_path.write_text(json.dumps({k: v for k, v in stored.items() if k != "base_payload"}))
    by_name = price_steps(map_id=map_id, held=held, jobs=1, root=root)

    # Drop that too: now it falls back to the run's own payload.
    (root / "cache" / "maps" / "fetched" / "base.json").unlink()
    from_the_run = price_steps(map_id=map_id, held=held, jobs=1, root=root)

    assert with_payload == by_name
    assert with_payload == from_the_run


def test_a_batch_records_the_base_it_rolled_from(root: Path) -> None:
    """A name is a pointer that dangles the moment that map is refetched; the
    payload is what makes a simulation replayable on its own."""
    write_cache("base", _PAYLOAD, root=root)
    batch = run_batch(name="p", payload=_PAYLOAD, base_map="base", rolls=2, seed=6, root=root)

    stored = read_sim_batch(batch.name, root)

    assert stored["base_payload"] == _PAYLOAD
    assert read_base_payload(f"{batch.name}/{batch.runs[0].name}", root) == _PAYLOAD


def test_a_base_is_still_found_with_the_map_it_came_from_deleted(root: Path) -> None:
    """The self-containment claim, asserted the only way that means anything."""
    write_cache("base", _PAYLOAD, root=root)
    batch = run_batch(name="p", payload=_PAYLOAD, base_map="base", rolls=2, seed=6, root=root)
    (root / "cache" / "maps" / "fetched" / "base.json").unlink()

    assert read_base_payload(f"{batch.name}/{batch.runs[0].name}", root) == _PAYLOAD


def test_a_batch_with_no_base_at_all_answers_none(root: Path) -> None:
    """What a batch written before this looks like. `None` means "use the
    run's own payload", which is what happened then anyway."""
    batch = run_batch(name="p", payload=_PAYLOAD, base_map="gone", rolls=1, seed=6, root=root)
    meta = sims_root(root) / batch.name / BATCH_META_FILE_NAME
    stored = json.loads(meta.read_text())
    meta.write_text(json.dumps({k: v for k, v in stored.items() if k != "base_payload"}))

    assert read_base_payload(f"{batch.name}/{batch.runs[0].name}", root) is None


def test_a_stopped_run_keeps_the_rolls_it_finished(root: Path) -> None:
    """**A partial run is an ordinary map with fewer chunks**, which is the
    whole reason stopping one is worth doing. Its ledger is short in exactly
    the way an exhausted roll pool already leaves it, so `simulated_payload`
    needs no special case and every command reads it unchanged.
    """
    rolled: list[str] = []
    batch = run_batch(
        name="stop", payload=_PAYLOAD, base_map="fray", rolls=10, seed=4, root=root,
        on_roll=lambda _run, _order, chunk: rolled.append(chunk),
        should_stop=lambda: len(rolled) >= 2,
    )

    assert len(rolled) == 2, "it stopped after the roll it was on, not mid-roll"
    run = batch.runs[0]
    assert run.cancelled is True
    assert len(run.rolls) == 2

    envelope = read_cache(f"{batch.name}/{run.name}", root)
    held = envelope["data"]["chunks"]["unlocked"]
    assert set(held) == {"100", *rolled}, "the payload holds exactly what was rolled"
    assert read_sim_batch(batch.name, root)["cancelled"] is True


def test_stopping_before_the_first_roll_writes_nothing(root: Path) -> None:
    """A run with an empty ledger would be a copy of the base map filed under
    a run's name - which reads as a simulation that did something."""
    batch = run_batch(
        name="stop", payload=_PAYLOAD, base_map="fray", rolls=5, seed=4, root=root,
        should_stop=lambda: True,
    )

    assert batch.runs == ()
    assert not list((sims_root(root) / batch.name).glob("run-*"))


def test_on_roll_reports_every_roll_once_with_what_landed(root: Path) -> None:
    """Progress counts rolls because a run's cost *is* its rolls: `2/3 runs`
    on a 3x100 job is three updates across four minutes."""
    seen: list[tuple[int, int, str]] = []
    batch = run_batch(
        name="p", payload=_PAYLOAD, base_map="fray", rolls=3, runs=2, seed=4, root=root,
        on_roll=lambda run, order, chunk: seen.append((run, order, chunk)),
    )

    rolled = [chunk for run in batch.runs for chunk in run.rolls]
    assert [chunk for _r, _o, chunk in seen] == rolled
    # Numbered from 1 within each run, and the run index says which.
    assert [(r, o) for r, o, _c in seen] == [(0, 1), (0, 2), (0, 3), (1, 1), (1, 2), (1, 3)]
