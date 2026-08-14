"""The export's `sections` branch as a directed graph over `(chunk, section)` nodes.

`chunkinfo['sections']` is 1,172 entries - *exactly* the `walkableChunks` key
set - of the form `{chunk: {section: [ref, ...]}}`.

**Upstream is live, so the counts below are measurements with a date on them**
(2026-08-14), not constants. What each one is quoted *for* is the claim beside
it, and that is what `tests/test_graph.py` asserts: the shape is pinned exactly
and the magnitudes only where reaching zero would kill the argument. Two edges
and one `"???"` appeared between two fetches a week apart; neither meant this
module was wrong, and a test that failed on them would have said it was. Two upstream passes consume
it: `findConnectedSections` (worker.js, ported in `sections.py`) and
`selectAllNeighborsCanvas` (index.js:3033-3079, ported in `neighbours.py`).
This module is the shared substrate, and is shaped for a third consumer that
does not exist yet: a search answering "fewest chunk unlocks to reach X".

**Direction is real, not decorative.** `sections[S]` lists what must already be
reachable for you to get *into* `S`, so reachability flows from a listed node
back to the node that lists it. `requirements(n)` is what `n` declares;
`dependents(n)` is the reverse index - the edges naming `n`, whose `source` is
the node `n` opens up. A frontier expansion from the unlocked set walks
`dependents`; `neighbours.py`'s eligibility test walks `requirements`. **125 of
the real export's 6,016 edges have no declared reverse**, so collapsing the two
into one undirected adjacency would invent 125 crossings the game lacks.

Nodes are `(chunk, section)` because that is the export's own `"4651-1"` id
form. A **bare ref means section `0`** - upstream's "the chunk itself", not a
declared section: 660 chunks have only `{"0": [...]}`, the other 512 have 2-9
sections and *never* a `"0"` key. So the node set is declared nodes **union**
referenced nodes, which is how `("11047","0")` and `("11300","0")` get in:
those two chunks are section-split (`1`, `W1`) yet their neighbours reference
them plainly. Upstream reads a bare ref as "that chunk is in the unlocked set"
(index.js:3070), never as "its section 0 is reachable", so those nodes are
correct and simply have no requirements. `sections_of` returns only *declared*
sections, matching `Object.keys(chunkInfo['sections'][id])`, because that is
what upstream iterates.

**`parse_ref` must never be pointed at an arbitrary chunk id.** It splits on the
first `-`, exactly as upstream does (`connection.split('-')[0]`,
index.js:3062-3063), which is only safe because every chunk id in `sections` is
numeric. The export also has 315 *named* chunk keys, 7 of them hyphenated
(`Dorgesh-Kaan`, `Player-owned house`, `Puro-Puro`), and
`parse_ref("Dorgesh-Kaan")` would yield the nonsense node `("Dorgesh","Kaan")`.
Use `chunk_node` for chunk ids; `parse_ref` is for `sections` refs only. Two
functions so the hazard is unrepresentable rather than merely documented.

`"???"` (56 refs) is the export's unresolved-neighbour placeholder. It produces
no edge, and the node carrying it is recorded in `unresolved`. Every one of the
56 has `"???"` as its **only** ref, so those sections have no connection-based
way in at all - only `manualSections` or a `Connect` link opens them. That
"every one" is the claim; the 56 is this week's count of it.

**Nothing is filtered to grid adjacency here.** 37 of the 6,016 edges are not
`±1`/`±256` steps (deltas up to 4,857 - boats, stairs, teleports), and one is a
same-chunk self-loop. `selectAllNeighborsCanvas` only ever *proposes* grid-
adjacent candidates, so `neighbours.py` applies that filter itself; a path
search needs the rest, so the graph is a deliberate superset of what the
neighbour walk traverses.

**Every edge binds its `sectionsLimits` entry at build time.** The gate lives at
the *top level* of the export (`chunkInfo['sectionsLimits']`, read at
index.js:3055), keyed `"<source-node> to <raw ref>"`, and holds only two entries
on the real export. An earlier port read it from `chunkInfo['codeItems']`
instead, where it has never existed - `codeItems` has 32 keys and none is
`sectionsLimits` - so the gate silently evaluated to `{}` and never fired. That
wrong location is recorded rather than quietly dropped because it is the
tempting one: `codeItems` is where most of the export's odds and ends live.
Resolving the gate here, once, at the only place that knows the key format, is
what makes that class of mistake structurally unrepeatable. This module
deliberately does **not** interpret a limit - that is `neighbours.py`'s `Tasks`
check; it only knows *where* the gate is.

**Shaped for the later search.** The intended cost model is 0 to move within a
chunk you already have and 1 to enter a locked one, so "fewest chunk unlocks"
falls out of a 0-1 BFS. Four things that needs, and why each is a field here
rather than work in the search's inner loop: `dependents`, so the frontier
expands in the direction of travel; `Node.chunk` as a plain attribute, so the
cost is an O(1) lookup and no ref string is re-parsed per relaxation;
`Edge.limit` pre-bound, so a gated crossing costs a truthiness test rather than
a dict probe into `sectionsLimits`; and edges stored as **tuples in export
declaration order**, not sets, so ties break identically on every run.
**Caveat to settle before writing that search:** the cost is per *chunk*, not
per edge, so a path leaving a locked chunk and re-entering through a different
section would be double-charged by a naive edge-cost formulation. The standard
fix is a per-chunk super-node (0-cost internal edges to each of its sections,
1-cost into the entry node); this shape supports it, but baking it in now would
change the node set and leak into `neighbours.py`.

**Seams, deliberately not implemented.** (i) `chunks[id].Connect` and
`chunks[id].Sections[n].Connect` (835 top-level + 228 nested) are the
cave/dungeon/instance entrances. They are *not* part of upstream's neighbour
eligibility - `selectAllNeighborsCanvas` never reads them - but they are how a
path reaches a named area, so a future pass adds them as a second edge kind:
construct `Edge` with keyword arguments so a `kind` field is additive. Note the
hazard above - `Connect` targets are chunk ids and must go through `chunk_node`,
and named-area nodes would enter the node set for the first time. (ii)
`questSections` (1,345 entries) is **node**-keyed (`"4656-1"`), not edge-keyed,
and upstream's only consumer is `checkQuestChunks` (index.js:9844-9860), which
warns that an *already-unlocked* chunk needs a quest - it never gates unlocking
or connectivity. If it ever becomes a gate here it is node metadata, not edge
metadata.

`sections.py` is deliberately unchanged by this module's introduction. Its
`_any_connection_open` parses the same ref format and is honest duplication, and
`unlocked_sections`' fixed point is a reachability closure over `dependents` -
but rewiring `findConnectedSections`, which every other derivation module sits
on, is a behaviour-risking refactor that belongs in its own commit with the
opt-in oracle suite run either side.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NamedTuple

from chunksim.model.chunkinfo import ChunkInfo

#: The world grid is 256 chunks tall, so a chunk id is roughly `x * 256 + y`
#: and its orthogonal neighbours are `id ± 1` / `id ± 256` (index.js:3040-3044).
GRID_HEIGHT = 256

#: The section a bare ref denotes: upstream's "the chunk itself". Never a key of
#: a multi-section chunk's `sections` entry - see the module docstring.
WHOLE_CHUNK_SECTION = "0"

#: The export's unresolved-neighbour placeholder.
UNRESOLVED_REF = "???"


class Node(NamedTuple):
    """One `(chunk, section)` pair - the export's `"4651-1"` id form.

    A `NamedTuple` rather than a frozen dataclass: hashable and orderable for
    free (dict keys, and heap/deque entries in the future search), unpackable,
    no per-node overhead over a plain tuple, but `node.chunk` still reads
    correctly in the search's inner loop.
    """

    chunk: str
    section: str


def parse_ref(ref: str) -> Node | None:
    """One `sections` connection string as a node, or `None` for `"???"`.

    Splits on the first `-`, exactly as upstream (index.js:3062-3063). **Only
    valid for refs**, never for arbitrary chunk ids - see `chunk_node` and the
    module docstring.
    """
    if ref == UNRESOLVED_REF:
        return None
    chunk, separator, section = ref.partition("-")
    return Node(chunk, section if separator else WHOLE_CHUNK_SECTION)


def chunk_node(chunk_id: str) -> Node:
    """A chunk id as its whole-chunk node, without ever splitting on `-`.

    The counterpart to `parse_ref`: hyphenated chunk names are real
    (`Dorgesh-Kaan`, `Player-owned house`), so a chunk id must not go through
    ref parsing.
    """
    return Node(chunk_id, WHOLE_CHUNK_SECTION)


def section_suffix(section: str) -> str:
    """Upstream's `sectionStr` (index.js:3054): `""` for section `0`, else `-N`."""
    return "" if section == WHOLE_CHUNK_SECTION else f"-{section}"


def format_ref(node: Node) -> str:
    """A node back in the export's own ref form. Inverse of `parse_ref`."""
    return f"{node.chunk}{section_suffix(node.section)}"


def limit_key(source: Node, ref: str) -> str:
    """The `sectionsLimits` key for a crossing, in upstream's exact string form
    (index.js:3055) - e.g. `"14646-1 to 14902"`."""
    return f"{format_ref(source)} to {ref}"


def grid_neighbours(chunk_id: int) -> tuple[int, int, int, int]:
    """The four orthogonally adjacent chunk ids (index.js:3040-3044)."""
    return (chunk_id - 1, chunk_id + 1, chunk_id - GRID_HEIGHT, chunk_id + GRID_HEIGHT)


def chunk_sort_key(chunk_id: str) -> tuple[int, int, str]:
    """Sort numeric chunk ids numerically and ahead of any named ones.

    `sortSelectedChunks` uses `parseInt` (index.js:3088), which only ever sees
    numeric ids; the named-chunk arm exists so callers can sort a mixed set
    without raising.
    """
    try:
        return (0, int(chunk_id), "")
    except ValueError:
        return (1, 0, chunk_id)


@dataclass(frozen=True)
class Edge:
    """One declared connection: `source` needs `target` to already be reachable.

    `ref` is kept verbatim because it is three things at once - half of
    `limit_key`, what `neighbours.py` branches on to reproduce upstream's
    `connection.includes('-')` test exactly, and what the CLI prints as the
    "via" attribution.
    """

    source: Node
    target: Node
    ref: str
    limit_key: str
    #: The bound `sectionsLimits` entry, or `None` when the crossing is ungated.
    #: Bound at build time so the lookup cannot be got wrong per-caller.
    limit: Mapping[str, Any] | None


@dataclass(frozen=True)
class SectionGraph:
    """The `sections` branch as a directed graph. Built once per invocation."""

    nodes: frozenset[Node]
    #: Node -> the edges it declares (what it needs). Export declaration order.
    requirement_edges: Mapping[Node, tuple[Edge, ...]]
    #: Node -> the edges naming it (what it opens up). The reverse index.
    dependent_edges: Mapping[Node, tuple[Edge, ...]]
    #: Chunk -> its *declared* section nodes, in export order. Deliberately not
    #: derived from `nodes`, which also holds referenced-but-undeclared ones.
    chunk_sections: Mapping[str, tuple[Node, ...]]
    #: Nodes whose only way in is the `"???"` placeholder.
    unresolved: frozenset[Node]

    def requirements(self, node: Node) -> tuple[Edge, ...]:
        return self.requirement_edges.get(node, ())

    def dependents(self, node: Node) -> tuple[Edge, ...]:
        return self.dependent_edges.get(node, ())

    def sections_of(self, chunk_id: str) -> tuple[Node, ...]:
        """The chunk's declared sections, or `()` if it has no `sections` entry
        - which is how non-walkable chunks are excluded (index.js:3050)."""
        return self.chunk_sections.get(chunk_id, ())

    def __contains__(self, node: object) -> bool:
        return node in self.nodes


def build_section_graph(chunk_info: ChunkInfo) -> SectionGraph:
    """Build the graph from `chunkinfo['sections']` and `chunkinfo['sectionsLimits']`.

    Tolerates a missing or wrongly-typed branch at every level, the same way
    `chunkinfo.py`'s accessors do. ~6k edges, trivial next to the export parse.
    """
    sections_data = chunk_info.sections
    limits = chunk_info.sections_limits

    nodes: set[Node] = set()
    requirements: dict[Node, list[Edge]] = {}
    dependents: dict[Node, list[Edge]] = {}
    chunk_sections: dict[str, tuple[Node, ...]] = {}
    unresolved: set[Node] = set()

    for chunk_id, chunk_sections_data in sections_data.items():
        if not isinstance(chunk_id, str) or not isinstance(chunk_sections_data, dict):
            continue
        declared: list[Node] = []
        for section_id, refs in chunk_sections_data.items():
            if not isinstance(section_id, str):
                continue
            source = Node(chunk_id, section_id)
            declared.append(source)
            nodes.add(source)
            if not isinstance(refs, list):
                continue
            for ref in refs:
                if not isinstance(ref, str):
                    continue
                target = parse_ref(ref)
                if target is None:
                    unresolved.add(source)
                    continue
                key = limit_key(source, ref)
                limit = limits.get(key)
                edge = Edge(
                    source=source,
                    target=target,
                    ref=ref,
                    limit_key=key,
                    limit=limit if isinstance(limit, dict) else None,
                )
                nodes.add(target)
                requirements.setdefault(source, []).append(edge)
                dependents.setdefault(target, []).append(edge)
        chunk_sections[chunk_id] = tuple(declared)

    return SectionGraph(
        nodes=frozenset(nodes),
        requirement_edges={node: tuple(edges) for node, edges in requirements.items()},
        dependent_edges={node: tuple(edges) for node, edges in dependents.items()},
        chunk_sections=chunk_sections,
        unresolved=frozenset(unresolved),
    )
