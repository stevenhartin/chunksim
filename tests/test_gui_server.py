"""Tests for the GUI's routing.

**Nothing here binds a socket.** `handle_request` is a pure function precisely
so the whole surface is reachable without one - loopback is still a socket,
still a port to collide on, still something a sandbox can refuse, and the
repo's "no test touches the network" rule is worth keeping in letter as well as
in spirit.
"""

from __future__ import annotations

import json
import re
import threading
import time
from http import HTTPStatus
from pathlib import Path
from typing import Any

import pytest

from fray_claude import cache
from fray_claude.api import FetchError
from fray_claude.gui.browser import window_flags
from fray_claude.gui.server import (
    Context,
    Response,
    _origin_ok,
    handle_request,
    normalise_host,
)

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


def test_a_view_carries_the_unlocked_cells(ctx: Context) -> None:
    response = _get("/api/view", ctx, map="fray")

    assert response.status == HTTPStatus.OK
    assert response.content_type.startswith("application/json")
    payload = _body(response)
    assert payload["map_id"] == "fray"
    assert [cell["chunk_id"] for cell in payload["cells"]] == [LUMBRIDGE]
    assert payload["counts"]["unlocked"] == 1


def test_a_comparison_marks_gains_and_losses_in_the_right_direction(
    tmp_path: Path,
) -> None:
    """Green is what the compared map has and the base does not.

    Backwards, this paints every gain red, which is the kind of thing that
    looks plausible in a screenshot.
    """
    _write_map(tmp_path, "before", [LUMBRIDGE, NORTH])
    _write_map(tmp_path, "after", [LUMBRIDGE, "13106"])
    ctx = Context(root=tmp_path)

    payload = _body(_get("/api/view", ctx, map="before", compare="after"))
    states = {cell["chunk_id"]: cell["state"] for cell in payload["cells"]}

    assert states["13106"] == "added"
    assert states[NORTH] == "removed"
    assert states[LUMBRIDGE] == "unlocked"
    assert payload["compare_map_id"] == "after"


def test_the_revision_moves_when_the_map_changes(ctx: Context, tmp_path: Path) -> None:
    """The live-reload token. A stat, not a hash - see the module docstring."""
    first = _body(_get("/api/revision", ctx, map="fray"))["revision"]

    _write_map(tmp_path, "fray", [LUMBRIDGE, NORTH])
    second = _body(_get("/api/revision", ctx, map="fray"))["revision"]

    assert first != second
    assert second == _body(_get("/api/view", ctx, map="fray"))["revision"]


def test_a_comparison_notices_either_side_changing(tmp_path: Path) -> None:
    _write_map(tmp_path, "before", [LUMBRIDGE])
    _write_map(tmp_path, "after", [LUMBRIDGE])
    ctx = Context(root=tmp_path)
    first = _body(_get("/api/revision", ctx, map="before", compare="after"))["revision"]

    _write_map(tmp_path, "after", [LUMBRIDGE, NORTH])
    second = _body(_get("/api/revision", ctx, map="before", compare="after"))["revision"]

    assert first != second


def test_maps_lists_what_is_cached(ctx: Context) -> None:
    payload = _body(_get("/api/maps", ctx))

    assert [entry["map_id"] for entry in payload] == ["fray"]


def test_an_unknown_map_is_a_404_carrying_the_cache_message(ctx: Context) -> None:
    """`CacheMissError`'s own text already names the fixing command."""
    response = _get("/api/view", ctx, map="nope")

    assert response.status == HTTPStatus.NOT_FOUND
    assert "nope" in _body(response)["error"]


def test_a_view_without_a_map_is_a_400(ctx: Context) -> None:
    response = _get("/api/view", ctx)

    assert response.status == HTTPStatus.BAD_REQUEST
    assert "map" in _body(response)["error"]


def test_an_unknown_route_is_a_404(ctx: Context) -> None:
    assert _get("/api/nope", ctx).status == HTTPStatus.NOT_FOUND
    assert _get("/nope", ctx).status == HTTPStatus.NOT_FOUND


def test_an_unknown_method_is_refused(ctx: Context) -> None:
    assert handle_request("PUT", "/api/view", {}, ctx).status == (
        HTTPStatus.METHOD_NOT_ALLOWED
    )


def test_posting_to_a_read_only_route_is_a_404(ctx: Context) -> None:
    """Only the action routes accept a POST; the rest simply are not there."""
    assert handle_request("POST", "/api/view", {}, ctx).status == HTTPStatus.NOT_FOUND


# --- traversal -------------------------------------------------------------


@pytest.mark.parametrize(
    "map_id",
    ["../../etc/passwd", "..", "../fray", "fray/../../etc/passwd", "/etc/passwd"],
)
def test_a_map_id_cannot_escape_the_cache(ctx: Context, map_id: str) -> None:
    """The guard is `cache.split_map_id`, not anything in the server.

    Pinned here so the reliance is visible: a second, weaker check in the
    server is exactly how two guards drift apart, so there deliberately isn't
    one.
    """
    assert _get("/api/view", ctx, map=map_id).status == HTTPStatus.NOT_FOUND


@pytest.mark.parametrize(
    "path",
    [
        "/static/../../../etc/passwd",
        "/static/%2e%2e%2f%2e%2e%2fapp.js",
        "/../style.css",
        "/static/",
    ],
)
def test_a_static_path_cannot_escape_the_resources(ctx: Context, path: str) -> None:
    """Closed by construction: the allowlist is matched by equality, so no
    caller-supplied string is ever joined onto a path."""
    assert _get(path, ctx).status == HTTPStatus.NOT_FOUND


# --- static and the image --------------------------------------------------


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/", "text/html"),
        ("/static/app.js", "text/javascript"),
        ("/static/style.css", "text/css"),
    ],
)
def test_the_packaged_resources_are_served(
    ctx: Context, path: str, content_type: str
) -> None:
    """Also proves each allowlist entry names a file that exists.

    It does **not** prove the wheel shipped them - only `python -m zipfile -l`
    can, and CLAUDE.md's Commands block carries that line.
    """
    response = _get(path, ctx)

    assert response.status == HTTPStatus.OK
    assert response.content_type.startswith(content_type)
    assert response.body


def test_the_tile_source_is_a_template_and_never_a_tile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**`/api/tiles` hands out a URL. It must never hand out a picture.**

    The tiles are CC BY-NC-SA 3.0 and this project is MIT, so caching them
    under `cache/` or re-serving them off loopback would make it a
    redistributor of NonCommercial artwork - pointing the browser at the
    wiki's own CDN makes it a page with a picture on it. That distinction is
    the whole reason this route exists, so it is asserted rather than trusted
    to a comment.
    """
    monkeypatch.delenv("FRAY_TILE_VERSION", raising=False)
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
    """`FRAY_TILE_VERSION` is the escape hatch for a scrape that has broken.

    The version comes out of a rendered page, and a page can change shape;
    pinning is what turns that from "the map is gone" into "the map is a bit
    old". It must not touch the wiki at all, which is what the exploding
    fetcher pins.
    """
    monkeypatch.setenv("FRAY_TILE_VERSION", "2020-01-01_z")
    monkeypatch.setattr(
        "fray_claude.gui.server.fetch_map_tile_version",
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
    monkeypatch.delenv("FRAY_TILE_VERSION", raising=False)
    cache.write_tile_version("2026-07-29_a", "https://example.invalid", root=tmp_path)
    # Age it past the refresh window so the scrape is attempted.
    blob = cache.blob_path(cache.TILE_VERSION_BLOB_NAME, tmp_path)
    stale = json.loads(blob.read_text())
    stale["fetched_at"] = "2020-01-01T00:00:00+00:00"
    blob.write_text(json.dumps(stale))

    def explode(*args: Any, **kwargs: Any) -> str:
        raise FetchError("the wiki is down")

    monkeypatch.setattr("fray_claude.gui.server.fetch_map_tile_version", explode)

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
    monkeypatch.delenv("FRAY_TILE_VERSION", raising=False)

    def explode(*args: Any, **kwargs: Any) -> str:
        raise FetchError("the wiki is down")

    monkeypatch.setattr("fray_claude.gui.server.fetch_map_tile_version", explode)

    payload = _body(_get("/api/tiles", Context(root=tmp_path)))

    assert payload["version"] == ""
    assert "the wiki is down" in payload["error"]


def test_the_world_map_route_is_gone(tmp_path: Path) -> None:
    """It used to serve Jagex's image off loopback. Nothing serves imagery now."""
    assert _get("/world_map", Context(root=tmp_path)).status == HTTPStatus.NOT_FOUND
    assert _get("/world_map.png", Context(root=tmp_path)).status == HTTPStatus.NOT_FOUND


# --- the contract between the two languages --------------------------------


def _app_js() -> str:
    from fray_claude.gui.server import RESOURCE_DIR

    return (RESOURCE_DIR / "app.js").read_text(encoding="utf-8")


def test_the_edge_bits_agree_across_the_two_languages() -> None:
    """`app.js` masks the same bitfield `worldmap.Edge` sets.

    Nothing forces these to match - the value crosses as a plain integer in
    JSON - so a renumbered flag would draw the hull on the wrong sides and
    every test on either side would still pass.
    """
    from fray_claude.gui.worldmap import Edge

    match = re.search(
        r"const TOP = (\d+), BOTTOM = (\d+), LEFT = (\d+), RIGHT = (\d+);", _app_js()
    )
    assert match is not None
    top, bottom, left, right = (int(value) for value in match.groups())

    assert (top, bottom, left, right) == (
        Edge.TOP.value,
        Edge.BOTTOM.value,
        Edge.LEFT.value,
        Edge.RIGHT.value,
    )


def test_the_hover_readout_inverts_the_real_projection() -> None:
    """The browser turns a square back into a chunk id without a round trip.

    That means it carries its own copy of the projection, and a copy that
    drifts would name the wrong chunk under the cursor - the sort of thing
    nobody notices until they paste the id into `fray unlock`.
    """
    from fray_claude.gui.worldmap import MAX_REGION_Y, MIN_REGION_X, REGION_STRIDE

    source = _app_js()
    # `gridToChunk`, which the hover readout and the candidate overlay both use.
    assert re.search(
        rf"\(gx \+ {MIN_REGION_X}\) \* {REGION_STRIDE} \+ \({MAX_REGION_Y} - gy\)", source
    )
    # `chunkToGrid`, the same projection run backwards.
    assert re.search(rf"\(id >> 8\) - {MIN_REGION_X}", source)
    assert re.search(rf"{MAX_REGION_Y} - \(id & 0xff\)", source)


def test_the_tile_pyramid_agrees_across_the_two_languages() -> None:
    """Three numbers cross into JavaScript with nothing enforcing agreement.

    `app.js` computes tile indices itself - a round trip per tile would be
    absurd - so it carries its own copy of the pyramid. Disagree and every
    tile is fetched at the wrong level, which draws a plausible-looking map of
    the wrong place.
    """
    from fray_claude.gui.worldmap import MAX_TILE_ZOOM, MIN_TILE_ZOOM, TILE_PIXELS

    source = _app_js()
    assert f"const TILE_PIXELS = {TILE_PIXELS};" in source
    assert f"const MIN_TILE_ZOOM = {MIN_TILE_ZOOM};" in source
    assert f"const MAX_TILE_ZOOM = {MAX_TILE_ZOOM};" in source
    # The span relation, which is the one piece of arithmetic that has to
    # match the wiki's scheme rather than merely match Python.
    assert "return TILE_PIXELS / Math.pow(2, z);" in source


def test_the_tile_placement_uses_the_edge_row_not_the_cell_row() -> None:
    """The off-by-one that draws a plausible map of the wrong place.

    `gridToChunk` uses `MAX_REGION_Y - region_y`, which numbers a *cell*:
    region 65 is row 0. `worldToScreenY` maps a world coordinate to where that
    *line* falls, and the line along the top of row 0 is region 65's north
    edge - one region further on. So it needs `MAX_REGION_Y + 1`, and using 65
    in both places puts every tile one row high.

    Caught by comparing the canvas against a raw tile, which matched to 0.016
    mean channel difference once fixed and 13.7 one pixel out. Pinned here
    because nothing else would notice.
    """
    from fray_claude.gui.worldmap import MAX_REGION_Y

    match = re.search(r"const GRID_TOP_REGION_Y = (\d+);", _app_js())
    assert match is not None
    assert int(match.group(1)) == MAX_REGION_Y + 1


def test_the_plane_reaches_the_tile_url_and_nothing_else() -> None:
    """**Changing floor changes the picture and no data at all.**

    A chunk is a region and a region contains every plane, so the unlocked
    set, the hull and every panel are identical on floor 3 and floor 0 - only
    the tiles differ. If a plane change ever started refetching a view, that
    would be a derivation per floor for no answer.
    """
    source = _app_js()

    assert "plane: 0," in source                      # part of the camera state
    assert '.replace("{plane}"' in source             # substituted into the URL
    # The handler invalidates and does nothing else - no loadView, no fetch.
    handler = re.search(
        r'el\.plane\.addEventListener\("change", \(\) => \{(.*?)\}\);', source, re.DOTALL
    )
    assert handler is not None
    body = handler.group(1)
    assert "invalidate()" in body
    assert "loadView" not in body and "getJSON" not in body


def test_a_higher_plane_sinks_the_ground_and_not_the_floor() -> None:
    """**A plane-N tile is one flat image holding both**, which is the whole
    difficulty.

    It is the ground floor faded back with this floor drawn over it - no
    transparency, and no separate overlay tile to ask for. Darkening the tile
    darkens the floor along with the ground, which is the bug this replaces.
    The fade is linear, so it is fitted per tile (`a` runs 0.13 to 0.52, so it
    cannot be assumed) and only the pixels that *fit* are sunk.
    """
    source = _app_js()

    assert "function composeFloor(" in source
    assert "function fitFade(" in source
    # The draw path and the coarse fallback both go through the composition,
    # or a fallback tile would come out undarkened.
    assert "const image = composedTile(z, x, y);" in source
    assert "composedTile(z - up, x >> up, y >> up)" in source
    # The ground floor is never composed against itself.
    assert "if (!state.plane || !floor) return floor;" in source
    # A whole-canvas scrim would darken the overlays too, and is gone.
    assert "drawPlaneScrim" not in source
    # Separating costs ~3ms a tile, so it is rationed per frame rather than
    # spent all at once; unbudgeted tiles draw unseparated, never blank.
    assert "composeBudget = PLANE_COMPOSE_BUDGET;" in source
    assert "if (composeBudget <= 0) {" in source


def test_a_missing_tile_falls_back_to_a_coarser_one() -> None:
    """A tile that is not there should look blurry, not black.

    Every level of the pyramid covers the same world, so the level above
    contains this tile at half the resolution. Without the walk a dropped
    request is a black square for the rest of the session - `onerror` cannot
    tell a 404 from a connection the browser gave up on, so a miss is also
    retried before it counts as absent.
    """
    source = _app_js()

    assert "function tileAncestor(" in source
    assert "tileAncestor(z, x, y)" in source          # drawTiles actually uses it
    # A miss is provisional: more than one attempt before it is remembered.
    match = re.search(r"const TILE_TRIES = (\d+);", source)
    assert match is not None and int(match.group(1)) > 1
    assert 'tileCache.delete(url)' in source          # so a later frame retries


def test_the_coarse_fallback_flips_y_and_not_x() -> None:
    """The one line in the fallback that can be silently wrong.

    Tile indices count *northward* while image rows run *southward*, so within
    an ancestor the child with the highest y is at the **top**. Getting it
    backwards mirrors every fallback vertically - which still looks like a
    plausible piece of map. Checked against real tiles: each of the four
    quadrants matched its parent crop and was the best of the four.
    """
    source = _app_js()

    assert "sx: (x & (step - 1)) * size," in source
    assert "sy: (step - 1 - (y & (step - 1))) * size," in source


def test_the_page_loads_tiles_from_the_wiki_and_not_from_here() -> None:
    """The licence lives in this assertion as much as in any docstring.

    A future edit that proxies tiles through `fray-gui` "for caching" would
    turn this project into a redistributor of NonCommercial artwork, and it
    would look like a performance win while doing it.
    """
    source = _app_js()

    assert "tiles.template" in source
    # No same-origin tile route, and no re-introduced world-map fetch.
    assert "/world_map" not in source
    assert 'image.crossOrigin = "anonymous";' in source


def test_the_tile_attribution_is_on_screen() -> None:
    """CC BY-NC-SA asks for credit, and a credit behind a menu is not one."""
    from fray_claude.gui.server import RESOURCE_DIR

    html = (RESOURCE_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="attribution"' in html
    assert "renderAttribution" in _app_js()


def test_the_whole_chunk_section_sentinel_agrees_across_the_two_languages() -> None:
    """An unsplit chunk's one section is drawn, not fetched.

    `server.WHOLE_CHUNK_SECTION` is a value the browser has to recognise to
    know it must fill the square itself. Disagree and it asks for
    `<chunk>-*.png`, which `cache.section_overlay_path` rejects - so the
    failure is a shading hole plus a 400 per square, in a mode nothing tests.
    """
    from fray_claude.gui.server import WHOLE_CHUNK_SECTION

    match = re.search(r'const WHOLE_CHUNK = "([^"]+)";', _app_js())
    assert match is not None
    assert match.group(1) == WHOLE_CHUNK_SECTION


# --- the actions -----------------------------------------------------------


def _post(path: str, ctx: Context, payload: Any = None, **headers: str) -> Response:
    body = b"" if payload is None else json.dumps(payload).encode("utf-8")
    return handle_request("POST", path, {}, ctx, body=body, headers=headers)


def _wait(ctx: Context, job_id: str, timeout: float = 5.0) -> dict[str, Any]:
    """Poll a job to completion, the way the browser does."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = ctx.jobs.get(job_id)
        assert job is not None
        if job.state != "running":
            return job.as_dict()
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


def test_a_simulate_post_returns_a_job_that_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of the job shape: a POST answers before the work does."""
    monkeypatch.setattr(
        "fray_claude.gui.server.run_batch",
        lambda **kw: _FakeBatch(kw["name"], kw["runs"], kw["on_complete"]),
    )
    ctx = Context(root=tmp_path, check_origin=False)
    _write_map(tmp_path, "fray", [LUMBRIDGE])

    response = _post("/api/simulate", ctx, {"map": "fray", "name": "sim", "rolls": 2})

    assert response.status == HTTPStatus.ACCEPTED
    job = _wait(ctx, _body(response)["job"])
    assert job["state"] == "done"
    assert job["result"]["batch"] == "sim"


def test_a_failing_job_reports_its_reason_without_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The traceback names paths on this machine, so it stays in the terminal."""
    def explode(**kw: Any) -> None:
        raise RuntimeError("the pool caught fire")

    monkeypatch.setattr("fray_claude.gui.server.run_batch", explode)
    ctx = Context(root=tmp_path, check_origin=False)
    _write_map(tmp_path, "fray", [LUMBRIDGE])

    response = _post("/api/simulate", ctx, {"map": "fray", "name": "sim", "rolls": 1})
    job = _wait(ctx, _body(response)["job"])

    assert job["state"] == "failed"
    assert job["error"] == "RuntimeError: the pool caught fire"
    assert "Traceback" not in json.dumps(job)


def test_a_bad_base_map_fails_the_post_not_the_job(tmp_path: Path) -> None:
    """Catching it here means the browser sees it immediately, not after a poll."""
    ctx = Context(root=tmp_path, check_origin=False)

    response = _post("/api/simulate", ctx, {"map": "nope", "name": "sim", "rolls": 1})

    assert response.status == HTTPStatus.NOT_FOUND


@pytest.mark.parametrize(
    "payload",
    [{"name": "sim"}, {"map": "fray"}, {}],
)
def test_a_simulate_without_its_required_fields_is_a_400(
    ctx: Context, payload: dict[str, Any]
) -> None:
    ctx = Context(root=ctx.root, check_origin=False)
    assert _post("/api/simulate", ctx, payload).status == HTTPStatus.BAD_REQUEST


def test_a_malformed_body_is_a_400(ctx: Context) -> None:
    ctx = Context(root=ctx.root, check_origin=False)
    response = handle_request("POST", "/api/fetch", {}, ctx, body=b"{not json")

    assert response.status == HTTPStatus.BAD_REQUEST


def test_a_cross_site_post_is_refused(ctx: Context) -> None:
    """A loopback bind stops other machines, not other tabs.

    Any page you have open can POST to 127.0.0.1 and the browser will send it.
    It cannot read the reply, so the exposure is nuisance-grade - but the
    header says plainly that the request is cross-site, and it costs nothing to
    believe it.
    """
    response = _post(
        "/api/fetch", ctx, {"map": "fray"}, **{"Sec-Fetch-Site": "cross-site", "Host": "localhost:8731"}
    )

    assert response.status == HTTPStatus.FORBIDDEN
    assert "cross-site" in _body(response)["error"]


def test_a_rebound_host_is_refused(ctx: Context) -> None:
    """DNS rebinding: a hostile domain resolving to 127.0.0.1, so its page's
    origin *is* this server and Sec-Fetch-Site reads same-origin."""
    response = _post(
        "/api/fetch", ctx, {"map": "fray"}, **{"Sec-Fetch-Site": "same-origin", "Host": "evil.example.com"}
    )

    assert response.status == HTTPStatus.FORBIDDEN
    assert "Host" in _body(response)["error"]


def test_a_same_origin_post_is_allowed(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "fray_claude.gui.server.fetch_map",
        lambda map_id, timeout=30.0: {"chunks": {"unlocked": {LUMBRIDGE: LUMBRIDGE}}},
    )
    response = _post(
        "/api/fetch", ctx, {"map": "fray"}, **{"Sec-Fetch-Site": "same-origin", "Host": "127.0.0.1:8731"}
    )

    assert response.status == HTTPStatus.ACCEPTED
    assert _wait(ctx, _body(response)["job"])["state"] == "done"


def test_a_post_from_an_allowed_host_is_accepted(
    ctx: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--host <tailnet address>` has to serve a page that can act.

    Loopback-only left the remote page rendering in full with every button
    403ing, which reads as a broken GUI rather than as a refusal.
    """
    monkeypatch.setattr(
        "fray_claude.gui.server.fetch_map",
        lambda map_id, timeout=30.0: {"chunks": {"unlocked": {LUMBRIDGE: LUMBRIDGE}}},
    )
    remote = Context(root=ctx.root, allowed_hosts=frozenset({"100.93.219.108"}))

    response = _post(
        "/api/fetch",
        remote,
        {"map": "fray"},
        **{"Sec-Fetch-Site": "same-origin", "Host": "100.93.219.108:8731"},
    )

    assert response.status == HTTPStatus.ACCEPTED
    assert _wait(remote, _body(response)["job"])["state"] == "done"


def test_the_allowlist_does_not_open_the_door_to_anything_else(ctx: Context) -> None:
    """Naming one address is not naming every address: rebinding still fails."""
    remote = Context(root=ctx.root, allowed_hosts=frozenset({"100.93.219.108"}))

    response = _post(
        "/api/fetch",
        remote,
        {"map": "fray"},
        **{"Sec-Fetch-Site": "same-origin", "Host": "evil.example.com"},
    )

    assert response.status == HTTPStatus.FORBIDDEN
    assert "Host" in _body(response)["error"]


def test_loopback_is_accepted_whatever_the_allowlist_holds(ctx: Context) -> None:
    """An ssh tunnel presents 127.0.0.1, and a bind elsewhere must not stop it."""
    remote = Context(root=ctx.root, allowed_hosts=frozenset({"100.93.219.108"}))

    assert _origin_ok({"Sec-Fetch-Site": "same-origin", "Host": "127.0.0.1:8731"},
                      remote.allowed_hosts) is None


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("127.0.0.1:8731", "127.0.0.1"),
        ("localhost", "localhost"),
        ("[::1]:8731", "::1"),
        ("::1", "::1"),
        ("Devbox.Tailnet.Ts.Net:8731", "devbox.tailnet.ts.net"),
    ],
)
def test_a_host_header_is_compared_without_its_port_or_case(
    header: str, expected: str
) -> None:
    """A bare IPv6 address keeps its colons; only the bracketed form has a port."""
    assert normalise_host(header) == expected


def test_an_unknown_job_is_a_404(ctx: Context) -> None:
    assert _get("/api/jobs/nope", ctx).status == HTTPStatus.NOT_FOUND


class _FakeBatch:
    """Stands in for `batch.run_batch`, which would want a real export."""

    def __init__(self, name: str, runs: int, on_complete: Any) -> None:
        self.name = name
        self.runs = [_FakeRun(f"run-{n:03d}") for n in range(1, runs + 1)]
        for run in self.runs:
            if on_complete:
                on_complete(run)


class _FakeRun:
    def __init__(self, name: str) -> None:
        self.name = name
        self.unlocked_chunks = 1
        self.rolls = ("100",)
        self.cancelled = False


def _resources() -> tuple[str, str, str]:
    from fray_claude.gui.server import RESOURCE_DIR

    return (
        (RESOURCE_DIR / "index.html").read_text(encoding="utf-8"),
        (RESOURCE_DIR / "app.js").read_text(encoding="utf-8"),
        (RESOURCE_DIR / "style.css").read_text(encoding="utf-8"),
    )


def test_every_element_the_page_reaches_for_exists() -> None:
    """`app.js` looks its elements up once, by id, into `el`.

    A renamed or dropped element leaves `el.thing` undefined and the failure
    lands wherever it is *used*, which may be three tabs away and only on a
    map that has something to show. Checking the list against the markup is
    the cheapest place to catch it.
    """
    html, js, _ = _resources()

    ids = set(re.findall(r'id="([^"]+)"', html))
    loop = re.search(r"for \(const id of \[(.*?)\]\)", js, re.DOTALL)
    assert loop is not None
    asked = set(re.findall(r'"([^"]+)"', loop.group(1)))

    assert asked, "the boot loop found no ids at all"
    assert asked <= ids, f"asked for but not in the markup: {sorted(asked - ids)}"


def test_every_style_token_is_defined() -> None:
    """The stylesheet's lengths all come from one scale.

    `var(--s7)` where the scale stops at `--s6` is not an error anywhere - the
    declaration is simply dropped and the element loses its padding, which
    reads as a layout bug with no cause.
    """
    _, _, css = _resources()

    defined = set(re.findall(r"^\s*(--[a-z0-9-]+)\s*:", css, re.MULTILINE))
    used = set(re.findall(r"var\((--[a-z0-9-]+)", css))

    assert used - defined == set(), f"undefined tokens: {sorted(used - defined)}"
    assert defined - used == set(), f"dead tokens: {sorted(defined - used)}"


def test_there_is_one_tooltip_system() -> None:
    """`title` and `data-tip` both show a tooltip, and both at once shows two.

    The custom one can carry a heading, a note and a keyboard hint; the native
    one is a plain string on a browser delay. Mixing them meant the bar behaved
    differently from every list under it.
    """
    html, _, _ = _resources()

    assert 'title="' not in html
    assert "data-tip=" in html


def test_the_scrolling_panes_reserve_their_gutter() -> None:
    """Chrome's overlay scrollbar sits *on top* of the last characters of a
    long task name, so the thing you are reading is the thing it covers.

    `scrollbar-gutter: stable` takes the width out of the content box whether
    or not the bar is showing, which also stops the pane reflowing the moment
    a list grows past the fold.
    """
    _, _, css = _resources()

    pane = re.search(r"\.pane > div:last-child \{(.*?)\}", css, re.DOTALL)
    assert pane is not None
    assert "scrollbar-gutter: stable" in pane.group(1)


def test_an_action_that_answers_inline_is_not_polled_as_a_job() -> None:
    """**Three of the six actions finish before they reply**, and reading
    `{ job }` off all six is what left the Maps tab showing deleted maps.

    `fetch`, `simulate` and `refresh` hand back a job id; `maps/remove`,
    `derived/prune` and `window` do the work and hand back the result. Polling
    `/api/jobs/undefined` 404s, and the 404 path treated that as "nothing more
    to say" - so the refresh callback never ran.
    """
    _, js, _ = _resources()

    assert "if (reply && reply.job) return followJob(" in js
    # The inline branch runs the callback rather than dropping it.
    assert "await onDone?.(reply);" in js


def test_the_chip_gestures_are_click_shift_ctrl() -> None:
    """Everything on by default, and narrowing to one is a single click.

    The strip records what is *off* rather than what is on, which is what
    makes a category nobody has seen yet default to on - holding the selected
    set froze it at whatever the first chunk happened to contain.
    """
    _, js, _ = _resources()

    body = re.search(r"function applyChipGesture\(.*?\n\}", js, re.DOTALL)
    assert body is not None
    assert "event.shiftKey" in body.group(0) and "off.delete(key)" in body.group(0)
    assert "event.ctrlKey || event.metaKey" in body.group(0) and "off.add(key)" in body.group(0)
    assert "off.clear();" in body.group(0)
    # Nothing anywhere holds a positive selection any more.
    assert "chunkCategories" not in js and "taskSections" not in js


def test_a_truncated_list_can_be_opened() -> None:
    """"17 more" used to be a dead grey line naming what it would not show."""
    _, js, css = _resources()

    assert "function withMore(" in js
    assert 'data-more="' in js
    # Collapsing is a second press, not something that happens on scroll.
    assert "Show fewer" in js
    body = re.search(r"function withMore\(.*?\n\}", js, re.DOTALL)
    assert body is not None and "scroll" not in body.group(0)
    assert ".more-toggle" in css


def test_removing_maps_asks_first() -> None:
    """`maps rm` deletes directories and is not undoable."""
    _, js, _ = _resources()

    assert "function confirmAction(" in js
    assert js.count("await confirmAction(") >= 2       # one map, and all of them
    # The derived cache is pure recomputation, so it is *not* gated.
    prune = re.search(r'getElementById\("prune"\)\.onclick.*?;', js, re.DOTALL)
    assert prune is not None and "confirmAction" not in prune.group(0)


def test_the_canvas_is_given_an_explicit_size() -> None:
    """`inset: 0` does not stretch a canvas, so the stylesheet must say the
    size outright.

    A canvas is a *replaced* element with intrinsic dimensions of 300x150, so
    with `width: auto` the offsets resolve against that intrinsic size rather
    than stretching it. Drop these two declarations and the map renders
    correctly into a 300x150 box in the corner - every coordinate right, the
    whole thing unusable, and looking like a rendering bug rather than a
    layout one.
    """
    from fray_claude.gui.server import RESOURCE_DIR

    css = (RESOURCE_DIR / "style.css").read_text(encoding="utf-8")
    canvas_rule = re.search(r"#canvas\s*\{(.*?)\}", css, re.DOTALL)

    assert canvas_rule is not None
    body = canvas_rule.group(1)
    assert re.search(r"\bwidth:\s*100%", body)
    assert re.search(r"\bheight:\s*100%", body)


# --- the derivation-backed endpoints ---------------------------------------


def _derived_ctx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, chunkinfo: dict[str, Any]
) -> Context:
    """A context whose derivations read a hand-built export.

    Same idiom as `tests/test_cli.py`: patch the reader rather than write a
    10MB file, so the fixture is the few keys under test.
    """
    monkeypatch.setattr(
        "fray_claude.gui.derivation.cache.read_chunkinfo",
        lambda override=None, root=None: chunkinfo,
    )
    monkeypatch.setattr(
        "fray_claude.gui.derivation.cache.read_blob",
        lambda name, root=None, hint=None: {"data": {}},
    )
    monkeypatch.setattr(
        "fray_claude.gui.derivation.cache.file_digest", lambda path: "digest"
    )
    # **Under `tmp_path`, not bare names.** These patch attributes on the
    # *shared* `cache` module, so anything that later writes through
    # `blob_path` writes wherever this points - and `Path("y")` is relative,
    # which put a stray file in the repo root the first time a test using
    # this fixture wrote a blob for real.
    monkeypatch.setattr(
        "fray_claude.gui.derivation.cache.chunkinfo_source", lambda o, r: tmp_path / "x"
    )
    monkeypatch.setattr(
        "fray_claude.gui.derivation.cache.blob_path", lambda n, r: tmp_path / f"{n}.json"
    )
    return Context(root=tmp_path)


def test_a_split_chunks_contents_are_found_and_attributed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**Contents live in one of two places and reading one is wrong.**

    An unsplit chunk carries Monster/NPC/Object at its top level; a split one
    carries nothing there and puts each branch inside `Sections`. 512 of the
    real export's chunks are split - Lumbridge among them - so a top-level
    read reported the castle as empty.

    They are collated into one list per kind, because the question is "what
    is in this square" - but which section something sits in still decides
    whether you can reach it, so that survives as a per-entity flag.
    """
    _write_map(tmp_path, "fray", [LUMBRIDGE])
    ctx = _derived_ctx(
        tmp_path,
        monkeypatch,
        {
            "chunks": {
                LUMBRIDGE: {
                    "Nickname": "Lumbridge Castle",
                    "Sections": {
                        "1": {"Monster": {"Duck": 11}, "NPC": {"Hans": 1}},
                        "2": {"Monster": {"Giant rat": 3}},
                    },
                }
            },
            "sections": {LUMBRIDGE: {"1": [], "2": []}},
        },
    )

    payload = _body(_get("/api/chunk", ctx, map="fray", chunk=LUMBRIDGE))

    assert payload["nickname"] == "Lumbridge Castle"
    monsters = {row["name"]: row for row in payload["contents"]["monster"]}
    assert sorted(monsters) == ["Duck", "Giant rat"]
    assert monsters["Duck"]["sections"] == ["1"]
    assert monsters["Giant rat"]["sections"] == ["2"]
    assert [row["name"] for row in payload["contents"]["npc"]] == ["Hans"]
    assert {s["section"] for s in payload["sections"]} == {"1", "2"}


def test_an_unsplit_chunk_reads_its_top_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_map(tmp_path, "fray", [LUMBRIDGE])
    ctx = _derived_ctx(
        tmp_path,
        monkeypatch,
        {"chunks": {LUMBRIDGE: {"Monster": {"Cow": 4}}}, "sections": {}},
    )

    payload = _body(_get("/api/chunk", ctx, map="fray", chunk=LUMBRIDGE))

    assert [row["name"] for row in payload["contents"]["monster"]] == ["Cow"]
    assert payload["contents"]["monster"][0]["reachable"] is True
    assert payload["sections"][0]["reachable"] is True


def test_a_locked_chunk_reports_nothing_reachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """You can see what is in a square without being able to get to it."""
    _write_map(tmp_path, "fray", [LUMBRIDGE])
    ctx = _derived_ctx(
        tmp_path,
        monkeypatch,
        {"chunks": {"13106": {"Monster": {"Cow": 4}}}, "sections": {}},
    )

    payload = _body(_get("/api/chunk", ctx, map="fray", chunk="13106"))

    assert payload["unlocked"] is False
    assert payload["reachable_sections"] == 0
    assert [row["name"] for row in payload["contents"]["monster"]] == ["Cow"]
    assert payload["contents"]["monster"][0]["reachable"] is False


def test_every_placed_chunk_gets_a_section_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**An unsplit chunk is one section, and the overlay has to say so.**

    Only split chunks used to appear, so shading the map left every unsplit
    square bare - which reads as missing data rather than as "this chunk is
    not divided". They carry `WHOLE_CHUNK_SECTION` instead, because upstream
    drew no mask for a shape that is the whole square: the browser fills it.

    Locked chunks are in, all-red, since "what is behind this square" is
    asked hardest about one you have not got.
    """
    from fray_claude.gui.server import WHOLE_CHUNK_SECTION

    _write_map(tmp_path, "fray", [LUMBRIDGE])
    ctx = _derived_ctx(
        tmp_path,
        monkeypatch,
        {
            "chunks": {
                LUMBRIDGE: {"Sections": {"0": {}, "1": {}}},
                NORTH: {"Monster": {"Cow": 4}},
                "Abyss": {"Monster": {"Abyssal leech": 1}},
            },
            "sections": {LUMBRIDGE: {"0": [], "1": []}},
        },
    )

    chunks = _body(_get("/api/sections", ctx, map="fray"))["chunks"]

    # Split and unlocked: section 0 comes free with the chunk, 1 does not.
    assert chunks[LUMBRIDGE] == {"0": True, "1": False}
    # Unsplit and locked: one section, and you cannot reach it.
    assert chunks[NORTH] == {WHOLE_CHUNK_SECTION: False}
    # A named area has no square, so there is nothing to shade.
    assert "Abyss" not in chunks


def test_the_full_diff_reports_both_directions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`/api/diff` is `fray diff`, and the one route allowed to derive twice.

    The map view answers the *chunks* question from a set difference in
    microseconds, which is why it does not call `compare_maps`. This one has
    to: sections, tasks, sources and BiS have no cheap answer.
    """
    _write_map(tmp_path, "before", [LUMBRIDGE])
    _write_map(tmp_path, "after", [LUMBRIDGE, NORTH])
    ctx = _derived_ctx(
        tmp_path,
        monkeypatch,
        {
            "chunks": {LUMBRIDGE: {"Monster": {"Cow": 4}}, NORTH: {"Monster": {"Duck": 11}}},
            "sections": {},
        },
    )

    payload = _body(_get("/api/diff", ctx, map1="before", map2="after"))

    assert payload["counts"]["chunks"] == {"added": 1, "removed": 0}
    assert list(payload["chunks"]["added"]) == [NORTH]
    assert payload["chunks"]["removed"] == []
    # The Duck comes with the chunk, so the sources branch moves too.
    assert payload["counts"]["sources"]["added"] >= 1
    assert payload["before_map"] == "before"
    assert payload["after_map"] == "after"


def test_the_full_diff_needs_both_maps(tmp_path: Path) -> None:
    response = _get("/api/diff", Context(root=tmp_path), map1="before")

    assert response.status == HTTPStatus.BAD_REQUEST
    assert "map2" in _body(response)["error"]


def test_the_areas_route_names_every_region_that_is_part_of_a_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Static per export, so no `map` and no derivation - just the parse.

    Which region is part of `Kurask Lair` does not depend on anybody's map,
    which is why the browser asks once at boot and never invalidates it.
    """
    _write_map(tmp_path, "fray", [LUMBRIDGE])
    ctx = _derived_ctx(
        tmp_path,
        monkeypatch,
        {
            "chunks": {
                "4751": {"Name": "Kurask Lair"},
                LUMBRIDGE: {"Monster": {"Cow": 4}},
            },
            "sections": {},
        },
    )

    payload = _body(_get("/api/areas", ctx))

    assert payload["areas"] == {"4751": "Kurask Lair"}


def test_a_map_holding_a_named_area_pays_for_the_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one case where `/api/view` is allowed to parse the 10MB export.

    A named id has no coordinates, so there is no cheaper way to draw it. The
    parse is conditional on the map actually holding one - see the companion
    test that an all-numeric map still never touches the export.
    """
    _write_map(tmp_path, "fray", [LUMBRIDGE, "Kurask Lair"])
    ctx = _derived_ctx(
        tmp_path,
        monkeypatch,
        {"chunks": {"4751": {"Name": "Kurask Lair"}}, "sections": {}},
    )

    payload = _body(_get("/api/view", ctx, map="fray"))
    drawn = {cell["chunk_id"]: cell["area"] for cell in payload["cells"]}

    assert drawn == {LUMBRIDGE: None, "4751": "Kurask Lair"}
    assert payload["counts"]["skipped"] == 0
    assert ctx.derivations.loaded


def test_the_area_labels_are_drawn_over_the_hull_and_read_the_same_map() -> None:
    """Two things the panel and the canvas have to agree on.

    A label under the hull is a name with a line through it; a hover readout
    reading some other source is a name that disagrees with the one on screen.
    """
    source = _app_js()

    layers = re.search(r"const LAYERS = \[(.*?)\];", source, re.DOTALL)
    assert layers is not None
    order = [n.strip() for n in layers.group(1).replace("\n", " ").split(",") if n.strip()]
    assert order.index("drawAreas") > order.index("drawHull")
    # The readout and the labels both read `state.areas`, which `/api/areas`
    # fills - not a second copy that could drift.
    assert "state.areas[chunkId]" in source
    assert 'getJSON("/api/areas")' in source


def test_the_summary_answers_what_fray_show_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_map(tmp_path, "fray", [LUMBRIDGE, NORTH])
    ctx = Context(root=tmp_path)

    payload = _body(_get("/api/summary", ctx, map="fray"))

    assert payload["unlocked_chunks"] == 2
    assert payload["kind"] == "fetched"


def test_unlocking_a_chunk_you_already_have_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The question has no meaning, and a zero-delta answer would look like a
    verdict rather than a category error."""
    _write_map(tmp_path, "fray", [LUMBRIDGE])
    ctx = _derived_ctx(
        tmp_path, monkeypatch, {"chunks": {LUMBRIDGE: {}}, "sections": {}}
    )

    response = _get("/api/unlock", ctx, map="fray", chunk=LUMBRIDGE)

    assert response.status == HTTPStatus.BAD_REQUEST
    assert "already unlocked" in _body(response)["error"]


def test_the_map_view_never_parses_the_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The property the whole server is built around.

    Rendering needs only the unlocked set, so a view request must not touch
    the 10MB export - that is what keeps it milliseconds and why nothing has
    to be invalidated.
    """
    _write_map(tmp_path, "fray", [LUMBRIDGE])

    def explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the map view parsed the chunkinfo export")

    monkeypatch.setattr("fray_claude.gui.derivation.cache.read_chunkinfo", explode)
    ctx = Context(root=tmp_path)

    assert _get("/api/view", ctx, map="fray").status == HTTPStatus.OK
    assert _get("/api/revision", ctx, map="fray").status == HTTPStatus.OK
    assert _get("/api/summary", ctx, map="fray").status == HTTPStatus.OK
    assert not ctx.derivations.loaded


def test_the_page_strips_task_markup_for_display() -> None:
    """Task names are markup-bearing keys and the raw form must not be shown.

    `~|Dom Onion's Reward Shop|~` is what everything is *keyed* by; stripping
    it is display-only, which is why the browser does it rather than the
    server. Mirrors `challenges.strip_task_markup`, and the page applies it
    only to names and details - other branches of the export use `~` and `|`
    for real.
    """
    source = _app_js()

    assert "function plain(" in source
    # Every place a task-ish string reaches innerHTML goes through it.
    assert source.count("plain(") >= 5


# --- upstream assets, fetched lazily ---------------------------------------


def test_a_section_mask_is_fetched_once_and_then_read_from_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of the proxy: 1,534 masks, and you look at a handful."""
    calls: list[str] = []

    def fake(name: str, timeout: float = 0.0) -> bytes:
        calls.append(name)
        return b"\x89PNG-mask"

    monkeypatch.setattr("fray_claude.gui.server.fetch_section_overlay", fake)
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

    monkeypatch.setattr("fray_claude.gui.server.fetch_section_overlay", fake)

    response = _get("/assets/section/12850-9.png", Context(root=tmp_path))

    assert response.status == HTTPStatus.NOT_FOUND


@pytest.mark.parametrize(
    "name",
    ["../../../etc/passwd", "12850-1/../../x", "..", "12850-1.png", "12850_1"],
)
def test_an_asset_name_cannot_escape_the_cache(tmp_path: Path, name: str) -> None:
    """**The one asset name that comes from a URL.**

    `cache.section_overlay_path` matches it whole against an alphabet with no
    `.` and no `/` in it, so there is nothing to smuggle through - and a name
    that fails is a malformed URL, not a missing file.
    """
    response = _get(f"/assets/section/{name}.png", Context(root=tmp_path))

    assert response.status == HTTPStatus.BAD_REQUEST


def test_a_skill_icon_takes_the_same_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "fray_claude.gui.server.fetch_skill_icon", lambda skill, timeout=0.0: b"icon"
    )

    response = _get("/assets/skill/Attack.png", Context(root=tmp_path))

    assert response.status == HTTPStatus.OK
    assert cache.skill_icon_path("Attack", tmp_path).read_bytes() == b"icon"


# --- window geometry -------------------------------------------------------


def test_the_page_reports_its_window_and_the_next_launch_reads_it_back(
    tmp_path: Path,
) -> None:
    """Chrome will not remember this for us; see `browser.window_flags`."""
    ctx = Context(root=tmp_path, check_origin=False)

    _post("/api/window", ctx, {"width": 1600, "height": 900, "x": 20, "y": 40})

    assert cache.read_gui_window(tmp_path) == {
        "width": 1600,
        "height": 900,
        "x": 20,
        "y": 40,
        "maximised": False,
    }
    assert window_flags(cache.read_gui_window(tmp_path)) == [
        "--window-size=1600,900",
        "--window-position=20,40",
    ]


def test_a_partial_or_hostile_window_report_is_ignored(tmp_path: Path) -> None:
    """The file is read back as command-line arguments, so its keys are fixed."""
    ctx = Context(root=tmp_path, check_origin=False)

    _post("/api/window", ctx, {"width": 800, "evil": "--headless"})

    assert cache.read_gui_window(tmp_path) == {}


def test_a_first_run_opens_maximised(tmp_path: Path) -> None:
    """Not fullscreen: closing the window is how you stop the server, and
    fullscreen hides the control that does it."""
    assert window_flags(cache.read_gui_window(tmp_path)) == ["--start-maximized"]


def test_no_unescaped_interpolation_lands_inside_an_attribute() -> None:
    """**`raw()` is for element content and never for an attribute.**

    Inside `data-tip="${...}"` it splices unescaped quotes straight through
    the closing quote and the markup after it lands on screen as text - which
    is what a tooltip built from `<span class="sub">` did. `tmpl` escapes an
    ordinary interpolation, and the browser decodes it again when
    `dataset.tip` is read, so the HTML arrives intact having never been able
    to escape its attribute.

    Cheap to get wrong and invisible in review, so it is asserted rather than
    remembered.
    """
    source = _app_js()

    offenders = re.findall(r'=\s*"\$\{raw\(', source)

    assert not offenders, f"{len(offenders)} raw() interpolations inside an attribute"


def test_a_fetch_can_name_any_map_and_blank_means_the_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**The point of the box is fetching a map you have never cached.**

    Every source-chunk map is a public unauthenticated read, so the id you can
    type is not limited to the ids already in the picker - which is exactly
    what "Fetch This Map", driven off the selected option, could not do.
    """
    seen: list[str] = []

    def pretend(map_id: str, timeout: float = 0.0) -> dict[str, Any]:
        seen.append(map_id)
        return {"chunks": {"unlocked": {LUMBRIDGE: LUMBRIDGE}}}

    monkeypatch.setattr("fray_claude.gui.server.fetch_map", pretend)
    ctx = Context(root=tmp_path, check_origin=False)

    named = _wait(ctx, _body(_post("/api/fetch", ctx, {"map": "someone-else"}))["job"])
    blank = _wait(ctx, _body(_post("/api/fetch", ctx, {"map": "  "}))["job"])

    assert seen == ["someone-else", cache.DEFAULT_MAP_ID]
    assert named["result"]["map"] == "someone-else"
    assert blank["result"]["map"] == cache.DEFAULT_MAP_ID
    # Both landed where `fray fetch` puts one, so the picker can see them.
    assert cache.read_cache("someone-else", tmp_path)["kind"] == cache.FETCHED


def test_the_default_map_id_agrees_across_the_two_languages() -> None:
    """The placeholder promises what blank does, and nothing enforces it.

    A third constant crossing into JavaScript over no wire at all - see the
    `Edge` bitfield and the projection. The symptom of drift is a box that
    says `fray` and fetches something else.
    """
    _, js, _ = _resources()

    declared = re.search(r'const DEFAULT_MAP_ID = "([^"]+)"', js)

    assert declared is not None
    assert declared.group(1) == cache.DEFAULT_MAP_ID


def test_a_fetch_refuses_to_ask_firebase_for_a_run(tmp_path: Path) -> None:
    """`batch/run-001` is something this project computed. Upstream has never
    heard of it, so asking is a mistake rather than a fetch."""
    ctx = Context(root=tmp_path, check_origin=False)

    response = _post("/api/fetch", ctx, {"map": "sim/run-001"})

    assert response.status == HTTPStatus.BAD_REQUEST
    assert "run" in _body(response)["error"]


def test_unlocking_a_chunk_writes_a_map_of_its_own_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`fray unlock --chunk X --cache-map NAME`, reached from the chunk panel.

    The kind is the assertion that matters: a map made by adding one chunk by
    hand is `unlocked`, not `simulated`, because the picker has to say which.
    """
    _write_map(tmp_path, "fray", [LUMBRIDGE])
    ctx = _derived_ctx(
        tmp_path,
        monkeypatch,
        {"chunks": {LUMBRIDGE: {}, NORTH: {}}, "sections": {}},
    )
    ctx = Context(root=tmp_path, check_origin=False, derivations=ctx.derivations)

    job = _wait(ctx, _body(_post("/api/unlock", ctx, {"map": "fray", "chunk": NORTH}))["job"])

    assert job["state"] == "done", job.get("error")
    saved = job["result"]
    assert saved["chunk"] == NORTH
    assert saved["unlocked_chunks"] == 2
    envelope = cache.read_cache(saved["open"], tmp_path)
    assert envelope["kind"] == cache.UNLOCKED
    assert set(envelope["data"]["chunks"]["unlocked"]) == {LUMBRIDGE, NORTH}
    # One job, recorded on the run as well as the batch - see `batch.py`.
    assert cache.read_batch(saved["name"], tmp_path, kind=cache.UNLOCKED)["batch_id"]


def test_unlocking_a_chunk_you_already_hold_fails_the_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The preview refuses it too. Saving a copy of the map under a new name
    and calling it an unlock would be the worse answer of the two."""
    _write_map(tmp_path, "fray", [LUMBRIDGE])
    ctx = _derived_ctx(tmp_path, monkeypatch, {"chunks": {LUMBRIDGE: {}}, "sections": {}})
    ctx = Context(root=tmp_path, check_origin=False, derivations=ctx.derivations)

    job = _wait(ctx, _body(_post("/api/unlock", ctx, {"map": "fray", "chunk": LUMBRIDGE}))["job"])

    assert job["state"] == "failed"
    assert "already unlocked" in job["error"]
    assert not (tmp_path / "cache" / "maps" / cache.UNLOCKED).exists()


def test_an_unlock_against_a_missing_map_fails_the_post_not_the_job(tmp_path: Path) -> None:
    """Same rule `simulate` follows: a bad base map is answered immediately."""
    ctx = Context(root=tmp_path, check_origin=False)

    assert _post("/api/unlock", ctx, {"map": "nope", "chunk": NORTH}).status == (
        HTTPStatus.NOT_FOUND
    )


@pytest.mark.parametrize("payload", [{"chunk": NORTH}, {"map": "fray"}, {}])
def test_an_unlock_without_its_required_fields_is_a_400(
    tmp_path: Path, payload: dict[str, Any]
) -> None:
    ctx = Context(root=tmp_path, check_origin=False)
    assert _post("/api/unlock", ctx, payload).status == HTTPStatus.BAD_REQUEST


def test_the_panel_offers_both_halves_of_the_unlock(tmp_path: Path) -> None:
    """**Asking and taking are two verbs and the page carries both.**

    `GET /api/unlock` prices a candidate and keeps nothing; `POST /api/unlock`
    saves the world it was describing. The preview dialog is where you decide,
    so the save lives in its footer as well as on the chunk panel.
    """
    _, js, _ = _resources()

    assert 'id="do-unlock"' in js and 'id="preview-unlock"' in js
    assert "function askUnlock(" in js
    # It asks for a name before writing anything, and posts what it was given.
    body = re.search(r"function askUnlock\(.*?\n\}\n", js, re.DOTALL)
    assert body is not None
    assert 'getElementById("unlock-name")' in body.group(0)
    assert '"/api/unlock",' in body.group(0)


def _write_run(root: Path, batch: str, unlocked: list[str], rolls: list[str]) -> str:
    """A one-run computed batch: the payload it ended on, and how it got there.

    `unlocked` is the *final* set, `rolls` what the run added - which is the
    pair a timeline replays. Deliberately does not write the base map, since
    a run replaying without one is the property under test.
    """
    directory = cache.claim_batch(batch, root, kind=cache.SIMULATED)
    run = cache.run_dir(directory, 1)
    cache.write_sim_run(
        run,
        map_id=f"{directory.name}/{run.name}",
        data={"chunks": {"unlocked": {chunk: chunk for chunk in unlocked}}},
        simulation={"run": run.name, "batch": directory.name, "rolls": list(rolls)},
        ledger=[
            {
                "order": index,
                "chunk_id": chunk,
                "new_sections": {chunk: {"0": True}},
                "new_tasks": {"Slayer": {f"task-{chunk}": {}}},
                "new_unsupported": [],
                "bis_upgrades": {},
            }
            for index, chunk in enumerate(rolls, start=1)
        ],
    )
    return f"{directory.name}/{run.name}"


def test_a_timeline_replays_a_run_without_parsing_the_export(tmp_path: Path) -> None:
    """**The property that makes the slider usable.**

    Dragging it refetches a view per step, so a step that cost a 10MB parse
    or a `derive` would stutter. The ledger and the saved payload are the
    whole input - and the base map is deliberately absent here, because a run
    carries its own past.
    """
    ctx = Context(root=tmp_path)
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH, "12852"], [NORTH, "12852"])

    payload = _body(_get("/api/timeline", ctx, map=map_id))

    assert not ctx.derivations.loaded, "the timeline parsed the export"
    assert [row["step"] for row in payload["steps"]] == [0, 1, 2]
    assert [row["chunk"] for row in payload["steps"]] == [None, NORTH, "12852"]
    assert [row["unlocked_chunks"] for row in payload["steps"]] == [1, 2, 3]
    assert [row["tasks"] for row in payload["steps"]] == [0, 1, 1]
    # Nobody has paid for the hours, and that is not the same as zero hours.
    assert payload["has_hours"] is False
    assert all(row["hours"] is None for row in payload["steps"])


def test_a_view_can_be_rewound_to_a_step(tmp_path: Path) -> None:
    """Everything rolled so far is `added`, so the growth accumulates green
    against the world the run started from."""
    ctx = Context(root=tmp_path)
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH, "12852"], [NORTH, "12852"])

    at_zero = _body(_get("/api/view", ctx, map=map_id, step="0"))
    at_one = _body(_get("/api/view", ctx, map=map_id, step="1"))

    assert not ctx.derivations.loaded
    assert at_zero["counts"] == {"unlocked": 1, "added": 0, "removed": 0, "skipped": 0}
    assert at_one["counts"]["added"] == 1
    assert {cell["chunk_id"] for cell in at_one["cells"]} == {LUMBRIDGE, NORTH}
    assert at_one["step"] == 1


def test_a_step_outside_the_run_is_a_400_not_a_guess(tmp_path: Path) -> None:
    ctx = Context(root=tmp_path)
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH], [NORTH])

    assert _get("/api/view", ctx, map=map_id, step="9").status == HTTPStatus.BAD_REQUEST
    assert _get("/api/view", ctx, map=map_id, step="-1").status == HTTPStatus.BAD_REQUEST
    assert _get("/api/view", ctx, map=map_id, step="soon").status == HTTPStatus.BAD_REQUEST


def test_a_fetched_map_has_no_timeline(tmp_path: Path) -> None:
    """No ledger, so nothing to step through - and that is the test the page
    uses to decide whether the strip appears at all."""
    ctx = Context(root=tmp_path)
    _write_map(tmp_path, "fray", [LUMBRIDGE])

    assert _get("/api/timeline", ctx, map="fray").status == HTTPStatus.NOT_FOUND
    # A plain view of it is unaffected.
    assert _get("/api/view", ctx, map="fray").status == HTTPStatus.OK


def test_stored_hours_are_served_and_a_moved_world_discards_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**A stamp mismatch reads as absent, not as an error.**

    The numbers are recomputable, so offering to recompute beats refusing to
    draw. A moved export, tasks map, rate scrape or overrides file all count -
    the last because it is hand-edited and checked in, so it moves without any
    fetch having happened.
    """
    ctx = _derived_ctx(tmp_path, monkeypatch, {"chunks": {}, "sections": {}})
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH], [NORTH])
    from fray_claude.gui.server import _timeline_stamp

    stamp = _timeline_stamp(ctx, enriched=False)
    cache.write_timeline(map_id, {"stamp": stamp, "added": [0.0, 2.5], "totals": [10.0, 12.5]}, tmp_path)

    fresh = _body(_get("/api/timeline", ctx, map=map_id))
    assert fresh["has_hours"] is True
    assert [row["hours"] for row in fresh["steps"]] == [None, 2.5]
    assert [row["total_hours"] for row in fresh["steps"]] == [10.0, 12.5]

    cache.write_timeline(
        map_id, {"stamp": {**stamp, "rates": "moved"}, "added": [0.0, 2.5], "totals": [10.0, 12.5]}, tmp_path
    )
    stale = _body(_get("/api/timeline", ctx, map=map_id))

    assert stale["has_hours"] is False
    assert all(row["hours"] is None for row in stale["steps"])


def test_cheap_hours_are_not_stale_merely_because_dps_is_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**`enriched` is recorded and deliberately not compared.**

    A simulation prices its own rolls with the estimator alone, because the
    derivation is already in hand and costs nothing more; `dps_bridge.enrich`
    adds ~1.3s a roll and would have tripled every batch. So the cheap answer
    is what a run is born with. Treating it as *stale* once the extra is
    installed would blank a graph that is perfectly good - it is a coarser
    answer, not an out-of-date one, and worth showing until the better one
    exists.
    """
    ctx = _derived_ctx(tmp_path, monkeypatch, {"chunks": {}, "sections": {}})
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH], [NORTH])
    from fray_claude.gui.server import _timeline_stamp

    cache.write_timeline(
        map_id,
        {"stamp": _timeline_stamp(ctx, enriched=False), "added": [0.0, 2.5], "totals": [10.0, 12.5]},
        tmp_path,
    )
    monkeypatch.setattr("fray_claude.gui.server.dps_bridge.DPS_AVAILABLE", True)

    payload = _body(_get("/api/timeline", ctx, map=map_id))

    assert payload["has_hours"] is True, "the cheap numbers were thrown away"
    assert payload["enriched"] is False
    # And the page is told there is a better answer to be had.
    assert payload["can_enrich"] is True


def test_enriched_hours_leave_nothing_to_upgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The button costs a minute on a long run, so it goes once it would only
    rewrite the same numbers."""
    ctx = _derived_ctx(tmp_path, monkeypatch, {"chunks": {}, "sections": {}})
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH], [NORTH])
    from fray_claude.gui.server import _timeline_stamp

    cache.write_timeline(
        map_id,
        {"stamp": _timeline_stamp(ctx, enriched=True), "added": [0.0, 2.5], "totals": [10.0, 12.5]},
        tmp_path,
    )
    monkeypatch.setattr("fray_claude.gui.server.dps_bridge.DPS_AVAILABLE", True)

    payload = _body(_get("/api/timeline", ctx, map=map_id))

    assert payload["enriched"] is True and payload["can_enrich"] is False


def test_without_the_extra_there_is_nothing_better_to_offer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`can_enrich` is about whether a *better* answer exists, so on a machine
    without the extra it is false however the numbers were computed."""
    ctx = _derived_ctx(tmp_path, monkeypatch, {"chunks": {}, "sections": {}})
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH], [NORTH])
    from fray_claude.gui.server import _timeline_stamp

    cache.write_timeline(
        map_id,
        {"stamp": _timeline_stamp(ctx, enriched=False), "added": [0.0, 2.5], "totals": [10.0, 12.5]},
        tmp_path,
    )
    monkeypatch.setattr("fray_claude.gui.server.dps_bridge.DPS_AVAILABLE", False)

    payload = _body(_get("/api/timeline", ctx, map=map_id))

    assert payload["has_hours"] is True and payload["can_enrich"] is False


def test_a_totals_list_that_does_not_fit_the_run_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run re-rolled under the same name has a different number of steps.
    Drawing the old numbers against the new chunks would be silently wrong."""
    ctx = _derived_ctx(tmp_path, monkeypatch, {"chunks": {}, "sections": {}})
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH], [NORTH])
    from fray_claude.gui.server import _timeline_stamp

    cache.write_timeline(
        map_id,
        {"stamp": _timeline_stamp(ctx, enriched=False), "added": [1.0, 2.0, 3.0, 4.0], "totals": [1.0, 2.0, 3.0, 4.0]},
        tmp_path
    )

    assert _body(_get("/api/timeline", ctx, map=map_id))["has_hours"] is False


def test_a_timeline_post_without_a_map_is_a_400(tmp_path: Path) -> None:
    ctx = Context(root=tmp_path, check_origin=False)
    assert _post("/api/timeline", ctx, {}).status == HTTPStatus.BAD_REQUEST
    assert _post("/api/timeline", ctx, {"map": "nope"}).status == HTTPStatus.NOT_FOUND


def test_the_strip_appears_only_for_a_run() -> None:
    """The page asks `/api/timeline` and shows the strip on a 200.

    A fetched map 404s, which is the honest answer - there is no sequence -
    and the strip has to treat that as "nothing to show" rather than as an
    error, or every fetched map gets a red toast.
    """
    _, js, css = _resources()

    assert "/api/timeline" in js
    assert ".timeline" in css
    body = re.search(r"async function loadTimeline\(.*?\n\}\n", js, re.DOTALL)
    assert body is not None
    assert "catch" in body.group(0), "a map with no ledger must not surface as an error"


def test_the_bottom_edge_is_shared_rather_than_stacked() -> None:
    """**The attribution must not end up behind the timeline strip.**

    CC BY-NC-SA asks for the credit to be visible, so "it is under there
    somewhere" is not good enough. `--strip-h` is what the bottom-anchored
    elements clear, and it is 0 whenever the strip is absent - so there is one
    rule rather than one per state. The legend moved to the top to make room,
    which is the other half of the same decision.
    """
    _, js, css = _resources()

    attribution = re.search(r"\.attribution \{(.*?)\}", css, re.DOTALL)
    assert attribution is not None
    assert "var(--strip-h)" in attribution.group(1), "the attribution ignores the strip"

    legend = re.search(r"\.legend \{(.*?)\}", css, re.DOTALL)
    assert legend is not None
    assert "top:" in legend.group(1) and "bottom:" not in legend.group(1)

    # The page is what knows how tall the strip actually is.
    assert '--strip-h' in js


def test_a_step_and_a_comparison_are_exclusive() -> None:
    """Two maps and a rewind would need a third colour for "gained by this
    roll but lost against the other side", which is nobody's question. The
    step wins in the query, and the strip hides itself while comparing."""
    _, js, _ = _resources()

    query = re.search(r"function mapQuery\(\) \{(.*?)\n\}", js, re.DOTALL)
    assert query is not None
    assert 'params.set("step"' in query.group(1)
    assert "else if (el.compare.value)" in query.group(1)

    load = re.search(r"async function loadTimeline\(\) \{(.*?)\n\}", js, re.DOTALL)
    assert load is not None
    assert "el.compare.value" in load.group(1)


def test_switching_map_forgets_the_step() -> None:
    """A step index belongs to one run. Carried across, it rewinds the new map
    to a roll it never had - and the counts quietly disagree with the slider."""
    _, js, _ = _resources()

    handler = re.search(
        r'el\.map\.addEventListener\("change".*?\n\}\);', js, re.DOTALL
    )
    assert handler is not None
    assert "state.step = null" in handler.group(0)
    assert "state.timeline = null" in handler.group(0)


def test_an_uncomputed_hours_series_is_not_drawn_as_zero() -> None:
    """**"Not computed" and "added no work" are different answers**, and both
    are common - eight of ten steps of a real run add exactly 0.0h. Drawing
    them the same would make a graph nobody could read."""
    _, js, _ = _resources()

    bars = re.search(r"function tlBars\(.*?\n\}\n", js, re.DOTALL)
    assert bars is not None
    # A null draws no bar at all; a zero still gets one, at a floor height.
    assert "value !== null && value !== undefined" in bars.group(0)
    assert "Math.max(1.5," in bars.group(0)
    # And the axis says so outright when nothing has been priced.
    assert "Compute hours" in bars.group(0)


def test_the_axis_only_reserves_room_for_negatives_when_there_are_some() -> None:
    """Tasks are never negative and hours usually are not, so a permanently
    centred zero line spent half the strip on empty space and halved the
    resolution of the bars actually there."""
    _, js, _ = _resources()

    bars = re.search(r"function tlBars\(.*?\n\}\n", js, re.DOTALL)
    assert bars is not None
    assert "known.some((v) => v < 0)" in bars.group(0)
    assert "down ? H * 0.62 : H - FOOT" in bars.group(0)


def test_the_legend_keys_off_the_counts_not_the_compared_map() -> None:
    """**A rewound run has green squares and no compared map.** Gating on the
    map left the chunks a run had rolled in a colour the legend never
    explained."""
    _, js, _ = _resources()

    legend = re.search(r"function renderLegend\(\) \{(.*?)\n\}", js, re.DOTALL)
    assert legend is not None
    assert "counts.added" in legend.group(1) and "counts.removed" in legend.group(1)
    # The expression, not the prose - the comment above it says the word too.
    assert "view.compare_map_id" not in legend.group(1)


def test_a_multi_run_batch_is_a_label_not_a_choice() -> None:
    """**Selecting one blanks the map**, and did before the timeline existed.

    `cache.resolve_map_path` refuses to guess which run a bare batch name
    means - picking one silently would make the same name describe a different
    world as runs were added - so it 404s `/api/view`, `/api/summary` and
    everything else. The picker offering it as a map was the bug.
    """
    _, js, _ = _resources()

    body = re.search(r"function mapOptions\(maps\) \{(.*?)\n\}", js, re.DOTALL)
    assert body is not None
    assert "<optgroup" in body.group(1)
    assert "m.runs > 1" in body.group(1)
    # A run belongs to its group, not to the top level as well.
    assert 'm.map_id.includes("/")' in body.group(1)


def test_rolling_opens_the_result_as_the_map(tmp_path: Path) -> None:
    """**It used to land in the compare slot, which is what hides the strip** -
    so rolling a simulation hid the one thing you rolled it to see."""
    _, js, _ = _resources()

    handler = re.search(r'runAction\(`Simulate \$\{rolls\} rolls`.*?\n    \};', js, re.DOTALL)
    assert handler is not None
    assert "el.map.value = result.open" in handler.group(0)
    assert 'el.compare.value = ""' in handler.group(0)
    assert "loadTimeline()" in handler.group(0)


def test_the_timeline_job_reports_slices_for_the_bar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**`k/N` is not decoration** - `app.js`'s `countsIn` parses exactly that
    into a real bar, and anything else leaves it indeterminate. The count is of
    slices, because a worker cannot report from inside one."""
    ctx = _derived_ctx(tmp_path, monkeypatch, {"chunks": {}, "sections": {}})
    ctx = Context(root=tmp_path, check_origin=False, derivations=ctx.derivations)
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH], [NORTH])
    seen: list[str] = []

    def fake(**kw: Any) -> tuple[list[float], list[float]]:
        report = kw["on_progress"]
        report(1, 2)
        report(2, 2)
        return [0.0, 1.0], [1.0, 2.0]

    monkeypatch.setattr("fray_claude.gui.server.price_steps", fake)
    monkeypatch.setattr(
        "fray_claude.gui.jobs.JobRegistry.submit",
        lambda self, action, work: _capture(self, action, work, seen),
    )

    _post("/api/timeline", ctx, {"map": map_id, "jobs": 2})

    assert any(re.fullmatch(r"\d+/\d+ slices - \d+ workers", line) for line in seen), seen


def _capture(registry: Any, action: str, work: Any, seen: list[str]) -> Any:
    """Run a job inline and keep every progress line it emitted."""
    work(seen.append, lambda: False)

    class _Job:
        id = "inline"

    return _Job()


def test_the_timeline_job_passes_jobs_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Omitted means auto, and auto is `price_steps`' call to make - the server
    must not resolve it to a number and hard-code today's core count into a
    stored answer."""
    ctx = _derived_ctx(tmp_path, monkeypatch, {"chunks": {}, "sections": {}})
    ctx = Context(root=tmp_path, check_origin=False, derivations=ctx.derivations)
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH], [NORTH])
    asked: list[int] = []

    def fake(**kw: Any) -> tuple[list[float], list[float]]:
        asked.append(kw["jobs"])
        return [0.0, 1.0], [1.0, 2.0]

    monkeypatch.setattr("fray_claude.gui.server.price_steps", fake)

    _wait(ctx, _body(_post("/api/timeline", ctx, {"map": map_id, "jobs": 4}))["job"])
    _wait(ctx, _body(_post("/api/timeline", ctx, {"map": map_id}))["job"])

    assert asked == [4, 0]


def test_a_timeline_written_under_the_old_meaning_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**A file with `totals` and no `added` predates the semantics change.**

    The bars used to be a delta of the totals and are now what each roll cost,
    which is a different number computed a different way. Reading an old file
    would draw perfectly plausible bars under a meaning nobody computed them
    for - the worst kind of wrong, because nothing looks broken.
    """
    ctx = _derived_ctx(tmp_path, monkeypatch, {"chunks": {}, "sections": {}})
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH], [NORTH])
    from fray_claude.gui.server import _timeline_stamp

    cache.write_timeline(
        map_id, {"stamp": _timeline_stamp(ctx, enriched=False), "totals": [10.0, 12.5]}, tmp_path
    )

    payload = _body(_get("/api/timeline", ctx, map=map_id))

    assert payload["has_hours"] is False
    assert all(row["hours"] is None for row in payload["steps"])


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


def test_refreshing_the_rates_runs_the_same_scrape_the_cli_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**One scraper, two callers.** `fray heuristics` and this button must
    write the same file; an eighteen-step sequence kept in two places would
    not stay the same for long. So this asserts the wiring - that the button
    reaches `scrape.scrape` - rather than re-testing the scrape."""
    ctx = _derived_ctx(tmp_path, monkeypatch, {"chunks": {}, "sections": {}})
    ctx = Context(root=tmp_path, check_origin=False, derivations=ctx.derivations)
    from fray_claude.scrape import ScrapeResult

    monkeypatch.setattr(
        "fray_claude.gui.server.scrape",
        lambda info, timeout=0.0, progress=None: ScrapeResult(
            config={"quests": {"Cook's Assistant": 5}},
            coverage={"quests": (1, 1)},
            sources={"quest pages": (1, 1)},
        ),
    )

    job = _wait(ctx, _body(_post("/api/refresh", ctx, {"what": "heuristics"}))["job"])

    assert job["state"] == "done", job.get("error")
    assert job["result"]["refreshed"] == "heuristics"
    # Read off disk, not through `cache.read_blob`: `_derived_ctx` patches that
    # on the shared module, so it would answer with the fixture's stub.
    written = json.loads(cache.blob_path(cache.WIKI_RATES_BLOB_NAME, tmp_path).read_text())
    assert written["data"] == {"quests": {"Cook's Assistant": 5}}


def test_the_page_fetches_the_rates_once_when_they_are_missing() -> None:
    """**Without them every hour in the Estimate tab is a default**, and the
    panel would say so in small print beside a confident-looking number.
    Eighteen requests is a fair price for that not being the first
    impression - but only when missing, never on a schedule."""
    _, js, _ = _resources()

    body = re.search(r"async function warmReference\(\) \{(.*?)\n\}", js, re.DOTALL)
    assert body is not None
    assert "!rates.cached" in body.group(1), "it must only fire when they are absent"
    # The 10MB export is deliberately not fetched on open.
    assert "chunkinfo" not in body.group(1)
    assert "warmReference();" in js


def test_cancelling_is_a_request_and_leaves_the_job_running(tmp_path: Path) -> None:
    """**A request, not a kill.** The work stops where it safely can - a
    simulation finishes the roll it is on - so the job is still `running`
    when the cancel answers, and the page has to keep polling rather than
    assume it is over."""
    ctx = Context(root=tmp_path, check_origin=False)
    started, release = threading.Event(), threading.Event()

    def work(progress: Any, stop: Any) -> dict[str, Any]:
        started.set()
        while not stop():
            if release.wait(timeout=0.01):
                break
        return {"stopped": stop()}

    job = ctx.jobs.submit("simulate", work)
    started.wait(timeout=5)

    reply = _body(_post("/api/cancel", ctx, {"job": job.id}))

    assert reply["state"] == "running", "it must not claim to have stopped already"
    assert reply["stopping"] is True
    finished = _wait(ctx, job.id)
    # Stopped on purpose is its own state: a page that coloured this like a
    # crash would be calling the user's own click a failure.
    assert finished["state"] == "cancelled"
    assert finished["error"] is None
    assert finished["result"] == {"stopped": True}


def test_cancelling_a_finished_job_is_not_an_error(tmp_path: Path) -> None:
    """The button and the last poll race, and "it had already finished" needs
    no handling by anyone."""
    ctx = Context(root=tmp_path, check_origin=False)
    job = ctx.jobs.submit("fetch", lambda _p, _s: {"done": True})
    _wait(ctx, job.id)

    reply = _body(_post("/api/cancel", ctx, {"job": job.id}))

    assert reply["state"] == "done"
    assert reply["stopping"] is False


def test_cancelling_an_unknown_job_is_a_404(tmp_path: Path) -> None:
    ctx = Context(root=tmp_path, check_origin=False)

    assert _post("/api/cancel", ctx, {"job": "nope"}).status == HTTPStatus.NOT_FOUND
    assert _post("/api/cancel", ctx, {}).status == HTTPStatus.BAD_REQUEST


def test_simulate_progress_counts_rolls_not_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**`2/3 runs` on a 3x100 job is three updates across four minutes.**
    The bar should count the thing that takes the time, and `countsIn` reads
    `k/N` either way."""
    seen: list[str] = []

    def fake(**kw: Any) -> Any:
        roll = kw["on_roll"]
        for run in range(kw["runs"]):
            for order in range(1, kw["rolls"] + 1):
                roll(run, order, "12850")
        return _FakeBatch(kw["name"], kw["runs"], kw["on_complete"])

    monkeypatch.setattr("fray_claude.gui.server.run_batch", fake)
    monkeypatch.setattr(
        "fray_claude.gui.jobs.JobRegistry.submit",
        lambda self, action, work: _capture(self, action, work, seen),
    )
    ctx = Context(root=tmp_path, check_origin=False)
    _write_map(tmp_path, "fray", [LUMBRIDGE])

    _post("/api/simulate", ctx, {"map": "fray", "name": "sim", "rolls": 4, "runs": 3})

    assert seen[0] == "0/12 rolls"
    assert seen[-1].startswith("12/12 rolls")
    assert not any("runs" in line for line in seen), seen


def test_the_progress_card_can_stop_a_job() -> None:
    """The control only appears while something is running that can stop, and
    it hides itself once asked - a button that stays lit after you press it
    reads as not having worked."""
    html, js, css = _resources()

    assert 'id="progress-cancel"' in html
    assert '"/api/cancel"' in js
    # Shown per job id, not unconditionally.
    assert 'el["progress-cancel"].hidden = !job' in js
    # Stopped is its own colour, not the loss one.
    assert ".progress.stopped" in css
    assert 'job.state === "cancelled"' in js


def test_a_bar_does_not_swallow_its_own_hover() -> None:
    """**The bars are drawn over the hit areas.** Without `pointer-events:
    none` the tooltip appeared on the empty background either side of a
    column but not on the column itself - hovering the very thing you are
    aiming at did nothing."""
    _, _, css = _resources()

    rule = re.search(r"\.tl-bar[^{]*\{([^}]*pointer-events[^}]*)\}", css)
    assert rule is not None, "the bars still take the pointer"
    assert "none" in rule.group(1)


def test_the_roll_tooltip_counts_rolls_not_the_whole_world() -> None:
    """`unlocked_chunks` counts the base map too, so the first roll of a
    simulation from a 106-chunk map read "106 chunks after this roll" - true,
    and not what a timeline is about."""
    _, js, _ = _resources()

    body = re.search(r"function tlTip\(.*?\n\}\n", js, re.DOTALL)
    assert body is not None
    assert "chunks rolled so far" in body.group(0)
    # The expression, not the prose - the comment above it explains why the
    # old field is wrong and so necessarily names it.
    assert "row.unlocked_chunks" not in body.group(0)


def test_a_roll_serves_the_task_names_a_step_summary_leaves_out(tmp_path: Path) -> None:
    """**One roll of the real export opened 239 tasks**, so `/api/timeline`
    carries counts and this carries names - the same ledger read, one step at
    a time and only when somebody asks to see it."""
    ctx = Context(root=tmp_path)
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH], [NORTH])

    payload = _body(_get("/api/roll", ctx, map=map_id, step="1"))

    assert not ctx.derivations.loaded, "reading one roll parsed the export"
    assert payload["chunk"] == NORTH
    assert payload["tasks_by_skill_names"] == {"Slayer": [f"task-{NORTH}"]}
    # The counts still agree with what the timeline said.
    assert payload["tasks"] == 1


def test_a_roll_outside_the_run_is_a_400(tmp_path: Path) -> None:
    ctx = Context(root=tmp_path)
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH], [NORTH])

    assert _get("/api/roll", ctx, map=map_id, step="9").status == HTTPStatus.BAD_REQUEST
    assert _get("/api/roll", ctx, map=map_id, step="x").status == HTTPStatus.BAD_REQUEST
    assert _get("/api/roll", ctx, map=map_id).status == HTTPStatus.BAD_REQUEST


def test_clicking_a_column_frames_the_chunk_and_details_is_separate() -> None:
    """**They cannot be the same gesture**: a dialog would cover the map it
    had just framed. Click takes you to the roll - slider, selection, camera -
    and the breakdown is its own control."""
    html, js, _ = _resources()

    assert 'id="tl-details"' in html
    body = re.search(r"async function goToRoll\(step\) \{(.*?)\n\}", js, re.DOTALL)
    assert body is not None
    assert "setStep(step)" in body.group(1)
    assert "selectChunk(" in body.group(1) and "focusChunk(" in body.group(1)
    # The overlay is opened by the button, not by the column.
    assert "slot.onclick = () => goToRoll(" in js
    assert 'el["tl-details"].addEventListener' in js


def test_a_deep_link_to_a_run_falls_back_to_its_batch() -> None:
    """A one-run batch is offered under its bare name, so `?map=t/run-001` is
    a valid map id with no option to match - and a `<select>` handed one it
    does not have blanks silently, landing you on whatever was first."""
    _, js, _ = _resources()

    body = re.search(r"async function loadMaps\(\) \{(.*?)\n\}", js, re.DOTALL)
    assert body is not None
    assert '.split("/")[0]' in body.group(1)
