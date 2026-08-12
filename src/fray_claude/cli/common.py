"""What every subcommand needs before it can answer anything.

Loading a map into a `MapState`, deriving it through the cache, emitting JSON,
and reporting an error the way `main` expects. Five functions, no rendering and
no domain logic - the point is that a family module can be read on its own.

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

from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.derive.pipeline import Derived, MapState, load_map_state
from fray_claude.model.firebase import reverse_tasks_map
from fray_claude.store.cache import (
    DEFAULT_MAP_ID,
    CacheMissError,
    TASKS_MAP_BLOB_NAME,
    blob_path,
    chunkinfo_source,
    file_digest,
    read_blob,
    read_cache,
    read_chunkinfo,
)
from fray_claude.store.derived_cache import Digests, cached_derive


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
    export, so `fray diff` can load two maps while paying the ~10MB parse once
    (`chunkinfo.py`: build one `ChunkInfo` per invocation).
    """
    envelope = read_cache(map_id if map_id is not None else args.map_id)
    info = chunk_info or ChunkInfo(read_chunkinfo(override=args.chunkinfo))
    try:
        tasks_map = reverse_tasks_map(read_blob(TASKS_MAP_BLOB_NAME)["data"])
    except CacheMissError:
        # No cached tasks map (e.g. a bare `--chunkinfo` override with no
        # `fray chunkinfo` run) - degrade gracefully rather than fail: see
        # `pipeline.load_map_state`'s docstring for what this costs.
        tasks_map = {}
    return load_map_state(envelope["data"], info, tasks_map)


def error(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


#: What `--map` defaults to everywhere. Named here rather than in each family
#: so `fray tasks` and `fray sections` cannot drift apart about which map they
#: mean when you type neither.
DEFAULT_MAP = DEFAULT_MAP_ID
