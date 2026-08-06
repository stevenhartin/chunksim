"""On-disk cache of fetched map state, kept in the project's `cache/` directory.

The only module that touches disk; raises `CacheMissError`. A map payload is
stored in an envelope (`map_id`/`fetched_at`/`source`/`kind`/`data`), so readers
go through the `data` key. `cache/` is found by walking up to the nearest
`pyproject.toml`, which lets the CLI run from any subdirectory.

Non-map blobs (the chunkinfo export, the tasks map) go through the generic
`write_blob`/`read_blob` pair instead. `read_chunkinfo` layers an override
(`--chunkinfo` / the `FRAY_CHUNKINFO` env var) in front of the cached copy,
for working from an export you already have locally - note that path reads
the file directly, with no `["data"]` unwrapping, so it wants a *raw* export
rather than this module's own envelope.

**`cache/` is sorted by purpose, and `cache/maps/` holds maps and nothing else
holds maps.** That sentence is the layout's whole point: `list_maps` used to
glob `cache/*.json` and skip the names it *knew* were not maps, so every new
blob had to be remembered or it turned up in the picker as a map called
`wiki_rates` that failed the moment it was chosen. Two were missed exactly that
way. A directory cannot be forgotten::

    cache/maps/fetched/<id>.json      # from Firebase; only `fray fetch` writes one
    cache/maps/simulated/<batch>/     # rolled by `fray simulate`
    cache/maps/unlocked/<batch>/      # `fray unlock --cache-map`
    cache/reference/                  # chunkinfo, tasks_map, wiki_rates, tile_version
    cache/derived/                    # `pipeline.derive` results, content-keyed
    cache/assets/                     # section masks, skill icons
    cache/gui/                        # window.json, and the browser profile

A batch, whichever computed kind::

    <batch>/batch.json          # every run's seed and rolled chunks, plus `batch_id`
    <batch>/run-001/map.json    # envelope, carrying `kind`
    <batch>/run-001/rolls.json  # that run's UnlockRecord ledger
    <batch>/run-001/run.json    # this run's seed/rolls, for listing

`read_cache` resolves every kind, so no subcommand needs to know which it has: a
fetched map wins, then `<batch>/run-00N`, then a bare `<batch>`
with exactly one run (which is what makes `--cache-map X` followed by
`--map X` work). A bare batch name with several runs is an error naming them
rather than a guess. **A name is claimed across every kind**, so `--map foo`
never has to guess which directory meant it. Ids are validated before they
reach the filesystem, so a `--map ../../etc/passwd` cannot escape `cache/`.

`migrate_layout` moves a pre-split cache into this one on first touch, renaming
rather than re-fetching - the chunk export is a 10MB download and `assets/` is
fifteen hundred files pulled one at a time.

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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fray_claude.api import map_url

CACHE_DIR_NAME = "cache"
_ROOT_MARKER = "pyproject.toml"

#: The map id every command falls back to when none is named - upstream's
#: `?fray`, which is the whole reason this project exists. It lives here
#: rather than in `cli.py` because both apps need it: the CLI as an argparse
#: default, the GUI as what an empty "fetch a named map" box means.
DEFAULT_MAP_ID = "fray"

#: **`cache/maps/` holds maps and nothing else holds maps.** That sentence is
#: the whole point of the layout, and it replaced a denylist: `list_maps` used
#: to glob `cache/*.json` and skip the names it knew were not maps, so every
#: new blob had to be *remembered* or it turned up in the picker as a map
#: called `wiki_rates` that failed the moment it was chosen. Two of them were
#: missed exactly that way. A directory cannot be forgotten.
MAPS_DIR_NAME = "maps"

#: The three kinds, one directory each. `fetched` came from Firebase;
#: `simulated` was rolled by `fray simulate`; `unlocked` is what
#: `fray unlock --cache-map` writes - a map with one chunk added.
#:
#: **`unlocked` used to be filed under `simulated`**, and this file argued for
#: that: both mean "this project computed it, upstream never saw it", and a
#: third kind would have to be taught to every removal path to buy nothing.
#: What it buys is being able to *tell them apart*, which is what the picker
#: needed and what that argument did not weigh.
FETCHED = "fetched"
SIMULATED = "simulated"
UNLOCKED = "unlocked"

#: Everything this project computed, as opposed to fetched. The removal paths
#: take this rather than naming `SIMULATED`, so adding a fourth kind is one
#: line here instead of a hunt.
COMPUTED_KINDS = (SIMULATED, UNLOCKED)
MAP_KINDS = (FETCHED, *COMPUTED_KINDS)

#: Reference data that is fetched and is *not* a map: the chunk export, the
#: tasks map, the scraped wiki rates, the map-tile version. One directory
#: because they share a lifecycle - all refetchable, none precious, none
#: nameable by `--map`.
REFERENCE_DIR_NAME = "reference"

DERIVED_DIR_NAME = "derived"

#: The GUI's own state: remembered window geometry and the browser profile it
#: launches with. Neither is data about the game.
GUI_DIR_NAME = "gui"

CHUNKINFO_BLOB_NAME = "chunkinfo"
TASKS_MAP_BLOB_NAME = "tasks_map"
#: The scraped half of the estimator's numbers - see `heuristics.py` for why
#: the hand-edited half lives outside `cache/` instead.
WIKI_RATES_BLOB_NAME = "wiki_rates"
CHUNKINFO_ENV_VAR = "FRAY_CHUNKINFO"

#: Where hand-written corrections live: checked in, so they are diffable and
#: survive a re-scrape, which nothing under the gitignored `cache/` would.
HEURISTICS_DIR_NAME = "heuristics"
OVERRIDES_FILE_NAME = "overrides.json"

#: Binary assets the GUI needs, kept beside the JSON blobs. Every one of them
#: is fetched rather than committed, because all of it is somebody else's
#: artwork - see `api.SECTION_OVERLAY_URL`.
#:
#: **The world map is deliberately not among them.** It is the wiki's
#: cartography tiles now and the browser loads them straight from the wiki's
#: CDN, so nothing here ever holds one; a checkout that predates the change has
#: a stale `world_map.jpg` (or `.png`) in here, which nothing reads and which
#: is safe to delete. See `api.MAP_TILE_URL` for why that is a licence
#: decision rather than a saving.
ASSET_DIR_NAME = "assets"

#: The map-tile render the browser should ask for, remembered so a restart
#: does not re-scrape the wiki. An ordinary blob: `{"data": "2026-07-29_a",
#: "fetched_at": ..., "source": ...}`.
TILE_VERSION_BLOB_NAME = "tile_version"
TILE_VERSION_ENV_VAR = "FRAY_TILE_VERSION"

#: How long a remembered tile version is used before the wiki is asked again.
#: The wiki re-renders every few weeks, and a version that has moved costs a
#: blank map rather than a stale one - the old paths 404 - so this is short
#: enough to self-heal within a day and long enough that opening the GUI
#: repeatedly does not scrape a page each time.
TILE_VERSION_MAX_AGE_HOURS = 24.0

#: Subdirectories of `assets/` holding the many-small-files kinds: one
#: 192x192 mask per (chunk, section), and one icon per skill. Both are fetched
#: lazily, one file at a time, because a chunk has a handful of sections and
#: nobody opens all 1,534 masks.
SECTION_OVERLAY_DIR = "section_overlays"
SKILL_ICON_DIR = "skill_icons"

#: Where the GUI remembers how its window was left. Not a blob: it has no
#: upstream source, no `fetched_at`, and is rewritten many times a session.
GUI_WINDOW_FILE = "window.json"
GUI_PROFILE_DIR = "profile"

MAP_FILE_NAME = "map.json"
ROLLS_FILE_NAME = "rolls.json"
RUN_META_FILE_NAME = "run.json"
BATCH_META_FILE_NAME = "batch.json"
RUN_PREFIX = "run-"

#: A batch name: no separators, no `..`, nothing the shell or `Path` would
#: reinterpret. A map id is one of these, optionally followed by `/run-<n>`.
_NAME_RE = re.compile(r"[A-Za-z0-9_.-]+")
_RUN_RE = re.compile(rf"{RUN_PREFIX}\d+")
#: A derived-cache key: hex digest plus the suffix its codec claims.
_DERIVED_KEY_RE = re.compile(r"[0-9a-f]{16,64}\.[a-z0-9.]{1,12}")
#: A section overlay's identity: `<chunk>-<section>`, where a section is a
#: number or upstream's `W`-prefixed water variant (`12850-W1`). This is the
#: one asset name that comes from a URL, so it is matched whole - the digits
#: and the `W` are the entire alphabet, which leaves `.` and `/` nothing to
#: hide in.
_OVERLAY_RE = re.compile(r"\d+-W?\d+")
#: A skill's name, which indexes an icon. Letters only, so the same argument
#: applies.
_SKILL_RE = re.compile(r"[A-Za-z]+")


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


def cache_root(root: Path | None = None) -> Path:
    """`cache/` itself. Everything below is a subdirectory of exactly one kind."""
    return (root or project_root()) / CACHE_DIR_NAME


def maps_root(root: Path | None = None) -> Path:
    """`cache/maps/`, under which every map and no other thing lives."""
    migrate_layout(root)
    return cache_root(root) / MAPS_DIR_NAME


def kind_root(kind: str, root: Path | None = None) -> Path:
    """`cache/maps/<kind>/`. Raises rather than inventing a fourth kind."""
    if kind not in MAP_KINDS:
        raise ValueError(f"unknown map kind {kind!r} (expected one of {MAP_KINDS})")
    return maps_root(root) / kind


def cache_path(map_id: str, root: Path | None = None) -> Path:
    """Return the file a *fetched* map is stored in."""
    return kind_root(FETCHED, root) / f"{map_id}.json"


def batches_root(kind: str, root: Path | None = None) -> Path:
    """Where one computed kind's batches live."""
    return kind_root(kind, root)


def sims_root(root: Path | None = None) -> Path:
    """Where simulated batches live. The default home for a computed map."""
    return kind_root(SIMULATED, root)


def reference_path(name: str, root: Path | None = None) -> Path:
    """A reference blob: fetched, not a map, not nameable by `--map`."""
    migrate_layout(root)
    return cache_root(root) / REFERENCE_DIR_NAME / f"{name}.json"


def gui_root(root: Path | None = None) -> Path:
    """The GUI's own state - window geometry, browser profile."""
    migrate_layout(root)
    return cache_root(root) / GUI_DIR_NAME


#: Where each thing used to live, and where it lives now. Read top to bottom;
#: a directory move is attempted before the files inside it are considered.
_MOVES: tuple[tuple[str, str], ...] = (
    ("sims", f"{MAPS_DIR_NAME}/{SIMULATED}"),
    ("chunkinfo.json", f"{REFERENCE_DIR_NAME}/chunkinfo.json"),
    ("tasks_map.json", f"{REFERENCE_DIR_NAME}/tasks_map.json"),
    ("wiki_rates.json", f"{REFERENCE_DIR_NAME}/wiki_rates.json"),
    ("tile_version.json", f"{REFERENCE_DIR_NAME}/tile_version.json"),
    ("gui-window.json", f"{GUI_DIR_NAME}/{GUI_WINDOW_FILE}"),
    ("gui-profile", f"{GUI_DIR_NAME}/{GUI_PROFILE_DIR}"),
)

#: Roots already migrated in this process. Migration is idempotent and cheap
#: after the first call, but it is on the path of every cache read and a stat
#: per file per call is not free.
_migrated: set[Path] = set()


def migrate_layout(root: Path | None = None) -> list[str]:
    """Move a pre-`cache/maps/` cache into the current layout, once.

    **Renames rather than re-fetches**, because some of what is down there is
    expensive: the chunk export is a 10MB download, the wiki rates are ~18
    requests, and `assets/` is fifteen hundred files pulled one at a time. A
    fetched map is cheap to replace and a *simulated* one is not - its seed is
    in the batch summary being moved.

    Idempotent, and tolerant of losing a race: `Path.rename` on a directory is
    atomic within a filesystem, so a second process either finds the source
    gone or the destination present, and both mean the move already happened.
    Anything it cannot move is left exactly where it is rather than deleted.
    """
    base = cache_root(root)
    if base in _migrated:
        return []
    _migrated.add(base)
    if not base.is_dir():
        return []

    moved: list[str] = []
    for old_name, new_name in _MOVES:
        old, new = base / old_name, base / new_name
        if not old.exists() or new.exists():
            continue
        new.parent.mkdir(parents=True, exist_ok=True)
        try:
            old.rename(new)
        except OSError:
            continue
        moved.append(f"{old_name} -> {new_name}")

    # Loose `cache/*.json` that is not a known blob is a fetched map from the
    # old flat layout. It is identified by *elimination*, which is exactly the
    # reasoning the new layout exists to retire - so it happens once, here,
    # and never again on a read path.
    known = {new.rsplit("/", 1)[-1] for _, new in _MOVES}
    fetched = base / MAPS_DIR_NAME / FETCHED
    for path in sorted(base.glob("*.json")):
        if path.name in known:
            continue
        target = fetched / path.name
        if target.exists():
            continue
        fetched.mkdir(parents=True, exist_ok=True)
        try:
            path.rename(target)
        except OSError:
            continue
        moved.append(f"{path.name} -> {MAPS_DIR_NAME}/{FETCHED}/{path.name}")
    return moved


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
    """Write `data` in an envelope recording when and where it came from.

    `kind` is written here as well as by `write_sim_run`, so `_with_kind`'s
    fill-in is only ever reached by a cache written before the field existed.
    An envelope that has to be *inferred* to be understood is one nobody can
    read on its own, which is what `is_simulated` was.
    """
    envelope = {
        "map_id": map_id,
        "fetched_at": datetime.now(UTC).isoformat(),
        "source": map_url(map_id),
        "kind": FETCHED,
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
    """Return the envelope file `map_id` names, whichever kind it is.

    A fetched `maps/fetched/<id>.json` wins; then `<batch>/run-00N`; then a
    bare `<batch>` holding exactly one run. Several runs is an error rather
    than a guess, because picking one silently would make
    `fray tasks --map <batch>` report a different world each time a run was
    added.

    **The computed kinds are searched in turn, and a name belongs to at most
    one of them** - `claim_batch` refuses a name any other kind already owns,
    so `--map foo` never has to be told which directory was meant.
    """
    fetched = cache_path(map_id, root) if "/" not in map_id else None
    if fetched is not None and fetched.is_file():
        return fetched

    name, run = split_map_id(map_id)
    batch_dir = _find_batch(name, root)
    if run is not None:
        path = batch_dir / run / MAP_FILE_NAME if batch_dir else None
        if path is not None and path.is_file():
            return path
        raise CacheMissError(f"no run {map_id!r}; run: fray maps list")

    runs = _run_dirs(batch_dir) if batch_dir else []
    if len(runs) == 1:
        return runs[0] / MAP_FILE_NAME
    if runs:
        names = ", ".join(f"{name}/{d.name}" for d in runs)
        raise CacheMissError(f"map {name!r} holds {len(runs)} runs; name one of: {names}")
    if fetched is not None:
        raise CacheMissError(f"no cached data for map {map_id!r}; run: fray fetch --map {map_id}")
    raise CacheMissError(f"no cached data for map {map_id!r}; run: fray maps list")


def _find_batch(name: str, root: Path | None = None) -> Path | None:
    """The batch directory called `name`, in whichever kind owns it."""
    for kind in COMPUTED_KINDS:
        directory = kind_root(kind, root) / name
        if directory.is_dir():
            return directory
    return None


def batch_kind(name: str, root: Path | None = None) -> str | None:
    """Which computed kind owns the batch called `name`, if any."""
    for kind in COMPUTED_KINDS:
        if (kind_root(kind, root) / name).is_dir():
            return kind
    return None


def _with_kind(envelope: dict[str, Any], fallback: str) -> dict[str, Any]:
    """Guarantee a `kind`, filling it in for an envelope written before there
    was one. `is_simulated` was the only signal then, and it could not tell a
    rolled map from an unlocked one - so an old computed map reads as
    `simulated`, which is what it was called at the time."""
    if not isinstance(envelope.get("kind"), str):
        envelope["kind"] = SIMULATED if envelope.get("is_simulated") is True else fallback
    return envelope


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
    return _with_kind(envelope, FETCHED)


def blob_path(name: str, root: Path | None = None) -> Path:
    """Where a reference blob lives. Kept as the name every caller already
    uses; `reference_path` is the same thing said in the layout's vocabulary."""
    return reference_path(name, root)


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


def read_blob(name: str, root: Path | None = None, *, hint: str | None = None) -> dict[str, Any]:
    """Return the cached envelope for `name`.

    `hint` is the command that would produce it, named in the error. It has a
    default because two of the three blobs come from `fray chunkinfo`, and it
    is a parameter because the third does not - a missing wiki blob telling
    you to run `fray chunkinfo` sends you to the wrong command entirely.
    """
    path = blob_path(name, root)
    hint = hint or "run: fray chunkinfo"
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


def overrides_path(root: Path | None = None) -> Path:
    """The checked-in file holding hand-written heuristic corrections."""
    return (root or project_root()) / HEURISTICS_DIR_NAME / OVERRIDES_FILE_NAME


def read_overrides(root: Path | None = None) -> dict[str, Any]:
    """Hand-written corrections, or `{}` if there are none.

    Absent is normal and not an error: a fresh clone has no corrections yet,
    and the estimator's job is to work from the scrape until someone disagrees
    with it. A *malformed* file does raise - it was written deliberately, so
    silently ignoring it would drop corrections without saying so.
    """
    path = overrides_path(root)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CacheMissError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise CacheMissError(f"{path} should hold an object, got {type(parsed).__name__}")
    return parsed


def claim_batch(name: str, root: Path | None = None, *, kind: str = SIMULATED) -> Path:
    """Create and return a fresh batch directory for `name`, of `kind`.

    `mkdir(exist_ok=False)` *is* the claim: it either creates the directory or
    raises, so two processes racing on the same name cannot both believe they
    won it. On a clash the name gains `-2`, `-3`, ... - including a clash with
    a *fetched* `cache/<name>.json`, so a simulated batch can never shadow a
    fetched map or make `--map <name>` ambiguous.
    """
    split_map_id(name)
    base = kind_root(kind, root)
    base.mkdir(parents=True, exist_ok=True)
    suffix = 1
    while True:
        candidate = name if suffix == 1 else f"{name}-{suffix}"
        directory = base / candidate
        # A name is claimed across *every* kind, not just this one: `--map`
        # takes a bare name and must not have to guess which directory meant it.
        if not _name_taken(candidate, root, skip=kind):
            try:
                directory.mkdir(exist_ok=False)
            except FileExistsError:
                pass
            else:
                return directory
        suffix += 1


def claim_sim_batch(name: str, root: Path | None = None) -> Path:
    """`claim_batch` for the simulated kind."""
    return claim_batch(name, root, kind=SIMULATED)


def _name_taken(name: str, root: Path | None, *, skip: str) -> bool:
    """Whether any kind already owns `name`. See `claim_batch`."""
    if cache_path(name, root).exists():
        return True
    return any(
        (kind_root(kind, root) / name).exists()
        for kind in COMPUTED_KINDS
        if kind != skip
    )


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
    kind: str = SIMULATED,
) -> Path:
    """Write one synthetic run: its envelope, its ledger, and its metadata.

    `map.json` is what `read_cache` reads; `rolls.json` is the full per-roll
    ledger; `run.json` is the small summary `list_maps` reads, so listing a
    100-run batch never opens a payload. The envelope mirrors `write_cache`'s,
    with `is_simulated` true and a `simulation` block for provenance.

    `kind` says which of the computed kinds this is, and it is written into
    the envelope rather than inferred from where the file sits. This file used
    to argue that `unlocked` need not be its own kind - both mean "this
    project computed it" - and the thing that argument left out is that the
    picker has to *say* which, and "simulated" is a lie about a map made by
    adding one chunk by hand.

    `is_simulated` is still written beside `kind`, for one reason only: a
    cache predating the split has it and nothing else, so `read_cache` fills
    `kind` in from it. New readers use `kind`.
    """
    directory.mkdir(parents=True, exist_ok=True)
    envelope = {
        "map_id": map_id,
        "fetched_at": datetime.now(UTC).isoformat(),
        "source": source or f"simulated from {simulation.get('base_map')!r}",
        "kind": kind,
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


def read_batch(name: str, root: Path | None = None, *, kind: str = SIMULATED) -> dict[str, Any]:
    """Return a batch's summary, rebuilt from its runs if `batch.json` is absent.

    An interrupted batch has run directories but no summary, and those runs are
    still perfectly good maps - so this falls back to reading each `run.json`
    rather than pretending the batch isn't there. A rebuilt summary carries
    `batch_id` from the first run that has one, which is what keeps the runs
    of an interrupted batch recognisable as one job.
    """
    split_map_id(name)
    directory = kind_root(kind, root) / name
    if not directory.is_dir():
        raise CacheMissError(f"no {kind} map {name!r}; run: fray maps list")

    runs = [_read_run_meta(path) for path in _run_dirs(directory)]
    summary: dict[str, Any] = {"name": name, "kind": kind, "runs": runs, "complete": False}
    inferred = next((r.get("batch_id") for r in runs if r.get("batch_id")), None)
    if inferred:
        summary["batch_id"] = inferred
    try:
        stored = _read_json_object(directory / BATCH_META_FILE_NAME)
    except CacheMissError:
        return summary
    summary.update(stored)
    summary["runs"] = runs or stored.get("runs", [])
    summary["complete"] = True
    return summary


def read_sim_batch(name: str, root: Path | None = None) -> dict[str, Any]:
    """`read_batch` for the simulated kind, which is what every caller wants."""
    return read_batch(name, root, kind=SIMULATED)


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
    #: **What makes several runs one job.** Minted once per batch and written
    #: into every run, so a run answers "which batch was I part of" on its own
    #: - the directory name cannot, because a name clash renames the batch and
    #: a rename loses the link entirely. Runs of one batch share it; two
    #: batches from the same base map do not.
    batch_id: str | None = None
    #: The batch a run belongs to, for a row that is a run rather than a batch.
    batch: str | None = None

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
            "batch_id": self.batch_id,
            "batch": self.batch,
        }


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _fetched_entries(root: Path | None) -> list[MapEntry]:
    """Every fetched map, which is every file in `cache/maps/fetched/`.

    **No denylist.** This used to glob `cache/*.json` and skip the names it
    knew were not maps, which meant a new blob had to be *remembered* or it
    turned up as a map that failed the moment it was chosen; two were missed
    exactly that way. Reading a directory that holds one kind of thing cannot
    go wrong in that direction.
    """
    directory = kind_root(FETCHED, root)
    if not directory.is_dir():
        return []
    entries: list[MapEntry] = []
    for path in sorted(directory.glob("*.json")):
        try:
            envelope = _read_json_object(path)
        except CacheMissError:
            continue
        data = envelope.get("data")
        chunks = data.get("chunks") if isinstance(data, dict) else None
        held = chunks.get("unlocked") if isinstance(chunks, dict) else None
        entries.append(
            MapEntry(
                map_id=path.stem,
                kind=FETCHED,
                created_at=_str_or_none(envelope.get("fetched_at")),
                unlocked_chunks=len(held) if isinstance(held, dict) else None,
            )
        )
    return entries


def _batch_entries(kind: str, root: Path | None, *, expand_runs: bool) -> list[MapEntry]:
    """Every batch of one computed kind, and optionally its runs."""
    base = kind_root(kind, root)
    if not base.is_dir():
        return []

    entries: list[MapEntry] = []
    for directory in sorted(base.iterdir()):
        if not directory.is_dir():
            continue
        try:
            summary = read_batch(directory.name, root, kind=kind)
        except CacheMissError:  # pragma: no cover - iterdir just listed it
            continue
        runs = summary.get("runs") or []
        entries.append(
            MapEntry(
                map_id=directory.name,
                kind=kind,
                created_at=_str_or_none(summary.get("created_at")),
                rolls=_int_or_none(summary.get("rolls_requested")),
                runs=len(runs),
                seed=_int_or_none(summary.get("seed")),
                base_map=_str_or_none(summary.get("base_map")),
                batch_id=_str_or_none(summary.get("batch_id")),
            )
        )
        if not expand_runs:
            continue
        for run in runs:
            rolled = run.get("rolls")
            entries.append(
                MapEntry(
                    map_id=f"{directory.name}/{run.get('run')}",
                    kind=kind,
                    created_at=_str_or_none(run.get("created_at")),
                    unlocked_chunks=_int_or_none(run.get("unlocked_chunks")),
                    rolls=len(rolled) if isinstance(rolled, list) else None,
                    seed=_int_or_none(run.get("seed")),
                    base_map=_str_or_none(run.get("base_map")),
                    batch_id=_str_or_none(run.get("batch_id")),
                    batch=_str_or_none(run.get("batch")) or directory.name,
                )
            )
    return entries


def list_maps(root: Path | None = None, *, expand_runs: bool = False) -> list[MapEntry]:
    """Every cached map, and **only** maps: fetched, then simulated, then
    unlocked.

    `expand_runs` adds a row per run underneath its batch - useful for a
    handful of runs, noise for a hundred, which is why it isn't the default.
    """
    entries = _fetched_entries(root)
    for kind in COMPUTED_KINDS:
        entries.extend(_batch_entries(kind, root, expand_runs=expand_runs))
    return entries


def remove_map(map_id: str, root: Path | None = None, *, include_fetched: bool = False) -> Path:
    """Delete a computed batch, a single run of one, or a fetched map.

    A fetched map is upstream state that only `fray fetch` can replace, so
    removing one takes an explicit `include_fetched` - a computed map is
    reproducible from what is recorded beside it, and is what routine cleanup
    is for.
    """
    name, run = split_map_id(map_id)
    fetched = cache_path(name, root)
    if run is None and fetched.is_file():
        if not include_fetched:
            raise CacheMissError(
                f"{map_id!r} is a fetched map, not a computed one; "
                "pass --include-fetched to remove it"
            )
        fetched.unlink()
        return fetched

    directory = _find_batch(name, root)
    if directory is not None and run is not None:
        directory = directory / run
    if directory is None or not directory.is_dir():
        raise CacheMissError(f"no cached map {map_id!r}; run: fray maps list")
    shutil.rmtree(directory)
    return directory


def remove_computed(root: Path | None = None, *, kinds: Sequence[str] = COMPUTED_KINDS) -> list[str]:
    """Delete every batch this project computed, leaving fetched maps alone.

    Takes the kinds rather than naming one, so a fourth is a line in
    `COMPUTED_KINDS` and not a second function nobody remembers to call.
    """
    removed: list[str] = []
    for kind in kinds:
        base = kind_root(kind, root)
        if not base.is_dir():
            continue
        for directory in sorted(base.iterdir()):
            if directory.is_dir():
                shutil.rmtree(directory)
                removed.append(directory.name)
    return removed


def derived_root(root: Path | None = None) -> Path:
    """The directory cached derivations live in."""
    return cache_root(root) / DERIVED_DIR_NAME


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


def gui_profile_dir(root: Path | None = None) -> Path:
    """The browser profile `fray-gui`'s app window runs in.

    Its own, and not the user's, for a reason that is mechanical rather than
    tidy: Chrome hands a URL to an already-running instance unless pointed at a
    separate profile, and the launched process then exits immediately - taking
    the server with it. See `gui/browser.py`.
    """
    return gui_root(root) / GUI_PROFILE_DIR


def asset_path(name: str, root: Path | None = None) -> Path:
    """Where a binary asset lives. `name` is a fixed constant, never user input."""
    return cache_root(root) / ASSET_DIR_NAME / name


def map_size(map_id: str, root: Path | None = None) -> int:
    """Bytes one cached map occupies, counting a run's whole directory.

    A simulated run is a `map.json` plus its ledger and metadata, and the
    ledger is usually the larger of the three - so reporting only the payload
    would understate what `fray maps rm` reclaims. Missing means `0`: this
    answers a tooltip, and a map that vanished between listing and stat is not
    worth an exception.
    """
    try:
        path = resolve_map_path(map_id, root)
    except CacheMissError:
        return 0
    try:
        if path.name == MAP_FILE_NAME:
            return sum(f.stat().st_size for f in path.parent.iterdir() if f.is_file())
        return path.stat().st_size
    except OSError:
        return 0


def section_overlay_path(name: str, root: Path | None = None) -> Path:
    """Where one section mask is cached. `name` is `<chunk>-<section>`.

    **This is the only asset name that reaches here from a URL**, so it is
    validated against `_OVERLAY_RE` in full rather than sanitised. `fullmatch`
    on an alphabet of digits and one `W` is not a filter that something can be
    smuggled through - there is no `.`, no `/` and no `%` in the language at
    all - which is the same argument the GUI's static allowlist makes and the
    reason neither needs a second check downstream.
    """
    if not _OVERLAY_RE.fullmatch(name):
        raise ValueError(f"not a section overlay name: {name!r}")
    return asset_path(f"{SECTION_OVERLAY_DIR}/{name}.png", root)


def skill_icon_path(skill: str, root: Path | None = None) -> Path:
    """Where one skill's icon is cached. Validated like `section_overlay_path`."""
    if not _SKILL_RE.fullmatch(skill):
        raise ValueError(f"not a skill name: {skill!r}")
    return asset_path(f"{SKILL_ICON_DIR}/{skill}.png", root)


def write_asset_at(path: Path, blob: bytes) -> Path:
    """Store a binary asset, atomically, at a path the caller already decided.

    The path comes in rather than a name because every asset left here is a
    *nested* one - a section mask, a skill icon - whose name has to be
    validated by `section_overlay_path` or `skill_icon_path` before anything
    joins it onto a directory.

    Same temp-file-plus-`os.replace` as `write_derived`, for the same reason:
    a reader never sees a partial file, so a mask being refetched under a
    request serves one version or the other rather than a truncated PNG.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_bytes(blob)
    os.replace(temp, path)
    return path


def gui_window_path(root: Path | None = None) -> Path:
    """Where the GUI's remembered window geometry lives."""
    return gui_root(root) / GUI_WINDOW_FILE


def read_gui_window(root: Path | None = None) -> dict[str, Any]:
    """How the window was last left, or `{}` if it never has been.

    Empty rather than an error because the caller's response to "no saved
    geometry" is to pick a default, and a first run is not a fault.
    """
    try:
        return _read_json_object(gui_window_path(root))
    except (CacheMissError, OSError):
        return {}


def write_gui_window(geometry: dict[str, Any], root: Path | None = None) -> Path:
    """Remember how the window was left. Atomic, like everything else here."""
    path = gui_window_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    return _atomic_write_json(path, geometry)


def tile_version_override() -> str | None:
    """`FRAY_TILE_VERSION`, for pinning a render the wiki no longer advertises.

    The escape hatch for the one fragile thing about the tile source: the
    version is scraped out of a page, and a page can change shape. Set this and
    nothing is scraped at all.
    """
    value = (os.environ.get(TILE_VERSION_ENV_VAR) or "").strip()
    return value or None


def read_tile_version(root: Path | None = None) -> tuple[str, float]:
    """The remembered tile version and its age in hours.

    The age is returned rather than judged here, because `cache.py` decides
    nothing about the network: whether an old version is worth re-scraping is
    the caller's call, and the caller is also the one that can fall back to
    this value when the scrape fails.
    """
    envelope = read_blob(TILE_VERSION_BLOB_NAME, root, hint="the GUI fetches this itself")
    data = envelope.get("data")
    version = data.get("version") if isinstance(data, dict) else None
    if not isinstance(version, str) or not version:
        raise CacheMissError(f"no tile version in {blob_path(TILE_VERSION_BLOB_NAME, root)}")
    try:
        fetched = datetime.fromisoformat(str(envelope.get("fetched_at")))
    except ValueError:
        # An unreadable timestamp means "as old as it gets", which sends the
        # caller to the network - the safe direction, since the cost is one
        # request and the alternative is trusting a version forever.
        return version, float("inf")
    return version, (datetime.now(UTC) - fetched).total_seconds() / 3600


def write_tile_version(version: str, source: str, root: Path | None = None) -> Path:
    """Remember `version`, so a restart does not scrape the wiki again."""
    return write_blob(TILE_VERSION_BLOB_NAME, {"version": version}, source, root)


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
