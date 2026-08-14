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
from datetime import UTC, datetime
from typing import Any

from chunksim.model.firebase import decode_payload


@dataclass(frozen=True)
class Summary:
    """Headline figures for one map's state."""

    unlocked_chunks: int
    chunk_order_entries: int
    active_tasks: dict[str, int]
    rules_enabled: int
    rules_total: int
    #: The Slayer task the player is stuck on, and the level it holds them
    #: at, or `None`. Worth a headline of its own because it is the one piece
    #: of map state that stops a *skill* rather than gating a task, and
    #: nothing else in the summary would hint at it - see
    #: `pipeline.SlayerLock` and `costing/slayer.py` on the way out.
    slayer_locked: tuple[str, int] | None = None

    @property
    def active_task_total(self) -> int:
        return sum(self.active_tasks.values())


def format_age(stamp: Any) -> str:
    """Render an ISO-8601 timestamp as a rough age, or `"unknown"`.

    Here rather than in `cli.py` because both apps render ages - a map's, a
    scrape's, and now an install's (`build_info.py`) - and two copies of a
    bucketing rule is two copies that can disagree about what "3h ago" means.
    Tolerant of anything unparseable, since every one of those timestamps
    arrives from a file that something else wrote.
    """
    if not isinstance(stamp, str):
        return "unknown"
    try:
        at = datetime.fromisoformat(stamp)
    except ValueError:
        return "unknown"
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)

    seconds = max(0, int((datetime.now(UTC) - at).total_seconds()))
    for limit, divisor, unit in ((60, 1, "s"), (3600, 60, "m"), (86400, 3600, "h")):
        if seconds < limit:
            return f"{seconds // divisor}{unit} ago"
    return f"{seconds // 86400}d ago"


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
        slayer_locked=_slayer_lock(payload),
    )


def _slayer_lock(payload: Mapping[str, Any]) -> tuple[str, int] | None:
    """`chunkinfo.slayerLocked` as `(task, level)`. Parsed the same way
    `pipeline._slayer_lock` does - the level is a string in the payload, and
    one that will not parse means no lock rather than a guessed cap."""
    branch = _mapping(payload, "chunkinfo").get("slayerLocked")
    if not isinstance(branch, dict):
        return None
    monster = decode_payload(branch).get("monster")
    if not isinstance(monster, str) or not monster:
        return None
    try:
        return monster, int(branch.get("level"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
