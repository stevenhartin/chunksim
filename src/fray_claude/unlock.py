"""What a single chunk unlock adds, attributed to the unlock that caused it.

`ChallengeResult.valid` (`challenges.py`) only ever grows as chunks are
added: every requirement this project checks is a *presence* check (an
item/object/monster/npc/chunk/prerequisite-task existing), never an
absence check, so a larger unlocked set can only add sources, never remove
them. That makes `derive(unlocked ∪ {chunk_id}).valid` minus
`derive(unlocked).valid` a clean partition - each task is attributed to
exactly the one unlock that first made it valid, and a later unlock can
never retroactively change an earlier one's recorded delta.

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
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fray_claude.pipeline import Derived, MapState, derive


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
    diff: dict[str, dict[str, bool]] = {}
    for chunk, sections in after.items():
        before_sections = before.get(chunk, {})
        newly = {sec: True for sec, ok in sections.items() if ok and not before_sections.get(sec)}
        if newly:
            diff[chunk] = newly
    return diff


def diff_valid_tasks(
    before: Mapping[str, Mapping[str, Any]], after: Mapping[str, Mapping[str, Any]]
) -> dict[str, dict[str, int | str | bool]]:
    """Tasks valid in `after` but not `before`."""
    diff: dict[str, dict[str, int | str | bool]] = {}
    for skill, names in after.items():
        before_names = before.get(skill, {})
        newly = {name: value for name, value in names.items() if name not in before_names}
        if newly:
            diff[skill] = newly
    return diff


def diff_bis_picks(
    before: Mapping[str, str], after: Mapping[str, str]
) -> dict[str, tuple[str | None, str]]:
    """`(style, slot)` picks that appeared or changed in `after` versus
    `before` - a slot with no prior pick has `previous=None`.
    """
    diff: dict[str, tuple[str | None, str]] = {}
    for key, item in after.items():
        previous = before.get(key)
        if previous != item:
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


def tasks_added_by(state: MapState, unlocked: Mapping[str, bool], chunk_id: str) -> UnlockDelta:
    """What unlocking `chunk_id` would add on top of `unlocked`, from scratch."""
    before = derive(state, unlocked)
    after = derive(state, {**unlocked, chunk_id: True})
    return delta_from(before, after, chunk_id)
