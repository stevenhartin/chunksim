"""The GUI app: a local server and a browser front-end for the world map.

`chunksim` answers in text; this answers in pixels. It is a second app in the same
distribution rather than a second distribution, because the 28 modules beside
`cli.py` already *are* the library and a `gui/` package completes the picture
without the cost of inter-package version pinning.

Layering mirrors the CLI's: `worldmap.py` is pure and holds every decision,
`server.py` is routing and bytes, and this module is argparse and a socket. The
GUI imports the library directly rather than shelling out to `chunksim` - shelling
would re-parse the 10MB export per call and trade typed exceptions for exit
codes.

**The window's lifetime is the server's**, because a server you have to
remember to Ctrl-C is a server you leave running. There are two mechanisms and
at most one is armed at a time, so there is never a question of which applies:

- an **app window** was opened, and the server waits on that process. Closing
  the window stops it. See `gui/browser.py`.
- no app window, so a **heartbeat**: the page polls every two seconds, and the
  server stops once nothing has asked for anything in `IDLE_TIMEOUT_SECONDS`.
  This is the `--no-browser` case and the Firefox-only case.
- `--keep-alive` arms **neither**, and is the case the other two are wrong for:
  a server driven over ssh outlives the browser that reads it, so a closed tab
  on a laptop should not leave the user reconnecting to restart it.

Ctrl-C works in all three and exits 0. This is the one command in the project
that runs until interrupted, and a traceback for the documented way to end it
would be wrong.

**Serving beyond loopback takes an address and, sometimes, a name.** `--host`
binds it, and the same value seeds the `Host` allowlist so that a page loaded
from a tailnet address may also POST to it - without that the remote page
renders in full and every button 403s (`server._origin_ok` has the reasoning).
`--allow-host` adds a name the bind does not spell, which a wildcard bind never
does. Nothing here is authenticated, so **the address chosen is the whole of
the access control**: a tailnet address is a different proposition from
`0.0.0.0` on a shared network, and this module will say so on stdout rather
than leave it in `--help`.

**The window's size is remembered, and has to be, because Chrome will not do
it.** An app window's saved bounds are keyed on an app id derived from the
URL, and ours carries the port and the `?map=` deep link - so every launch
looks like a different app to it. The page reports its own geometry to
`/api/window` instead, and `browser.window_flags` reads it back. A first run
opens maximised.

The modules, and what each owns:

- `server.py` - routing, as a **pure `handle_request`** with a
  `BaseHTTPRequestHandler` adapter over it. Owns the `Sec-Fetch-Site`/`Host`
  checks, and `_state_at`, the one place `(map, step)` becomes a world, so six
  routes cannot disagree about what a step means.
- `http.py` - the vocabulary every route speaks. **Must stay directly in
  `gui/`**: `RESOURCE_DIR` is `__file__`-relative, which is why this split is
  flat rather than a `routes/` package.
- `routes_view.py` - the **cheap path**, every route answerable without parsing
  the export. Nothing here may call `ctx.derivations.load` (one documented
  exception, with a test).
- `routes_derived.py` - the **expensive path**. `walked_into` owns the name join
  for a square you can reach without rolling, and **both callers share it**: the
  map outlines them and the chunk panel stops greying their contents. Those two
  disagreed until it existed. `/api/diff` derives both sides and is the one
  route allowed to be slow. `/api/training` is here too, and takes the one
  optional `skill` parameter in the API: without it the methods overlay draws
  the per-skill summary and with it the drill-down. It reads the same
  `costing/inputs.training_answer` `chunksim training` does, so a method the
  overlay shows cannot rank differently from the one the command names. Also
  `reachable_by_area`, the squares a map can walk
  into without having rolled them, joined to `expanded_chunks` **by name** - the
  `sections` graph does not model dungeon entrances at all.
- `routes_reference.py` - bytes belonging to no map: the static allowlist, blob
  freshness, the tile *template*, and the lazy asset proxy.
- `actions.py` - the POST handlers. **An action's reply shape decides whether
  the page polls it** - a job id, or the result. `/api/blank` makes a map out of
  nothing, for a first run with nothing to open. `/api/update` is silent on
  every failure by design; `/api/update/install` **verifies a checksum before
  executing anything** and refuses an asset that published none.
- `jobs.py` - the background job registry. **The only mutable state in the
  GUI**, kept out of the pure layer deliberately. Also `claim_once`, which is
  what stops the page's boot warm-up re-scraping the wiki on every reload.
- `derivation.py` - the boundary between the cheap path and the expensive one.
  Loads `ChunkInfo` **lazily**, and holds the `ReferenceBlobs` - the one memo
  here validated against the files' mtimes, because stale overrides key the
  enrichment cache. Also `load_step`, which is how a panel describes one roll of
  a run rather than the map.
- `settings.py` - what a preference *means*: the defaults, and the validation
  that refuses rather than coerces. `cache.py` stores it and knows nothing about
  it; this is where the next preference goes. **`first_run_done` living here is
  what makes "never asked again unless the cache is empty" free**, because the
  file is under `cache/`.
- `knobs.py` - what an override **path** means: which layer a value came from,
  and whether a proposed one is allowed. Pure, and the guard on paths that
  address a file read back and parsed.
- `panels.py` - shaping `Derived` into what the panel draws, one shape across
  all five categories, pure. **A completed row carries `when`**:
  `checkedChallenges` is what was ticked during the chunk in play and the next
  roll migrates it into `completedChallenges`, so the un-migrated half *is*
  "this chunk" and needs no new data. **A skills row's level is
  `Level - bestBoost`, not `Level`** - printing the requirement would send
  someone training levels a boost already covers - and it needs `MapState` as
  well as `Derived`, because the boost depends on this map's rules and reachable
  items; without one the row says nothing rather than printing the unboosted
  number. **New shaping goes here, not into the JavaScript.** A *roll* is shaped
  from the ledger alone, so anything the selection compares has to be in the
  ledger.
- `worldmap.py` - where a chunk sits on the map and which sides face outward.
  Owns the projection (the y axis is flipped) and `hull_edges`.
- `browser.py` - finding a Chromium-family browser and opening an app window
  whose lifetime is the server's. `--user-data-dir` is load-bearing, not
  tidiness.
- `__main__.py` - `python -m chunksim.gui`, which exists for the Windows payload
  rather than for convenience.
- this module - `chunksim-gui`'s argparse and socket, `allowed_hosts`, and the
  arming of at most one of the two shutdown mechanisms. Downloads nothing.

`resources/` is the front end itself. `app.js` is heavily commented and is where
its rationale lives; `tests/test_gui_contract.py` is what stops it and the
Python drifting apart.
"""

from __future__ import annotations

import argparse
import errno
import sys
import threading
import time
import webbrowser
from collections.abc import Sequence
from pathlib import Path

from chunksim.store import cache
from chunksim.remote.api import DEFAULT_TIMEOUT
from chunksim.store.build_info import print_watermark
from chunksim.gui.browser import open_app_window
from chunksim.gui.jobs import JobState
from chunksim.gui.http import Context, should_stop
from chunksim.gui.server import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    LOOPBACK_HOSTS,
    WILDCARD_HOSTS,
    MapServer,
    normalise_host,
)
from chunksim.gui.worldmap import MapView, build_view

__all__ = ["MapView", "allowed_hosts", "build_view", "main"]


def allowed_hosts(host: str, extra: Sequence[str] = ()) -> frozenset[str]:
    """Which `Host` values name this server, beyond the loopback names.

    The bind seeds it, so `--host <tailnet address>` needs no second flag for
    the page served there to be able to POST back. A **wildcard contributes
    nothing** - `0.0.0.0` is every interface rather than an address anyone
    types, so it cannot stand in for the one they will - and loopback is left
    out because `server._origin_ok` accepts it unconditionally.

    Pure, and separate from `main` for that reason: the interesting part of
    `--host` is this set, and reaching it through a bound socket to test it
    would be absurd.
    """
    named = {normalise_host(name) for name in [host, *extra]}
    return frozenset(named - WILDCARD_HOSTS - LOOPBACK_HOSTS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chunksim-gui",
        description="Serve an interactive world map of a cached chunk map.",
    )
    parser.add_argument(
        "--map", dest="map_id", default=None, help="map to open (default: the first cached)"
    )
    parser.add_argument(
        "--compare",
        default=None,
        metavar="MAPID",
        help="open in delta mode against this map: gains green, losses red",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="port to bind (default: %(default)s; 0 lets the OS choose)",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=(
            "address to bind (default: %(default)s). Anything else exposes your "
            "map to other machines on the network, which this does not "
            "authenticate"
        ),
    )
    parser.add_argument(
        "--allow-host",
        action="append",
        default=[],
        dest="allow_hosts",
        metavar="HOST",
        help=(
            "also accept this name in the Host header, for an address other "
            "machines reach by a name --host does not spell - a MagicDNS name, "
            "or anything at all when --host is a wildcard. Repeatable"
        ),
    )
    parser.add_argument(
        "--keep-alive",
        action="store_true",
        help=(
            "serve until Ctrl-C instead of stopping once the last client goes "
            "away; for a server left running over ssh"
        ),
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help=(
            "do not open anything; serve until the last client goes away or "
            "Ctrl-C"
        ),
    )
    parser.add_argument(
        "--tab",
        action="store_true",
        help=(
            "open an ordinary tab in your usual browser instead of an app "
            "window, keeping your profile and extensions"
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=(
            "request timeout for the one wiki page read to find the current "
            "map-tile render (default: %(default)s)"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # stdout, unlike `chunksim`'s: there is no `--export-json -` here to keep clean,
    # and the other startup lines are here. The page shows the same thing, but
    # a server started over ssh is often read from a terminal first.
    print_watermark("chunksim-gui", sys.stdout)
    # **No map image is downloaded and none is served.** The browser fetches
    # the wiki's tiles itself; all this process resolves is which render to
    # ask for, lazily, on the first `/api/tiles` request. See
    # `api.MAP_TILE_URL` for why keeping the bytes out of here is a licence
    # decision rather than a saving.
    allowed = allowed_hosts(args.host, args.allow_hosts)
    context = Context(allowed_hosts=allowed, keep_alive=args.keep_alive)

    try:
        server = MapServer((args.host, args.port), context)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print(
                f"port {args.port} is already in use; pass --port to pick another",
                file=sys.stderr,
            )
            return 1
        print(f"could not bind {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 1

    # Read the address back rather than trusting `args.port`, so `--port 0`
    # prints something you can actually open. The stdlib types the host half as
    # `str | bytes` because a Unix socket puts a path there; this is always
    # AF_INET, so decoding is the honest narrowing.
    bound_host, bound_port = server.server_address[:2]
    host = bound_host.decode() if isinstance(bound_host, bytes) else bound_host
    url = f"http://{host}:{bound_port}/"
    query = []
    if args.map_id:
        query.append(f"map={args.map_id}")
    if args.compare:
        query.append(f"compare={args.compare}")
    if query:
        url += "?" + "&".join(query)

    print(f"serving {url}")
    if normalise_host(args.host) not in LOOPBACK_HOSTS:
        print("reachable by other machines on that network, and not authenticated")
        if not allowed:
            print(
                "  --host names no address, so actions will be refused: pass "
                "--allow-host with the address you open it at"
            )
    if args.keep_alive:
        print("staying up until Ctrl-C, whether or not anything is watching")

    # Opened after binding, so nothing can load before the socket listens.
    window = None
    if not args.no_browser and not args.tab:
        window = open_app_window(
            url,
            cache.gui_profile_dir(context.root),
            geometry=cache.read_gui_window(context.root),
        )
        if window is not None:
            print(f"opened an app window ({window.browser.name}); close it to stop")
    if window is None and not args.no_browser:
        try:
            webbrowser.open(url, new=2)
        except Exception:  # noqa: BLE001 - opening a browser is best-effort
            pass
        print("close the tab to stop, or press Ctrl-C")
    if window is None and args.no_browser:
        print("open it yourself; it stops when you close it, or on Ctrl-C")

    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    try:
        if window is not None:
            window.wait()
        else:
            # Poll rather than block, so Ctrl-C is answered promptly.
            while not should_stop(context):
                time.sleep(1.0)
    except KeyboardInterrupt:
        print()
    finally:
        if window is not None:
            window.close()
        server.shutdown()
        server.server_close()

    _report_abandoned(context)
    print("stopped")
    return 0


def _report_abandoned(context: Context) -> None:
    """Name any job that was still running, and where its output went.

    Job threads are daemons, so shutting down abandons them. `batch.run_batch`
    claims its directory up front and writes each run atomically, so what is
    left is a partial batch rather than a corrupt one - but it is a batch
    nobody asked for, and saying so is the difference between tidying it up
    and wondering where it came from.
    """
    running = [job for job in context.jobs.recent() if job.state is JobState.RUNNING]
    for job in running:
        detail = f" ({job.progress})" if job.progress else ""
        print(f"abandoning {job.action}{detail}", file=sys.stderr)
    if running:
        print("any partial output is under cache/sims - chunksim maps rm removes it", file=sys.stderr)


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
