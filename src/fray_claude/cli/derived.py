"""`fray derived`: what the cached derivations cost, and ageing them out.

`cache/derived/` is neither a map nor reference data - it is `pipeline.derive`'s
*results*, keyed by a hash of everything the derivation read, so an entry is
never *wrong*, only unreachable once its inputs move. That is why `clean` is
about disk rather than correctness, and why its default cut-off is generous.
"""

from __future__ import annotations
#: `fray derived clean`'s default cut-off. Entries are keyed by content, so a
#: stale one is never *wrong*, only unreachable - ageing them out is about disk,
#: not correctness, hence a generous default.
DEFAULT_DERIVED_MAX_AGE_DAYS = 14
import argparse


from fray_claude.model.summary import format_age
from fray_claude.store.cache import list_derived, prune_derived


def _cmd_derived_list(args: argparse.Namespace) -> int:
    entries = list_derived()
    if not entries:
        print("no cached derivations")
        return 0

    total = sum(entry.size for entry in entries)
    print(f"entries      {len(entries)}")
    print(f"size         {total / 1_048_576:.1f} MiB")
    print(f"oldest read  {format_age(entries[0].accessed_at.isoformat())}")
    print(f"newest read  {format_age(entries[-1].accessed_at.isoformat())}")
    if args.verbose:
        for entry in entries:
            age = format_age(entry.accessed_at.isoformat())
            print(f"  {entry.key}  {entry.size / 1024:>8.0f} KiB  read {age}")
    return 0


def _cmd_derived_clean(args: argparse.Namespace) -> int:
    max_age = None if args.all else args.older_than
    removed = prune_derived(max_age_days=max_age)
    if not removed:
        print("nothing to clean")
        return 0
    freed = sum(entry.size for entry in removed)
    scope = "all" if args.all else f"unread for {args.older_than:g} days"
    print(
        f"removed {len(removed)} cached derivations ({scope}), "
        f"freeing {freed / 1_048_576:.1f} MiB"
    )
    return 0


def add_arguments(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """This family's subcommands and their flags."""
    derived = subcommands.add_parser("derived", help="inspect or clean the cached derivations")
    derived.set_defaults(func=_cmd_derived_list, verbose=False)
    derived_verbs = derived.add_subparsers(dest="derived_command")

    derived_list = derived_verbs.add_parser("list", help="summarise the cache (the default)")
    derived_list.add_argument(
        "--verbose", action="store_true", help="list every entry, not just the totals"
    )
    derived_list.set_defaults(func=_cmd_derived_list)

    derived_clean = derived_verbs.add_parser("clean", help="drop entries that haven't been read")
    derived_clean.add_argument(
        "--older-than",
        type=float,
        default=DEFAULT_DERIVED_MAX_AGE_DAYS,
        metavar="DAYS",
        help="drop entries not read for this many days (default: %(default)s)",
    )
    derived_clean.add_argument(
        "--all", action="store_true", help="drop every entry, whenever it was last read"
    )
    derived_clean.set_defaults(func=_cmd_derived_clean)
