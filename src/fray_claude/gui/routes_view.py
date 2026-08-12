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

from fray_claude.costing.estimate import EstimateResult
from fray_claude.costing.training import TrainingOption, training_options
from fray_claude.costing.inputs import load_heuristics
from fray_claude.derive.active_tasks import _level_proven_elsewhere
from fray_claude.derive.task_names import strip_task_markup
from fray_claude.runs.batch import PriceSpec, _Prepared, price_detail
from fray_claude.store.cache import CacheMissError
from fray_claude.runs.timeline import matches as timeline_matches
from fray_claude.runs.timeline import stamp as timeline_stamp

from typing import Any
from fray_claude.gui.panels import roll_panel
from fray_claude.gui.worldmap import MapView
from collections.abc import Mapping
from fray_claude.runs.timeline import Step
from fray_claude.model.summary import _mapping
from fray_claude.gui.worldmap import build_view
from fray_claude.store import cache
from fray_claude.derive.delta import diff_names
from fray_claude.costing import dps_bridge
from fray_claude.runs.timeline import replay
from fray_claude.runs.timeline import rolled_chunks
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


def roll_record(map_id: str, chunk_id: str, ctx: Context) -> dict[str, Any]:
    """The **ledger entry** one roll wrote, as opposed to its timeline `Step`.

    `Step.tasks_added` is names per skill and `Step.bis_upgrades` a count -
    which is right for a fifty-step series and not enough to shape one roll
    the way the Tasks tab shapes a map. The record still carries what was
    thrown away: each challenge's value (its `Level`, or an `Extra`'s `Label`)
    and which item each BiS slot gained. See `panels.roll_panel`.

    Still no export and no derivation, so `/api/roll` stays a JSON read.
    """
    for entry in cache.read_rolls(map_id, ctx.root):
        if entry.get("chunk_id") == chunk_id:
            return dict(entry)
    return {}


def roll_panels(map_id: str, ctx: Context) -> list[dict[str, Any]]:
    """Every roll of a run, shaped the way the Tasks tab shapes a map.

    **One pass, one answer, three readers.** The overlay draws one of these,
    the graph's bars measure them and the tooltip breaks one down - and until
    they came from here the graph counted the raw ledger while the overlay
    showed the filtered set, so hovering a column said 18 and opening it showed
    two rows.

    The ceiling is carried forward as the walk goes: a roll is filtered against
    everything before it, then folds its own levels in for the rolls after. It
    is the same arithmetic `roll_baseline` does for a single step, done once
    for the run instead of once per step - which is the only reason this can
    sit on `/api/timeline` at all.

    Index-aligned with `replay`'s steps, so `[0]` is the baseline and empty.
    """
    ledger = cache.read_rolls(map_id, ctx.root)
    by_chunk = {
        str(entry["chunk_id"]): entry
        for entry in ledger
        if isinstance(entry.get("chunk_id"), str)
    }
    ceiling = _completed_levels(map_id, ctx)
    challenges = ctx.derivations.chunk_info().challenges if ceiling else {}
    panels: list[dict[str, Any]] = [roll_panel({})]
    for chunk_id in rolled_chunks(ledger):
        record = by_chunk.get(chunk_id, {})
        panels.append(roll_panel(record, ceiling, challenges))
        _raise_ceiling(ceiling, record)
    return panels


def _raise_ceiling(ceiling: dict[str, float], record: Mapping[str, Any]) -> None:
    """Fold one roll's levels into the running high-water mark, in place."""
    for skill, tasks in _mapping(record, "new_tasks").items():
        for level in (tasks or {}).values():
            if isinstance(level, (int, float)) and not isinstance(level, bool):
                ceiling[skill] = max(ceiling.get(skill, 0.0), float(level))


def panel_counts(panel: Mapping[str, Any]) -> tuple[int, dict[str, int]]:
    """A shaped roll as the graph reads it: a total, and a total per section.

    **Per section rather than per skill**, which the tooltip used to print.
    After the filter a skill contributes at most one row, so a per-skill
    breakdown is a list of ones; the sections are the headings the overlay
    actually draws, which is what "the numbers match" has to mean.
    """
    by_group = {
        str(section["label"]): int(section["active_total"])
        for section in panel.get("sections", ())
        if section.get("active_total")
    }
    return sum(by_group.values()), by_group


def roll_baseline(map_id: str, step: int, ctx: Context) -> dict[str, float]:
    """Per skill, the level a run had already reached before roll `step`.

    **What makes a roll's tasks news is that they are *better*.** Unlocking a
    Crafting chunk opens `Cook a ~|cup of tea (porcelain)|~` at Cooking 20;
    on a map that has already ticked the 99 Cooking cape that is not a new
    Cooking goal, and the Tasks tab does not show it - `active_tasks` gates
    candidacy on `highestChallengeLevelArr`, the highest level among a skill's
    *completed* challenges. The roll overlay had no such gate and listed it.

    Two contributions, and the run's ledger only carries one of them:

    - **What the base map had already proved**, which is the case above and
      the reason this route now parses the export. A completed challenge's
      level comes from `challenges[skill][name]['Level']`, and the completed
      set itself from the base payload - constant for the whole run, since
      rolling adds chunks and never ticks anything.
    - **What earlier rolls opened.** A level-20 task is not news if roll three
      already opened a level-70 one, which is the same rule applied to the
      run's own past.

    **The parse is the cheap half of the export, which is why this is
    affordable.** `ChunkInfo`'s accessors are lazy, so reading `challenges` off
    a fresh one is 0.07s measured on the real 10MB file - not the ~1s a
    `derive` costs. A run with no recorded base map answers `{}` without
    touching it at all.

    The one approximation is stated rather than hidden: the level read is the
    challenge's face value where `active_tasks._highest_completed_level` uses
    `boosts.completed_ceiling`, which is *lower* when a boost was needed. So
    this baseline can be a few levels high and hide a marginal task. Porting
    the boost arithmetic here would need a `SourceIndex`, and that means a
    derivation - an order of magnitude more than this whole route costs.
    """
    highest = _completed_levels(map_id, ctx)
    ledger = cache.read_rolls(map_id, ctx.root)
    by_chunk = {
        str(entry["chunk_id"]): entry
        for entry in ledger
        if isinstance(entry.get("chunk_id"), str)
    }
    # Ordered as `replay` orders them, so "before this step" means the same
    # thing here as it does to the slider.
    for chunk_id in rolled_chunks(ledger)[: max(0, step - 1)]:
        _raise_ceiling(highest, by_chunk.get(chunk_id, {}))
    return highest


def _completed_levels(map_id: str, ctx: Context) -> dict[str, float]:
    """The level each skill had already reached on the map a run was rolled from.

    **Two contributions, and both were found by playing a run out by hand.**
    The check is the one this is here to satisfy: take the base map, tick off
    every task it is currently showing, unlock the chunk the simulation rolled,
    derive, and see whether the newly-active task is the one the roll panel
    named. Two disagreements came out of it and each is a term below.

    - **What a completion proves, including elsewhere in the export.** Real
      data files a task under the skill it exercises while defining it in
      another category: `completedChallenges.Thieving` holds `~|Wilderness
      Diary#Elite|~ Task 5`, which lives in `challenges.Diary` with
      `Skills: {Thieving: 84}`. Reading only `challenges['Thieving']` put the
      ceiling at 58, and a level-75 gem stall three rolls later read as news
      where `active_tasks` - which has `_level_proven_elsewhere` - called it
      obsolete. That function is imported rather than reimplemented.
    - **What the map is already working on.** A skill's *active* task is the
      highest-level valid one it has; a roll opening something below it changes
      nothing, and the played-out check says so by ticking that task off before
      the roll. This is the term that costs a derivation - `base_derived`,
      through the same on-disk cache, ~0.15s where the run left its base state
      behind and ~0.8s where it did not.
    """
    payload = cache.read_base_payload(map_id, ctx.root)
    if payload is None:
        return {}
    challenges = ctx.derivations.chunk_info().challenges
    state = ctx.derivations.base_state(payload)
    highest: dict[str, float] = {}

    def raise_to(skill: str, name: str) -> None:
        known = challenges.get(skill) or {}
        challenge = known.get(name)
        level = challenge.get("Level") if isinstance(challenge, dict) else None
        if not isinstance(level, (int, float)) or isinstance(level, bool):
            level = _level_proven_elsewhere(skill, name, challenges)
        if isinstance(level, (int, float)) and not isinstance(level, bool):
            highest[skill] = max(highest.get(skill, 0.0), float(level))

    for skill, names in state.completed_challenges.items():
        for name in names:
            raise_to(skill, name)
    for skill, entry in ctx.derivations.base_derived(payload).task_classification.as_dict().items():
        current = entry.get("active")
        if isinstance(current, str) and current:
            raise_to(skill, current)
    return highest


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
    """Every step, plus whatever hours are already on disk.

    **Fetched once when a run is opened, not per drag** - which is the thing
    to keep in mind about its cost. The slider redraws from the rows this
    returns; nothing here runs again while you scrub.

    That is what pays for `roll_panels`, and it is a change from what this
    docstring used to promise. The steps and the hours still come from the
    ledger, the saved payload and the disk - but the *counts* are now the
    filtered ones the overlay draws, and filtering needs the base map's
    completed levels, which live in the export. A graph counting one thing
    while the panel under it listed another was the worse answer, and the bill
    is small: **0.09s cold and 0.01s warm** on a 50-roll run of the real map,
    because reading `challenges` off a `ChunkInfo` is lazy and cheap where
    deriving from one is not.

    `_cached_hours` still reads a digest stamp rather than the file it
    describes, so the hours half remains free.
    """
    steps = _run_steps(map_id, ctx)
    added, totals, enriched = _cached_hours(map_id, ctx)
    rows = series(steps, totals=totals, added=added)
    # **The bars measure what the overlay lists.** `Step.task_count` is the raw
    # ledger; these are the same rolls after the Tasks tab's own rules.
    # `tasks_by_skill` goes rather than sitting beside the new field: it is a
    # perfectly good answer to a different question, and a payload carrying two
    # counts of "this roll's tasks" is one where somebody reads the wrong one.
    for row, panel in zip(rows, roll_panels(map_id, ctx)):
        row["tasks"], row["tasks_by_group"] = panel_counts(panel)
        row.pop("tasks_by_skill", None)
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
                # **The same basis the bars were priced on**, which is the
                # run's own last state - see `batch._walk`. Pricing this pair
                # against themselves would put a pie under a bar that measured
                # something else.
                final=tuple(sorted(steps[-1].unlocked)),
            ),
            # Everything this needs is already parsed on the context - the
            # export, its tasks map, its digests and the reference blobs - so
            # the click does not re-read 13MB to rebuild them. The pool
            # workers still load their own; see `batch._Prepared`.
            _Prepared(
                info=ctx.derivations.chunk_info(),
                tasks_map=ctx.derivations.tasks_map(),
                digests=ctx.derivations.digests(),
                reference=ctx.derivations.reference(),
            ),
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

    Needs the derivation and the rates the estimate was made against. Both
    come off the context rather than off disk - the rates used to be a second
    read of `wiki_rates.json` in a request that had already made two - and it
    still returns `{}` rather than failing when anything is missing. A tooltip
    is worth a lookup; it is not worth an error.
    """
    if not result.skills:
        return {}
    try:
        state = ctx.derivations.load(map_id)
        heuristics, _ = load_heuristics(
            state.state.chunk_info, ctx.root, ctx.derivations.reference()
        )
    except (CacheMissError, OSError):
        return {}
    return {
        skill.skill: training_options(
            state.derived, state.state.chunk_info, heuristics, skill.skill
        )
        for skill in result.skills
    }
