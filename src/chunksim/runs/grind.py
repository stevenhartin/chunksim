"""Roll until a chunk lands a grind you would not do, and report where.

`simulate.py` answers "where would I end up after N rolls". This answers the
question a chunk player actually asks, which is the same walk with the opposite
thing held fixed: **how many more chunks do I get before one of them costs more
than I am willing to spend?** The roll count is the answer here rather than the
input, so it cannot be a fixed-length run with the bars read afterwards - the
stopping point *is* the measurement.

**This module owns when a grind stops and how its rolls are priced, and nothing
else.** Which chunk is picked is `simulate.roll_pool`'s, unchanged and
uncopied - the discipline `completion.py` keeps as this project's other second
consumer of it. How N of these are driven across cores stays `batch.py`'s,
which still owns **both** `ProcessPoolExecutor`s in the project: `run_grind`
below is a run *body* that `batch.run_batch` dispatches through its `body`
seam, not a second batch runner. What an hour is belongs to `costing/`.

**The stopping rule is rebuilt inside the worker, from data.** A `should_stop`
callable cannot cross into a pooled worker (`batch._run_one_reporting` says
why), and a grind's whole point is that the decision is made where the rolling
happens, from something that worker priced. So `RunSpec.stop_over_hours`
travels and `_StepPricer` is constructed on arrival - which is also why
`run_grind` is module level: it pickles by qualified name.

### The threshold is what the roll *added*, not what is left

`timeline.added_hours` (see its docstring): the work this chunk newly put in
front of you, clamped at zero, never the outstanding total. That choice is the
feature rather than a detail. The outstanding total climbs into the thousands
and would trip any sane threshold on roll one; the *added* figure is what a
player weighs when a roll lands - "is this the chunk that finally asks for a
thing I do not want to do".

A consequence the results table has to own, and the same one the timeline strip
already does: these do not sum to the total, and are not meant to.

### Why this cannot reuse `batch._Pricer`, and what that costs

`_Pricer` prices every step against **one** `priced_heuristics` computed on the
state the run *ends* in - the approximation `batch._walk` states, which buys
the property that the last bar's total is the Estimate tab's to the penny.

A grind cannot have it. The state a grind ends in is not known until the grind
has decided to stop, and it decides by pricing. So every step is priced against
its own rates: ~1.0s `recipe_priced` plus ~0.7s `enrich` plus two `estimate`s
at 7.9ms, roughly 2.5s a roll once the derivation is counted - against
`_Pricer`'s ~1.9s for a whole *run*.

`_walk`'s own docstring calls per-step pricing "the ideal" and its shortcut
"correct enough and simpler, not… out of reach", so this is the more accurate
of the two. It is also a **different quantity** - early rolls priced with worse
gear and fewer recipes - and the two must never be mistaken for each other.
`timeline.PER_STEP_BASIS` is how a stored series says which it is, and
`gui/actions._timeline_job` refuses to reprice across the line rather than
silently converting.

**It is still one pricing loop.** `_StepPricer` walks `batch._priced_series`
two steps at a time - the shape `batch.price_detail` already established ("hand
it two steps, `[k-1, k]`, and it returns `added_estimate` for `k`") - rather
than running an arithmetic of its own. **Both members of a diff pair are priced
under one `Heuristics`**, step `k`'s, because `added_estimate` compares two
estimates and comparing them across two rate bases would be a diff of two
different worlds.

### Stopping, and the three ways it happens

`on_state` fires before `on_roll` for the same order, and only `on_roll` knows
which chunk was taken - so a state is stashed in the first and priced in the
second, once the id that reached it is known. That is the same callback split
`simulate_rolls` documents, spent for a second reason.

- **`OVER`** - a roll's added hours passed the threshold. `should_stop` is
  checked at the *top* of the next iteration, so the roll that tripped it is
  already in the ledger, which is what makes it nameable as the wall.
- **`STUCK`** - the roll pool came up empty: the map is finished, or the
  account cannot reach anything new. No wall was found.
- **`CAPPED`** - `MAX_ROLLS` was reached. See that constant.

All three leave a short ledger, "the same shape an exhausted pool already
leaves", so `simulated_payload` needs no special case and a grind run is an
ordinary cached map with an ordinary timeline.

### Legs and waves: how a straggler gets the workers a drained pool is wasting

**A grind measures at 68.7% utilisation on 50 simulations across 16 workers,
and 84% of the idle time is in the final third** - ending with one simulation
running alone while fifteen workers sit out. Nothing can be given to that
run while it is inside a single pool task, so it is built from pieces instead:

- `advance` runs a bounded sequential stretch and hands back a `Frontier`.
  This is the whole of a grind while the pool is busy, and a `Frontier` is
  what makes one resumable somewhere else later.
- `roll_ahead` rolls and derives **without pricing**, which is only possible
  because the roll sequence is a pure function of the seed - pricing decides
  where to cut, never where to go.
- `price_wave` prices one of those steps, and is the piece that runs many at
  once for a single run. Independent per step, so a wave of eight is eight
  tasks rather than a chain.
- `settle` cuts the wave back to the first step over the threshold, discarding
  what was speculated past it.

`batch._schedule` decides between them, and `leg_plan` is how it is handed all
five without this module and that one importing each other.

**`simulate_rolls` gained one thing for this: `rng`.** An earlier version of
this docstring said it needed no change, and that was wrong rather than merely
incomplete - a resumed leg has to draw from where the last one stopped, or a
run the scheduler happened to split would diverge from one it did not, and
`--jobs` would decide an answer. The generator position travels in the
frontier. See `Frontier.rng_state`.

Measured end to end: 484.5s to 426.8s on that same batch, with the 69-second
single-straggler tail collapsing to three seconds.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from chunksim.costing.heuristics import Heuristics
from chunksim.costing.inputs import priced_heuristics_reusing
from chunksim.derive.pipeline import Derived, MapState, load_map_state
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.model.firebase import reverse_tasks_map
from chunksim.model.summary import _mapping
from chunksim.runs.batch import (
    LegPlan,
    RunResult,
    RunSpec,
    _Pricer,
    _priced_series,
    run_metadata,
)
from chunksim.runs.simulate import UnlockRecord, simulate_rolls, simulated_payload
from chunksim.runs.timeline import PER_STEP_BASIS
from chunksim.store.cache import (
    CacheMissError,
    TASKS_MAP_BLOB_NAME,
    blob_path,
    chunkinfo_source,
    file_digest,
    read_blob,
    read_chunkinfo,
    write_sim_run,
)
from chunksim.store.derived_cache import Digests, RollCache, decode, encode

#: Why a grind stopped. `OVER` is the answer one was run to get; the other two
#: are the ways it can fail to find one, and they are kept apart because they
#: say opposite things about the map - `STUCK` means there was no wall to find,
#: `CAPPED` means the search gave up before finding it.
#:
#: Pinned against the front end by `tests/test_gui_contract.py`, the way
#: `players.py`'s own state names are: one vocabulary, named once.
OVER = "over"
STUCK = "stuck"
CAPPED = "capped"
OUTCOMES: tuple[str, ...] = (OVER, STUCK, CAPPED)

#: A hard ceiling on one grind's rolls: a safety rail rather than a parameter,
#: which is why it is a constant here and not a third input box.
#:
#: A threshold nothing crosses runs until the pool is empty, and the pool is
#: every rollable chunk on the map - 1,172 of the export's 2,234. At ~2.5s a
#: roll that is nearly an hour for a *single* simulation, and the batch's own
#: `should_stop` cannot end it: pooled, that is checked **between** runs,
#: because stopping a worker mid-roll needs a channel the pool does not have
#: (`batch.run_batch`). So a runaway grind is not cancellable and this is the
#: only place to bound one.
#:
#: 200 is far past any threshold a player would set and still about eight
#: minutes. A run that reaches it reports `CAPPED` rather than a wall, so a
#: capped grind is visibly different from one that found its answer and can
#: never be silently counted as though it had.
MAX_ROLLS = 200


@dataclass(frozen=True)
class GrindOutcome:
    """Where one grind stopped, and what stopped it.

    `chunk`, `step` and `hours` are `None` for every reason but `OVER`: a grind
    that ran out of pool or hit the cap has no wall, and reporting its last
    roll as one would put a chunk nobody rejected into the results table as
    though it were the reason the run ended.
    """

    reason: str
    chunk: str | None = None
    step: int | None = None
    hours: float | None = None
    total_hours: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "chunk": self.chunk,
            "step": self.step,
            "hours": self.hours,
            "total_hours": self.total_hours,
        }


@dataclass
class _StepPricer:
    """Prices each roll on its own state, as the roll lands, and judges it.

    **The mutable state here never leaves the worker that built it** - one
    instance per `run_grind` call, on that call's stack - exactly as
    `batch._Pricer`'s docstring puts it. The process-parallel rule is about
    *module* state and there is still none.

    Unlike `_Pricer` this holds **two** derivations rather than all of them:
    the current one and its predecessor, which is all `added_estimate` needs.
    `_Pricer` must hold every one because it cannot price until the run ends;
    this cannot defer at all, so it has nothing to keep. That is the one way
    per-step pricing is *cheaper* - fifty held derivations cost ~95MB a worker.
    """

    state: MapState
    base: _Pricer
    #: The unlocked ids at each step, oldest first. `priced_heuristics` has to
    #: be told which chunks the state it prices from holds, and a `Derived`
    #: does not carry them.
    held: list[dict[str, bool]]
    limit: float
    cap: int
    #: How many rolls landed before this leg. Every step this reports is
    #: numbered against the whole grind, so a run split into legs names the
    #: same terminating step as one that was not - see `advance`.
    offset: int = 0
    #: True when this leg continues an earlier one, in which case its step 0
    #: is a step the previous leg already priced and must not price again.
    resumed: bool = False
    added: list[float] = field(default_factory=list)
    totals: list[float] = field(default_factory=list)
    previous: Derived | None = None
    _outcome: GrindOutcome | None = None
    #: The derivation `on_state` was handed, waiting for `on_roll` to say which
    #: chunk reached it. See `on_state`.
    _pending: Derived | None = None
    #: `dps_bridge.PricedFights` from the previous step, so the next one
    #: reprices only what a roll actually moved. Never crosses a leg boundary:
    #: a resumed leg starts from scratch and is merely slower, which beats
    #: putting a derived object in a `Frontier` that has to pickle.
    fights: Any = None

    @property
    def levels(self) -> dict[str, int]:
        """A fresh copy per read: `priced_heuristics` and `estimate` both take
        this as a mutable dict, and one shared between steps would be a memo
        living longer than the call that made it."""
        return dict(self.base.reference.levels)

    def _rates(self, order: int, derived: Derived) -> Heuristics:
        """This step's own rates - the one departure from `_Pricer`.

        Cached behind `derived_cache.cached_enrich` on the step's own unlocked
        set, so no two steps of one grind collide and re-walking the same
        chunks is a file read rather than another ~1.7s.
        """
        priced, _, fights = priced_heuristics_reusing(
            self.state,
            self.held[order],
            derived,
            self.base.heuristics,
            self.levels,
            self.base.digests,
            world=self.base.world,
            root=self.base.root,
            reference=self.base.reference,
            # **What the roll before priced.** A roll only adds, so most kill
            # rates are unchanged and `enrich_incremental` reprices only what
            # moved. Held on this pricer, which lives on one leg's stack and
            # is never shared - the sanctioned "passed in and returned, never
            # stored" shape.
            previous=self.fights,
        )
        self.fights = fights
        return priced

    def price(self, order: int, derived: Derived, chunk_id: str | None = None) -> None:
        """Cost one step, and decide whether it ended the grind.

        Step 0 is the world the run started in - a baseline rather than a roll,
        so it has no `chunk_id`. It is priced, because the next step needs
        something to diff against, and never judged.
        """
        rates = self._rates(order, derived)
        # Two steps, one basis, `baseline=True` so only the second is reported
        # - `batch.price_detail`'s own shape, and the reason this is not a
        # second pricing loop. Step 0 has no predecessor and is walked alone.
        pair = (
            [(order, derived)]
            if self.previous is None
            else [(order - 1, self.previous), (order, derived)]
        )
        walked = _priced_series(
            self.state,
            iter(pair),
            rates,
            self.base.world,
            self.levels,
            baseline=self.previous is not None,
        )
        _, fresh, total = walked[-1]
        cost = 0.0 if order == 0 else round(sum(fresh.buckets.values()), 4)
        self.added.append(cost)
        self.totals.append(total)
        self.previous = derived
        if order == 0 or self._outcome is not None:
            return
        step = order + self.offset
        if cost > self.limit:
            self._outcome = GrindOutcome(
                OVER, chunk=chunk_id, step=step,
                hours=cost, total_hours=round(total, 4),
            )
        elif step >= self.cap:
            self._outcome = GrindOutcome(CAPPED, step=step)

    def on_state(self, order: int, derived: Derived) -> None:
        """Step 0 is priced now; every later one waits for its chunk id.

        `on_roll` fires immediately after this for the same order and is the
        only callback told *which* chunk was taken - and both the wall's name
        and `priced_heuristics`' own input need the ids, not the derivation
        alone. So a state is stashed here and priced there.

        Step 0 is the exception because it is not a roll: `held` was built with
        the run's starting set, so nothing is waiting to be learned.

        **A resumed leg's step 0 is somebody else's step**, already priced and
        already in `added`. It is kept as the diff baseline and nothing else -
        pricing it again would put a duplicate in the series and shift every
        bar after it.
        """
        if order == 0:
            if self.resumed:
                self.previous = derived
                return
            self.price(0, derived)
            return
        self._pending = derived

    def frozen(self) -> bytes:
        """The state this leg ended on, encoded for the next one.

        `derived_cache.encode`'s ~118KiB rather than a raw pickle's ~0.53MB,
        because this crosses a process boundary. Empty when the leg derived
        nothing at all, which is a grind that rolled zero times.
        """
        return b"" if self.previous is None else encode(self.previous)

    def outcome_if_ended(
        self, *, rolled: int, asked: int, total: int, cap: int
    ) -> GrindOutcome | None:
        """What ended the grind, or `None` if it is merely out of budget.

        The distinction a leg exists for, and it is not visible from inside
        `simulate_rolls`: a loop that stops having rolled everything it was
        asked for has either finished the grind or run out of *this leg's*
        allowance, and only the caller knows which. Rolling fewer than asked
        means the pool came up empty, which is the one ending this cannot
        confuse with a budget.
        """
        if self._outcome is not None:
            return self._outcome
        if rolled < asked:
            return GrindOutcome(STUCK)
        return GrindOutcome(CAPPED, step=total) if total >= cap else None

    def on_roll(self, order: int, chunk_id: str) -> None:
        self.held.append({**self.held[order - 1], chunk_id: True})
        derived, self._pending = self._pending, None
        if derived is not None:
            self.price(order, derived, chunk_id)

    def should_stop(self) -> bool:
        """Whether the last roll ended the grind.

        Read at the *top* of `simulate_rolls`' loop, one iteration after
        `price` set it - which is precisely why the terminating roll is in the
        ledger and can be named.
        """
        return self._outcome is not None

    def outcome(self) -> GrindOutcome:
        """What stopped this grind.

        An empty pool is not visible from here - `simulate_rolls` simply stops
        - so it is inferred: nothing rejected and nothing capped leaves running
        out of chunks. A grind that rolled nothing at all is `STUCK` too, and
        truthfully so.
        """
        return self._outcome if self._outcome is not None else GrindOutcome(STUCK)



@dataclass(frozen=True)
class Frontier:
    """Where a paused grind got to - everything needed to continue it in
    another process, and nothing else.

    **It exists so a long grind can be taken apart and rescheduled**, which is
    the only way spare workers can be pointed at a straggler: once a whole
    simulation is inside one pool task there is no way to reclaim it. A leg
    ends, hands this back, and the next leg picks it up wherever the scheduler
    decides to run it.

    **`rng_state` is the load-bearing field and the reason this is not
    simply `(rolled, derived)`.** `--jobs must never change a result`, so a
    resumed run has to draw from exactly where it stopped: a fresh
    `Random(seed)` would replay the draws already spent and a differently
    seeded one would take another path, and either way the answer would depend
    on whether the scheduler happened to split this run. `random.Random`
    carries its own position and `getstate()` pickles, so the position travels
    with the frontier. See `simulate.simulate_rolls`.

    `derived` is `derived_cache.encode`'s ~118KiB rather than a raw `Derived`'s
    ~0.53MB, because it crosses a process boundary once per leg. It is the
    state at the *last rolled step*, which is exactly what pricing the next one
    needs to diff against - and carrying it is what lets a resumed leg keep the
    area carry going instead of restarting it cold.
    """

    rolled: tuple[str, ...]
    rng_state: Any
    derived: bytes
    added: tuple[float, ...]
    totals: tuple[float, ...]
    #: `UnlockRecord`s rather than their dicts: `simulated_payload` reads
    #: the records and `write_sim_run` wants the dicts, so keeping the
    #: richer form means no leg has to guess which the next one needs.
    ledger: tuple[UnlockRecord, ...]

    @property
    def steps(self) -> int:
        """Rolls landed so far. `added`/`totals` hold one more, the baseline."""
        return len(self.rolled)


@dataclass(frozen=True)
class Leg:
    """What one stretch of a grind produced.

    `outcome` is `None` when the leg ran out of budget with the grind still
    going - the frontier is then the thing worth keeping. Anything else means
    the grind is over and the frontier is its final state.
    """

    frontier: Frontier
    outcome: GrindOutcome | None
    #: What the priced series was computed against - see `timeline.stamp`.
    #: Carried so `write_leg` need not rebuild a `_Pricer` to learn it.
    stamp: Mapping[str, Any] = field(default_factory=dict)
    cancelled: bool = False

    @property
    def finished(self) -> bool:
        return self.outcome is not None


def run_grind(
    spec: RunSpec,
    *,
    on_roll: Callable[[int, str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> RunResult:
    """Execute one grind and write its directory. Runs in a worker process.

    `batch.run_one`'s twin, and deliberately the same signature: it is passed
    to `run_batch(body=...)`, which knows only that a body takes a spec and
    two optional callbacks. Loads its own `ChunkInfo` and tasks map for the
    reason `batch.py`'s module docstring gives - at ~0.1s against a
    multi-minute run it beats pickling 10MB.

    Falls back to `batch.run_one`'s behaviour in one case: without cached wiki
    rates there is no pricer, so there is no threshold to test and no grind to
    run. That raises rather than rolling blindly - a grind with no prices is
    not a cheaper answer, it is no answer, and `gui/actions` refuses the job
    before starting forty of these for the same reason.

    **One unbounded leg**, which is what makes this and the scheduled path the
    same code rather than two implementations of one rule. See `advance`.
    """
    leg = advance(spec, budget=None, on_roll=on_roll, should_stop=should_stop)
    return write_leg(spec, leg)


@dataclass(frozen=True)
class _Setup:
    """What every task in this module builds before it can do anything.

    Assembled per task rather than once per worker, deliberately: a pool
    worker that cached this in a module global would be the first
    module-level mutable state in the project, which is the thing keeping
    `--jobs` honest. `batch.py`'s `_Prepared` records the same refusal and the
    same ~0.1s price for it.
    """

    state: MapState
    unlocked: dict[str, bool]
    digests: Digests
    base: _Pricer

    @classmethod
    def of(cls, spec: RunSpec) -> _Setup:
        info = ChunkInfo(read_chunkinfo(override=spec.chunkinfo_path, root=spec.root))
        try:
            tasks_map = reverse_tasks_map(read_blob(TASKS_MAP_BLOB_NAME, spec.root)["data"])
        except CacheMissError:
            tasks_map = {}
        state, unlocked = load_map_state(spec.payload, info, tasks_map)
        digests = Digests(
            chunkinfo=file_digest(chunkinfo_source(spec.chunkinfo_path, spec.root)),
            tasks_map=file_digest(blob_path(TASKS_MAP_BLOB_NAME, spec.root)),
        )
        # Named with the batch, so this run prices against the account
        # `run_batch` copied off the base map - see `batch.run_one`.
        base = _Pricer.build(
            info, spec.root, digests,
            map_id=spec.directory.parent.name, basis=PER_STEP_BASIS,
        )
        if base is None:
            raise CacheMissError("no cached wiki rates; run: chunksim heuristics")
        return cls(state=state, unlocked=dict(unlocked), digests=digests, base=base)


def advance(
    spec: RunSpec,
    frontier: Frontier | None = None,
    *,
    budget: int | None = None,
    on_roll: Callable[[int, str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Leg:
    """Roll and price one stretch of a grind. Runs in a worker process.

    `budget` is a maximum, not a target: the leg ends early the moment the
    grind does, so a generous budget costs nothing and a small one only buys
    the scheduler a chance to re-plan. `None` means "until the grind ends",
    which is what `run_grind` asks for and what a saturated pool wants - a leg
    boundary is pure overhead when there is no spare worker to hand the next
    one to.

    **A resumed leg is the same run, not a similar one.** The chunks come from
    the frontier's own generator position, so splitting a grind into legs
    cannot move a single roll - which is what keeps `--jobs must never change a
    result` true of a scheduler that splits some runs and not others. The
    determinism is pinned directly by `tests/test_grind.py`.

    **What a leg boundary costs**: `simulate_rolls` derives the state it starts
    from, so resuming pays one derivation the unbroken run would not, and the
    area carry restarts from there rather than continuing. Both are why budgets
    are large when the pool is busy.
    """
    setup = _Setup.of(spec)
    state, unlocked, digests, base = setup.state, setup.unlocked, setup.digests, setup.base

    cap = min(spec.rolls, MAX_ROLLS)
    done = frontier.steps if frontier is not None else 0
    # The ids this leg starts from: the base set plus everything already rolled.
    start_ids = dict(unlocked)
    for chunk_id in frontier.rolled if frontier is not None else ():
        start_ids[chunk_id] = True

    rng = random.Random(spec.seed)
    if frontier is not None:
        rng.setstate(frontier.rng_state)

    pricer = _StepPricer(
        state=state,
        base=base,
        held=[start_ids],
        limit=spec.stop_over_hours if spec.stop_over_hours is not None else 0.0,
        cap=cap,
        # **Numbered against the whole grind, not this leg.** The cap and the
        # reported step are properties of the run; a leg is a scheduling
        # detail and must not be able to shift either.
        offset=done,
        added=list(frontier.added) if frontier is not None else [],
        totals=list(frontier.totals) if frontier is not None else [],
        resumed=frontier is not None,
    )

    def rolled_cb(order: int, chunk_id: str) -> None:
        pricer.on_roll(order, chunk_id)
        if on_roll is not None:
            on_roll(order + done, chunk_id)

    def stop() -> bool:
        return pricer.should_stop() or (should_stop is not None and should_stop())

    remaining = cap - done
    if budget is not None:
        remaining = min(remaining, budget)
    leg_ledger = simulate_rolls(
        state,
        start_ids,
        rolls=max(0, remaining),
        rng=rng,
        cache=RollCache(digests, spec.cache_behaviour, spec.root, spec.carry_areas),
        carry_areas=spec.carry_areas,
        on_state=pricer.on_state,
        on_roll=rolled_cb,
        should_stop=stop,
    )
    cancelled = should_stop is not None and should_stop()
    rolls = (frontier.rolled if frontier is not None else ()) + tuple(
        record.chunk_id for record in leg_ledger
    )
    ledger = (frontier.ledger if frontier is not None else ()) + tuple(leg_ledger)
    ended = pricer.outcome_if_ended(
        rolled=len(leg_ledger), asked=max(0, remaining), total=len(rolls), cap=cap
    )
    return Leg(
        frontier=Frontier(
            rolled=rolls,
            rng_state=rng.getstate(),
            derived=pricer.frozen(),
            added=tuple(pricer.added),
            totals=tuple(pricer.totals),
            ledger=ledger,
        ),
        outcome=None if cancelled and ended is None else ended,
        stamp=base.stamp,
        cancelled=cancelled,
    )


@dataclass(frozen=True)
class Scouted:
    """One roll, derived but not yet priced. See `roll_ahead`."""

    chunk_id: str
    record: UnlockRecord
    derived: bytes


@dataclass(frozen=True)
class Wave:
    """A stretch rolled blind, ready to be priced in parallel.

    **The point of rolling without pricing.** A grind's rolls are a pure
    function of the seed - pricing decides only where to *cut* - so the next
    few can be derived before anyone knows whether the first of them already
    ended the run. Deriving is the cheap half (~0.9s against ~2.8s), so
    speculating on it costs little, and it turns the expensive half into
    `len(steps)` independent tasks where there was a sequential chain.

    That is only worth doing when workers would otherwise be idle: every step
    past the wall is priced for nothing. See `batch`'s scheduler for when it
    decides that is true.
    """

    steps: tuple[Scouted, ...]
    rng_state: Any
    #: The pool came up empty inside this wave, so there is nothing after it.
    exhausted: bool


def roll_ahead(spec: RunSpec, frontier: Frontier | None, depth: int) -> Wave:
    """Roll and derive up to `depth` steps without pricing any of them.

    Runs in a worker process, and is the sequential half of a wavefront: the
    chain cannot be parallelised, because each roll's candidate pool comes from
    the previous roll's derivation. What it produces *can* be, which is the
    whole trade.
    """
    setup = _Setup.of(spec)
    cap = min(spec.rolls, MAX_ROLLS)
    done = frontier.steps if frontier is not None else 0
    start_ids = dict(setup.unlocked)
    for chunk_id in frontier.rolled if frontier is not None else ():
        start_ids[chunk_id] = True

    rng = random.Random(spec.seed)
    if frontier is not None:
        rng.setstate(frontier.rng_state)

    derived: list[bytes] = []

    def keep(order: int, state: Derived) -> None:
        # Step 0 is the state this wave starts from, which the caller already
        # holds - only what the wave *adds* travels back.
        if order > 0:
            derived.append(encode(state))

    wanted = max(0, min(depth, cap - done))
    ledger = simulate_rolls(
        setup.state,
        start_ids,
        rolls=wanted,
        rng=rng,
        cache=RollCache(setup.digests, spec.cache_behaviour, spec.root, spec.carry_areas),
        carry_areas=spec.carry_areas,
        on_state=keep,
    )
    return Wave(
        steps=tuple(
            Scouted(chunk_id=record.chunk_id, record=record, derived=blob)
            for record, blob in zip(ledger, derived)
        ),
        rng_state=rng.getstate(),
        exhausted=len(ledger) < wanted,
    )


def price_wave(
    spec: RunSpec, held: Mapping[str, bool], previous: bytes, current: bytes
) -> tuple[float, float]:
    """One step of a wave, priced: `(what it added, what is outstanding)`.

    Runs in a worker process, one per step, and **this is the parallel half**.
    A step is independent of every other because `added_estimate` needs only
    the two derivations either side of it and the rates at `held` - the same
    property `batch.price_detail` relies on, and the reason a wave is worth
    rolling blind for.

    Both derivations arrive `derived_cache.encode`'d because the wave already
    paid for them; re-deriving here would cost more than the parallelism buys.

    **Priced as step 1 of a two-step walk, not as step 0.** `_StepPricer`
    treats step 0 as a baseline and reports it as costing nothing, which is
    right for a run's opening state and would silently zero every figure here.
    """
    setup = _Setup.of(spec)
    pricer = _StepPricer(
        state=setup.state,
        base=setup.base,
        # Index 1 is the step being priced; index 0 is never read, the
        # predecessor arriving as a derivation rather than as an id set.
        held=[{}, dict(held)],
        # Neither gate may fire: this prices one step for a caller that judges
        # it, and an outcome invented here would be about nothing.
        limit=float("inf"),
        cap=2**31,
        resumed=True,
        previous=decode(previous),
    )
    step = decode(current)
    assert step is not None, "a wave only encodes states it derived"
    pricer.price(1, step)
    return pricer.added[-1], pricer.totals[-1]


def settle(
    spec: RunSpec,
    frontier: Frontier,
    wave: Wave,
    prices: Sequence[tuple[float, float]],
    stamp: Mapping[str, Any],
) -> Leg:
    """A blind wave plus its prices, cut at the first step over the threshold.

    **Runs in the parent, and is where speculation is paid back.** The wave
    rolled past the wall without knowing where it was; this walks the priced
    steps in order and keeps only up to the first one that ends the grind, so
    a run that stopped on step 2 of an eight-step wave records two rolls and
    not eight. What was computed for the other six is discarded, which is the
    cost the scheduler accepted when it chose to speculate.

    Pure and parent-side, so nothing here touches a worker or the disk.

    **Only ever resumes.** A run's opening state has to be priced as a
    baseline before anything can be diffed against it, which is `advance`'s
    job; by the time the pool has drained enough for waves to be worth
    anything, every run has long since had one.
    """
    limit = spec.stop_over_hours if spec.stop_over_hours is not None else 0.0
    cap = min(spec.rolls, MAX_ROLLS)
    rolled = list(frontier.rolled)
    added = list(frontier.added)
    totals = list(frontier.totals)
    ledger = list(frontier.ledger)
    outcome: GrindOutcome | None = None

    for index, step in enumerate(wave.steps):
        cost, total = prices[index]
        rolled.append(step.chunk_id)
        added.append(cost)
        totals.append(total)
        ledger.append(step.record)
        if cost > limit:
            outcome = GrindOutcome(
                OVER, chunk=step.chunk_id, step=len(rolled),
                hours=cost, total_hours=round(total, 4),
            )
            break
        if len(rolled) >= cap:
            outcome = GrindOutcome(CAPPED, step=len(rolled))
            break
    else:
        # Nothing in the wave ended it, so only an empty pool can have.
        if wave.exhausted:
            outcome = GrindOutcome(STUCK)

    kept = len(rolled) - frontier.steps
    return Leg(
        frontier=Frontier(
            rolled=tuple(rolled),
            # **Past the cut when the run ended here, and that is harmless**:
            # a finished grind is never resumed, and an unfinished one kept
            # every step the wave rolled, so the position matches what it
            # drew. Nothing reads this on the branch where it is stale.
            rng_state=wave.rng_state,
            derived=wave.steps[kept - 1].derived if kept else frontier.derived,
            added=tuple(added),
            totals=tuple(totals),
            ledger=tuple(ledger),
        ),
        outcome=outcome,
        stamp=stamp,
    )


def write_leg(spec: RunSpec, leg: Leg) -> RunResult:
    """Turn a finished grind into its run directory.

    Split from `advance` because a scheduled grind is many legs and only one
    of them writes - and because `advance` then touches no disk beyond the
    derived cache, which is what lets a leg run anywhere.
    """
    frontier, outcome = leg.frontier, leg.outcome or GrindOutcome(STUCK)
    ledger = list(frontier.ledger)
    payload = simulated_payload(spec.payload, ledger)
    rolls = frontier.rolled
    held = payload.get("chunks", {}).get("unlocked", {})
    cancelled = leg.cancelled

    if ledger:
        write_sim_run(
            spec.directory,
            map_id=f"{spec.directory.parent.name}/{spec.name}",
            data=payload,
            simulation=run_metadata(
                spec, rolled=rolls, held=held, cancelled=cancelled,
                extra={"grind": outcome.as_dict(), "threshold_hours": spec.stop_over_hours},
            ),
            ledger=[record.as_dict() for record in ledger],
            timeline=(
                None
                if len(frontier.totals) < 2
                else {
                    "stamp": dict(leg.stamp),
                    "added": list(frontier.added),
                    "totals": list(frontier.totals),
                }
            ),
        )
    return RunResult(
        name=spec.name,
        seed=spec.seed,
        rolls=rolls,
        unlocked_chunks=len(held),
        cancelled=cancelled,
        written=bool(ledger),
        # Into `batch.json`, so the results overlay is one file read rather
        # than one request per simulation. See `RunResult.extra`.
        extra={"grind": outcome.as_dict()},
    )


@dataclass(frozen=True)
class ChunkWall:
    """One chunk that ended at least one grind, and how it did.

    `share` is of *every* grind, not only of those that found a wall - so the
    shares of the walls plus the unwalled runs sum to one, and a map where most
    grinds simply run out of chunks cannot read as though one chunk were
    responsible for all of them.
    """

    chunk: str
    share: float
    mean_hours: float
    #: The grinds that ended here, longest first - the drill-down's own order,
    #: sorted once here so the page never has to.
    at: tuple[Mapping[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "chunk": self.chunk,
            "runs": len(self.at),
            "share": self.share,
            "mean_hours": self.mean_hours,
            "at": [dict(entry) for entry in self.at],
        }


def collate(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """A batch's runs, turned into what the results overlay draws.

    Pure, and **names no chunk**: `runs/` is self-contained and never parses
    the export, so a chunk is an id here and the page joins the name it already
    holds from `/api/areas`. The same division `/api/roll` makes.

    Three keys:

    - `runs` - one row per simulation. A row with no `grind` block is carried
      with a null outcome rather than dropped, so the count on screen and the
      directory on disk cannot disagree.
    - `distribution` - `[{chunks, runs}]` over the **dense** range from the
      shortest grind to the longest. Dense on purpose: a chunk count nobody hit
      is a real zero and has to be a zero column, or the histogram misreports
      the shape of the distribution rather than merely omitting a bar.
    - `chunks` - the collation, most runs first and ties broken by id so the
      order is stable between two identical batches.
    """
    rows: list[dict[str, Any]] = []
    by_chunk: dict[str, list[dict[str, Any]]] = {}
    unwalled: dict[str, int] = {}
    for entry in runs:
        name = entry.get("run")
        if not isinstance(name, str) or not name:
            continue
        found = _mapping(entry, "grind")
        reason = found.get("reason")
        chunks = entry.get("rolls")
        row = {
            "run": name,
            "chunks": len(chunks) if isinstance(chunks, list) else 0,
            "outcome": reason if isinstance(reason, str) else None,
            "chunk": found.get("chunk") if isinstance(found.get("chunk"), str) else None,
            "step": _number(found.get("step")),
            "hours": _number(found.get("hours")),
            "total_hours": _number(found.get("total_hours")),
        }
        rows.append(row)
        if row["outcome"] == OVER and row["chunk"] is not None and row["hours"] is not None:
            by_chunk.setdefault(str(row["chunk"]), []).append(row)
        elif row["outcome"] is not None:
            unwalled[str(row["outcome"])] = unwalled.get(str(row["outcome"]), 0) + 1

    total = len(rows)
    walls = [
        ChunkWall(
            chunk=chunk,
            share=(len(hit) / total) if total else 0.0,
            mean_hours=round(sum(float(row["hours"] or 0.0) for row in hit) / len(hit), 4),
            at=tuple(sorted(hit, key=lambda row: (-float(row["hours"] or 0.0), row["run"]))),
        )
        for chunk, hit in by_chunk.items()
    ]
    walls.sort(key=lambda wall: (-len(wall.at), wall.chunk))
    return {
        "runs": rows,
        "distribution": _distribution(rows),
        "chunks": [wall.as_dict() for wall in walls],
        "unwalled": dict(sorted(unwalled.items())),
    }


def _distribution(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, int]]:
    """`[{chunks, runs}]` over every count from the shortest grind to the
    longest, zeroes included. See `collate` on why it is dense."""
    counts: dict[int, int] = {}
    for row in rows:
        chunks = row.get("chunks")
        if isinstance(chunks, int) and not isinstance(chunks, bool):
            counts[chunks] = counts.get(chunks, 0) + 1
    if not counts:
        return []
    return [
        {"chunks": chunks, "runs": counts.get(chunks, 0)}
        for chunks in range(min(counts), max(counts) + 1)
    ]


def _number(value: Any) -> float | None:
    """A JSON number, or `None` - `True` is an `int` in Python and would
    otherwise read as 1."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def leg_plan() -> LegPlan:
    """The five functions `batch._schedule` drives a grind with.

    Built here rather than imported there, which is what keeps the dependency
    one-way: `grind` knows about `batch`, `batch` knows only that a plan has
    these five names. Every one is module level, because all five pickle by
    qualified name into a pool worker.
    """
    return LegPlan(
        advance=advance,
        roll_ahead=roll_ahead,
        price=price_wave,
        settle=settle,
        write=write_leg,
    )
