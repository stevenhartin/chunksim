"""The GUI app: a local server and a browser front-end for the world map.

`fray` answers in text; this answers in pixels. It is a second app in the same
distribution rather than a second distribution, because the 27 modules beside
`cli.py` already *are* the library and a `gui/` package completes the picture
without the cost of inter-package version pinning.

Layering mirrors the CLI's: `worldmap.py` is pure and holds every decision,
`server.py` is routing and bytes, and this module is argparse and a socket. The
GUI imports the library directly rather than shelling out to `fray` - shelling
would re-parse the 10MB export per call and trade typed exceptions for exit
codes.

**Ctrl-C is how you stop it, so Ctrl-C exits 0.** This is the one command in
the project that runs until interrupted, and a traceback for the documented
way to end it would be wrong.
"""

from __future__ import annotations

import argparse
import errno
import sys
import webbrowser
from pathlib import Path

from fray_claude import cache
from fray_claude.api import DEFAULT_TIMEOUT, FetchError, fetch_world_map
from fray_claude.gui.server import DEFAULT_HOST, DEFAULT_PORT, Context, MapServer
from fray_claude.gui.worldmap import MapView, build_view

__all__ = ["MapView", "build_view", "main"]


def _ensure_world_map(context: Context, timeout: float) -> None:
    """Download the map image if this installation has not got it yet.

    Fetched rather than shipped because it is Jagex's artwork - see
    `api.WORLD_MAP_URL`. Once per machine, and `FRAY_WORLD_MAP` skips it
    entirely.

    A failure here is reported and *not* fatal: the chunk grid, the hull and
    every number still work without the image, and a server that refuses to
    start because GitHub is unreachable would be worse than one that draws on
    a blank background.
    """
    if context.world_map_path.is_file():
        return
    print(f"world map not cached, downloading from upstream (~8.4 MiB)...", flush=True)
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
        "--no-browser", action="store_true", help="do not open a browser window"
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
    print("press Ctrl-C to stop")
    if not args.no_browser:
        # After binding, so the tab cannot load before the socket listens. A
        # headless box makes this fail or write to stderr, and neither should
        # take the server down.
        try:
            webbrowser.open(url, new=2)
        except Exception:  # noqa: BLE001 - opening a browser is best-effort
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.shutdown()
        server.server_close()
    print("stopped")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
