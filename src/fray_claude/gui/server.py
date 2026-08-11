"""Routing, the origin checks, and the socket adapter over them.

**`handle_request` is a pure function and the `BaseHTTPRequestHandler` below is
a thin adapter over it.** That is the whole structural decision here: routing,
error mapping and every response body are decided by a function taking strings
and returning a `Response`, so the tests exercise the entire surface without
binding a socket. The repo's rule that no test touches the network then holds
in letter as well as in spirit - loopback is still a socket, still a port to
collide on, still a thing a sandbox can refuse.

**This module accepts inbound connections, which no other module in the project
does.** `remote/api.py` remains the only module making *outbound* calls; the
two rules are about opposite directions and do not conflict.

What used to be 1,610 lines is now five modules and this one. The payload
builders live with the property that defines them - `routes_view.py` answers
without parsing the export, `routes_derived.py` cannot, `routes_reference.py`
serves bytes belonging to no map, `actions.py` holds the eleven POSTs, and
`http.py` holds the vocabulary all four share. What is left here is the
dispatch and the two checks that guard it:

- **`Sec-Fetch-Site` must be `same-origin`**, which closes cross-site POSTs.
- **`Host` must name this server**, which closes DNS rebinding - loopback
  always, plus whatever `--host`/`--allow-host` said. Hardcoding loopback did
  not refuse a remote page, it *half* served one: every panel rendered and
  every button 403'd.

There is still no token, so beyond loopback the address chosen is the whole of
the access control.
"""

from __future__ import annotations
import json
import os
import time
import traceback
from collections.abc import Mapping
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit
from fray_claude.store import cache
from fray_claude.remote.api import (
    fetch_ca_tier_icon,
    fetch_section_overlay,
    fetch_skill_icon,
)
from fray_claude.store.build_info import read_build
from fray_claude.costing.estimate import estimate
from fray_claude.derive.neighbours import eligible_neighbours
from fray_claude.derive.search import build_world_index, search
from fray_claude.model.summary import summarise
from fray_claude.gui.panels import task_panel
from fray_claude.gui.actions import _ACTIONS
from fray_claude.gui.http import Context, Response, _error, _first, _json, touch
from fray_claude.gui.routes_derived import (
    _chunk_detail,
    _estimate_payload,
    _full_diff,
    _section_states,
    _unlock_preview,
)
from fray_claude.gui.routes_reference import (
    _cached_upstream_asset,
    _reference_state,
    _static,
    _tile_source,
)
from fray_claude.gui.routes_view import (
    _run_steps,
    _timeline_payload,
    build_map_view,
    roll_detail,
)

#: The port `fray-gui` binds unless told otherwise. Arbitrary, and high enough
#: to need no privileges.
DEFAULT_PORT = 8731
DEFAULT_HOST = "127.0.0.1"

#: `Host` values that name this server whatever it bound, so a POST carrying
#: one is never a rebinding attempt. Anything else has to be named - see
#: `_origin_ok`.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

#: Binds that name no particular address, so they contribute nothing to the
#: allowlist: a wildcard is every interface, not a machine anyone types.
WILDCARD_HOSTS = frozenset({"0.0.0.0", "::", ""})

def normalise_host(value: str) -> str:
    """A `Host` header or a `--host` value as a bare address, for comparison.

    Strips the port, the brackets an IPv6 literal carries in a URL, and case -
    hostnames are case-insensitive, so `Devbox.tailnet.ts.net` is the machine
    `devbox.tailnet.ts.net` is. A bare IPv6 address is left alone: it is only
    the bracketed form that can carry a port, so `::1` is two colons and not a
    host with a port on it.
    """
    host = value.strip()
    if host.startswith("["):
        host = host.partition("]")[0].lstrip("[")
    elif host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    return host.casefold()


def _origin_ok(
    headers: Mapping[str, str], allowed: frozenset[str] = frozenset()
) -> str | None:
    """Why this POST should be refused, or `None` if it is fine.

    **A loopback bind stops other machines, not other tabs.** Any page you have
    open can POST to 127.0.0.1 and the browser will send it - cross-site
    request forgery. It cannot read the reply, so the exposure here is
    nuisance-grade: burn CPU on a simulation, write junk into `cache/sims/`.
    Two header checks close it for nothing:

    - `Sec-Fetch-Site` must be `same-origin`. Every current browser sends it,
      and a cross-site POST is exactly what it reports.
    - `Host` must **name this server**, which closes DNS rebinding - a hostile
      domain resolving to this address so that its page's origin *is* this
      server.

    **What names this server is loopback plus whatever `--host`/`--allow-host`
    said**, which is why this takes an allowlist rather than testing for
    loopback. Serving a tailnet address is a real use - drive the machine over
    ssh, read the map from a laptop - and hardcoding loopback did not refuse
    that, it *half* served it: every panel rendered and every button 403'd,
    which is a worse outcome than either serving it or refusing to.

    The allowlist is **named, never inferred**. A wildcard bind names no
    address, so `--host 0.0.0.0` alone still refuses; and no name is resolved
    on a request path, since that would be a network call from the module that
    makes none, on the request of whoever sent the header.

    Deliberately no per-launch token: it would put a secret in the URL and
    break bookmarking to buy little more than this. Beyond loopback the address
    is the whole of the access control, which `--host`'s help text says.
    """
    site = headers.get("Sec-Fetch-Site")
    if site is not None and site != "same-origin":
        return f"cross-site request refused (Sec-Fetch-Site: {site})"
    host = normalise_host(headers.get("Host") or "")
    if host and host not in LOOPBACK_HOSTS and host not in allowed:
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
    touch(ctx)
    if method == "POST":
        return _handle_post(path, body, headers or {}, ctx)
    if method not in ("GET", "HEAD"):
        return _error(f"{method} is not supported", HTTPStatus.METHOD_NOT_ALLOWED)

    static = _static(path, ctx)
    if static is not None:
        return static

    # Both names are validated by `cache.py` against an alphabet with no `.`
    # and no `/` in it, and a `ValueError` there is a malformed URL, not a
    # missing file - so it is a 400 rather than the 404 a real miss gets.
    if path.startswith("/assets/section/") and path.endswith(".png"):
        name = path.removeprefix("/assets/section/").removesuffix(".png")
        try:
            target = cache.section_overlay_path(name, ctx.root)
        except ValueError as exc:
            return _error(str(exc), HTTPStatus.BAD_REQUEST)
        return _cached_upstream_asset(
            target, lambda: fetch_section_overlay(name), what=f"section overlay {name}"
        )

    if path.startswith("/assets/ca/") and path.endswith(".png"):
        tier = path.removeprefix("/assets/ca/").removesuffix(".png")
        try:
            target = cache.ca_tier_icon_path(tier, ctx.root)
        except ValueError as exc:
            return _error(str(exc), HTTPStatus.BAD_REQUEST)
        return _cached_upstream_asset(
            target, lambda: fetch_ca_tier_icon(tier), what=f"{tier} tier icon"
        )

    if path.startswith("/assets/skill/") and path.endswith(".png"):
        skill = path.removeprefix("/assets/skill/").removesuffix(".png")
        try:
            target = cache.skill_icon_path(skill, ctx.root)
        except ValueError as exc:
            return _error(str(exc), HTTPStatus.BAD_REQUEST)
        return _cached_upstream_asset(
            target, lambda: fetch_skill_icon(skill), what=f"{skill} icon"
        )

    try:
        if path == "/api/maps":
            return _json(
                [
                    # `size` is the tooltip's, not the library's: `MapEntry`
                    # describes what a map *is*, and how many bytes it happens
                    # to occupy is a fact about this disk.
                    {**entry.as_dict(), "size": cache.map_size(entry.map_id, ctx.root)}
                    for entry in cache.list_maps(ctx.root, expand_runs=True)
                ]
            )

        if path == "/api/build":
            # **Which install is answering, for the page to watermark itself
            # with.** The same question `fray`'s first line answers, asked of
            # the server rather than of the terminal - and worth asking of the
            # server, because with `--host` the page may be on a different
            # machine from the checkout anyone is editing. Two stat calls, on
            # the package's own metadata; see `build_info.py`.
            return _json(read_build().as_dict())

        if path == "/api/reference":
            return _json({"reference": _reference_state(ctx)})

        if path == "/api/areas":
            # Static per export - which region is part of which named place
            # does not depend on any map - so no `map` parameter and no
            # derivation. It does need the export parsed; that is why the
            # browser asks for it once at boot rather than per view.
            info = ctx.derivations.chunk_info()
            # `labels` rides along with `areas` because both are static per
            # export and the page wants them at the same moment - one parse,
            # one request, ~30KB of names.
            return _json({"areas": info.area_names(), "labels": info.chunk_labels()})

        if path == "/api/tiles":
            return _json(_tile_source(ctx))

        if path == "/api/jobs":
            return _json([job.as_dict() for job in ctx.jobs.recent()])

        if path.startswith("/api/jobs/"):
            job = ctx.jobs.get(path.removeprefix("/api/jobs/"))
            if job is None:
                return _error("no such job", HTTPStatus.NOT_FOUND)
            return _json(job.as_dict())

        if path == "/api/summary":
            map_id = _first(query, "map")
            if map_id is None:
                return _error("missing required parameter 'map'", HTTPStatus.BAD_REQUEST)
            envelope = cache.read_cache(map_id, ctx.root)
            summary = summarise(envelope["data"])
            return _json(
                {
                    "map_id": map_id,
                    "kind": envelope.get("kind", cache.FETCHED),
                    "created_at": envelope.get("fetched_at"),
                    "unlocked_chunks": summary.unlocked_chunks,
                    "chunk_order_entries": summary.chunk_order_entries,
                    "rules_enabled": summary.rules_enabled,
                    "rules_total": summary.rules_total,
                    "active_tasks": summary.active_tasks,
                    "active_task_total": summary.active_task_total,
                }
            )

        if path == "/api/neighbours":
            map_id = _first(query, "map")
            if map_id is None:
                return _error("missing required parameter 'map'", HTTPStatus.BAD_REQUEST)
            state = ctx.derivations.load(map_id)
            entries = eligible_neighbours(state.state, state.unlocked, state.derived)
            return _json({"map_id": map_id, "neighbours": [n.as_dict() for n in entries]})

        if path == "/api/sections":
            map_id = _first(query, "map")
            if map_id is None:
                return _error("missing required parameter 'map'", HTTPStatus.BAD_REQUEST)
            return _json(
                {"map_id": map_id, "chunks": _section_states(ctx.derivations.load(map_id))}
            )

        if path == "/api/diff":
            map1 = _first(query, "map1")
            map2 = _first(query, "map2")
            if map1 is None or map2 is None:
                return _error(
                    "missing required parameter 'map1' or 'map2'", HTTPStatus.BAD_REQUEST
                )
            return _json({"map1": map1, "map2": map2, **_full_diff(map1, map2, ctx)})

        if path == "/api/chunk":
            map_id = _first(query, "map")
            chunk_id = _first(query, "chunk")
            if map_id is None or chunk_id is None:
                return _error(
                    "missing required parameter 'map' or 'chunk'", HTTPStatus.BAD_REQUEST
                )
            state = ctx.derivations.load(map_id)
            return _json(_chunk_detail(state, chunk_id, ctx))

        if path == "/api/unlock":
            map_id = _first(query, "map")
            chunk_id = _first(query, "chunk")
            if map_id is None or chunk_id is None:
                return _error(
                    "missing required parameter 'map' or 'chunk'", HTTPStatus.BAD_REQUEST
                )
            state = ctx.derivations.load(map_id)
            if chunk_id in state.unlocked:
                return _error(f"chunk {chunk_id} is already unlocked", HTTPStatus.BAD_REQUEST)
            return _json(_unlock_preview(state, chunk_id, ctx))

        if path == "/api/search":
            term = _first(query, "q")
            if term is None:
                return _error("missing required parameter 'q'", HTTPStatus.BAD_REQUEST)
            limit = max(1, min(200, int(_first(query, "limit") or 40)))
            # **`unlocked` and `derived` are what make `available` mean
            # anything.** Without them every hit and every one of its
            # locations comes back locked, which is not a cheaper answer -
            # it is a wrong one, and it silently made the whole panel say
            # "nothing here is reachable". `fray search` has always passed
            # both; this is the same call.
            map_id = _first(query, "map")
            against = ctx.derivations.load(map_id) if map_id else None
            info = against.state.chunk_info if against else ctx.derivations.chunk_info()
            results = search(
                build_world_index(info),
                term,
                unlocked=against.unlocked if against else None,
                derived=against.derived if against else None,
                limit=limit,
            )
            return _json({"query": term, "results": [r.as_dict() for r in results]})

        if path == "/api/estimate":
            map_id = _first(query, "map")
            if map_id is None:
                return _error("missing required parameter 'map'", HTTPStatus.BAD_REQUEST)
            return _json(_estimate_payload(ctx.derivations.load(map_id), ctx))

        if path == "/api/tasks":
            map_id = _first(query, "map")
            if map_id is None:
                return _error("missing required parameter 'map'", HTTPStatus.BAD_REQUEST)
            state = ctx.derivations.load(map_id)
            return _json({"map_id": map_id, **task_panel(state.derived)})

        if path == "/api/derived":
            return _json(
                [
                    {
                        "key": cached.key,
                        "size": cached.size,
                        "accessed_at": cached.accessed_at.isoformat(),
                    }
                    for cached in cache.list_derived(ctx.root)
                ]
            )

        if path == "/api/roll":
            map_id = _first(query, "map")
            raw = _first(query, "step")
            if map_id is None or raw is None:
                return _error(
                    "missing required parameter 'map' or 'step'", HTTPStatus.BAD_REQUEST
                )
            try:
                index = int(str(raw))
            except ValueError:
                return _error(f"step {raw!r} is not a number", HTTPStatus.BAD_REQUEST)
            steps = _run_steps(map_id, ctx)
            if not 0 <= index < len(steps):
                return _error(
                    f"step {index} is outside this run's 0..{len(steps) - 1}",
                    HTTPStatus.BAD_REQUEST,
                )
            roll = steps[index]
            # **The names, which `/api/timeline` deliberately leaves out.** One
            # roll of the real export opened 239 tasks; sending every name for
            # every step would be most of a megabyte to draw a bar chart with.
            # This is the same ledger read, asked for one step at a time.
            return _json(
                {
                    **roll.as_dict(),
                    "tasks_by_skill_names": {
                        skill: list(names)
                        for skill, names in sorted(roll.tasks_added.items())
                        if names
                    },
                    # The hours behind this one roll, priced on the click. See
                    # `routes_view.roll_detail`: `None` when it cannot be
                    # priced, and the overlay simply omits the chart.
                    "hours": roll_detail(map_id, index, ctx),
                }
            )

        if path == "/api/timeline":
            map_id = _first(query, "map")
            if map_id is None:
                return _error("missing required parameter 'map'", HTTPStatus.BAD_REQUEST)
            return _json(_timeline_payload(map_id, ctx))

        if path in ("/api/view", "/api/revision"):
            map_id = _first(query, "map")
            if map_id is None:
                return _error("missing required parameter 'map'", HTTPStatus.BAD_REQUEST)
            compare = _first(query, "compare")
            raw_step = _first(query, "step")
            try:
                step = None if raw_step in (None, "") else int(str(raw_step))
            except ValueError:
                return _error(f"step {raw_step!r} is not a number", HTTPStatus.BAD_REQUEST)
            try:
                view = build_map_view(map_id, compare, ctx, step)
            except ValueError as exc:
                return _error(str(exc), HTTPStatus.BAD_REQUEST)
            if path == "/api/revision":
                return _json({"revision": view.revision})
            return _json({**view.as_dict(), "step": step})
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
        refusal = _origin_ok(headers, ctx.allowed_hosts)
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
    "LOOPBACK_HOSTS",
    "WILDCARD_HOSTS",
    "RESOURCE_DIR",
    "Context",
    "MapHandler",
    "MapServer",
    "IDLE_TIMEOUT_SECONDS",
    "Response",
    "build_map_view",
    "handle_request",
    "idle_seconds",
    "normalise_host",
    "should_stop",
    "touch",
]
