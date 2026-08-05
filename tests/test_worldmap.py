"""Tests for the world-map projection and the hull.

The projection is the load-bearing part: get the y-flip or the origin wrong and
every square lands somewhere plausible but false, which no later test would
catch. `test_lumbridge_is_where_lumbridge_is` is the anchor, and it was checked
against the real image by cropping it rather than by re-reading the arithmetic.
"""

from __future__ import annotations

import pytest

from fray_claude.delta import diff_names
from fray_claude.gui.worldmap import (
    GRID_COLUMNS,
    GRID_ROWS,
    NATIVE_TILE_ZOOM,
    PIXELS_PER_CHUNK,
    TILE_PIXELS,
    TILES_PER_CHUNK,
    CellState,
    Edge,
    build_view,
    chunk_id_of,
    grid_position,
    hull_edges,
    region_xy,
)

#: Lumbridge. Region (50, 50), grid (35, 15), tile 2/0_50_50.png.
LUMBRIDGE = "12850"


def test_lumbridge_is_where_lumbridge_is() -> None:
    """The anchor. Verified by cropping the real image at this rectangle.

    If the y-flip is ever inverted this is the test that says so - everything
    else in the module is self-consistent either way round.
    """
    assert region_xy(12850) == (50, 50)

    position = grid_position(LUMBRIDGE)

    assert position is not None
    assert (position.grid_x, position.grid_y) == (35, 15)
    assert (position.pixel_x, position.pixel_y) == (8960, 3840)


def test_the_y_axis_is_flipped() -> None:
    """A region further north sits *higher* on the image, i.e. a lower row."""
    north = grid_position(str(chunk_id_of(50, 51)))
    south = grid_position(str(chunk_id_of(50, 49)))

    assert north is not None and south is not None
    assert north.grid_y < south.grid_y


def test_the_projection_tiles_the_image_exactly() -> None:
    """The four corners, and no off-by-one at either far edge."""
    top_left = grid_position(str(chunk_id_of(15, 65)))
    bottom_right = grid_position(str(chunk_id_of(62, 32)))

    assert top_left is not None and bottom_right is not None
    assert (top_left.grid_x, top_left.grid_y) == (0, 0)
    assert (bottom_right.grid_x, bottom_right.grid_y) == (GRID_COLUMNS - 1, GRID_ROWS - 1)
    assert bottom_right.pixel_x + PIXELS_PER_CHUNK == GRID_COLUMNS * PIXELS_PER_CHUNK
    assert bottom_right.pixel_y + PIXELS_PER_CHUNK == GRID_ROWS * PIXELS_PER_CHUNK


def test_a_region_round_trips_through_its_id() -> None:
    for chunk_id in (12850, 11833, 6449, 13623):
        assert chunk_id_of(*region_xy(chunk_id)) == chunk_id


def test_a_named_area_has_no_square() -> None:
    """315 of the export's chunk ids are places, not regions."""
    assert grid_position("Abyss") is None
    assert grid_position("Dorgesh-Kaan") is None
    assert grid_position("Player-owned house") is None


def test_an_underground_region_has_no_square() -> None:
    """Numeric, but off the surface rectangle the image covers.

    `4751` is Kurask Lair at region (18, 143) - a real region, nowhere on this
    map. Assuming "numeric implies drawable" draws it at a wrong square rather
    than failing, which is why the check exists at all.
    """
    assert region_xy(4751) == (18, 143)
    assert grid_position("4751") is None
    assert grid_position(str(chunk_id_of(425, 50))) is None


# --- the hull --------------------------------------------------------------


def test_a_lone_chunk_is_outlined_on_all_four_sides() -> None:
    edges = hull_edges({12850})

    assert edges[12850] == Edge.TOP | Edge.BOTTOM | Edge.LEFT | Edge.RIGHT


def test_a_shared_edge_is_drawn_by_neither_side() -> None:
    """The requirement, stated as a test: no border between two unlocked chunks.

    East-west, so the pair differs by the 256 stride.
    """
    west, east = 12850, 12850 + 256
    edges = hull_edges({west, east})

    assert not edges[west] & Edge.RIGHT
    assert not edges[east] & Edge.LEFT
    # Every other side still faces outward.
    assert edges[west] == Edge.TOP | Edge.BOTTOM | Edge.LEFT
    assert edges[east] == Edge.TOP | Edge.BOTTOM | Edge.RIGHT


def test_a_vertical_pair_omits_the_edge_the_y_flip_moves() -> None:
    """`id + 1` is one region north, which is one row *up* on screen.

    The case most likely to be written upside-down, so it is asserted in screen
    terms rather than in id terms.
    """
    lower_id, higher_id = 12850, 12851
    edges = hull_edges({lower_id, higher_id})

    # 12851 is north of 12850, so it is the one drawn above it.
    assert not edges[lower_id] & Edge.TOP
    assert not edges[higher_id] & Edge.BOTTOM
    assert edges[lower_id] & Edge.BOTTOM
    assert edges[higher_id] & Edge.TOP


def test_a_solid_block_has_no_interior_edges() -> None:
    block = {12850, 12851, 12850 + 256, 12851 + 256}
    edges = hull_edges(block)

    drawn = sum(bin(int(edge)).count("1") for edge in edges.values())
    assert drawn == 8  # a 2x2 square has eight outer sides, not sixteen


def test_a_hole_gets_its_own_boundary() -> None:
    """Correct, and worth pinning: the invariant is about adjacency.

    "No edge between two unlocked chunks" does not imply "exactly one closed
    loop" - a ring is outlined on the outside *and* around the gap.
    """
    centre = 12850
    ring = {
        centre + dx * 256 + dy
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
        if (dx, dy) != (0, 0)
    }
    edges = hull_edges(ring)

    # The four chunks orthogonally around the hole each face it.
    assert edges[centre + 1] & Edge.BOTTOM
    assert edges[centre - 1] & Edge.TOP
    assert edges[centre + 256] & Edge.LEFT
    assert edges[centre - 256] & Edge.RIGHT


def test_diagonal_neighbours_do_not_touch() -> None:
    a, b = 12850, 12850 + 256 + 1
    edges = hull_edges({a, b})

    every_side = Edge.TOP | Edge.BOTTOM | Edge.LEFT | Edge.RIGHT
    assert edges[a] == every_side
    assert edges[b] == every_side


def test_the_hull_closes_itself_at_the_edge_of_the_map() -> None:
    """No grid-boundary special case is needed, and this is why.

    The test is membership of the unlocked set, so a chunk on the top row asks
    about a region nobody ever unlocked and gets its outer edge for free.
    """
    top_row = chunk_id_of(50, 65)
    edges = hull_edges({top_row})

    assert edges[top_row] & Edge.TOP


# --- the view --------------------------------------------------------------


def test_locked_chunks_are_absent_rather_than_listed() -> None:
    view = build_view(map_id="fray", unlocked=[LUMBRIDGE])

    assert [cell.chunk_id for cell in view.cells] == [LUMBRIDGE]
    assert view.counts.unlocked == 1
    assert view.geometry.grid_columns * view.geometry.grid_rows == 1632


def test_unplaceable_ids_are_reported_not_dropped() -> None:
    """A canvas showing fewer chunks than `fray show` must explain itself."""
    view = build_view(map_id="fray", unlocked=[LUMBRIDGE, "Abyss", "4751"])

    assert view.skipped == ("Abyss", "4751")
    assert view.counts.skipped == 2
    assert view.counts.unlocked == 3  # counted as held, just not drawable
    assert [cell.chunk_id for cell in view.cells] == [LUMBRIDGE]


def test_added_and_removed_get_their_own_states() -> None:
    gained, lost = str(chunk_id_of(50, 51)), str(chunk_id_of(50, 49))
    view = build_view(
        map_id="a",
        unlocked=[LUMBRIDGE, lost],
        added=[gained],
        removed=[lost],
        compare_map_id="b",
    )
    states = {cell.chunk_id: cell.state for cell in view.cells}

    assert states[LUMBRIDGE] is CellState.UNLOCKED
    assert states[gained] is CellState.ADDED
    assert states[lost] is CellState.REMOVED
    assert view.counts.added == 1
    assert view.counts.removed == 1


def test_the_hull_spans_the_additions_but_not_the_removals() -> None:
    """A gained chunk extends the outline; a lost one sits inside it.

    Tracing the base alone would leave green squares hanging outside the
    border, which reads as a rendering fault rather than as a gain.
    """
    gained = str(chunk_id_of(50, 51))
    view = build_view(map_id="a", unlocked=[LUMBRIDGE], added=[gained], compare_map_id="b")
    edges = {cell.chunk_id: cell.edges for cell in view.cells}

    # The two are vertically adjacent, so the border between them is not drawn.
    assert not edges[LUMBRIDGE] & Edge.TOP
    assert not edges[gained] & Edge.BOTTOM

    lost = str(chunk_id_of(50, 51))
    removed_view = build_view(
        map_id="a", unlocked=[LUMBRIDGE, lost], removed=[lost], compare_map_id="b"
    )
    removed_edges = {cell.chunk_id: cell.edges for cell in removed_view.cells}
    # Dropped from the blob, so the base chunk regains the edge it had shared.
    assert removed_edges[LUMBRIDGE] & Edge.TOP


def test_the_view_agrees_with_fray_diff() -> None:
    """`build_view` and `delta.diff_names` must describe the same comparison.

    `fray diff --map1 a --map2 b chunks` reports "added" as present in map2 and
    absent from map1. A renderer that read it the other way would paint gains
    red, so the two are pinned together the way `tests/test_delta.py` pins
    `unlock` and `delta`.
    """
    before = {LUMBRIDGE: LUMBRIDGE, "12851": "12851"}
    after = {LUMBRIDGE: LUMBRIDGE, "13106": "13106"}
    branch = diff_names(before, after)

    view = build_view(
        map_id="a",
        unlocked=before,
        added=branch.added,
        removed=branch.removed,
        compare_map_id="b",
    )
    states = {cell.chunk_id: cell.state for cell in view.cells}

    assert states["13106"] is CellState.ADDED
    assert states["12851"] is CellState.REMOVED


def test_the_payload_serialises() -> None:
    view = build_view(map_id="fray", unlocked=[LUMBRIDGE], revision=123)
    payload = view.as_dict()

    assert payload["map_id"] == "fray"
    assert payload["revision"] == 123
    assert payload["cells"][0]["state"] == "unlocked"
    assert payload["geometry"]["pixels_per_chunk"] == PIXELS_PER_CHUNK
    assert payload["overlays"] == {}


def test_overlays_are_carried_through() -> None:
    """The seam the planned roll heatmaps drop into."""
    view = build_view(map_id="fray", unlocked=[LUMBRIDGE], overlays={"heat": {"12850": 4}})

    assert view.as_dict()["overlays"] == {"heat": {"12850": 4}}


@pytest.mark.parametrize("value", ["", "  ", "-1", "12.5", "12850x"])
def test_a_malformed_id_is_skipped_rather_than_raising(value: str) -> None:
    assert grid_position(value) is None


def test_one_tile_is_one_chunk_at_the_native_zoom() -> None:
    """The property the whole renderer rests on.

    The wiki's tiles are indexed on the game's own coordinates - `256 / 2**z`
    game tiles per 256px tile - so at z=2 a tile spans exactly one 64x64
    region and its index *is* the chunk id decomposed. That is what lets
    `app.js` draw a chunk's square straight from a single file, and it is
    asserted rather than assumed because a re-tiling upstream would break it
    silently.
    """
    span = TILE_PIXELS // 2**NATIVE_TILE_ZOOM

    assert span == TILES_PER_CHUNK
    assert TILE_PIXELS // span * TILES_PER_CHUNK == PIXELS_PER_CHUNK

    # Lumbridge: chunk 12850 -> tile (50, 50), *not* flipped. Only the drawing
    # inverts y; the tile index counts north like the game does.
    assert region_xy(int(LUMBRIDGE)) == (50, 50)
