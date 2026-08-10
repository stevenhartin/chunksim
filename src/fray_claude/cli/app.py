"""The parser, and the one place a subcommand's exceptions become an exit code.

`build_parser` builds the root parser and then asks each family to add its own
subcommands, in the order they appear on `fray --help`. `main` dispatches
purely through `args.func` - no name table, no `if` chain - and funnels
`FetchError`, `CacheMissError`, `NotImplementedError` and `ConvergenceError`
into a stderr line and exit 1.

**This file used to be all of `fray`, at 1,750 lines.** The families it now
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
  four I/O ones.
- **`--limit`** defaults to `None` - full output - for `sections`, `sources`,
  `tasks`, `neighbours` and `diff`, so piping to `grep` or `less` needs no
  flag; but to `10` for `search`, where the tail of a fuzzy ranking is noise
  rather than data.
"""


import argparse
import json
import sys
from typing import Any

from fray_claude.remote.api import FetchError
from fray_claude.store.build_info import print_watermark
from fray_claude.store.cache import CacheMissError
from fray_claude.derive.challenges import strip_task_markup
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.derive.delta import compare_maps
from fray_claude.cli import (
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
from fray_claude.cli.common import error, load_state
from fray_claude.cli.render import display_tasks
from fray_claude.store.derived_cache import CacheBehaviour
from fray_claude.derive.pipeline import ConvergenceError, load_map_state



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fray", description="Offline tooling for source-chunk map state."
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
    print_watermark("fray")
    handler: Any = args.func
    try:
        return int(handler(args))
    except (FetchError, CacheMissError, NotImplementedError, ConvergenceError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
