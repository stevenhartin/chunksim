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

Which of a run's derived states get cached is `derived_cache.py`'s call, not
this module's: `StateCache` is the seam, and this module only says whether a
state is the one it started from, passed through, or finished on.

`simulated_payload` turns a finished ledger back into a *map payload*, so a
simulated future can be cached and read by every other subcommand (see
`cache.py`'s layout and `batch.py`'s driver). It is pure - it never mutates the
payload it is given - and it touches exactly four branches; its docstring says
why each one, including the two it deliberately deletes.

Not modelled: manual chunk selection/blacklisting and the `roll2`/`roll5`
bonus rerolls - user-interaction features orthogonal to a pure roll
simulation, not part of eligibility itself.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

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


def simulated_payload(
    base_payload: Mapping[str, Any],
    records: Sequence[UnlockRecord],
    *,
    start_time_ms: int | None = None,
) -> dict[str, Any]:
    """A new map payload with `records`' rolls applied to `base_payload`.

    Pure: every branch it changes is rebuilt rather than mutated, so the
    payload passed in is safe to reuse for another run in the same process.
    Four branches change, and no others:

    - `chunks.unlocked` gains each rolled chunk in the payload's own
      `{id: id}` string form - real data is `{'6449': '6449'}`, not booleans,
      and `pipeline.load_map_state` only reads the keys.
    - `chunkOrder` gains one `{timestamp_ms: chunk_id}` entry per roll, its
      real shape. Nothing derives from it (it's a partial log upstream too),
      but leaving it alone would make `fray show` misreport a simulated map.
    - `chunkinfo.checkedChallenges` is merged into `completedChallenges` and
      cleared, because that is what rolling the next chunk does upstream
      (`completeChallenges`, index.js:12718). Both branches are stored
      encoded, and merging them keyed-as-stored needs no decode round trip -
      `firebase.decode_challenge_keyed` handles either form on the way back
      in. Derivation is unaffected (`load_map_state` already merges the two);
      what this fixes is the `(Active)` marker, which would otherwise keep
      flagging the *pre-simulation* chunk's tick-offs as "this chunk". With
      no rolls, nothing has committed, so nothing moves.
    - `chunkinfo.activeTasks` and `chunks.selected` are **dropped**. They hold
      upstream's own computed answers for the unlocked set it computed them
      against - this project's oracles (see `active_tasks.py`,
      `neighbours.py`). Carrying them into a state upstream has never seen
      would manufacture an oracle that agrees with nothing, and
      `fray tasks`'s "upstream says" line would compare against it.
    """
    payload = dict(base_payload)

    chunks = dict(_mapping(base_payload, "chunks"))
    unlocked = dict(_mapping(chunks, "unlocked"))
    for record in records:
        unlocked[record.chunk_id] = record.chunk_id
    chunks["unlocked"] = unlocked
    chunks.pop("selected", None)
    payload["chunks"] = chunks

    order = dict(_mapping(base_payload, "chunkOrder"))
    stamp = int(time.time() * 1000) if start_time_ms is None else start_time_ms
    for offset, record in enumerate(records):
        order[str(stamp + offset)] = (
            int(record.chunk_id) if record.chunk_id.isdigit() else record.chunk_id
        )
    payload["chunkOrder"] = order

    info = dict(_mapping(base_payload, "chunkinfo"))
    if records:
        completed: dict[str, Any] = {}
        for category, entries in _mapping(info, "completedChallenges").items():
            completed[category] = dict(entries) if isinstance(entries, dict) else entries
        for category, entries in _mapping(info, "checkedChallenges").items():
            if isinstance(entries, dict) and isinstance(completed.get(category), dict):
                completed[category].update(entries)
            elif isinstance(entries, dict):
                completed[category] = dict(entries)
        info["completedChallenges"] = completed
        info.pop("checkedChallenges", None)
    info.pop("activeTasks", None)
    payload["chunkinfo"] = info

    return payload


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


class StateCache(Protocol):
    """How a simulation's derived states are stored, if at all.

    This module knows *which* state it is deriving - the one it starts from,
    one it passed through, the one it finished on - and nothing about whether
    any of them is worth keeping. `derived_cache.RollCache` implements this and
    owns that policy, so `--cache-behaviour` never leaks in here.
    """

    def derive_state(
        self, state: MapState, unlocked: Mapping[str, bool], *, start: bool
    ) -> Derived:
        """Derive `unlocked`, storing it or not as the policy sees fit."""

    def keep_final(
        self, state: MapState, unlocked: Mapping[str, bool], derived: Derived
    ) -> None:
        """Offer the state the run finished on, which is the one the saved
        simulated map holds - so a later `--map <that run>` can reuse it."""


def simulate_rolls(
    state: MapState,
    unlocked: Mapping[str, bool],
    *,
    rolls: int,
    seed: int | None = None,
    cache: StateCache | None = None,
    on_state: Callable[[int, Derived], None] | None = None,
) -> list[UnlockRecord]:
    """Simulate up to `rolls` chunk unlocks from `unlocked`, stopping early
    if the roll pool is ever empty. Each record's delta is computed against
    the state immediately before that roll and never recomputed afterwards.

    Every derived state is offered to `cache` (see `StateCache`); with none
    supplied nothing is stored and this is a plain sequence of `derive` calls.
    The finishing state is offered *separately*, after the loop, because
    whether a roll is the last one is not knowable when it is derived: the run
    ends either at `rolls` or the first time the pool comes up empty, and the
    second of those is only visible one iteration later. Deriving it twice to
    find out would cost a second per run, which is the whole saving.

    `on_state` sees every state the run passes through, numbered from 0 for
    the one it starts on. **It exists so a caller can measure a state without
    this module learning how**: `batch.py` prices each one for the timeline,
    which is free there because the derivation has already been paid for, and
    would be a second a roll if the timeline were rebuilt afterwards. Nothing
    here knows what an hour is, and nothing it does depends on the callback.
    """
    rng = random.Random(seed)
    current_ids: dict[str, bool] = dict(unlocked)
    before = (
        cache.derive_state(state, current_ids, start=True)
        if cache is not None
        else derive(state, current_ids)
    )
    graph = build_section_graph(state.chunk_info)
    ledger: list[UnlockRecord] = []
    if on_state is not None:
        on_state(0, before)

    for order in range(1, rolls + 1):
        pool = roll_pool(state, current_ids, before, graph=graph)
        if not pool:
            break
        chunk_id = rng.choice(pool)
        current_ids = {**current_ids, chunk_id: True}
        after = (
            cache.derive_state(state, current_ids, start=False)
            if cache is not None
            else derive(state, current_ids)
        )
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
        if on_state is not None:
            on_state(order, after)

    if cache is not None and ledger:
        cache.keep_final(state, current_ids, before)

    return ledger
