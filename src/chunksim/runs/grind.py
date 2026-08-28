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

`simulate_rolls` needs no change: both seams already exist and its docstring
says `on_state` is there for exactly this.

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
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from chunksim.costing.heuristics import Heuristics
from chunksim.costing.inputs import priced_heuristics
from chunksim.derive.pipeline import Derived, MapState, load_map_state
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.model.firebase import reverse_tasks_map
from chunksim.model.summary import _mapping
from chunksim.runs.batch import (
    RunResult,
    RunSpec,
    _Pricer,
    _priced_series,
    run_metadata,
)
from chunksim.runs.simulate import simulate_rolls, simulated_payload
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
from chunksim.store.derived_cache import Digests, RollCache

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
    added: list[float] = field(default_factory=list)
    totals: list[float] = field(default_factory=list)
    _previous: Derived | None = None
    _outcome: GrindOutcome | None = None
    #: The derivation `on_state` was handed, waiting for `on_roll` to say which
    #: chunk reached it. See `on_state`.
    _pending: Derived | None = None

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
        priced, _ = priced_heuristics(
            self.state,
            self.held[order],
            derived,
            self.base.heuristics,
            self.levels,
            self.base.digests,
            world=self.base.world,
            root=self.base.root,
            reference=self.base.reference,
        )
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
            if self._previous is None
            else [(order - 1, self._previous), (order, derived)]
        )
        walked = _priced_series(
            self.state,
            iter(pair),
            rates,
            self.base.world,
            self.levels,
            baseline=self._previous is not None,
        )
        _, fresh, total = walked[-1]
        cost = 0.0 if order == 0 else round(sum(fresh.buckets.values()), 4)
        self.added.append(cost)
        self.totals.append(total)
        self._previous = derived
        if order == 0 or self._outcome is not None:
            return
        if cost > self.limit:
            self._outcome = GrindOutcome(
                OVER, chunk=chunk_id, step=order,
                hours=cost, total_hours=round(total, 4),
            )
        elif order >= self.cap:
            self._outcome = GrindOutcome(CAPPED, step=order)

    def on_state(self, order: int, derived: Derived) -> None:
        """Step 0 is priced now; every later one waits for its chunk id.

        `on_roll` fires immediately after this for the same order and is the
        only callback told *which* chunk was taken - and both the wall's name
        and `priced_heuristics`' own input need the ids, not the derivation
        alone. So a state is stashed here and priced there.

        Step 0 is the exception because it is not a roll: `held` was built with
        the run's starting set, so nothing is waiting to be learned.
        """
        if order == 0:
            self.price(0, derived)
            return
        self._pending = derived

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

    def stored(self) -> dict[str, Any] | None:
        """What to write to `timeline.json`, or `None` if there is no series.

        The shape `_Pricer.stored` writes, read by the same
        `routes_view._cached_hours`, differing only in the `basis` its stamp
        carries. A grind that rolled nothing has one step and no bars, which is
        not a timeline.
        """
        if len(self.totals) < 2:
            return None
        return {"stamp": self.base.stamp, "added": self.added, "totals": self.totals}


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
    """
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

    pricer = _StepPricer(
        state=state,
        base=base,
        held=[dict(unlocked)],
        limit=spec.stop_over_hours if spec.stop_over_hours is not None else 0.0,
        cap=min(spec.rolls, MAX_ROLLS),
    )

    def rolled(order: int, chunk_id: str) -> None:
        pricer.on_roll(order, chunk_id)
        if on_roll is not None:
            on_roll(order, chunk_id)

    def stop() -> bool:
        return pricer.should_stop() or (should_stop is not None and should_stop())

    ledger = simulate_rolls(
        state,
        unlocked,
        rolls=min(spec.rolls, MAX_ROLLS),
        seed=spec.seed,
        cache=RollCache(digests, spec.cache_behaviour, spec.root, spec.carry_areas),
        carry_areas=spec.carry_areas,
        on_state=pricer.on_state,
        on_roll=rolled,
        should_stop=stop,
    )
    cancelled = should_stop is not None and should_stop()
    payload = simulated_payload(spec.payload, ledger)
    rolls = tuple(record.chunk_id for record in ledger)
    held = payload.get("chunks", {}).get("unlocked", {})
    outcome = pricer.outcome()

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
            timeline=pricer.stored(),
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
