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
its own with `chunksim simulate --seed <that>` without replaying the batch.

**`save_unlock` is here for the metadata, not for the rolling.** A hand-picked
unlock does no simulation and spawns no process, but it lands on disk in the
same batch-of-one shape - and `maps list`, the map picker and `read_batch` all
read that shape. Two writers of it would be two things to keep in agreement, so
there is one, and it is the module that already owned the layout.
"""

from __future__ import annotations

import os
import random
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4
from pathlib import Path
from typing import Any

from chunksim.store.cache import (
    EDITED,
    SIMULATED,
    TASKS_MAP_BLOB_NAME,
    WIKI_RATES_BLOB_NAME,
    CacheMissError,
    blob_path,
    chunkinfo_source,
    claim_batch,
    kind_root,
    read_batch,
    read_rolls,
    claim_sim_batch,
    file_digest,
    overrides_path,
    overrides_source,
    read_base_payload,
    read_blob,
    read_cache,
    read_chunkinfo,
    read_overrides,
    run_dir,
    write_sim_batch,
    write_sim_run,
)
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.store.derived_cache import (
    CacheBehaviour,
    Digests,
    RollCache,
    cached_derive,
)
from chunksim.costing import dps_bridge
from chunksim.costing.estimate import EstimateResult, estimate
from chunksim.costing.inputs import (
    ReferenceBlobs,
    level_overrides,
    load_reference,
    priced_heuristics,
)
from chunksim.model.edits import apply_ticks
from chunksim.model.firebase import reverse_tasks_map
from chunksim.costing.heuristics import Heuristics, merge
from chunksim.costing.heuristics import load as load_heuristics
from chunksim.derive.pipeline import Derived, MapState, load_map_state
from chunksim.derive.search import WorldIndex, build_world_index
from chunksim.runs.simulate import UnlockRecord, simulate_rolls, simulated_payload
from chunksim.model.summary import _mapping
from chunksim.runs.timeline import added_estimate, added_hours
from chunksim.runs.timeline import stamp as timeline_stamp
from chunksim.derive.unlock import UnlockDelta

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
    #: Carry each roll's discovered areas into the next roll's derivation.
    #: Roughly twice as fast, and measured rather than proved - which is why
    #: `simulate_rolls` re-derives the finished state cold and compares before
    #: anything is saved. See `pipeline.derive`.
    carry_areas: bool = True


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

    **Two phases, and the split is forced by what a price is measured
    against.** `priced_heuristics` needs a state to price *from* - it walks the
    item graph for every rated method and, with the `dps` extra, simulates
    every reachable fight - and the state this series has to use is **the one
    the run ends in**, so that the last bar's total is the Estimate tab's
    number to the penny (see `_walk`). That state does not exist until the last
    roll has landed. So phase one keeps each `Derived` as it arrives and prices
    nothing; phase two prices the lot.

    **This used to stop at bare `load_heuristics` and the numbers were wrong.**
    The estimator itself was never the difference - `_walk` and
    `inputs.estimate_answer` call the same `estimate` - but the `Heuristics`
    underneath it was: no recipe-computed rates, no material costs, no prayer
    methods, no simulated kill rates, no computed combat rates, and no
    `level_overrides`. On one simulated run of the reference map that read
    **17,928h against 5,093h** for the same map, and the timeline said one while the Estimate tab
    said the other. A cheap answer that disagrees with the expensive one by
    threefold is not a coarser answer, it is a wrong one, so there is now only
    the expensive one.

    **What it costs is ~1.9s a run, not the minute it once would have.** One
    `priced_heuristics` is ~1.3s and each step's `estimate` is 7.9ms, so a
    50-roll run pays about two seconds after its last roll - inside the worker
    that rolled it, so a batch pays it once across its cores rather than once
    per run in series. The old refusal ("~1.29s a roll, 68 minutes to 176") was
    costed when the enrichment was per step and `recipe_priced` was 60.6s; both
    of those are gone.

    **The derivations are held, and re-reading them instead was measured and
    rejected.** Holding fifty costs +95MB per worker on a real map,
    which looked worth a branch: under the default `CacheBehaviour.ALL` every
    state is on disk by the time this runs and could be read back at ~3ms
    each. Measured on sixteen cores, 50 rolls, one real map:

    | | wall | peak RSS |
    |---|---|---|
    | before this pricing existed | 48s | 1,557MB |
    | holding, which is what this does | 53s | 3,171MB |
    | re-reading, tried and dropped | 51s | 3,340MB |

    **The branch does not move the number it was for.** The peak is set by the
    pricing phase, not by phase one: sixteen workers each load the monster
    index and simulate every reachable fight, and that dwarfs the derivations
    they were holding - re-reading was in fact very slightly *worse*, having
    also to decompress them. So there is one path, and the doubling is the
    price of the real estimate rather than of this design. Re-reading would
    also have meant re-deriving at ~0.5s a step under `EXTREMITIES` and
    `NONE` - half a minute a run for the people who chose those.

    The only mutable state in this module, and it never leaves the worker that
    built it - one instance per `run_one` call, on that call's stack. The
    process-parallel rule is about *module* state, and there is still none.
    """

    heuristics: Heuristics
    world: WorldIndex
    stamp: dict[str, Any]
    digests: Digests
    reference: ReferenceBlobs
    root: Path | None
    #: Phase one's output, oldest first: the world before any roll, then one
    #: per roll. Priced only once the last of them has arrived.
    states: list[Derived] = field(default_factory=list)
    totals: list[float] = field(default_factory=list)
    added: list[float] = field(default_factory=list)

    @classmethod
    def build(
        cls,
        info: ChunkInfo,
        root: Path | None,
        digests: Digests,
        reference: ReferenceBlobs | None = None,
    ) -> _Pricer | None:
        """A pricer, or `None` when this machine cannot price anything.

        Without `cache/reference/wiki_rates.json` every number falls back to a
        default and the total is thousands of hours light - which is a worse
        answer than no timeline at all, because a graph does not carry the
        caveat that `chunksim show` prints beside the figure.
        """
        blobs = load_reference(root) if reference is None else reference
        if not blobs.scraped_found:
            return None
        return cls(
            heuristics=load_heuristics(
                merge(blobs.scraped, blobs.overrides),
                boss_monsters=frozenset(_mapping(info.code_items, "bossMonsters")),
                slayer_monsters=frozenset(info.slayer_monsters),
            ),
            world=build_world_index(info),
            stamp=timeline_stamp(
                chunkinfo=digests.chunkinfo,
                tasks_map=digests.tasks_map,
                rates=blobs.pricing.rates,
                overrides=blobs.pricing.overrides,
                # **What actually priced them**, so the page can say. It is
                # excluded from the freshness comparison - see
                # `timeline.matches` - and is a claim about quality, not age.
                enriched=dps_bridge.DPS_AVAILABLE,
            ),
            digests=digests,
            reference=blobs,
            root=root,
        )

    def record(self) -> Callable[[int, Derived], None]:
        """The `simulate_rolls` callback. Phase one: keep, do not price."""

        def kept(order: int, derived: Derived) -> None:
            self.states.append(derived)

        return kept

    def price(self, state: MapState, steps: Sequence[Mapping[str, bool]]) -> None:
        """Phase two: price every state the run passed through.

        `steps` is the unlocked set at each of them, oldest first - the world
        before any roll, then one per roll. `run_one` accumulates it off the
        ledger, because the `on_state` callback is handed a derivation and not
        the ids behind it, and `priced_heuristics` has to be told which chunks
        the state it prices from holds. A length that disagrees with the states
        kept is a caller error rather than something to price around.

        A run that rolled nothing has one state and no bars, and prices
        nothing - `stored` refuses it anyway, and computing an enrichment for
        it would be the whole cost of this for none of the benefit.

        **What is priced is the carried derivation, and that is safe**, which
        is worth saying because `derived_cache.cached_derive` refuses to
        *store* one. The difference is that this runs after `simulate_rolls`
        has checked itself: a run whose carry diverged raised
        `CarryDivergedError` and never reached here, so what is priced equals
        what a cold derivation would have given - which is also why re-reading
        the stored copy gives the same answer as holding it.
        """
        if len(steps) < 2 or len(self.states) != len(steps):
            return
        heuristics, _ = priced_heuristics(
            state,
            steps[-1],
            self.states[-1],
            self.heuristics,
            self.reference.levels,
            self.digests,
            world=self.world,
            root=self.root,
            reference=self.reference,
        )
        priced = _priced_series(
            state,
            enumerate(self.states),
            heuristics,
            self.world,
            self.reference.levels,
        )
        self.added = [round(sum(fresh.buckets.values()), 4) for _, fresh, _ in priced]
        self.totals = [total for _, _, total in priced]

    def stored(self) -> dict[str, Any] | None:
        """What to write, or `None` if the run rolled nothing worth graphing."""
        if len(self.totals) < 2:
            return None
        return {"stamp": self.stamp, "added": self.added, "totals": self.totals}


def _priced_series(
    state: MapState,
    steps: Iterable[tuple[int, Derived]],
    heuristics: Heuristics,
    world: WorldIndex,
    levels: Mapping[str, int],
    *,
    baseline: bool = False,
) -> list[tuple[int, EstimateResult, float]]:
    """`(step, what it added, what is outstanding after it)`, in step order.

    **The one pricing loop, and it has to stay one.** A run prices itself as it
    finishes and the GUI can reprice it later across every core; those are two
    callers of two shapes - derivations in hand, derivations off the disk - and
    when they were two loops they layered different inputs and disagreed by
    threefold about the same run. Worse, both wrote to the same cache key, so
    the last one to run decided what the other read back. That is the bug
    `costing/inputs.py` was extracted to prevent, and keeping the arithmetic in
    one function is what stops it coming back a third time.

    `steps` is consumed lazily and deliberately: `_walk` derives as it goes, so
    materialising it would hold a slice's worth of `Derived` for no reason.

    `baseline` drops the first step from the result, for a slice that starts
    mid-run and is carrying its predecessor only to have something to measure
    its head against. The slice that owns that step reports it.

    `level_overrides` reaches the estimator here, exactly as
    `inputs.estimate_answer` passes it - a rate priced at one level and spent
    at another is the kind of disagreement this function exists to remove.
    """
    out: list[tuple[int, EstimateResult, float]] = []
    before: EstimateResult | None = None
    overrides = dict(levels)
    for position, (order, derived) in enumerate(steps):
        result = estimate(state, derived, world, heuristics, level_overrides=overrides)
        if not (baseline and position == 0):
            out.append((order, added_estimate(before, result), sum(result.buckets.values())))
        before = result
    return out


def _overrides_digest(root: Path | None) -> str:
    """`heuristics/overrides.json` is checked in and hand-edited, so it moves
    without any fetch having happened - the case a digest of the fetched
    inputs alone would miss."""
    try:
        return file_digest(overrides_source(root))
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
    #: Whether to price through `inputs.priced_heuristics`. `True` is what a
    #: reprice wants; `False` exists so a *breakdown* can be computed under the
    #: same rates as the series it is breaking down. A run stores the cheap
    #: answer when it is simulated, so a pie priced one way beside a bar priced
    #: the other would be two different questions with one figure each, and the
    #: smaller number would look like a bug.
    enrich: bool = True
    #: The unlocked set the run *ends* in - the rates every step is priced
    #: against. See `_walk`: one basis for the whole series, and it is the
    #: run's own last state so the last total is the Estimate tab's number.
    final: tuple[str, ...] = ()


def _walk(
    spec: PriceSpec, prepared: _Prepared | None = None
) -> list[tuple[int, EstimateResult, float]]:
    """Price one contiguous slice of a run's rolls. Runs in a worker process.

    A projection of `_walk`: the totals, which are all the bars need and all
    that is worth pickling back out of a worker. `price_detail` keeps the
    `EstimateResult` instead.

    Returns `(step, hours this roll added, hours outstanding after it)` per step -
    **except its first**, which is only there as the baseline the second one
    is measured against and is dropped on the way out. See `_slices`.

    **Sets up once per slice and keeps nothing between calls.** The obvious
    alternative - a `ProcessPoolExecutor(initializer=...)` filling a module
    global - would save the ~0.14s of setup per slice and would be the first
    module-level mutable state in the project, which is the thing that keeps
    `--jobs` honest.

    **Priced through `inputs.priced_heuristics`, which is the whole point of
    that module.** This used to layer its own: `load_heuristics` and then
    `dps_bridge.enrich_incremental`, and nothing else. What that left out was
    `recipe_priced` - every computed rate and every material cost - and the
    combat rates that come after it, so the timeline's totals were a
    materially different number from the Estimate tab's for the same map:
    **17,928h against 5,093h** on one simulated run of the reference map.

    Worse than the disagreement was where it was stored. Both paths key
    `cached_enrich` on `PricingDigests`, so the two computations shared one
    entry and the last writer won - opening the Estimate tab could change what
    a timeline drew, and the other way round. That is the exact bug
    `costing/inputs.py` was extracted to prevent, reappearing here because this
    module assembled its own inputs rather than asking for them.

    **One enrichment for the whole series, computed on the state the run ends
    in.** Pricing each step against its own is the ideal, and it is the cheaper
    of the two by far: `recipe_priced` walks the item graph for every rated
    method, measured at **1.0s** on a mid-run state of that run, and
    `enrich` adds ~0.7s - so fifty steps is about a minute and a half against
    one step's under two seconds. One is what this does, cached after, and it buys the
    property the disagreement was about - the last step *is* the map, so its
    total is the Estimate tab's to the penny.

    **That margin used to be a thousandfold and is now about fiftyfold**: the
    same measurement read 63.7s before the `_Walk` caches landed (see
    `costing/estimate.py`). The approximation below is therefore a good deal
    cheaper to remove than it was, and is kept because it is *correct enough
    and simpler*, not because per-step pricing is out of reach.

    What it costs is that an early roll is priced at the rates the run ends
    with, which understates a grind you would really have done with worse gear
    and no recipes for half of it. That is a real approximation and it is
    stated rather than hidden; what it is not is an inconsistency, because
    every bar is measured on the same basis and the bars exist to be compared
    with each other.

    The other casualty is `enrich_incremental`: `priced_heuristics` calls
    `enrich`, and there is now only one call to make anyway.
    """
    if prepared is None:
        info = ChunkInfo(read_chunkinfo(override=spec.chunkinfo_path, root=spec.root))
        try:
            tasks_map: Mapping[str, str] = reverse_tasks_map(
                read_blob(TASKS_MAP_BLOB_NAME, spec.root)["data"]
            )
        except CacheMissError:
            tasks_map = {}
        digests = Digests(
            chunkinfo=file_digest(chunkinfo_source(spec.chunkinfo_path, spec.root)),
            tasks_map=file_digest(blob_path(TASKS_MAP_BLOB_NAME, spec.root)),
        )
        reference = load_reference(spec.root)
    else:
        info, tasks_map = prepared.info, prepared.tasks_map
        digests, reference = prepared.digests, prepared.reference

    state, _ = load_map_state(_base_of(spec), info, dict(tasks_map))
    pricer = _Pricer.build(info, spec.root, digests, reference)
    if pricer is None:
        raise CacheMissError("no cached wiki rates; run: chunksim heuristics")

    levels = reference.levels
    heuristics = pricer.heuristics
    if spec.enrich and spec.final:
        # The run's last state, not this slice's - every worker has to reach
        # the same rates or two slices of one graph disagree at their seam.
        ending = dict.fromkeys(spec.final, True)
        heuristics, _ = priced_heuristics(
            state,
            ending,
            cached_derive(state, ending, digests, root=spec.root),
            heuristics,
            levels,
            digests,
            world=pricer.world,
            root=spec.root,
            reference=reference,
        )

    # Lazy on purpose - see `_priced_series`. A slice that starts mid-run
    # carries its predecessor purely to have something to measure the head
    # against; the slice that owns that step reports it.
    walked = (
        (order, cached_derive(state, dict.fromkeys(held, True), digests, root=spec.root))
        for order, held in spec.steps
    )
    return _priced_series(
        state,
        walked,
        heuristics,
        pricer.world,
        levels,
        baseline=spec.steps[0][0] > 0,
    )


def price_slice(spec: PriceSpec) -> list[tuple[int, float, float]]:
    """The totals `price_steps` pickles back out of each worker."""
    return [
        (order, round(sum(fresh.buckets.values()), 4), total)
        for order, fresh, total in _walk(spec)
    ]


@dataclass(frozen=True)
class _Prepared:
    """The per-process setup `_walk` would otherwise do for itself.

    **For the in-process caller only.** `price_slice` and `warm_slice` run in
    pool workers, where loading the export from disk is deliberate: at ~0.1s
    against a multi-minute run it is cheaper than pickling 10MB, and under
    `forkserver` a parent-parsed export would not be shared anyway (see the
    module docstring). Neither passes one of these.

    The GUI is the opposite case. `roll_detail` runs `_walk` on a click, in
    the server process, next to a `Derivations` already holding the parsed
    export, its tasks map and its digests - so it was re-reading 13MB and the
    rate scrape to rebuild what it was sitting on.
    """

    info: ChunkInfo
    tasks_map: Mapping[str, str]
    digests: Digests
    reference: ReferenceBlobs


def price_detail(spec: PriceSpec, prepared: _Prepared | None = None) -> EstimateResult | None:
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
    walked = _walk(spec, prepared)
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
    """What each roll of a run cost, and what is outstanding after it, in step
    order.

    Two series because they answer different questions and neither recovers
    the other: the bars are `timeline.added_hours` - what this roll newly put
    in front of you - and the totals are the whole estimate for that state,
    which a tooltip wants and the bars deliberately do not sum to. See
    `timeline.series` on why the second one climbs.

    **This is the parallel half of what `_Pricer` does inside a run**, and
    since both go through `_priced_series` the two answers are equal rather
    than merely similar - `tests/test_batch.py` pins that. What is left for
    this to do is a *re*price: the reference data moved, the `dps` extra was
    installed since, or the run predates the current `timeline.PRICING_MODEL`.

    It is worth spreading because the expensive part is per *slice*, not per
    step: one `priced_heuristics` at ~1.3s, of which ~0.7s is `osrs_dps`
    simulating fights - pure CPU over independent states - against ~7.9ms for
    each step's `estimate`.

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
            map_id=map_id,
            steps=part,
            root=root,
            chunkinfo_path=chunkinfo_path,
            base=base,
            final=tuple(held[-1]),
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
        cache=RollCache(digests, spec.cache_behaviour, spec.root, spec.carry_areas),
        carry_areas=spec.carry_areas,
        on_state=None if pricer is None else pricer.record(),
        on_roll=on_roll,
        should_stop=should_stop,
    )
    stopped = should_stop is not None and should_stop()
    payload = simulated_payload(spec.payload, ledger)
    rolled = tuple(record.chunk_id for record in ledger)
    held = payload.get("chunks", {}).get("unlocked", {})
    # **After the rolling, because the rates are the run's final ones.** See
    # `_Pricer.price`: pricing an early roll needs the state the run *ends* in,
    # which does not exist until the last roll has landed. The ids per step are
    # the starting set plus one chunk at a time, which is what a roll is.
    if pricer is not None:
        pricer.price(state, _step_ids(unlocked, rolled))

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


def _step_ids(
    unlocked: Mapping[str, bool], rolled: Sequence[str]
) -> list[dict[str, bool]]:
    """The unlocked set at every step of a run, oldest first.

    `len(result)` is `len(rolled) + 1`: the world the run started in, then one
    per roll. This is `timeline.replay`'s arithmetic run forwards - it
    subtracts the later rolls off the final set, because it has no base map to
    start from and this does.
    """
    steps = [dict(unlocked)]
    for chunk_id in rolled:
        steps.append({**steps[-1], chunk_id: True})
    return steps


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
    carry_areas: bool = True,
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
                carry_areas=carry_areas,
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


def _run_one_reporting(spec: RunSpec, queue: Any, run_index: int) -> RunResult:
    """`run_one` in a worker, reporting each roll back down `queue`.

    **Module level because it has to pickle.** A closure over the queue would
    not survive the trip to a worker, which is the reason `run_one`'s
    `on_roll` is a keyword argument rather than a `RunSpec` field in the first
    place - a spec pickles, a callback does not.

    `should_stop` still does not cross: a submitted future is already inside a
    worker and there is nothing to interrupt it with. Progress travels *out*,
    which is a different direction and a much cheaper promise.
    """

    def report(order: int, chunk_id: str) -> None:
        queue.put((run_index, order, chunk_id))

    return run_one(spec, on_roll=report)


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
    carry_areas: bool = True,
    on_complete: Callable[[RunResult], None] | None = None,
    on_roll: Callable[[int, int, str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> BatchResult:
    """Claim a batch directory, run `runs` simulations into it, and summarise.

    `jobs` of 1 runs inline - no pool, no worker processes - which keeps the
    common single-run case (and the test suite) in one process. Above 1, runs
    are dispatched to a `ProcessPoolExecutor`; `on_complete` fires in *this*
    process as each finishes, so progress can be reported without any worker
    holding a handle to the caller. `jobs` of 0 means every core this process
    is allowed to use, resolved by `os.process_cpu_count()`.

    **This default is 1 while `chunksim simulate`'s is 0, deliberately.** A run is
    ~40s of `derive` and a batch is embarrassingly parallel, so somebody
    typing the command wants their cores used. A *library* default that forks
    sixteen processes is a different matter: the GUI calls this from a job
    thread, and fifteen tests call it with `runs` of two to five and no
    `jobs`, where a real `forkserver` pool would cost more than the batch. So
    the wide default lives at the edge that a person typed, and this one stays
    where a caller can see it.

    `batch.json` is written last, by this process alone. An interrupted batch
    therefore has run directories but no summary, and `cache.read_sim_batch`
    rebuilds the summary from the runs in that case rather than treating the
    batch as lost.

    **`on_roll` is per roll, pooled or not.** A run's cost is its rolls, so
    that is what a progress bar should count - `2/3 runs` on a 3x100 job is
    three updates across four minutes, and the two in between say nothing.

    Pooled, the callback fires in a worker with no way to reach the caller, so
    a `multiprocessing.Manager` queue carries the reports out and a drainer
    thread in this process turns them back into `on_roll` calls. The docstring
    here used to record that as the trade not taken; a batch that appears to do
    nothing for four minutes is what changed the answer.

    **It is the only shared state in this module and it is one-way.** Reports
    travel out; nothing travels in, and nothing a worker sends can change what
    a worker computes - so `--jobs` still cannot change a result. The manager
    process is started only when there is an `on_roll` to feed, so the command
    line without a progress bar pays nothing for it.

    `should_stop` ends the batch early. Inline it is checked **per roll**, so
    a partial run is kept; pooled it is checked **between runs**, because
    stopping a worker mid-roll needs a signal the pool has no channel for.
    Either way the batch is summarised from what finished.
    """
    if rolls < 1:
        raise ValueError("rolls must be at least 1")
    if runs < 1:
        raise ValueError("runs must be at least 1")
    if jobs < 0:
        raise ValueError("jobs must not be negative")
    # Resolved once, here, so the inline/pooled choice below and the pool's
    # own width agree about what `0` meant. `process_cpu_count` is affinity-
    # and cgroup-aware where `cpu_count` is not, and this can be in a
    # container - the same call `price_steps` makes for the same reason.
    workers = jobs if jobs > 0 else (os.process_cpu_count() or 1)

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
        carry_areas=carry_areas,
    )

    results: list[RunResult] = []
    if workers == 1 or len(specs) == 1:
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

        import multiprocessing
        import queue as queue_module
        import threading

        manager = multiprocessing.Manager() if on_roll is not None else None
        reports = manager.Queue() if manager is not None else None
        draining = threading.Event()

        def drain() -> None:
            """Turn a worker's reports back into `on_roll` calls, here.

            A timeout rather than a blocking get, so the thread notices the
            batch ending; and a final sweep after it, because a roll reported
            microseconds before the last future resolved is still a roll.
            """
            assert reports is not None and on_roll is not None
            while not draining.is_set():
                try:
                    run_index, order, chunk_id = reports.get(timeout=0.1)
                except (queue_module.Empty, EOFError, OSError):
                    continue
                on_roll(run_index, order, chunk_id)

        drainer = threading.Thread(target=drain, daemon=True) if reports is not None else None
        if drainer is not None:
            drainer.start()

        with ProcessPoolExecutor(max_workers=min(workers, len(specs))) as pool:
            futures = [
                pool.submit(run_one, spec) if reports is None
                else pool.submit(_run_one_reporting, spec, reports, index)
                for index, spec in enumerate(specs)
            ]
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

        if drainer is not None and reports is not None and on_roll is not None:
            # **The sweep matters.** A roll reported microseconds before the
            # last future resolved is still a roll, and dropping it leaves the
            # bar a few short of the total it just claimed to reach.
            draining.set()
            drainer.join(timeout=2.0)
            while True:
                try:
                    run_index, order, chunk_id = reports.get_nowait()
                except Exception:
                    break
                on_roll(run_index, order, chunk_id)
        if manager is not None:
            manager.shutdown()

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
class SavedEdit:
    """Where a hand-edited map landed. See `save_edit`."""

    name: str
    ticks: int
    chunks: list[str]
    unlocked_chunks: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ticks": self.ticks,
            "chunks": self.chunks,
            "unlocked_chunks": self.unlocked_chunks,
        }


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
    apps save an unlock now - `chunksim unlock --cache-map` and the GUI's chunk
    panel - and the thing they must not disagree about is the *metadata* shape,
    since `maps list`, the picker and `read_batch` all read it. One writer is
    how that is guaranteed rather than hoped for.

    Reuses `simulate.py`'s two pieces rather than growing its own: a one-entry
    ledger drives `simulated_payload` (which reads only `chunk_id` from a
    record, plus whether there are any), and the run lands in the batch layout
    so `--map`, `chunksim maps` and the clash suffix all work unchanged.

    **It lands under `cache/maps/edited/`, beside a hand-committed map.** It
    had a kind of its own for a while, on the grounds that "one candidate
    chunk, priced" and "six ticked tasks" are different things - which is true
    and decides nothing: both are a map this project made by hand from another
    one, both remove the same way, both browse the same way. What is worth
    keeping is *which* chunk and that it came from `unlock`, and that is in the
    batch metadata rather than in the kind.
    """
    record = UnlockRecord(
        order=1,
        chunk_id=delta.chunk_id,
        new_sections=delta.new_sections,
        new_tasks=delta.new_tasks,
        new_unsupported=delta.new_unsupported,
        bis_upgrades=delta.bis_upgrades,
        newly_trainable=delta.newly_trainable,
        boosted_levels=delta.boosted_levels,
        proven_levels=delta.proven_levels,
    )
    written = _write_one_run_batch(
        name=name,
        kind=EDITED,
        origin="unlock",
        base_payload=payload,
        data=simulated_payload(payload, [record]),
        ledger=[record.as_dict()],
        rolls=[delta.chunk_id],
        base_map=base_map,
        base_fetched_at=base_fetched_at,
        source=f"unlock {delta.chunk_id} from {base_map!r}",
        extra_meta={"chunk": delta.chunk_id},
        root=root,
    )
    return SavedUnlock(
        name=written.name, chunk_id=delta.chunk_id, unlocked_chunks=written.unlocked_chunks
    )


def save_edit(
    *,
    name: str,
    payload: Mapping[str, Any],
    ticked: Mapping[str, Sequence[str]],
    unlocked: Sequence[str],
    base_map: str,
    base_fetched_at: str | None = None,
    replace: bool = False,
    root: Path | None = None,
) -> SavedEdit:
    """Save a hand-edited map; returns what was claimed.

    An *edit* is a map a person changed by hand in the GUI - tasks ticked off,
    chunks unlocked - committed under a new name. It is its own kind rather
    than an `unlocked` one because that kind means precisely one thing (one
    candidate chunk, priced by `chunksim unlock`), and calling a map with six
    ticked tasks an unlock is the same wrong that split `unlocked` out of
    `simulated`.

    **Its ledger records the chunks and no attribution.** `simulated_payload`
    reads only `chunk_id` from a record, so the records here are synthetic and
    their delta fields are empty - nothing derived them, and inventing a task
    count for a hand edit would manufacture exactly the kind of number this
    project refuses elsewhere. Nothing draws it: an edited map browses, where
    the ledger only pins the step so the view can say which chunks arrived.

    **`replace` edits `name` in place**, which is what an already-edited map
    wants: the first change to a fetched map forks it, and every change after
    that is a change to *your* map rather than a new one beside it. The
    accumulated history is what makes that work - the batch keeps the payload
    it was originally forked from and the ledger grows, so the map still
    replays every chunk you have ever added by hand rather than only the last
    click's.
    """
    history: list[dict[str, Any]] = []
    origin_payload: Mapping[str, Any] = payload
    keep_id: str | None = None
    if replace:
        # **Where it came from is where it came from.** An edit of an edit is
        # still forked from the map the *first* one forked from, so the base
        # payload, the base map's name and the batch id all stay put; only the
        # world and the ledger move. Taking `base_map` from the caller would
        # make the map its own origin on the second commit.
        summary = read_batch(name, root, kind=EDITED)
        stored = summary.get("base_payload")
        if isinstance(stored, Mapping):
            origin_payload = stored
        keep_id = summary.get("batch_id") or None
        base_map = str(summary.get("base_map") or base_map)
        base_fetched_at = summary.get("base_fetched_at") or base_fetched_at
        history = list(read_rolls(name, root))

    records = [
        UnlockRecord(
            order=index,
            chunk_id=chunk_id,
            new_sections={},
            new_tasks={},
            new_unsupported=frozenset(),
            bis_upgrades={},
        )
        for index, chunk_id in enumerate(unlocked, start=len(history) + 1)
    ]
    ticks = sum(len(names) for names in ticked.values())
    data = simulated_payload(apply_ticks(payload, ticked), records)
    written = _write_one_run_batch(
        name=name,
        kind=EDITED,
        origin="edit",
        base_payload=origin_payload,
        data=data,
        ledger=history + [record.as_dict() for record in records],
        rolls=[str(entry.get("chunk_id")) for entry in history] + list(unlocked),
        base_map=base_map,
        base_fetched_at=base_fetched_at,
        source=f"edit of {base_map!r}: {ticks} ticked, {len(records)} unlocked",
        extra_meta={"ticks": ticks},
        replace=replace,
        batch_id=keep_id,
        root=root,
    )
    return SavedEdit(
        name=written.name,
        ticks=ticks,
        chunks=list(unlocked),
        unlocked_chunks=written.unlocked_chunks,
    )


def save_snapshot(
    *,
    name: str,
    base_payload: Mapping[str, Any],
    ledger: Sequence[dict[str, Any]],
    chunks: Sequence[str],
    base_map: str,
    root: Path | None = None,
) -> SavedEdit:
    """Save the world after `len(chunks)` rolls of a run as a map of its own.

    **A truncation, not a replay.** `simulated_payload` reads only `chunk_id`
    from a record, so the state after k rolls is the base payload with those k
    chunks applied - no export, no `derive`, the same property `timeline.py`
    leans on. The records handed to it are therefore synthetic, while the
    ledger written out is the run's own, truncated: a snapshot's own timeline
    should be the real history it came from rather than a hollowed-out copy.

    Filed as `edited` rather than as a fourth computed kind. What it is is a
    map a person made by hand out of a run, which is the same claim `save_edit`
    files - and a kind exists to be *said* in the picker, where "this came out
    of a timeline" and "I ticked some things" are one answer.
    """
    records = [
        UnlockRecord(
            order=index,
            chunk_id=chunk_id,
            new_sections={},
            new_tasks={},
            new_unsupported=frozenset(),
            bis_upgrades={},
        )
        for index, chunk_id in enumerate(chunks, start=1)
    ]
    written = _write_one_run_batch(
        name=name,
        kind=EDITED,
        origin="snapshot",
        base_payload=base_payload,
        data=simulated_payload(base_payload, records),
        ledger=list(ledger),
        rolls=list(chunks),
        base_map=base_map,
        base_fetched_at=None,
        source=f"snapshot of {base_map!r} at roll {len(records)}",
        extra_meta={"ticks": 0, "snapshot_of": base_map},
        root=root,
    )
    return SavedEdit(
        name=written.name, ticks=0, chunks=list(chunks), unlocked_chunks=written.unlocked_chunks
    )


@dataclass(frozen=True)
class _WrittenBatch:
    name: str
    unlocked_chunks: int | None


def _write_one_run_batch(
    *,
    name: str,
    kind: str,
    origin: str,
    base_payload: Mapping[str, Any],
    data: Mapping[str, Any],
    ledger: Sequence[dict[str, Any]],
    rolls: Sequence[str],
    base_map: str,
    base_fetched_at: str | None,
    source: str,
    extra_meta: Mapping[str, Any] | None = None,
    replace: bool = False,
    batch_id: str | None = None,
    root: Path | None = None,
) -> _WrittenBatch:
    """The batch-of-one write sequence, shared by every hand-made map.

    Both apps mint these now - `chunksim unlock --cache-map`, the chunk panel's
    **Unlock**, the ribbon's **Commit** - and the thing they must not disagree
    about is the *metadata* shape, since `maps list`, the picker and
    `read_batch` all read it. One writer is how that is guaranteed rather than
    hoped for, and the second caller is what made it a function.

    **`replace` writes over an existing batch instead of claiming a name**,
    which is what makes an edited map editable rather than merely forkable.
    A fetched map is upstream's and immutable, so the first change forks it;
    what follows is that the fork is an ordinary map you keep working on, and
    a Commit that minted `<map>-edit-2`, `-3`, `-4` down the chunk you were
    planning was a new map per click rather than a map you were editing.
    Everything else is unchanged, including `batch_id` when the caller passes
    the one already there - it is the same map, not a new job.
    """
    directory = (
        kind_root(kind, root) / name if replace else claim_batch(name, root, kind=kind)
    )
    if replace and not directory.is_dir():
        raise CacheMissError(f"no {kind} map {name!r} to update; run: chunksim maps list")
    run = run_dir(directory, 1)
    held = data.get("chunks", {}).get("unlocked", {})
    chunks = len(held) if isinstance(held, dict) else None
    # Minted here for the same reason `run_batch` mints one: the directory
    # name cannot carry it, because a clash renames the batch.
    batch_id = batch_id or uuid4().hex
    created_at = datetime.now(UTC).isoformat()
    meta: dict[str, Any] = {
        "run": run.name,
        "batch": directory.name,
        "batch_id": batch_id,
        "runs_in_batch": 1,
        "origin": origin,
        "seed": None,
        "rolls": list(rolls),
        "rolls_requested": len(rolls),
        "base_map": base_map,
        "base_fetched_at": base_fetched_at,
        "created_at": created_at,
        "unlocked_chunks": chunks,
        **dict(extra_meta or {}),
    }
    write_sim_run(
        run,
        map_id=f"{directory.name}/{run.name}",
        data=dict(data),
        simulation=meta,
        ledger=list(ledger),
        source=source,
        kind=kind,
    )
    write_sim_batch(
        directory,
        {
            "name": directory.name,
            "batch_id": batch_id,
            "kind": kind,
            "origin": origin,
            "created_at": created_at,
            "base_map": base_map,
            "base_payload": dict(base_payload),
            "base_fetched_at": base_fetched_at,
            "rolls_requested": len(rolls),
            "seed": None,
            "runs": [meta],
        },
    )
    return _WrittenBatch(name=directory.name, unlocked_chunks=chunks)
