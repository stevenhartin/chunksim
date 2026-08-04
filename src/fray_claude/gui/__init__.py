"""The GUI app: a local server and a browser front-end for the world map.

`fray` answers in text; this answers in pixels. It is a second app in the same
distribution rather than a second distribution, because the 27 modules beside
`cli.py` already *are* the library and a `gui/` package completes the picture
without the cost of inter-package version pinning.

Layering here mirrors the CLI's: `worldmap.py` is pure and holds every
decision, `server.py` is routing and bytes, and this module is argparse and a
socket. The GUI imports the library directly rather than shelling out to
`fray` - shelling would re-parse the 10MB export per call and throw away typed
exceptions for exit codes.
"""

from fray_claude.gui.worldmap import MapView, build_view

__all__ = ["MapView", "build_view"]
