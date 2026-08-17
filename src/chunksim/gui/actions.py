"""The eleven POST actions, and the job registry they hand work to.

`fetch`, `simulate`, `unlock`, `commit`, `snapshot`, `timeline`, `cancel`,
`refresh`,
`maps/remove`, `derived/prune`, `window`. `_ACTIONS` is the dispatch table
`server._handle_post` looks them up in - it was already a table before this
split, which is why this module needed no routing invented for it.

**An action's reply shape decides whether the page polls it.**
`fetch`/`simulate`/`unlock`/`commit`/`timeline`/`refresh` return a job id and report
progress while a thread does the work; `maps/remove`/`derived/prune`/`window`/
`cancel` do the work and return the result. Reading `{ job }` off all of them
polled `/api/jobs/undefined`, whose 404 silently swallowed the refresh callback
and left deleted maps on screen.

`cancel` is a *request*, not a kill: the work stops where it safely can, so the
job stays `running` until it agrees, and it ends `CANCELLED` rather than
`FAILED` - the user did it, and what it kept is an ordinary cached map.
"""

from __future__ import annotations

from chunksim.remote.scrape import SOURCE as SCRAPE_SOURCE
from chunksim.remote.scrape import scrape_recipes

from typing import Any
from chunksim.remote.api import CHUNKINFO_URL
from collections.abc import Callable
from chunksim.remote.api import DEFAULT_TIMEOUT
from collections.abc import Mapping
from chunksim.gui.jobs import Progress
from chunksim.runs.batch import RunResult

from chunksim.gui.jobs import StopCheck
from chunksim.remote.api import TASKS_MAP_URL
from chunksim.gui.jobs import as_int
from chunksim.model.rules import default_rules
from chunksim.remote.api import FetchError, RELEASES_URL, fetch_latest_release
from chunksim.store.cache import CacheMissError
from chunksim.store.build_info import is_newer, read_build
from chunksim.store import cache
from chunksim.store.derived_cache import cached_derive
from chunksim.costing import dps_bridge
from chunksim.remote.api import fetch_chunkinfo
from chunksim.remote.api import fetch_map
from chunksim.remote.api import fetch_tasks_map
import os
import subprocess
import sys
from pathlib import Path
from chunksim.runs.batch import price_steps
from chunksim.runs.batch import run_batch
from chunksim.runs.batch import save_edit, save_snapshot, save_unlock
from chunksim.remote.scrape import scrape
from chunksim.gui import knobs, settings
from chunksim.gui.http import Context
from chunksim.gui.routes_view import _run_steps
from chunksim.gui.routes_view import _timeline_stamp
from chunksim.gui.routes_view import resolve_knob


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


def _settings_state(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Save the interface's preferences and answer with what was saved.

    **Answers inline rather than with a job id**, which is not a style choice:
    `app.js` polls any reply carrying a `job` key, so a handler that finishes
    its work immediately must not look like one that has not started.

    The reply is the *stored* settings, not the payload - `settings.sanitise`
    may have refused part of what was sent, and the page redrawing from the
    answer is what makes that visible rather than silent.
    """
    settled = settings.sanitise(payload, cache.read_gui_settings(ctx.root))
    cache.write_gui_settings(settled, ctx.root)
    return settled


def _heuristic_state(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Write one override, and answer with the knob as it now stands.

    **Answers inline**, for `_settings_state`'s reason: `app.js` polls any
    reply carrying a `job` key.

    `scope` decides which file, and the page decides `scope` from its mode -
    Browse is the standing opinion and writes `heuristics/overrides.json`;
    Timeline and Edit are about one map and write its own. Both are ordinary
    merged config, so the same path addresses the same thing in either.

    The reply is the *resolved* knob rather than an acknowledgement, so the
    page redraws from what was stored. A refused value raises, which
    `_handle_post` turns into a 400 - visible, where a 200 saying nothing
    happened is the silent-refusal failure `settings.py` already records.
    """
    path = str(payload.get("path") or "")
    scope = str(payload.get("scope") or "")
    if scope not in knobs.SCOPES:
        raise ValueError(f"scope must be one of {', '.join(knobs.SCOPES)}")
    raw = payload.get("value")
    if raw is not None and (isinstance(raw, bool) or not isinstance(raw, (int, float))):
        raise ValueError("value must be a number, or null to clear the override")
    number = None if raw is None else float(raw)

    if scope == "site":
        current = cache.read_overrides(ctx.root)
        cache.write_overrides(knobs.written(path, number, current), ctx.root)
    else:
        map_id = str(payload.get("map") or "")
        if not map_id:
            raise ValueError("a map-scoped override needs a map")
        current = cache.read_map_overrides(map_id, ctx.root)
        cache.write_map_overrides(map_id, knobs.written(path, number, current), ctx.root)
    # The memo watches both files' mtimes, but dropping it here means the very
    # next request cannot race the stat's resolution - this is the one writer,
    # so it is the one place that knows for certain something moved.
    ctx.derivations.forget_reference()
    return resolve_knob(path, str(payload.get("map") or ""), ctx)


#: **A development escape hatch, deliberately unadvertised.** Typed into the
#: fetch box it builds a map holding every chunk a roll could ever land on,
#: which is the map several of this project's measurements are quoted against -
#: "with every chunk unlocked and every level at 99" appears half a dozen times
#: in `CLAUDE.md` and was, until now, a Python snippet somebody had to rewrite
#: each time.
#:
#: It is not in the README, not in the placeholder and not in any tooltip, and
#: it is refused unless the server is bound to loopback alone - `allowed_hosts`
#: is empty exactly then, since `--host`/`--allow-host` are the only things
#: that fill it. So it is available where the person running the server is the
#: person reading the page, and nowhere else. That is the whole of the guard
#: and it is worth being clear about: it is not a permission system, it is a
#: statement that this is a local tool.
UBER_MAP_SENTINEL = "__UBER__"


def _uber_map(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Every *rollable* chunk, unlocked, on top of whichever map is open.

    **The base matters, so it is required rather than defaulted**: a map
    carries the player's `rules`, their `maxSkill` and their completed
    challenges, and an "everything unlocked" map is only useful as *this* map
    with the chunk constraint removed. Written as an ordinary edit, because
    that is what it is - a map this project made by hand from another one - so
    it removes, browses, diffs and edits like any other.

    **Rollable is `chunkinfo['sections']`, not `chunkinfo['chunks']`**, and the
    difference is the whole point of this being a ceiling worth measuring
    against. The export lists 2,234 chunks and only 1,172 have a sections
    entry; the rest are 747 unwalkable squares and **315 named areas** - the
    Abyss, Ape Atoll Dungeon, Pyramid Plunder, a player-owned house. A roll can
    never land on any of them: `derive/neighbours.py` requires a sections entry
    before a chunk is even a candidate, and measured, no fetched map holds a
    single non-numeric id.

    So unlocking all 2,234 built a state no player can be in, and it showed:
    it made 11,135 tasks valid where the rollable set makes 10,111, and forty
    of the difference were Prayer tasks that **the reference map does not have
    either**. A ceiling is only useful if a player could stand on it.
    """
    if ctx.allowed_hosts:
        raise ValueError("the uber map is a loopback-only development tool")
    base = str(payload.get("base") or "").strip()
    if not base:
        raise ValueError("the uber map needs a base map to build on")
    envelope = cache.read_cache(base, ctx.root)
    info = ctx.derivations.chunk_info()
    held = envelope["data"].get("chunks", {}).get("unlocked") or {}
    chunks = [chunk_id for chunk_id in info.sections if chunk_id not in held]
    if not chunks:
        raise ValueError(f"{base!r} already holds every chunk")

    def work(progress: Progress, _stop: StopCheck) -> dict[str, Any]:
        progress(f"unlocking {len(chunks)} chunks")
        saved = save_edit(
            name=f"{base.replace('/', '-')}-uber",
            payload=envelope["data"],
            ticked={},
            unlocked=chunks,
            base_map=base,
            base_fetched_at=envelope.get("fetched_at"),
            root=ctx.root,
        )
        return {**saved.as_dict(), "map": saved.name, "open": saved.name}

    return {"job": ctx.jobs.submit(f"uber map from {base}", work).id}


def _fetch_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Download any named map from Firebase, not only the one on screen.

    **An empty name is refused rather than defaulted.** There is no house map
    id to fall back on - a fetch names someone's world on a public database,
    and guessing whose is not this project's business. The CLI's `fetch` is
    the same shape: `--map` is required there for the same reason.
    `cache.split_map_id` is what makes the name safe to accept from a browser
    at all - it rejects anything that is not `[A-Za-z0-9_.-]+`, so no second,
    weaker check belongs here.
    """
    map_id = str(payload.get("map") or "").strip()
    if not map_id:
        raise ValueError("type the map id to fetch")
    if map_id == UBER_MAP_SENTINEL:
        return _uber_map(payload, ctx)
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


def _blank_map(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """A map with nothing unlocked, for someone who has no map yet.

    **The point is that the world is browsable before you own anything.** With
    no map cached at all the page has nothing to draw and no way in; this gives
    it a real map to open, in edit mode, where any square can be unlocked by
    hand - `_unlock_job` and the front end already decline to check eligibility
    on an edit, which is what makes a first chunk possible at all (a map with
    nothing unlocked has no eligible neighbours by definition).

    **It seeds upstream's own rules rather than leaving the branch empty**, and
    that is not tidiness: a missing rule key skips its gate where `False`
    refuses it, so `rules={}` is the most permissive map there is - 526
    obtainable items on a three-chunk world against 3 for a real one. See
    `model/rules.py`, which owns the table and the measurement.

    Answers **inline rather than as a job**: it writes four small files and
    does no network, and the page needs the claimed name back in the same
    breath because `claim_batch` suffixes `untitled-2` when the last draft is
    still there.
    """
    name = str(payload.get("name") or "untitled").strip() or "untitled"
    saved = save_edit(
        name=name,
        # Forked from nothing, which is the honest answer and what `base_map`
        # is asked for. It is metadata; no code reads it back as a map id.
        payload={"rules": default_rules()},
        ticked={},
        unlocked=[],
        base_map="",
        root=ctx.root,
    )
    return {"map": saved.name, "open": saved.name}


def _update_state(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Whether a newer `chunksim` has been published.

    **Every failure is silent, and that is the design.** An update check
    interrupting someone to say it could not reach GitHub is worse than one
    that quietly does not run: nobody asked, and nothing they were doing
    depends on the answer. So a network error, a private or release-less
    repository, and a version neither side could parse all come back the same
    way - `available: false`, no error text, no toast.

    Answers **inline**: it is one small GET behind a day-long cache, so a job
    id would buy a poll for something usually already on disk.
    """
    build = read_build()
    answer: dict[str, Any] = {"current": build.version, "available": False, "latest": None}
    if not settings.sanitise({}, cache.read_gui_settings(ctx.root)).get("update_check"):
        return {**answer, "checked": False, "why": "disabled"}

    fresh = bool(payload.get("force"))
    remembered: dict[str, Any] | None = None
    if not fresh:
        try:
            remembered, age = cache.read_update(ctx.root)
            fresh = age > cache.UPDATE_MAX_AGE_HOURS
        except CacheMissError:
            fresh = True

    if fresh:
        try:
            release = fetch_latest_release()
        except FetchError:
            # Nothing to say and nothing to remember: a failed check must not
            # write a "no update" that then stands for a day.
            return {**answer, "checked": False, "why": "unreachable"}
        remembered = release.as_dict() if release else {}
        cache.write_update(remembered, RELEASES_URL, ctx.root)

    latest = (remembered or {}).get("version")
    if not isinstance(latest, str) or not is_newer(latest, build.version):
        return {**answer, "checked": True}
    return {
        **answer,
        "checked": True,
        "available": True,
        "latest": latest,
        "url": (remembered or {}).get("url") or "",
        # Present only when this platform can act on it, so the page does not
        # have to know what an installer is.
        "installer": (remembered or {}).get("installer") if sys.platform == "win32" else None,
    }


def _update_install_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Download the published installer, check it, and hand over to it.

    **User-initiated only.** Nothing here runs on a timer or on boot; the page
    calls this because someone pressed a button next to a version number they
    were shown.

    **The digest is checked before anything is executed**, against what the
    release API reported beside the download URL. HTTPS with certificate
    validation is what makes that digest trustworthy in the first place; the
    hash is what catches a truncated or substituted download afterwards. An
    asset with no digest is **refused** rather than run on the strength of the
    transport alone, and a mismatch deletes the file rather than keeping it
    around to be found later.

    The installer is written to a temporary directory, never to `cache/`:
    nothing under there is executable, and an unpacked `.exe` sitting in a data
    directory is a thing waiting to be run by accident.
    """
    if sys.platform != "win32":
        raise ValueError("the installer is a Windows build")
    asset = payload.get("installer")
    if not isinstance(asset, Mapping):
        raise ValueError("no installer was offered")
    url, digest = asset.get("url"), asset.get("digest")
    name = str(asset.get("name") or "chunksim-setup.exe")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise ValueError("the installer URL is not https")
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise ValueError("the release published no checksum for the installer")

    def work(progress: Progress, _stop: StopCheck) -> dict[str, Any]:
        import hashlib
        import tempfile
        import urllib.request

        progress(f"downloading {name}")
        directory = Path(tempfile.mkdtemp(prefix="chunksim-update-"))
        # `Path(name).name` strips any directory the release put in the asset
        # name, so a hostile one cannot write outside the temporary directory.
        target = directory / Path(name).name
        with urllib.request.urlopen(url, timeout=300.0) as response:
            target.write_bytes(response.read())

        progress("checking the download")
        got = hashlib.sha256(target.read_bytes()).hexdigest()
        if got != digest.removeprefix("sha256:"):
            target.unlink(missing_ok=True)
            raise ValueError("the download did not match its published checksum")

        progress("starting the installer")
        # `/SILENT` is Inno Setup's: a progress window, no questions. The
        # installer replaces files this process has open, so the server has to
        # go - and it says so before it does, because the page is about to
        # lose its connection and should not read that as a crash.
        # Detached, or the installer dies with the server it was started from.
        subprocess.Popen(
            [str(target), "/SILENT"],
            close_fds=True,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        ctx.stopping[0] = True
        return {"installing": name, "path": str(target)}

    return {"job": ctx.jobs.submit("update", work).id}


def _simulate_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Roll a batch of simulated futures, as a job the page polls.

    **Wide by default, like the command line**, because a run is tens of
    seconds of `derive` and the runs do not depend on each other. What that
    costs is the Stop button's precision: `run_batch` can only check between
    runs once it pools, since a submitted future is already inside a worker
    with no channel back. So stopping a 10x50 batch lands within a run rather
    than within a roll - a handful of seconds, not instant. A single run still
    executes inline and still stops on the roll.
    """
    map_id = str(payload.get("map") or "").strip()
    name = str(payload.get("name") or "").strip()
    if not map_id:
        raise ValueError("missing 'map'")
    if not name:
        raise ValueError("missing 'name' for the simulated map")
    rolls = as_int(payload, "rolls", 1)
    runs = as_int(payload, "runs", 1)
    # **0, the same default the command line carries.** A run is tens of
    # seconds of `derive` and the runs are independent, so a batch started
    # from the page should use the machine; `runs/batch.py` keeps the
    # conservative default for callers who did not ask.
    jobs = as_int(payload, "jobs", 0)
    # Resolved the way `run_batch` resolves it, so the page reports at the
    # granularity the batch actually runs at rather than guessing.
    workers = jobs if jobs > 0 else (os.process_cpu_count() or 1)
    inline = workers == 1 or runs == 1
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

        # **Says how wide it is running, because that is the other half of
        # "why is this taking so long".** Sixteen workers on fifty rolls and
        # one worker on fifty rolls are the same bar and very different waits.
        where = f" on {min(workers, runs)} workers" if not inline else ""

        def roll(_run: int, _order: int, chunk_id: str) -> None:
            nonlocal rolled
            rolled += 1
            # Pooled, rolls arrive from several runs at once and out of order,
            # so the chunk name would flicker between unrelated worlds. The
            # count is the honest thing to show; the name belongs to the one
            # run that is inline.
            detail = f" - {chunk_id}" if inline else f" - {finished}/{runs} runs{where}"
            progress(f"{rolled}/{total} rolls{detail}" + (" - stopping" if stop() else ""))

        def report(result: RunResult) -> None:
            nonlocal finished, rolled
            finished += 1
            # Rolls are counted as they happen now, pooled or not, so this no
            # longer has to catch the count up - it only guards against a run
            # that reported nothing at all.
            rolled = max(rolled, finished * rolls)
            # Inline, every roll already produced a line and this would only
            # repeat the last one with a run tally bolted on.
            if not inline:
                progress(f"{rolled}/{total} rolls - {finished}/{runs} runs{where}")

        progress(f"0/{total} rolls{where}")
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
            # **Pooled too, now.** `run_batch` carries a worker's rolls back
            # over a manager queue, so a fifty-roll batch ticks up rather than
            # standing still until a whole run lands.
            on_roll=roll,
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
    """`chunksim unlock --chunk X --cache-map NAME`: add one chunk by hand.

    **The same path as `GET /api/unlock`, one step further on.** The GET
    answers "what would this give me" and keeps nothing; this saves the world
    it was describing. Both derive twice, which is why this is a job rather
    than an inline action even though the write itself is instant - cold, the
    export parse alone is a second.

    The eligibility check is deliberately *not* made: `chunksim unlock` will price
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
        from chunksim.derive.unlock import tasks_added_by

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


def _commit_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Save the browser's pending edits as a new map.

    **The edits live in the browser until this is pressed**, which is what
    makes edit mode cheap: a ticked task greys out and an unlocked chunk lights
    up with no derivation at all, and exactly one derivation happens - here, on
    the world that results. A preview that re-derived per tick would cost ~0.8s
    a click and answer a question nobody asked halfway through.

    Job-shaped although it derives nothing itself: the page polls
    `fetch`/`simulate`/`unlock` and an action that replied differently would be
    a second protocol for no reason. **The claimed name comes back as `open`**,
    since `claim_batch` suffixes a clash and the name that landed is not
    always the name that was typed.
    """
    map_id = str(payload.get("map") or "").strip()
    if not map_id:
        raise ValueError("missing 'map'")
    # **An edited map is edited, not re-forked.** A fetched map is upstream's
    # and immutable, so the first change forks it; every change after that is
    # a change to the map you made, and minting `-2`, `-3`, `-4` down a chunk
    # you were planning is a new map per click rather than a map you are
    # working on. The page asks for `replace` when the base is already an
    # edit, and the kind is checked here because a browser cannot be the
    # authority on what it is allowed to overwrite.
    replace = bool(payload.get("replace")) and cache.read_cache(
        map_id, ctx.root
    ).get("kind") == cache.EDITED
    name = map_id if replace else (str(payload.get("name") or "").strip() or f"{map_id}-edit")

    raw_ticked = payload.get("ticked") or {}
    if not isinstance(raw_ticked, Mapping):
        raise ValueError("'ticked' must be an object of category -> task names")
    ticked = {
        str(category): [str(task) for task in names]
        for category, names in raw_ticked.items()
        if isinstance(names, (list, tuple)) and names
    }
    raw_unlocked = payload.get("unlocked") or []
    if not isinstance(raw_unlocked, (list, tuple)):
        raise ValueError("'unlocked' must be a list of chunk ids")
    unlocked = [str(chunk).strip() for chunk in raw_unlocked if str(chunk).strip()]
    if not ticked and not unlocked:
        raise ValueError("nothing to commit")

    # Read the base map now, so a bad id fails the POST rather than the job.
    envelope = cache.read_cache(map_id, ctx.root)
    held = envelope["data"].get("chunks", {}).get("unlocked", {})
    if isinstance(held, Mapping):
        already = [chunk for chunk in unlocked if chunk in held]
        if already:
            raise ValueError(f"already unlocked on {map_id}: {', '.join(sorted(already))}")

    def work(progress: Progress, _stop: StopCheck) -> dict[str, Any]:
        progress(f"writing {name}")
        saved = save_edit(
            name=name,
            payload=envelope["data"],
            ticked=ticked,
            unlocked=unlocked,
            base_map=map_id,
            base_fetched_at=envelope.get("fetched_at"),
            replace=replace,
            root=ctx.root,
        )
        return {**saved.as_dict(), "open": saved.name}

    ticks = sum(len(names) for names in ticked.values())
    return {"job": ctx.jobs.submit(f"commit {ticks} ticks, {len(unlocked)} chunks", work).id}


def _snapshot_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Save the world at roll `step` of a run as a map in its own right.

    **This is the way out of a timeline.** A run is a sequence of worlds and
    can only be seen in timeline mode, which means it cannot be diffed, edited
    or browsed - so the answer to "I want to work with *this* roll" is to make
    it a real map, after which it behaves like any other. That is what gives
    the feature a purpose beyond convenience and lets the invariant stay
    absolute.

    **No derivation at all.** The state after `k` rolls is the base payload
    with those rolls applied, and `simulate.simulated_payload` reads only
    `chunk_id` from a record - so the arithmetic is a truncation, not a
    replay. `UnlockRecord` has no `from_dict` and `as_dict` is lossy
    (`bis_upgrades` is reshaped, `new_unsupported` sorted), so the records fed
    to it are synthetic while the ledger *written out* is the run's own dicts,
    truncated. That way the snapshot's own timeline is the real one rather
    than a hollowed-out copy.
    """
    map_id = str(payload.get("map") or "").strip()
    if not map_id:
        raise ValueError("missing 'map'")
    try:
        step = int(payload.get("step"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError("missing or non-numeric 'step'") from None

    rolls = cache.read_rolls(map_id, ctx.root)
    if not 0 < step <= len(rolls):
        # Step 0 is the baseline, which is the base map and not a snapshot.
        raise ValueError(f"step {step} is outside this run's 1..{len(rolls)}")
    base = cache.read_base_payload(map_id, ctx.root)
    if base is None:
        raise ValueError(f"{map_id} does not record the payload it was rolled from")

    kept = rolls[:step]
    chunks = [str(roll.get("chunk_id") or "") for roll in kept]
    if not all(chunks):
        raise ValueError(f"{map_id}'s ledger has a roll with no chunk")
    name = str(payload.get("name") or "").strip() or f"{map_id.replace('/', '-')}-at-{step}"

    def work(progress: Progress, _stop: StopCheck) -> dict[str, Any]:
        progress(f"writing {name}")
        saved = save_snapshot(
            name=name,
            base_payload=base,
            ledger=kept,
            chunks=chunks,
            base_map=map_id,
            root=ctx.root,
        )
        return {**saved.as_dict(), "step": step, "open": saved.name}

    return {"job": ctx.jobs.submit(f"snapshot {map_id} at {step}", work).id}


def _timeline_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Re-price every step of a run, and store the answer beside its ledger.

    **A re-price, not the price.** A run prices itself as it finishes, on the
    same basis the Estimate tab uses and through the same `_priced_series`, so
    this is normally not needed at all and the page hides the button. What is
    left for it are the three ways a stored series can stop describing the
    world: the reference data moved, the `dps` extra was installed since, or
    the run predates the current `timeline.PRICING_MODEL`.

    It is still a job rather than an inline answer. Per slice it is one
    `priced_heuristics` at ~1.3s - of which ~0.7s is `osrs_dps` simulating
    every reachable fight - against ~7.9ms for each step's `estimate`, and
    `price_steps` spreads the slices across every core. The result goes to
    `timeline.json` stamped with what it was computed against, and every later
    viewing is a file read.

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



def _blob_present(what: str, ctx: Context) -> bool:
    """Is the blob an `auto` refresh would fetch already on disk?

    A `stat`, not a read: the question is whether to start a scrape, and
    parsing 1.7MB of recipes to answer it would cost more than the answer is
    worth. `routes_reference._reference_state` takes the same line.

    **`blob_source`, so a shipped config counts as present.** The wiki-derived
    blobs are checked in and packaged now (`cache.SHIPPED_BLOB_NAMES`), so an
    ordinary install already holds them and an `auto` refresh has nothing to
    fetch. Asking `blob_path` instead would send every fresh install to the
    wiki for data it was distributed with, which is the whole thing that
    move was for.
    """
    name = {
        "chunkinfo": cache.CHUNKINFO_BLOB_NAME,
        "heuristics": cache.WIKI_RATES_BLOB_NAME,
        "recipes": cache.RECIPES_BLOB_NAME,
    }[what]
    return cache.blob_source(name, ctx.root).is_file()


def _refresh_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Re-download the reference data `chunksim chunkinfo`, `chunksim heuristics` and
    `chunksim recipes` get.

    One action because they are one decision - the export, the scraped rates
    and the per-action recipe data are the static inputs, and refreshing one
    without the others leaves the estimator quoting numbers against a world
    that moved.
    """
    what = str(payload.get("what") or "chunkinfo")
    if what not in ("chunkinfo", "heuristics", "recipes"):
        raise ValueError(f"unknown refresh target {what!r}")

    # **An `auto` refresh is the page's idea, not the user's.** The front end
    # warms the two wiki blobs on boot so a fresh cache does not open on
    # fallback numbers, which is worth about sixty requests once. It is not
    # worth them again on every reload, and a scrape that fails should say so
    # and stop rather than restart itself each time a tab opens - so this
    # answers "already there" or "already tried" without starting a job. A
    # button press sends no `auto` and is never refused.
    if payload.get("auto") is True:
        # **The export is checked like the other two.** It used to be exempt,
        # from when nothing auto-refreshed it - and the exemption was a
        # 10 MiB re-download once per server process the moment the first-run
        # flow started warming it, since `claim_once` only stops the *second*
        # attempt in a process.
        if _blob_present(what, ctx):
            return {"skipped": what, "why": "cached"}
        if not ctx.jobs.claim_once(f"refresh {what}"):
            return {"skipped": what, "why": "attempted"}

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

        if what == "recipes":
            # `chunksim recipes`, through the same function for the same reason.
            # Needs no export: a Bucket query per skill and nothing joined
            # until something prices with it.
            progress("downloading per-action recipe data")
            recipes = scrape_recipes(timeout=DEFAULT_TIMEOUT)
            cache.write_blob(cache.RECIPES_BLOB_NAME, recipes, SCRAPE_SOURCE, ctx.root)
            # Paired with the write on purpose. `Derivations.reference` would
            # notice on its own - it stamps the files - but a refresh that
            # forgets to say so is exactly how a memo starts serving numbers
            # from before it.
            ctx.derivations.forget_reference()
            return {"refreshed": "recipes", "skills": len(recipes)}

        # `chunksim heuristics`, run through the same function so the two cannot
        # produce different files. Needs the export parsed - it asks the wiki
        # about the quests and slayer masters *this* export names.
        result = scrape(ctx.derivations.chunk_info(), timeout=DEFAULT_TIMEOUT, progress=progress)
        cache.write_blob(cache.WIKI_RATES_BLOB_NAME, result.config, SCRAPE_SOURCE, ctx.root)
        ctx.derivations.forget_reference()
        return {"refreshed": "heuristics", **result.as_dict()}

    return {"job": ctx.jobs.submit(f"refresh {what}", work).id}


def _remove_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Delete cached maps, or every simulated one.

    Fetched maps are refused unless `include_fetched` says otherwise, matching
    `chunksim maps rm`: a computed map records what made it, and a fetched one
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
    "/api/blank": _blank_map,
    "/api/update": _update_state,
    "/api/update/install": _update_install_job,
    "/api/simulate": _simulate_job,
    "/api/unlock": _unlock_job,
    "/api/commit": _commit_job,
    "/api/snapshot": _snapshot_job,
    "/api/timeline": _timeline_job,
    "/api/cancel": _cancel_job,
    "/api/refresh": _refresh_job,
    "/api/maps/remove": _remove_job,
    "/api/derived/prune": _prune_job,
    "/api/window": _window_state,
    "/api/settings": _settings_state,
    "/api/heuristic": _heuristic_state,
}
