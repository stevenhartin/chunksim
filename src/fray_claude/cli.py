"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from typing import Any

from fray_claude.api import DEFAULT_TIMEOUT, FetchError, fetch_map
from fray_claude.cache import CacheMissError, read_cache, write_cache
from fray_claude.summary import summarise

DEFAULT_MAP = "fray"


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

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler: Any = args.func
    try:
        return int(handler(args))
    except (FetchError, CacheMissError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
