"""What every subcommand needs before it can answer anything.

Loading a map into a `MapState`, deriving it through the cache, resolving
which map was meant, emitting JSON, and reporting an error the way `main`
expects. No rendering and no domain logic - the point is that a family module
can be read on its own.

**The names lost their leading underscore when they crossed a module
boundary.** They were private to one 1,700-line file; they are now the small
public surface every family imports, and calling them private would be a
comment that disagrees with the import list.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from chunksim.model.chunkinfo import ChunkInfo
from chunksim.derive.pipeline import Derived, MapState, load_map_state
from chunksim.model.firebase import reverse_tasks_map
from chunksim.store.cache import (
    FETCHED,
    CacheMissError,
    TASKS_MAP_BLOB_NAME,
    blob_path,
    chunkinfo_source,
    file_digest,
    read_blob,
    read_cache,
    list_maps,
    read_chunkinfo,
)
from chunksim.store.derived_cache import Digests, cached_derive


def emit_json(data: Any, destination: str) -> None:
    """Write `data` to `destination`: `-` means stdout, anything else a file path."""
    text = json.dumps(data, indent=2, sort_keys=True)
    if destination == "-":
        print(text)
    else:
        Path(destination).write_text(text + "\n", encoding="utf-8")


def digests(args: argparse.Namespace) -> Digests:
    """Content hashes of the reference data, for the derived cache's key."""
    return Digests(
        chunkinfo=file_digest(chunkinfo_source(override=args.chunkinfo)),
        tasks_map=file_digest(blob_path(TASKS_MAP_BLOB_NAME)),
    )


def derive_cached(
    args: argparse.Namespace,
    state: MapState,
    unlocked: Mapping[str, bool],
    known: Digests | None = None,
) -> Derived:
    """`derive` through the on-disk cache - see `derived_cache.py`.

    Every subcommand goes through here rather than calling `derive` directly,
    so `--recompute` means the same thing everywhere. Tests and the opt-in
    oracles keep calling `pipeline.derive`, which is what keeps them a
    cache-free correctness signal.

    `known` is a `Digests` the caller already has. Computing one hashes the
    10.3MB export and the 3.0MB tasks map, which costs about as much as a warm
    `cached_derive` returns in - so the handlers that derive twice, or that
    derive and then estimate, pass one rather than paying for it again.
    `gui/derivation.py` and `runs/batch.py` already worked this way.
    """
    return cached_derive(
        state, unlocked, digests(args) if known is None else known, refresh=args.recompute
    )


def load_state(
    args: argparse.Namespace,
    map_id: str | None = None,
    *,
    chunk_info: ChunkInfo | None = None,
) -> tuple[MapState, dict[str, bool]]:
    """The cached map, decoded into a `MapState` and its unlocked-chunk set.

    `map_id` overrides `args.map_id` and `chunk_info` reuses an already-parsed
    export, so `chunksim diff` can load two maps while paying the ~10MB parse once
    (`chunkinfo.py`: build one `ChunkInfo` per invocation).
    """
    envelope = read_cache(map_id if map_id is not None else args.map_id)
    info = chunk_info or ChunkInfo(read_chunkinfo(override=args.chunkinfo))
    try:
        tasks_map = reverse_tasks_map(read_blob(TASKS_MAP_BLOB_NAME)["data"])
    except CacheMissError:
        # No cached tasks map (e.g. a bare `--chunkinfo` override with no
        # `chunksim chunkinfo` run) - degrade gracefully rather than fail: see
        # `pipeline.load_map_state`'s docstring for what this costs.
        tasks_map = {}
    return load_map_state(envelope["data"], info, tasks_map)


def error(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


class MapAmbiguityError(Exception):
    """`--map` was omitted and the cache could not imply one."""


def resolve_map(map_id: str | None, root: Path | None = None) -> str:
    """The map a command means when `--map` was not typed.

    **There is no default map id.** There used to be one - a particular
    account's, hard-coded - and it made every command silently about one
    person's world. What a command can honestly infer instead is the cache:
    if exactly one map is cached, that is unambiguously the one you meant.

    **Only *fetched* maps count.** A simulated or edited map is something this
    project computed from one, so counting them would make the first `chunksim
    simulate` turn every later bare command into an ambiguity error - the tool
    would get harder to use the more you used it. Upstream state is what a map
    id names, and a fetched map is the only kind that is any.

    Zero and two-or-more are both errors, and deliberately different ones: an
    empty cache needs a fetch, an ambiguous one needs a choice. Neither guesses.
    Named here rather than in each family so no two subcommands can drift apart
    about which map they mean when you type neither.
    """
    if map_id is not None:
        return map_id
    fetched = sorted({e.map_id for e in list_maps(root) if e.kind == FETCHED})
    if not fetched:
        raise MapAmbiguityError(
            "no maps cached; run: chunksim fetch --map <id>  (the id is the "
            "`?<id>` part of your chunk-picker URL)"
        )
    if len(fetched) > 1:
        raise MapAmbiguityError(
            "several maps cached, so --map is required; choose one of: " + ", ".join(fetched)
        )
    return fetched[0]
