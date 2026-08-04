"""The local HTTP server behind `fray-gui`, and the routing it does.

**`handle_request` is a pure function and the `BaseHTTPRequestHandler` below is
a thin adapter over it.** That is the whole structural decision here: routing,
error mapping and every response body are decided by a function taking strings
and returning a `Response`, so `tests/test_gui_server.py` exercises the entire
surface without binding a socket. The repo's rule that no test touches the
network then holds in letter as well as in spirit - loopback is still a socket,
still a port to collide on, still a thing a sandbox can refuse.

**This module accepts inbound connections, which no other module in the project
does.** `api.py` remains the only module making *outbound* calls; the two rules
are about opposite directions and do not conflict. It binds `127.0.0.1` unless
told otherwise, and reads maps only through `cache.read_cache`.

**A request is milliseconds, so there is no cache to invalidate.** Rendering
needs `payload["chunks"]["unlocked"]` and nothing else - no `ChunkInfo` parse
(~1s), no `derive` (~0.15s warm), because a chunk's square is fixed by its id.
Every request therefore re-reads the map file, and a `fray fetch` or
`fray simulate` in another terminal shows up on the next poll with no
invalidation machinery and no restart. `/api/revision` is a `stat`, so polling
it twice a second costs nothing.

**The delta is a set difference, not `delta.compare_maps`.** That function
derives *both* sides unconditionally - the two `derive_with(...)` calls are
arguments to `compare`, so passing `branches={"chunks"}` narrows the comparison
and not the work - which would spend ~2s to answer something
`delta.diff_names` answers in microseconds. `compare_maps` becomes the right
call the day an overlay is keyed on a derived branch; it is the wrong one for
chunks.

**Path traversal is closed by construction rather than by sanitising.** Static
files come from a fixed allowlist, so no user-supplied string is ever joined
onto a path. Map ids need no checking here either, because `cache.split_map_id`
already rejects anything that is not a plain name or a `<name>/run-<n>` pair -
and a second, weaker check in this module is exactly how two guards drift
apart. `tests/test_gui_server.py` pins that reliance so it cannot be quietly
removed.

Manual checks this cannot make, since none of it is reachable from Python:

- zoom stays anchored under the cursor at both ends of the clamp;
- no seam appears between two adjacent unlocked chunks at any zoom;
- a drag released off-canvas does not strand the pointer;
- Lumbridge's square lands on Lumbridge.
"""

from __future__ import annotations

import json
import os
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import cached_property
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from fray_claude import cache
from fray_claude.api import DEFAULT_TIMEOUT, fetch_map
from fray_claude.batch import RunResult, run_batch
from fray_claude.delta import diff_names
from fray_claude.gui.jobs import JobRegistry, Progress, as_int
from fray_claude.gui.worldmap import MapView, build_view

#: The port `fray-gui` binds unless told otherwise. Arbitrary, and high enough
#: to need no privileges.
DEFAULT_PORT = 8731
DEFAULT_HOST = "127.0.0.1"

#: Text assets that ship inside the package. The world map is *not* here - it
#: is fetched to `cache/assets/` because it is Jagex's artwork; see
#: `api.WORLD_MAP_URL`.
RESOURCE_DIR = Path(__file__).resolve().parent / "resources"

#: **The whole static surface, as a fixed allowlist.** Four entries, matched by
#: equality, so nothing a caller sends is ever joined onto a path and traversal
#: has nowhere to happen. If this ever becomes a glob, the replacement needs
#: `resolve().is_relative_to(RESOURCE_DIR)` *after* unquoting - which is the
#: bug this shape exists to avoid.
_STATIC: dict[str, tuple[str, str]] = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/static/style.css": ("style.css", "text/css; charset=utf-8"),
}

_JSON = "application/json; charset=utf-8"


@dataclass(frozen=True)
class Response:
    """One HTTP response, decided before any socket is involved."""

    status: int
    content_type: str
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Context:
    """What a request is answered against.

    `root` is the cache root, so a test can point the whole server at a
    `tmp_path` the way every other cache-touching test does.
    """

    root: Path | None = None
    resources: Path = RESOURCE_DIR
    world_map: Path | None = None
    jobs: JobRegistry = field(default_factory=JobRegistry)
    #: Whether the browser-origin checks apply. Off in tests, which have no
    #: browser to send the headers this asserts on.
    check_origin: bool = True

    @cached_property
    def world_map_path(self) -> Path:
        """The PNG to serve. Override, `FRAY_WORLD_MAP`, then the cache."""
        return cache.world_map_source(self.world_map, self.root)


def _json(payload: Any, status: int = HTTPStatus.OK) -> Response:
    body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    return Response(status=status, content_type=_JSON, body=body)


def _error(message: str, status: int) -> Response:
    return _json({"error": message}, status)


def _unlocked(map_id: str, ctx: Context) -> tuple[dict[str, Any], int]:
    """One map's unlocked set and the mtime that dates it.

    The mtime is the live-reload token. It is deliberately not a hash of the
    payload: a `stat` is cheaper than a read, and the cost of a false positive
    is one redraw the user cannot see.
    """
    path = cache.resolve_map_path(map_id, ctx.root)
    envelope = cache.read_cache(map_id, ctx.root)
    chunks = envelope.get("data", {}).get("chunks", {})
    unlocked = chunks.get("unlocked") if isinstance(chunks, dict) else None
    revision = path.stat().st_mtime_ns
    return (unlocked if isinstance(unlocked, dict) else {}), revision


def build_map_view(map_id: str, compare: str | None, ctx: Context) -> MapView:
    """The payload for one map, or for one map against another.

    `map_id` is the base and `compare` the other side, so `added` is what
    `compare` has and the base does not. That matches
    `fray diff --map1 <base> --map2 <compare> chunks` exactly.
    """
    base, revision = _unlocked(map_id, ctx)
    if compare is None:
        return build_view(map_id=map_id, unlocked=base, revision=revision)

    other, other_revision = _unlocked(compare, ctx)
    branch = diff_names(base, other)
    return build_view(
        map_id=map_id,
        unlocked=base,
        added=branch.added,
        removed=branch.removed,
        compare_map_id=compare,
        # Either side changing has to invalidate the view, so the token spans
        # both. Summing is enough - it moves whenever either mtime does.
        revision=revision + other_revision,
    )


def _first(query: Mapping[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    if not values:
        return None
    value = values[0].strip()
    return value or None


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


def _world_map(ctx: Context, if_none_match: str | None) -> Response:
    """The map image, with an `ETag` so it is fetched over the wire once.

    8.4MiB is worth a conditional request: without one, every reload spends it
    again on an image that changes only when upstream re-renders the world.
    """
    path = ctx.world_map_path
    try:
        stat = path.stat()
    except FileNotFoundError:
        return _error(
            f"world map not cached at {path}; it is downloaded on first run, "
            "or point FRAY_WORLD_MAP at a local copy",
            HTTPStatus.NOT_FOUND,
        )

    etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
    if if_none_match == etag:
        return Response(
            status=HTTPStatus.NOT_MODIFIED,
            content_type="image/png",
            body=b"",
            headers={"ETag": etag},
        )
    return Response(
        status=HTTPStatus.OK,
        content_type="image/png",
        body=path.read_bytes(),
        headers={"ETag": etag, "Cache-Control": "no-cache"},
    )


def _fetch_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    map_id = str(payload.get("map") or "").strip()
    if not map_id:
        raise ValueError("missing 'map'")

    def work(progress: Progress) -> dict[str, Any]:
        progress(f"fetching {map_id}")
        data = fetch_map(map_id, timeout=DEFAULT_TIMEOUT)
        path = cache.write_cache(map_id, data, ctx.root)
        unlocked = data.get("chunks", {}).get("unlocked", {})
        return {"map": map_id, "path": str(path), "unlocked_chunks": len(unlocked)}

    return {"job": ctx.jobs.submit("fetch", work).id}


def _simulate_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    map_id = str(payload.get("map") or "").strip()
    name = str(payload.get("name") or "").strip()
    if not map_id:
        raise ValueError("missing 'map'")
    if not name:
        raise ValueError("missing 'name' for the simulated map")
    rolls = as_int(payload, "rolls", 1)
    runs = as_int(payload, "runs", 1)
    jobs = as_int(payload, "jobs", 1)
    seed_raw = payload.get("seed")
    seed = None if seed_raw in (None, "") else as_int({"s": seed_raw}, "s", 0) or None

    # Read the base map now, so a bad id fails the POST rather than a job.
    envelope = cache.read_cache(map_id, ctx.root)

    def work(progress: Progress) -> dict[str, Any]:
        done = 0

        def report(result: RunResult) -> None:
            nonlocal done
            done += 1
            progress(f"{done}/{runs} runs - {result.name} -> {result.unlocked_chunks} chunks")

        progress(f"0/{runs} runs")
        batch = run_batch(
            name=name,
            payload=envelope["data"],
            base_map=map_id,
            base_fetched_at=envelope.get("fetched_at"),
            rolls=rolls,
            runs=runs,
            jobs=jobs,
            seed=seed,
            root=ctx.root,
            on_complete=report,
        )
        return {
            "batch": batch.name,
            "runs": len(batch.runs),
            # What to put in the map picker afterwards, resolved the way
            # `cache.read_cache` resolves a bare batch name.
            "open": batch.name if len(batch.runs) == 1 else f"{batch.name}/{batch.runs[0].name}",
        }

    return {"job": ctx.jobs.submit("simulate", work).id}


_ACTIONS: dict[str, Callable[[Mapping[str, Any], Context], dict[str, Any]]] = {
    "/api/fetch": _fetch_job,
    "/api/simulate": _simulate_job,
}


def _origin_ok(headers: Mapping[str, str]) -> str | None:
    """Why this POST should be refused, or `None` if it is fine.

    **A loopback bind stops other machines, not other tabs.** Any page you have
    open can POST to 127.0.0.1 and the browser will send it - cross-site
    request forgery. It cannot read the reply, so the exposure here is
    nuisance-grade: burn CPU on a simulation, write junk into `cache/sims/`.
    Two header checks close it for nothing:

    - `Sec-Fetch-Site` must be `same-origin`. Every current browser sends it,
      and a cross-site POST is exactly what it reports.
    - `Host` must be loopback, which closes DNS rebinding - a hostile domain
      resolving to 127.0.0.1 so that its page's origin *is* this server.

    Deliberately no per-launch token: it would put a secret in the URL and
    break bookmarking to buy little more than this. `--host` exposing the
    server beyond loopback is the case where one starts earning its keep, and
    that flag's help text says so.
    """
    site = headers.get("Sec-Fetch-Site")
    if site is not None and site != "same-origin":
        return f"cross-site request refused (Sec-Fetch-Site: {site})"
    host = (headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
    if host and host not in ("localhost", "127.0.0.1", "::1"):
        return f"unexpected Host header {host!r}"
    return None


def handle_request(
    method: str,
    path: str,
    query: Mapping[str, list[str]],
    ctx: Context,
    *,
    if_none_match: str | None = None,
    body: bytes = b"",
    headers: Mapping[str, str] | None = None,
) -> Response:
    """Route one request. Pure: strings in, a `Response` out."""
    if method == "POST":
        return _handle_post(path, body, headers or {}, ctx)
    if method not in ("GET", "HEAD"):
        return _error(f"{method} is not supported", HTTPStatus.METHOD_NOT_ALLOWED)

    static = _static(path, ctx)
    if static is not None:
        return static

    if path == "/world_map.png":
        return _world_map(ctx, if_none_match)

    try:
        if path == "/api/maps":
            return _json([entry.as_dict() for entry in cache.list_maps(ctx.root, expand_runs=True)])

        if path == "/api/jobs":
            return _json([job.as_dict() for job in ctx.jobs.recent()])

        if path.startswith("/api/jobs/"):
            job = ctx.jobs.get(path.removeprefix("/api/jobs/"))
            if job is None:
                return _error("no such job", HTTPStatus.NOT_FOUND)
            return _json(job.as_dict())

        if path in ("/api/view", "/api/revision"):
            map_id = _first(query, "map")
            if map_id is None:
                return _error("missing required parameter 'map'", HTTPStatus.BAD_REQUEST)
            compare = _first(query, "compare")
            view = build_map_view(map_id, compare, ctx)
            if path == "/api/revision":
                return _json({"revision": view.revision})
            return _json(view.as_dict())
    except cache.CacheMissError as exc:
        # The message already names the command that would fix it, which is
        # exactly what the browser should show.
        return _error(str(exc), HTTPStatus.NOT_FOUND)

    return _error(f"no route for {path!r}", HTTPStatus.NOT_FOUND)


def _handle_post(
    path: str, body: bytes, headers: Mapping[str, str], ctx: Context
) -> Response:
    action = _ACTIONS.get(path)
    if action is None:
        return _error(f"no route for {path!r}", HTTPStatus.NOT_FOUND)

    if ctx.check_origin:
        refusal = _origin_ok(headers)
        if refusal is not None:
            return _error(refusal, HTTPStatus.FORBIDDEN)

    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError as exc:
        return _error(f"malformed JSON body: {exc}", HTTPStatus.BAD_REQUEST)
    if not isinstance(payload, dict):
        return _error("expected a JSON object", HTTPStatus.BAD_REQUEST)

    try:
        return _json(action(payload, ctx), HTTPStatus.ACCEPTED)
    except ValueError as exc:
        return _error(str(exc), HTTPStatus.BAD_REQUEST)
    except cache.CacheMissError as exc:
        return _error(str(exc), HTTPStatus.NOT_FOUND)


class MapServer(ThreadingHTTPServer):
    """A threading server carrying the `Context` its handler answers against.

    Threading is not decoration: the 8.4MiB image occupies a connection for a
    moment, and a single-threaded server would stall `/api/view` behind it.

    Subclassed rather than passing the context through `functools.partial`
    because the stub types `RequestHandlerClass` as `type[BaseRequestHandler]`,
    so a partial needs an ignore where an attribute needs one `cast`.
    """

    daemon_threads = True

    def __init__(self, address: tuple[str, int], context: Context) -> None:
        self.context = context
        super().__init__(address, MapHandler)


class MapHandler(BaseHTTPRequestHandler):
    """The adapter. Everything it decides, `handle_request` decided first."""

    server_version = "fray-gui"
    #: Suppresses the `Python/3.14` half of the `Server:` header. The version
    #: of an interpreter is not something a local tool should announce.
    sys_version = ""

    def do_GET(self) -> None:  # noqa: N802 - the stdlib's spelling
        self._respond()

    def do_POST(self) -> None:  # noqa: N802 - the stdlib's spelling
        length = int(self.headers.get("Content-Length") or 0)
        self._respond(body_in=self.rfile.read(length) if length else b"")

    def do_HEAD(self) -> None:  # noqa: N802 - the stdlib's spelling
        self._respond(body=False)

    def _respond(self, *, body: bool = True, body_in: bytes = b"") -> None:
        parts = urlsplit(self.path)
        context = cast(MapServer, self.server).context
        try:
            response = handle_request(
                self.command or "GET",
                parts.path,
                parse_qs(parts.query),
                context,
                if_none_match=self.headers.get("If-None-Match"),
                body=body_in,
                headers={name: value for name, value in self.headers.items()},
            )
        except Exception:  # noqa: BLE001 - a handler must not take the server down
            # The traceback goes to the terminal, never to the browser: it
            # names paths on this machine.
            traceback.print_exc()
            response = _error("internal error; see the terminal", HTTPStatus.INTERNAL_SERVER_ERROR)

        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        for name, value in response.headers.items():
            self.send_header(name, value)
        self.end_headers()
        if body and response.body:
            self.wfile.write(response.body)

    def log_message(self, format: str, *args: Any) -> None:
        """One line per request, and only when asked.

        The stdlib default writes a line per request to stderr, which a poll
        every two seconds turns into an unreadable terminal.
        """
        if os.environ.get("FRAY_GUI_VERBOSE"):
            super().log_message(format, *args)


__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "RESOURCE_DIR",
    "Context",
    "MapHandler",
    "MapServer",
    "Response",
    "build_map_view",
    "handle_request",
]
