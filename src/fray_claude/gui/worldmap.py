"""Where a chunk sits on upstream's world map, and where the unlocked blob ends.

Pure and I/O-free: everything here is arithmetic over chunk ids plus the frozen
result classes the browser is sent as JSON. `server.py` is the adapter that
turns a request into a `MapView` and back into bytes, the same way `cli.py`
holds argparse and nothing else.

**This lives in `gui/` rather than in the library because all of it is about
one particular image.** The 48x34 grid, the 128-pixel cell, the one-pixel
border and the flipped y axis are properties of `osrs_world_map.jpg`, not facts
about the game world that the rest of the project could use. The one piece that
*is* world knowledge
is `region_xy`, and `dps_bridge.in_wilderness` already inlines it; if the
library ever wants that decoder, the move is to push those two functions down
into the library rather than to host this module up there and have a library
module import from an app package.

**The projection, verified against the image rather than derived on paper.**
A chunk id *is* an OSRS region id, so:

    region_x, region_y = chunk_id >> 8, chunk_id & 0xFF
    grid_x = region_x - MIN_REGION_X          # 15
    grid_y = MAX_REGION_Y - region_y          # 65 - y, and note the direction

**The y axis is flipped**, which is the one thing here that will look like a
bug: the image's origin is the world's *north*-west corner and image rows grow
southward, while OSRS's `region_y` grows *northward*. Lumbridge is chunk 12850
= region (50, 50) = grid (35, 15) = pixel (4480, 1921) once the border offset
is added, and cropping the real image at that rectangle really does show
Lumbridge castle - checked, not assumed, because every later bug in this module
would otherwise look like a hull bug.

**Two kinds of chunk id have no square on this map**, and `grid_position`
returning `None` is how both are reported:

- **Named areas.** 315 of the export's 2,234 chunk ids are strings like
  `Abyss`, `Dorgesh-Kaan` or `Player-owned house`. They are real places with
  real contents; they are not regions and have no coordinates at all.
- **Underground and instanced regions.** Numeric, but outside the surface
  rectangle - `4751` is Kurask Lair at region (18, 143), far below the map's
  `region_y` ceiling of 65. Roughly 386 of them.

A caller that assumes "numeric implies drawable" gets a wrong square rather
than an error, which is why the check is one function and every path goes
through it. `MapView.skipped` carries whatever was dropped, so a canvas showing
fewer chunks than `fray show` counted explains itself instead of reading as a
rendering fault.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import IntFlag, StrEnum
from typing import Any

#: An OSRS region is 64x64 tiles and Jagex's published map draws each tile 2
#: pixels across, so a chunk is a 128-pixel square. Every other number here
#: follows from that and is asserted below rather than trusted.
TILES_PER_CHUNK = 64
PIXELS_PER_TILE = 2
PIXELS_PER_CHUNK = TILES_PER_CHUNK * PIXELS_PER_TILE

#: `osrs_world_map.jpg`, fetched from Jagex's own CDN. See
#: `api.fetch_world_map`.
IMAGE_WIDTH = 6145
IMAGE_HEIGHT = 4353

#: **The map content does not start at the image's top-left corner.** The
#: published JPEG carries a one-pixel black border along its top and right
#: edges, so the 6144x4352 of actual world sits at `(0, 1)`. Measured, not
#: assumed: the last column means 1.0 and the first row 2.0 against ~55 for
#: real content, and aligning the whole image against upstream's own render
#: downscaled to 6144x4352 picks `(0, 1)` over the other three corners. A
#: renderer that ignores this draws every square one pixel high, which is
#: invisible at a glance and wrong at every zoom.
#: One pixel on one side of each axis - the right edge for x, the top for y,
#: which is why only `IMAGE_ORIGIN_Y` is non-zero. A border after the content
#: costs the origin nothing and the image size one pixel all the same.
BORDER_PIXELS = 1
IMAGE_ORIGIN_X = 0
IMAGE_ORIGIN_Y = 1

#: The surface rectangle the image covers, in OSRS region coordinates. World
#: tiles x 960-4031 and y 2048-4223, divided by 64.
MIN_REGION_X = 15
MAX_REGION_X = 62
MIN_REGION_Y = 32
MAX_REGION_Y = 65

GRID_COLUMNS = MAX_REGION_X - MIN_REGION_X + 1
GRID_ROWS = MAX_REGION_Y - MIN_REGION_Y + 1

#: The id-space step between horizontally adjacent chunks. `region_x` occupies
#: the high byte, so a step east is +256 and a step *north* is +1.
REGION_STRIDE = 256

# The projection has to tile the image exactly, border included. If Jagex ever
# re-renders the map at a different scale these stop agreeing, and failing at
# import is far kinder than drawing every square in the wrong place.
assert GRID_COLUMNS * PIXELS_PER_CHUNK + BORDER_PIXELS == IMAGE_WIDTH
assert GRID_ROWS * PIXELS_PER_CHUNK + BORDER_PIXELS == IMAGE_HEIGHT
# The border is on one side or the other, never split across both.
assert IMAGE_ORIGIN_X in (0, BORDER_PIXELS)
assert IMAGE_ORIGIN_Y in (0, BORDER_PIXELS)


class Edge(IntFlag):
    """Which sides of a chunk face something that is not unlocked."""

    NONE = 0
    TOP = 1
    BOTTOM = 2
    LEFT = 4
    RIGHT = 8


class CellState(StrEnum):
    """What a drawn cell means. Locked chunks are *absent*, not a state."""

    UNLOCKED = "unlocked"
    ADDED = "added"
    REMOVED = "removed"


def region_xy(chunk_id: int) -> tuple[int, int]:
    """The OSRS region coordinates a chunk id encodes.

    A chunk id is not merely *derived from* a region id, it **is** one:
    `region_x * 256 + region_y`. 12850 is region (50, 50), Lumbridge.
    """
    return chunk_id >> 8, chunk_id & 0xFF


def chunk_id_of(region_x: int, region_y: int) -> int:
    """The chunk id for a region. The inverse of `region_xy`."""
    return region_x * REGION_STRIDE + region_y


def on_surface(region_x: int, region_y: int) -> bool:
    """Whether a region falls inside the rectangle the map image covers."""
    return (
        MIN_REGION_X <= region_x <= MAX_REGION_X
        and MIN_REGION_Y <= region_y <= MAX_REGION_Y
    )


@dataclass(frozen=True)
class GridPos:
    """A chunk's cell on the 48x34 grid, and its pixel origin on the image."""

    grid_x: int
    grid_y: int

    @property
    def pixel_x(self) -> int:
        """The left edge of this cell *in the image*, border included."""
        return IMAGE_ORIGIN_X + self.grid_x * PIXELS_PER_CHUNK

    @property
    def pixel_y(self) -> int:
        """The top edge of this cell *in the image*, border included."""
        return IMAGE_ORIGIN_Y + self.grid_y * PIXELS_PER_CHUNK


def grid_position(chunk_id: str) -> GridPos | None:
    """Where `chunk_id` sits on the map, or `None` if it sits nowhere.

    **The one place both skip rules live**, so no caller has to remember them.
    `None` means the id is a named area (`Abyss`) or an off-surface region
    (Kurask Lair at region y 143) - see the module docstring. Both are ordinary
    facts about the export rather than errors, and the caller's response to
    either is the same: leave it out of the drawing and record it.
    """
    if not chunk_id.isdigit():
        return None
    region_x, region_y = region_xy(int(chunk_id))
    if not on_surface(region_x, region_y):
        return None
    # The y-flip. See the module docstring - image rows grow south, region y
    # grows north.
    return GridPos(grid_x=region_x - MIN_REGION_X, grid_y=MAX_REGION_Y - region_y)


def hull_edges(unlocked: Iterable[int]) -> dict[int, Edge]:
    """Which sides of each unlocked chunk face outward.

    Ports upstream's `chunkBordersCanvas` (index.js:3934), which is the
    requirement's "a thick border between locked and unlocked, and none between
    two unlocked chunks" expressed as a per-chunk test rather than as a traced
    polygon: an edge is drawn exactly when the neighbour across it is not
    unlocked, so a shared edge is omitted from *both* sides and the outline of
    the blob is what survives.

    **The neighbour arithmetic looks upside-down and is not.** `region_x` is
    the high byte, so `id + 256` is the chunk east and `id + 1` is the chunk
    one region *north* - which the flipped y axis puts one row **up** on
    screen. Hence `id + 1` guarding `TOP`.

    No special case is needed at the edge of the map. The test is membership of
    the unlocked set, not of the grid, so a chunk on the top row asks about a
    region that was never unlocked and correctly draws its outer edge.

    A blob with a hole in it produces an inner boundary as well as an outer
    one. That is right: the invariant is "no edge between two unlocked chunks",
    not "exactly one closed loop".
    """
    inside = frozenset(unlocked)
    edges: dict[int, Edge] = {}
    for chunk_id in inside:
        edge = Edge.NONE
        if chunk_id + 1 not in inside:
            edge |= Edge.TOP
        if chunk_id - 1 not in inside:
            edge |= Edge.BOTTOM
        if chunk_id + REGION_STRIDE not in inside:
            edge |= Edge.RIGHT
        if chunk_id - REGION_STRIDE not in inside:
            edge |= Edge.LEFT
        edges[chunk_id] = edge
    return edges


@dataclass(frozen=True)
class MapGeometry:
    """Every constant the browser needs, so no number is written twice."""

    image_width: int = IMAGE_WIDTH
    image_height: int = IMAGE_HEIGHT
    pixels_per_chunk: int = PIXELS_PER_CHUNK
    grid_columns: int = GRID_COLUMNS
    grid_rows: int = GRID_ROWS
    #: Where grid (0, 0) sits inside the image. See `IMAGE_ORIGIN_Y`.
    origin_x: int = IMAGE_ORIGIN_X
    origin_y: int = IMAGE_ORIGIN_Y

    def as_dict(self) -> dict[str, Any]:
        return {
            "image_width": self.image_width,
            "image_height": self.image_height,
            "pixels_per_chunk": self.pixels_per_chunk,
            "grid_columns": self.grid_columns,
            "grid_rows": self.grid_rows,
            "origin_x": self.origin_x,
            "origin_y": self.origin_y,
        }


@dataclass(frozen=True)
class ChunkCell:
    """One drawn square: where it is, what it means, which sides it outlines."""

    chunk_id: str
    region_x: int
    region_y: int
    grid_x: int
    grid_y: int
    state: CellState
    #: An `Edge` bitmask. `0` when the cell sits wholly inside the blob.
    edges: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "region_x": self.region_x,
            "region_y": self.region_y,
            "grid_x": self.grid_x,
            "grid_y": self.grid_y,
            "state": str(self.state),
            "edges": self.edges,
        }


@dataclass(frozen=True)
class ViewCounts:
    """What the header line reports, computed once rather than in JavaScript."""

    unlocked: int = 0
    added: int = 0
    removed: int = 0
    skipped: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "unlocked": self.unlocked,
            "added": self.added,
            "removed": self.removed,
            "skipped": self.skipped,
        }


@dataclass(frozen=True)
class MapView:
    """One rendering of one map, ready to serialise.

    **`cells` holds only the chunks worth drawing** - unlocked, added or
    removed - and locked is the *absence* of an entry. The browser washes every
    grid cell it was not given, which keeps this payload at a few hundred
    entries instead of 1,632 and means adding a chunk never grows the format.
    """

    map_id: str
    geometry: MapGeometry
    cells: tuple[ChunkCell, ...]
    counts: ViewCounts
    compare_map_id: str | None = None
    #: `st_mtime_ns` of the map file(s) this was built from. The browser polls
    #: it to notice a `fray fetch` in another terminal; it is deliberately not
    #: a hash, because a stat is cheaper than a read and a false positive
    #: costs one redraw.
    revision: int = 0
    #: Ids that could not be placed. See `grid_position`.
    skipped: tuple[str, ...] = ()
    #: The slot the planned roll heatmaps drop into. An overlay is one entry
    #: here and one layer function in `app.js`; nothing else has to change.
    overlays: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "map_id": self.map_id,
            "compare_map_id": self.compare_map_id,
            "revision": self.revision,
            "geometry": self.geometry.as_dict(),
            "cells": [cell.as_dict() for cell in self.cells],
            "counts": self.counts.as_dict(),
            "skipped": list(self.skipped),
            "overlays": dict(self.overlays),
        }


def build_view(
    *,
    map_id: str,
    unlocked: Iterable[str],
    added: Iterable[str] = (),
    removed: Iterable[str] = (),
    compare_map_id: str | None = None,
    revision: int = 0,
    overlays: Mapping[str, Any] | None = None,
) -> MapView:
    """Assemble the payload for one map, or for one map against another.

    `unlocked` is the base map's set. `added` is what the compared map has and
    the base does not; `removed` is the reverse. That ordering makes
    `build_view(unlocked=a, added=d.added, removed=d.removed)` for
    `d = delta.diff_names(a, b)` describe exactly what
    `fray diff --map1 a --map2 b chunks` reports, and a test pins the two
    together.

    **The hull is traced around everything that is not `removed`**, which is
    exactly the compared map's own set: base plus what it gains, minus what it
    loses. A comparison asks what the base *becomes*, so the outline is the
    shape you would end up with, and the browser washes a removed square like
    any other locked one before tinting it red. Tracing the base alone would
    draw the old shape with green squares hanging outside it, which reads as a
    rendering error rather than as a gain.

    Which side is passed as `unlocked` therefore does not change the output:
    `base ∪ added ∪ removed` is the union either way and `added`/`removed`
    decide every label. Passing the base is simply the honest description of
    what the caller has.

    Every input is membership-tested and never read for its value. The map
    payload stores `chunks.unlocked` as `{"12850": "12850"}` - the id again,
    not `True` - so a truthiness check here would be a coincidence rather than
    a contract.
    """
    base = tuple(unlocked)
    gained = tuple(added)
    lost = tuple(removed)

    # `dict.fromkeys` rather than a set: the order the caller gave is the order
    # the browser draws in, so two runs produce byte-identical JSON.
    states: dict[str, CellState] = {}
    for chunk_id in base:
        states.setdefault(chunk_id, CellState.UNLOCKED)
    for chunk_id in gained:
        states[chunk_id] = CellState.ADDED
    for chunk_id in lost:
        # Relabels a base chunk, or introduces one the base never had - which
        # is what happens when the *compared* map is passed as `unlocked`.
        # Either way a removed square is drawn outside the hull.
        states[chunk_id] = CellState.REMOVED

    positions: dict[str, GridPos] = {}
    skipped: list[str] = []
    for chunk_id in states:
        position = grid_position(chunk_id)
        if position is None:
            skipped.append(chunk_id)
        else:
            positions[chunk_id] = position

    # The blob the hull traces: everything currently held, plus what the
    # comparison would gain. A removed chunk is part of the base and so is
    # already in here, which is what puts it inside the outline.
    outlined = frozenset(
        int(chunk_id)
        for chunk_id, state in states.items()
        if chunk_id in positions and state is not CellState.REMOVED
    )
    edges = hull_edges(outlined)

    cells = []
    for chunk_id, position in positions.items():
        region_x, region_y = region_xy(int(chunk_id))
        cells.append(
            ChunkCell(
                chunk_id=chunk_id,
                region_x=region_x,
                region_y=region_y,
                grid_x=position.grid_x,
                grid_y=position.grid_y,
                state=states[chunk_id],
                edges=int(edges.get(int(chunk_id), Edge.NONE)),
            )
        )

    counts = ViewCounts(
        unlocked=sum(1 for state in states.values() if state is CellState.UNLOCKED),
        added=sum(1 for state in states.values() if state is CellState.ADDED),
        removed=sum(1 for state in states.values() if state is CellState.REMOVED),
        skipped=len(skipped),
    )
    return MapView(
        map_id=map_id,
        geometry=MapGeometry(),
        cells=tuple(cells),
        counts=counts,
        compare_map_id=compare_map_id,
        revision=revision,
        skipped=tuple(skipped),
        overlays=dict(overlays or {}),
    )


__all__ = [
    "GRID_COLUMNS",
    "GRID_ROWS",
    "IMAGE_HEIGHT",
    "IMAGE_ORIGIN_X",
    "IMAGE_ORIGIN_Y",
    "IMAGE_WIDTH",
    "MAX_REGION_X",
    "MAX_REGION_Y",
    "MIN_REGION_X",
    "MIN_REGION_Y",
    "PIXELS_PER_CHUNK",
    "REGION_STRIDE",
    "CellState",
    "ChunkCell",
    "Edge",
    "GridPos",
    "MapGeometry",
    "MapView",
    "ViewCounts",
    "build_view",
    "chunk_id_of",
    "grid_position",
    "hull_edges",
    "on_surface",
    "region_xy",
]
