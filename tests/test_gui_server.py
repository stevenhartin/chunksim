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


def test_the_world_map_is_served_with_an_etag(tmp_path: Path) -> None:
    cache.write_asset(cache.WORLD_MAP_ASSET, b"\x89PNG fake", root=tmp_path)
    ctx = Context(root=tmp_path)

    response = _get("/world_map.png", ctx)

    assert response.status == HTTPStatus.OK
    assert response.content_type == "image/png"
    assert response.body == b"\x89PNG fake"
    assert response.headers["ETag"]


def test_a_matching_etag_is_a_304_with_no_body(tmp_path: Path) -> None:
    """8.4MiB is worth a conditional request; without one every reload
    re-sends an image that changes only when upstream re-renders the world."""
    cache.write_asset(cache.WORLD_MAP_ASSET, b"\x89PNG fake", root=tmp_path)
    ctx = Context(root=tmp_path)
    etag = _get("/world_map.png", ctx).headers["ETag"]

    response = handle_request("GET", "/world_map.png", {}, ctx, if_none_match=etag)

    assert response.status == HTTPStatus.NOT_MODIFIED
    assert response.body == b""


def test_a_missing_world_map_says_how_to_get_one(tmp_path: Path) -> None:
    response = _get("/world_map.png", Context(root=tmp_path))

    assert response.status == HTTPStatus.NOT_FOUND
    assert "FRAY_WORLD_MAP" in _body(response)["error"]


def test_the_world_map_override_is_honoured(tmp_path: Path) -> None:
    local = tmp_path / "elsewhere.png"
    local.write_bytes(b"\x89PNG local")

    response = _get("/world_map.png", Context(root=tmp_path, world_map=local))

    assert response.body == b"\x89PNG local"


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
    from fray_claude.gui.worldmap import MAX_REGION_Y, MIN_REGION_X

    source = _app_js()
    assert re.search(rf"const regionX = gx \+ {MIN_REGION_X};", source)
    assert re.search(rf"const regionY = {MAX_REGION_Y} - gy;", source)


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
