"""Tests for `gui/routes_reference.py`: tiles, blob freshness, the build stamp and proxied assets.

`handle_request` is pure - strings in, a `Response` out - so every test
here exercises the real routing without binding a socket.
"""

from __future__ import annotations

import json
import re
from http import HTTPStatus
from pathlib import Path
from typing import Any

import pytest

from chunksim.store import cache
from chunksim.remote.api import FetchError
from chunksim.gui.server import Context, Response, handle_request


LUMBRIDGE = "12850"

NORTH = "12851"  # one region north of Lumbridge


def _write_map(root: Path, map_id: str, unlocked: list[str]) -> None:
    """A cached map holding `unlocked`.

    The values are the id strings again, not `True` - that is what the real
    payload holds, and a test that wrote `True` would let a truthiness bug
    through.
    """
    cache.write_cache(
        map_id,
        {"chunks": {"unlocked": {chunk: chunk for chunk in unlocked}}},
        root=root,
    )

@pytest.fixture
def ctx(tmp_path: Path) -> Context:
    _write_map(tmp_path, "fray", [LUMBRIDGE])
    return Context(root=tmp_path)


def _get(path: str, ctx: Context, **query: str) -> Response:
    return handle_request("GET", path, {k: [v] for k, v in query.items()}, ctx)


def _body(response: Response) -> Any:
    return json.loads(response.body.decode("utf-8"))


def test_the_tile_source_is_a_template_and_never_a_tile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**`/api/tiles` hands out a URL. It must never hand out a picture.**

    The tiles are CC BY-NC-SA 3.0 and this project is GPL-3.0, so caching them
    under `cache/` or re-serving them off loopback would make it a
    redistributor of NonCommercial artwork - pointing the browser at the
    wiki's own CDN makes it a page with a picture on it. That distinction is
    the whole reason this route exists, so it is asserted rather than trusted
    to a comment.
    """
    monkeypatch.delenv("CHUNKSIM_TILE_VERSION", raising=False)
    cache.write_tile_version("2026-07-29_a", "https://example.invalid", root=tmp_path)

    payload = _body(_get("/api/tiles", Context(root=tmp_path)))

    assert payload["version"] == "2026-07-29_a"
    assert payload["map_id"] == -1  # Full Map, not the surface. See MAP_TILE_MAP_ID.
    assert payload["template"].startswith("https://maps.runescape.wiki/")
    assert "{version}" in payload["template"] and "{z}" in payload["template"]
    assert payload["attribution"]
    assert payload["error"] is None
    # Nothing image-shaped was written anywhere under the cache root.
    assert not list((tmp_path / "cache").rglob("*.png"))
    assert not list((tmp_path / "cache").rglob("*.jpg"))


def test_a_pinned_tile_version_skips_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`CHUNKSIM_TILE_VERSION` is the escape hatch for a scrape that has broken.

    The version comes out of a rendered page, and a page can change shape;
    pinning is what turns that from "the map is gone" into "the map is a bit
    old". It must not touch the wiki at all, which is what the exploding
    fetcher pins.
    """
    monkeypatch.setenv("CHUNKSIM_TILE_VERSION", "2020-01-01_z")
    monkeypatch.setattr(
        "chunksim.gui.routes_reference.fetch_map_tile_version",
        lambda *a, **k: pytest.fail("a pinned version still scraped the wiki"),
    )

    payload = _body(_get("/api/tiles", Context(root=tmp_path)))

    assert payload["version"] == "2020-01-01_z"
    assert payload["pinned"] is True


def test_a_failed_scrape_falls_back_to_the_last_known_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale version still draws a map; no version draws nothing.

    The render it names stays on the CDN, so the worst case of using an old
    one is a world a few weeks out of date - strictly better than a blank
    canvas. The error rides along so the page can say so.
    """
    monkeypatch.delenv("CHUNKSIM_TILE_VERSION", raising=False)
    cache.write_tile_version("2026-07-29_a", "https://example.invalid", root=tmp_path)
    # Age it past the refresh window so the scrape is attempted.
    blob = cache.blob_path(cache.TILE_VERSION_BLOB_NAME, tmp_path)
    stale = json.loads(blob.read_text())
    stale["fetched_at"] = "2020-01-01T00:00:00+00:00"
    blob.write_text(json.dumps(stale))

    def explode(*args: Any, **kwargs: Any) -> str:
        raise FetchError("the wiki is down")

    monkeypatch.setattr("chunksim.gui.routes_reference.fetch_map_tile_version", explode)

    payload = _body(_get("/api/tiles", Context(root=tmp_path)))

    assert payload["version"] == "2026-07-29_a"
    assert "the wiki is down" in payload["error"]


def test_no_version_anywhere_is_reported_rather_than_guessed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A version is never constructed from today's date.

    The suffix is a letter that increments within a day, so a guess is wrong
    more often than not and a wrong one 404s into a blank map with nothing
    saying why.
    """
    monkeypatch.delenv("CHUNKSIM_TILE_VERSION", raising=False)

    def explode(*args: Any, **kwargs: Any) -> str:
        raise FetchError("the wiki is down")

    monkeypatch.setattr("chunksim.gui.routes_reference.fetch_map_tile_version", explode)

    payload = _body(_get("/api/tiles", Context(root=tmp_path)))

    assert payload["version"] == ""
    assert "the wiki is down" in payload["error"]


def test_the_build_route_says_which_install_is_answering(ctx: Context) -> None:
    """The same question `fray`'s first line answers, asked of the server."""
    payload = _body(_get("/api/build", ctx))

    assert set(payload) == {"version", "installed_at", "kind", "path"}
    assert payload["kind"] in ("wheel", "editable", "source")


def test_a_section_mask_is_fetched_once_and_then_read_from_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of the proxy: 1,534 masks, and you look at a handful."""
    calls: list[str] = []

    def fake(name: str, timeout: float = 0.0) -> bytes:
        calls.append(name)
        return b"\x89PNG-mask"

    monkeypatch.setattr("chunksim.gui.server.fetch_section_overlay", fake)
    ctx = Context(root=tmp_path)

    first = _get("/assets/section/12850-1.png", ctx)
    second = _get("/assets/section/12850-1.png", ctx)

    assert first.status == HTTPStatus.OK
    assert first.content_type == "image/png"
    assert second.body == first.body == b"\x89PNG-mask"
    assert calls == ["12850-1"], "the second request went back to the network"


def test_a_missing_mask_is_a_404_rather_than_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Upstream drew masks for the sections it drew; absence is an answer."""

    def fake(name: str, timeout: float = 0.0) -> bytes:
        raise FetchError("HTTP 404")

    monkeypatch.setattr("chunksim.gui.server.fetch_section_overlay", fake)

    response = _get("/assets/section/12850-9.png", Context(root=tmp_path))

    assert response.status == HTTPStatus.NOT_FOUND


def test_reference_state_is_cheap_and_says_what_is_missing(tmp_path: Path) -> None:
    """**The page asks this on boot**, so it must not read the 10MB export to
    find out whether the export exists. A `stat` and the envelope's first few
    hundred bytes answer it."""
    ctx = Context(root=tmp_path)
    cache.write_blob(cache.CHUNKINFO_BLOB_NAME, {"chunks": {}}, "test", tmp_path)

    rows = _body(_get("/api/reference", ctx))["reference"]

    assert not ctx.derivations.loaded, "reading the reference state parsed the export"
    by_name = {row["name"]: row for row in rows}
    assert by_name[cache.CHUNKINFO_BLOB_NAME]["cached"] is True
    assert by_name[cache.CHUNKINFO_BLOB_NAME]["fetched_at"]
    assert by_name[cache.WIKI_RATES_BLOB_NAME]["cached"] is False
    # Which action refreshes which blob is answered here, not in the page.
    assert by_name[cache.WIKI_RATES_BLOB_NAME]["refresh"] == "heuristics"
    assert by_name[cache.CHUNKINFO_BLOB_NAME]["refresh"] == "chunkinfo"


def test_the_recipe_blob_is_one_of_the_reference_rows(tmp_path: Path) -> None:
    """**Its absence floors a whole skill and says nothing.**

    Every one of Construction's 227 rated methods comes from a `{{Recipe}}`
    row, so a cache without this blob prices the skill at the 1,000/hr default
    - 13,034h against 191h, with `(none found)` as its method. Every other
    skill degrades partially; this one degrades completely, which reads as a
    modelling gap rather than as missing data. The page could not say it was
    missing and offered no way to fetch it.
    """
    ctx = Context(root=tmp_path)

    rows = _body(_get("/api/reference", ctx))["reference"]

    entry = next(row for row in rows if row["name"] == cache.RECIPES_BLOB_NAME)
    assert entry["cached"] is False
    assert entry["refresh"] == "recipes"
    assert not ctx.derivations.loaded, "asking what is cached parsed the export"
