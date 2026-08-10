"""What a single chunk unlock adds, attributed to the unlock that caused it.

`ChallengeResult.valid` (`challenges.py`) very nearly only grows as chunks
are added: almost every requirement this project checks is a *presence*
check (an item/object/monster/npc/chunk/prerequisite-task existing), so a
larger unlocked set can only add sources, never remove them. That makes
`derive(unlocked ∪ {chunk_id}).valid` minus `derive(unlocked).valid` a clean
partition - each task is attributed to exactly the one unlock that first
made it valid, and a later unlock can never retroactively change an earlier
one's recorded delta.

**One exception, `BackupParent`** (`challenges._drop_superseded_backups`):
a barehanded-catch challenge is deleted once the proper method it backs up
becomes valid, so an unlock that supplies a butterfly net *removes* 11
challenges on the real map. The diff is a set difference and simply won't
list them, so nothing breaks mechanically - but a task attributed to an
earlier unlock can later stop being valid, and that record is not revisited.
The alternative, re-diffing every prior record on each roll, would trade a
rare stale credit for a ledger that changes under you retroactively; the
project's semantics already prefer the former (see `bis.py`'s note below).
17 challenges in the whole export carry `BackupParent`, all `Hunter`.

The *panel*'s active-task selection (`calcCurrentChallenges2`, now ported in
`active_tasks.py`) would still be the wrong thing to diff for attribution,
even though it's computed: it picks only the single highest challenge per
skill from whatever's currently valid, and a later chunk can promote a
*different* (higher) challenge into that role, so what counts as "active"
for a skill is not monotonic - a later chunk genuinely does change what an
earlier one would display. That's exactly why this project's simulation
ledger (`simulate.py`) is built on `calc_challenges`'s `valid` directly, not
`active_tasks.py`'s classification.

`bis.py`'s output is exactly that non-monotonic panel-like case, deliberately
exempted from the partition argument above: a later unlock can make a
*better* item available for a slot an earlier unlock already filled, so
`UnlockDelta.bis_upgrades` records which (style, slot) picks changed between
`before`/`after` - not "new" tasks attributed to one unlock, but a per-unlock
snapshot of what improved, as agreed with the project's BiS semantics
(recompute the best achievable set fresh per state, per chunk roll).

**Everything above is why this module's diffs are one-directional**, and it
holds only for the one pair it builds: a single `MapState` with one extra
chunk. Comparing two *arbitrary* cached maps is `delta.py` - symmetric,
across all six `Derived` branches, claiming no attribution. The three helpers
here are projections of its primitives (the added half, `after`-side only),
so the two views of the same diff cannot drift apart. They stay projections
rather than calls to `delta.compare`: `simulate.py` runs `delta_from` once
per roll, and a six-branch comparison there would be a new cost in the loop
`--jobs` exists to make finish.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from fray_claude.derive.delta import diff_nested, diff_picks
from fray_claude.derive.pipeline import Derived, MapState, derive


@dataclass(frozen=True)
class UnlockDelta:
    """What unlocking `chunk_id` adds, on top of an already-derived `before`."""

    chunk_id: str
    new_sections: dict[str, dict[str, bool]]
    new_tasks: dict[str, dict[str, int | str | bool]]
    new_unsupported: frozenset[str]
    bis_upgrades: dict[str, tuple[str | None, str]]

    @property
    def task_count(self) -> int:
        return sum(len(names) for names in self.new_tasks.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "new_sections": self.new_sections,
            "new_tasks": self.new_tasks,
            "new_unsupported": sorted(self.new_unsupported),
            "bis_upgrades": {
                key: {"previous": previous, "new": new}
                for key, (previous, new) in self.bis_upgrades.items()
            },
        }


def diff_reachable_sections(
    before: Mapping[str, Mapping[str, bool]], after: Mapping[str, Mapping[str, bool]]
) -> dict[str, dict[str, bool]]:
    """Sections present (and reachable) in `after` but not `before`."""
    return {
        chunk: {section: True for section in branch.added}
        for chunk, branch in diff_nested(before, after, truthy_only=True).items()
        if branch.added
    }


def diff_valid_tasks(
    before: Mapping[str, Mapping[str, Any]], after: Mapping[str, Mapping[str, Any]]
) -> dict[str, dict[str, int | str | bool]]:
    """Tasks valid in `after` but not `before`."""
    return {
        skill: branch.added
        for skill, branch in diff_nested(before, after, keep_values=True).items()
        if branch.added
    }


def diff_bis_picks(
    before: Mapping[str, str], after: Mapping[str, str]
) -> dict[str, tuple[str | None, str]]:
    """`(style, slot)` picks that appeared or changed in `after` versus
    `before` - a slot with no prior pick has `previous=None`.

    A slot the `after` state does not fill at all is *not* reported, which is
    what keeps this the additions-only view: `delta.diff_picks` records that
    as `(item, None)`, and this drops it.
    """
    diff: dict[str, tuple[str | None, str]] = {}
    for key, (previous, item) in diff_picks(before, after).items():
        if item is not None:
            diff[key] = (previous, item)
    return diff


def delta_from(before: Derived, after: Derived, chunk_id: str) -> UnlockDelta:
    """Build the `UnlockDelta` between two already-derived pipeline runs."""
    return UnlockDelta(
        chunk_id=chunk_id,
        new_sections=diff_reachable_sections(before.reachable_sections, after.reachable_sections),
        new_tasks=diff_valid_tasks(before.challenges.valid, after.challenges.valid),
        new_unsupported=frozenset(after.challenges.unsupported - before.challenges.unsupported),
        bis_upgrades=diff_bis_picks(before.bis.picks, after.bis.picks),
    )


def tasks_added_by(
    state: MapState,
    unlocked: Mapping[str, bool],
    chunk_id: str,
    *,
    derive_with: Callable[[MapState, Mapping[str, bool]], Derived] = derive,
) -> UnlockDelta:
    """What unlocking `chunk_id` would add on top of `unlocked`, from scratch.

    `derive_with` lets `cli.py` route both runs through the on-disk cache
    (`derived_cache.cached_derive`) - two derives is why `fray unlock` costs
    twice what the other commands do, and the "before" half is the very state
    every other command just derived. It defaults to the plain `derive`, so
    nothing that imports this module gets a cache it didn't ask for.
    """
    before = derive_with(state, unlocked)
    after = derive_with(state, {**unlocked, chunk_id: True})
    return delta_from(before, after, chunk_id)
