"""Which chunks are eligible to be unlocked next, and the number each carries.

Port of `selectAllNeighborsCanvas` (index.js:3033-3079) plus
`sortSelectedChunks` (index.js:3086-3090), on top of `graph.py`. Upstream
reaches it two ways: automatically after a roll when
`chunkNeighboursOptions.autoWalkableRollable` is on, and from the clipboard
menu's "assign" action (index.js:4652) - the "assign numbers to neighbouring
chunks" button this module is named for. Both `chunkNeighboursOptions` flags are
`false` on the real map.

A chunk is eligible if it is orthogonally grid-adjacent to *any* unlocked chunk
(`id ± 1`, `id ± 256`), is "gray" (`checkIfGray`, index.js:2735 - absent from
`unlocked`/`selected`/`potential`/`blacklisted`), passes the `F2P` walkability
test when that rule is on, has a `chunkinfo['sections']` entry at all (only the
1,172 walkable chunks do), and has **one of its own sections declaring a
connection to something already reachable**, subject to that connection's
`sectionsLimits` gate.

**Numbering is by descending numeric chunk id, 1-based: number 1 is the
*highest* id.** `sortSelectedChunks` re-sorts the whole selected array on every
rebuild, so the push order the walk happens to produce is irrelevant. The number
is **display only** - the roll picks uniformly over
`Object.keys(tempChunks['selected'])` (index.js:3396-3398) and reads the number
back afterwards purely for the modal (`sNum = tempSelectedChunks.indexOf(...) +
1`, index.js:3400). `neighbour_pool` therefore returns ids in ascending order
and the numbering does not bias the roll.

**`sectionsLimits` is a *top-level* export key** (`chunkInfo['sectionsLimits']`,
index.js:3055). An earlier version of this port read
`chunkInfo['codeItems']['sectionsLimits']`, which has never existed - `codeItems`
has 32 keys and none is that - so the gate always evaluated to `{}` and never
blocked anything. That wrong location is recorded here rather than quietly
deleted because it is the tempting one: `codeItems` is where most of the
export's odds and ends live. `ChunkInfo.sections_limits` has exposed the right
branch all along, and `graph.py` now binds it to the edge, so the lookup cannot
be got wrong again. The fix changes no answer for *this* map, and the reason is
worth recording because it is not "the gate is harmless": the export's only two
entries gate the crossing between `14646-1` (Port Phasmatys) and `14902` (the
School Boat), and **both chunks are already unlocked**, so neither can ever be a
candidate. The gate is unobservable from the map's own state, and the
regression test therefore has to hold `{14902}` alone and watch `14646` - where
the unfixed code returned `["14646"]` and this one returns `[]`.

**A failed gate abandons the whole section, not just that connection.** Upstream
iterates a section's connection list with `.some(...)`, and the failed-gate
branch does `return true` (index.js:3060), which terminates `.some()` for that
entire section - the section's remaining connections are never tested. An
earlier version of this port used `continue` and kept testing them.
Abandonment is per-*section*: the `forEach` over the candidate's sections is
unaffected, so another section can still qualify the chunk. The success branch,
by contrast, returns `undefined`, so `.some()` does keep going after a push -
but the `!selected.hasOwnProperty(newChunkId)` guard (index.js:3070) makes every
further push a no-op, so returning at the first qualifying connection is
behaviourally identical and is what `_qualifying_edge` does. On the current
export the difference is unobservable, because both `sectionsLimits` entries
gate the **last** connection in their section's list (`14646-1 ->
["14647-1","14902"]`, `14902-0 -> ["14646-1"]`), so `continue` and abandon agree.
It is recorded and tested anyway: it is a genuine control-flow divergence, and
one added ref would expose it.

The reachability test branches on **`edge.ref`, not on the target's section
id**. Upstream tests `connection.includes('-')` (index.js:3065), not "is this
section 0". The two are equivalent on today's export - zero refs end in `-0` -
but they diverge the moment a `"4139-0"` ref appears: upstream would probe
`unlockedSections['4139']['0']`, which `findConnectedSections` never sets
because it skips section `0` outright (`sections.py`), so it would read false,
whereas a section-based branch would fall through to the unlocked-membership
test and could read true.

**The `via_*` attribution is this project's addition** - upstream records only
*that* a chunk qualified, never why. It is not an arbitrary tiebreak: it is the
`(section, connection)` upstream's own `.some()` fires on, i.e. the first
qualifying pair in export declaration order, respecting section abandonment. It
is independent of which unlocked chunk proposed the candidate, because the
eligibility test scans the *candidate's own* refs against the whole reachable
set rather than against the chunk you came from - so the answer does not depend
on the iteration order of the `unlocked` mapping.

**`selectNeighborsCanvas` (index.js:3009-3029) is deliberately not ported.** It
is the per-roll UI convenience under `chunkNeighboursOptions.neighbors`; it
early-returns entirely when `autoWalkableRollable` is on (the two are mutually
exclusive); and its gating is *strictly weaker* - `checkIfGray` plus, optionally,
a bare `walkableRollable` list membership test, and **no sections, connections
or `sectionsLimits` check whatsoever** - so it can mark chunks selected that are
not actually reachable. It also never calls `sortSelectedChunks`, so the numbers
it writes are push order, not descending id. A different, looser answer to a
different question.

`checkIfGray`'s `potential` and `blacklisted` branches are not modelled because
nothing can populate them: a fetched payload's `chunks` holds only `unlocked`
(plus the sticker branches), and `settings.chunkNeighboursOptions` is all-false,
so upstream never writes the others for this map. Manual chunk selection and
blacklisting, and the `roll2`/`roll5` bonus rerolls, stay out for the same
reason `simulate.py` leaves them out - they are user-interaction features, not
part of eligibility.

Region filters (`rollingChunksOptions`) do **not** apply here -
`selectAllNeighborsCanvas` never references them. They only ever gate the
bootstrap "Random Start" pool, which stays in `simulate.py`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from fray_claude.graph import (
    Edge,
    Node,
    SectionGraph,
    build_section_graph,
    chunk_sort_key,
    grid_neighbours,
)
from fray_claude.pipeline import Derived, MapState


@dataclass(frozen=True)
class Neighbour:
    """One eligible chunk, with the number upstream's canvas puts on it."""

    #: 1-based, by descending chunk id - number 1 is the *highest* id.
    number: int
    chunk_id: str
    nickname: str | None
    #: The candidate's own section that qualified, and the raw connection
    #: string it declared. This project's addition - see the module docstring.
    via_section: str
    via_ref: str

    @property
    def node(self) -> Node:
        return Node(self.chunk_id, self.via_section)

    def as_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "chunk_id": self.chunk_id,
            "nickname": self.nickname,
            "via_section": self.via_section,
            "via_ref": self.via_ref,
        }


def assign_numbers(chunk_ids: Iterable[str]) -> dict[str, int]:
    """Port of `sortSelectedChunks` (index.js:3086-3090): 1-based numbers by
    descending numeric chunk id."""
    ordered = sorted(set(chunk_ids), key=chunk_sort_key, reverse=True)
    return {chunk_id: number for number, chunk_id in enumerate(ordered, start=1)}


def _limit_met(limit: Mapping[str, Any], valid: Mapping[str, Mapping[str, Any]]) -> bool:
    """Whether a `sectionsLimits` entry's `Tasks` are all currently valid.

    A non-string skill value fails the gate rather than being skipped:
    upstream's `globalValids.hasOwnProperty(<non-string>)` is false, i.e.
    *invalid* (index.js:3057-3059). Every real value is `"Quest"`.
    """
    tasks = limit.get("Tasks")
    if not isinstance(tasks, dict):
        return True
    for task_name, task_skill in tasks.items():
        if not isinstance(task_skill, str):
            return False
        if task_name not in valid.get(task_skill, {}):
            return False
    return True


def _qualifying_edge(
    graph: SectionGraph,
    candidate: str,
    unlocked: Mapping[str, bool],
    reachable_sections: Mapping[str, Mapping[str, bool]],
    valid: Mapping[str, Mapping[str, Any]],
) -> Edge | None:
    """The first connection that makes `candidate` reachable, or `None`.

    Mirrors upstream's nested `forEach`/`.some` exactly: the `break` is the
    `.some()` callback's `return true` on a failed gate, which abandons that
    *section* while leaving the remaining sections to be tried.
    """
    for node in graph.sections_of(candidate):
        for edge in graph.requirements(node):
            if edge.limit is not None and not _limit_met(edge.limit, valid):
                break
            if "-" in edge.ref:
                if reachable_sections.get(edge.target.chunk, {}).get(edge.target.section):
                    return edge
            elif edge.target.chunk in unlocked:
                return edge
    return None


def eligible_neighbours(
    state: MapState,
    unlocked: Mapping[str, bool],
    current: Derived,
    *,
    graph: SectionGraph | None = None,
) -> list[Neighbour]:
    """The chunks eligible to be unlocked next, in number order.

    Pass `graph` to reuse one across calls - `simulate_rolls` builds it once
    per run rather than once per roll.
    """
    section_graph = graph if graph is not None else build_section_graph(state.chunk_info)
    walkable_f2p = set(state.chunk_info.walkable_chunks_f2p)
    f2p = state.rules.get("F2P") is True

    qualifying: dict[str, Edge] = {}
    for chunk_id_str in unlocked:
        try:
            chunk_id = int(chunk_id_str)
        except ValueError:
            continue  # area names aren't grid-addressable
        for candidate_id in grid_neighbours(chunk_id):
            candidate = str(candidate_id)
            if candidate in unlocked or candidate in qualifying:
                continue
            if f2p and candidate not in walkable_f2p:
                continue
            edge = _qualifying_edge(
                section_graph,
                candidate,
                unlocked,
                current.reachable_sections,
                current.challenges.valid,
            )
            if edge is not None:
                qualifying[candidate] = edge

    numbers = assign_numbers(qualifying)
    return sorted(
        (
            Neighbour(
                number=numbers[candidate],
                chunk_id=candidate,
                nickname=_nickname(state, candidate),
                via_section=edge.source.section,
                via_ref=edge.ref,
            )
            for candidate, edge in qualifying.items()
        ),
        key=lambda neighbour: neighbour.number,
    )


def neighbour_pool(
    state: MapState,
    unlocked: Mapping[str, bool],
    current: Derived,
    *,
    graph: SectionGraph | None = None,
) -> list[str]:
    """The eligible chunk ids, sorted ascending - what `simulate.roll_pool`
    rolls from. Sorted rather than numbered because the roll is uniform over
    the set (index.js:3396-3398); sorting only keeps a seeded run reproducible.
    """
    return sorted(
        neighbour.chunk_id
        for neighbour in eligible_neighbours(state, unlocked, current, graph=graph)
    )


def _nickname(state: MapState, chunk_id: str) -> str | None:
    name = state.chunk_info.chunk(chunk_id).get("Nickname")
    return name if isinstance(name, str) else None
