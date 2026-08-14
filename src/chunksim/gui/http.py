"""The vocabulary every route speaks, and the server's own lifetime.

`Response` and `Context`, the two constructors every handler ends in (`_json`,
`_error`), the query accessor `_first`, and the heartbeat (`touch`,
`idle_seconds`, `should_stop`).

**This module has to live directly in `gui/`, and that is load-bearing.**
`RESOURCE_DIR` is `Path(__file__).resolve().parent / "resources"`, so a module
one directory deeper computes the wrong path - which is why the split is flat
here rather than a `gui/routes/` package. It is the same class of bug that made
`build_info` report its own subdirectory when it moved into `store/`.

It imports none of the route modules, and they all import it. That direction is
what keeps the six acyclic.
"""

from __future__ import annotations

from typing import Any
from chunksim.gui.derivation import Derivations
from http import HTTPStatus
from chunksim.gui.jobs import JobRegistry
from chunksim.gui.jobs import JobState
from collections.abc import Mapping
from pathlib import Path
from dataclasses import dataclass
from dataclasses import field
import json
import time


_JSON = "application/json; charset=utf-8"


#: Text assets that ship inside the package. No map imagery is here or
#: anywhere else on this machine: the browser loads tiles straight from the
#: wiki's CDN - see `api.MAP_TILE_URL`.
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


#: How long the server outlives its last client when nothing is holding it
#: open. The page polls `/api/revision` every 2s, so this is roughly seven
#: missed polls - long enough to survive a slow reload or a laptop briefly
#: asleep, short enough that a closed tab does not leave a process behind.
#: Only armed when no app window was opened; see `gui/browser.py`.
IDLE_TIMEOUT_SECONDS = 15.0


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
    jobs: JobRegistry = field(default_factory=JobRegistry)
    #: Loaded on the first request that needs a derivation, never for the map
    #: view. See `gui/derivation.py`.
    derivations: Derivations = field(default_factory=Derivations)
    #: When the last client was heard from, for the idle shutdown. Mutable, so
    #: it is a one-element list rather than a field on a frozen dataclass -
    #: the alternative is unfreezing `Context`, and every other field here
    #: genuinely is constant.
    last_seen: list[float] = field(default_factory=lambda: [0.0])
    #: The map-tile version last resolved, so one server run scrapes the
    #: wiki once however many times the page asks. Mutable for the same reason
    #: `last_seen` is.
    tile_version: list[str] = field(default_factory=lambda: [""])
    #: Whether the browser-origin checks apply. Off in tests, which have no
    #: browser to send the headers this asserts on.
    check_origin: bool = True
    #: `Host` values that name this server besides loopback - what `--host`
    #: and `--allow-host` were given. Empty for an ordinary loopback bind.
    allowed_hosts: frozenset[str] = frozenset()
    #: Whether the idle shutdown is disarmed (`--keep-alive`), for a server
    #: meant to outlive the browser that reads it.
    keep_alive: bool = False

    def __post_init__(self) -> None:
        # `Derivations` needs the same root the rest of the context reads
        # from, and a default factory cannot see its siblings.
        if self.derivations._root is None and self.root is not None:
            object.__setattr__(self.derivations, "_root", self.root)


def _json(payload: Any, status: int = HTTPStatus.OK) -> Response:
    body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    return Response(status=status, content_type=_JSON, body=body)


def _error(message: str, status: int) -> Response:
    return _json({"error": message}, status)


def _first(query: Mapping[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def touch(ctx: Context) -> None:
    """Record that a client is still there."""
    ctx.last_seen[0] = time.monotonic()


def idle_seconds(ctx: Context) -> float:
    """How long since a client last asked for anything, or `0.0` if never.

    Zero rather than infinity for the never-seen case, and the difference is
    not academic: `should_stop` compares this against a timeout, so infinity
    would make a server nobody has opened yet stop *immediately* - which is
    exactly what `--no-browser` is, for the seconds between binding and the
    user pasting the URL.
    """
    if not ctx.last_seen[0]:
        return 0.0
    return time.monotonic() - ctx.last_seen[0]


def should_stop(ctx: Context, timeout: float = IDLE_TIMEOUT_SECONDS) -> bool:
    """Whether the last client has gone and nothing is holding the server open.

    Three things hold it open, and only the first is obvious:

    - a client asked for something within `timeout`;
    - **nobody has connected yet** - a server waiting to be opened is not an
      idle one, and `--no-browser` prints a URL for someone to paste;
    - **a job is running.** Closing the tab that started a simulation should
      not throw the simulation away; the browser leaving is not a reason to
      abandon work already begun, which will be in the cache when a window
      next opens.

    `--keep-alive` disarms it entirely: a server left running over ssh is meant
    to outlive the browser that reads it, and stopping fifteen seconds after a
    laptop's tab closed is a server you have to go back and restart.
    """
    if ctx.keep_alive:
        return False
    if not ctx.last_seen[0]:
        return False
    if any(job.state is JobState.RUNNING for job in ctx.jobs.recent()):
        return False
    return idle_seconds(ctx) > timeout
