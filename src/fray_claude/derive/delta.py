"""Compare two derived map states, symmetrically.

`unlock.py` diffs two derivations too, but only ever the one pair
`derive(unlocked)` / `derive(unlocked ∪ {chunk})`: a single `MapState`, one
extra chunk, and additions only. That is sound there and stays there - read
its docstring for the monotonicity argument its attribution rule rests on.

This module is the general case, where none of that holds. Two cached maps
have *different `MapState`s* - their own `completedChallenges`, `rules`,
`settings`, `manualTasks` - and neither unlocked set need contain the other,
so a task can be valid on one side and not the other in either direction.
Every branch here is two-sided: `BranchDelta` carries `added` and `removed`,
and `compare(a, b)`'s `added` is `compare(b, a)`'s `removed`.

**All six `Derived` branches, deliberately.** `UnlockDelta` covers four and
skips `source_index`, `task_classification` and `other_tasks` because those
are non-monotonic display state, and so are the wrong thing to *attribute* to
one unlock (`unlock.py`'s docstring, third paragraph). No attribution is
claimed here - a `StateDelta` is a snapshot comparison of two worlds, not a
ledger entry crediting one of them - so they are in scope, and are most of
what "what changed between these maps" actually means.

**`sources` is `SourceIndex`, not `ChallengeResult.available_items`.** That
makes this branch agree with what `fray sources` prints, which is the point
of it, but it inherits `SourceIndex`'s known understatement: an item
obtainable only by *making* it (`Granite ring (i)`, the output of an imbue
challenge) is absent from `SourceIndex.items` and present in
`available_items`. Read `challenges.py`'s note on the two before using this
branch for anything but display - `bis.py` and `boosts.py` both got that
distinction wrong first.

`unlock.py` keeps its own cheap, one-directional path over the three
primitives below rather than projecting a `StateDelta` down to `UnlockDelta`:
`simulate.py` calls `unlock.delta_from` once per roll and `batch.py` counts
it as free next to `derive`, so a six-branch comparison there - `sources`
included, which is the only expensive one - would put a new cost inside the
one loop `--jobs` exists to make finish. The two share the primitives, which
is what stops them drifting; `tests/test_delta.py` asserts they agree.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from fray_claude.derive.active_tasks import SkillClassification
from fray_claude.derive.other_tasks import CategoryTasks
from fray_claude.derive.pipeline import Derived, MapState, derive
from fray_claude.derive.sources import CATEGORIES as SOURCE_CATEGORIES

#: The comparable branches, in the order `fray diff` reports them. `bis`
#: covers `StateDelta.bis_picks` and `bis_tasks` together: they are one
#: branch to a reader and two shapes to the code.
BRANCHES = ("chunks", "sections", "tasks", "unsupported", "sources", "bis", "skills", "other")

#: `SourceIndex`'s branches. `drop_rates` is not in `sources.CATEGORIES` (it
#: isn't listable by `fray sources`) but it does change between states, and
#: leaving it out would make the sources branch quietly incomplete.
_SOURCE_BRANCHES = (*SOURCE_CATEGORIES, "drop_rates")


@dataclass(frozen=True)
class BranchDelta:
    """One branch's two-sided difference: names gained and names lost.

    `added` maps name to the value the *after* side held, so a caller that
    wants the value (`challenges.valid`'s `Level`/`Label`, a BiS label) has
    it without a second lookup. Branches whose values are structure rather
    than information - a source's `{source: tag}` map, a chunk id's own id -
    normalise to `True`, which is also what `unlock.diff_reachable_sections`
    has always emitted.
    """

    added: dict[str, Any] = field(default_factory=dict)
    removed: frozenset[str] = frozenset()

    @property
    def empty(self) -> bool:
        return not self.added and not self.removed

    @property
    def counts(self) -> tuple[int, int]:
        return len(self.added), len(self.removed)

    def as_dict(self) -> dict[str, Any]:
        return {"added": self.added, "removed": sorted(self.removed)}


@dataclass(frozen=True)
class SkillDelta:
    """One skill's `active_tasks.SkillClassification`, compared.

    `active` is `None` when the winner did not change, and otherwise the
    `(before, after)` pair - either side possibly `None`, since a skill can
    have no qualifying challenge at all. It is a *pair* rather than an
    add/remove split because there is only ever one winner: "Woodcutting
    moved from X to Y" is the fact, not "gained Y, lost X".
    """

    active: tuple[str | None, str | None] | None = None
    obsolete: BranchDelta = field(default_factory=BranchDelta)
    completed: BranchDelta = field(default_factory=BranchDelta)

    @property
    def empty(self) -> bool:
        return self.active is None and self.obsolete.empty and self.completed.empty

    def as_dict(self) -> dict[str, Any]:
        return {
            "active": None if self.active is None else list(self.active),
            "obsolete": self.obsolete.as_dict(),
            "completed": self.completed.as_dict(),
        }


@dataclass(frozen=True)
class MapSide:
    """One side of a comparison: what `derive` needs, plus a label for it."""

    state: MapState
    unlocked: Mapping[str, bool]
    map_id: str = ""


@dataclass(frozen=True)
class StateDelta:
    """What changed between two derived states, branch by branch.

    Every field is empty when the two sides agree, so a `StateDelta` between
    a state and itself is empty throughout - `tests/test_delta.py` asserts
    exactly that, because it is the property the rest of the diff rests on.
    """

    before_map: str = ""
    after_map: str = ""
    chunks: BranchDelta = field(default_factory=BranchDelta)
    sections: dict[str, BranchDelta] = field(default_factory=dict)
    tasks: dict[str, BranchDelta] = field(default_factory=dict)
    unsupported: BranchDelta = field(default_factory=BranchDelta)
    sources: dict[str, BranchDelta] = field(default_factory=dict)
    #: `"{style}-{slot}"` -> `(before, after)`; either side `None` for a slot
    #: only one of the two states fills. Value-compared, not set-compared -
    #: see `bis.py` on why BiS is recomputed fresh per state.
    bis_picks: dict[str, tuple[str | None, str | None]] = field(default_factory=dict)
    #: Keyed `active`/`completed`/`outdated`, matching `bis.BisResult`.
    bis_tasks: dict[str, BranchDelta] = field(default_factory=dict)
    skills: dict[str, SkillDelta] = field(default_factory=dict)
    #: Category -> `{"active": ..., "completed": ...}`. Groups are flattened
    #: away: a task name is unique across a category's groups, and which
    #: group renders it is `other_tasks.py`'s display concern, not a fact
    #: about the two states.
    other: dict[str, dict[str, BranchDelta]] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not any(count for counts in self.counts().values() for count in counts) and not (
            self.bis_picks or any(not skill.empty for skill in self.skills.values())
        )

    def counts(self) -> dict[str, tuple[int, int]]:
        """`(added, removed)` per branch, for the summary `fray diff` prints.

        `bis_picks` and each skill's `active` are excluded: neither is an
        add/remove split, so folding them into these totals would report a
        changed pick as an addition. `cli.py` renders them separately.
        """
        return {
            "chunks": self.chunks.counts,
            "sections": _total(self.sections.values()),
            "tasks": _total(self.tasks.values()),
            "unsupported": self.unsupported.counts,
            "sources": _total(self.sources.values()),
            "bis": _total(self.bis_tasks.values()),
            "skills": _total(
                branch
                for skill in self.skills.values()
                for branch in (skill.obsolete, skill.completed)
            ),
            "other": _total(
                branch for category in self.other.values() for branch in category.values()
            ),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "before_map": self.before_map,
            "after_map": self.after_map,
            "chunks": self.chunks.as_dict(),
            "sections": {chunk: branch.as_dict() for chunk, branch in self.sections.items()},
            "tasks": {skill: branch.as_dict() for skill, branch in self.tasks.items()},
            "unsupported": self.unsupported.as_dict(),
            "sources": {name: branch.as_dict() for name, branch in self.sources.items()},
            "bis_picks": {
                key: {"before": before, "after": after}
                for key, (before, after) in self.bis_picks.items()
            },
            "bis_tasks": {name: branch.as_dict() for name, branch in self.bis_tasks.items()},
            "skills": {skill: change.as_dict() for skill, change in self.skills.items()},
            "other": {
                category: {name: branch.as_dict() for name, branch in branches.items()}
                for category, branches in self.other.items()
            },
        }


def _total(branches: Iterable[BranchDelta]) -> tuple[int, int]:
    added = removed = 0
    for branch in branches:
        added += len(branch.added)
        removed += len(branch.removed)
    return added, removed


def _as_mapping(names: Mapping[str, Any] | Iterable[str]) -> Mapping[str, Any]:
    """Accept a name set or a name->value mapping, so one primitive serves
    `challenges.unsupported` (a `frozenset`) and `challenges.valid` alike.
    """
    return names if isinstance(names, Mapping) else {name: True for name in names}


def diff_names(
    before: Mapping[str, Any] | Iterable[str],
    after: Mapping[str, Any] | Iterable[str],
    *,
    truthy_only: bool = False,
    keep_values: bool = False,
) -> BranchDelta:
    """Names present in one side and not the other.

    `truthy_only` treats a falsy value as absent, which is what
    `Derived.reachable_sections` means by it: a section recorded `False` is
    *not* reachable, so `True -> False` is a removal rather than a no-op.

    `keep_values` carries the after side's value into `added`; without it
    every added name gets `True`. Off by default because most branches'
    values are structure (a source's `{source: tag}` map) that a diff reader
    doesn't want and `--export-json` shouldn't carry.
    """
    before_map, after_map = _as_mapping(before), _as_mapping(after)
    held_before = _present(before_map, truthy_only)
    held_after = _present(after_map, truthy_only)
    return BranchDelta(
        added={
            name: (after_map[name] if keep_values else True) for name in held_after - held_before
        },
        removed=frozenset(held_before - held_after),
    )


def _present(names: Mapping[str, Any], truthy_only: bool) -> set[str]:
    if not truthy_only:
        return set(names)
    return {name for name, value in names.items() if value}


def diff_nested(
    before: Mapping[str, Mapping[str, Any] | Iterable[str]],
    after: Mapping[str, Mapping[str, Any] | Iterable[str]],
    *,
    truthy_only: bool = False,
    keep_values: bool = False,
) -> dict[str, BranchDelta]:
    """`diff_names` per outer key, over the union of both sides' keys.

    Keys whose two sides agree are dropped, so an unchanged skill or chunk
    never reaches the output. Walking the *union* rather than `after` is the
    whole difference from `unlock.py`'s one-directional helpers: a chunk that
    only the before side has must still be able to report its removals.
    """
    deltas: dict[str, BranchDelta] = {}
    for key in sorted({*before, *after}):
        branch = diff_names(
            before.get(key, {}),
            after.get(key, {}),
            truthy_only=truthy_only,
            keep_values=keep_values,
        )
        if not branch.empty:
            deltas[key] = branch
    return deltas


def diff_picks(
    before: Mapping[str, str], after: Mapping[str, str]
) -> dict[str, tuple[str | None, str | None]]:
    """Value comparison over the union: every key the two sides disagree on.

    Generalises `unlock.diff_bis_picks`, which walks `after` alone and so
    cannot see a slot that lost its pick entirely - `(item, None)` here.
    """
    changed: dict[str, tuple[str | None, str | None]] = {}
    for key in sorted({*before, *after}):
        was, now = before.get(key), after.get(key)
        if was != now:
            changed[key] = (was, now)
    return changed


def _diff_skills(
    before: Mapping[str, SkillClassification], after: Mapping[str, SkillClassification]
) -> dict[str, SkillDelta]:
    empty = SkillClassification(active=None, obsolete=frozenset(), completed=frozenset())
    deltas: dict[str, SkillDelta] = {}
    for skill in sorted({*before, *after}):
        was, now = before.get(skill, empty), after.get(skill, empty)
        change = SkillDelta(
            active=None if was.active == now.active else (was.active, now.active),
            obsolete=diff_names(was.obsolete, now.obsolete),
            completed=diff_names(was.completed, now.completed),
        )
        if not change.empty:
            deltas[skill] = change
    return deltas


def _category_names(category: CategoryTasks | None, attribute: str) -> set[str]:
    if category is None:
        return set()
    return {name for group in category.groups for name in getattr(group, attribute)}


def _diff_other(
    before: Mapping[str, CategoryTasks], after: Mapping[str, CategoryTasks]
) -> dict[str, dict[str, BranchDelta]]:
    deltas: dict[str, dict[str, BranchDelta]] = {}
    for category in sorted({*before, *after}):
        was, now = before.get(category), after.get(category)
        branches = {
            attribute: diff_names(
                _category_names(was, attribute), _category_names(now, attribute)
            )
            for attribute in ("active", "completed")
        }
        present = {name: branch for name, branch in branches.items() if not branch.empty}
        if present:
            deltas[category] = present
    return deltas


def _validate(branches: frozenset[str] | None) -> frozenset[str]:
    if branches is None:
        return frozenset(BRANCHES)
    unknown = sorted(branches - frozenset(BRANCHES))
    if unknown:
        raise ValueError(f"unknown delta branch: {unknown[0]!r} (expected one of {BRANCHES})")
    return branches


def compare(
    before: Derived,
    after: Derived,
    *,
    unlocked: tuple[Mapping[str, bool], Mapping[str, bool]] | None = None,
    map_ids: tuple[str, str] = ("", ""),
    branches: frozenset[str] | None = None,
) -> StateDelta:
    """The two-sided difference between two already-derived states.

    Pure, and does no deriving of its own - `compare_maps` is the entry point
    that does. `unlocked` is optional because the unlocked-chunk set is *not*
    part of `Derived`: pass both sides' to fill the `chunks` branch, omit it
    and that branch is empty.

    `branches` restricts the work. `sources` is the only branch whose cost is
    worth avoiding (the real `SourceIndex` dwarfs the others), but a caller
    listing one branch has no reason to pay for the rest either.
    """
    want = _validate(branches)
    before_unlocked, after_unlocked = unlocked if unlocked is not None else ({}, {})
    return StateDelta(
        before_map=map_ids[0],
        after_map=map_ids[1],
        chunks=(
            diff_names(before_unlocked, after_unlocked) if "chunks" in want else BranchDelta()
        ),
        sections=(
            diff_nested(before.reachable_sections, after.reachable_sections, truthy_only=True)
            if "sections" in want
            else {}
        ),
        tasks=(
            diff_nested(before.challenges.valid, after.challenges.valid, keep_values=True)
            if "tasks" in want
            else {}
        ),
        unsupported=(
            diff_names(before.challenges.unsupported, after.challenges.unsupported)
            if "unsupported" in want
            else BranchDelta()
        ),
        sources=(
            diff_nested(
                {name: getattr(before.source_index, name) for name in _SOURCE_BRANCHES},
                {name: getattr(after.source_index, name) for name in _SOURCE_BRANCHES},
            )
            if "sources" in want
            else {}
        ),
        bis_picks=diff_picks(before.bis.picks, after.bis.picks) if "bis" in want else {},
        bis_tasks=(
            diff_nested(
                {name: getattr(before.bis, name) for name in ("active", "completed", "outdated")},
                {name: getattr(after.bis, name) for name in ("active", "completed", "outdated")},
                keep_values=True,
            )
            if "bis" in want
            else {}
        ),
        skills=(
            _diff_skills(before.task_classification.skills, after.task_classification.skills)
            if "skills" in want
            else {}
        ),
        other=(
            _diff_other(before.other_tasks.categories, after.other_tasks.categories)
            if "other" in want
            else {}
        ),
    )


def compare_maps(
    before: MapSide,
    after: MapSide,
    *,
    derive_with: Callable[[MapState, Mapping[str, bool]], Derived] = derive,
    branches: frozenset[str] | None = None,
) -> StateDelta:
    """Derive both sides and compare them.

    A `MapSide` per side rather than `unlock.tasks_added_by`'s one shared
    `MapState`: two cached maps differ in far more than their unlocked sets -
    `completedChallenges`, `rules`, `settings`, `manualTasks` all feed
    `derive` - so each side has to be derived against its own.

    `derive_with` is the same injection seam `unlock.py` carries, so `cli.py`
    can route both derivations through `derived_cache.cached_derive` while
    nothing that merely imports this module gets a cache it didn't ask for.
    """
    return compare(
        derive_with(before.state, before.unlocked),
        derive_with(after.state, after.unlocked),
        unlocked=(before.unlocked, after.unlocked),
        map_ids=(before.map_id, after.map_id),
        branches=branches,
    )
