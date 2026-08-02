"""On-disk cache of fetched map state, kept in the project's `cache/` directory."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fray_claude.api import map_url

CACHE_DIR_NAME = "cache"
_ROOT_MARKER = "pyproject.toml"


class CacheMissError(Exception):
    """No usable cached copy exists for the requested map."""


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


def write_cache(map_id: str, data: dict[str, Any], root: Path | None = None) -> Path:
    """Write `data` in an envelope recording when and where it came from."""
    path = cache_path(map_id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "map_id": map_id,
        "fetched_at": datetime.now(UTC).isoformat(),
        "source": map_url(map_id),
        "data": data,
    }
    path.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
    return path


def read_cache(map_id: str, root: Path | None = None) -> dict[str, Any]:
    """Return the cached envelope for `map_id`.

    The payload itself is under the `data` key; the rest is provenance.
    """
    path = cache_path(map_id, root)
    hint = f"run: fray fetch --map {map_id}"
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CacheMissError(f"no cached data for map {map_id!r}; {hint}") from exc

    try:
        envelope: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CacheMissError(f"cache for map {map_id!r} is not valid JSON; {hint}") from exc

    if not isinstance(envelope, dict) or not isinstance(envelope.get("data"), dict):
        raise CacheMissError(f"cache for map {map_id!r} is malformed; {hint}")
    return envelope
