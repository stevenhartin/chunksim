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
import time
from http import HTTPStatus
from pathlib import Path
from typing import Any

import pytest

from fray_claude import cache
from fray_claude.api import FetchError
from fray_claude.gui.browser import window_flags
from fray_claude.gui.server import Context, Response, handle_request

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
    monkeypatch.setattr(
        "fray_claude.gui.derivation.cache.chunkinfo_source", lambda o, r: Path("x")
    )
    monkeypatch.setattr("fray_claude.gui.derivation.cache.blob_path", lambda n, r: Path("y"))
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
