"""On-disk cache of fetched map state, kept in the project's `cache/` directory.

The only module that touches disk; raises `CacheMissError`. A map payload is
stored in an envelope (`map_id`/`fetched_at`/`source`/`is_simulated`/`data`), so
readers go through the `data` key. `cache/` is found by walking up to the nearest
`pyproject.toml`, which lets the CLI run from any subdirectory.

Non-map blobs (the chunkinfo export, the tasks map) go through the generic
`write_blob`/`read_blob` pair instead. `read_chunkinfo` layers an override
(`--chunkinfo` / the `FRAY_CHUNKINFO` env var) in front of the cached copy,
for working from an export you already have locally - note that path reads
the file directly, with no `["data"]` unwrapping, so it wants a *raw* export
rather than this module's own envelope.

**Two kinds of map live here.** A *fetched* map is a flat `cache/<id>.json`,
written by `fray fetch` from upstream. A *simulated* map is anything this
project computed instead - `fray simulate --cache-map` and
`fray unlock --cache-map` both land here - stored one directory per run under
a named batch::

    cache/sims/<batch>/batch.json          # every run's seed and rolled chunks
    cache/sims/<batch>/run-001/map.json    # envelope, `is_simulated: true`
    cache/sims/<batch>/run-001/rolls.json  # that run's UnlockRecord ledger
    cache/sims/<batch>/run-001/run.json    # this run's seed/rolls, for listing

`read_cache` resolves both, so no subcommand needs to know which it has: a
fetched `cache/<id>.json` wins, then `<batch>/run-00N`, then a bare `<batch>`
with exactly one run (which is what makes `--cache-map X` followed by
`--map X` work). A bare batch name with several runs is an error naming them
rather than a guess. Ids are validated before they reach the filesystem, so a
`--map ../../etc/passwd` cannot escape `cache/`.

A third kind of thing lives here: `cache/derived/<key>` holds cached *results*
of `pipeline.derive` (see `derived_cache.py` for the key and the codec). Those
are pure derived data - deleting the lot only costs recomputation - which is
why `fray derived clean` needs no guard while `fray maps rm` does.

Everything here is written so a batch can be produced by several processes at
once (see `batch.py`): `claim_sim_batch` uses `mkdir(exist_ok=False)` as an
atomic claim rather than a check-then-create, and every write lands through a
temp file in the destination directory followed by `os.replace`, so an
interrupted run leaves either the old file or the new one and never a
half-written envelope that later reads as malformed. The derived cache needs no
lock for the same reason plus one more: two processes that computed the same
key wrote the same bytes, so either rename winning is correct. Its only mutable
field is the mtime `read_derived` touches, which is a single atomic syscall.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fray_claude.api import map_url

CACHE_DIR_NAME = "cache"
SIMS_DIR_NAME = "sims"
DERIVED_DIR_NAME = "derived"
_ROOT_MARKER = "pyproject.toml"

CHUNKINFO_BLOB_NAME = "chunkinfo"
TASKS_MAP_BLOB_NAME = "tasks_map"
CHUNKINFO_ENV_VAR = "FRAY_CHUNKINFO"

MAP_FILE_NAME = "map.json"
ROLLS_FILE_NAME = "rolls.json"
RUN_META_FILE_NAME = "run.json"
BATCH_META_FILE_NAME = "batch.json"
RUN_PREFIX = "run-"

FETCHED = "fetched"
SIMULATED = "simulated"

#: A batch name: no separators, no `..`, nothing the shell or `Path` would
#: reinterpret. A map id is one of these, optionally followed by `/run-<n>`.
_NAME_RE = re.compile(r"[A-Za-z0-9_.-]+")
_RUN_RE = re.compile(rf"{RUN_PREFIX}\d+")
#: A derived-cache key: hex digest plus the suffix its codec claims.
_DERIVED_KEY_RE = re.compile(r"[0-9a-f]{16,64}\.[a-z0-9.]{1,12}")


class CacheMissError(Exception):
    """No usable cached copy exists for the requested map or blob."""


def project_root(start: Path | None = None) -> Path:
    """Nearest ancestor holding `pyproject.toml`, falling back to `start`.

    Walking up means the cache resolves to the same place whether the CLI is run
    from the repo root or a subdirectory.
    """
    origin = (start or Path.cwd()).resolve()
    for candidate in (origin, *origin.parents):
        if (candidate / _ROOT_MARKER).is_file():
            return candidate
    return origin


def cache_path(map_id: str, root: Path | None = None) -> Path:
    """Return the cache file for `map_id`."""
    return (root or project_root()) / CACHE_DIR_NAME / f"{map_id}.json"


def sims_root(root: Path | None = None) -> Path:
    """Return the directory simulated batches live under."""
    return (root or project_root()) / CACHE_DIR_NAME / SIMS_DIR_NAME


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> Path:
    """Write `payload` as JSON so readers see all of it or none of it.

    The temp file is created in the destination directory so `os.replace` is a
    same-filesystem rename, which is what makes it atomic.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)
    return path


def write_cache(map_id: str, data: dict[str, Any], root: Path | None = None) -> Path:
    """Write `data` in an envelope recording when and where it came from."""
    envelope = {
        "map_id": map_id,
        "fetched_at": datetime.now(UTC).isoformat(),
        "source": map_url(map_id),
        "is_simulated": False,
        "data": data,
    }
    return _atomic_write_json(cache_path(map_id, root), envelope)


def split_map_id(map_id: str) -> tuple[str, str | None]:
    """Split `map_id` into its batch name and optional `run-<n>` part.

    Raises `CacheMissError` for anything that isn't a plain name or a
    `<name>/run-<n>` pair, so no caller can be talked into a path traversal.
    """
    name, _, run = map_id.partition("/")
    if not _NAME_RE.fullmatch(name) or name in {".", ".."}:
        raise CacheMissError(f"invalid map id {map_id!r}")
    if not run:
        return name, None
    if not _RUN_RE.fullmatch(run):
        raise CacheMissError(f"invalid map id {map_id!r}: expected '<name>/{RUN_PREFIX}<n>'")
    return name, run


def _run_dirs(batch_dir: Path) -> list[Path]:
    """Every run directory in `batch_dir`, in run order."""
    if not batch_dir.is_dir():
        return []
    return sorted(
        entry
        for entry in batch_dir.iterdir()
        if entry.is_dir() and _RUN_RE.fullmatch(entry.name) and (entry / MAP_FILE_NAME).is_file()
    )


def resolve_map_path(map_id: str, root: Path | None = None) -> Path:
    """Return the envelope file `map_id` names, fetched or simulated.

    A fetched `cache/<id>.json` wins; then `<batch>/run-00N`; then a bare
    `<batch>` holding exactly one run. Several runs is an error rather than a
    guess, because picking one silently would make `fray tasks --map <batch>`
    report a different world each time a run was added.
    """
    fetched = cache_path(map_id, root) if "/" not in map_id else None
    if fetched is not None and fetched.is_file():
        return fetched

    name, run = split_map_id(map_id)
    batch_dir = sims_root(root) / name
    if run is not None:
        path = batch_dir / run / MAP_FILE_NAME
        if path.is_file():
            return path
        raise CacheMissError(f"no simulated run {map_id!r}; run: fray maps list")

    runs = _run_dirs(batch_dir)
    if len(runs) == 1:
        return runs[0] / MAP_FILE_NAME
    if runs:
        names = ", ".join(f"{name}/{d.name}" for d in runs)
        raise CacheMissError(f"map {name!r} holds {len(runs)} runs; name one of: {names}")
    if fetched is not None:
        raise CacheMissError(f"no cached data for map {map_id!r}; run: fray fetch --map {map_id}")
    raise CacheMissError(f"no cached data for map {map_id!r}; run: fray maps list")


def read_cache(map_id: str, root: Path | None = None) -> dict[str, Any]:
    """Return the cached envelope for `map_id`, fetched or simulated.

    The payload itself is under the `data` key; the rest is provenance.
    """
    path = resolve_map_path(map_id, root)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:  # pragma: no cover - resolve_map_path checked
        raise CacheMissError(f"no cached data for map {map_id!r}") from exc

    try:
        envelope: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CacheMissError(f"cache for map {map_id!r} is not valid JSON") from exc

    if not isinstance(envelope, dict) or not isinstance(envelope.get("data"), dict):
        raise CacheMissError(f"cache for map {map_id!r} is malformed")
    return envelope


def blob_path(name: str, root: Path | None = None) -> Path:
    """Return the cache file for a non-map blob (the chunkinfo export, tasks map)."""
    return (root or project_root()) / CACHE_DIR_NAME / f"{name}.json"


def write_blob(name: str, data: dict[str, Any], source: str, root: Path | None = None) -> Path:
    """Write `data` under `name`, in the same provenance envelope as `write_cache`."""
    path = blob_path(name, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "name": name,
        "fetched_at": datetime.now(UTC).isoformat(),
        "source": source,
        "data": data,
    }
    path.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
    return path


def read_blob(name: str, root: Path | None = None) -> dict[str, Any]:
    """Return the cached envelope for `name`."""
    path = blob_path(name, root)
    hint = "run: fray chunkinfo"
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CacheMissError(f"no cached data for {name!r}; {hint}") from exc

    try:
        envelope: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CacheMissError(f"cache for {name!r} is not valid JSON; {hint}") from exc

    if not isinstance(envelope, dict) or not isinstance(envelope.get("data"), dict):
        raise CacheMissError(f"cache for {name!r} is malformed; {hint}")
    return envelope


def claim_sim_batch(name: str, root: Path | None = None) -> Path:
    """Create and return a fresh batch directory for `name`.

    `mkdir(exist_ok=False)` *is* the claim: it either creates the directory or
    raises, so two processes racing on the same name cannot both believe they
    won it. On a clash the name gains `-2`, `-3`, ... - including a clash with
    a *fetched* `cache/<name>.json`, so a simulated batch can never shadow a
    fetched map or make `--map <name>` ambiguous.
    """
    split_map_id(name)
    base = sims_root(root)
    base.mkdir(parents=True, exist_ok=True)
    suffix = 1
    while True:
        candidate = name if suffix == 1 else f"{name}-{suffix}"
        directory = base / candidate
        if not cache_path(candidate, root).exists():
            try:
                directory.mkdir(exist_ok=False)
            except FileExistsError:
                pass
            else:
                return directory
        suffix += 1


def run_dir(batch_dir: Path, index: int) -> Path:
    """The directory for run `index` (1-based) of `batch_dir`."""
    return batch_dir / f"{RUN_PREFIX}{index:03d}"


def write_sim_run(
    directory: Path,
    *,
    map_id: str,
    data: dict[str, Any],
    simulation: dict[str, Any],
    ledger: list[dict[str, Any]],
    source: str | None = None,
) -> Path:
    """Write one synthetic run: its envelope, its ledger, and its metadata.

    `map.json` is what `read_cache` reads; `rolls.json` is the full per-roll
    ledger; `run.json` is the small summary `list_maps` reads, so listing a
    100-run batch never opens a payload. The envelope mirrors `write_cache`'s,
    with `is_simulated` true and a `simulation` block for provenance.

    `source` overrides that provenance line for a run this project produced
    some way other than rolling - `fray unlock --cache-map` writes one. It is
    the *only* thing distinguishing the two here: `is_simulated` stays true
    and `MapEntry.kind` stays `SIMULATED`, because both mean "this project
    computed it, upstream never saw it", which is equally true of either. A
    third `kind` would have to be taught to `remove_map`'s `include_fetched`
    guard, `remove_all_simulated` and `fray maps clean` to buy nothing.
    """
    directory.mkdir(parents=True, exist_ok=True)
    envelope = {
        "map_id": map_id,
        "fetched_at": datetime.now(UTC).isoformat(),
        "source": source or f"simulated from {simulation.get('base_map')!r}",
        "is_simulated": True,
        "simulation": simulation,
        "data": data,
    }
    _atomic_write_json(directory / ROLLS_FILE_NAME, {"rolls": ledger})
    _atomic_write_json(directory / RUN_META_FILE_NAME, simulation)
    # Last, so a run directory only reads as usable once the rest is on disk.
    return _atomic_write_json(directory / MAP_FILE_NAME, envelope)


def write_sim_batch(directory: Path, meta: dict[str, Any]) -> Path:
    """Write a batch's `batch.json` summary (the parent process's only write)."""
    return _atomic_write_json(directory / BATCH_META_FILE_NAME, meta)


def read_sim_batch(name: str, root: Path | None = None) -> dict[str, Any]:
    """Return a batch's summary, rebuilt from its runs if `batch.json` is absent.

    An interrupted batch has run directories but no summary, and those runs are
    still perfectly good simulated maps - so listing falls back to reading each
    `run.json` rather than pretending the batch isn't there.
    """
    split_map_id(name)
    directory = sims_root(root) / name
    if not directory.is_dir():
        raise CacheMissError(f"no simulated map {name!r}; run: fray maps list")

    runs = [_read_run_meta(path) for path in _run_dirs(directory)]
    summary: dict[str, Any] = {"name": name, "runs": runs, "complete": False}
    try:
        stored = _read_json_object(directory / BATCH_META_FILE_NAME)
    except CacheMissError:
        return summary
    summary.update(stored)
    summary["runs"] = runs or stored.get("runs", [])
    summary["complete"] = True
    return summary


def _read_run_meta(directory: Path) -> dict[str, Any]:
    try:
        meta = _read_json_object(directory / RUN_META_FILE_NAME)
    except CacheMissError:
        meta = {}
    meta.setdefault("run", directory.name)
    return meta


@dataclass(frozen=True)
class MapEntry:
    """One row of `fray maps`: a fetched map, or a simulated batch/run."""

    map_id: str
    kind: str
    created_at: str | None = None
    unlocked_chunks: int | None = None
    rolls: int | None = None
    runs: int | None = None
    seed: int | None = None
    base_map: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "map_id": self.map_id,
            "kind": self.kind,
            "created_at": self.created_at,
            "unlocked_chunks": self.unlocked_chunks,
            "rolls": self.rolls,
            "runs": self.runs,
            "seed": self.seed,
            "base_map": self.base_map,
        }


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _fetched_entries(root: Path | None) -> list[MapEntry]:
    directory = (root or project_root()) / CACHE_DIR_NAME
    if not directory.is_dir():
        return []
    entries: list[MapEntry] = []
    for path in sorted(directory.glob("*.json")):
        name = path.stem
        if name in {CHUNKINFO_BLOB_NAME, TASKS_MAP_BLOB_NAME}:
            continue
        try:
            envelope = _read_json_object(path)
        except CacheMissError:
            continue
        if envelope.get("is_simulated") is True:
            continue
        unlocked = envelope.get("data")
        chunks = unlocked.get("chunks") if isinstance(unlocked, dict) else None
        held = chunks.get("unlocked") if isinstance(chunks, dict) else None
        entries.append(
            MapEntry(
                map_id=name,
                kind=FETCHED,
                created_at=_str_or_none(envelope.get("fetched_at")),
                unlocked_chunks=len(held) if isinstance(held, dict) else None,
            )
        )
    return entries


def list_maps(root: Path | None = None, *, expand_runs: bool = False) -> list[MapEntry]:
    """Every cached map: fetched ones first, then one row per simulated batch.

    `expand_runs` adds a row per run underneath its batch - useful for a
    handful of runs, noise for a hundred, which is why it isn't the default.
    """
    entries = _fetched_entries(root)
    base = sims_root(root)
    if not base.is_dir():
        return entries

    for directory in sorted(base.iterdir()):
        if not directory.is_dir():
            continue
        try:
            summary = read_sim_batch(directory.name, root)
        except CacheMissError:  # pragma: no cover - iterdir just listed it
            continue
        runs = summary.get("runs") or []
        entries.append(
            MapEntry(
                map_id=directory.name,
                kind=SIMULATED,
                created_at=_str_or_none(summary.get("created_at")),
                rolls=_int_or_none(summary.get("rolls_requested")),
                runs=len(runs),
                seed=_int_or_none(summary.get("seed")),
                base_map=_str_or_none(summary.get("base_map")),
            )
        )
        if not expand_runs:
            continue
        for run in runs:
            rolled = run.get("rolls")
            entries.append(
                MapEntry(
                    map_id=f"{directory.name}/{run.get('run')}",
                    kind=SIMULATED,
                    created_at=_str_or_none(run.get("created_at")),
                    unlocked_chunks=_int_or_none(run.get("unlocked_chunks")),
                    rolls=len(rolled) if isinstance(rolled, list) else None,
                    seed=_int_or_none(run.get("seed")),
                    base_map=_str_or_none(run.get("base_map")),
                )
            )
    return entries


def remove_map(map_id: str, root: Path | None = None, *, include_fetched: bool = False) -> Path:
    """Delete a simulated batch, a single simulated run, or a fetched map.

    A fetched map is upstream state that only `fray fetch` can replace, so
    removing one takes an explicit `include_fetched` - the simulated states are
    reproducible from their seeds, and are what routine cleanup is for.
    """
    name, run = split_map_id(map_id)
    fetched = cache_path(name, root)
    if run is None and fetched.is_file():
        if not include_fetched:
            raise CacheMissError(
                f"{map_id!r} is a fetched map, not a simulation; pass --include-fetched to remove it"
            )
        fetched.unlink()
        return fetched

    directory = sims_root(root) / name
    if run is not None:
        directory = directory / run
    if not directory.is_dir():
        raise CacheMissError(f"no cached map {map_id!r}; run: fray maps list")
    shutil.rmtree(directory)
    return directory


def remove_all_simulated(root: Path | None = None) -> list[str]:
    """Delete every simulated batch, leaving fetched maps and blobs alone."""
    base = sims_root(root)
    if not base.is_dir():
        return []
    removed: list[str] = []
    for directory in sorted(base.iterdir()):
        if directory.is_dir():
            shutil.rmtree(directory)
            removed.append(directory.name)
    return removed


def derived_root(root: Path | None = None) -> Path:
    """The directory cached derivations live in."""
    return (root or project_root()) / CACHE_DIR_NAME / DERIVED_DIR_NAME


def derived_path(key: str, root: Path | None = None) -> Path:
    """The file a derived-cache key names.

    `key` is a hex digest plus its codec's suffix (`derived_cache.py` builds
    it); anything else is rejected before it reaches the filesystem, on the
    same principle as `split_map_id`.
    """
    if not _DERIVED_KEY_RE.fullmatch(key):
        raise CacheMissError(f"invalid derived-cache key {key!r}")
    return derived_root(root) / key


def read_derived(key: str, root: Path | None = None) -> bytes | None:
    """Return a cached derivation's bytes, or `None` if there isn't one.

    Reading is what "used" means here, so this refreshes the file's mtime -
    one `os.utime`, atomic, needing no lock and no ledger, which is what
    `prune_derived` then reads as last-accessed. `st_atime` would be the
    obvious field and is not usable: `relatime`/`noatime` mounts make it a lie.

    A missing entry is `None` rather than an error, because every caller's
    response to one is the same: compute it.
    """
    path = derived_path(key, root)
    try:
        blob = path.read_bytes()
    except (FileNotFoundError, IsADirectoryError):
        return None
    try:
        os.utime(path)
    except OSError:
        # A read-only cache directory is still a perfectly good cache; it just
        # ages by creation time instead.
        pass
    return blob


def write_derived(key: str, blob: bytes, root: Path | None = None) -> Path:
    """Store a cached derivation.

    Same temp-file-plus-`os.replace` as every other write here, which is what
    makes concurrent writers safe *without* a lock: two workers that computed
    the same key wrote the same bytes, so whichever rename lands last is
    correct either way, and no reader ever sees a partial file.
    """
    path = derived_path(key, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_bytes(blob)
    os.replace(temp, path)
    return path


@dataclass(frozen=True)
class DerivedEntry:
    """One cached derivation on disk: `accessed_at` is its mtime."""

    key: str
    size: int
    accessed_at: datetime


def list_derived(root: Path | None = None) -> list[DerivedEntry]:
    """Every cached derivation, least recently used first."""
    directory = derived_root(root)
    if not directory.is_dir():
        return []
    entries = [
        DerivedEntry(
            key=path.name,
            size=path.stat().st_size,
            accessed_at=datetime.fromtimestamp(path.stat().st_mtime, UTC),
        )
        for path in directory.iterdir()
        if path.is_file() and _DERIVED_KEY_RE.fullmatch(path.name)
    ]
    return sorted(entries, key=lambda entry: entry.accessed_at)


def prune_derived(
    root: Path | None = None, *, max_age_days: float | None = None
) -> list[DerivedEntry]:
    """Delete cached derivations untouched for `max_age_days`, or all of them.

    Ages on *last access*, not creation: an entry read every day is worth
    keeping however old it is, and one written a month ago and never read
    since is not.
    """
    removed: list[DerivedEntry] = []
    cutoff = (
        None
        if max_age_days is None
        else datetime.now(UTC) - timedelta(days=max_age_days)
    )
    for entry in list_derived(root):
        if cutoff is not None and entry.accessed_at >= cutoff:
            continue
        try:
            derived_path(entry.key, root).unlink()
        except FileNotFoundError:  # pragma: no cover - another process got there first
            continue
        removed.append(entry)
    return removed


def _read_json_object(path: Path) -> dict[str, Any]:
    """Read one JSON object off disk, as itself - no envelope unwrapping.

    Shared by the `--chunkinfo` override and the batch/run metadata files, so
    the messages name the path rather than any one caller's flag.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CacheMissError(f"{path} not found") from exc
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CacheMissError(f"{path} is not valid JSON") from exc
    if not isinstance(data, dict):
        raise CacheMissError(f"{path} is not a JSON object")
    return data


def chunkinfo_source(override: Path | None = None, root: Path | None = None) -> Path:
    """The file `read_chunkinfo` would read: override, env var, then the cache."""
    path = override
    if path is None:
        env_value = os.environ.get(CHUNKINFO_ENV_VAR)
        path = Path(env_value) if env_value else None
    return path if path is not None else blob_path(CHUNKINFO_BLOB_NAME, root)


def read_chunkinfo(override: Path | None = None, root: Path | None = None) -> dict[str, Any]:
    """Return the parsed chunkinfo export.

    Checks `override`, then the `FRAY_CHUNKINFO` environment variable, before
    falling back to the copy `fray chunkinfo` cached from upstream.
    """
    path = override
    if path is None:
        env_value = os.environ.get(CHUNKINFO_ENV_VAR)
        path = Path(env_value) if env_value else None
    if path is not None:
        return _read_json_object(path)
    data: dict[str, Any] = read_blob(CHUNKINFO_BLOB_NAME, root)["data"]
    return data


def file_digest(path: Path) -> str:
    """A content hash of `path`, or `""` if it isn't readable.

    Used to key the derived cache on the reference data a derivation was
    computed against. sha256 over the whole ~10MB export measures at 4ms
    (it is hardware-accelerated), so this is cheap enough to do on every
    invocation and far safer than trusting size and mtime.

    An unreadable file hashes to `""` rather than raising: the caller is
    building a cache key, and the honest answer for "I could not identify the
    inputs" is a key that matches nothing.
    """
    try:
        with path.open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError:
        return ""
