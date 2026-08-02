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

    def _string_list(self, key: str) -> list[str]:
        value = self.data.get(key)
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str)]
