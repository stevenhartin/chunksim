"""Bytes that are not derived from any map.

The page itself (`_static`, against a four-entry allowlist matched by equality,
so nothing a caller sends is ever joined onto a path), the reference blobs'
freshness (`_reference_state`, a `stat` and the envelope's first few hundred
bytes - the page asks this on boot, so it must not read the 10MB export to find
out whether the export exists), the map-tile *template*, and the lazy proxy for
upstream's section masks and skill icons.

**The tiles are a URL, never bytes.** `/api/tiles` hands out a template and the
browser fetches from the wiki directly: the cartography is CC BY-NC-SA 3.0
against this project's MIT, so caching it under `cache/` or re-serving it off
loopback would make this a redistributor of NonCommercial artwork, where
linking makes it a page with a picture on it. A test asserts no tile route
exists, so a later "let's cache these" cannot pass review by looking like a
speed-up.

The masks and icons *are* proxied, one file at a time on the request that first
draws them, because a chunk has a handful of sections and nobody opens all
1,534.
"""

from __future__ import annotations

from typing import Any
from collections.abc import Callable
from chunksim.remote.api import DEFAULT_TIMEOUT
from chunksim.remote.api import FetchError
from http import HTTPStatus
from chunksim.remote.api import MAP_TILE_ATTRIBUTION
from chunksim.remote.api import MAP_TILE_MAP_ID
from chunksim.remote.api import MAP_TILE_URL
from chunksim.remote.api import MAP_TILE_VERSION_URL
from pathlib import Path
from chunksim.store import cache
from chunksim.remote.api import fetch_map_tile_version
from chunksim.gui.http import Context
from chunksim.gui.http import Response
from chunksim.gui.http import _STATIC
from chunksim.gui.http import _error


#: The reference blobs the page cares whether it has, and what to call them.
#: `tile_version` is deliberately absent: it is refetched on its own whenever
#: the wiki moves a render, and nobody would press a button for it.
#: `(blob, label, what to POST to /api/refresh)`. The page is told the third
#: rather than deriving it, so "which action refreshes this" is answered in
#: one place instead of in a lookup table on each side.
_REFERENCE_BLOBS = (
    (cache.CHUNKINFO_BLOB_NAME, "Chunk data", "chunkinfo"),
    (cache.WIKI_RATES_BLOB_NAME, "Wiki rates", "heuristics"),
    # **Absent, this floors a whole skill and says nothing.** Every one of
    # Construction's 227 rated methods comes from a `{{Recipe}}` row, so a
    # cache without this blob prices the skill at the 1,000/hr default -
    # 13,034h against 191h - with `(none found)` as its method. Every other
    # skill degrades partially; this one degrades completely, which is exactly
    # the shape that reads as a modelling gap rather than as missing data.
    (cache.RECIPES_BLOB_NAME, "Wiki recipes", "recipes"),
)


def _reference_state(ctx: Context) -> list[dict[str, Any]]:
    """What reference data is on disk and when it was fetched.

    **Cheap on purpose** - a `stat` and the envelope's own header, not the
    payload - because the page asks on boot to decide whether anything is
    missing. Reading the 10MB chunk export to find out whether it exists
    would be a poor way to answer the question.
    """
    out: list[dict[str, Any]] = []
    for name, label, refresh in _REFERENCE_BLOBS:
        path = cache.blob_path(name, ctx.root)
        fetched_at = None
        if path.is_file():
            try:
                # The envelope's `fetched_at` sits in the first few hundred
                # bytes; `read_blob` would pull the whole export in.
                head = path.read_text(encoding="utf-8", errors="replace")[:400]
                marker = '"fetched_at": "'
                if marker in head:
                    fetched_at = head.split(marker, 1)[1].split('"', 1)[0]
            except OSError:  # pragma: no cover - a file we just stat'd
                fetched_at = None
        out.append(
            {
                "name": name,
                "label": label,
                "refresh": refresh,
                "cached": path.is_file(),
                "fetched_at": fetched_at,
                "size": path.stat().st_size if path.is_file() else 0,
            }
        )
    return out


def _static(path: str, ctx: Context) -> Response | None:
    entry = _STATIC.get(path)
    if entry is None:
        return None
    name, content_type = entry
    try:
        body = (ctx.resources / name).read_bytes()
    except FileNotFoundError:
        # A packaging fault, not a user one: the wheel shipped without its
        # resources. Says so, rather than 404ing like a bad URL.
        return _error(f"missing packaged resource {name!r}", HTTPStatus.INTERNAL_SERVER_ERROR)
    return Response(
        status=HTTPStatus.OK,
        content_type=content_type,
        body=body,
        # These change with the install, and the install is the only thing
        # that changes them, so revalidating every time costs nothing.
        headers={"Cache-Control": "no-cache"},
    )


def _tile_source(ctx: Context) -> dict[str, Any]:
    """Where the browser should get its map tiles.

    **This hands out a URL template; it never fetches a tile.** The tiles are
    CC BY-NC-SA 3.0 and this project is MIT, so caching them under `cache/` or
    serving them off loopback would make it a redistributor of NonCommercial
    artwork. Pointing the page at the wiki's own CDN makes it a page with a
    picture on it. That also means the `User-Agent` those tiles need is the
    browser's, which browsers always send - the 403 an anonymous script gets is
    not a problem anybody here has to solve.

    Only the *version* has to be resolved, and it is the fragile part: the wiki
    publishes no index, so it is scraped out of the map page's fallback image
    (`wiki.map_tile_version`). Three layers, in order:

    - `CHUNKSIM_TILE_VERSION`, which skips the network entirely;
    - a cached answer younger than `TILE_VERSION_MAX_AGE_HOURS`;
    - the wiki, written back to the cache.

    **A failed scrape falls back to the cached version rather than to
    nothing.** A stale version still draws a map; the render it names stays on
    the CDN. `error` is reported either way so the page can say the map may be
    out of date instead of quietly showing one.
    """
    source: dict[str, Any] = {
        "template": MAP_TILE_URL,
        "map_id": MAP_TILE_MAP_ID,
        "attribution": MAP_TILE_ATTRIBUTION,
        "attribution_url": MAP_TILE_VERSION_URL,
        "version": "",
        "error": None,
    }

    pinned = cache.tile_version_override()
    if pinned:
        return {**source, "version": pinned, "pinned": True}

    if ctx.tile_version[0]:
        return {**source, "version": ctx.tile_version[0]}

    cached, age = "", float("inf")
    try:
        cached, age = cache.read_tile_version(ctx.root)
    except cache.CacheMissError:
        pass
    if cached and age < cache.TILE_VERSION_MAX_AGE_HOURS:
        ctx.tile_version[0] = cached
        return {**source, "version": cached}

    try:
        version = fetch_map_tile_version(DEFAULT_TIMEOUT)
    except FetchError as exc:
        if cached:
            ctx.tile_version[0] = cached
            return {**source, "version": cached, "error": f"{exc} (using the last known version)"}
        return {**source, "error": str(exc)}

    cache.write_tile_version(version, MAP_TILE_VERSION_URL, ctx.root)
    ctx.tile_version[0] = version
    return {**source, "version": version}


def _cached_upstream_asset(
    path: Path, fetch: Callable[[], bytes], *, what: str
) -> Response:
    """Serve a small upstream image, fetching it once if this machine lacks it.

    **A lazy proxy rather than a download step**, because the two collections
    behind it are 1,534 section masks and 24 skill icons and nobody looks at
    all of either. A chunk's masks arrive when you first shade that chunk, and
    stay; the second visit is a disk read.

    This is the GUI reaching the network, which `api.py` otherwise owns alone -
    so it does not: the fetch is an `api` function passed in, and the bytes go
    to disk through `cache.py`. The only thing decided here is *when*.

    A miss is a 404 rather than an error. Upstream has a mask for every
    section it drew and nothing promises one exists for a section it did not,
    so "there is no mask" is an ordinary answer the caller draws nothing for.
    """
    try:
        blob: bytes | None = path.read_bytes()
    except FileNotFoundError:
        blob = None
    if blob is None:
        try:
            blob = fetch()
        except FetchError as exc:
            return _error(f"could not fetch {what}: {exc}", HTTPStatus.NOT_FOUND)
        cache.write_asset_at(path, blob)
    return Response(
        status=HTTPStatus.OK,
        content_type="image/png",
        body=blob,
        # Upstream regenerates these only when it redraws the world, and the
        # URL carries the identity, so this is genuinely immutable.
        headers={"Cache-Control": "max-age=31536000, immutable"},
    )
