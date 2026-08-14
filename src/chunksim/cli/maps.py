"""`chunksim maps`: what is cached, and removing it.

This package's only *nested* subcommand (`maps list|rm|clean`). Two of the
three verbs are destructive, and `maps rm NAME` reads better than a `--rm
NAME` flag hung off a listing command.

`maps list` carries `--export-json` even though it is not a derivation: its
output is a reduction over the cache rather than a cache file, and it is the
index a batch analysis iterates. It is also where "you stopped this" gets
said, since a cancelled run is an ordinary cached map in every other respect.
"""

from __future__ import annotations
import argparse

from collections.abc import Iterable

from chunksim.cli.common import emit_json
from chunksim.model.summary import format_age
from chunksim.store.cache import FETCHED, MapEntry, list_maps, remove_computed, remove_map


def _maps_rows(entries: Iterable[MapEntry]) -> list[str]:
    """`chunksim maps` as fixed-width rows; runs indent under their batch."""
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
            print("no cached maps; run: chunksim fetch")
    if args.export_json is not None:
        emit_json({"maps": [entry.as_dict() for entry in entries]}, args.export_json)
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


def add_arguments(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """This family's subcommands and their flags."""
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

    maps_clean = map_verbs.add_parser(
        "clean", help="remove every map this project computed (simulated and unlocked)"
    )
    maps_clean.add_argument(
        "--include-fetched",
        action="store_true",
        help="also remove fetched maps (never the chunkinfo/tasks-map blobs)",
    )
    maps_clean.set_defaults(func=_cmd_maps_clean)
