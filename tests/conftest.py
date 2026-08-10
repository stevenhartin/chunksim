"""What the oracle tests share, so they set up once rather than twelve times.

**The problem this solves is duplication, and the speed is a side effect.**
Twelve tests across eight files are gated on the real export, and each one
re-declared the same two `os.environ.get` lookups, the same copy-pasted skipif
reason, and the same five-line ritual: parse the ~10MB export, read the repo's
own `cache/`, rebuild the tasks map, `load_map_state`, `derive`. Eight copies of
a setup is eight places to update when the setup changes, which is the cost this
whole refactor is about.

The measurable part is **not** the parse, which is what it looks like: reading
and parsing the 10MB export costs 0.050s, so twelve copies of it were never the
problem. It is the `derive` each one then ran - ~0.9s apiece, seven of them
against the same map. Sharing that took the oracle run from 10.35s to 6.42s.

**The gating markers are the load-bearing half.** A real-cache test must skip on
a fresh clone, not fail, and it must be gated on **both** variables - the export
*and* `FRAY_MAP_CACHE`, which is presence-only and says "this checkout's own
`cache/` is populated, read it". Two tests were once gated on the export alone
and so failed with `CacheMissError` for anyone who had not fetched a map. One
marker each removes the chance of getting that wrong again.

They are **real pytest markers applied at collection**, not `skipif` objects a
test file imports: `tests/` is not a package, so `from .conftest import …` does
not work and `import conftest` would only work by accident of `sys.path`. A test
writes `@pytest.mark.real_cache` and needs no import; `pytest_collection_modifyitems`
below attaches the skip. It also means `-m real_cache` selects them.

**Session scope is safe here and is not a cache.** `ChunkInfo`, `MapState` and
`Derived` are frozen or read-only by construction, so one instance shared across
tests cannot drift; and `real_derived` calls `pipeline.derive` **directly, never
`cached_derive`**, so the oracles stay the cache-free correctness signal CLAUDE.md
says they are. This is one computation shared, not a stored answer reused.

Deliberately small. Anything here is depended on by every test file in the
project, so a helper earns its place by being duplicated *in substance* - not by
being merely common. `_chunk_info`, fifteen copies of `return ChunkInfo(data)`,
stays where it is: promoting a one-liner would make fifteen files depend on this
module for nothing.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from fray_claude.cache import project_root, read_blob, read_cache, read_chunkinfo
from fray_claude.chunkinfo import ChunkInfo
from fray_claude.firebase import reverse_tasks_map
from fray_claude.pipeline import Derived, MapState, derive, load_map_state

#: The raw export, or `fray chunkinfo`'s envelope around one - `read_chunkinfo`
#: takes either since `cache._unwrapped_export`.
REAL_EXPORT = os.environ.get("FRAY_CHUNKINFO")

#: Presence-only: its value is never read. It says "this checkout's `cache/` is
#: populated", because the map is read through `cache.project_root()` rather
#: than from anything this variable names.
REAL_CACHE = os.environ.get("FRAY_MAP_CACHE")

#: The map the oracles are recorded against.
ORACLE_MAP = "fray"

_NO_EXPORT = pytest.mark.skip(
    reason="set FRAY_CHUNKINFO to a chunk export (raw or the cached envelope) to run this"
)

_NO_CACHE = pytest.mark.skip(
    reason=(
        "set FRAY_CHUNKINFO to a chunk export and FRAY_MAP_CACHE to anything; the map "
        "itself is read from the repo's own cache/, so FRAY_MAP_CACHE's value is unused"
    )
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip the opt-in oracles unless their inputs are present.

    Applied here rather than as a `skipif` per test so the two conditions are
    stated once. A missing input **skips** - never fails - because a fresh
    clone has neither the 10MB export nor a fetched map, and a red suite there
    would say something untrue about the code.
    """
    for item in items:
        if item.get_closest_marker("real_cache") and not (REAL_EXPORT and REAL_CACHE):
            item.add_marker(_NO_CACHE)
        elif item.get_closest_marker("real_export") and not REAL_EXPORT:
            item.add_marker(_NO_EXPORT)


@pytest.fixture(scope="session")
def real_export() -> ChunkInfo:
    """The real export, parsed once for the whole session."""
    assert REAL_EXPORT is not None, "guarded by requires_real_export"
    return ChunkInfo(read_chunkinfo(override=Path(REAL_EXPORT)))


@pytest.fixture(scope="session")
def real_tasks_map() -> dict[str, str]:
    """`tasksMap.json` inverted, so `t_N` ids read back as names."""
    return reverse_tasks_map(read_blob("tasks_map", project_root())["data"])


@pytest.fixture(scope="session")
def real_payload() -> dict[str, Any]:
    """The cached map payload the oracles are recorded in.

    The payload, not the envelope: every caller wants `envelope["data"]`, and
    the oracles themselves live inside it under `chunkinfo.activeTasks`.
    """
    payload: dict[str, Any] = read_cache(ORACLE_MAP, project_root())["data"]
    return payload


@pytest.fixture(scope="session")
def real_state(
    real_export: ChunkInfo, real_tasks_map: dict[str, str], real_payload: dict[str, Any]
) -> tuple[MapState, dict[str, bool]]:
    """`load_map_state` over the real map, once."""
    return load_map_state(real_payload, real_export, real_tasks_map)


@pytest.fixture(scope="session")
def real_derived(real_state: tuple[MapState, dict[str, bool]]) -> Derived:
    """`pipeline.derive` over the real map - **not** `cached_derive`.

    The oracles exist to catch a defect in this code, so they must not be able
    to pass by reading an answer this code stored earlier.
    """
    state, unlocked = real_state
    return derive(state, unlocked)


@pytest.fixture
def no_ambient_chunkinfo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop an exported `FRAY_CHUNKINFO` shadowing a test's own `tmp_path`.

    Any test calling `cache.read_chunkinfo()` without an explicit `override`
    needs this, or it reads the developer's real export instead of the fixture
    it just built - and passes or fails for reasons that have nothing to do
    with it.
    """
    monkeypatch.delenv("FRAY_CHUNKINFO", raising=False)
