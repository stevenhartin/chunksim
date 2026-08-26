"""Run one account from a fixed, known-good start to the game's own
completion state, auto-completing every valid Skills/Sailing/Combat/Quest/
Diary/Extra task before each roll, and report exactly where and why it
stopped.

Framed as a diagnostic, not a Monte-Carlo sample: `run_chunkman` starts on
chunk `12850` (Lumbridge) - never a random bootstrap roll, since `unlocked`
is never empty here - under a **fixed** rules mapping the caller supplies
(`maxed_account_state`'s own docstring says why the real cached map `fray`'s
rules, not `default_rules()`, is the one this project's own regression test
pins), with every skill already at 99 and nothing completed. One seed, one
run: multi-seed sampling was considered and set aside in favour of fixing
the start point, which is the actual source of the "got stuck for reasons
that don't generalise" failure mode this exists to catch.

**The start also seeds a spawn-point `manual_sections` override
(`start_section`, see `run_chunkman`'s own docstring) - without it the run
is stuck on step 0.** Chunk `12850` alone reaches no neighbour in any
direction under the ordinary `Connect` graph: its own sections all require
another chunk's section to already be open, and none of its neighbours'
declared connections target its section `0` (the one every unlocked chunk
gets for free) either. This is a real property of the export, not a bug -
it reflects a teleport placing the account inside a *specific* section
(`12850-1`) that the `Connect` graph has no vocabulary for, since that
graph only ever describes walking between already-reachable places.

**Why `completed_challenges` is mutated and re-derived, not left as
bookkeeping.** `challenges.calc_challenges` reads `completed_challenges`
through `_highest_completed_levels`/`_level_attainable`: for a real Skill
category whose primary training method is not yet reachable, having already
completed a task at level L lets other <=L tasks in that skill validate
anyway. `Quest`/`Diary`/`Extra`/`Nonskill`/`Sailing`/`Combat` never read
this (their `trainable` lookup always defaults `True`), so only the Skills
half of the auto-complete step can change what rolls next - but it can, so
the loop re-derives after applying a step's completions rather than
deferring the effect to the following roll. The re-derive is skipped
whenever a step found nothing new, which is the common case once every
skill has found a trainable route.

**What "auto-complete" covers.** Every one of the 23 real skills, plus
`Sailing` and `Combat` (both real, distinct `chunk_info.challenges`
categories - `Sailing` alone is 243 entries), plus `Quest`/`Diary`/`Extra`.
Deliberately **not** `Nonskill` - it houses structural `UnlocksArea`/
`ConnectsSections`/shooting-star/clue entries, not player tasks, and
completing one has no derivation effect anyway (see the correction above:
only a Skill category's own untrainable-skill escape hatch reads
`completed_challenges` at all).

Terminates two ways: the neighbour pool comes up empty (**stuck** - the
failure case this project wants recorded, not just noticed) or every one of
the export's rollable chunks (`len(chunk_info.sections)`) is unlocked
(**complete**). Persistence is in-memory only while the simulation runs -
no `cache/maps/edited/` writes per step, matching how this project's own
oracle tests already build `MapState` objects directly and loop `derive()`.
A report is written once, at the end, by `write_report`/`summarize`.

**The one exception, and it is deliberate: a *stuck* run's final state gets
persisted as a real cached map, via `persist_stuck_state`.** A successful
run never does - the whole point is a broken state is worth loading with
this project's own CLI/GUI (`chunksim show --map chunkman-stuck`,
`chunksim tasks --map chunkman-stuck`, the GUI's chunk panel) to dig into
*why*, and a run that finished cleanly has nothing to dig into.
`persist_stuck_state` is never called automatically by `run_chunkman` -
the caller decides, and does so only on `outcome.stuck`.

Reuses `simulate.roll_pool` rather than reimplementing chunk selection -
there is exactly one uniform-random-pick mechanism in this project and this
module is a second caller of it, not a second copy. Reuses `batch.save_edit`
for the one persisted artifact, for the same reason.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from random import Random
from typing import Any

from chunksim.derive.graph import SectionGraph, build_section_graph, chunk_sort_key, grid_neighbours
from chunksim.derive.neighbours import _qualifying_edge
from chunksim.derive.pipeline import Derived, MapState, derive
from chunksim.derive.unlock import UnlockDelta, delta_from
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.model.experience import MAX_SKILL_LEVEL
from chunksim.model.summary import _mapping
from chunksim.runs.batch import SavedEdit, save_edit
from chunksim.runs.simulate import CarryDivergedError, roll_pool
from chunksim.store.cache import CacheMissError

#: The 23 real skills - `max_skill`/`passive_skill` are read by name
#: (`_skills_requirement_met`, `sections._skills_needed_met`), not
#: enumerated from the export. The production home for this fact; `tests/`
#: keeps its own small copies for the reason their own comments give
#: (a test file cannot import from another test file, and the fact is
#: small and stable enough that sharing it isn't worth a fixture).
ALL_SKILLS: tuple[str, ...] = (
    "Attack", "Strength", "Defence", "Ranged", "Prayer", "Magic", "Runecraft",
    "Construction", "Hitpoints", "Agility", "Herblore", "Thieving", "Crafting",
    "Fletching", "Slayer", "Hunter", "Mining", "Smithing", "Fishing", "Cooking",
    "Firemaking", "Woodcutting", "Farming",
)

#: What "auto-complete" means. Nonskill excluded deliberately - see the
#: module docstring. Sailing/Combat included: both are real, player-facing
#: categories, not structural ones.
AUTO_COMPLETE_CATEGORIES: frozenset[str] = frozenset(
    {*ALL_SKILLS, "Sailing", "Combat", "Quest", "Diary", "Extra"}
)


def maxed_account_state(
    chunk_info: ChunkInfo,
    rules: Mapping[str, Any],
    *,
    manual_sections: Mapping[str, Mapping[str, bool]] = {},
) -> MapState:
    """A fresh account: every skill at 99, `rules` as given, nothing
    completed, every other manual/backlog branch empty.

    `rules` is the caller's to supply - *which* rules define "the account"
    is the whole point of a diagnostic run, so this function only builds the
    maxed-skill, blank-history shell around them. A caller wanting the real
    cached map `fray`'s own rules reads `real_state[0].rules` (or
    `load_map_state(read_cache("fray")["data"], chunk_info).rules`) and
    passes that - discarding fray's own real progress deliberately: "a
    maxed account with the fray ruleset" means fray's *rules*, not fray's
    actual completed-task history. Simulating a fresh account under those
    rules is the whole exercise.

    `manual_sections` is how `run_chunkman` seeds the spawn-point section -
    see its own docstring for why the connectivity graph alone cannot
    express "which section of the start chunk you're physically placed in".
    """
    maxed = {skill: MAX_SKILL_LEVEL for skill in ALL_SKILLS}
    return MapState(
        chunk_info=chunk_info,
        rules=rules,
        settings={},
        manual_sections=manual_sections,
        manual_areas={},
        manual_monsters={},
        manual_equipment={},
        backlogged_sources={},
        max_skill=maxed,
        passive_skill=maxed,
        completed_challenges={},
        checked_challenges={},
        manual_tasks={},
        backlog={},
        active_tasks={},
    )


def _auto_complete_targets(
    derived: Derived, already_completed: Mapping[str, Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Every valid-but-not-completed challenge in `AUTO_COMPLETE_CATEGORIES`.

    Reads `derived.challenges.valid` directly, not `task_classification`/
    `other_tasks` - those pick a *display* winner (and, for `Quest`, drop
    already-superseded prerequisite steps from `.active`); this wants every
    challenge `Tasks`/`Chunks` gates can themselves reference, unfiltered.
    """
    targets: dict[str, dict[str, Any]] = {}
    for category in AUTO_COMPLETE_CATEGORIES:
        valid = derived.challenges.valid.get(category, {})
        done = already_completed.get(category, {})
        new = {name: value for name, value in valid.items() if name not in done}
        if new:
            targets[category] = new
    return targets


@dataclass(frozen=True)
class ChunkmanStep:
    """One iteration: this step's auto-completions, then its roll - or the
    stall that ended the run on this step."""

    order: int
    pool_size_before_roll: int
    #: `{category: [task names newly marked complete this step]}`, sorted.
    newly_completed: dict[str, list[str]]
    #: `None` on the final, stalled step - no roll happened.
    chunk_id: str | None
    delta: UnlockDelta | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "pool_size_before_roll": self.pool_size_before_roll,
            "newly_completed": self.newly_completed,
            "chunk_id": self.chunk_id,
            "delta": self.delta.as_dict() if self.delta is not None else None,
        }


@dataclass(frozen=True)
class CategoryTally:
    """Valid-vs-completed count for one auto-completed category, at the
    run's terminal state - visible even on a "success" run, since hitting
    every headline criterion says nothing about a category with, say, three
    tasks that were simply never valid at all."""

    category: str
    valid_total: int
    completed_total: int

    @property
    def gap(self) -> int:
        return self.valid_total - self.completed_total

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "valid_total": self.valid_total,
            "completed_total": self.completed_total,
            "gap": self.gap,
        }


@dataclass(frozen=True)
class ChunkmanOutcome:
    """The result of one `run_chunkman` call - the full step history plus
    the final state's answer to every headline completion criterion."""

    stuck: bool
    steps: tuple[ChunkmanStep, ...]
    final_unlocked: dict[str, bool]
    final_state: MapState
    final_derived: Derived
    rejected_neighbours: dict[str, str]

    every_chunk_unlocked: bool
    quests_incomplete: tuple[str, ...]
    diaries_incomplete: tuple[str, ...]
    combat_achievements_incomplete: tuple[str, ...]
    bosses_missing: tuple[str, ...]

    category_tallies: tuple[CategoryTally, ...]

    def all_headline_criteria_met(self) -> bool:
        return (
            self.every_chunk_unlocked
            and not self.quests_incomplete
            and not self.diaries_incomplete
            and not self.combat_achievements_incomplete
            and not self.bosses_missing
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "stuck": self.stuck,
            "steps": [step.as_dict() for step in self.steps],
            "final_unlocked": sorted(self.final_unlocked),
            "rejected_neighbours": self.rejected_neighbours,
            "every_chunk_unlocked": self.every_chunk_unlocked,
            "quests_incomplete": list(self.quests_incomplete),
            "diaries_incomplete": list(self.diaries_incomplete),
            "combat_achievements_incomplete": list(self.combat_achievements_incomplete),
            "bosses_missing": list(self.bosses_missing),
            "category_tallies": [tally.as_dict() for tally in self.category_tallies],
            "all_headline_criteria_met": self.all_headline_criteria_met(),
        }


def _diagnose_rejected_neighbours(
    state: MapState,
    unlocked: Mapping[str, bool],
    current: Derived,
    graph: SectionGraph,
) -> dict[str, str]:
    """For every chunk grid-adjacent to `unlocked` but not itself unlocked or
    eligible, why it was rejected: `"not rollable"` (no `chunkinfo['sections']`
    entry at all), `"not walkable (F2P rule)"`, or `"no qualifying section
    connection yet"`. Purely a reporting aid for a stuck run - reuses
    `neighbours._qualifying_edge` (the exact eligibility gate) rather than
    reimplementing it, and changes nothing about eligibility itself.
    """
    walkable_f2p = set(state.chunk_info.walkable_chunks_f2p)
    f2p = state.rules.get("F2P") is True
    sections = state.chunk_info.sections

    reasons: dict[str, str] = {}
    for chunk_id_str in unlocked:
        try:
            chunk_id = int(chunk_id_str)
        except ValueError:
            continue  # area names aren't grid-addressable
        for candidate_id in grid_neighbours(chunk_id):
            candidate = str(candidate_id)
            if candidate in unlocked or candidate in reasons:
                continue
            if candidate not in sections:
                reasons[candidate] = "not rollable (no sections entry)"
                continue
            if f2p and candidate not in walkable_f2p:
                reasons[candidate] = "not walkable (F2P rule)"
                continue
            edge = _qualifying_edge(
                graph, candidate, unlocked, current.reachable_sections, current.challenges.valid
            )
            if edge is None:
                reasons[candidate] = "no qualifying section connection yet"
    return reasons


def _check_quests(chunk_info: ChunkInfo, valid_quest: Mapping[str, Any]) -> tuple[str, ...]:
    quest_challenges = chunk_info.challenges.get("Quest") or {}
    by_base: dict[str, list[str]] = {}
    for name, challenge in quest_challenges.items():
        if not isinstance(challenge, dict):
            continue
        base = challenge.get("BaseQuest")
        if isinstance(base, str):
            by_base.setdefault(base, []).append(name)
    incomplete = sorted(
        base for base, steps in by_base.items() if any(step not in valid_quest for step in steps)
    )
    return tuple(incomplete)


def _check_diaries(chunk_info: ChunkInfo, valid_diary: Mapping[str, Any]) -> tuple[str, ...]:
    diary_challenges = chunk_info.challenges.get("Diary") or {}
    incomplete = sorted(
        name
        for name, challenge in diary_challenges.items()
        if isinstance(challenge, dict) and "Reward" in challenge and name not in valid_diary
    )
    return tuple(incomplete)


def _check_combat_achievements(chunk_info: ChunkInfo, valid_diary: Mapping[str, Any]) -> tuple[str, ...]:
    diary_challenges = chunk_info.challenges.get("Diary") or {}
    incomplete = sorted(
        name
        for name, challenge in diary_challenges.items()
        if isinstance(challenge, dict)
        and challenge.get("BaseQuest") == "Combat Achievements"
        and name not in valid_diary
    )
    return tuple(incomplete)


def _check_bosses(chunk_info: ChunkInfo, monsters: Mapping[str, Any]) -> tuple[str, ...]:
    boss_monsters = _mapping(chunk_info.code_items, "bossMonsters")
    return tuple(sorted(boss for boss in boss_monsters if boss not in monsters))


def _build_outcome(
    state: MapState,
    current_ids: dict[str, bool],
    derived: Derived,
    steps: list[ChunkmanStep],
    chunk_info: ChunkInfo,
    rejected_neighbours: dict[str, str],
    *,
    stuck: bool,
) -> ChunkmanOutcome:
    valid_quest = derived.challenges.valid.get("Quest", {})
    valid_diary = derived.challenges.valid.get("Diary", {})
    tallies = tuple(
        CategoryTally(
            category=category,
            valid_total=len(derived.challenges.valid.get(category, {})),
            completed_total=len(state.completed_challenges.get(category, {})),
        )
        for category in sorted(AUTO_COMPLETE_CATEGORIES)
    )
    return ChunkmanOutcome(
        stuck=stuck,
        steps=tuple(steps),
        final_unlocked=dict(current_ids),
        final_state=state,
        final_derived=derived,
        rejected_neighbours=rejected_neighbours,
        every_chunk_unlocked=len(current_ids) == len(chunk_info.sections),
        quests_incomplete=_check_quests(chunk_info, valid_quest),
        diaries_incomplete=_check_diaries(chunk_info, valid_diary),
        combat_achievements_incomplete=_check_combat_achievements(chunk_info, valid_diary),
        bosses_missing=_check_bosses(chunk_info, derived.source_index.monsters),
        category_tallies=tallies,
    )


def run_chunkman(
    chunk_info: ChunkInfo,
    rules: Mapping[str, Any],
    *,
    start_chunk_id: str = "12850",
    start_section: str | None = "1",
    seed: int | None = 12850,
    carry_areas: bool = True,
) -> ChunkmanOutcome:
    """Run one seeded chunkman simulation from `start_chunk_id` to whichever
    terminal state comes first. See the module docstring for the two
    termination conditions and why the start is fixed rather than random.

    **`start_section` is the spawn point, not a connectivity fact.** Chunk
    `12850` (Lumbridge)'s own sections all require a *different* chunk's
    section to already be reachable, and none of its neighbours' declared
    connections point at its section `0` (the only section every unlocked
    chunk gets for free) either - so under the ordinary `Connect` graph
    alone, unlocking `12850` with nothing else reaches no neighbour at all
    in any direction, confirmed by tracing `neighbours._qualifying_edge`
    directly. That is a real property of the export's connectivity data,
    not a bug: it reflects that the game places a fresh account inside a
    *specific* section (`12850-1`, Lumbridge's main square - not `-2` or
    `-3`) via teleport, which the `Connect` graph has no way to encode since
    it only ever describes walking between already-reachable places. This
    parameter is threaded through as `manual_sections` precisely because
    that override exists for exactly this shape of fact - see
    `sections.unlocked_sections`'s own docstring on a `manualSections` entry
    seeding the accumulator before the fixed point runs. Confirmed against
    the real export: with `12850-1` seeded, the eligible pool from a bare
    `{"12850": True}` start is exactly `{12594, 12849, 12851, 13106}` - its
    four grid neighbours, each via a declared connection into `12850-1`.
    Pass `None` to start with no section override at all (the ordinary
    `Connect`-graph-only behaviour), which is almost always wrong for a
    single-chunk start.
    """
    manual_sections = {start_chunk_id: {start_section: True}} if start_section is not None else {}
    state = maxed_account_state(chunk_info, rules, manual_sections=manual_sections)
    current_ids: dict[str, bool] = {start_chunk_id: True}
    graph = build_section_graph(chunk_info)
    rng = Random(seed)
    steps: list[ChunkmanStep] = []

    before = derive(state, current_ids)
    order = 0
    stuck = False
    while True:
        order += 1
        targets = _auto_complete_targets(before, state.completed_challenges)
        if targets:
            merged = {
                category: {**state.completed_challenges.get(category, {}), **names}
                for category, names in targets.items()
            }
            state = dataclasses.replace(
                state, completed_challenges={**state.completed_challenges, **merged}
            )
            carry = dict(before.expanded_chunks) if carry_areas else None
            before = derive(state, current_ids, carry_areas=carry)

        pool = roll_pool(state, current_ids, before, graph=graph)
        if not pool:
            stuck = True
            steps.append(
                ChunkmanStep(
                    order=order,
                    pool_size_before_roll=0,
                    newly_completed={category: sorted(names) for category, names in targets.items()},
                    chunk_id=None,
                    delta=None,
                )
            )
            break

        chunk_id = rng.choice(pool)
        current_ids = {**current_ids, chunk_id: True}
        carry = dict(before.expanded_chunks) if carry_areas else None
        after = derive(state, current_ids, carry_areas=carry)
        delta = delta_from(before, after, chunk_id, state=state)
        steps.append(
            ChunkmanStep(
                order=order,
                pool_size_before_roll=len(pool),
                newly_completed={category: sorted(names) for category, names in targets.items()},
                chunk_id=chunk_id,
                delta=delta,
            )
        )
        before = after
        if len(current_ids) == len(chunk_info.sections):
            break

    if carry_areas and steps:
        verified = derive(state, current_ids)
        if verified != before:
            raise CarryDivergedError(
                "carrying areas reached a different derivation from deriving "
                f"cold after {len(steps)} chunkman step(s); re-run with "
                "carry_areas=False, and see pipeline.derive"
            )
        before = verified

    rejected = _diagnose_rejected_neighbours(state, current_ids, before, graph) if stuck else {}
    return _build_outcome(state, current_ids, before, steps, chunk_info, rejected, stuck=stuck)


def write_report(outcome: ChunkmanOutcome, path: Path) -> None:
    """Write `outcome` as structured JSON at `path` - re-loadable and
    diffable across runs, which is the primary artifact an investigation
    into a stuck run works from."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(outcome.as_dict(), indent=2, sort_keys=True), encoding="utf-8")


def summarize(outcome: ChunkmanOutcome) -> str:
    """A short human-readable summary of `outcome` - one line per headline
    criterion, the category tally table, and, for a stuck run, every
    rejected neighbour and why."""
    total_sections = len(outcome.final_state.chunk_info.sections)
    lines = [
        f"chunkman: {'STUCK' if outcome.stuck else 'COMPLETE'} after {len(outcome.steps)} step(s)",
        f"  every chunk unlocked: {outcome.every_chunk_unlocked} "
        f"({len(outcome.final_unlocked)}/{total_sections})",
        f"  quests incomplete: {len(outcome.quests_incomplete)}",
        f"  diaries incomplete: {len(outcome.diaries_incomplete)}",
        f"  combat achievements incomplete: {len(outcome.combat_achievements_incomplete)}",
        f"  bosses missing: {len(outcome.bosses_missing)}",
        "",
        "category tallies (completed/valid, gap):",
    ]
    for tally in outcome.category_tallies:
        lines.append(f"  {tally.category}: {tally.completed_total}/{tally.valid_total} (gap {tally.gap})")
    if outcome.stuck and outcome.rejected_neighbours:
        lines.append("")
        lines.append("rejected neighbours:")
        for chunk_id, reason in sorted(outcome.rejected_neighbours.items(), key=lambda kv: int(kv[0])):
            lines.append(f"  {chunk_id}: {reason}")
    return "\n".join(lines)


def persist_stuck_state(
    outcome: ChunkmanOutcome,
    rules: Mapping[str, Any],
    *,
    base_map: str,
    base_fetched_at: str | None = None,
    name: str = "chunkman-stuck",
    root: Path | None = None,
) -> SavedEdit:
    """Persist a **stuck** run's final state as a real cached map
    (`cache/maps/edited/<name>`), loadable via `--map <name>` for
    interactive investigation with this project's own CLI/GUI. **Call this
    only when `outcome.stuck` is true** - see the module docstring for why a
    successful run is never persisted.

    Builds a synthetic base payload from scratch (empty chunks, no
    completions, `rules` and every skill at 99) rather than starting from a
    real fetched map - chunkman's own account never was one. `save_edit` (an
    existing primitive, reused rather than reimplemented) then applies the
    whole run's unlocked-chunk set and completed-challenge set as one edit.

    `replace=True` is tried first, so repeated investigation runs update the
    same cached map in place rather than accumulating a new one each time -
    falling back to `replace=False` only the first time the map doesn't
    exist yet.
    """
    maxed = {skill: MAX_SKILL_LEVEL for skill in ALL_SKILLS}
    base_payload: dict[str, Any] = {
        "chunks": {"unlocked": {}},
        "rules": dict(rules),
        "settings": {},
        "chunkinfo": {"maxSkill": maxed, "passiveSkill": {}},
    }
    ticked = {
        category: sorted(names)
        for category, names in outcome.final_state.completed_challenges.items()
        if names
    }
    unlocked = sorted(outcome.final_unlocked, key=chunk_sort_key)

    try:
        return save_edit(
            name=name,
            payload=base_payload,
            ticked=ticked,
            unlocked=unlocked,
            base_map=base_map,
            base_fetched_at=base_fetched_at,
            replace=True,
            root=root,
        )
    except CacheMissError:
        return save_edit(
            name=name,
            payload=base_payload,
            ticked=ticked,
            unlocked=unlocked,
            base_map=base_map,
            base_fetched_at=base_fetched_at,
            replace=False,
            root=root,
        )
