"""Derive counts from a raw map payload.

Deliberately free of I/O so the later simulation work can reuse these directly.
Extend this layer rather than `cli.py`.

Firebase omits empty containers rather than storing them, so every lookup
here must tolerate a missing branch - `_mapping` exists for that, and is
worth reusing (`chunkinfo.py` does too, over the export instead of a map
payload).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Summary:
    """Headline figures for one map's state."""

    unlocked_chunks: int
    chunk_order_entries: int
    active_tasks: dict[str, int]
    rules_enabled: int
    rules_total: int

    @property
    def active_task_total(self) -> int:
        return sum(self.active_tasks.values())


def _mapping(payload: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    """Walk nested keys, yielding `{}` if any level is absent or not an object.

    Firebase omits empty containers entirely rather than storing them, so every
    lookup has to tolerate a missing branch.
    """
    node: Any = payload
    for key in keys:
        if not isinstance(node, dict):
            return {}
        node = node.get(key)
    return node if isinstance(node, dict) else {}


def summarise(payload: dict[str, Any]) -> Summary:
    """Reduce a raw map payload to its headline counts."""
    rules = _mapping(payload, "rules")
    active = _mapping(payload, "chunkinfo", "activeTasks")
    return Summary(
        unlocked_chunks=len(_mapping(payload, "chunks", "unlocked")),
        # Fewer entries than unlocked chunks, and timestamps repeat: this is a
        # partial log, not an authoritative unlock order.
        chunk_order_entries=len(_mapping(payload, "chunkOrder")),
        active_tasks={
            category: len(tasks)
            for category, tasks in sorted(active.items())
            if isinstance(tasks, dict)
        },
        rules_enabled=sum(1 for value in rules.values() if value is True),
        rules_total=len(rules),
    )
