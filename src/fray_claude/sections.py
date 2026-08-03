"""Which sections of the unlocked chunks are actually reachable.

Not every chunk is a single unit: 505 of the export's 2,222 chunks are split
into numbered sections (`Sections` in a chunk's entry), and a chunk being
"unlocked" only makes its section `0` reachable - crossing into section `1`
requires a connection (`sections[chunk][n]`, a list of other sections/chunks)
that is itself already reachable, or a static per-section `Connect` link to
another chunk that's separately unlocked. This module ports upstream's fixed
point over that connectivity: `findConnectedSections` (worker.js) plus the
one live part of `getAllChunkAreas` (worker.js).

`getAllChunkAreas`'s automatic area-detection branch is dead code upstream:
its filter predicate (`.filter(subArea => { chunks.hasOwnProperty(subArea) })`)
is an arrow function with a block body and no `return`, so it always
evaluates to `undefined` and the branch it guards can never run. Only the
`manualAreas` override has any observable effect, so that's all
`expand_chunk_areas` reproduces.

`sectionsLimits` is deliberately absent from this module - it gates
*rollable-neighbour* eligibility (`selectAllNeighborsCanvas`, index.js), not
the connectivity of chunks already unlocked, so it belongs with the roll
simulation instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fray_claude.chunkinfo import ChunkInfo

# Areas upstream explicitly excludes from cross-chunk connectivity
# (index.js `unconnectedAreas`) - not present anywhere in the export itself.
UNCONNECTED_AREAS = frozenset({"Zanaris", "Puro-Puro", "Player-owned house"})


def expand_chunk_areas(
    chunk_ids: Mapping[str, bool], *, manual_areas: Mapping[str, bool] | None = None
) -> dict[str, bool]:
    """Port of `getAllChunkAreas`'s only live effect: the `manualAreas` override."""
    expanded = dict(chunk_ids)
    for area, enabled in (manual_areas or {}).items():
        if enabled:
            expanded[area] = True
        else:
            expanded.pop(area, None)
    return expanded


def unlocked_sections(
    chunk_ids: Mapping[str, bool],
    chunk_info: ChunkInfo,
    *,
    manual_areas: Mapping[str, bool] | None = None,
    manual_sections: Mapping[str, Mapping[str, bool]] | None = None,
    opt_out_sections: bool = False,
    opt_out_sections_water: bool = False,
) -> dict[str, dict[str, bool]]:
    """Which sections of `chunk_ids` are reachable, as `{chunk: {section: True}}`.

    Runs `expand_chunk_areas` first, then `findConnectedSections`'s fixed
    point: a section becomes reachable once one of its connections is
    reachable, and that can unlock further connections, so this repeats
    until a pass adds nothing new.

    Upstream's `findConnectedSections` is also re-entrant against
    previously-computed state (an explicit `false` marker gets cleared, to
    be reconsidered next refresh) - not modelled here, since this recomputes
    from scratch every call rather than incrementally refining UI state.
    """
    expanded = expand_chunk_areas(chunk_ids, manual_areas=manual_areas)
    manual = manual_sections or {}
    sections_data = chunk_info.sections
    chunks_data = chunk_info.chunks

    # A `manualSections` entry of `true` is a direct override - upstream
    # seeds it into the accumulator (`combineJSONs`) *before* the fixed
    # point runs, so it's reachable regardless of connectivity. A `false`
    # entry blocks the section below without needing to be seeded here: see
    # the module docstring for why upstream's own re-entrant handling of it
    # is not modelled.
    reachable: dict[str, dict[str, bool]] = {}
    for chunk, chunk_manual in manual.items():
        if chunk not in expanded or not isinstance(chunk_manual, dict):
            continue
        for section_id, flag in chunk_manual.items():
            if flag is True:
                reachable.setdefault(chunk, {})[section_id] = True

    added = True
    while added:
        added = False
        for chunk, chunk_sections in sections_data.items():
            if chunk not in expanded or not isinstance(chunk_sections, dict):
                continue
            for section_id, connections in chunk_sections.items():
                if section_id == "0" or reachable.get(chunk, {}).get(section_id):
                    continue
                if manual.get(chunk, {}).get(section_id) is False:
                    continue
                if _section_is_reachable(
                    chunk,
                    section_id,
                    connections,
                    expanded,
                    reachable,
                    chunks_data,
                    opt_out_sections=opt_out_sections,
                    opt_out_sections_water=opt_out_sections_water,
                ):
                    reachable.setdefault(chunk, {})[section_id] = True
                    added = True
    return reachable


def _section_is_reachable(
    chunk: str,
    section_id: str,
    connections: Any,
    chunk_ids: Mapping[str, bool],
    reachable: Mapping[str, Mapping[str, bool]],
    chunks_data: Mapping[str, Any],
    *,
    opt_out_sections: bool,
    opt_out_sections_water: bool,
) -> bool:
    if opt_out_sections_water:
        return True
    if opt_out_sections and "W" not in section_id:
        return True
    if isinstance(connections, list) and _any_connection_open(connections, chunk_ids, reachable):
        return True
    return _any_static_connect_open(chunk, section_id, chunk_ids, chunks_data)


def _any_connection_open(
    connections: list[Any],
    chunk_ids: Mapping[str, bool],
    reachable: Mapping[str, Mapping[str, bool]],
) -> bool:
    for connection in connections:
        if not isinstance(connection, str):
            continue
        if "-" in connection:
            target_chunk, _, target_section = connection.partition("-")
            if reachable.get(target_chunk, {}).get(target_section):
                return True
        elif connection in chunk_ids:
            return True
    return False


def _any_static_connect_open(
    chunk: str, section_id: str, chunk_ids: Mapping[str, bool], chunks_data: Mapping[str, Any]
) -> bool:
    entry = chunks_data.get(chunk)
    sections_field = entry.get("Sections") if isinstance(entry, dict) else None
    section_entry = sections_field.get(section_id) if isinstance(sections_field, dict) else None
    connect = section_entry.get("Connect") if isinstance(section_entry, dict) else None
    if not isinstance(connect, dict):
        return False
    for sub_chunk_id in connect:
        sub_entry = chunks_data.get(sub_chunk_id)
        name = sub_entry.get("Name") if isinstance(sub_entry, dict) else None
        if not isinstance(name, str) or name in UNCONNECTED_AREAS:
            continue
        if name in chunk_ids and chunk_ids[name] is not False:
            return True
    return False


@dataclass(frozen=True)
class ChunkSections:
    """One unlocked chunk's reachable and locked sections, for `fray sections
    list`/`fray sections <chunk-id>`. Section `0` is a chunk's implicit
    "whole thing" section - always reachable once the chunk is unlocked, and
    never itself tracked in `unlocked_sections`'s output - so it's always
    included in `reachable` here rather than left for callers to add back.
    """

    chunk_id: str
    name: str | None
    reachable: list[str]
    locked: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "name": self.name,
            "reachable": self.reachable,
            "locked": self.locked,
        }


def _sort_key(chunk_id: str) -> tuple[int, object]:
    return (0, int(chunk_id)) if chunk_id.isdigit() else (1, chunk_id)


def describe_sections(
    chunk_ids: Mapping[str, bool],
    reachable: Mapping[str, Mapping[str, bool]],
    chunk_info: ChunkInfo,
) -> list[ChunkSections]:
    """One `ChunkSections` per id in `chunk_ids` (already `expand_chunk_areas`d),
    sorted numerically where chunk ids allow.
    """
    entries = []
    for chunk_id in sorted(chunk_ids, key=_sort_key):
        computed = sorted(reachable.get(chunk_id, {}))
        defined = chunk_info.sections.get(chunk_id, {})
        all_sections = set(defined) - {"0"} if isinstance(defined, dict) else set()
        locked = sorted(all_sections - set(computed))

        entry = chunk_info.chunk(chunk_id)
        name = entry.get("Nickname")
        if not isinstance(name, str):
            name = entry.get("Name") if isinstance(entry.get("Name"), str) else None

        entries.append(
            ChunkSections(chunk_id=chunk_id, name=name, reachable=["0", *computed], locked=locked)
        )
    return entries
