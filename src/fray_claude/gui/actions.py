"""The nine POST actions, and the job registry they hand work to.

`fetch`, `simulate`, `unlock`, `timeline`, `cancel`, `refresh`,
`maps/remove`, `derived/prune`, `window`. `_ACTIONS` is the dispatch table
`server._handle_post` looks them up in - it was already a table before this
split, which is why this module needed no routing invented for it.

**An action's reply shape decides whether the page polls it.**
`fetch`/`simulate`/`unlock`/`timeline`/`refresh` return a job id and report
progress while a thread does the work; `maps/remove`/`derived/prune`/`window`/
`cancel` do the work and return the result. Reading `{ job }` off all of them
polled `/api/jobs/undefined`, whose 404 silently swallowed the refresh callback
and left deleted maps on screen.

`cancel` is a *request*, not a kill: the work stops where it safely can, so the
job stays `running` until it agrees, and it ends `CANCELLED` rather than
`FAILED` - the user did it, and what it kept is an ordinary cached map.
"""

from __future__ import annotations

from fray_claude.remote.scrape import SOURCE as SCRAPE_SOURCE

from typing import Any
from fray_claude.remote.api import CHUNKINFO_URL
from collections.abc import Callable
from fray_claude.remote.api import DEFAULT_TIMEOUT
from collections.abc import Mapping
from fray_claude.gui.jobs import Progress
from fray_claude.runs.batch import RunResult

from fray_claude.gui.jobs import StopCheck
from fray_claude.remote.api import TASKS_MAP_URL
from fray_claude.gui.jobs import as_int
from fray_claude.store import cache
from fray_claude.store.derived_cache import cached_derive
from fray_claude.costing import dps_bridge
from fray_claude.remote.api import fetch_chunkinfo
from fray_claude.remote.api import fetch_map
from fray_claude.remote.api import fetch_tasks_map
import os
from fray_claude.runs.batch import price_steps
from fray_claude.runs.batch import run_batch
from fray_claude.runs.batch import save_unlock
from fray_claude.remote.scrape import scrape
from fray_claude.gui.http import Context
from fray_claude.gui.routes_view import _run_steps
from fray_claude.gui.routes_view import _timeline_stamp


def _window_state(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Remember the window's shape, so the next launch opens the same one.

    Sent by the page, because only the page can see it: the server launched a
    browser and has no idea what the user then did to the window. Ignoring
    anything unrecognised keeps a hostile or stale caller from writing
    arbitrary JSON into the cache - the file is *read back* as command-line
    arguments, so its keys are exactly the four this understands.
    """
    geometry = {
        key: int(value)
        for key in ("width", "height", "x", "y")
        if isinstance(value := payload.get(key), (int, float))
    }
    if len(geometry) == 4 and geometry["width"] > 0 and geometry["height"] > 0:
        geometry["maximised"] = bool(payload.get("maximised"))
        cache.write_gui_window(geometry, ctx.root)
        return {"saved": True}
    return {"saved": False}


def _fetch_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Download any named map from Firebase, not only the one on screen.

    **An empty name means `fray`**, matching every `--map` default in the CLI,
    because that is the map this project exists for and typing it every time
    is friction for nothing. `cache.split_map_id` is what makes the name safe
    to accept from a browser at all - it rejects anything that is not
    `[A-Za-z0-9_.-]+`, so no second, weaker check belongs here.
    """
    map_id = str(payload.get("map") or "").strip() or cache.DEFAULT_MAP_ID
    if cache.split_map_id(map_id)[1] is not None:
        # A run is something this project computed. Firebase has never heard
        # of one, so asking it for `batch/run-001` is a mistake, not a fetch.
        raise ValueError(f"{map_id!r} names a run, not a map on source-chunk")

    def work(progress: Progress, _stop: StopCheck) -> dict[str, Any]:
        progress(f"fetching {map_id}")
        data = fetch_map(map_id, timeout=DEFAULT_TIMEOUT)
        path = cache.write_cache(map_id, data, ctx.root)
        unlocked = data.get("chunks", {}).get("unlocked", {})
        return {"map": map_id, "path": str(path), "unlocked_chunks": len(unlocked)}

    return {"job": ctx.jobs.submit("fetch", work).id}


def _simulate_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    map_id = str(payload.get("map") or "").strip()
    name = str(payload.get("name") or "").strip()
    if not map_id:
        raise ValueError("missing 'map'")
    if not name:
        raise ValueError("missing 'name' for the simulated map")
    rolls = as_int(payload, "rolls", 1)
    runs = as_int(payload, "runs", 1)
    jobs = as_int(payload, "jobs", 1)
    seed_raw = payload.get("seed")
    seed = None if seed_raw in (None, "") else as_int({"s": seed_raw}, "s", 0) or None

    # Read the base map now, so a bad id fails the POST rather than a job.
    envelope = cache.read_cache(map_id, ctx.root)

    def work(progress: Progress, stop: StopCheck) -> dict[str, Any]:
        # **Rolls, not runs.** A run's cost is its rolls, so `2/3 runs` on a
        # 3x100 job is three updates across four minutes and the two in
        # between say nothing. `countsIn` in `app.js` reads `k/N` either way.
        total = rolls * runs
        rolled = 0
        finished = 0

        def roll(_run: int, _order: int, chunk_id: str) -> None:
            nonlocal rolled
            rolled += 1
            progress(f"{rolled}/{total} rolls - {chunk_id}" + (" - stopping" if stop() else ""))

        def report(result: RunResult) -> None:
            nonlocal finished, rolled
            finished += 1
            # Pooled runs report nothing per roll, so the count catches up
            # here; inline it is already there and this only re-states it.
            rolled = max(rolled, finished * rolls)
            if jobs > 1:
                progress(f"{rolled}/{total} rolls - {finished}/{runs} runs")

        progress(f"0/{total} rolls")
        batch = run_batch(
            name=name,
            payload=envelope["data"],
            base_map=map_id,
            base_fetched_at=envelope.get("fetched_at"),
            rolls=rolls,
            runs=runs,
            jobs=jobs,
            seed=seed,
            root=ctx.root,
            on_complete=report,
            # Only inline: a worker has no channel back, so `run_batch`
            # ignores this above `--jobs 1` and reports per run instead.
            on_roll=roll if jobs == 1 else None,
            should_stop=stop,
        )
        kept = sum(len(run.rolls) for run in batch.runs)
        return {
            "batch": batch.name,
            "runs": len(batch.runs),
            "rolls": kept,
            "rolls_requested": total,
            "cancelled": stop(),
            # What to put in the map picker afterwards, resolved the way
            # `cache.read_cache` resolves a bare batch name. A batch stopped
            # before its first roll finished has no run to open.
            "open": (
                ""
                if not batch.runs
                else batch.name
                if len(batch.runs) == 1
                else f"{batch.name}/{batch.runs[0].name}"
            ),
        }

    return {"job": ctx.jobs.submit("simulate", work).id}


def _unlock_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """`fray unlock --chunk X --cache-map NAME`: add one chunk by hand.

    **The same path as `GET /api/unlock`, one step further on.** The GET
    answers "what would this give me" and keeps nothing; this saves the world
    it was describing. Both derive twice, which is why this is a job rather
    than an inline action even though the write itself is instant - cold, the
    export parse alone is a second.

    The eligibility check is deliberately *not* made: `fray unlock` will price
    any chunk on the map, candidate or not, because "what if I could get
    there" is a fair question. Already-unlocked is refused, since adding a
    chunk that is already held would write a copy of the map under a new name
    and call it an unlock.
    """
    map_id = str(payload.get("map") or "").strip()
    chunk_id = str(payload.get("chunk") or "").strip()
    if not map_id:
        raise ValueError("missing 'map'")
    if not chunk_id:
        raise ValueError("missing 'chunk'")
    name = str(payload.get("name") or "").strip() or f"{map_id}-{chunk_id}"

    # Read the base map now, so a bad id fails the POST rather than a job.
    envelope = cache.read_cache(map_id, ctx.root)

    def work(progress: Progress, _stop: StopCheck) -> dict[str, Any]:
        from fray_claude.derive.unlock import tasks_added_by

        progress(f"deriving {map_id}")
        state = ctx.derivations.load(map_id)
        if chunk_id in state.unlocked:
            raise ValueError(f"chunk {chunk_id} is already unlocked on {map_id}")
        progress(f"deriving {map_id} with {chunk_id}")
        delta = tasks_added_by(
            state.state,
            state.unlocked,
            chunk_id,
            derive_with=lambda st, un: cached_derive(
                st, un, ctx.derivations.digests(), root=ctx.root
            ),
        )
        saved = save_unlock(
            name=name,
            payload=envelope["data"],
            delta=delta,
            base_map=map_id,
            base_fetched_at=envelope.get("fetched_at"),
            root=ctx.root,
        )
        return {
            **saved.as_dict(),
            "tasks": delta.task_count,
            "sections": sum(len(s) for s in delta.new_sections.values()),
            "bis_upgrades": len(delta.bis_upgrades),
            # `read_cache` resolves a one-run batch by its bare name, so this
            # is what the picker should select afterwards.
            "open": saved.name,
        }

    return {"job": ctx.jobs.submit(f"unlock {chunk_id}", work).id}


def _timeline_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Price every step of a run, and store the answer beside its ledger.

    **This is the expensive half and it is a job for one reason:
    `dps_bridge.enrich`.** Measured on the real export, a step costs ~0.01s to
    derive and estimate when the derivation is cached - and ~1.3s more when
    the `dps` extra is installed, because the kill rates are recomputed from
    the map's own BiS gear. A 50-roll run is therefore a minute or so, and
    skipping `enrich` is not the fix: the Estimate tab uses it, and a timeline
    that disagreed with the tab beside it would be worse than a slow one.

    So it is paid once. The result goes to `timeline.json` stamped with what
    it was computed against, and every later viewing is a file read.

    Derivations come from `cached_derive`, so under the default
    `--cache-behaviour all` every step is already on disk and the derive cost
    is zero. Under `extremities` or `none` they are recomputed at ~0.9s each -
    slower, but not an error, and the progress line says which is happening.
    """
    map_id = str(payload.get("map") or "").strip()
    if not map_id:
        raise ValueError("missing 'map'")
    jobs = as_int(payload, "jobs", 0)
    steps = _run_steps(map_id, ctx)

    def work(progress: Progress, _stop: StopCheck) -> dict[str, Any]:
        workers = jobs if jobs > 0 else (os.process_cpu_count() or 1)

        def report(done: int, total: int) -> None:
            # `k/N` is the shape `app.js`'s `countsIn` parses into a real bar.
            progress(f"{done}/{total} slices - {workers} workers")

        progress(f"0/1 slices - {workers} workers")
        added, totals = price_steps(
            map_id=map_id,
            held=[sorted(step.unlocked) for step in steps],
            jobs=jobs,
            root=ctx.root,
            on_progress=report,
        )
        cache.write_timeline(
            map_id,
            {
                "stamp": _timeline_stamp(ctx, enriched=dps_bridge.DPS_AVAILABLE),
                "added": added,
                "totals": totals,
            },
            ctx.root,
        )
        return {"map": map_id, "steps": len(added), "hours": round(totals[-1], 1)}

    return {"job": ctx.jobs.submit(f"timeline {map_id}", work).id}


def _cancel_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Ask a running job to stop.

    **The id is in the body, not the path**, so this joins `_ACTIONS` like
    every other action and inherits the `Sec-Fetch-Site`/`Host` checks rather
    than needing a second dispatch that could forget them.

    **A request, not a kill**, and the reply says so: the work stops where it
    safely can - `run_batch` finishes the roll it is on - so the job is still
    `running` when this answers and the page keeps polling. Cancelling a job
    that has already finished is a no-op rather than an error, because the
    button and the last poll race and "it had already finished" needs no
    handling by anyone.
    """
    job_id = str(payload.get("job") or "").strip()
    if not job_id:
        raise ValueError("missing 'job'")
    job = ctx.jobs.cancel(job_id)
    if job is None:
        raise cache.CacheMissError(f"no such job {job_id!r}")
    return {"job": job.id, "state": str(job.state), "stopping": job.stopping.is_set()}


def _refresh_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Re-download the reference data `fray chunkinfo` and `fray heuristics` get.

    Both in one action because they are one decision - the chunkinfo export and
    the wiki rates are the two static inputs, and refreshing one without the
    other leaves the estimator quoting numbers against a world that moved.
    """
    what = str(payload.get("what") or "chunkinfo")
    if what not in ("chunkinfo", "heuristics"):
        raise ValueError(f"unknown refresh target {what!r}")

    def work(progress: Progress, _stop: StopCheck) -> dict[str, Any]:
        if what == "chunkinfo":
            progress("downloading the chunk export (~10 MiB)")
            info = fetch_chunkinfo(DEFAULT_TIMEOUT)
            cache.write_blob(cache.CHUNKINFO_BLOB_NAME, info, CHUNKINFO_URL, ctx.root)
            progress("downloading the tasks map")
            tasks = fetch_tasks_map(DEFAULT_TIMEOUT)
            cache.write_blob(cache.TASKS_MAP_BLOB_NAME, tasks, TASKS_MAP_URL, ctx.root)
            # The export changed underneath us, so anything parsed from the old
            # one is now wrong. Dropping it is cheaper than reasoning about it.
            ctx.derivations.reset()
            return {"refreshed": "chunkinfo", "chunks": len(info.get("chunks", {}))}

        # `fray heuristics`, run through the same function so the two cannot
        # produce different files. Needs the export parsed - it asks the wiki
        # about the quests and slayer masters *this* export names.
        result = scrape(ctx.derivations.chunk_info(), timeout=DEFAULT_TIMEOUT, progress=progress)
        cache.write_blob(cache.WIKI_RATES_BLOB_NAME, result.config, SCRAPE_SOURCE, ctx.root)
        return {"refreshed": "heuristics", **result.as_dict()}

    return {"job": ctx.jobs.submit(f"refresh {what}", work).id}


def _remove_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Delete cached maps, or every simulated one.

    Fetched maps are refused unless `include_fetched` says otherwise, matching
    `fray maps rm`: a computed map records what made it, and a fetched one
    costs a round trip and is the thing everything else is derived from.
    """
    names = payload.get("names")
    include_fetched = bool(payload.get("include_fetched"))
    if payload.get("all"):
        removed = cache.remove_computed(ctx.root)
        return {"removed": removed}
    if not isinstance(names, list) or not names:
        raise ValueError("missing 'names' to remove")
    removed = []
    for name in names:
        cache.remove_map(str(name), ctx.root, include_fetched=include_fetched)
        removed.append(str(name))
    return {"removed": removed}


def _prune_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Age out cached derivations. Pure recomputation, so nothing is at risk."""
    # `None` means "all of them", which is what an omitted age asks for.
    raw = payload.get("older_than")
    older_than = None if raw is None or raw == "" else float(raw)
    dropped = cache.prune_derived(ctx.root, max_age_days=older_than)
    return {"dropped": len(dropped), "freed": sum(entry.size for entry in dropped)}


_ACTIONS: dict[str, Callable[[Mapping[str, Any], Context], dict[str, Any]]] = {
    "/api/fetch": _fetch_job,
    "/api/simulate": _simulate_job,
    "/api/unlock": _unlock_job,
    "/api/timeline": _timeline_job,
    "/api/cancel": _cancel_job,
    "/api/refresh": _refresh_job,
    "/api/maps/remove": _remove_job,
    "/api/derived/prune": _prune_job,
    "/api/window": _window_state,
}
