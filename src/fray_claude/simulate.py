"""Simulate chunk rolls and accumulate the tasks/sections they unlock.

Dispatches between the two roll-eligibility mechanisms in index.js:

- **Bootstrap roll** (nothing unlocked yet): uniform over `walkableChunks`
  (or `walkableChunksF2P` under the `F2P` rule), restricted to whichever
  regions `settings.rollingChunksOptions` selects (all of them, if none are
  checked), further intersected with the `bank`/`noquest` pools if those
  toggles are on. Port of the "Random Start" branch of `pickCanvas`
  (index.js:3345-3393). There is no neighbour concept yet, so region
  filtering only ever applies here - which is exactly why this pool lives in
  this module and the other one does not.
- **Neighbour roll**: the eligible-neighbour set, owned by `neighbours.py`.
  Read its docstring for the port of `selectAllNeighborsCanvas`, the
  `sectionsLimits` gate and the canvas numbering. Region filters do *not*
  apply to it - `selectAllNeighborsCanvas` never references them.

Both pools are picked from uniformly at random via a seeded `random.Random`,
over a *sorted* candidate list, so the same seed reproduces the same run
regardless of set/dict iteration order. The numbering `neighbours.py` computes
does not bias the pick: upstream picks uniformly over the selected key set
(index.js:3396-3398) and only reads the number back for the roll modal.

Each roll's record is built via `unlock.delta_from` and never revisited by a
later roll - `bis_upgrades` included, so a later roll's improvement doesn't
get folded back into an earlier record. See `unlock.py` for why that is the
agreed semantics rather than an approximation.

Not modelled: manual chunk selection/blacklisting and the `roll2`/`roll5`
bonus rerolls - user-interaction features orthogonal to a pure roll
simulation, not part of eligibility itself.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fray_claude.graph import SectionGraph, build_section_graph
from fray_claude.neighbours import neighbour_pool
from fray_claude.pipeline import Derived, MapState, derive
from fray_claude.summary import _mapping
from fray_claude.unlock import delta_from

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
    """Port of the "Random Start" pool (index.js:3345-3393, inside `pickCanvas`)."""
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


def roll_pool(
    state: MapState,
    unlocked: Mapping[str, bool],
    current: Derived,
    *,
    graph: SectionGraph | None = None,
) -> list[str]:
    """The chunk ids eligible to be rolled next, sorted for determinism.

    Which pool applies is the roll's question, so the dispatch lives here;
    the neighbour pool itself is `neighbours.py`'s. Pass `graph` to reuse one
    across rolls.
    """
    if unlocked:
        return neighbour_pool(state, unlocked, current, graph=graph)
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
    graph = build_section_graph(state.chunk_info)
    ledger: list[UnlockRecord] = []

    for order in range(1, rolls + 1):
        pool = roll_pool(state, current_ids, before, graph=graph)
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
