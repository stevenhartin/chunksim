"""HTTP access to the chunk-picker Firebase Realtime Database.

The web app reaches this database through the Firebase JS SDK, but the REST API
exposes the same data and the database is world-readable, so a plain GET is
enough. No credentials are involved.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

MAP_URL = "https://chunkpicker.firebaseio.com/maps/{map_id}.json"

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
