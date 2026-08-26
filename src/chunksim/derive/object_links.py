"""A second, narrower departure from "port only": chunks linked by a shared
physical `Object` - a portal, not a quest step - that upstream's own
`Connect`/`sections`/`ConnectsSections` data has no way to express because
the two ends are nowhere near each other on the grid.

**Why this is not `quest_jumps.py`.** `quest_jumps.py`'s own entries are all
gated on a quest step becoming valid - a narrative "you are taken somewhere".
An object link has no such gate: the export's own `Object` data already says
two chunks share a named, walk-through structure (`Bounty Hunter portal`
being the first confirmed case - present at `12600`, East Ferox Enclave, and
`13631`, Daimon's Crater Center, and nowhere else), and a real player can
walk through either end the moment they can reach the other, with no quest
prerequisite at all. Folding this into `KNOWN_QUEST_JUMPS` would have forced
a fake `trigger_name` onto something that isn't quest-gated; a second small
registry says exactly what is true instead.

**Why the linked set is computed, not hand-listed.** `KNOWN_OBJECT_LINKS`
names only the `Object` string; `_linked_chunks` scans the live export for
every walkable chunk (`chunk_info.sections` membership - the same "1,172 of
2,234" restriction `neighbours.py` itself applies) carrying it, every call.
Hand-listing `12600`/`13631` directly would go stale the moment a re-fetch
added or renamed a chunk carrying the same object; scanning cannot.

**Symmetric, not directed.** Unlike a quest jump's `anchor` -> `target`,
either linked chunk unlocks the other - there is no "trigger" side. Confirmed
against the real `chunkman-stuck` export state without a full simulation
rerun: `12600` (East Ferox Enclave) is already ordinarily reachable there,
and adding this entry alone makes `13631` (Daimon's Crater Center, previously
a genuine dead end - see `quest_jumps.py`'s own note on why it was left
unresolved) appear as a roll candidate; the reverse (unlocking `13631` first)
offers `12600` back, confirmed the same way with the two chunk_ids swapped.

Only the candidacy half is needed here, unlike `quest_jumps.py`: both known
members are bare chunks (no `Sections` map), so the landing section is free
the instant either is unlocked - the same convention `graph.py`'s own
`WHOLE_CHUNK_SECTION` documents - and there is nothing for
`pipeline.derive`'s loop to force open. A future entry linking a *sectioned*
chunk would need the same `landing_section`-forcing half `quest_jumps.py`
carries; add it once a real one is confirmed, not speculatively.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from chunksim.derive.graph import Edge, chunk_node
from chunksim.model.chunkinfo import ChunkInfo


@dataclass(frozen=True)
class ObjectLink:
    """A named `Object` this project treats as physically linking every
    walkable chunk that carries it - see this module's own docstring for
    why, and why the linked chunk set is computed rather than named here.
    """

    #: The exact `Object` key, as it appears in `chunk_info.chunk(...)`.
    object_name: str


KNOWN_OBJECT_LINKS: tuple[ObjectLink, ...] = (
    # Bounty Hunter portal - confirmed present (top-level `Object`, not
    # sectioned) at exactly two chunks in the 2026-08-26 export: `12600`
    # (East Ferox Enclave, already ordinarily reachable) and `13631`
    # (Daimon's Crater Center, otherwise a dead end - see quest_jumps.py's
    # own note on why no quest jump was written for it instead). Grepped
    # exhaustively across every chunk's top-level and per-section `Object`
    # map for this exact string; no third chunk carries it.
    ObjectLink(object_name="Bounty Hunter portal"),
)


def _linked_chunks(chunk_info: ChunkInfo, object_name: str) -> tuple[str, ...]:
    """Every walkable chunk (`chunk_info.sections` membership) whose
    top-level `Object` map carries `object_name`. Sectioned placements
    aren't matched - no known entry needs it; see the module docstring."""
    return tuple(
        chunk_id
        for chunk_id in chunk_info.sections
        if object_name in chunk_info.chunk(chunk_id).get("Object", {})
    )


def object_link_candidates(unlocked: Mapping[str, bool], chunk_info: ChunkInfo) -> dict[str, Edge]:
    """Not-yet-unlocked object-linked chunks that qualify as roll candidates
    because another chunk sharing the same named `Object` is already
    unlocked. Shaped as `Edge`s so they drop into `eligible_neighbours`'s
    own `qualifying` dict unchanged, the same fallback shape
    `quest_jump_candidates` uses."""
    candidates: dict[str, Edge] = {}
    for link in KNOWN_OBJECT_LINKS:
        members = _linked_chunks(chunk_info, link.object_name)
        already_unlocked = [member for member in members if member in unlocked]
        if not already_unlocked:
            continue
        source = already_unlocked[0]
        for member in members:
            if member in unlocked or member in candidates:
                continue
            candidates[member] = Edge(
                source=chunk_node(member),
                target=chunk_node(source),
                ref=f"object link: {link.object_name}",
                limit_key="",
                limit=None,
            )
    return candidates
