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

**`save_unlock` is here for the metadata, not for the rolling.** A hand-picked
unlock does no simulation and spawns no process, but it lands on disk in the
same batch-of-one shape - and `maps list`, the map picker and `read_batch` all
read that shape. Two writers of it would be two things to keep in agreement, so
there is one, and it is the module that already owned the layout.
"""

from __future__ import annotations

import os
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4
from pathlib import Path
from typing import Any

from fray_claude.store.cache import (
    SIMULATED,
    TASKS_MAP_BLOB_NAME,
    UNLOCKED,
    WIKI_RATES_BLOB_NAME,
    CacheMissError,
    blob_path,
    chunkinfo_source,
    claim_batch,
    claim_sim_batch,
    file_digest,
    overrides_path,
    read_base_payload,
    read_blob,
    read_cache,
    read_chunkinfo,
    read_overrides,
    run_dir,
    write_sim_batch,
    write_sim_run,
)
from fray_claude.costing import dps_bridge
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.store.derived_cache import (
    CacheBehaviour,
    Digests,
    RollCache,
    cached_derive,
    cached_enrich,
    pricing_digests,
)
from fray_claude.costing.estimate import EstimateResult, estimate
from fray_claude.costing.levels import goal_levels, infer_levels
from fray_claude.model.firebase import reverse_tasks_map
from fray_claude.costing.heuristics import Heuristics, merge
from fray_claude.costing.heuristics import load as load_heuristics
from fray_claude.derive.pipeline import Derived, MapState, load_map_state
from fray_claude.derive.search import WorldIndex, build_world_index
from fray_claude.runs.simulate import UnlockRecord, simulate_rolls, simulated_payload
from fray_claude.model.summary import _mapping
from fray_claude.runs.timeline import added_estimate, added_hours
from fray_claude.runs.timeline import stamp as timeline_stamp
from fray_claude.derive.unlock import UnlockDelta

#: Draw run seeds from, so a batch seed of 1 and a run seed of 1 can't collide
#: into "the same run twice" by coincidence.
_SEED_SPACE = 2**63

#: How many rolls a pricing slice should hold before it is worth splitting off
#: another worker. A slice costs one full `enrich` (~0.66s) for its head and
#: almost nothing per step after, so short slices buy no wall clock and spend
#: a lot of CPU. See `price_steps`.
_MIN_SLICE = 6


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
    #: True when the run was stopped before it had rolled what it was asked
    #: for. `written` is false only when it was stopped before rolling at all.
    cancelled: bool = False
    written: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "run": self.name,
            "seed": self.seed,
            "rolls": list(self.rolls),
            "unlocked_chunks": self.unlocked_chunks,
            "cancelled": self.cancelled,
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


@dataclass
class _Pricer:
    """Costs each state a run passes through, for the timeline.

    **This is the one place a simulation is worth pricing, because the
    derivation is already in hand.** `estimate` over a `Derived` is under 5ms;
    the ~0.82s it would otherwise need is the `derive` this run has just done
    anyway. Rebuilding the series afterwards means paying that again per step,
    so a run is born with its timeline rather than earning one later.

    **It stops at the estimator and does not call `dps_bridge.enrich`.** That
    would add ~1.29s a roll - measured - and take a 100x50 batch from 68
    minutes to 176, on every batch whether or not anyone opens its timeline.
    So a run stores the cheap answer and `gui/server.py` upgrades it on
    request; `timeline.stamp`'s `enriched` flag is what tells the two apart,
    and `timeline.matches` deliberately ignores it so the cheap numbers do not
    read as stale.

    The only mutable state in this module, and it never leaves the worker that
    built it - one instance per `run_one` call, on that call's stack. The
    process-parallel rule is about *module* state, and there is still none.
    """

    heuristics: Heuristics
    world: WorldIndex
    stamp: dict[str, Any]
    totals: list[float] = field(default_factory=list)
    added: list[float] = field(default_factory=list)
    _last: EstimateResult | None = None

    @classmethod
    def build(cls, info: ChunkInfo, root: Path | None, digests: Digests) -> _Pricer | None:
        """A pricer, or `None` when this machine cannot price anything.

        Without `cache/reference/wiki_rates.json` every number falls back to a
        default and the total is thousands of hours light - which is a worse
        answer than no timeline at all, because a graph does not carry the
        caveat that `fray show` prints beside the figure.
        """
        try:
            scraped = read_blob(WIKI_RATES_BLOB_NAME, root)["data"]
        except CacheMissError:
            return None
        overrides = read_overrides(root)
        return cls(
            heuristics=load_heuristics(
                merge(scraped, overrides),
                boss_monsters=frozenset(_mapping(info.code_items, "bossMonsters")),
                slayer_monsters=frozenset(info.slayer_monsters),
            ),
            world=build_world_index(info),
            stamp=timeline_stamp(
                chunkinfo=digests.chunkinfo,
                tasks_map=digests.tasks_map,
                rates=file_digest(blob_path(WIKI_RATES_BLOB_NAME, root)),
                overrides=_overrides_digest(root),
                enriched=False,
            ),
        )

    def record(self, state: MapState) -> Callable[[int, Derived], None]:
        """The `simulate_rolls` callback, bound to the state being rolled."""

        def priced(order: int, derived: Derived) -> None:
            result = estimate(state, derived, self.world, self.heuristics)
            # Both series, for the reason `price_steps` gives: the bars are
            # what a roll cost and the totals are what is left, and neither
            # recovers the other.
            self.added.append(added_hours(self._last, result))
            self.totals.append(sum(result.buckets.values()))
            self._last = result

        return priced

    def stored(self) -> dict[str, Any] | None:
        """What to write, or `None` if the run rolled nothing worth graphing."""
        if len(self.totals) < 2:
            return None
        return {"stamp": self.stamp, "added": self.added, "totals": self.totals}


def _overrides_digest(root: Path | None) -> str:
    """`heuristics/overrides.json` is checked in and hand-edited, so it moves
    without any fetch having happened - the case a digest of the fetched
    inputs alone would miss."""
    try:
        return file_digest(overrides_path(root))
    except (OSError, CacheMissError):
        return ""


@dataclass(frozen=True)
class PriceSpec:
    """One worker's share of a timeline. Picklable, plain data, read-only.

    **It carries chunk *ids*, not states.** A `Derived` pickles to 0.53MB and a
    `ChunkInfo` to 4.01MB; parsing the export costs 0.052s and reading a
    derivation out of `cache/derived/` costs 0.003s warm. So the worker rebuilds
    both rather than receiving either, which is `RunSpec`'s reasoning applied to
    a smaller task.
    """

    map_id: str
    #: `(step index, that step's unlocked chunk ids)`, already sorted.
    steps: tuple[tuple[int, tuple[str, ...]], ...]
    root: Path | None
    chunkinfo_path: Path | None
    #: The payload the run was rolled *from*. Everything is derived against
    #: this rather than the run's own saved map, which is what lets a reprice
    #: reuse the derivations the simulation already cached - measured at 13/13
    #: hits against 0/13. `None` falls back to the run's payload, which is
    #: slower and not different; see `cache.read_base_payload`.
    base: Mapping[str, Any] | None = None
    #: Whether to let `dps_bridge` recompute the rates. `True` is what a
    #: reprice wants; `False` exists so a *breakdown* can be computed under the
    #: same rates as the series it is breaking down. A run stores the wiki-rate
    #: answer when it is simulated, so a pie priced from gear beside a bar
    #: priced from the wiki would be two different questions with one figure
    #: each, and the smaller number would look like a bug.
    enrich: bool = True


def _walk(spec: PriceSpec) -> list[tuple[int, EstimateResult, float]]:
    """Price one contiguous slice of a run's rolls. Runs in a worker process.

    A projection of `_walk`: the totals, which are all the bars need and all
    that is worth pickling back out of a worker. `price_detail` keeps the
    `EstimateResult` instead.

    Returns `(step, hours this roll added, hours left after it)` per step -
    **except its first**, which is only there as the baseline the second one
    is measured against and is dropped on the way out. See `_slices`.

    **Sets up once per slice and keeps nothing between calls.** The obvious
    alternative - a `ProcessPoolExecutor(initializer=...)` filling a module
    global - would save the ~0.14s of setup per slice and would be the first
    module-level mutable state in the project, which is the thing that keeps
    `--jobs` honest.

    The pricing itself walks forward through the slice carrying a
    `PricedFights`, so only the head pays a full `enrich`; see
    `dps_bridge.enrich_incremental` for the measurement behind that.
    """
    info = ChunkInfo(read_chunkinfo(override=spec.chunkinfo_path, root=spec.root))
    try:
        tasks_map = reverse_tasks_map(read_blob(TASKS_MAP_BLOB_NAME, spec.root)["data"])
    except CacheMissError:
        tasks_map = {}
    state, _ = load_map_state(_base_of(spec), info, tasks_map)
    digests = Digests(
        chunkinfo=file_digest(chunkinfo_source(spec.chunkinfo_path, spec.root)),
        tasks_map=file_digest(blob_path(TASKS_MAP_BLOB_NAME, spec.root)),
    )
    pricer = _Pricer.build(info, spec.root, digests)
    if pricer is None:
        raise CacheMissError("no cached wiki rates; run: fray heuristics")

    index = dps_bridge.load_monster_index() if dps_bridge.DPS_AVAILABLE else None
    pinned = frozenset(_mapping(read_overrides(spec.root), "monsters"))
    levels = infer_levels(state)
    pricing = pricing_digests(spec.root)

    out: list[tuple[int, EstimateResult, float]] = []
    fights: Any = None
    before: EstimateResult | None = None
    for position, (order, held) in enumerate(spec.steps):
        unlocked = dict.fromkeys(held, True)
        derived = cached_derive(state, unlocked, digests, root=spec.root)
        heuristics = pricer.heuristics
        if spec.enrich and dps_bridge.DPS_AVAILABLE:
            goals = goal_levels(state, derived, dict(levels))

            # **The two optimisations are for different presses.** A stored
            # enrichment is ~3ms and wins outright on a repeat; the
            # incremental walk is what makes the *first* press fast. So the
            # cache is tried first and the walk fills the misses.
            #
            # A hit breaks the chain, because a stored enrichment is the
            # answer and not the working. `fights = None` says so, and the
            # next miss simply prices in full - slower than it might have
            # been, never wrong.
            carried = fights
            fights = None

            def price(
                base: Heuristics = heuristics,
                at: Derived = derived,
                lv: dict[str, int] = goals,
                previous: Any = carried,
            ) -> tuple[Heuristics, Any]:
                nonlocal fights
                priced, coverage, fights = dps_bridge.enrich_incremental(
                    base, info, at, lv, previous=previous, index=index, pinned_monsters=pinned
                )
                return priced, coverage

            heuristics, _ = cached_enrich(
                price, state, unlocked, digests, pricing, root=spec.root
            )
        result = estimate(state, derived, pricer.world, heuristics)
        # A slice that starts mid-run carries its predecessor purely to have
        # something to measure the head against; it is not this slice's to
        # report, and the slice that owns it reports it.
        baseline = position == 0 and order > 0
        if not baseline:
            out.append((order, added_estimate(before, result), sum(result.buckets.values())))
        before = result
    return out


def price_slice(spec: PriceSpec) -> list[tuple[int, float, float]]:
    """The totals `price_steps` pickles back out of each worker."""
    return [
        (order, round(sum(fresh.buckets.values()), 4), total)
        for order, fresh, total in _walk(spec)
    ]


def price_detail(spec: PriceSpec) -> EstimateResult | None:
    """The **breakdown** behind one step's bar, rather than its total.

    `price_slice` walks a slice and keeps one number per step; the roll details
    overlay wants the last step's whole `EstimateResult` - the buckets to draw
    as a pie, and the items behind them with their hours. Rather than a second
    pricing loop that could disagree with the bars, this runs the same one and
    keeps what it normally discards: hand it two steps, `[k-1, k]`, and it
    returns `added_estimate` for `k`.

    Runs in-process, not in a pool: it is one step, on a click, and the
    derivations it needs are the ones the timeline already cached.
    """
    if not spec.steps:
        return None
    walked = _walk(spec)
    return walked[-1][1] if walked else None

def _base_of(spec: PriceSpec) -> Mapping[str, Any]:
    """The state a slice derives against: the run's base, or the run itself.

    **Both give the same numbers and only one of them is fast.** A run's own
    payload has been through `simulated_payload`, which merges
    `checkedChallenges` and drops `activeTasks`, so its `MapState` hashes
    differently from the base it was rolled from and reaches none of the
    derivations the simulation cached along the way. Falling back to it is
    what every batch written before batches recorded their base does.
    """
    if spec.base is not None:
        return spec.base
    data: Mapping[str, Any] = read_cache(spec.map_id, spec.root)["data"]
    return data


def warm_slice(spec: PriceSpec) -> int:
    """Derive every state in `spec`, storing each. Runs in a worker process.

    **Deriving and pricing want opposite shapes, so they get separate rounds.**
    A cold `derive` is ~0.8s a step, is perfectly independent, and gains
    nothing from being next to its neighbour - it wants every core. Pricing
    wants the opposite: long contiguous slices, so `enrich_incremental` has a
    predecessor to carry forward. Doing both in one pass forced a choice, and
    on a 21-step run either choice cost more than the pair does - short slices
    left the pricing with nothing to reuse, long ones left twelve cores idle
    through the derivations.

    So this round warms `cache/derived/` across every worker, and the pricing
    round then reads those back at ~3ms while keeping its slices long.
    """
    info = ChunkInfo(read_chunkinfo(override=spec.chunkinfo_path, root=spec.root))
    try:
        tasks_map = reverse_tasks_map(read_blob(TASKS_MAP_BLOB_NAME, spec.root)["data"])
    except CacheMissError:
        tasks_map = {}
    state, _ = load_map_state(_base_of(spec), info, tasks_map)
    digests = Digests(
        chunkinfo=file_digest(chunkinfo_source(spec.chunkinfo_path, spec.root)),
        tasks_map=file_digest(blob_path(TASKS_MAP_BLOB_NAME, spec.root)),
    )
    for _, held in spec.steps:
        cached_derive(state, dict.fromkeys(held, True), digests, root=spec.root)
    return len(spec.steps)


def _slices(
    held: Sequence[Sequence[str]], count: int
) -> list[tuple[tuple[int, tuple[str, ...]], ...]]:
    """Deal the steps out `count` ways, **contiguously**.

    **This used to stride, and the reasoning was right about the old code.**
    Pricing every step from scratch made a step's cost grow along a run - later
    states hold more chunks, so more monsters are reachable - and contiguous
    slices would have handed one worker the whole expensive tail. Striding gave
    every slice a mix.

    `dps_bridge.enrich_incremental` inverts that profile. A roll only ever
    *adds*, so within a contiguous slice only the **head** is expensive and the
    rest reuse it; measured, 94% of kill rates are identical to the roll
    before. That is both more even than striding was and the only arrangement
    where the reuse is possible at all - a strided slice never holds two
    consecutive rolls.

    Each slice also carries the step *before* its head, as a baseline for
    `timeline.added_hours`; see `price_slice`.

    Empty slices are dropped, so asking for more slices than there are steps
    is not an error - it just produces fewer.
    """
    work = [(order, tuple(ids)) for order, ids in enumerate(held)]
    if count <= 1:
        return [tuple(work)]
    size = -(-len(work) // count)
    out: list[tuple[tuple[int, tuple[str, ...]], ...]] = []
    for start in range(0, len(work), size):
        # One step of overlap: a slice head needs its predecessor priced to
        # know what the head's roll actually added.
        out.append(tuple(work[max(0, start - 1) : start + size]))
    return out


def price_steps(
    *,
    map_id: str,
    held: Sequence[Sequence[str]],
    jobs: int = 0,
    root: Path | None = None,
    chunkinfo_path: Path | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[list[float], list[float]]:
    """What each roll of a run cost, and what was left after it, in step order.

    Two series because they answer different questions and neither recovers
    the other: the bars are `timeline.added_hours` - what this roll newly put
    in front of you - and the totals are what remains, which a tooltip wants
    and the bars deliberately do not sum to.

    **This is the parallel half of what `_Pricer` does inline.** A simulation
    prices its own rolls as it goes, because the derivation is already in hand
    and `estimate` alone is under 5ms. Repricing through `dps_bridge.enrich` is
    ~1.24s a step, which is a minute on a 50-roll run - and 94% of it is
    `osrs_dps` simulating fights, pure CPU over independent states. So it goes
    across cores.

    **Measured on the real export** (8 physical cores, 16 logical), 16 steps:
    19.9s sequential, 10.4s at 2, 5.4s at 4, 2.9s at 8, 2.8s at 16 - so it
    **plateaus at the physical core count** and SMT buys 5%. Overshooting is
    free rather than harmful, which is why `jobs=0` can take the logical count
    and not have to guess at the topology. Every one of those job counts
    produced identical totals, which is the property `tests/test_batch.py`
    pins: **`jobs` must never change a result.**

    `jobs=0` picks `os.process_cpu_count()` - affinity- and cgroup-aware, which
    `os.cpu_count()` is not, and this can be running inside a container.
    `jobs=1` runs inline with no pool at all, which is what keeps the test
    suite in one process.

    `on_progress(done, total)` counts *slices*, not steps: a worker cannot
    report from inside one.

    **One slice per job, and never shorter than `_MIN_SLICE`.** Slices are
    contiguous so each can carry its pricing forward (see `_slices`), which
    makes every extra slice another full-price head and another duplicated
    baseline. Twenty-one steps across sixteen workers is two steps a slice and
    no reuse at all - the same wall clock as before for sixteen times the CPU.
    Capping the count keeps slices long enough for the carry to pay, and the
    wall clock barely moves because a slice is one expensive head and a tail
    of near-free steps either way.
    """
    if not held:
        return [], []
    wanted = jobs if jobs > 0 else (os.process_cpu_count() or 1)
    parts = _slices(held, max(1, min(wanted, -(-len(held) // _MIN_SLICE))))
    # Resolved once in the parent: it is ~36KB of plain data, and every worker
    # asking the disk for it separately would be the same answer N times.
    base = read_base_payload(map_id, root)
    specs = [
        PriceSpec(
            map_id=map_id, steps=part, root=root, chunkinfo_path=chunkinfo_path, base=base
        )
        for part in parts
    ]

    priced: dict[int, tuple[float, float]] = {}
    done = 0

    def landed(result: list[tuple[int, float, float]]) -> None:
        nonlocal done
        priced.update({order: (added, total) for order, added, total in result})
        done += 1
        if on_progress is not None:
            on_progress(done, len(specs))

    if wanted <= 1 or len(specs) == 1:
        for spec in specs:
            landed(price_slice(spec))
    else:
        # Imported here for the reason `run_batch` gives: `concurrent.futures`
        # costs ~12ms to import and only a real pool ever needs it.
        from concurrent.futures import ProcessPoolExecutor, as_completed

        # Every step once, dealt `wanted` ways so a worker pays its ~0.15s of
        # setup once rather than once per step. Order is irrelevant here - a
        # derivation is independent of its neighbours - so this strides, which
        # is exactly what the *pricing* round cannot do. See `warm_slice`.
        every = tuple(sorted({step for part in parts for step in part}))
        warming = [
            PriceSpec(
                map_id=map_id, steps=group, root=root, chunkinfo_path=chunkinfo_path, base=base
            )
            for k in range(wanted)
            if (group := every[k::wanted])
        ]
        with ProcessPoolExecutor(max_workers=wanted) as pool:
            for _ in pool.map(warm_slice, warming):
                pass
            futures = [pool.submit(price_slice, spec) for spec in specs]
            for future in as_completed(futures):
                landed(future.result())

    # Completion order is scheduling noise; step order is the answer.
    order = sorted(priced)
    return [priced[step][0] for step in order], [priced[step][1] for step in order]


def run_one(
    spec: RunSpec,
    *,
    on_roll: Callable[[int, str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> RunResult:
    """Execute one run and write its directory. Runs in a worker process.

    Loads its own `ChunkInfo` and tasks map - see the module docstring for why
    that is the design rather than a cost.

    **`on_roll` and `should_stop` only reach here inline.** They are keyword
    arguments rather than `RunSpec` fields because a spec has to pickle and a
    callable does not; `run_batch` passes them when `jobs` is 1 and leaves
    them unset when it uses the pool, where a worker has no channel back.

    A stopped run still writes, provided it rolled anything. Its ledger is
    short in exactly the way an exhausted roll pool already leaves it, so
    `simulated_payload` needs no special case and the result is an ordinary
    cached map with fewer chunks.
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
    pricer = _Pricer.build(info, spec.root, digests)
    ledger = simulate_rolls(
        state,
        unlocked,
        rolls=spec.rolls,
        seed=spec.seed,
        cache=RollCache(digests, spec.cache_behaviour, spec.root),
        on_state=None if pricer is None else pricer.record(state),
        on_roll=on_roll,
        should_stop=should_stop,
    )
    stopped = should_stop is not None and should_stop()
    payload = simulated_payload(spec.payload, ledger)
    rolled = tuple(record.chunk_id for record in ledger)
    held = payload.get("chunks", {}).get("unlocked", {})

    simulation = {
        "run": spec.name,
        "seed": spec.seed,
        "rolls": list(rolled),
        "rolls_requested": spec.rolls,
        # **Only `run.json` records this.** The envelope stays an ordinary
        # map, because a partial run *is* one - fewer chunks, nothing else
        # different - and `maps list` is where "you stopped this" belongs.
        "cancelled": stopped,
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
    # A run stopped before its first roll has nothing to say: writing it
    # would put a copy of the base map in the batch under a run's name.
    if ledger:
        write_sim_run(
            spec.directory,
            map_id=f"{spec.directory.parent.name}/{spec.name}",
            data=payload,
            simulation=simulation,
            ledger=[record.as_dict() for record in ledger],
            timeline=None if pricer is None else pricer.stored(),
        )
    return RunResult(
        name=spec.name,
        seed=spec.seed,
        rolls=rolled,
        unlocked_chunks=len(held),
        cancelled=stopped,
        written=bool(ledger),
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


def _roll_reporter(
    on_roll: Callable[[int, int, str], None], run_index: int
) -> Callable[[int, str], None]:
    """Bind a run's index onto the batch-level callback, so a caller counting
    rolls across a whole batch knows which run each came from."""

    def report(order: int, chunk_id: str) -> None:
        on_roll(run_index, order, chunk_id)

    return report


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
    on_roll: Callable[[int, int, str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
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

    **`on_roll` is per roll and only fires inline.** A run's cost is its
    rolls, so that is what a progress bar should count - `2/3 runs` on a
    3x100 job is three updates across four minutes. With `jobs > 1` the
    callback would fire inside a worker with no channel back, so the pooled
    path reports through `on_complete` alone and the caller says which
    granularity it is getting. Threading a `multiprocessing.Queue` through
    `RunSpec` would buy a smoother CLI bar for the one piece of shared state
    this module is built without.

    `should_stop` ends the batch early. Inline it is checked **per roll**, so
    a partial run is kept; pooled it is checked **between runs**, because
    stopping a worker mid-roll needs a signal the pool has no channel for.
    Either way the batch is summarised from what finished.
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
        for index, spec in enumerate(specs):
            if should_stop is not None and should_stop():
                break
            result = run_one(
                spec,
                on_roll=None if on_roll is None else _roll_reporter(on_roll, index),
                should_stop=should_stop,
            )
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
                # Between runs, not within one: a submitted future is already
                # in a worker and there is no channel to interrupt it.
                if should_stop is not None and should_stop():
                    for pending in futures:
                        pending.cancel()
                    break

    # Completion order is scheduling noise; run order is the reproducible one.
    results.sort(key=lambda result: result.name)
    # A run stopped before its first roll left nothing on disk, so it must not
    # appear in a summary that claims to describe the directory.
    results = [result for result in results if result.written]
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
            # **The base itself, not just its name.** A name is a pointer that
            # dangles the moment that map is refetched or removed; the payload
            # is what makes a simulation replayable on its own, and what lets
            # a reprice reach the derivations these rolls already cached. See
            # `cache.read_base_payload`.
            "base_payload": dict(payload),
            "base_fetched_at": base_fetched_at,
            "rolls_requested": rolls,
            "seed": seed,
            "cancelled": bool(should_stop is not None and should_stop()),
            "runs": [result.as_dict() for result in results],
        },
    )
    return batch


@dataclass(frozen=True)
class SavedUnlock:
    """Where a hand-unlocked map landed. See `save_unlock`."""

    name: str
    chunk_id: str
    unlocked_chunks: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "chunk": self.chunk_id,
            "unlocked_chunks": self.unlocked_chunks,
        }


def save_unlock(
    *,
    name: str,
    payload: Mapping[str, Any],
    delta: UnlockDelta,
    base_map: str,
    base_fetched_at: str | None = None,
    root: Path | None = None,
) -> SavedUnlock:
    """Save one hand-picked unlock as a cached map; returns what was claimed.

    **This is a batch of one run and is written as one**, which is the reason
    it lives beside `run_batch` rather than in `cli.py` where it started. Both
    apps save an unlock now - `fray unlock --cache-map` and the GUI's chunk
    panel - and the thing they must not disagree about is the *metadata* shape,
    since `maps list`, the picker and `read_batch` all read it. One writer is
    how that is guaranteed rather than hoped for.

    Reuses `simulate.py`'s two pieces rather than growing its own: a one-entry
    ledger drives `simulated_payload` (which reads only `chunk_id` from a
    record, plus whether there are any), and the run lands in the batch layout
    so `--map`, `fray maps` and the clash suffix all work unchanged.

    **It is its own kind, under `cache/maps/unlocked/`.** It used to be filed
    as `simulated` on the grounds that both mean "this project computed it";
    what that missed is that a picker has to *say* which, and calling a map
    made by adding one chunk by hand a simulation is simply wrong.
    """
    record = UnlockRecord(
        order=1,
        chunk_id=delta.chunk_id,
        new_sections=delta.new_sections,
        new_tasks=delta.new_tasks,
        new_unsupported=delta.new_unsupported,
        bis_upgrades=delta.bis_upgrades,
    )
    unlocked_payload = simulated_payload(payload, [record])
    directory = claim_batch(name, root, kind=UNLOCKED)
    run = run_dir(directory, 1)
    held = unlocked_payload.get("chunks", {}).get("unlocked", {})
    chunks = len(held) if isinstance(held, dict) else None
    # Minted here for the same reason `run_batch` mints one: the directory
    # name cannot carry it, because a clash renames the batch.
    batch_id = uuid4().hex
    created_at = datetime.now(UTC).isoformat()
    meta: dict[str, Any] = {
        "run": run.name,
        "batch": directory.name,
        "batch_id": batch_id,
        "runs_in_batch": 1,
        "origin": "unlock",
        "chunk": delta.chunk_id,
        "seed": None,
        "rolls": [delta.chunk_id],
        "rolls_requested": 1,
        "base_map": base_map,
        "base_fetched_at": base_fetched_at,
        "created_at": created_at,
        "unlocked_chunks": chunks,
    }
    write_sim_run(
        run,
        map_id=f"{directory.name}/{run.name}",
        data=unlocked_payload,
        simulation=meta,
        ledger=[record.as_dict()],
        source=f"unlock {delta.chunk_id} from {base_map!r}",
        kind=UNLOCKED,
    )
    write_sim_batch(
        directory,
        {
            "name": directory.name,
            "batch_id": batch_id,
            "kind": UNLOCKED,
            "origin": "unlock",
            "created_at": created_at,
            "base_map": base_map,
            "base_payload": dict(payload),
            "base_fetched_at": base_fetched_at,
            "rolls_requested": 1,
            "seed": None,
            "runs": [meta],
        },
    )
    return SavedUnlock(name=directory.name, chunk_id=delta.chunk_id, unlocked_chunks=chunks)
