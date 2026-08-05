"""The GUI app: a local server and a browser front-end for the world map.

`fray` answers in text; this answers in pixels. It is a second app in the same
distribution rather than a second distribution, because the 28 modules beside
`cli.py` already *are* the library and a `gui/` package completes the picture
without the cost of inter-package version pinning.

Layering mirrors the CLI's: `worldmap.py` is pure and holds every decision,
`server.py` is routing and bytes, and this module is argparse and a socket. The
GUI imports the library directly rather than shelling out to `fray` - shelling
would re-parse the 10MB export per call and trade typed exceptions for exit
codes.

**The window's lifetime is the server's**, because a server you have to
remember to Ctrl-C is a server you leave running. There are two mechanisms and
exactly one is armed at a time, so there is never a question of which applies:

- an **app window** was opened, and the server waits on that process. Closing
  the window stops it. See `gui/browser.py`.
- no app window, so a **heartbeat**: the page polls every two seconds, and the
  server stops once nothing has asked for anything in `IDLE_TIMEOUT_SECONDS`.
  This is the `--no-browser` case and the Firefox-only case.

Ctrl-C works in both and exits 0. This is the one command in the project that
runs until interrupted, and a traceback for the documented way to end it would
be wrong.

**The window's size is remembered, and has to be, because Chrome will not do
it.** An app window's saved bounds are keyed on an app id derived from the
URL, and ours carries the port and the `?map=` deep link - so every launch
looks like a different app to it. The page reports its own geometry to
`/api/window` instead, and `browser.window_flags` reads it back. A first run
opens maximised.
"""

from __future__ import annotations

import argparse
import errno
import sys
import threading
import time
import webbrowser
from pathlib import Path

from fray_claude import cache
from fray_claude.api import DEFAULT_TIMEOUT, FetchError, fetch_world_map
from fray_claude.gui.browser import open_app_window
from fray_claude.gui.jobs import JobState
from fray_claude.gui.server import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    Context,
    MapServer,
    should_stop,
)
from fray_claude.gui.worldmap import MapView, build_view

__all__ = ["MapView", "build_view", "main"]


def _ensure_world_map(context: Context, timeout: float) -> None:
    """Download the map image if this installation has not got it yet.

    Fetched rather than shipped because it is Jagex's artwork - see
    `api.WORLD_MAP_URL`. Once per machine, and `FRAY_WORLD_MAP` skips it
    entirely.

    A failure here is reported and *not* fatal: the chunk grid, the hull and
    every number still work without the image, and a server that refuses to
    start because a CDN is unreachable would be worse than one that draws on
    a blank background.
    """
    if context.world_map_path.is_file():
        return
    print("world map not cached, downloading from Jagex (~2.9 MiB)...", flush=True)
    try:
        blob = fetch_world_map(timeout)
    except FetchError as exc:
        print(f"could not download the world map: {exc}", file=sys.stderr)
        print("the map will draw without its background image", file=sys.stderr)
        return
    path = cache.write_asset(cache.WORLD_MAP_ASSET, blob, context.root)
    print(f"wrote {path} ({len(blob):,} bytes)", flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fray-gui",
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
        "--world-map",
        type=Path,
        default=None,
        help="path to a local copy of the map image, overriding FRAY_WORLD_MAP",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="request timeout for the one-off image download (default: %(default)s)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    context = Context(world_map=args.world_map)
    _ensure_world_map(context, args.timeout)

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
        print("any partial output is under cache/sims - fray maps rm removes it", file=sys.stderr)


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
