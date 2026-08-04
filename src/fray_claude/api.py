"""HTTP access to the chunk-picker Firebase Realtime Database.

The web app reaches this database through the Firebase JS SDK, but the REST API
exposes the same data and the database is world-readable, so a plain GET is
enough. No credentials are involved, and no custom `User-Agent` is set -
there is nothing to disguise.

The only module that touches the network; raises `FetchError`. Note that an
unknown map comes back as HTTP 200 with a bare `null` rather than a 404, so
that is the *only* "no such map" signal available.

`urllib` is imported inside the two functions that fetch, not at module scope.
`cache.py` imports this module for `map_url` alone, so every command paid
`urllib.request`'s ~11ms import (it drags in `logging` and `traceback`) to reach
one `str.format` - and only `fetch`/`chunkinfo` ever open a socket. Patching
`urllib.request.urlopen` still works: the name is resolved on the module object
at call time, which is what `tests/test_api.py` does.
"""

from __future__ import annotations

import json
from typing import Any

MAP_URL = "https://chunkpicker.firebaseio.com/maps/{map_id}.json"

# gh-pages is upstream's default branch and where the live site is served
# from; `main` 404s.
_UPSTREAM_RAW = "https://raw.githubusercontent.com/source-chunk/chunk-picker-v2/gh-pages/{path}"
CHUNKINFO_URL = _UPSTREAM_RAW.format(path="chunkpicker-chunkinfo-export.json")
TASKS_MAP_URL = _UPSTREAM_RAW.format(path="tasksMap.json")

DEFAULT_TIMEOUT = 30.0


class FetchError(Exception):
    """A map could not be retrieved, or was not in the expected shape."""


def map_url(map_id: str) -> str:
    """Return the REST endpoint holding `map_id`'s state."""
    return MAP_URL.format(map_id=map_id)


def fetch_map(map_id: str, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Return the live state for `map_id`.

    No custom headers are sent: urllib's default User-Agent identifies neither
    the user nor this project, so setting one would only add information.
    """
    import urllib.error
    import urllib.request

    url = map_url(map_id)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload: Any = json.load(response)
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} fetching map {map_id!r}") from exc
    except TimeoutError as exc:
        raise FetchError(f"timed out after {timeout:g}s fetching map {map_id!r}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"network error fetching map {map_id!r}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise FetchError(f"malformed JSON for map {map_id!r}: {exc}") from exc

    # An unknown path yields HTTP 200 with a bare `null` rather than a 404, so
    # this is the only signal that the map does not exist.
    if payload is None:
        raise FetchError(f"no such map: {map_id!r}")
    if not isinstance(payload, dict):
        raise FetchError(
            f"expected an object for map {map_id!r}, got {type(payload).__name__}"
        )
    return payload


def fetch_chunkinfo(timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Return upstream's chunk/section/challenge reference data (~7MB, static)."""
    return _fetch_json_object(CHUNKINFO_URL, timeout, what="chunkinfo export")


def fetch_tasks_map(timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Return upstream's task-name <-> `t_N` id interning table."""
    return _fetch_json_object(TASKS_MAP_URL, timeout, what="tasks map")


def _fetch_json_object(url: str, timeout: float, *, what: str) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload: Any = json.load(response)
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} fetching {what}") from exc
    except TimeoutError as exc:
        raise FetchError(f"timed out after {timeout:g}s fetching {what}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"network error fetching {what}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise FetchError(f"malformed JSON for {what}: {exc}") from exc

    if not isinstance(payload, dict):
        raise FetchError(f"expected an object for {what}, got {type(payload).__name__}")
    return payload
