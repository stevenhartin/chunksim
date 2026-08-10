"""`fray neighbours`: which chunks are eligible to unlock next.

Numbered the way source-chunk's own canvas numbers them - descending chunk id,
1-based - because the number is the thing you read off the screen when
deciding, and a different numbering here would be worse than none.
`derive/neighbours.py` owns that and the `sectionsLimits` gate.
"""

from __future__ import annotations
import argparse

from pathlib import Path

from fray_claude.cli.common import DEFAULT_MAP, derive_cached, emit_json, load_state
from fray_claude.derive.graph import build_section_graph
from fray_claude.derive.neighbours import eligible_neighbours


def _cmd_neighbours(args: argparse.Namespace) -> int:
    state, unlocked = load_state(args)
    entries = eligible_neighbours(
        state, unlocked, derive_cached(args, state, unlocked), graph=build_section_graph(state.chunk_info)
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
        emit_json(
            {
                "map_id": args.map_id,
                "unlocked_chunks": len(unlocked),
                "neighbours": [entry.as_dict() for entry in entries],
            },
            args.export_json,
        )
    return 0


def add_arguments(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """This family's subcommands and their flags."""
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
