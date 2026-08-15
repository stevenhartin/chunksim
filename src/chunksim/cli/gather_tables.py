"""`chunksim gather-tables`: rebuild the gathering model's inputs, for a developer.

**The one subcommand here that writes into the source tree**, and the one a user
never runs. Everything else that fetches - `chunksim heuristics`, `chunksim
recipes`, `chunksim chunkinfo` - writes a *cache* blob that the user is expected
to refresh; this writes `src/chunksim/heuristics/gathering.json`, which is
checked in and shipped as package data, and is therefore a change to the project
rather than to somebody's cache.

That is deliberate and it is the whole design. A gathering rate is computed from
three tables - a success curve, a roll interval, a node cycle - and none of them
moves more than once a game update. Making every install re-read six hundred
wiki pages to learn that a willow tree still takes four ticks would buy nothing
and cost the estimator a network dependency it does not otherwise have. So the
tables are read here, once, by whoever is changing the model, and
`costing/gathering.py` reads only the file.

**Refetching is not part of the estimate.** `chunksim estimate` must never reach
this code, which is why the fetching is injected into `gathering.build_tables`
rather than imported by it: the pure module cannot open a socket even by
accident, and the only caller that hands it `api.py`'s functions is this one.

What it prints is coverage, for the same reason `chunksim heuristics` does - a
table is only as good as what it reached, and the count is the honest measure of
how much of the model is real data.
"""

from __future__ import annotations

import argparse

from chunksim.remote import gathering
from chunksim.remote.api import DEFAULT_TIMEOUT, fetch_wiki_pages, fetch_wiki_transclusions
from chunksim.store.cache import write_gathering
from chunksim.remote.scrape import SOURCE as SCRAPE_SOURCE


def _cmd_gather_tables(args: argparse.Namespace) -> int:
    """Read the wiki's gathering tables and write the shipped config."""
    tables = gathering.build_tables(
        lambda template: fetch_wiki_transclusions(template, timeout=args.timeout),
        lambda titles: fetch_wiki_pages(titles, timeout=args.timeout),
        progress=lambda step: print(f"  {step}"),
    )

    path = write_gathering(tables.as_dict(), SCRAPE_SOURCE, args.root)

    print()
    for source, (found, asked) in tables.sources.items():
        share = f" ({found / asked:.0%})" if asked else ""
        print(f"{source:<20} {found:>5}/{asked}{share}")
    for name, count in tables.counts.items():
        print(f"{name:<20} {count:>5}")

    curves = sum(len(series) for series in tables.curves.values())
    actions = sum(len(rows) for rows in tables.actions.values())
    print(f"\n{'curve series':<20} {curves:>5} across {len(tables.curves)} pages")
    print(f"{'calculator rows':<20} {actions:>5} across {len(tables.actions)} skills")
    print(f"\nwrote {path} ({path.stat().st_size:,} bytes)")
    print("this file is checked in - commit it with the change that needed it")
    return 0


def add_arguments(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """This family's subcommand and its flags."""
    # **No `--map` and no `--chunkinfo`.** The tables describe the game rather
    # than any map, which is what lets one checked-in file serve every install;
    # a flag naming a map here would imply otherwise.
    gather = subcommands.add_parser(
        "gather-tables",
        help="developer: rebuild src/chunksim/heuristics/gathering.json from the wiki",
    )
    gather.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"seconds to wait on each request (default {DEFAULT_TIMEOUT:g})",
    )
    gather.add_argument(
        "--root",
        default=None,
        help="write into this tree instead of the checkout (tests and dry runs)",
    )
    gather.set_defaults(func=_cmd_gather_tables)
