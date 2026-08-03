"""Simulate chunk rolls and accumulate the tasks/sections they unlock.

Ports the two roll-eligibility mechanisms in index.js:

- **Bootstrap roll** (nothing unlocked yet): uniform over `walkableChunks`
  (or `walkableChunksF2P` under the `F2P` rule), restricted to whichever
  regions `settings.rollingChunksOptions` selects (all of them, if none are
  checked), further intersected with the `bank`/`noquest` pools if those
  toggles are on. There is no neighbour concept yet, so region filtering
  only ever applies here.
- **Neighbour roll** (port of `selectAllNeighborsCanvas`): every locked
  chunk orthogonally adjacent (`chunk_id ± 1`, `chunk_id ± 256` - the grid
  is 256 chunks tall) to *any* unlocked chunk, that has a `chunkinfo.json`
  `sections` entry (only walkable chunks do) with at least one connection
  back to something already reachable - either a plain already-unlocked
  chunk, or a specific already-reachable section - gated by `sectionsLimits`
  requiring certain tasks already valid, where it applies. Region filters do
  *not* apply to this pool - upstream's `selectAllNeighborsCanvas` never
  references them.

Both pools are picked from uniformly at random via a seeded `random.Random`,
so the same seed reproduces the same simulated run.

Not modelled: manual chunk selection/blacklisting, `roll2`/`roll5` bonus
rerolls, and the `chunkNeighboursOptions` UI conveniences
(`autoWalkableRollable`/`walkableRollable`/`remove`) - all user-interaction
features orthogonal to a pure roll simulation, not part of eligibility
itself.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fray_claude.pipeline import Derived, MapState, derive
from fray_claude.summary import _mapping
from fray_claude.unlock import delta_from

_GRID_HEIGHT = 256

_REGION_NAMES = (
    "Misthalin",
    "Karamja",
    "Asgarnia",
    "Fremennik Province",
    "Kandarin",
    "Kharidian Desert",
    "Morytania",
    "Tirannwn",
    "Wilderness",
    "Kourend",
    "Varlamore",
    "Ocean",
)


@dataclass(frozen=True)
class UnlockRecord:
    """One roll's result: the delta it produced, snapshotted at roll time
    and never revisited by a later roll - see the module docstring's
    attribution note (shared with `unlock.py`).
    """

    order: int
    chunk_id: str
    new_sections: dict[str, dict[str, bool]]
    new_tasks: dict[str, dict[str, int | str | bool]]
    new_unsupported: frozenset[str]
    bis_upgrades: dict[str, tuple[str | None, str]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "chunk_id": self.chunk_id,
            "new_sections": self.new_sections,
            "new_tasks": self.new_tasks,
            "new_unsupported": sorted(self.new_unsupported),
            "bis_upgrades": {
                key: {"previous": previous, "new": new}
                for key, (previous, new) in self.bis_upgrades.items()
            },
        }


def _region_key(name: str) -> str:
    return name.replace(" ", "_").lower()


def _bootstrap_pool(state: MapState) -> list[str]:
    """Port of the "Random Start" pool (index.js, inside `pickChunkCanvas`)."""
    walkable = set(
        state.chunk_info.walkable_chunks_f2p
        if state.rules.get("F2P") is True
        else state.chunk_info.walkable_chunks
    )
    options = _mapping(state.settings, "rollingChunksOptions")
    selected_regions = [name for name in _REGION_NAMES if options.get(_region_key(name)) is True]
    regions_to_use = selected_regions or list(_REGION_NAMES)

    rolling = state.chunk_info.rolling_chunks
    pool: set[str] = set()
    for region in regions_to_use:
        members = rolling.get(_region_key(region))
        if isinstance(members, list):
            pool.update(m for m in members if isinstance(m, str))

    if options.get("bank") is True:
        bank_members = rolling.get("bank")
        pool &= set(bank_members) if isinstance(bank_members, list) else set()
    if options.get("noquest") is True:
        noquest_members = rolling.get("noquest")
        pool &= set(noquest_members) if isinstance(noquest_members, list) else set()

    return sorted(pool & walkable)


def _grid_neighbours(chunk_id: int) -> tuple[int, int, int, int]:
    return (chunk_id - 1, chunk_id + 1, chunk_id - _GRID_HEIGHT, chunk_id + _GRID_HEIGHT)


def _sections_limit_met(limit: Mapping[str, Any], valid: Mapping[str, Mapping[str, Any]]) -> bool:
    tasks = limit.get("Tasks")
    if not isinstance(tasks, dict):
        return True
    for task_name, task_skill in tasks.items():
        if not isinstance(task_skill, str):
            continue
        if task_name not in valid.get(task_skill, {}):
            return False
    return True


def _has_reachable_connection(
    candidate: str,
    candidate_sections: Mapping[str, Any],
    sections_limits: Mapping[str, Any],
    unlocked: Mapping[str, bool],
    reachable_sections: Mapping[str, Mapping[str, bool]],
    valid: Mapping[str, Mapping[str, Any]],
) -> bool:
    for section_id, connections in candidate_sections.items():
        if not isinstance(connections, list):
            continue
        suffix = "" if section_id == "0" else f"-{section_id}"
        for connection in connections:
            if not isinstance(connection, str):
                continue
            limit = sections_limits.get(f"{candidate}{suffix} to {connection}")
            if isinstance(limit, dict) and not _sections_limit_met(limit, valid):
                continue
            if "-" in connection:
                conn_chunk, _, conn_section = connection.partition("-")
                if reachable_sections.get(conn_chunk, {}).get(conn_section):
                    return True
            elif connection in unlocked:
                return True
    return False


def _neighbour_pool(state: MapState, unlocked: Mapping[str, bool], current: Derived) -> list[str]:
    """Port of `selectAllNeighborsCanvas`."""
    walkable_f2p = set(state.chunk_info.walkable_chunks_f2p)
    sections = state.chunk_info.sections
    sections_limits = _mapping(state.chunk_info.code_items, "sectionsLimits")

    pool: set[str] = set()
    for chunk_id_str in unlocked:
        try:
            chunk_id = int(chunk_id_str)
        except ValueError:
            continue  # area names aren't grid-addressable
        for candidate_id in _grid_neighbours(chunk_id):
            candidate = str(candidate_id)
            if candidate in unlocked or candidate in pool:
                continue
            if state.rules.get("F2P") is True and candidate not in walkable_f2p:
                continue
            candidate_sections = sections.get(candidate)
            if not isinstance(candidate_sections, dict):
                continue
            if _has_reachable_connection(
                candidate,
                candidate_sections,
                sections_limits,
                unlocked,
                current.reachable_sections,
                current.challenges.valid,
            ):
                pool.add(candidate)
    return sorted(pool)


def roll_pool(state: MapState, unlocked: Mapping[str, bool], current: Derived) -> list[str]:
    """The chunk ids eligible to be rolled next, sorted for determinism."""
    if unlocked:
        return _neighbour_pool(state, unlocked, current)
    return _bootstrap_pool(state)


def simulate_rolls(
    state: MapState, unlocked: Mapping[str, bool], *, rolls: int, seed: int | None = None
) -> list[UnlockRecord]:
    """Simulate up to `rolls` chunk unlocks from `unlocked`, stopping early
    if the roll pool is ever empty. Each record's delta is computed against
    the state immediately before that roll and never recomputed afterwards.
    """
    rng = random.Random(seed)
    current_ids: dict[str, bool] = dict(unlocked)
    before = derive(state, current_ids)
    ledger: list[UnlockRecord] = []

    for order in range(1, rolls + 1):
        pool = roll_pool(state, current_ids, before)
        if not pool:
            break
        chunk_id = rng.choice(pool)
        current_ids = {**current_ids, chunk_id: True}
        after = derive(state, current_ids)
        delta = delta_from(before, after, chunk_id)
        ledger.append(
            UnlockRecord(
                order=order,
                chunk_id=chunk_id,
                new_sections=delta.new_sections,
                new_tasks=delta.new_tasks,
                new_unsupported=delta.new_unsupported,
                bis_upgrades=delta.bis_upgrades,
            )
        )
        before = after

    return ledger
