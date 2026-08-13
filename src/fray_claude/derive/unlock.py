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

**One boolean off that classification is read anyway, and the distinction is
the point.** `newly_trainable_backlog` takes `SkillClassification.primary` -
`checkPrimaryMethod`, one flag per skill - and not the winner it chose. The
flag is monotonic in the same way validity is (a chunk supplies a training
method; a later chunk does not take it away), so diffing it keeps the
partition argument above intact, where diffing the winner would not. What it
buys is the one kind of addition a validity diff cannot express: a skill
whose whole standing backlog becomes eligible at once, with no task's
validity changing. Its docstring carries the measurement.

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
across all six `Derived` branches, claiming no attribution. Three of the four
helpers here are projections of its primitives (the added half, `after`-side
only), so the two views of the same diff cannot drift apart; the fourth,
`newly_trainable_backlog`, has no counterpart there because a symmetric
comparison of two arbitrary maps has no "became" to report. They stay projections
rather than calls to `delta.compare`: `simulate.py` runs `delta_from` once
per roll, and a six-branch comparison there would be a new cost in the loop
`--jobs` exists to make finish.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from fray_claude.derive import boosts
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
    #: Per skill this unlock made *trainable*, the valid tasks it already had.
    #: Empty for every roll that trains nothing new, which is most of them.
    #: See `newly_trainable_backlog` for why validity alone does not cover it.
    newly_trainable: dict[str, dict[str, int | str | bool]] = field(default_factory=dict)
    #: Where a boost puts a task at a level other than the one the export
    #: states - the level a *candidate* is ranked at. Sparse, and empty when
    #: `delta_from` was given no `MapState` to read `rules['Boosting']` from.
    boosted_levels: dict[str, dict[str, float]] = field(default_factory=dict)
    #: The same tasks under the *completed* clamp: what having done one would
    #: prove. A different number from `boosted_levels` and needed separately -
    #: see `_clamped_levels`.
    proven_levels: dict[str, dict[str, float]] = field(default_factory=dict)

    @property
    def task_count(self) -> int:
        return sum(len(names) for names in self.new_tasks.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "new_sections": self.new_sections,
            "new_tasks": self.new_tasks,
            "newly_trainable": self.newly_trainable,
            "boosted_levels": self.boosted_levels,
            "proven_levels": self.proven_levels,
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


def newly_trainable_backlog(
    before: Derived, after: Derived
) -> dict[str, dict[str, int | str | bool]]:
    """Per skill that became trainable, the valid tasks it already had.

    **The one thing an unlock adds that `diff_valid_tasks` cannot see.**
    `active_tasks._is_eligible` gates candidacy on one boolean per skill -
    `checkPrimaryMethod`, "can this be trained here at all" - so until a chunk
    supplies a method, every one of that skill's valid challenges is barred
    from competing. The chunk that supplies it changes no task's *validity*
    and yet makes a standing backlog actionable all at once.

    Measured, on `verf-sim/run-001`: rolling `12849` adds Chaeldar, flipping
    Slayer from untrainable to trainable. 21 tasks become valid, all at level
    65 or below - and the 16 that were already valid, `Slay an ~|abyssal
    demon|~` (85) among them, become eligible without appearing in any diff.
    The roll panel read the additions alone and named the level-65 task.

    Only the backlog is recorded, not the union: `new_tasks` already carries
    what the unlock made valid, and a reader wanting the full candidate set
    takes the two together (`gui/panels._roll_classification`).

    Additions-only, like everything else here. A skill that *stops* being
    trainable is not recorded - see the module docstring on `BackupParent`
    for the project's standing preference between a rare stale credit and a
    ledger that rewrites itself.
    """
    backlog: dict[str, dict[str, int | str | bool]] = {}
    for skill, after_skill in after.task_classification.skills.items():
        if not after_skill.primary:
            continue
        before_skill = before.task_classification.skills.get(skill)
        if before_skill is not None and before_skill.primary:
            continue
        standing = before.challenges.valid.get(skill) or {}
        if standing:
            backlog[skill] = dict(standing)
    return backlog


def _clamped_levels(
    state: MapState,
    after: Derived,
    branches: Iterable[Mapping[str, Mapping[str, Any]]],
    clamp: Callable[..., float],
) -> dict[str, dict[str, float]]:
    """Where a boost puts a task at a level other than the export's.

    **The ledger records the export's `Level` and the panel ranks on it, but
    the thing being reproduced ranks on the boosted one.** `active_tasks`
    compares `boosts.real_level` throughout (its ceiling is
    `boosts.completed_ceiling` for the same reason), so two tasks the export
    calls Level 95 are not equal if a boost reaches one of them and
    `NoBoost` bars the other - and a panel comparing the raw numbers ties
    them and breaks the tie the wrong way.

    Measured, on `verf-sim/run-001` rolling `5179` with `rules['Boosting']`
    on: `Slay a ~|hydra|~` and `Slay the ~|Alchemical Hydra|~` are both
    Level 95 in the export, the first boosts to 90 and the second is
    `NoBoost`. The classification therefore picks the Alchemical Hydra
    outright, while the panel tied them and `_wins_tie` handed it to the
    hydra on `Priority`.

    **Sparse by design**: only tasks whose boosted level differs are stored,
    which on the real map is a small minority, so this costs the ledger
    almost nothing. 1.3us per task measured, against a ~0.76s derive - the
    cost is not why it is sparse, legibility is.

    **Two clamps, and one is not derivable from the other.** `clamp` is
    either `boosts.real_level` - what level a candidate really needs, which a
    boost *lowers* - or `boosts.completed_ceiling` - what having done it
    proves, which a boost also lowers but by its own rule
    (`active_tasks._completed_level_ceiling` says why the two differ
    upstream). The panel ranks on the first and the running high-water mark
    folds the second, so the delta records both rather than one and a
    conversion that does not exist.

    Skill categories only. `Quest`/`Diary`/`Extra` values are labels rather
    than levels and no boost applies to them.
    """
    out: dict[str, dict[str, float]] = {}
    challenges = state.chunk_info.challenges
    for branch in branches:
        for skill, tasks in branch.items():
            known = challenges.get(skill)
            if not isinstance(known, dict):
                continue
            for name in tasks:
                challenge = known.get(name)
                if not isinstance(challenge, dict):
                    continue
                raw = challenge.get("Level")
                if not isinstance(raw, (int, float)) or isinstance(raw, bool):
                    continue
                level = clamp(
                    skill,
                    name,
                    challenge,
                    float(raw),
                    rules=state.rules,
                    chunk_info=state.chunk_info,
                    items=after.challenges.available_items,
                    source_index=after.source_index,
                )
                if level != float(raw):
                    out.setdefault(skill, {})[name] = level
    return out


def delta_from(
    before: Derived, after: Derived, chunk_id: str, *, state: MapState | None = None
) -> UnlockDelta:
    """Build the `UnlockDelta` between two already-derived pipeline runs.

    `state` is what `boosted_levels` needs and nothing else here reads. It is
    optional because a caller comparing two hand-built `Derived`s has no map
    to give - and its absence records *no boost information*, which is a
    smaller claim than a level, rather than a guessed one.
    """
    new_tasks = diff_valid_tasks(before.challenges.valid, after.challenges.valid)
    newly_trainable = newly_trainable_backlog(before, after)
    return UnlockDelta(
        chunk_id=chunk_id,
        new_sections=diff_reachable_sections(before.reachable_sections, after.reachable_sections),
        new_tasks=new_tasks,
        new_unsupported=frozenset(after.challenges.unsupported - before.challenges.unsupported),
        bis_upgrades=diff_bis_picks(before.bis.picks, after.bis.picks),
        newly_trainable=newly_trainable,
        boosted_levels=(
            _clamped_levels(state, after, (new_tasks, newly_trainable), boosts.real_level)
            if state is not None
            else {}
        ),
        proven_levels=(
            _clamped_levels(state, after, (new_tasks, newly_trainable), boosts.completed_ceiling)
            if state is not None
            else {}
        ),
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
    return delta_from(before, after, chunk_id, state=state)
