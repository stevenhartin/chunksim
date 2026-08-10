"""Tests for the section-level connectivity graph."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from fray_claude.cache import read_chunkinfo
from fray_claude.chunkinfo import ChunkInfo
from fray_claude.graph import (
    Node,
    build_section_graph,
    chunk_node,
    chunk_sort_key,
    format_ref,
    grid_neighbours,
    limit_key,
    parse_ref,
    section_suffix,
)

_REAL_CHUNKINFO = os.environ.get("FRAY_CHUNKINFO")


def _graph(**data: Any) -> Any:
    return build_section_graph(ChunkInfo(data))


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("4139", Node("4139", "0")),
        ("4651-1", Node("4651", "1")),
        ("4907-W1", Node("4907", "W1")),
    ],
)
def test_parse_ref_reads_every_ref_form(ref: str, expected: Node) -> None:
    assert parse_ref(ref) == expected


def test_parse_ref_rejects_the_unresolved_placeholder() -> None:
    assert parse_ref("???") is None


@pytest.mark.parametrize("ref", ["4139", "4651-1", "4907-W1"])
def test_format_ref_round_trips_every_ref_form(ref: str) -> None:
    node = parse_ref(ref)
    assert node is not None
    assert format_ref(node) == ref


def test_chunk_node_never_splits_a_hyphenated_area_name() -> None:
    """Why `chunk_node` exists at all: `parse_ref` is for refs, not chunk ids.

    Seven chunk keys in the export are hyphenated names. Routing one through
    ref parsing yields a nonsense node, which is pinned here so the two
    functions are never collapsed into one.
    """
    assert chunk_node("Dorgesh-Kaan") == Node("Dorgesh-Kaan", "0")
    assert parse_ref("Dorgesh-Kaan") == Node("Dorgesh", "Kaan")


def test_section_suffix_is_empty_only_for_the_whole_chunk_section() -> None:
    assert section_suffix("0") == ""
    assert section_suffix("1") == "-1"
    assert section_suffix("W1") == "-W1"


def test_limit_key_matches_upstreams_string_form() -> None:
    # The two real entries in the export, both directions.
    assert limit_key(Node("14646", "1"), "14902") == "14646-1 to 14902"
    assert limit_key(Node("14902", "0"), "14646-1") == "14902 to 14646-1"


def test_grid_neighbours_are_plus_minus_one_and_the_grid_height() -> None:
    assert grid_neighbours(14646) == (14645, 14647, 14390, 14902)


def test_chunk_sort_key_orders_numeric_ids_numerically() -> None:
    assert sorted(["1000", "999", "20"], key=chunk_sort_key) == ["20", "999", "1000"]


def test_chunk_sort_key_puts_named_chunks_after_numeric_ones() -> None:
    assert sorted(["Zanaris", "999"], key=chunk_sort_key) == ["999", "Zanaris"]


def test_requirements_are_the_nodes_own_declared_refs_in_export_order() -> None:
    graph = _graph(sections={"100": {"1": ["200", "300-2"]}})

    refs = [edge.ref for edge in graph.requirements(Node("100", "1"))]
    assert refs == ["200", "300-2"]


def test_dependents_is_the_reverse_index() -> None:
    graph = _graph(sections={"100": {"1": ["200"]}})

    edges = graph.dependents(Node("200", "0"))
    assert len(edges) == 1
    assert edges[0].source == Node("100", "1")


def test_an_asymmetric_edge_appears_in_one_direction_only() -> None:
    """The graph is directed: 125 real edges have no declared reverse."""
    graph = _graph(sections={"100": {"0": ["200"]}, "200": {"0": []}})

    assert graph.dependents(Node("200", "0"))
    assert graph.requirements(Node("200", "0")) == ()


def test_an_unresolved_ref_produces_no_edge_but_records_the_node() -> None:
    graph = _graph(sections={"100": {"1": ["???"]}})

    assert Node("100", "1") in graph.unresolved
    assert graph.requirements(Node("100", "1")) == ()


def test_a_referenced_but_undeclared_node_joins_the_node_set() -> None:
    """The 11047/11300 case: a section-split chunk referenced plainly.

    The node is real - upstream reads a bare ref as "that chunk is unlocked" -
    but it is not a *declared* section, so `sections_of` must not report it.
    """
    graph = _graph(sections={"100": {"0": ["11047"]}, "11047": {"1": [], "W1": []}})

    assert Node("11047", "0") in graph.nodes
    assert graph.sections_of("11047") == (Node("11047", "1"), Node("11047", "W1"))


def test_sections_of_is_empty_for_a_chunk_with_no_sections_entry() -> None:
    assert _graph(sections={}).sections_of("100") == ()


def test_a_non_grid_adjacent_edge_is_kept() -> None:
    """38 real edges are boats/stairs/teleports, not grid steps. The graph is a
    deliberate superset of what `neighbours.py` traverses."""
    graph = _graph(sections={"100": {"0": ["1123"]}})

    assert [edge.target for edge in graph.requirements(Node("100", "0"))] == [Node("1123", "0")]


def test_a_top_level_sections_limit_binds_to_the_edge_it_keys() -> None:
    graph = _graph(
        sections={"100": {"1": ["200", "300"]}},
        sectionsLimits={"100-1 to 200": {"Tasks": {"Do it": "Quest"}}},
    )

    gated, ungated = graph.requirements(Node("100", "1"))
    assert gated.limit == {"Tasks": {"Do it": "Quest"}}
    assert gated.limit_key == "100-1 to 200"
    assert ungated.limit is None


def test_a_sections_limit_under_code_items_is_ignored() -> None:
    """`sectionsLimits` is a *top-level* export key (index.js:3055).

    An earlier port read `codeItems['sectionsLimits']`, which has never
    existed, so the gate never fired. The decoy here pins that the wrong
    location stays inert.
    """
    graph = _graph(
        sections={"100": {"1": ["200"]}},
        codeItems={"sectionsLimits": {"100-1 to 200": {"Tasks": {"Do it": "Quest"}}}},
    )

    (edge,) = graph.requirements(Node("100", "1"))
    assert edge.limit is None


def test_a_malformed_sections_branch_is_tolerated() -> None:
    graph = _graph(sections={"100": "nonsense", "200": {"0": "nonsense"}, "300": {"0": [7, "400"]}})

    assert graph.sections_of("100") == ()
    assert graph.requirements(Node("200", "0")) == ()
    assert [edge.ref for edge in graph.requirements(Node("300", "0"))] == ["400"]


def test_a_missing_sections_branch_builds_an_empty_graph() -> None:
    graph = _graph()

    assert graph.nodes == frozenset()
    assert graph.unresolved == frozenset()


@pytest.mark.skipif(
    not _REAL_CHUNKINFO, reason="set FRAY_CHUNKINFO to a raw export to run this"
)
def test_the_real_export_builds_a_graph_matching_its_sections_branch() -> None:
    """Opt-in: the structural facts the module docstring rests on.

    These are anchored counts rather than magic numbers - each one is a claim
    the docstring makes, and a change to any of them means the export changed
    shape and the docstring needs revisiting.
    """
    assert _REAL_CHUNKINFO is not None
    info = ChunkInfo(read_chunkinfo(override=Path(_REAL_CHUNKINFO)))
    graph = build_section_graph(info)

    assert set(info.sections) == set(info.walkable_chunks)

    edges = [edge for node in graph.chunk_sections for edge in _all_edges(graph, node)]
    assert all(edge.target.chunk in info.sections for edge in edges)

    declared = {node for nodes in graph.chunk_sections.values() for node in nodes}
    assert graph.nodes - declared == {Node("11047", "0"), Node("11300", "0")}

    # Every `"???"` node has that placeholder as its only way in.
    assert all(graph.requirements(node) == () for node in graph.unresolved)

    gated = [edge for edge in edges if edge.limit is not None]
    assert {edge.limit_key for edge in gated} == {"14646-1 to 14902", "14902 to 14646-1"}

    # Reciprocity is strict: S -> T counts as reversed only if T itself
    # declares an edge back to S. 125 do not, which is why the graph must
    # stay directed.
    declared_edges = {(edge.source, edge.target) for edge in edges}
    unreciprocated = [edge for edge in edges if (edge.target, edge.source) not in declared_edges]
    assert len(unreciprocated) == 125
    assert len(edges) == 6014
    assert len(graph.unresolved) == 55


def _all_edges(graph: Any, chunk_id: str) -> list[Any]:
    return [edge for node in graph.sections_of(chunk_id) for edge in graph.requirements(node)]
