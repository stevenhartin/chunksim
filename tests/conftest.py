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
*and* `CHUNKSIM_MAP_CACHE`, which is presence-only and says "this checkout's own
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
from collections.abc import Callable
from typing import Any

import pytest

from chunksim.store.cache import data_root, read_blob, read_cache, read_chunkinfo
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.model.firebase import reverse_tasks_map
from chunksim.derive.pipeline import Derived, MapState, derive, load_map_state

#: The raw export, or `chunksim chunkinfo`'s envelope around one - `read_chunkinfo`
#: takes either since `cache._unwrapped_export`.
REAL_EXPORT = os.environ.get("CHUNKSIM_CHUNKINFO")

#: Presence-only: its value is never read. It says "this checkout's `cache/` is
#: populated", because the map is read through `cache.data_root()` rather
#: than from anything this variable names.
REAL_CACHE = os.environ.get("CHUNKSIM_MAP_CACHE")

#: The map the oracles are recorded against.
ORACLE_MAP = "fray"

#: Presence-only, like `REAL_CACHE`. Gates the oracles measured in minutes -
#: today the carry equality run, which simulates both cached maps twice over.
#: Kept off the ordinary oracle run so that stays worth typing.
SLOW_ORACLES = os.environ.get("CHUNKSIM_SLOW_ORACLES")

_NO_EXPORT = pytest.mark.skip(
    reason="set CHUNKSIM_CHUNKINFO to a chunk export (raw or the cached envelope) to run this"
)

_NO_SLOW = pytest.mark.skip(
    reason="set CHUNKSIM_SLOW_ORACLES (with CHUNKSIM_CHUNKINFO and CHUNKSIM_MAP_CACHE) to run this"
)

_NO_CACHE = pytest.mark.skip(
    reason=(
        "set CHUNKSIM_CHUNKINFO to a chunk export and CHUNKSIM_MAP_CACHE to anything; the map "
        "itself is read from the repo's own cache/, so CHUNKSIM_MAP_CACHE's value is unused"
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
        if item.get_closest_marker("slow") and not (REAL_EXPORT and REAL_CACHE and SLOW_ORACLES):
            item.add_marker(_NO_SLOW)
        elif item.get_closest_marker("real_cache") and not (REAL_EXPORT and REAL_CACHE):
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
    return reverse_tasks_map(read_blob("tasks_map", data_root())["data"])


@pytest.fixture(scope="session")
def real_payload() -> dict[str, Any]:
    """The cached map payload the oracles are recorded in.

    The payload, not the envelope: every caller wants `envelope["data"]`, and
    the oracles themselves live inside it under `chunkinfo.activeTasks`.
    """
    payload: dict[str, Any] = read_cache(ORACLE_MAP, data_root())["data"]
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
    """Stop an exported `CHUNKSIM_CHUNKINFO` shadowing a test's own `tmp_path`.

    Any test calling `cache.read_chunkinfo()` without an explicit `override`
    needs this, or it reads the developer's real export instead of the fixture
    it just built - and passes or fails for reasons that have nothing to do
    with it.
    """
    monkeypatch.delenv("CHUNKSIM_CHUNKINFO", raising=False)


# --- what the CLI tests share --------------------------------------------
#
# **Fixtures returning callables, rather than plain functions.** `tests/` is not
# a package, so a helper module here could only be imported by accident of
# `sys.path`; a fixture is the mechanism pytest already provides for sharing
# setup, and it carries `monkeypatch` for free rather than taking it as an
# argument at every call site.


@pytest.fixture(autouse=True)
def no_real_user_data(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """**A test that escapes its root must not reach the developer's own data.**

    `cache.data_root` falls back to `user_data_root()` when there is no
    checkout and no `CHUNKSIM_CACHE`, which is right for an installed program
    and a trap here: a fixture that builds a not-quite-checkout used to write
    into the working directory, where it was at least visible, and would now
    write into `~/.local/share/chunksim` instead. That happened once, during
    the change that introduced this - two tests fetched a map into the real
    home directory and only failed for an unrelated reason.

    Autouse, because the tests that need protecting are exactly the ones that
    did not think to ask for it.
    """
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("XDG_DATA_HOME", str(home / "share"))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData" / "Local"))
    monkeypatch.delenv("CHUNKSIM_CACHE", raising=False)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway checkout root that `cache.data_root()` will find.

    **Both markers, because `checkout_root` wants both.** `pyproject.toml`
    alone is any Python project, and an installed `chunksim` must not treat one
    of those as its home - so a fixture standing in for the checkout has to
    look like the checkout.
    """
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "src" / "chunksim").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def cached_map(monkeypatch: pytest.MonkeyPatch) -> Callable[[dict[str, Any], dict[str, Any]], None]:
    """Fetch a payload into the temporary cache and fake the export.

    **Two readers, and both must be patched.** `chunksim chunkinfo` and `fray
    heuristics` read the export through `cli.io_commands`; every derivation
    command reads it through `cli.common.load_state`. Patching one leaves the
    other reading the developer's real cache - which is not a failing test but
    a passing one, computed against the wrong map.
    """
    from chunksim.cli.app import main

    def cache(payload: dict[str, Any], chunkinfo_data: dict[str, Any]) -> None:
        monkeypatch.setattr(
            "chunksim.cli.io_commands.fetch_map",
            lambda map_id, timeout=30.0: payload,
        )
        main(["fetch", "--map", ORACLE_MAP])
        for module in ("io_commands", "common"):
            monkeypatch.setattr(
                f"chunksim.cli.{module}.read_chunkinfo",
                lambda override=None, root=None: chunkinfo_data,
            )

    return cache


@pytest.fixture
def simulatable(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    """Cache a map and an export that `chunksim simulate` can actually roll from.

    Writes the export as a *blob* rather than patching the reader, because
    `batch.run_one` resolves its own copy in a worker process - which is the
    point of the worker design and would be invisible to a patch made in the
    parent.
    """
    from chunksim.cli.app import main
    from chunksim.store.cache import write_blob

    def prepare() -> None:
        monkeypatch.delenv("CHUNKSIM_CHUNKINFO", raising=False)
        monkeypatch.setattr(
            "chunksim.cli.io_commands.fetch_map",
            lambda map_id, timeout=30.0: {"chunks": {"unlocked": {"100": "100"}}},
        )
        main(["fetch", "--map", ORACLE_MAP])
        write_blob(
            "chunkinfo",
            {"sections": {"101": {"0": ["100"]}, "102": {"0": ["101"]}}},
            "test",
        )

    return prepare


@pytest.fixture
def derived_entries() -> Callable[[Path], list[Path]]:
    """Everything `cache/derived/` holds under a project root, or nothing."""

    def entries(project: Path) -> list[Path]:
        directory = project / "cache" / "derived"
        return sorted(directory.iterdir()) if directory.is_dir() else []

    return entries
