"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fray_claude.api import (
    DEFAULT_TIMEOUT,
    CHUNKINFO_URL,
    TASKS_MAP_URL,
    FetchError,
    fetch_chunkinfo,
    fetch_map,
    fetch_tasks_map,
)
from fray_claude.cache import (
    CHUNKINFO_BLOB_NAME,
    TASKS_MAP_BLOB_NAME,
    CacheMissError,
    read_blob,
    read_cache,
    read_chunkinfo,
    write_blob,
    write_cache,
)
from fray_claude.challenges import strip_task_markup
from fray_claude.chunkinfo import ChunkInfo
from fray_claude.firebase import reverse_tasks_map
from fray_claude.pipeline import MapState, derive, load_map_state
from fray_claude.search import TYPES, build_world_index, search
from fray_claude.sections import describe_sections, expand_chunk_areas
from fray_claude.simulate import simulate_rolls
from fray_claude.sources import CATEGORIES as SOURCE_CATEGORIES
from fray_claude.summary import summarise
from fray_claude.unlock import tasks_added_by

DEFAULT_MAP = "fray"


def _emit_json(data: Any, destination: str) -> None:
    """Write `data` to `destination`: `-` means stdout, anything else a file path."""
    text = json.dumps(data, indent=2, sort_keys=True)
    if destination == "-":
        print(text)
    else:
        Path(destination).write_text(text + "\n", encoding="utf-8")


def _format_age(fetched_at: Any) -> str:
    """Render an ISO-8601 timestamp as a rough age."""
    if not isinstance(fetched_at, str):
        return "unknown"
    try:
        stamp = datetime.fromisoformat(fetched_at)
    except ValueError:
        return "unknown"
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)

    seconds = max(0, int((datetime.now(UTC) - stamp).total_seconds()))
    for limit, divisor, unit in ((60, 1, "s"), (3600, 60, "m"), (86400, 3600, "h")):
        if seconds < limit:
            return f"{seconds // divisor}{unit} ago"
    return f"{seconds // 86400}d ago"


def _cmd_fetch(args: argparse.Namespace) -> int:
    data = fetch_map(args.map_id, timeout=args.timeout)
    path = write_cache(args.map_id, data)
    print(f"fetched map {args.map_id!r} -> {path} ({path.stat().st_size:,} bytes)")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    envelope = read_cache(args.map_id)
    summary = summarise(envelope["data"])

    print(f"map            {args.map_id}")
    print(f"fetched        {_format_age(envelope.get('fetched_at'))}")
    print(f"unlocked       {summary.unlocked_chunks} chunks")
    print(f"chunk order    {summary.chunk_order_entries} entries")
    print(f"rules          {summary.rules_enabled} of {summary.rules_total} enabled")
    if summary.active_tasks:
        detail = ", ".join(f"{name} {count}" for name, count in summary.active_tasks.items())
        print(f"active tasks   {summary.active_task_total} ({detail})")
    else:
        print("active tasks   0")
    return 0


def _cmd_chunkinfo(args: argparse.Namespace) -> int:
    chunkinfo = fetch_chunkinfo(timeout=args.timeout)
    chunkinfo_path = write_blob(CHUNKINFO_BLOB_NAME, chunkinfo, CHUNKINFO_URL)
    print(f"fetched chunkinfo -> {chunkinfo_path} ({chunkinfo_path.stat().st_size:,} bytes)")

    tasks_map = fetch_tasks_map(timeout=args.timeout)
    tasks_map_path = write_blob(TASKS_MAP_BLOB_NAME, tasks_map, TASKS_MAP_URL)
    print(f"fetched tasks map -> {tasks_map_path} ({tasks_map_path.stat().st_size:,} bytes)")
    return 0


def _load_state(args: argparse.Namespace) -> tuple[MapState, dict[str, bool]]:
    envelope = read_cache(args.map_id)
    info = ChunkInfo(read_chunkinfo(override=args.chunkinfo))
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


def _print_capped(names: list[str], limit: int | None) -> None:
    shown = names if limit is None else names[:limit]
    for name in shown:
        print(f"  {name}")
    if limit is not None and len(names) > limit:
        print(f"  ... and {len(names) - limit} more (--limit {len(names)} to see all)")


def _cmd_sections(args: argparse.Namespace) -> int:
    state, unlocked = _load_state(args)
    result = derive(state, unlocked)

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
    index = derive(state, unlocked).source_index

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
    derived = derive(state, unlocked)
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
            # scale, the actionable split is below. `--export-json` still
            # carries the full per-category `valid` mapping.
            print(f"map          {args.map_id}")
            print(f"valid tasks  {total_valid}")
            print(f"unsupported  {len(result.unsupported)} individual tasks (see CLAUDE.md)")
            print(
                f"skill tasks  active {active_count}, completed {completed_count}, "
                f"obsolete {obsolete_count} (across {len(classifications)} skill categories)"
            )
            bis_line = f"  {'BiS':<10} active {len(derived.bis.active)}, completed {len(derived.bis.completed)}"
            if derived.bis.outdated:
                bis_line += f", outdated {len(derived.bis.outdated)}"
            print(bis_line)
        if args.export_json is not None:
            _emit_json(
                {
                    "map_id": args.map_id,
                    **result.as_dict(),
                    "bis": derived.bis.as_dict(),
                    "task_classification": derived.task_classification.as_dict(),
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
    result = derive(state, unlocked)
    hits = search(
        world, args.query, unlocked=unlocked, derived=result, types=args.type, limit=args.limit
    )

    if args.export_json != "-":
        print(f"query {args.query!r}")
        print(f"hits  {len(hits)}")
        for hit in hits:
            status = "available" if hit.available else "locked"
            # A no-op for every type but `task`, whose names carry the same
            # `~|...|~` markup - as do the challenge names behind a
            # `task:<category>` item route.
            print(f"{hit.type.upper():8} {strip_task_markup(hit.name)}  [{status}]")
            if hit.type == "item":
                for source in hit.detail["sources"]:
                    source_status = "available" if source["available"] else "locked"
                    source_name = strip_task_markup(source["name"])
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


def _cmd_unlock(args: argparse.Namespace) -> int:
    state, unlocked = _load_state(args)
    delta = tasks_added_by(state, unlocked, args.chunk_id)

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
            print(f"new unsupported {len(delta.new_unsupported)} (see CLAUDE.md)")

    if args.export_json is not None:
        _emit_json({"map_id": args.map_id, **delta.as_dict()}, args.export_json)
    return 0


def _cmd_simulate(args: argparse.Namespace) -> int:
    state, unlocked = _load_state(args)
    ledger = simulate_rolls(state, unlocked, rolls=args.rolls, seed=args.seed)
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
    tasks.set_defaults(func=_cmd_tasks)

    unlock = subcommands.add_parser(
        "unlock", help="tasks/sections a candidate chunk would add, on top of the cached map"
    )
    unlock.add_argument("--chunk", dest="chunk_id", required=True, help="candidate chunk id")
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
    unlock.set_defaults(func=_cmd_unlock)

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
    simulate.set_defaults(func=_cmd_simulate)

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
    search.set_defaults(func=_cmd_search)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler: Any = args.func
    try:
        return int(handler(args))
    except (FetchError, CacheMissError, NotImplementedError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
