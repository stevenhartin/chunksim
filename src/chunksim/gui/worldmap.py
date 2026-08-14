"""Where a chunk sits on upstream's world map, and where the unlocked blob ends.

Pure and I/O-free: everything here is arithmetic over chunk ids plus the frozen
result classes the browser is sent as JSON. `server.py` is the adapter that
turns a request into a `MapView` and back into bytes, the same way `cli.py`
holds argparse and nothing else.

**This lives in `gui/` rather than in the library because all of it is about
one particular map.** The 53x180 grid, the tile pyramid and the flipped y axis
are properties of how the OSRS wiki tiles the world, not facts about the game
that the rest of the project could use. The one piece that *is* world knowledge
is `region_xy`, and `dps_bridge.in_wilderness` already inlines it; if the
library ever wants that decoder, the move is to push those two functions down
into the library rather than to host this module up there and have a library
module import from an app package.

**The projection, verified against the image rather than derived on paper.**
A chunk id *is* an OSRS region id, so:

    region_x, region_y = chunk_id >> 8, chunk_id & 0xFF
    grid_x = region_x - MIN_REGION_X          # 14
    grid_y = MAX_REGION_Y - region_y          # 197 - y, and note the direction

**The y axis is flipped**, which is the one thing here that will look like a
bug: the screen's origin is the world's *north*-west corner and rows grow
southward, while OSRS's `region_y` grows *northward*. Lumbridge is chunk 12850
= region (50, 50) = grid (36, 147), and its tile really is
`.../tiles/rendered/-1/2/0_50_50.png` - checked, not assumed, because every
later bug in this module would otherwise look like a hull bug.

**The tile URLs do *not* flip y.** The tile index counts north like the game
does, so a tile is addressed `(region_x, region_y)` and only the *drawing*
inverts. Mixing those two up puts the world upside down, which at least fails
loudly; getting it right in one place and not the other does not.

**Underground is on the same grid, not on a second one.** The Full Map tile
set covers region y up to 197, so Kurask Lair at region (18, 143) has a square
like anything else - it simply sits far to the *north* of the overworld,
because the y-flip puts high region y at the top. That is how the wiki lays it
out too. 1,905 of the export's 1,919 numeric ids are placeable this way,
against 1,176 when only the surface was drawn.

**`grid_position` is about *regions*, and two kinds of id are not one:**

- **Named areas.** 315 of the export's 2,234 chunk ids are strings like
  `Abyss` or `Player-owned house`, with no coordinates at all.
- **Fourteen numeric pointers**, at synthetic regions like (425, 201) that no
  tiling covers. They carry a `Name` and nothing else.

Both are `None` here and both are resolved by `build_view` instead, which has
`chunkinfo.area_names()` to hand: a name becomes the regions carrying it, and
a `<parent>#<part>` with nowhere to go borrows its parent's. **Given the whole
export, that leaves nothing unplaced** - 2,234 ids become 1,905 cells and an
empty `skipped`.

`skipped` is therefore now about a *map* holding something this build cannot
place, not about the export having ids it never could. A caller that assumes
"numeric implies drawable" still gets a wrong square rather than an error,
which is why the check is one function and every path goes through it, and
`MapView.skipped` still carries whatever was dropped so a canvas showing fewer
chunks than `chunksim show` counted explains itself.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import IntFlag, StrEnum
from typing import Any

#: An OSRS region is 64x64 tiles, and the wiki's tiles draw a 256-pixel square
#: per region at their native zoom - 4 pixels per game tile. Every other number
#: here follows from that and is asserted below rather than trusted.
TILES_PER_CHUNK = 64
PIXELS_PER_TILE = 4
PIXELS_PER_CHUNK = TILES_PER_CHUNK * PIXELS_PER_TILE

#: The tile pyramid the browser draws from, and **the reason this projection
#: got simpler rather than more complicated when the map moved.** The tiles are
#: indexed on the game's own coordinates - `256 / 2**z` game tiles per 256px
#: tile, y counting northward - so at `NATIVE_TILE_ZOOM` one tile *is* one
#: chunk and its index *is* the chunk id decomposed. There is no image origin,
#: no border and no single-image size to keep in agreement any more: a chunk's
#: square is its own file. See `api.MAP_TILE_URL`, and `app.js`'s `drawTiles`
#: for how a level is picked.
TILE_PIXELS = 256
NATIVE_TILE_ZOOM = 2
MIN_TILE_ZOOM = -3
MAX_TILE_ZOOM = 3

#: The rectangle the map covers, in OSRS region coordinates - **the whole
#: world, not the surface.** These are `basemaps.json`'s bounds for the
#: `Full Map` tile set (`api.MAP_TILE_MAP_ID`), which is the one that carries
#: the dungeons, instances and boss rooms as well as the overworld.
#:
#: They were narrower once, and that was a real bug rather than a simpler
#: choice: the surface-only rectangle (x 15-62, y 32-65) clipped five chunks
#: the export actually holds - 6722, 7234, 7490, 11842 and 13122, all at
#: region y 66 - and reported them as unplaceable alongside the genuinely
#: unplaceable ones, where nothing distinguished the two.
#:
#: To re-derive after a re-render: read `versions/<v>/basemaps.json`, find the
#: entry whose `mapId` is -1, and divide its `bounds` by 64. Hardcoded rather
#: than fetched because the projection has to be a constant - `grid_position`
#: is called from pure code that has no business making a request - and
#: because a world that grows makes these too small, which shows up as chunks
#: in `skipped` rather than as anything silent.
MIN_REGION_X = 14
MAX_REGION_X = 66
MIN_REGION_Y = 18
MAX_REGION_Y = 197

GRID_COLUMNS = MAX_REGION_X - MIN_REGION_X + 1
GRID_ROWS = MAX_REGION_Y - MIN_REGION_Y + 1

#: The id-space step between horizontally adjacent chunks. `region_x` occupies
#: the high byte, so a step east is +256 and a step *north* is +1.
REGION_STRIDE = 256

#: What separates a named area from a part of it: `Brimhaven Dungeon#Section
#: 1`, `Karuulm Slayer Dungeon#Lobby`. **Not markup** - `challenges.py`'s
#: `~|...|~` is markup and this is a real character in a real name, one of the
#: several the Firebase codec escapes and restores. `build_view` uses it for
#: one narrow fallback; see its docstring for why the separator alone is not
#: the condition.
AREA_SUBDIVISION = "#"

# One tile per chunk at the native zoom is the whole basis of the renderer. If
# the wiki ever re-tiles at a different scale this stops holding, and failing at
# import is far kinder than drawing every square in the wrong place.
assert TILE_PIXELS // (TILE_PIXELS // 2**NATIVE_TILE_ZOOM) * TILES_PER_CHUNK == PIXELS_PER_CHUNK
assert TILE_PIXELS // 2**NATIVE_TILE_ZOOM == TILES_PER_CHUNK
assert MIN_TILE_ZOOM <= NATIVE_TILE_ZOOM <= MAX_TILE_ZOOM


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


def on_map(region_x: int, region_y: int) -> bool:
    """Whether a region falls inside the rectangle the tiles cover.

    Named `on_surface` once, which stopped being true when the base layer
    became the Full Map: most of what passes now is *underground*.
    """
    return (
        MIN_REGION_X <= region_x <= MAX_REGION_X
        and MIN_REGION_Y <= region_y <= MAX_REGION_Y
    )


@dataclass(frozen=True)
class GridPos:
    """A chunk's cell on the grid, and its pixel origin at native zoom."""

    grid_x: int
    grid_y: int

    @property
    def pixel_x(self) -> int:
        """This cell's left edge, in a whole-world image at native zoom."""
        return self.grid_x * PIXELS_PER_CHUNK

    @property
    def pixel_y(self) -> int:
        """This cell's top edge, in a whole-world image at native zoom."""
        return self.grid_y * PIXELS_PER_CHUNK


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
    if not on_map(region_x, region_y):
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

    pixels_per_chunk: int = PIXELS_PER_CHUNK
    grid_columns: int = GRID_COLUMNS
    grid_rows: int = GRID_ROWS
    tile_pixels: int = TILE_PIXELS
    native_tile_zoom: int = NATIVE_TILE_ZOOM
    min_tile_zoom: int = MIN_TILE_ZOOM
    max_tile_zoom: int = MAX_TILE_ZOOM

    def as_dict(self) -> dict[str, Any]:
        return {
            "pixels_per_chunk": self.pixels_per_chunk,
            "grid_columns": self.grid_columns,
            "grid_rows": self.grid_rows,
            "tile_pixels": self.tile_pixels,
            "native_tile_zoom": self.native_tile_zoom,
            "min_tile_zoom": self.min_tile_zoom,
            "max_tile_zoom": self.max_tile_zoom,
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
    #: The named area this region is part of, when it is part of one -
    #: `Kurask Lair`, `Karuulm Slayer Dungeon`. `None` for the 1,396 regions
    #: the export gives no name.
    area: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "region_x": self.region_x,
            "region_y": self.region_y,
            "grid_x": self.grid_x,
            "grid_y": self.grid_y,
            "state": str(self.state),
            "edges": self.edges,
            "area": self.area,
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
    #: it to notice a `chunksim fetch` in another terminal; it is deliberately not
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
    areas: Mapping[str, str] | None = None,
) -> MapView:
    """Assemble the payload for one map, or for one map against another.

    `unlocked` is the base map's set. `added` is what the compared map has and
    the base does not; `removed` is the reverse. That ordering makes
    `build_view(unlocked=a, added=d.added, removed=d.removed)` for
    `d = delta.diff_names(a, b)` describe exactly what
    `chunksim diff --map1 a --map2 b chunks` reports, and a test pins the two
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

    **`areas` is `chunkinfo.area_names()` and is what lets a named area be
    drawn at all.** Without it `Abyss` is an id with no square; with it, the
    name resolves to the numbered chunks that carry it - the regions the place
    actually occupies - and those get cells. A resolved id is *not* a second
    cell on top of the numeric one: when a map holds both `Abyss` and its
    region, one cell comes out, because two cells on one square would put two
    hull edges there and count the square twice.

    **A subdivision with no square of its own falls back to its parent's.**
    Fourteen ids in the export are pure pointers - they carry a `Name` and
    nothing else, at synthetic regions like (425, 201) that no tiling covers -
    and they are all `<parent>#Section N`: `Brimhaven Dungeon` sections 1-7 and
    `Yanille Agility Dungeon` sections 1-7. Both parents *are* placeable, so
    the honest square for a section is the dungeon's.

    **The condition is "has no square", not "has a `#`"**, and the difference
    is the whole rule: 59 named areas contain a `#` and **52 of them already
    have their own region** (`Karuulm Slayer Dungeon#Lobby` is region 5280).
    Firing on the separator would move those onto their parent and lose the
    detail the export went to the trouble of recording. Of the remaining
    seven, the ones whose parent has no region either - `Barbarian
    Assault#Basement`, and 38 like it - stay unplaced, which is the truth.

    Every input is membership-tested and never read for its value. The map
    payload stores `chunks.unlocked` as `{"12850": "12850"}` - the id again,
    not `True` - so a truthiness check here would be a coincidence rather than
    a contract.
    """
    # A named area to the numbered chunks it occupies. Built once and only
    # when there is something to look up, so the ordinary all-numeric map pays
    # nothing for a feature it does not use.
    regions_of: dict[str, list[str]] = {}
    if areas:
        for chunk_id, area in areas.items():
            regions_of.setdefault(area, []).append(chunk_id)

    def drawable(chunk_ids: Iterable[str]) -> bool:
        return any(grid_position(chunk_id) is not None for chunk_id in chunk_ids)

    def expand(chunk_id: str) -> list[str]:
        """A named id becomes the regions it names; anything else stays put.

        With one fallback, and only when there is otherwise nowhere to draw:
        a `<parent>#<part>` subdivision borrows its parent's regions. See the
        docstring on why the test is "nowhere to draw" rather than "has a
        `#`".
        """
        if chunk_id.isdigit():
            resolved = [chunk_id]
            name = (areas or {}).get(chunk_id, "")
        else:
            resolved = list(regions_of.get(chunk_id) or [chunk_id])
            name = chunk_id
        if drawable(resolved):
            return resolved

        parent = name.split(AREA_SUBDIVISION, 1)[0] if AREA_SUBDIVISION in name else ""
        inherited = regions_of.get(parent) or []
        return list(inherited) if drawable(inherited) else resolved

    base = tuple(unlocked)
    gained = tuple(added)
    lost = tuple(removed)

    # `dict.fromkeys` rather than a set: the order the caller gave is the order
    # the browser draws in, so two runs produce byte-identical JSON.
    states: dict[str, CellState] = {}
    for chunk_id in base:
        for resolved in expand(chunk_id):
            states.setdefault(resolved, CellState.UNLOCKED)
    for chunk_id in gained:
        for resolved in expand(chunk_id):
            states[resolved] = CellState.ADDED
    for chunk_id in lost:
        # Relabels a base chunk, or introduces one the base never had - which
        # is what happens when the *compared* map is passed as `unlocked`.
        # Either way a removed square is drawn outside the hull.
        for resolved in expand(chunk_id):
            states[resolved] = CellState.REMOVED

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
                area=(areas or {}).get(chunk_id),
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
    "AREA_SUBDIVISION",
    "GRID_COLUMNS",
    "GRID_ROWS",
    "MAX_TILE_ZOOM",
    "MIN_TILE_ZOOM",
    "NATIVE_TILE_ZOOM",
    "MAX_REGION_X",
    "MAX_REGION_Y",
    "MIN_REGION_X",
    "MIN_REGION_Y",
    "PIXELS_PER_CHUNK",
    "TILE_PIXELS",
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
    "on_map",
    "region_xy",
]
