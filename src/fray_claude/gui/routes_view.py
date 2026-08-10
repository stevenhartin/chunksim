"""The cheap path: everything answerable without parsing the export.

`/api/{view,revision,summary,timeline,roll}` and the pieces they are built
from. **A request here is milliseconds, which is why nothing is cached**: the
map view needs only `chunks.unlocked`, since a chunk's square is fixed by its
id, so every request re-reads the map file and a `fray fetch` in another
terminal shows up in the browser two seconds later with no invalidation
machinery at all.

Keeping these in one module makes that property checkable rather than
remembered: **nothing in this file may call `ctx.derivations.load`.** The one
exception is `_areas_for`, which parses the export only when the unlocked set
holds a non-numeric id, and a test pins that the map view does not trigger it.

The timeline is here for the same reason. A run is self-contained - the state
before roll k is `final - rolls[k:]` - so replaying one needs no base map, no
export and no `derive`, which is what lets the slider redraw as you drag it.
"""

from __future__ import annotations

from fray_claude.runs.timeline import matches as timeline_matches
from fray_claude.runs.timeline import stamp as timeline_stamp

from typing import Any
from fray_claude.gui.worldmap import MapView
from collections.abc import Mapping
from fray_claude.runs.timeline import Step
from fray_claude.model.summary import _mapping
from fray_claude.gui.worldmap import build_view
from fray_claude.store import cache
from fray_claude.derive.delta import diff_names
from fray_claude.costing import dps_bridge
from fray_claude.runs.timeline import replay
from fray_claude.runs.timeline import series


from fray_claude.gui.derivation import unlocked_of
from fray_claude.gui.http import Context


def _unlocked(map_id: str, ctx: Context) -> tuple[dict[str, Any], int]:
    """One map's unlocked set and the mtime that dates it.

    The mtime is the live-reload token. It is deliberately not a hash of the
    payload: a `stat` is cheaper than a read, and the cost of a false positive
    is one redraw the user cannot see.
    """
    path = cache.resolve_map_path(map_id, ctx.root)
    envelope = cache.read_cache(map_id, ctx.root)
    revision = path.stat().st_mtime_ns
    return unlocked_of(envelope), revision


def _areas_for(unlocked: Mapping[str, Any], ctx: Context) -> dict[str, str] | None:
    """`chunkinfo.area_names()`, but **only when something needs it**.

    Resolving `Abyss` to the regions it occupies needs the 10MB export parsed,
    and the whole reason `/api/view` is milliseconds is that it does not do
    that. So the parse is conditional on the map actually holding a
    non-numeric id: every ordinary map has none, keeps the fast path, and a
    test pins that. A map that *does* hold one has no cheaper way to be drawn
    correctly, and pays about a second, once.
    """
    if not any(not chunk_id.isdigit() for chunk_id in unlocked):
        return None
    return ctx.derivations.chunk_info().area_names()


def build_map_view(
    map_id: str, compare: str | None, ctx: Context, step: int | None = None
) -> MapView:
    """The payload for one map, or for one map against another.

    `map_id` is the base and `compare` the other side, so `added` is what
    `compare` has and the base does not. That matches
    `fray diff --map1 <base> --map2 <compare> chunks` exactly.

    `step` rewinds a simulated run to the world after that many rolls. It is
    **exclusive of `compare`** - a comparison asks about two maps and a step
    asks about one map's past, and answering both at once would need a third
    colour for "gained by the roll, lost against the other side".
    """
    if step is not None:
        return _step_view(map_id, step, ctx)

    base, revision = _unlocked(map_id, ctx)
    if compare is None:
        return build_view(
            map_id=map_id,
            unlocked=base,
            revision=revision,
            areas=_areas_for(base, ctx),
        )

    other, other_revision = _unlocked(compare, ctx)
    branch = diff_names(base, other)
    return build_view(
        map_id=map_id,
        unlocked=base,
        added=branch.added,
        removed=branch.removed,
        compare_map_id=compare,
        # Either side changing has to invalidate the view, so the token spans
        # both. Summing is enough - it moves whenever either mtime does.
        revision=revision + other_revision,
        areas=_areas_for({**base, **other}, ctx),
    )


def _run_steps(map_id: str, ctx: Context) -> tuple[Step, ...]:
    """One run replayed, or `CacheMissError` when the map is not a run.

    **No export, no derivation** - the ledger and the saved payload are the
    whole input, which is what makes dragging the slider a JSON read. See
    `timeline.py`; a test asserts this route never loads `ChunkInfo`.
    """
    envelope = cache.read_cache(map_id, ctx.root)
    return replay(unlocked_of(envelope), cache.read_rolls(map_id, ctx.root))


def _step_view(map_id: str, step: int, ctx: Context) -> MapView:
    """The world after `step` rolls of a simulated run.

    Everything the run has rolled *so far* is `added`, so the simulation's
    growth accumulates green against the map it started from and the hull
    traces the world as it stood. No new drawing concept: `added` already
    means "this side has it and the base does not", and here the base is the
    run's own past.
    """
    steps = _run_steps(map_id, ctx)
    if not 0 <= step < len(steps):
        raise ValueError(f"step {step} is outside this run's 0..{len(steps) - 1}")
    unlocked = {chunk_id: True for chunk_id in sorted(steps[step].unlocked)}
    return build_view(
        map_id=map_id,
        unlocked=unlocked,
        added=[s.chunk_id for s in steps[1 : step + 1] if s.chunk_id],
        revision=cache.resolve_map_path(map_id, ctx.root).stat().st_mtime_ns,
        areas=_areas_for(unlocked, ctx),
    )


def _timeline_stamp(ctx: Context, *, enriched: bool) -> dict[str, Any]:
    """What a stored hours series was computed against. See `timeline.stamp`.

    `enriched` says whether `dps_bridge` priced these numbers. It is recorded
    but **not compared**, because a simulation prices its own rolls with the
    estimator alone - free, since the derivation is already done - and paying
    `enrich`'s ~1.3s a roll would have tripled every batch. So the cheap
    answer is what a run is born with, and this is the upgrade.
    """
    digests = ctx.derivations.digests()
    return timeline_stamp(
        chunkinfo=digests.chunkinfo,
        tasks_map=digests.tasks_map,
        rates=cache.file_digest(cache.blob_path(cache.WIKI_RATES_BLOB_NAME, ctx.root)),
        overrides=_overrides_digest(ctx),
        enriched=enriched,
    )


def _overrides_digest(ctx: Context) -> str:
    """`heuristics/overrides.json` is checked in and hand-edited, so it moves
    without any fetch having happened - which is exactly the case a digest of
    the *fetched* inputs alone would miss."""
    try:
        return cache.file_digest(cache.overrides_path(ctx.root))
    except (OSError, cache.CacheMissError):
        return ""


def _floats(value: Any) -> list[float] | None:
    if not isinstance(value, list) or not all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in value
    ):
        return None
    return [float(v) for v in value]


def _cached_hours(
    map_id: str, ctx: Context
) -> tuple[list[float] | None, list[float] | None, bool]:
    """A run's stored hours - what each roll added, what was left - and whether
    `dps_bridge` priced them.

    A stamp mismatch reads as absent rather than as an error: the numbers are
    recomputable, and offering to recompute is a better answer than refusing
    to draw anything. **A file without `added` is one written under the old
    delta-of-totals meaning**, and is refused for the same reason - the bars
    would be drawn under a meaning they were never computed for.
    """
    try:
        stored = cache.read_timeline(map_id, ctx.root)
    except cache.CacheMissError:
        return None, None, False
    if not timeline_matches(stored.get("stamp"), _timeline_stamp(ctx, enriched=False)):
        return None, None, False
    added = _floats(stored.get("added"))
    if added is None:
        return None, None, False
    enriched = bool(_mapping(stored, "stamp").get("enriched"))
    return added, _floats(stored.get("totals")), enriched


def _timeline_payload(map_id: str, ctx: Context) -> dict[str, Any]:
    """The cheap half: every step, plus whatever hours are already on disk.

    **This must not parse the export.** The steps come from the ledger and the
    saved payload, and the hours come off disk or not at all - which is what
    lets the slider redraw at JSON-read speed. `_cached_hours` reads a digest
    stamp, which needs `Derivations.digests()`, and that reads file hashes
    rather than the file: no `ChunkInfo`, and a test pins it.
    """
    steps = _run_steps(map_id, ctx)
    added, totals, enriched = _cached_hours(map_id, ctx)
    rows = series(steps, totals=totals, added=added)
    # **Read back off the shaped rows, not off the stored list.** `series`
    # refuses a totals list that does not fit the run - a run re-rolled under
    # one name has a different number of steps - so asking the store instead
    # would let the flag promise hours the graph never got.
    has_hours = any(row["hours"] is not None for row in rows)
    return {
        "map_id": map_id,
        "steps": rows,
        "has_hours": has_hours,
        "enriched": enriched and has_hours,
        # Whether there is a better answer available than the one on screen.
        # Without the extra there is not, however the numbers were computed.
        "can_enrich": dps_bridge.DPS_AVAILABLE and not (enriched and has_hours),
        "dps": dps_bridge.DPS_AVAILABLE,
    }
