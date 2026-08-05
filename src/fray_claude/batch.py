"""Run N simulations from one starting state and cache each as its own map.

`simulate.py` rolls; `cache.py` writes; this module owns the bit in between -
seed derivation, the process pool, and what each run leaves on disk. It is the
only module that spawns processes.

**Why processes.** A roll costs one `pipeline.derive`, measured at ~0.76s on
the real export (2.7s before `challenges.py`'s gate hoists), and that is
essentially the whole cost of a run (the ~10MB chunkinfo parse is ~0.1s,
`unlock.delta_from` is free). The work is pure-Python and CPU-bound, so threads
would serialise on the GIL; a heatmap-sized batch (100 runs x 50 rolls) is well
over an hour in one process and minutes across a dozen.

**No shared mutable state, by construction.** Each worker loads its *own*
`ChunkInfo` from disk rather than receiving the parent's, because at ~0.1s
against a multi-minute run that is 0.1% overhead and cheaper than pickling
10MB - and because Python 3.14 defaults multiprocessing to `forkserver` on
Linux, so a parent-parsed export would not be copy-on-write shared anyway. Each
worker writes only its own run directory, and only the parent writes
`batch.json`. Nothing is passed by reference, so `--jobs` changes which process
a run executes in and nothing else: a batch is reproducible from its seed
regardless of how it was scheduled, which `tests/test_batch.py` asserts
directly by comparing a `--jobs 1` batch against a `--jobs 2` one.

Every run records the seed it was given, so any single run can be reproduced on
its own with `fray simulate --seed <that>` without replaying the batch.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4
from pathlib import Path
from typing import Any

from fray_claude.cache import (
    SIMULATED,
    TASKS_MAP_BLOB_NAME,
    CacheMissError,
    blob_path,
    chunkinfo_source,
    claim_sim_batch,
    file_digest,
    read_blob,
    read_chunkinfo,
    run_dir,
    write_sim_batch,
    write_sim_run,
)
from fray_claude.chunkinfo import ChunkInfo
from fray_claude.derived_cache import CacheBehaviour, Digests, RollCache
from fray_claude.firebase import reverse_tasks_map
from fray_claude.pipeline import load_map_state
from fray_claude.simulate import simulate_rolls, simulated_payload

#: Draw run seeds from, so a batch seed of 1 and a run seed of 1 can't collide
#: into "the same run twice" by coincidence.
_SEED_SPACE = 2**63


@dataclass(frozen=True)
class RunSpec:
    """One run's complete input. Picklable, self-contained, and read-only.

    It carries the *base payload* (~25KB) rather than any parsed state: the
    worker builds everything else itself, so nothing is shared between runs.
    """

    directory: Path
    name: str
    seed: int
    rolls: int
    payload: Mapping[str, Any]
    base_map: str
    base_fetched_at: str | None
    chunkinfo_path: Path | None
    root: Path | None
    #: The identity every run of one batch shares. See `cache.MapEntry`.
    batch_id: str = ""
    runs_in_batch: int = 1
    #: Which of this run's derived states to keep - see `CacheBehaviour`.
    cache_behaviour: CacheBehaviour = CacheBehaviour.ALL


@dataclass(frozen=True)
class RunResult:
    """What a finished run reports back - small, because the payload stayed on
    the worker's disk rather than travelling back through the pool.
    """

    name: str
    seed: int
    rolls: tuple[str, ...]
    unlocked_chunks: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "run": self.name,
            "seed": self.seed,
            "rolls": list(self.rolls),
            "unlocked_chunks": self.unlocked_chunks,
        }


@dataclass(frozen=True)
class BatchResult:
    """A finished batch: where it landed, and every run in run order.

    `name` is the directory actually claimed, which is *not* always the name
    asked for - see `cache.claim_sim_batch` for the clash suffixing.
    """

    name: str
    directory: Path
    rolls_requested: int
    seed: int | None
    runs: tuple[RunResult, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "rolls_requested": self.rolls_requested,
            "seed": self.seed,
            "runs": [run.as_dict() for run in self.runs],
        }


def derive_seeds(seed: int | None, runs: int) -> list[int]:
    """One seed per run, drawn from `seed` so a batch replays exactly.

    Deriving rather than using `seed + i` keeps consecutive batches from
    overlapping (batch seed 1 run 2 vs batch seed 2 run 1). With `seed` unset
    the draw is from entropy, and the results are still recorded per run, so an
    unseeded batch is reproducible after the fact even though it wasn't
    reproducible in advance.
    """
    master = random.Random(seed)
    return [master.randrange(_SEED_SPACE) for _ in range(runs)]


def run_one(spec: RunSpec) -> RunResult:
    """Execute one run and write its directory. Runs in a worker process.

    Loads its own `ChunkInfo` and tasks map - see the module docstring for why
    that is the design rather than a cost.
    """
    info = ChunkInfo(read_chunkinfo(override=spec.chunkinfo_path, root=spec.root))
    try:
        tasks_map = reverse_tasks_map(read_blob(TASKS_MAP_BLOB_NAME, spec.root)["data"])
    except CacheMissError:
        # Same graceful degradation as `cli._load_state`: no cached tasks map
        # means `t_N`-keyed entries decode empty rather than failing the run.
        tasks_map = {}

    state, unlocked = load_map_state(spec.payload, info, tasks_map)
    # Built here rather than passed in: a `RollCache` is cheap, and building it
    # inside the worker keeps `RunSpec` to plain data.
    digests = Digests(
        chunkinfo=file_digest(chunkinfo_source(spec.chunkinfo_path, spec.root)),
        tasks_map=file_digest(blob_path(TASKS_MAP_BLOB_NAME, spec.root)),
    )
    ledger = simulate_rolls(
        state,
        unlocked,
        rolls=spec.rolls,
        seed=spec.seed,
        cache=RollCache(digests, spec.cache_behaviour, spec.root),
    )
    payload = simulated_payload(spec.payload, ledger)
    rolled = tuple(record.chunk_id for record in ledger)
    held = payload.get("chunks", {}).get("unlocked", {})

    simulation = {
        "run": spec.name,
        "seed": spec.seed,
        "rolls": list(rolled),
        "rolls_requested": spec.rolls,
        "base_map": spec.base_map,
        "base_fetched_at": spec.base_fetched_at,
        "created_at": datetime.now(UTC).isoformat(),
        "unlocked_chunks": len(held),
        # **What makes these runs one job.** Written into every run, not just
        # the batch summary, so a run answers it alone - the directory name
        # cannot, because a clash renames the batch and a rename severs the
        # link. See `cache.MapEntry.batch_id`.
        "batch": spec.directory.parent.name,
        "batch_id": spec.batch_id,
        "run": spec.name,
        "runs_in_batch": spec.runs_in_batch,
    }
    write_sim_run(
        spec.directory,
        map_id=f"{spec.directory.parent.name}/{spec.name}",
        data=payload,
        simulation=simulation,
        ledger=[record.as_dict() for record in ledger],
    )
    return RunResult(
        name=spec.name, seed=spec.seed, rolls=rolled, unlocked_chunks=len(held)
    )


def _specs(
    directory: Path,
    seeds: Sequence[int],
    *,
    payload: Mapping[str, Any],
    rolls: int,
    base_map: str,
    base_fetched_at: str | None,
    chunkinfo_path: Path | None,
    root: Path | None,
    cache_behaviour: CacheBehaviour,
    batch_id: str,
) -> list[RunSpec]:
    specs: list[RunSpec] = []
    for index, seed in enumerate(seeds, start=1):
        run = run_dir(directory, index)
        specs.append(
            RunSpec(
                directory=run,
                name=run.name,
                seed=seed,
                rolls=rolls,
                payload=payload,
                base_map=base_map,
                base_fetched_at=base_fetched_at,
                chunkinfo_path=chunkinfo_path,
                root=root,
                batch_id=batch_id,
                runs_in_batch=len(seeds),
                cache_behaviour=cache_behaviour,
            )
        )
    return specs


def run_batch(
    *,
    name: str,
    payload: Mapping[str, Any],
    base_map: str,
    base_fetched_at: str | None = None,
    rolls: int,
    runs: int = 1,
    jobs: int = 1,
    seed: int | None = None,
    chunkinfo_path: Path | None = None,
    root: Path | None = None,
    cache_behaviour: CacheBehaviour = CacheBehaviour.ALL,
    on_complete: Callable[[RunResult], None] | None = None,
) -> BatchResult:
    """Claim a batch directory, run `runs` simulations into it, and summarise.

    `jobs` of 1 runs inline - no pool, no worker processes - which keeps the
    common single-run case (and the test suite) in one process. Above 1, runs
    are dispatched to a `ProcessPoolExecutor`; `on_complete` fires in *this*
    process as each finishes, so progress can be reported without any worker
    holding a handle to the caller.

    `batch.json` is written last, by this process alone. An interrupted batch
    therefore has run directories but no summary, and `cache.read_sim_batch`
    rebuilds the summary from the runs in that case rather than treating the
    batch as lost.
    """
    if rolls < 1:
        raise ValueError("rolls must be at least 1")
    if runs < 1:
        raise ValueError("runs must be at least 1")
    if jobs < 1:
        raise ValueError("jobs must be at least 1")

    directory = claim_sim_batch(name, root)
    # Minted before any run starts, so every one of them records the same
    # value and an interrupted batch is still recognisable as one job.
    batch_id = uuid4().hex
    specs = _specs(
        directory,
        derive_seeds(seed, runs),
        batch_id=batch_id,
        payload=payload,
        rolls=rolls,
        base_map=base_map,
        base_fetched_at=base_fetched_at,
        chunkinfo_path=chunkinfo_path,
        root=root,
        cache_behaviour=cache_behaviour,
    )

    results: list[RunResult] = []
    if jobs == 1 or len(specs) == 1:
        for spec in specs:
            result = run_one(spec)
            results.append(result)
            if on_complete is not None:
                on_complete(result)
    else:
        # Imported here, not at module scope: `concurrent.futures` costs ~12ms
        # to import (it pulls in `multiprocessing`), and `cli.py` imports this
        # module on every command while only `--jobs > 1` ever needs a pool.
        from concurrent.futures import ProcessPoolExecutor, as_completed

        with ProcessPoolExecutor(max_workers=min(jobs, len(specs))) as pool:
            futures = [pool.submit(run_one, spec) for spec in specs]
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                if on_complete is not None:
                    on_complete(result)

    # Completion order is scheduling noise; run order is the reproducible one.
    results.sort(key=lambda result: result.name)
    batch = BatchResult(
        name=directory.name,
        directory=directory,
        rolls_requested=rolls,
        seed=seed,
        runs=tuple(results),
    )
    write_sim_batch(
        directory,
        {
            "name": directory.name,
            "batch_id": batch_id,
            "kind": SIMULATED,
            "created_at": datetime.now(UTC).isoformat(),
            "base_map": base_map,
            "base_fetched_at": base_fetched_at,
            "rolls_requested": rolls,
            "seed": seed,
            "runs": [result.as_dict() for result in results],
        },
    )
    return batch
