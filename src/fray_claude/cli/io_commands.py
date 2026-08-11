"""The four subcommands that talk to the network or summarise what they wrote.

`fetch`, `show`, `chunkinfo` and `heuristics`. They are grouped because of
what they have in common and what they lack: each is a thin shell over
`remote/`, none derives anything, and **none of them carries `--export-json`
or `--recompute`** - there is no derivation to export or to recompute, and a
flag that means one thing on nine subcommands must not mean something else on
these.

`show` is the exception that proves it: it reads only what `fetch` already
wrote, which is why it can report the map's shape without a `ChunkInfo` parse.
It also reports whether the DPS extra is installed, because an estimate
computed with it is a materially different number from one without and nothing
else on that screen would say so.
"""

from __future__ import annotations
import argparse
import sys

from pathlib import Path

from fray_claude.cli.common import DEFAULT_MAP
from fray_claude.costing import dps_bridge
from fray_claude.costing.heuristics import disagreements
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.derive.task_names import strip_task_markup
from fray_claude.model.summary import format_age, summarise
from fray_claude.remote.api import CHUNKINFO_URL, DEFAULT_TIMEOUT, TASKS_MAP_URL, fetch_chunkinfo, fetch_map, fetch_tasks_map
from fray_claude.remote.scrape import SOURCE as SCRAPE_SOURCE
from fray_claude.remote.scrape import recipe_coverage, scrape, scrape_recipes
from fray_claude.store.cache import CHUNKINFO_BLOB_NAME, FETCHED, RECIPES_BLOB_NAME, TASKS_MAP_BLOB_NAME, WIKI_RATES_BLOB_NAME, read_cache, read_chunkinfo, read_overrides, write_blob, write_cache


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
    if summary.slayer_locked is not None:
        # Printed only when set, unlike every line above it: an absent lock is
        # the ordinary case and "slayer unlocked" on every map would read as a
        # rule rather than as the alarm this is.
        task, level = summary.slayer_locked
        print(f"slayer locked  {strip_task_markup(task)} - capped at {level}")
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


def _cmd_recipes(args: argparse.Namespace) -> int:
    """`fray recipes`: what one action of a training method pays and costs.

    A dozen Bucket queries, one per skill that has recipes. Separate from
    `fray heuristics` because it fetches different things from a different API
    at a different cadence: a money-making guide's kph is somebody's estimate
    and moves, while "an attack potion is 25 xp and two ticks" is a fact about
    the game and does not.

    The coverage line that matters is the tick one. Experience alone is half a
    rate; without the action's duration there is nothing to divide by, so a
    skill with recipes and no ticks is covered on paper only.
    """
    recipes = scrape_recipes(timeout=args.timeout)
    path = write_blob(RECIPES_BLOB_NAME, recipes, SCRAPE_SOURCE)

    total_rows = total_ticked = 0
    for skill, (ticked, rows) in sorted(recipe_coverage(recipes).items()):
        share = f"{ticked / rows:.0%} timed" if rows else "none"
        print(f"{skill:<14} {rows:>5} recipes  ({share})")
        total_rows += rows
        total_ticked += ticked
    print(f"\n{'total':<14} {total_rows:>5} recipes, {total_ticked} with a tick cost")
    print(f"wrote {path} ({path.stat().st_size:,} bytes)")
    return 0


def add_arguments(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """This family's subcommands and their flags."""
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

    recipes = subcommands.add_parser(
        "recipes",
        help="download per-action experience and tick costs from the wiki",
    )
    recipes.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="request timeout in seconds (default: %(default)s)",
    )
    recipes.set_defaults(func=_cmd_recipes)
