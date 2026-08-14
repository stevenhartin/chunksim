"""The parser, and the one place a subcommand's exceptions become an exit code.

`build_parser` builds the root parser and then asks each family to add its own
subcommands, in the order they appear on `chunksim --help`. `main` dispatches
purely through `args.func` - no name table, no `if` chain - and funnels
`FetchError`, `CacheMissError`, `NotImplementedError` and `ConvergenceError`
into a stderr line and exit 1.

**This file used to be all of `chunksim`, at 1,750 lines.** The families it now
calls are one module each, parser beside handler, so changing a flag edits one
file and `tests/test_cli_<family>.py` is the file that checks it. What is left
here is the assembly: if it is about a particular subcommand, it does not
belong in this module.

Two conventions span the families and so are stated here rather than in any
one of them:

- **`--export-json PATH`** writes a subcommand's full result as JSON, or to
  stdout when `PATH` is `-` - in which case it *replaces* the human-readable
  summary rather than interleaving with it, so piping stays clean. Carried by
  the nine derivation subcommands plus `maps list`, whose output is a
  reduction over the cache rather than a cache file; deliberately not by the
  five I/O ones.
- **`--limit`** defaults to `None` - full output - for `estimate`, `sections`,
  `sources`, `tasks`, `neighbours` and `diff`, so piping to `grep` or `less`
  needs no flag; but to `10` for `search`, where the tail of a fuzzy ranking is
  noise rather than data.
"""


import argparse
import json
import sys
from typing import Any

from chunksim.remote.api import FetchError
from chunksim.store.build_info import print_watermark
from chunksim.store.cache import CacheMissError
from chunksim.derive.task_names import strip_task_markup
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.derive.delta import compare_maps
from chunksim.cli import (
    derived,
    diff,
    estimate,
    io_commands,
    listing,
    maps,
    neighbours,
    search,
    simulate,
    unlock,
)
from chunksim.cli.common import MapAmbiguityError, error, load_state, resolve_map
from chunksim.cli.render import display_tasks
from chunksim.store.derived_cache import CacheBehaviour
from chunksim.derive.pipeline import ConvergenceError, load_map_state



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chunksim", description="Offline tooling for source-chunk map state."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    io_commands.add_arguments(subcommands)

    estimate.add_arguments(subcommands)

    listing.add_arguments(subcommands)

    unlock.add_arguments(subcommands)

    # `--map1`/`--map2` rather than this file's usual single `--map`, and both
    # required: a diff against a defaulted map id would compare the wrong two
    # worlds on a typo and still print a plausible answer.
    diff.add_arguments(subcommands)

    neighbours.add_arguments(subcommands)

    simulate.add_arguments(subcommands)

    # The only nested subcommand here: `maps` is three verbs over one noun,
    # two of them destructive, and `--rm NAME`-style flags read far worse for
    # those than `maps rm NAME` does.
    maps.add_arguments(subcommands)

    derived.add_arguments(subcommands)

    search.add_arguments(subcommands)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Before the handler, so it is the first thing on screen even when the
    # command then spends ten seconds deriving - and after parsing, so `--help`
    # and a usage error stay clean.
    print_watermark("chunksim")
    # **Resolved once, here, rather than in each handler.** `args.map_id` is
    # read in some forty places downstream - printed, keyed on, written into
    # exported JSON - and every one of them wants the id that was *meant*. So
    # the omitted-`--map` case is settled before any handler runs, and no
    # handler has to know the default is inferred rather than declared.
    if hasattr(args, "map_id") and args.map_id is None:
        try:
            args.map_id = resolve_map(None)
        except MapAmbiguityError as exc:
            return error(str(exc))
    handler: Any = args.func
    try:
        return int(handler(args))
    except (FetchError, CacheMissError, NotImplementedError, ConvergenceError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
