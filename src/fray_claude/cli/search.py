"""`fray search`: the whole world, not just what this map can reach.

`derive/search.py` walks all five item routes over the raw export, so this is
a strict superset of what `fray sources` can list - which is the point, since
the question is usually "where would I have to go for this".

Two things differ from the listing commands. `--limit` defaults to **10**
rather than to everything, because the tail of a fuzzy ranking is noise; and
markup is stripped **per hit type** - task hits and `task:` routes only, never
blanket - so a genuinely tilde-named shop survives being displayed.
"""

from __future__ import annotations
import argparse

from pathlib import Path

from fray_claude.cli.common import DEFAULT_MAP, derive_cached, emit_json, load_state
from fray_claude.derive.task_names import strip_task_markup
from fray_claude.derive.search import TYPES, build_world_index, search


def _cmd_search(args: argparse.Namespace) -> int:
    state, unlocked = load_state(args)
    world = build_world_index(state.chunk_info)
    result = derive_cached(args, state, unlocked)
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
        emit_json(
            {"query": args.query, "hits": [hit.as_dict() for hit in hits]}, args.export_json
        )
    return 0


def add_arguments(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """This family's subcommands and their flags."""
    search_cmd = subcommands.add_parser(
        "search", help="fuzzy-search items/monsters/npcs/objects/shops/tasks across the whole map"
    )
    search_cmd.add_argument("query", help="text to search for")
    search_cmd.add_argument(
        "--type",
        dest="type",
        action="append",
        choices=TYPES,
        default=None,
        help="restrict to one entity type (repeat --type to combine); default: search all",
    )
    search_cmd.add_argument(
        "--limit", type=int, default=10, help="max results (default: %(default)s)"
    )
    search_cmd.add_argument(
        "--map", dest="map_id", default=DEFAULT_MAP, help="map id (default: %(default)s)"
    )
    search_cmd.add_argument(
        "--chunkinfo",
        type=Path,
        default=None,
        help="path to a chunkinfo export, overriding the cache and FRAY_CHUNKINFO",
    )
    search_cmd.add_argument(
        "--export-json",
        metavar="PATH",
        default=None,
        help="write the full result as JSON to PATH, or to stdout if PATH is '-'",
    )
    search_cmd.add_argument(
        "--recompute",
        action="store_true",
        help="ignore any cached derivation and compute (and re-store) a fresh one",
    )
    search_cmd.set_defaults(func=_cmd_search)
