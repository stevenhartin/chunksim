"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
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
    read_cache,
    read_chunkinfo,
    write_blob,
    write_cache,
)
from fray_claude.challenges import UNSUPPORTED_CATEGORIES, calc_challenges
from fray_claude.chunkinfo import ChunkInfo
from fray_claude.firebase import decode_payload
from fray_claude.sections import expand_chunk_areas, unlocked_sections
from fray_claude.sources import gather_chunks_info
from fray_claude.summary import _mapping, summarise

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


def _cmd_sections(args: argparse.Namespace) -> int:
    envelope = read_cache(args.map_id)
    payload = envelope["data"]
    info = ChunkInfo(read_chunkinfo(override=args.chunkinfo))

    # Neither branch used here (`chunks.unlocked`, `chunkinfo.manualSections`)
    # references `t_N` task ids, so decoding with no tasks map is safe - see
    # `firebase.decode_payload`.
    unlocked = decode_payload(_mapping(_mapping(payload, "chunks"), "unlocked"))
    manual_sections = decode_payload(_mapping(_mapping(payload, "chunkinfo"), "manualSections"))
    settings = _mapping(payload, "settings")

    reachable = unlocked_sections(
        unlocked,
        info,
        manual_sections=manual_sections,
        opt_out_sections=settings.get("optOutSections") is True,
        opt_out_sections_water=settings.get("optOutSectionsWater") is True,
    )
    total_sections = sum(len(sections) for sections in reachable.values())

    # `--export-json -` replaces the text summary on stdout, so a pipe sees
    # only JSON; a file destination leaves stdout for the summary as usual.
    if args.export_json != "-":
        print(f"map                {args.map_id}")
        print(f"unlocked chunks    {len(unlocked)}")
        print(f"sectioned chunks   {len(reachable)}")
        print(f"reachable sections {total_sections}")

    if args.export_json is not None:
        _emit_json(
            {"map_id": args.map_id, "unlocked_chunks": len(unlocked), "sections": reachable},
            args.export_json,
        )
    return 0


def _cmd_sources(args: argparse.Namespace) -> int:
    envelope = read_cache(args.map_id)
    payload = envelope["data"]
    info = ChunkInfo(read_chunkinfo(override=args.chunkinfo))
    chunkinfo_branch = _mapping(payload, "chunkinfo")

    # None of these branches reference `t_N` task ids (they hold chunk,
    # item, monster, and rule names), so decoding with no tasks map is safe
    # - see `firebase.decode_payload`.
    unlocked = decode_payload(_mapping(_mapping(payload, "chunks"), "unlocked"))
    manual_sections = decode_payload(_mapping(chunkinfo_branch, "manualSections"))
    manual_monsters = decode_payload(_mapping(chunkinfo_branch, "manualMonsters"))
    manual_equipment = decode_payload(_mapping(chunkinfo_branch, "manualEquipment"))
    backlogged_sources = decode_payload(_mapping(chunkinfo_branch, "backloggedSources"))
    rules = decode_payload(_mapping(payload, "rules"))
    settings = _mapping(payload, "settings")

    reachable = unlocked_sections(
        unlocked,
        info,
        manual_sections=manual_sections,
        opt_out_sections=settings.get("optOutSections") is True,
        opt_out_sections_water=settings.get("optOutSectionsWater") is True,
    )
    expanded = expand_chunk_areas(unlocked)
    index = gather_chunks_info(
        expanded,
        reachable,
        info,
        rules=rules,
        backlogged_sources=backlogged_sources,
        manual_monsters=manual_monsters,
        manual_equipment=manual_equipment,
    )

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


def _cmd_tasks(args: argparse.Namespace) -> int:
    envelope = read_cache(args.map_id)
    payload = envelope["data"]
    info = ChunkInfo(read_chunkinfo(override=args.chunkinfo))
    chunkinfo_branch = _mapping(payload, "chunkinfo")

    # None of these branches reference `t_N` task ids, so decoding with no
    # tasks map is safe - see `firebase.decode_payload`.
    unlocked = decode_payload(_mapping(_mapping(payload, "chunks"), "unlocked"))
    manual_sections = decode_payload(_mapping(chunkinfo_branch, "manualSections"))
    manual_monsters = decode_payload(_mapping(chunkinfo_branch, "manualMonsters"))
    manual_equipment = decode_payload(_mapping(chunkinfo_branch, "manualEquipment"))
    backlogged_sources = decode_payload(_mapping(chunkinfo_branch, "backloggedSources"))
    max_skill = decode_payload(_mapping(chunkinfo_branch, "maxSkill"))
    rules = decode_payload(_mapping(payload, "rules"))
    settings = _mapping(payload, "settings")

    reachable = unlocked_sections(
        unlocked,
        info,
        manual_sections=manual_sections,
        opt_out_sections=settings.get("optOutSections") is True,
        opt_out_sections_water=settings.get("optOutSectionsWater") is True,
    )
    expanded = expand_chunk_areas(unlocked)
    index = gather_chunks_info(
        expanded,
        reachable,
        info,
        rules=rules,
        backlogged_sources=backlogged_sources,
        manual_monsters=manual_monsters,
        manual_equipment=manual_equipment,
    )
    result = calc_challenges(expanded, reachable, index, info, rules=rules, max_skill=max_skill)
    total_valid = sum(len(names) for names in result.valid.values())

    if args.export_json != "-":
        print(f"map          {args.map_id}")
        print(f"valid tasks  {total_valid}")
        for skill, names in sorted(result.valid.items()):
            print(f"  {skill:<12} {len(names)}")
        print(f"unsupported  {len(result.unsupported)} individual tasks (see CLAUDE.md)")
        print(
            f"not computed {', '.join(sorted(UNSUPPORTED_CATEGORIES))} "
            "(whole categories - absence isn't 'none valid', see CLAUDE.md)"
        )

    if args.export_json is not None:
        _emit_json({"map_id": args.map_id, **result.as_dict()}, args.export_json)
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
