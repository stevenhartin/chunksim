"""Tests for `gui/server.py`: dispatch, the static allowlist, and the two origin checks.

`handle_request` is pure - strings in, a `Response` out - so every test
here exercises the real routing without binding a socket.
"""

from __future__ import annotations

import re
from http import HTTPStatus
from pathlib import Path

import pytest

from chunksim.store import cache
from chunksim.gui.browser import window_flags
from chunksim.gui.server import (
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


def test_an_unknown_route_is_a_404(ctx: Context) -> None:
    assert _get("/api/nope", ctx).status == HTTPStatus.NOT_FOUND
    assert _get("/nope", ctx).status == HTTPStatus.NOT_FOUND


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


def test_the_world_map_route_is_gone(tmp_path: Path) -> None:
    """It used to serve Jagex's image off loopback. Nothing serves imagery now."""
    assert _get("/world_map", Context(root=tmp_path)).status == HTTPStatus.NOT_FOUND
    assert _get("/world_map.png", Context(root=tmp_path)).status == HTTPStatus.NOT_FOUND


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
    from chunksim.gui.http import RESOURCE_DIR

    css = (RESOURCE_DIR / "style.css").read_text(encoding="utf-8")
    canvas_rule = re.search(r"#canvas\s*\{(.*?)\}", css, re.DOTALL)

    assert canvas_rule is not None
    body = canvas_rule.group(1)
    assert re.search(r"\bwidth:\s*100%", body)
    assert re.search(r"\bheight:\s*100%", body)


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
        "chunksim.gui.server.fetch_skill_icon", lambda skill, timeout=0.0: b"icon"
    )

    response = _get("/assets/skill/Attack.png", Context(root=tmp_path))

    assert response.status == HTTPStatus.OK
    assert cache.skill_icon_path("Attack", tmp_path).read_bytes() == b"icon"


def test_a_first_run_opens_maximised(tmp_path: Path) -> None:
    """Not fullscreen: closing the window is how you stop the server, and
    fullscreen hides the control that does it."""
    assert window_flags(cache.read_gui_window(tmp_path)) == ["--start-maximized"]
