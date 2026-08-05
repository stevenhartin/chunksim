"""Typed, tolerant access to the upstream chunk/section/challenge reference data.

Pure and I/O-free: `cache.read_chunkinfo` is the disk-touching counterpart
that supplies the parsed dict this module wraps. Parsing the ~7MB export is
the expensive part, not attribute access, so callers should build one
`ChunkInfo` per command invocation and pass it down rather than re-parsing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fray_claude.summary import _mapping


@dataclass(frozen=True)
class ChunkInfo:
    """Wraps the parsed chunkinfo export.

    Every accessor tolerates a missing or wrongly-typed branch, the same way
    `summary.py` tolerates a missing branch in a map payload.
    """

    data: dict[str, Any]

    @property
    def chunks(self) -> dict[str, Any]:
        return _mapping(self.data, "chunks")

    @property
    def sections(self) -> dict[str, Any]:
        return _mapping(self.data, "sections")

    @property
    def sections_limits(self) -> dict[str, Any]:
        return _mapping(self.data, "sectionsLimits")

    @property
    def challenges(self) -> dict[str, Any]:
        return _mapping(self.data, "challenges")

    @property
    def drops(self) -> dict[str, Any]:
        return _mapping(self.data, "drops")

    @property
    def code_items(self) -> dict[str, Any]:
        return _mapping(self.data, "codeItems")

    @property
    def shop_items(self) -> dict[str, Any]:
        return _mapping(self.data, "shopItems")

    @property
    def skill_items(self) -> dict[str, Any]:
        return _mapping(self.data, "skillItems")

    @property
    def slayer_monsters(self) -> dict[str, Any]:
        return _mapping(self.data, "slayerMonsters")

    @property
    def slayer_tasks(self) -> dict[str, Any]:
        """`slayerTasks[category][monster]` - which monsters count for a task.

        Lives under `codeItems`, not at the top level beside `slayerMonsters`,
        which is a different thing: that one maps a monster to its Slayer
        level requirement and holds 95 entries, where this holds 144
        categories and is the authoritative task-to-monster mapping.
        """
        return _mapping(self.code_items, "slayerTasks")

    @property
    def equipment(self) -> dict[str, Any]:
        """Per-item combat bonuses, attack speed and slot.

        The one branch carrying stats rather than names, and the player half
        of a damage calculation - the export has no monster combat stats at
        all. See `dps_bridge.py`, which pairs it with an external source for
        the other half.
        """
        return _mapping(self.data, "equipment")

    @property
    def rolling_chunks(self) -> dict[str, Any]:
        return _mapping(self.data, "rollingChunks")

    @property
    def walkable_chunks(self) -> list[str]:
        return self._string_list("walkableChunks")

    @property
    def walkable_chunks_f2p(self) -> list[str]:
        return self._string_list("walkableChunksF2P")

    def chunk(self, chunk_id: str) -> dict[str, Any]:
        """A single chunk's entry, or `{}` if unknown."""
        value = self.chunks.get(chunk_id)
        return value if isinstance(value, dict) else {}

    def area_names(self) -> dict[str, str]:
        """`chunk id -> the named area it is part of`, for every chunk in one.

        **This is where a named area's location comes from, and it is exact
        rather than a name match.** The export stores such a place twice: once
        under its *name* as a top-level `chunks` key holding its contents, and
        once as one or more ordinary numbered chunks carrying `Name` - and a
        numbered chunk is a region, so it has a square. `6727` is region
        (26, 71) and says `Name: "Grotesque Guardians' Lair"`; that region *is*
        where the lair is.

        Measured on the real export: all 315 named areas are reachable this
        way, 301 of them landing somewhere drawable, and **502 of the 719
        placeable underground chunks get a label** out of it. Nothing here is
        fuzzy, so there is no provenance to record and no tier to tune -
        contrast `heuristics.py`, whose joins are between two vocabularies
        nobody reconciled.

        The mapping is many-to-one and stays that way: 70 areas span several
        chunks (Hallowed Sepulchre is 24) but **no chunk carries two names**,
        so inverting it is lossless.

        `sections.area_connections` walks the same `Name` fields for a
        different question - which chunks *unlock* an area - and the two are
        deliberately separate: connectivity is upstream's rule set, and this
        is geometry.
        """
        found: dict[str, str] = {}
        for chunk_id, entry in self.chunks.items():
            if not isinstance(entry, dict):
                continue
            name = entry.get("Name")
            if isinstance(name, str) and name:
                found[chunk_id] = name
        return found

    def _string_list(self, key: str) -> list[str]:
        value = self.data.get(key)
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str)]
