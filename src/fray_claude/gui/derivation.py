"""Deriving a map for the GUI, and paying for it only when asked.

**The map view deliberately needs none of this.** A chunk's square is fixed by
its id, so rendering the world costs a 36KB read and no more - which is what
makes every view request milliseconds and why nothing has to be invalidated.
Everything *else* the CLI can answer - which sections you reach, what a chunk
gives you, which tasks are valid, what a candidate would add - needs the 10MB
export parsed and a full `derive` behind it.

So this module is the boundary between the two, and the rule it exists to keep
is: **a request that does not need a derivation must not pay for one.**
`server.py` calls `view_state` for the map and `derived_state` only for the
panels.

**`ChunkInfo` is loaded once and held**, because parsing the export takes about
a second and a panel that costs a second every time it opens is a panel nobody
opens twice. That makes this the first cached mutable state in the server, and
it is worth naming rather than discovering: the pure layer's no-module-state
rule is about `simulate --jobs` running it in worker processes, and none of
this is on that path. The cache lives on a `Context` instance, not in a module
global, so two servers in one process would not share it.

Derivations themselves go through `derived_cache.cached_derive`, the same
on-disk cache every subcommand uses, so a panel opened here is warm if you have
already run `fray tasks` and vice versa.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fray_claude.store import cache
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.store.derived_cache import Digests, cached_derive
from fray_claude.model.firebase import reverse_tasks_map
from fray_claude.pipeline import Derived, MapState, load_map_state


@dataclass(frozen=True)
class DerivedState:
    """One map, parsed and derived: everything a panel could want."""

    map_id: str
    state: MapState
    unlocked: dict[str, bool]
    derived: Derived


class Derivations:
    """The export, the tasks map and their digests, loaded on demand.

    One instance per `Context`. Loading is guarded by a lock so two requests
    arriving together parse the export once rather than twice - the browser
    opening a panel and polling at the same time is the normal case, not a
    contrived one.
    """

    def __init__(self, root: Path | None = None, chunkinfo: Path | None = None) -> None:
        self._root = root
        self._chunkinfo_override = chunkinfo
        self._lock = threading.Lock()
        self._info: ChunkInfo | None = None
        self._tasks_map: dict[str, str] | None = None
        self._digests: Digests | None = None

    @property
    def loaded(self) -> bool:
        """Whether the export has been parsed yet. For reporting, not logic."""
        return self._info is not None

    def chunk_info(self) -> ChunkInfo:
        """The parsed export, loading it the first time it is wanted."""
        with self._lock:
            if self._info is None:
                self._info = ChunkInfo(
                    cache.read_chunkinfo(override=self._chunkinfo_override, root=self._root)
                )
            return self._info

    def _reverse_tasks(self) -> dict[str, str]:
        with self._lock:
            if self._tasks_map is None:
                blob = cache.read_blob(cache.TASKS_MAP_BLOB_NAME, self._root)
                self._tasks_map = reverse_tasks_map(blob["data"])
            return self._tasks_map

    def digests(self) -> Digests:
        """Content hashes keying the on-disk derivation cache."""
        with self._lock:
            if self._digests is None:
                self._digests = Digests(
                    chunkinfo=cache.file_digest(
                        cache.chunkinfo_source(self._chunkinfo_override, self._root)
                    ),
                    tasks_map=cache.file_digest(
                        cache.blob_path(cache.TASKS_MAP_BLOB_NAME, self._root)
                    ),
                )
            return self._digests

    def reset(self) -> None:
        """Forget the parsed export, so the next request reloads it.

        Called when `fray chunkinfo` refreshes the file underneath us. The
        alternative - reasoning about which parts of a parsed export a new one
        invalidates - is the invalidation problem this server was built to
        avoid, and dropping the lot costs one second.
        """
        with self._lock:
            self._info = None
            self._tasks_map = None
            self._digests = None

    def state_of(self, map_id: str) -> tuple[MapState, dict[str, bool]]:
        """One map parsed but **not** derived.

        For a caller that will derive several *different* unlocked sets off
        one `MapState` - the timeline prices every step of a run, and only
        the last of those is the map's own set. Deriving that one first, just
        to throw the `Derived` away, is a wasted second on a cold cache.

        Still pays the export parse, so this is not the cheap path: the map
        view uses `unlocked_of` and touches none of this.
        """
        envelope = cache.read_cache(map_id, self._root)
        return load_map_state(envelope["data"], self.chunk_info(), self._reverse_tasks())

    def load(self, map_id: str) -> DerivedState:
        """Parse and derive one map.

        Not memoised per map on purpose. `cached_derive` already caches the
        expensive half on disk, keyed by everything that could change it, so a
        second call is ~0.15s; a memo here would instead have to notice a
        `fray fetch` landing under it, which is the invalidation problem this
        server exists without.
        """
        info = self.chunk_info()
        envelope = cache.read_cache(map_id, self._root)
        state, unlocked = load_map_state(envelope["data"], info, self._reverse_tasks())
        derived = cached_derive(state, unlocked, self.digests(), root=self._root)
        return DerivedState(map_id=map_id, state=state, unlocked=unlocked, derived=derived)


def unlocked_of(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """The unlocked set out of a raw envelope, tolerating a missing branch.

    The map view's whole input. Kept here beside `Derivations` so the cheap
    path and the expensive one are visibly the same boundary.
    """
    chunks = envelope.get("data", {}).get("chunks", {})
    unlocked = chunks.get("unlocked") if isinstance(chunks, dict) else None
    return unlocked if isinstance(unlocked, dict) else {}


__all__ = ["DerivedState", "Derivations", "unlocked_of"]
