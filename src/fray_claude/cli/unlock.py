"""`fray unlock`: what one candidate chunk would add.

Additions only, and only over one `MapState` - `derive/unlock.py` owns the
attribution rule and its one exception. For two arbitrary maps, `fray diff` is
the symmetric question and a different one.

`--cache-map NAME` saves the post-unlock world through `batch.save_unlock`,
which is the same writer the GUI's Unlock button uses - one writer for the
metadata `maps list`, the picker and `read_batch` all read back.
"""

from __future__ import annotations
import argparse

from pathlib import Path
from typing import Any

from fray_claude.cli.common import DEFAULT_MAP, derive_cached, digests, emit_json, load_state
from fray_claude.derive.unlock import UnlockDelta, tasks_added_by
from fray_claude.runs.batch import save_unlock
from fray_claude.store.cache import read_cache


def _unlock_to_cache(args: argparse.Namespace, delta: UnlockDelta) -> str:
    """Save the post-unlock state as a cached map; returns the name claimed.

    `batch.save_unlock` does the writing, because the GUI's chunk panel saves
    one too and the metadata shape is what `maps list` and the picker read -
    see that function for why there is exactly one writer of it.
    """
    envelope = read_cache(args.map_id)
    saved = save_unlock(
        name=args.cache_map,
        payload=envelope["data"],
        delta=delta,
        base_map=args.map_id,
        base_fetched_at=envelope.get("fetched_at"),
    )
    return saved.name


def _cmd_unlock(args: argparse.Namespace) -> int:
    state, unlocked = load_state(args)
    # `tasks_added_by` derives twice - before and after - so hash once.
    known = digests(args)
    delta = tasks_added_by(
        state,
        unlocked,
        args.chunk_id,
        derive_with=lambda s, u: derive_cached(args, s, u, known),
    )
    saved = _unlock_to_cache(args, delta) if args.cache_map is not None else None

    if args.export_json != "-":
        print(f"map          {args.map_id}")
        print(f"chunk        {delta.chunk_id}")
        print(f"new tasks    {delta.task_count}")
        for skill, names in sorted(delta.new_tasks.items()):
            print(f"  {skill:<12} {len(names)}")
        print(f"new sections {sum(len(s) for s in delta.new_sections.values())}")
        if delta.bis_upgrades:
            print(f"bis upgrades {len(delta.bis_upgrades)}")
            for key, (previous, new) in sorted(delta.bis_upgrades.items()):
                print(f"  {key:<20} {previous or '(none)'} -> {new}")
        if delta.new_unsupported:
            print(f"new unsupported {len(delta.new_unsupported)} (see challenges.py)")
        if saved is not None:
            if saved != args.cache_map:
                print(f"name {args.cache_map!r} was taken; saved as {saved!r}")
            print(f"saved as     {saved}")
            print(f"read with    fray tasks --map {saved}")

    if args.export_json is not None:
        payload: dict[str, Any] = {"map_id": args.map_id, **delta.as_dict()}
        if saved is not None:
            payload["cached_map"] = saved
        emit_json(payload, args.export_json)
    return 0


def add_arguments(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """This family's subcommands and their flags."""
    unlock = subcommands.add_parser(
        "unlock", help="tasks/sections a candidate chunk would add, on top of the cached map"
    )
    unlock.add_argument("--chunk", dest="chunk_id", required=True, help="candidate chunk id")
    unlock.add_argument(
        "--cache-map",
        dest="cache_map",
        metavar="NAME",
        default=None,
        help="save the post-unlock state as a cached map under NAME, readable with --map",
    )
    unlock.add_argument(
        "--map", dest="map_id", default=DEFAULT_MAP, help="map id (default: %(default)s)"
    )
    unlock.add_argument(
        "--chunkinfo",
        type=Path,
        default=None,
        help="path to a chunkinfo export, overriding the cache and FRAY_CHUNKINFO",
    )
    unlock.add_argument(
        "--export-json",
        metavar="PATH",
        default=None,
        help="write the full result as JSON to PATH, or to stdout if PATH is '-'",
    )
    unlock.add_argument(
        "--recompute",
        action="store_true",
        help="ignore any cached derivation and compute (and re-store) a fresh one",
    )
    unlock.set_defaults(func=_cmd_unlock)
