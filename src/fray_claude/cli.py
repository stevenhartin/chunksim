"""Command line entry point: argparse subcommands and their rendering only.

A new subcommand keeps its logic in a pure module and calls it from here.
`main()` funnels `FetchError`, `CacheMissError`, `NotImplementedError` and
`ConvergenceError` into a stderr message and exit 1; `_load_state`
(-> `pipeline.load_map_state`) handles the common cache-read + decode step.

`--export-json PATH` writes a subcommand's full result as JSON to `PATH`, or
to stdout if `PATH` is `-` - in which case it *replaces* the human-readable
summary rather than interleaving with it, so piping stays clean. It is
carried by the eight *derivation* subcommands
(`sections`/`sources`/`tasks`/`unlock`/`diff`/`neighbours`/`simulate`/`search`),
plus `maps list` - whose output is a reduction over the cache rather than a
cache file, and is the index a batch analysis iterates - and deliberately not
by the three I/O ones (`fetch`/`show`/`chunkinfo`).

`diff --map1 A --map2 B` compares two cached maps of either kind through
`delta.compare_maps`, which is symmetric where `unlock` is one-directional -
read `delta.py` before assuming the two report the same thing. It is the one
subcommand taking two maps, so it names them `--map1`/`--map2` instead of
this file's usual `--map`, and builds a single `ChunkInfo` for both sides.
`unlock --cache-map NAME` saves the post-unlock state the way
`simulate --cache-map` saves a run, into the same layout and so readable by
every other subcommand's `--map`.

`simulate --cache-map NAME` saves each run as a cached map instead of only
printing it, `--runs N` asks for N independent simulations and `--jobs N`
spreads them over worker processes; `batch.py` owns all three, and `cache.py`
the layout they land in. `--cache-behaviour` picks how much of a run's derived
state to keep (`derived_cache.CacheBehaviour`) - all of it by default, so
re-running a seed is served from disk. `--runs` without `--cache-map` is an error rather
than a silent single run: there would be nowhere to put the other N-1. The
`maps` subcommand is this file's only *nested* one (`maps list|rm|clean`) -
two of its three verbs are destructive, and `maps rm NAME` reads better than
a `--rm NAME` flag on a listing command.

`sections`/`sources`/`tasks` take an optional positional (`list` or a chunk
id; one of `sources.CATEGORIES`; a challenge category) to list that branch's
contents instead of just its counts, each capped by `--limit`. That defaults
to `None` - full output - for those three and for `neighbours`, so piping to
`grep`/`less` just works without a flag, but to `10` for `search`, where the
tail of a fuzzy ranking is noise rather than data.

`fray tasks <category>` branches four ways:

- `Diary`/`Quest`/`Other` (or `Extra`; both accepted case-insensitively and
  displayed `Other (Extra)`) list `derived.other_tasks` grouped under
  headers, showing each task's `Description` where the export has one.
- `BiS` lists `derived.bis.active`/`completed`/`outdated` - BiS isn't a
  category in `state.chunk_info.challenges` at all, see `challenges.py` -
  rendered through `BisResult.display_sorted`/`bis_display_name` rather than
  as raw task names, so lines read `[<slot>] Obtain a granite ring (i)` with
  this chunk's completions floated to the top. The raw `~|...|~` names stay
  the keys in `--export-json`.
- A real skill category (`derived.task_classification.skills`) shows
  **active -> completed -> obsolete** sections, plus an opportunistic
  comparison against `state.active_tasks[skill]` ("not cached" when absent,
  the common case - see `active_tasks.py`).
- Anything else keeps the flat valid listing.

Every one of those paths renders through `_display_tasks` ->
`challenges.strip_task_markup`, which **sorts on the stripped form** so the
visible order matches the screen; sorting raw would file every marked-up name
under `~`. `search` strips per hit type (task hits and `task:` routes only),
never blanket, so a genuinely tilde-named shop survives.

The bare `fray tasks` overview prints totals, the active/completed/obsolete
split, and then each category's *active* tasks beneath its own line - one
`<skill> <task>` row per skill with a current goal, then the `BiS` picks in
the same `[<slot>] Obtain ...` form, both capped by `--limit`. The
per-category `valid` enumeration it used to carry instead was mostly tasks a
higher tier has already superseded; `--export-json` still has the full
mapping. `fray unlock`/`fray simulate` print BiS upgrades alongside new
tasks/sections when there are any, and report task *counts* rather than
names, so neither needs markup stripping.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fray_claude.remote.api import (
    DEFAULT_TIMEOUT,
    CHUNKINFO_URL,
    TASKS_MAP_URL,
    FetchError,
    fetch_chunkinfo,
    fetch_map,
    fetch_tasks_map,
)
from fray_claude.batch import RunResult, run_batch, save_unlock
from fray_claude.store.build_info import print_watermark
from fray_claude.store.cache import (
    CHUNKINFO_BLOB_NAME,
    FETCHED,
    TASKS_MAP_BLOB_NAME,
    CacheMissError,
    DEFAULT_MAP_ID,
    MapEntry,
    blob_path,
    chunkinfo_source,
    file_digest,
    list_derived,
    list_maps,
    prune_derived,
    read_blob,
    read_cache,
    WIKI_RATES_BLOB_NAME,
    read_chunkinfo,
    read_overrides,
    remove_computed,
    remove_map,
    write_blob,
    write_cache,
)
from fray_claude.challenges import strip_task_markup
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.delta import BRANCHES, BranchDelta, MapSide, StateDelta, compare_maps
from fray_claude import dps_bridge, estimate_inputs
from fray_claude.estimate import (
    BUCKETS,
    EstimateResult,
    estimate,
    goal_levels,
    infer_levels,
)
from fray_claude.heuristics import Heuristics, disagreements, load, merge
from fray_claude.store.derived_cache import (
    CacheBehaviour,
    Digests,
    RollCache,
    cached_derive,
    cached_enrich,
    pricing_digests,
)
from fray_claude.model.firebase import reverse_tasks_map
from fray_claude.graph import build_section_graph
from fray_claude.neighbours import eligible_neighbours
from fray_claude.other_tasks import CATEGORIES as OTHER_CATEGORIES
from fray_claude.other_tasks import CategoryTasks, display_name, task_text
from fray_claude.pipeline import ConvergenceError, Derived, MapState, load_map_state
from fray_claude.remote.scrape import SOURCE as SCRAPE_SOURCE
from fray_claude.remote.scrape import scrape
from fray_claude.search import TYPES, build_world_index, search
from fray_claude.sections import describe_sections, expand_chunk_areas
from fray_claude.simulate import simulate_rolls
from fray_claude.sources import CATEGORIES as SOURCE_CATEGORIES
from fray_claude.model.summary import _mapping, format_age, summarise
from fray_claude.unlock import UnlockDelta, tasks_added_by

DEFAULT_MAP = DEFAULT_MAP_ID


def _emit_json(data: Any, destination: str) -> None:
    """Write `data` to `destination`: `-` means stdout, anything else a file path."""
    text = json.dumps(data, indent=2, sort_keys=True)
    if destination == "-":
        print(text)
    else:
        Path(destination).write_text(text + "\n", encoding="utf-8")


def _cmd_fetch(args: argparse.Namespace) -> int:
    data = fetch_map(args.map_id, timeout=args.timeout)
    path = write_cache(args.map_id, data)
    print(f"fetched map {args.map_id!r} -> {path} ({path.stat().st_size:,} bytes)")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    envelope = read_cache(args.map_id)
    summary = summarise(envelope["data"])

    simulated = envelope.get("kind", FETCHED) != FETCHED
    print(f"map            {args.map_id}")
    if simulated:
        simulation = envelope.get("simulation")
        provenance = simulation if isinstance(simulation, dict) else {}
        rolled = provenance.get("rolls")
        rolls = len(rolled) if isinstance(rolled, list) else 0
        print(
            f"simulated      {rolls} rolls from {provenance.get('base_map')} "
            f"(seed {provenance.get('seed')})"
        )
    age = format_age(envelope.get("fetched_at"))
    print(f"{'created' if simulated else 'fetched'}        {age}")
    print(f"unlocked       {summary.unlocked_chunks} chunks")
    print(f"chunk order    {summary.chunk_order_entries} entries")
    print(f"rules          {summary.rules_enabled} of {summary.rules_total} enabled")
    if summary.active_tasks:
        detail = ", ".join(f"{name} {count}" for name, count in summary.active_tasks.items())
        print(f"active tasks   {summary.active_task_total} ({detail})")
    else:
        print("active tasks   0")
    # Not a property of the map at all, but of this installation - and an
    # estimate computed with the calculator is a different number from one
    # computed without it, which nothing else on this screen would say.
    version = dps_bridge.library_version()
    print(
        f"dps calc       osrs-dps {version}"
        if version is not None
        else "dps calc       not installed (pip install '.[dps]')"
    )
    return 0


def _cmd_chunkinfo(args: argparse.Namespace) -> int:
    chunkinfo = fetch_chunkinfo(timeout=args.timeout)
    chunkinfo_path = write_blob(CHUNKINFO_BLOB_NAME, chunkinfo, CHUNKINFO_URL)
    print(f"fetched chunkinfo -> {chunkinfo_path} ({chunkinfo_path.stat().st_size:,} bytes)")

    tasks_map = fetch_tasks_map(timeout=args.timeout)
    tasks_map_path = write_blob(TASKS_MAP_BLOB_NAME, tasks_map, TASKS_MAP_URL)
    print(f"fetched tasks map -> {tasks_map_path} ({tasks_map_path.stat().st_size:,} bytes)")
    return 0


def _cmd_heuristics(args: argparse.Namespace) -> int:
    """`fray heuristics`: rebuild the scraped half of the estimator's numbers.

    ~18 requests, run about as often as `fray chunkinfo`. `scrape.py` does the
    reading - the GUI's *Refresh Rates* runs the same function, so the two
    cannot drift - and this prints what it found. Coverage is printed per
    section because it is the honest measure of how much of the estimate is
    real data and how much is a default waiting to be corrected.
    """
    info = ChunkInfo(read_chunkinfo(override=args.chunkinfo))
    result = scrape(info, timeout=args.timeout, progress=lambda step: print(f"  {step}"))
    if result.sheet_error:
        print(f"slayer sheet     unavailable ({result.sheet_error})", file=sys.stderr)
    path = write_blob(WIKI_RATES_BLOB_NAME, result.config, SCRAPE_SOURCE)

    for source, (found, asked) in result.sources.items():
        print(f"{source:<16} {found}/{asked}")
    print(
        f"{'slayer sheet':<16} {result.counts['slayer tasks']} tasks,"
        f" {result.counts['task lengths']} with lengths"
    )
    print(f"{'superiors':<16} {result.counts['superiors']}")

    print()
    for section, (found, total) in result.coverage.items():
        share = f"{found / total:.0%} from the wiki" if total else "nothing to price"
        print(f"{section:<9} {found:>5}/{total:<5} ({share})")
    for line in disagreements(result.config, read_overrides()):
        print(f"  overridden: {line}")
    print(f"\nwrote {path} ({path.stat().st_size:,} bytes)")
    return 0


def _digests(args: argparse.Namespace) -> Digests:
    """Content hashes of the reference data, for the derived cache's key."""
    return Digests(
        chunkinfo=file_digest(chunkinfo_source(override=args.chunkinfo)),
        tasks_map=file_digest(blob_path(TASKS_MAP_BLOB_NAME)),
    )


def _derive(args: argparse.Namespace, state: MapState, unlocked: Mapping[str, bool]) -> Derived:
    """`derive` through the on-disk cache - see `derived_cache.py`.

    Every subcommand goes through here rather than calling `derive` directly,
    so `--recompute` means the same thing everywhere. Tests and the opt-in
    oracles keep calling `pipeline.derive`, which is what keeps them a
    cache-free correctness signal.
    """
    return cached_derive(state, unlocked, _digests(args), refresh=args.recompute)


def _load_state(
    args: argparse.Namespace,
    map_id: str | None = None,
    *,
    chunk_info: ChunkInfo | None = None,
) -> tuple[MapState, dict[str, bool]]:
    """The cached map, decoded into a `MapState` and its unlocked-chunk set.

    `map_id` overrides `args.map_id` and `chunk_info` reuses an already-parsed
    export, so `fray diff` can load two maps while paying the ~7MB parse once
    (`chunkinfo.py`: build one `ChunkInfo` per invocation).
    """
    envelope = read_cache(map_id if map_id is not None else args.map_id)
    info = chunk_info or ChunkInfo(read_chunkinfo(override=args.chunkinfo))
    try:
        tasks_map = reverse_tasks_map(read_blob(TASKS_MAP_BLOB_NAME)["data"])
    except CacheMissError:
        # No cached tasks map (e.g. a bare `--chunkinfo` override with no
        # `fray chunkinfo` run) - degrade gracefully rather than fail: see
        # `pipeline.load_map_state`'s docstring for what this costs.
        tasks_map = {}
    return load_map_state(envelope["data"], info, tasks_map)


def _error(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


def _display_tasks(names: Iterable[str]) -> list[str]:
    """Task names sorted for display, markup stripped. Sorting happens on
    the stripped form so the visible order matches what's on screen -
    `~|Zamorak|~ ...` would otherwise sort under `~`, i.e. nowhere useful.
    """
    return sorted(strip_task_markup(name) for name in names)


def _resolve_other_category(category: str | None) -> str | None:
    """Map a user-typed category onto one of `other_tasks.CATEGORIES`.

    Both the export's `Extra` and the app's `Other` are accepted; matching is
    case-insensitive so `fray tasks other` works like every other argument
    here would if it were typed loosely.
    """
    if category is None:
        return None
    folded = category.casefold()
    for name in OTHER_CATEGORIES:
        if folded in (name.casefold(), display_name(name).casefold()):
            return name
    return None


def _other_lines(tasks: CategoryTasks, chunk_info: ChunkInfo) -> list[str]:
    """One `[Group] description` line per active task, group order preserved."""
    challenges = chunk_info.challenges.get(tasks.category) or {}
    return [
        f"[{group.name}] {task_text(name, challenges.get(name) or {})}"
        for group in tasks.groups
        for name in group.active
    ]


def _print_grouped(
    tasks: CategoryTasks, chunk_info: ChunkInfo, attr: str, limit: int | None
) -> None:
    """A category's groups with headers, each group's tasks indented under it.

    `--limit` caps the *tasks* rather than the groups, so a large category
    still shows where its work is concentrated; a group with nothing in the
    requested half is skipped entirely.
    """
    challenges = chunk_info.challenges.get(tasks.category) or {}
    shown = 0
    for group in tasks.groups:
        names: tuple[str, ...] = getattr(group, attr)
        if not names:
            continue
        if limit is not None and shown >= limit:
            remaining = sum(len(getattr(g, attr)) for g in tasks.groups) - shown
            print(f"  ... and {remaining} more (--limit {shown + remaining} to see all)")
            return
        print(f"  {group.name}")
        for name in names:
            if limit is not None and shown >= limit:
                break
            challenge = challenges.get(name) or {}
            text = (
                tasks.completed_text(name, challenge)
                if attr == "completed"
                else task_text(name, challenge)
            )
            print(f"    {text}")
            shown += 1


def _print_capped(names: list[str], limit: int | None) -> None:
    shown = names if limit is None else names[:limit]
    for name in shown:
        print(f"  {name}")
    if limit is not None and len(names) > limit:
        print(f"  ... and {len(names) - limit} more (--limit {len(names)} to see all)")


def _cmd_sections(args: argparse.Namespace) -> int:
    state, unlocked = _load_state(args)
    result = _derive(args, state, unlocked)

    if args.target is None:
        total_sections = sum(len(s) for s in result.reachable_sections.values())
        # `--export-json -` replaces the text summary on stdout, so a pipe
        # sees only JSON; a file destination leaves stdout for the summary.
        if args.export_json != "-":
            print(f"map                {args.map_id}")
            print(f"unlocked chunks    {len(unlocked)}")
            print(f"sectioned chunks   {len(result.reachable_sections)}")
            print(f"reachable sections {total_sections}")
        if args.export_json is not None:
            _emit_json(
                {
                    "map_id": args.map_id,
                    "unlocked_chunks": len(unlocked),
                    "sections": result.reachable_sections,
                },
                args.export_json,
            )
        return 0

    expanded = expand_chunk_areas(unlocked)
    entries = describe_sections(expanded, result.reachable_sections, state.chunk_info)

    if args.target == "list":
        if args.export_json != "-":
            print(f"map             {args.map_id}")
            print(f"unlocked chunks {len(entries)}")
            shown = entries if args.limit is None else entries[: args.limit]
            for entry in shown:
                label = f"{entry.chunk_id:<8} {entry.name or '':<20}"
                print(f"  {label} {', '.join(entry.reachable)}")
            if args.limit is not None and len(entries) > args.limit:
                print(f"  ... and {len(entries) - args.limit} more (--limit {len(entries)})")
        if args.export_json is not None:
            _emit_json(
                {"map_id": args.map_id, "chunks": [e.as_dict() for e in entries]}, args.export_json
            )
        return 0

    match = next((e for e in entries if e.chunk_id == args.target), None)
    if match is None:
        return _error(f"chunk {args.target!r} is not unlocked on map {args.map_id!r}")
    if args.export_json != "-":
        print(f"map       {args.map_id}")
        print(f"chunk     {match.chunk_id}")
        print(f"name      {match.name or 'unknown'}")
        print(f"reachable {', '.join(match.reachable)}")
        print(f"locked    {', '.join(match.locked) if match.locked else 'none'}")
    if args.export_json is not None:
        _emit_json({"map_id": args.map_id, **match.as_dict()}, args.export_json)
    return 0


def _cmd_sources(args: argparse.Namespace) -> int:
    state, unlocked = _load_state(args)
    index = _derive(args, state, unlocked).source_index

    if args.category is None:
        if args.export_json != "-":
            print(f"map        {args.map_id}")
            print(f"items      {len(index.items)}")
            print(f"objects    {len(index.objects)}")
            print(f"monsters   {len(index.monsters)}")
            print(f"npcs       {len(index.npcs)}")
            print(f"shops      {len(index.shops)}")
        if args.export_json is not None:
            _emit_json({"map_id": args.map_id, **index.as_dict()}, args.export_json)
        return 0

    contents = index.category(args.category)
    names = sorted(contents)
    if args.export_json != "-":
        print(f"map      {args.map_id}")
        print(f"category {args.category}")
        print(f"count    {len(names)}")
        _print_capped(names, args.limit)
    if args.export_json is not None:
        _emit_json(
            {"map_id": args.map_id, "category": args.category, args.category: contents},
            args.export_json,
        )
    return 0


def _cmd_tasks(args: argparse.Namespace) -> int:
    state, unlocked = _load_state(args)
    derived = _derive(args, state, unlocked)
    result = derived.challenges

    if args.category is None:
        total_valid = sum(len(names) for names in result.valid.values())
        classifications = derived.task_classification.skills
        active_count = sum(1 for c in classifications.values() if c.active is not None)
        obsolete_count = sum(len(c.obsolete) for c in classifications.values())
        completed_count = sum(len(c.completed) for c in classifications.values())
        if args.export_json != "-":
            # The per-category `valid` breakdown this used to print is mostly
            # tasks a higher tier has already superseded - the totals stay for
            # scale, and each category lists its *active* tasks instead, which
            # is the part you can act on. `--export-json` still carries the
            # full per-category `valid` mapping.
            print(f"map          {args.map_id}")
            print(f"valid tasks  {total_valid}")
            print(f"unsupported  {len(result.unsupported)} individual tasks (see challenges.py)")
            print(
                f"skill tasks  active {active_count}, completed {completed_count}, "
                f"obsolete {obsolete_count} (across {len(classifications)} skill categories)"
            )
            _print_capped(
                [
                    f"{skill:<13} {strip_task_markup(classification.active)}"
                    for skill, classification in sorted(classifications.items())
                    if classification.active is not None
                ],
                args.limit,
            )
            bis_line = f"BiS          active {len(derived.bis.active)}, completed {len(derived.bis.completed)}"
            if derived.bis.outdated:
                bis_line += f", outdated {len(derived.bis.outdated)}"
            print(bis_line)
            _print_capped(derived.bis.display_sorted(derived.bis.active), args.limit)
            for category in OTHER_CATEGORIES:
                tasks = derived.other_tasks.categories.get(category)
                if tasks is None:
                    continue
                print(
                    f"{tasks.label:<12} active {tasks.active_total}, "
                    f"completed {tasks.completed_total}"
                )
                _print_capped(_other_lines(tasks, state.chunk_info), args.limit)
        if args.export_json is not None:
            _emit_json(
                {
                    "map_id": args.map_id,
                    **result.as_dict(),
                    "bis": derived.bis.as_dict(),
                    "task_classification": derived.task_classification.as_dict(),
                    "other_tasks": derived.other_tasks.as_dict(),
                },
                args.export_json,
            )
        return 0

    if args.category == "BiS":
        bis = derived.bis
        if args.export_json != "-":
            print(f"map       {args.map_id}")
            print("category  BiS")
            print(f"active    {len(bis.active)}")
            _print_capped(bis.display_sorted(bis.active), args.limit)
            print(f"completed {len(bis.completed)}")
            _print_capped(bis.display_sorted(bis.completed), args.limit)
            if bis.outdated:
                print(f"outdated  {len(bis.outdated)}")
                for name in sorted(bis.outdated, key=lambda n: (n not in bis.current_chunk, n)):
                    print(f"  {bis.display_name(name)}  ({bis.outdated[name]})")
        if args.export_json is not None:
            _emit_json({"map_id": args.map_id, "category": "BiS", **bis.as_dict()}, args.export_json)
        return 0

    other_category = _resolve_other_category(args.category)
    if other_category is not None:
        tasks = derived.other_tasks.categories[other_category]
        label = tasks.label
        heading = label if label == other_category else f"{label} ({other_category})"
        if args.export_json != "-":
            print(f"map      {args.map_id}")
            print(f"category {heading}")
            print(f"active   {tasks.active_total}")
            _print_grouped(tasks, state.chunk_info, "active", args.limit)
            print(f"completed {tasks.completed_total}")
            _print_grouped(tasks, state.chunk_info, "completed", args.limit)
        if args.export_json is not None:
            _emit_json({"map_id": args.map_id, **tasks.as_dict()}, args.export_json)
        return 0

    if args.category in derived.task_classification.skills:
        classification = derived.task_classification.skills[args.category]
        oracle = state.active_tasks.get(args.category, {})
        oracle_active = next(iter(oracle), None)
        if oracle_active is None:
            oracle_note = "not cached"
        elif oracle_active == classification.active:
            oracle_note = f"matches cached active task ({strip_task_markup(oracle_active)!r})"
        else:
            oracle_note = f"cached active task is {strip_task_markup(oracle_active)!r} (mismatch)"
        active_name = (
            strip_task_markup(classification.active) if classification.active else "(none)"
        )
        if args.export_json != "-":
            print(f"map      {args.map_id}")
            print(f"category {args.category}")
            print(f"active   {active_name}  [{oracle_note}]")
            print(f"completed {len(classification.completed)}")
            _print_capped(_display_tasks(classification.completed), args.limit)
            print(f"obsolete {len(classification.obsolete)}")
            _print_capped(_display_tasks(classification.obsolete), args.limit)
        if args.export_json is not None:
            _emit_json(
                {
                    "map_id": args.map_id,
                    "category": args.category,
                    **classification.as_dict(),
                    "cached_active_task": oracle_active,
                },
                args.export_json,
            )
        return 0

    if args.category not in state.chunk_info.challenges:
        return _error(f"unknown task category: {args.category!r}")

    names = sorted(result.valid.get(args.category, {}))
    if args.export_json != "-":
        print(f"map      {args.map_id}")
        print(f"category {args.category}")
        print(f"valid    {len(names)}")
        _print_capped(_display_tasks(names), args.limit)
    if args.export_json is not None:
        _emit_json(
            {"map_id": args.map_id, "category": args.category, "valid": names},
            args.export_json,
        )
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    state, unlocked = _load_state(args)
    world = build_world_index(state.chunk_info)
    result = _derive(args, state, unlocked)
    hits = search(
        world, args.query, unlocked=unlocked, derived=result, types=args.type, limit=args.limit
    )

    if args.export_json != "-":
        print(f"query {args.query!r}")
        print(f"hits  {len(hits)}")
        for hit in hits:
            status = "available" if hit.available else "locked"
            # Task names, and the challenge behind a `task:<category>` item
            # route, carry `~|...|~`. Nothing else does - and a shop really
            # is named `~ Uglug's stuffsies ~` - so this stays type-scoped
            # rather than blanket-applied. See `strip_task_markup`.
            name = strip_task_markup(hit.name) if hit.type == "task" else hit.name
            print(f"{hit.type.upper():8} {name}  [{status}]")
            if hit.type == "item":
                for source in hit.detail["sources"]:
                    source_status = "available" if source["available"] else "locked"
                    source_name = source["name"]
                    if str(source["route"]).startswith("task:"):
                        source_name = strip_task_markup(source_name)
                    print(f"  {source['route']}: {source_name}  [{source_status}]")
                    locs = source["locations"]
                    if locs:
                        print("    " + ", ".join(loc["chunk_id"] for loc in locs))
                    else:
                        print("    (no known location)")
            elif hit.type == "task":
                print(f"  category: {hit.detail['category']}")
            else:
                locs = hit.detail["locations"]
                if locs:
                    print("    " + ", ".join(loc["chunk_id"] for loc in locs))
                else:
                    print("    (no known location)")
                if hit.type == "monster" and hit.detail["boss"]:
                    print("    boss")
                if hit.detail["provides"]:
                    print("    provides: " + ", ".join(hit.detail["provides"]))

    if args.export_json is not None:
        _emit_json(
            {"query": args.query, "hits": [hit.as_dict() for hit in hits]}, args.export_json
        )
    return 0


def _unlock_to_cache(args: argparse.Namespace, delta: UnlockDelta) -> str:
    """Save the post-unlock state as a cached map; returns the name claimed.

    `batch.save_unlock` does the writing, because the GUI's chunk panel saves
    one too and the metadata shape is what `maps list` and the picker read -
    see that function for why there is exactly one writer of it.
    """
    envelope = read_cache(args.map_id)
    saved = save_unlock(
        name=args.cache_map,
        payload=envelope["data"],
        delta=delta,
        base_map=args.map_id,
        base_fetched_at=envelope.get("fetched_at"),
    )
    return saved.name


def _cmd_unlock(args: argparse.Namespace) -> int:
    state, unlocked = _load_state(args)
    delta = tasks_added_by(
        state,
        unlocked,
        args.chunk_id,
        derive_with=lambda s, u: _derive(args, s, u),
    )
    saved = _unlock_to_cache(args, delta) if args.cache_map is not None else None

    if args.export_json != "-":
        print(f"map          {args.map_id}")
        print(f"chunk        {delta.chunk_id}")
        print(f"new tasks    {delta.task_count}")
        for skill, names in sorted(delta.new_tasks.items()):
            print(f"  {skill:<12} {len(names)}")
        print(f"new sections {sum(len(s) for s in delta.new_sections.values())}")
        if delta.bis_upgrades:
            print(f"bis upgrades {len(delta.bis_upgrades)}")
            for key, (previous, new) in sorted(delta.bis_upgrades.items()):
                print(f"  {key:<20} {previous or '(none)'} -> {new}")
        if delta.new_unsupported:
            print(f"new unsupported {len(delta.new_unsupported)} (see challenges.py)")
        if saved is not None:
            if saved != args.cache_map:
                print(f"name {args.cache_map!r} was taken; saved as {saved!r}")
            print(f"saved as     {saved}")
            print(f"read with    fray tasks --map {saved}")

    if args.export_json is not None:
        payload: dict[str, Any] = {"map_id": args.map_id, **delta.as_dict()}
        if saved is not None:
            payload["cached_map"] = saved
        _emit_json(payload, args.export_json)
    return 0


def _delta_lines(branch: BranchDelta, *, strip: bool = False) -> list[str]:
    """One `+ name`/`- name` line each, gains before losses."""
    added = _display_tasks(branch.added) if strip else sorted(branch.added)
    removed = _display_tasks(branch.removed) if strip else sorted(branch.removed)
    return [f"+ {name}" for name in added] + [f"- {name}" for name in removed]


def _nested_delta_lines(
    branches: Mapping[str, BranchDelta], *, strip: bool = False, label: str = ""
) -> list[str]:
    """Each key's gains and losses indented under its own header."""
    lines: list[str] = []
    for key in sorted(branches):
        lines.append(f"{label}{key}")
        lines.extend(f"  {line}" for line in _delta_lines(branches[key], strip=strip))
    return lines


def _name_or_none(name: str | None) -> str:
    return strip_task_markup(name) if name else "(none)"


def _print_diff_branch(delta: StateDelta, branch: str, limit: int | None) -> None:
    """One branch's names in full. `--limit` caps printed *lines*, headers
    included, so a capped listing still shows which keys it got through.
    """
    lines: list[str] = []
    if branch == "chunks":
        lines = _delta_lines(delta.chunks)
    elif branch == "sections":
        lines = _nested_delta_lines(delta.sections)
    elif branch == "tasks":
        lines = _nested_delta_lines(delta.tasks, strip=True)
    elif branch == "unsupported":
        lines = _delta_lines(delta.unsupported, strip=True)
    elif branch == "sources":
        lines = _nested_delta_lines(delta.sources)
    elif branch == "bis":
        lines = [
            f"{key:<24} {_name_or_none(before)} -> {_name_or_none(after)}"
            for key, (before, after) in sorted(delta.bis_picks.items())
        ]
        lines.extend(_nested_delta_lines(delta.bis_tasks, strip=True))
    elif branch == "skills":
        for skill in sorted(delta.skills):
            change = delta.skills[skill]
            lines.append(skill)
            if change.active is not None:
                was, now = change.active
                lines.append(f"  goal {_name_or_none(was)} -> {_name_or_none(now)}")
            lines.extend(f"  obsolete {line}" for line in _delta_lines(change.obsolete, strip=True))
            lines.extend(
                f"  completed {line}" for line in _delta_lines(change.completed, strip=True)
            )
    else:
        for category in sorted(delta.other):
            lines.append(display_name(category))
            for name, changed in sorted(delta.other[category].items()):
                lines.extend(f"  {name} {line}" for line in _delta_lines(changed, strip=True))
    _print_capped(lines, limit)


def _print_diff_summary(delta: StateDelta, branch: str | None) -> None:
    """`+gained -lost` per branch. With `--branch`, only that one: the others
    weren't computed, and printing them as zeroes would read as "unchanged".
    """
    print(f"map1         {delta.before_map}")
    print(f"map2         {delta.after_map}")
    for name, (added, removed) in delta.counts().items():
        if branch is None or branch == name:
            print(f"{name:<12} +{added} -{removed}")
    if delta.bis_picks:
        print(f"bis picks    {len(delta.bis_picks)} changed")
    goals = sum(1 for change in delta.skills.values() if change.active is not None)
    if goals:
        print(f"skill goals  {goals} changed")


def _cmd_diff(args: argparse.Namespace) -> int:
    if args.branch is not None and args.branch not in BRANCHES:
        return _error(f"unknown branch {args.branch!r} (expected one of {', '.join(BRANCHES)})")

    # One `ChunkInfo` for both sides: parsing the ~10MB export is the expensive
    # part, and the two maps are read against the same world by definition.
    # Taking it from the first side rather than building it up front also keeps
    # a missing *map* the first thing reported, as in every other subcommand.
    before_state, before_unlocked = _load_state(args, args.map1)
    after_state, after_unlocked = _load_state(args, args.map2, chunk_info=before_state.chunk_info)
    delta = compare_maps(
        MapSide(before_state, before_unlocked, args.map1),
        MapSide(after_state, after_unlocked, args.map2),
        derive_with=lambda s, u: _derive(args, s, u),
        branches=None if args.branch is None else frozenset({args.branch}),
    )

    if args.export_json != "-":
        _print_diff_summary(delta, args.branch)
        if args.branch is not None:
            _print_diff_branch(delta, args.branch, args.limit)
    if args.export_json is not None:
        _emit_json(delta.as_dict(), args.export_json)
    return 0


def _cmd_estimate(args: argparse.Namespace) -> int:
    if args.bucket is not None and args.bucket not in BUCKETS:
        return _error(f"unknown bucket {args.bucket!r} (expected one of {', '.join(BUCKETS)})")

    state, unlocked = _load_state(args)
    derived = _derive(args, state, unlocked)
    # Everything about *what* to price lives in `estimate_inputs`, shared with
    # the GUI so the two apps cannot answer differently; what is left here is
    # rendering.
    answer = estimate_inputs.estimate_answer(
        state, unlocked, derived, _digests(args), refresh=args.recompute
    )

    if args.export_json != "-":
        _print_estimate(
            answer.result,
            args.map_id,
            args.bucket,
            args.limit,
            answer.scraped_rates,
            answer.coverage,
        )
    if args.export_json is not None:
        _emit_json(answer.as_dict(args.map_id), args.export_json)
    return 0


def _print_estimate(
    result: EstimateResult,
    map_id: str,
    bucket: str | None,
    limit: int | None,
    scraped_found: bool = True,
    coverage: dps_bridge.DpsCoverage | None = None,
) -> None:
    print(f"map          {map_id}")
    if coverage is not None and coverage.priced_anything:
        pinned = f", {coverage.pinned} pinned" if coverage.pinned else ""
        print(
            f"dps calc     {coverage.monsters} of {coverage.offered} reachable monsters, "
            f"{coverage.slayer_tasks} slayer tasks ({'/'.join(coverage.styles)}{pinned})"
        )
    for name, hours in result.buckets.items():
        if bucket is None or bucket == name:
            print(f"{name:<12} {hours:>9,.1f}h")
    if bucket is None:
        print(f"{'total':<12} {result.total_hours:>9,.1f}h")
        if result.unpriced:
            print(f"unpriced     {len(result.unpriced)} (no priceable route - see estimate.py)")
        _print_estimate_warnings(result, scraped_found)
        return

    if bucket == "skilling":
        for skill in sorted(result.skills, key=lambda skill: -skill.hours):
            flag = " (default rate)" if skill.defaulted else ""
            print(
                f"  {skill.skill:<13} {skill.current_level:>3} -> {skill.target_level:<3}"
                f" {skill.xp:>10,} xp @ {skill.xp_per_hour:>9,.0f}/hr"
                f" = {skill.hours:>7,.1f}h  {skill.method}{flag}"
            )
        _print_slayer_masters(result)
        return

    if bucket == "quests":
        rows = result.in_bucket(bucket)
        for task in rows if limit is None else rows[:limit]:
            print(f"  {task.hours:>8,.1f}h {strip_task_markup(task.task):<48} {task.detail}")
        if limit is not None and len(rows) > limit:
            print(f"  ... and {len(rows) - limit} more (--limit {len(rows)} to see all)")
        return

    # Grouped by source, because that is how the time is actually spent: the
    # items under one heading are earned together, so the heading carries
    # what the source costs and each item still shows its own expected time.
    groups = result.sources_in(bucket)
    for source, hours, entries in groups if limit is None else groups[:limit]:
        together = f"  ({len(entries)} items, earned together)" if len(entries) > 1 else ""
        print(f"  {hours:>8,.1f}h {source}{together}")
        for entry in entries:
            covers = f" x{len(entry.tasks)}" if len(entry.tasks) > 1 else ""
            print(f"      {entry.hours:>8,.1f}h {entry.item}{covers}")
    if limit is not None and len(groups) > limit:
        print(f"  ... and {len(groups) - limit} more (--limit {len(groups)} to see all)")


def _print_slayer_masters(result: EstimateResult) -> None:
    """Every reachable master, not just the one the estimate used.

    Slayer is the one skill whose rate depends on *who you talk to*, and XP
    per hour is not the only reason to pick one: a master with a fuller task
    list, fewer gaps in its data, a denser superior pool, or a points balance
    that does not bleed can be the better choice even when slower. The
    estimate still uses the fastest.

    Every column is computed at this chunk's *end* levels - see
    `estimate.goal_levels`. The list a master offers at Slayer 92 is the one
    that holds for the tail of the chunk, and the tail is where the time
    goes.
    """
    if not result.slayer_masters:
        return

    chosen = result.slayer.master if result.slayer else ""
    print(
        f"\n  {'slayer master':<18} {'xp/hr':>9} {'skip':>5} {'pts/task':>9} {'no data':>8}"
        "  sup. unique"
    )
    for rate in result.slayer_masters:
        # The shared unique table, not the superior itself: the drops are
        # what anyone is farming supers for.
        rolls = result.superior_rolls.get(rate.master, 0.0)
        supers = f"1 per {1 / rolls:,.0f}h" if rolls > 0 else "none"
        marker = " *" if rate.master == chosen else "  "
        print(
            f" {marker}{rate.master:<18} {rate.xp_per_hour:>9,.0f} {rate.skip_rate:>5.0%}"
            f" {rate.points_delta:>+9.1f} {rate.unpriced:>8.0%}  {supers}"
        )
    print("  * used by the estimate (fastest); the others are shown to compare")
    print("  skip = share of *offered* tasks whose monsters this map cannot reach")
    print("  pts/task = points earned, less points paid skipping those; negative bleeds points")
    print("  sup. unique = how often the shared superior table rolls - imbued heart,")
    print("  eternal gem, dust and mist battlestaff. A superior itself spawns far")
    print("  more often; the unique off one is what the hours are spent on")
    print("  all four assume this chunk's end levels - the task list you will")
    print("  spend most of it on - not the levels you hold today")


def _print_estimate_warnings(result: EstimateResult, scraped_found: bool = True) -> None:
    """What makes the total untrustworthy, said plainly rather than buried."""
    if not scraped_found:
        # The single biggest thing that can be wrong with a total, and the
        # easiest to miss: without the scrape there are no superior mappings
        # and no slayer assignment sizes, so whole classes of drop cannot be
        # priced and the total is light rather than wrong-looking.
        print(
            "\nno cached wiki rates: every rate below is a default."
            "\n  run: fray heuristics   (superior and task-gated drops cannot be"
            " priced without it)"
        )
    defaulted = [skill.skill for skill in result.skills if skill.defaulted]
    if defaulted:
        print(
            f"\n{len(defaulted)} skill(s) using the default training rate:"
            f" {', '.join(sorted(defaulted))}"
        )
        print("  correct them in heuristics/overrides.json - see heuristics.py")
    slayer = result.slayer
    if slayer is None:
        return
    # Two different problems, said as two different sentences: one is a fact
    # about the map, the other is a hole in the config.
    if slayer.coverage < 0.5:
        print(
            f"\nslayer: only {slayer.coverage:.0%} of {slayer.master}'s task weight is"
            " reachable, so its rate is optimistic (see slayer.py)"
        )
    if slayer.unpriced > 0.05:
        print(
            f"\nslayer: {slayer.unpriced:.0%} of {slayer.master}'s task weight has no rate"
            " data - reachable, but not costed"
        )
        print("  add them under `slayer` in heuristics/overrides.json")


def _cmd_neighbours(args: argparse.Namespace) -> int:
    state, unlocked = _load_state(args)
    entries = eligible_neighbours(
        state, unlocked, _derive(args, state, unlocked), graph=build_section_graph(state.chunk_info)
    )

    if args.export_json != "-":
        print(f"map             {args.map_id}")
        print(f"unlocked chunks {len(unlocked)}")
        print(f"eligible chunks {len(entries)}")
        shown = entries if args.limit is None else entries[: args.limit]
        for entry in shown:
            print(
                f"  {entry.number:>3}  {entry.chunk_id:<6} "
                f"{entry.nickname or '':<32} via {entry.via_ref}"
            )
        if args.limit is not None and len(entries) > args.limit:
            print(f"  ... and {len(entries) - args.limit} more (--limit {len(entries)} to see all)")

    if args.export_json is not None:
        _emit_json(
            {
                "map_id": args.map_id,
                "unlocked_chunks": len(unlocked),
                "neighbours": [entry.as_dict() for entry in entries],
            },
            args.export_json,
        )
    return 0


def _maps_rows(entries: Iterable[MapEntry]) -> list[str]:
    """`fray maps` as fixed-width rows; runs indent under their batch."""
    rows = [f"{'NAME':<28} {'KIND':<10} {'RUNS':>5} {'ROLLS':>6} {'CHUNKS':>7}  AGE"]
    for entry in entries:
        runs = "-" if entry.runs is None else str(entry.runs)
        rolls = "-" if entry.rolls is None else str(entry.rolls)
        chunks = "-" if entry.unlocked_chunks is None else str(entry.unlocked_chunks)
        indent = "  " if "/" in entry.map_id else ""
        name = f"{indent}{entry.map_id}"
        # A stopped batch's `rolls` is what it *asked* for, so without this
        # the only clue is a run count quietly short of it.
        age = format_age(entry.created_at) + (" (stopped)" if entry.cancelled else "")
        rows.append(
            f"{name:<28} {entry.kind:<10} {runs:>5} {rolls:>6} {chunks:>7}  {age}"
        )
    return rows


def _cmd_maps_list(args: argparse.Namespace) -> int:
    entries = list_maps(expand_runs=args.runs)
    if args.export_json != "-":
        if entries:
            for row in _maps_rows(entries):
                print(row)
        else:
            print("no cached maps; run: fray fetch")
    if args.export_json is not None:
        _emit_json({"maps": [entry.as_dict() for entry in entries]}, args.export_json)
    return 0


def _cmd_maps_rm(args: argparse.Namespace) -> int:
    for map_id in args.names:
        path = remove_map(map_id, include_fetched=args.include_fetched)
        print(f"removed {map_id} ({path})")
    return 0


def _cmd_maps_clean(args: argparse.Namespace) -> int:
    removed = remove_computed()
    for name in removed:
        print(f"removed {name}")
    if args.include_fetched:
        for entry in list_maps():
            if entry.kind == FETCHED:
                remove_map(entry.map_id, include_fetched=True)
                print(f"removed {entry.map_id}")
                removed.append(entry.map_id)
    if not removed:
        print("nothing to clean")
    else:
        plural = "" if len(removed) == 1 else "s"
        print(f"removed {len(removed)} cached map{plural}")
    return 0


#: `fray derived clean`'s default cut-off. Entries are keyed by content, so a
#: stale one is never *wrong*, only unreachable - ageing them out is about disk,
#: not correctness, hence a generous default.
DEFAULT_DERIVED_MAX_AGE_DAYS = 14


def _cmd_derived_list(args: argparse.Namespace) -> int:
    entries = list_derived()
    if not entries:
        print("no cached derivations")
        return 0

    total = sum(entry.size for entry in entries)
    print(f"entries      {len(entries)}")
    print(f"size         {total / 1_048_576:.1f} MiB")
    print(f"oldest read  {format_age(entries[0].accessed_at.isoformat())}")
    print(f"newest read  {format_age(entries[-1].accessed_at.isoformat())}")
    if args.verbose:
        for entry in entries:
            age = format_age(entry.accessed_at.isoformat())
            print(f"  {entry.key}  {entry.size / 1024:>8.0f} KiB  read {age}")
    return 0


def _cmd_derived_clean(args: argparse.Namespace) -> int:
    max_age = None if args.all else args.older_than
    removed = prune_derived(max_age_days=max_age)
    if not removed:
        print("nothing to clean")
        return 0
    freed = sum(entry.size for entry in removed)
    scope = "all" if args.all else f"unread for {args.older_than:g} days"
    print(
        f"removed {len(removed)} cached derivations ({scope}), "
        f"freeing {freed / 1_048_576:.1f} MiB"
    )
    return 0


def _simulate_to_cache(args: argparse.Namespace) -> int:
    """`fray simulate --cache-map`: persist each run as its own cached map."""
    envelope = read_cache(args.map_id)
    quiet = args.export_json == "-"

    def report(result: RunResult) -> None:
        print(f"  {result.name} {len(result.rolls)} rolls -> {result.unlocked_chunks} chunks")

    batch = run_batch(
        name=args.cache_map,
        payload=envelope["data"],
        base_map=args.map_id,
        base_fetched_at=envelope.get("fetched_at"),
        rolls=args.rolls,
        runs=args.runs,
        jobs=args.jobs,
        seed=args.seed,
        chunkinfo_path=args.chunkinfo,
        cache_behaviour=CacheBehaviour(args.cache_behaviour),
        on_complete=None if quiet else report,
    )

    if not quiet:
        if batch.name != args.cache_map:
            print(f"name {args.cache_map!r} was taken; saved as {batch.name!r}")
        print(f"batch        {batch.name} ({batch.directory})")
        print(f"runs         {len(batch.runs)} x {args.rolls} rolls")
        read_as = batch.name if len(batch.runs) == 1 else f"{batch.name}/{batch.runs[0].name}"
        print(f"read with    fray tasks --map {read_as}")
    if args.export_json is not None:
        _emit_json(batch.as_dict(), args.export_json)
    return 0


def _cmd_simulate(args: argparse.Namespace) -> int:
    if args.rolls < 1:
        return _error("--rolls must be at least 1")
    if args.runs < 1:
        return _error("--runs must be at least 1")
    if args.jobs < 1:
        return _error("--jobs must be at least 1")
    if args.cache_map is not None:
        return _simulate_to_cache(args)
    if args.runs > 1:
        return _error("--runs needs --cache-map: without it there is nowhere to put the runs")

    state, unlocked = _load_state(args)
    ledger = simulate_rolls(
        state,
        unlocked,
        rolls=args.rolls,
        seed=args.seed,
        cache=RollCache(_digests(args), CacheBehaviour(args.cache_behaviour)),
    )
    total_tasks = sum(len(names) for record in ledger for names in record.new_tasks.values())
    total_bis = sum(len(record.bis_upgrades) for record in ledger)

    if args.export_json != "-":
        seed_note = f" (seed {args.seed})" if args.seed is not None else ""
        print(f"map          {args.map_id}")
        print(f"rolls        {len(ledger)} of {args.rolls} requested{seed_note}")
        for record in ledger:
            task_count = sum(len(names) for names in record.new_tasks.values())
            section_count = sum(len(s) for s in record.new_sections.values())
            bis_count = len(record.bis_upgrades)
            print(
                f"  {record.order:>3} {record.chunk_id:<8} tasks+{task_count} "
                f"sections+{section_count} bis+{bis_count}"
            )
        print(f"total new tasks {total_tasks}")
        if total_bis:
            print(f"total bis upgrades {total_bis}")

    if args.export_json is not None:
        _emit_json(
            {
                "map_id": args.map_id,
                "seed": args.seed,
                "rolls_requested": args.rolls,
                "rolls": [record.as_dict() for record in ledger],
            },
            args.export_json,
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fray", description="Offline tooling for source-chunk map state."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    fetch = subcommands.add_parser("fetch", help="download map state and cache it locally")
    fetch.add_argument(
        "--map", dest="map_id", default=DEFAULT_MAP, help="map id (default: %(default)s)"
    )
    fetch.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="request timeout in seconds (default: %(default)s)",
    )
    fetch.set_defaults(func=_cmd_fetch)

    show = subcommands.add_parser("show", help="summarise the cached map state")
    show.add_argument(
        "--map", dest="map_id", default=DEFAULT_MAP, help="map id (default: %(default)s)"
    )
    show.set_defaults(func=_cmd_show)

    chunkinfo = subcommands.add_parser(
        "chunkinfo", help="download upstream's chunk/challenge reference data and cache it"
    )
    chunkinfo.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="request timeout in seconds (default: %(default)s)",
    )
    chunkinfo.set_defaults(func=_cmd_chunkinfo)

    # An I/O command like `fetch`/`chunkinfo`, so no `--export-json`: its
    # product is the cache blob, and `fray estimate --export-json` is how the
    # numbers come back out.
    heuristics = subcommands.add_parser(
        "heuristics", help="download the wiki/spreadsheet rates the estimator spends"
    )
    heuristics.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="request timeout in seconds (default: %(default)s)",
    )
    heuristics.add_argument(
        "--chunkinfo",
        type=Path,
        default=None,
        help="path to a chunkinfo export, overriding the cache and FRAY_CHUNKINFO",
    )
    heuristics.set_defaults(func=_cmd_heuristics)

    estimate_cmd = subcommands.add_parser(
        "estimate", help="roughly how long the outstanding active tasks would take"
    )
    estimate_cmd.add_argument(
        "bucket",
        nargs="?",
        default=None,
        metavar="BUCKET",
        help=f"drill into one bucket, one of: {', '.join(BUCKETS)}",
    )
    estimate_cmd.add_argument(
        "--limit", type=int, default=None, help="cap the tasks listed for BUCKET"
    )
    estimate_cmd.add_argument(
        "--map", dest="map_id", default=DEFAULT_MAP, help="map id (default: %(default)s)"
    )
    estimate_cmd.add_argument(
        "--chunkinfo",
        type=Path,
        default=None,
        help="path to a chunkinfo export, overriding the cache and FRAY_CHUNKINFO",
    )
    estimate_cmd.add_argument(
        "--export-json",
        metavar="PATH",
        default=None,
        help="write the full result as JSON to PATH, or to stdout if PATH is '-'",
    )
    estimate_cmd.add_argument(
        "--recompute",
        action="store_true",
        help="ignore any cached derivation and compute (and re-store) a fresh one",
    )
    estimate_cmd.set_defaults(func=_cmd_estimate)

    sections = subcommands.add_parser(
        "sections", help="reachable sections for the cached map's unlocked chunks"
    )
    sections.add_argument(
        "target",
        nargs="?",
        default=None,
        metavar="[list|CHUNK_ID]",
        help="'list' for every unlocked chunk, or a chunk id to inspect; omit for counts only",
    )
    sections.add_argument(
        "--limit", type=int, default=None, help="cap the number of chunks printed by 'list'"
    )
    sections.add_argument(
        "--map", dest="map_id", default=DEFAULT_MAP, help="map id (default: %(default)s)"
    )
    sections.add_argument(
        "--chunkinfo",
        type=Path,
        default=None,
        help="path to a chunkinfo export, overriding the cache and FRAY_CHUNKINFO",
    )
    sections.add_argument(
        "--export-json",
        metavar="PATH",
        default=None,
        help="write the full result as JSON to PATH, or to stdout if PATH is '-'",
    )
    sections.add_argument(
        "--recompute",
        action="store_true",
        help="ignore any cached derivation and compute (and re-store) a fresh one",
    )
    sections.set_defaults(func=_cmd_sections)

    sources = subcommands.add_parser(
        "sources", help="items/objects/monsters/npcs/shops the cached map's unlocked chunks give"
    )
    sources.add_argument(
        "category",
        nargs="?",
        default=None,
        choices=SOURCE_CATEGORIES,
        help=f"one of {SOURCE_CATEGORIES} to list its contents; omit for counts only",
    )
    sources.add_argument(
        "--limit", type=int, default=None, help="cap the number of names printed"
    )
    sources.add_argument(
        "--map", dest="map_id", default=DEFAULT_MAP, help="map id (default: %(default)s)"
    )
    sources.add_argument(
        "--chunkinfo",
        type=Path,
        default=None,
        help="path to a chunkinfo export, overriding the cache and FRAY_CHUNKINFO",
    )
    sources.add_argument(
        "--export-json",
        metavar="PATH",
        default=None,
        help="write the full result as JSON to PATH, or to stdout if PATH is '-'",
    )
    sources.add_argument(
        "--recompute",
        action="store_true",
        help="ignore any cached derivation and compute (and re-store) a fresh one",
    )
    sources.set_defaults(func=_cmd_sources)

    tasks = subcommands.add_parser(
        "tasks", help="which challenges are currently valid for the cached map"
    )
    tasks.add_argument(
        "category",
        nargs="?",
        default=None,
        help="a challenge category (e.g. Cooking, Nonskill) to list its valid tasks",
    )
    tasks.add_argument(
        "--limit", type=int, default=None, help="cap the number of tasks printed"
    )
    tasks.add_argument(
        "--map", dest="map_id", default=DEFAULT_MAP, help="map id (default: %(default)s)"
    )
    tasks.add_argument(
        "--chunkinfo",
        type=Path,
        default=None,
        help="path to a chunkinfo export, overriding the cache and FRAY_CHUNKINFO",
    )
    tasks.add_argument(
        "--export-json",
        metavar="PATH",
        default=None,
        help="write the full result as JSON to PATH, or to stdout if PATH is '-'",
    )
    tasks.add_argument(
        "--recompute",
        action="store_true",
        help="ignore any cached derivation and compute (and re-store) a fresh one",
    )
    tasks.set_defaults(func=_cmd_tasks)

    unlock = subcommands.add_parser(
        "unlock", help="tasks/sections a candidate chunk would add, on top of the cached map"
    )
    unlock.add_argument("--chunk", dest="chunk_id", required=True, help="candidate chunk id")
    unlock.add_argument(
        "--cache-map",
        dest="cache_map",
        metavar="NAME",
        default=None,
        help="save the post-unlock state as a cached map under NAME, readable with --map",
    )
    unlock.add_argument(
        "--map", dest="map_id", default=DEFAULT_MAP, help="map id (default: %(default)s)"
    )
    unlock.add_argument(
        "--chunkinfo",
        type=Path,
        default=None,
        help="path to a chunkinfo export, overriding the cache and FRAY_CHUNKINFO",
    )
    unlock.add_argument(
        "--export-json",
        metavar="PATH",
        default=None,
        help="write the full result as JSON to PATH, or to stdout if PATH is '-'",
    )
    unlock.add_argument(
        "--recompute",
        action="store_true",
        help="ignore any cached derivation and compute (and re-store) a fresh one",
    )
    unlock.set_defaults(func=_cmd_unlock)

    # `--map1`/`--map2` rather than this file's usual single `--map`, and both
    # required: a diff against a defaulted map id would compare the wrong two
    # worlds on a typo and still print a plausible answer.
    diff = subcommands.add_parser(
        "diff", help="compare two cached maps: what the second has that the first doesn't, and back"
    )
    diff.add_argument("--map1", required=True, metavar="MAPID", help="the map to compare from")
    diff.add_argument("--map2", required=True, metavar="MAPID", help="the map to compare to")
    diff.add_argument(
        "branch",
        nargs="?",
        default=None,
        metavar="BRANCH",
        help=f"list one branch's names in full, one of: {', '.join(BRANCHES)}",
    )
    diff.add_argument("--limit", type=int, default=None, help="cap the lines printed for BRANCH")
    diff.add_argument(
        "--chunkinfo",
        type=Path,
        default=None,
        help="path to a chunkinfo export, overriding the cache and FRAY_CHUNKINFO",
    )
    diff.add_argument(
        "--export-json",
        metavar="PATH",
        default=None,
        help="write the full result as JSON to PATH, or to stdout if PATH is '-'",
    )
    diff.add_argument(
        "--recompute",
        action="store_true",
        help="ignore any cached derivation and compute (and re-store) a fresh one",
    )
    diff.set_defaults(func=_cmd_diff)

    neighbours = subcommands.add_parser(
        "neighbours",
        help="chunks eligible to be unlocked next, numbered the way the canvas numbers them",
    )
    neighbours.add_argument(
        "--limit", type=int, default=None, help="cap the number of neighbours printed"
    )
    neighbours.add_argument(
        "--map", dest="map_id", default=DEFAULT_MAP, help="map id (default: %(default)s)"
    )
    neighbours.add_argument(
        "--chunkinfo",
        type=Path,
        default=None,
        help="path to a chunkinfo export, overriding the cache and FRAY_CHUNKINFO",
    )
    neighbours.add_argument(
        "--export-json",
        metavar="PATH",
        default=None,
        help="write the full result as JSON to PATH, or to stdout if PATH is '-'",
    )
    neighbours.add_argument(
        "--recompute",
        action="store_true",
        help="ignore any cached derivation and compute (and re-store) a fresh one",
    )
    neighbours.set_defaults(func=_cmd_neighbours)

    simulate = subcommands.add_parser(
        "simulate", help="simulate N chunk rolls from the cached map and accumulate their tasks"
    )
    simulate.add_argument(
        "--rolls", type=int, required=True, help="number of chunks to roll"
    )
    simulate.add_argument(
        "--seed", type=int, default=None, help="RNG seed, for a reproducible run"
    )
    simulate.add_argument(
        "--cache-map",
        dest="cache_map",
        metavar="NAME",
        default=None,
        help="save each run as a cached map under NAME, readable with --map",
    )
    simulate.add_argument(
        "--runs",
        type=int,
        default=1,
        help="number of independent simulations to run (needs --cache-map; default: %(default)s)",
    )
    simulate.add_argument(
        "--cache-behaviour",
        dest="cache_behaviour",
        choices=[behaviour.value for behaviour in CacheBehaviour],
        default=CacheBehaviour.ALL.value,
        help="which derived states to keep in the derivation cache (default: %(default)s)",
    )
    simulate.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="worker processes to spread the runs over (default: %(default)s)",
    )
    simulate.add_argument(
        "--map", dest="map_id", default=DEFAULT_MAP, help="map id (default: %(default)s)"
    )
    simulate.add_argument(
        "--chunkinfo",
        type=Path,
        default=None,
        help="path to a chunkinfo export, overriding the cache and FRAY_CHUNKINFO",
    )
    simulate.add_argument(
        "--export-json",
        metavar="PATH",
        default=None,
        help="write the full result as JSON to PATH, or to stdout if PATH is '-'",
    )
    simulate.add_argument(
        "--recompute",
        action="store_true",
        help="ignore any cached derivation and compute (and re-store) a fresh one",
    )
    simulate.set_defaults(func=_cmd_simulate)

    # The only nested subcommand here: `maps` is three verbs over one noun,
    # two of them destructive, and `--rm NAME`-style flags read far worse for
    # those than `maps rm NAME` does.
    maps = subcommands.add_parser("maps", help="list, remove or clean cached maps")
    maps.set_defaults(func=_cmd_maps_list, runs=False, export_json=None)
    map_verbs = maps.add_subparsers(dest="maps_command")

    maps_list = map_verbs.add_parser("list", help="list cached maps (the default)")
    maps_list.add_argument(
        "--runs", action="store_true", help="also list each batch's individual runs"
    )
    maps_list.add_argument(
        "--export-json",
        metavar="PATH",
        default=None,
        help="write the listing as JSON to PATH, or to stdout if PATH is '-'",
    )
    maps_list.set_defaults(func=_cmd_maps_list)

    maps_rm = map_verbs.add_parser("rm", help="remove a computed batch, a single run, or a map")
    maps_rm.add_argument(
        "names", nargs="+", metavar="NAME", help="map id, e.g. Demo or Demo/run-002"
    )
    maps_rm.add_argument(
        "--include-fetched",
        action="store_true",
        help="allow removing a fetched map, not just computed ones",
    )
    maps_rm.set_defaults(func=_cmd_maps_rm)

    # Same nested shape as `maps`, for the other on-disk cache. No
    # `--include-fetched`-style guard here: a cached derivation is pure derived
    # data, so the worst a wrong `clean` costs is recomputation.
    derived = subcommands.add_parser("derived", help="inspect or clean the cached derivations")
    derived.set_defaults(func=_cmd_derived_list, verbose=False)
    derived_verbs = derived.add_subparsers(dest="derived_command")

    derived_list = derived_verbs.add_parser("list", help="summarise the cache (the default)")
    derived_list.add_argument(
        "--verbose", action="store_true", help="list every entry, not just the totals"
    )
    derived_list.set_defaults(func=_cmd_derived_list)

    derived_clean = derived_verbs.add_parser("clean", help="drop entries that haven't been read")
    derived_clean.add_argument(
        "--older-than",
        type=float,
        default=DEFAULT_DERIVED_MAX_AGE_DAYS,
        metavar="DAYS",
        help="drop entries not read for this many days (default: %(default)s)",
    )
    derived_clean.add_argument(
        "--all", action="store_true", help="drop every entry, whenever it was last read"
    )
    derived_clean.set_defaults(func=_cmd_derived_clean)

    maps_clean = map_verbs.add_parser(
        "clean", help="remove every map this project computed (simulated and unlocked)"
    )
    maps_clean.add_argument(
        "--include-fetched",
        action="store_true",
        help="also remove fetched maps (never the chunkinfo/tasks-map blobs)",
    )
    maps_clean.set_defaults(func=_cmd_maps_clean)

    search = subcommands.add_parser(
        "search", help="fuzzy-search items/monsters/npcs/objects/shops/tasks across the whole map"
    )
    search.add_argument("query", help="text to search for")
    search.add_argument(
        "--type",
        dest="type",
        action="append",
        choices=TYPES,
        default=None,
        help="restrict to one entity type (repeat --type to combine); default: search all",
    )
    search.add_argument(
        "--limit", type=int, default=10, help="max results (default: %(default)s)"
    )
    search.add_argument(
        "--map", dest="map_id", default=DEFAULT_MAP, help="map id (default: %(default)s)"
    )
    search.add_argument(
        "--chunkinfo",
        type=Path,
        default=None,
        help="path to a chunkinfo export, overriding the cache and FRAY_CHUNKINFO",
    )
    search.add_argument(
        "--export-json",
        metavar="PATH",
        default=None,
        help="write the full result as JSON to PATH, or to stdout if PATH is '-'",
    )
    search.add_argument(
        "--recompute",
        action="store_true",
        help="ignore any cached derivation and compute (and re-store) a fresh one",
    )
    search.set_defaults(func=_cmd_search)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Before the handler, so it is the first thing on screen even when the
    # command then spends ten seconds deriving - and after parsing, so `--help`
    # and a usage error stay clean.
    print_watermark("fray")
    handler: Any = args.func
    try:
        return int(handler(args))
    except (FetchError, CacheMissError, NotImplementedError, ConvergenceError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
