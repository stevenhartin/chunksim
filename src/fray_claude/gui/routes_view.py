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

from fray_claude.costing.estimate import (
    EstimateResult,
    TrainingOption,
    training_options,
)
from fray_claude.costing.inputs import load_heuristics
from fray_claude.derive.task_names import strip_task_markup
from fray_claude.runs.batch import PriceSpec, price_detail
from fray_claude.store.cache import CacheMissError
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


def roll_detail(map_id: str, index: int, ctx: Context) -> dict[str, Any] | None:
    """The hours behind one roll, broken down the way the Estimate tab is.

    **Computed on the click, not stored with the run.** `timeline.json` keeps
    one number per step because that is what the bars need, and a run of the
    real export opens 239 tasks in a single roll - storing every item and its
    hours for every step would be most of a megabyte written on every
    simulation, for a dialog most runs never open.

    So this prices two steps, `k-1` and `k`, through the same `_walk` the bars
    go through, and keeps the `EstimateResult` that `price_slice` throws away.
    On a run whose timeline has been computed both derivations are already in
    `cache/derived/`, which is the case this is fast in.

    `None` rather than an error when it cannot be priced - no export, no
    scraped rates, or step 0, which is a baseline and not a roll. The overlay
    then draws what it always drew; the pie is an addition, not a precondition.
    """
    steps = _run_steps(map_id, ctx)
    if not 0 < index < len(steps):
        return None
    # **Priced the way the bar was priced.** A run stores the wiki-rate answer
    # when it is simulated and only a reprice upgrades it, so enriching here
    # unconditionally would put a gear-priced pie under a wiki-priced bar and
    # invite the reader to trust the difference.
    added, _totals, enriched = _cached_hours(map_id, ctx)
    held = [sorted(steps[index - 1].unlocked), sorted(steps[index].unlocked)]
    try:
        result = price_detail(
            PriceSpec(
                map_id=map_id,
                steps=tuple((order, tuple(chunks)) for order, chunks in zip((index - 1, index), held)),
                root=ctx.root,
                chunkinfo_path=None,
                base=cache.read_base_payload(map_id, ctx.root),
                enrich=enriched if added is not None else True,
            )
        )
    except (CacheMissError, OSError):
        return None
    if result is None:
        return None
    options = _training_options_for(result, map_id, ctx)
    # **Two decimals, because `timeline.series` uses two.** The pie sits
    # directly under the bar it explains, so a total that renders as a
    # hundredth apart from it invites the reader to look for a reason there
    # is not one.
    return {
        "total_hours": round(sum(result.buckets.values()), 2),
        "buckets": {name: round(value, 2) for name, value in result.buckets.items()},
        # The rows behind the slices: what this roll actually put in front of
        # you, longest first, with the tasks each one answers.
        "items": [
            {
                "item": item.item,
                "hours": round(item.hours, 4),
                "bucket": item.bucket,
                "source": item.source,
                "tasks": [strip_task_markup(name) for name in item.tasks],
            }
            for item in sorted(result.items, key=lambda i: -i.hours)
        ],
        "quests": [
            {"task": strip_task_markup(task.task), "hours": round(task.hours, 4),
             "detail": task.detail}
            for task in sorted(result.tasks, key=lambda t: -t.hours)
        ],
        # **The whole skilling row, not just its hours.** "Herblore 13,034h" is
        # a number you have to take on trust; the rate, the method it came from
        # and the levels either side are the reasoning behind it, and `options`
        # is what the estimator knew about and could not use.
        "skills": [
            {
                **skill.as_dict(),
                "hours": round(skill.hours, 2),
                "options": [o.as_dict() for o in options.get(skill.skill, ())[:6]],
                "options_total": len(options.get(skill.skill, ())),
            }
            for skill in sorted(result.skills, key=lambda s: -s.hours)
            if skill.hours > 0
        ],
    }


def _training_options_for(
    result: EstimateResult, map_id: str, ctx: Context
) -> dict[str, tuple[TrainingOption, ...]]:
    """What else could have trained each skill this roll charged for.

    Needs the derivation and the rates the estimate was made against, which is
    a second load - so it is done once for the skills actually on screen, and
    returns `{}` rather than failing when anything is missing. A tooltip is
    worth a parse; it is not worth an error.
    """
    if not result.skills:
        return {}
    try:
        state = ctx.derivations.load(map_id)
        heuristics, _ = load_heuristics(state.state.chunk_info, ctx.root)
    except (CacheMissError, OSError):
        return {}
    return {
        skill.skill: training_options(
            state.derived, state.state.chunk_info, heuristics, skill.skill
        )
        for skill in result.skills
    }
