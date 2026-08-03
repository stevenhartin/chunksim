"""Run the full sections -> sources -> challenges pipeline for a chunk set.

`MapState` bundles the per-map inputs that stay fixed across a single `fray`
invocation (the chunkinfo export, decoded rules/settings, manual overrides);
`derive` runs the pipeline for a given *set of unlocked chunk ids*, so
`unlock.py` and `simulate.py` can call it twice - once for the current
state, once for a candidate chunk added - without duplicating the
`unlocked_sections` -> `gather_chunks_info` -> `calc_challenges` -> `compute_bis` ->
`classify_tasks` wiring that `cli.py`'s `sections`/`sources`/`tasks` subcommands also share.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fray_claude.active_tasks import TaskClassification, classify_tasks
from fray_claude.bis import BisResult, compute_bis
from fray_claude.challenges import ChallengeResult, calc_challenges
from fray_claude.chunkinfo import ChunkInfo
from fray_claude.firebase import decode_challenge_keyed, decode_payload
from fray_claude.sections import expand_chunk_areas, unlockable_areas, unlocked_sections
from fray_claude.sources import SourceIndex, gather_chunks_info
from fray_claude.summary import _mapping


@dataclass(frozen=True)
class MapState:
    """Decoded, per-map inputs that don't change as candidate chunks are
    added - only the unlocked-chunk-id set passed to `derive` does.
    """

    chunk_info: ChunkInfo
    rules: Mapping[str, Any]
    settings: Mapping[str, Any]
    manual_sections: Mapping[str, Any]
    manual_areas: Mapping[str, bool]
    manual_monsters: Mapping[str, Any]
    manual_equipment: Mapping[str, Any]
    backlogged_sources: Mapping[str, Any]
    max_skill: Mapping[str, int]
    passive_skill: Mapping[str, int]
    #: `completedChallenges` merged with `checkedChallenges` - see
    #: `load_map_state` for why they're one thing here. Every completion
    #: *test* should read this, not the two branches separately.
    completed_challenges: Mapping[str, Mapping[str, Any]]
    #: The `checkedChallenges` half of the above on its own: what was ticked
    #: off during the chunk currently in play, before the next roll migrates
    #: it. A strict subset of `completed_challenges`, kept only so output can
    #: distinguish this chunk's acquisitions from earlier ones.
    checked_challenges: Mapping[str, Mapping[str, Any]]
    manual_tasks: Mapping[str, Mapping[str, Any]]
    backlog: Mapping[str, Mapping[str, Any]]
    active_tasks: Mapping[str, Mapping[str, Any]]
    #: Truthy `chunkinfo.constructionLocked` (real data: `{'chunk': '10547'}`)
    #: - Mahogany Homes is gated behind a chunk the player hasn't taken, which
    #: invalidates every contract tier. See `challenges.py`.
    construction_locked: bool = False


@dataclass(frozen=True)
class Derived:
    """One pipeline run's full output for a given unlocked-chunk-id set."""

    reachable_sections: dict[str, dict[str, bool]]
    source_index: SourceIndex
    challenges: ChallengeResult
    bis: BisResult
    task_classification: TaskClassification


#: Upper bound on `derive`'s convergence loop (area unlocks + `taskUnlocks`
#: source gating). The real export's chains are a couple of links deep, so
#: this is a runaway guard rather than a real limit.
_MAX_AREA_PASSES = 8


def derive(state: MapState, unlocked: Mapping[str, bool]) -> Derived:
    """Run `unlocked_sections` -> `gather_chunks_info` -> `calc_challenges`,
    looping while newly-valid challenges unlock further named areas.

    That loop is what makes this function, rather than any single module,
    the place upstream's circularity lives: an `UnlocksArea` challenge only
    becomes valid once its requirements are met, and unlocking the area it
    names adds that area's monsters/items as *new sources*, which can in turn
    validate more challenges (upstream does the same thing by re-running
    `gatherChunksInfo` mid-`calcChallenges`, worker.js:2153). Keeping the
    loop here lets `sections.py`/`sources.py`/`challenges.py` each stay
    one-directional and separately testable.

    The same loop feeds each pass's validity back into `gather_chunks_info`
    as `valid_tasks`, which is how `taskUnlocks` gating works: a shop or
    monster present in a chunk can still be locked behind completing a
    challenge there (upstream's `shouldDelete` pass deletes such entries
    from an already-built index instead; iterating to a fixed point reaches
    the same answer without a mutate-after-the-fact step). The first pass
    runs ungated, so a gate can only ever *remove* a source that its own
    unlock task hadn't yet justified.
    """
    expanded = expand_chunk_areas(unlocked, manual_areas=state.manual_areas)
    reachable: dict[str, dict[str, bool]] = {}
    index: SourceIndex | None = None
    challenges: ChallengeResult | None = None
    valid_tasks: dict[str, dict[str, int | str | bool]] = {}

    for _ in range(_MAX_AREA_PASSES):
        reachable = unlocked_sections(
            expanded,
            state.chunk_info,
            manual_sections=state.manual_sections,
            opt_out_sections=state.settings.get("optOutSections") is True,
            opt_out_sections_water=state.settings.get("optOutSectionsWater") is True,
        )
        index = gather_chunks_info(
            expanded,
            reachable,
            state.chunk_info,
            rules=state.rules,
            backlogged_sources=state.backlogged_sources,
            manual_monsters=state.manual_monsters,
            manual_equipment=state.manual_equipment,
            max_skill=state.max_skill,
            valid_tasks=valid_tasks,
        )
        challenges = calc_challenges(
            expanded,
            reachable,
            index,
            state.chunk_info,
            rules=state.rules,
            max_skill=state.max_skill,
            backlogged_sources=state.backlogged_sources,
            passive_skill=state.passive_skill,
            backlog=state.backlog,
            manual_tasks=state.manual_tasks,
            construction_locked=state.construction_locked,
        )
        new_areas = unlockable_areas(
            challenges.valid,
            expanded,
            reachable,
            state.chunk_info,
            manual_areas=state.manual_areas,
            max_skill=state.max_skill,
            passive_skill=state.passive_skill,
        )
        if not new_areas and challenges.valid == valid_tasks:
            break
        valid_tasks = challenges.valid
        expanded = {**expanded, **new_areas}

    assert index is not None and challenges is not None  # loop always runs at least once
    bis = compute_bis(
        state.chunk_info,
        # Not `index.items`: BiS candidates must include items that only
        # exist as a valid challenge's `Output` (e.g. `Granite ring (i)`,
        # obtainable solely by imbuing one) - see `ChallengeResult`.
        challenges.available_items,
        challenges.valid,
        rules=state.rules,
        max_skill=state.max_skill,
        passive_skill=state.passive_skill,
        completed_bis=state.completed_challenges.get("BiS", {}),
        checked_bis=state.checked_challenges.get("BiS", {}),
    )
    task_classification = classify_tasks(
        challenges.valid,
        state.chunk_info,
        completed_challenges=state.completed_challenges,
        manual_tasks=state.manual_tasks,
        backlog=state.backlog,
        passive_skill=state.passive_skill,
        source_index=index,
        rules=state.rules,
    )
    return Derived(
        reachable_sections=reachable,
        source_index=index,
        challenges=challenges,
        bis=bis,
        task_classification=task_classification,
    )


def _merge_challenge_keyed(
    *branches: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Union several `{category: {name: value}}` branches."""
    merged: dict[str, dict[str, Any]] = {}
    for branch in branches:
        for category, entries in branch.items():
            merged.setdefault(category, {}).update(entries)
    return merged


def load_map_state(
    payload: Mapping[str, Any], chunk_info: ChunkInfo, tasks_map: Mapping[str, str] | None = None
) -> tuple[MapState, dict[str, bool]]:
    """Decode a raw cached-map payload into a `MapState` plus its unlocked
    chunk ids. Most decoded branches hold chunk/item/monster/rule names, not
    `t_N` task ids, so decoding those needs no `tasks_map` - see
    `firebase.decode_payload`. `activeTasks`/`completedChallenges`/`backlog`
    key entries by `t_N` id (mixed with the occasional literal name; see
    `firebase.decode_challenge_keyed`), so without `tasks_map` every id-keyed
    entry is dropped rather than kept raw. Pass the reverse map from
    `firebase.reverse_tasks_map` (built from the cached `tasks_map` blob)
    when available.

    `completed_challenges` merges `checkedChallenges` into
    `completedChallenges`. They're separate upstream only as a commit step:
    ticking a task's checkbox writes `checkedChallenges`, and rolling the
    next chunk migrates the lot into `completedChallenges` and clears it
    (`completeChallenges`, index.js:12718). So anything obtained during the
    *current* chunk sits only in `checkedChallenges` - treating that as
    not-yet-obtained would report an item you already hold as still to get.
    `checked_challenges` keeps that half addressable on its own, so output
    can mark what was banked this chunk; it is a view for display, not a
    second source of truth - completion tests use `completed_challenges`.
    """
    tasks_map = tasks_map or {}
    chunkinfo_branch = _mapping(payload, "chunkinfo")
    unlocked = decode_payload(_mapping(_mapping(payload, "chunks"), "unlocked"))
    checked_challenges = decode_challenge_keyed(
        _mapping(chunkinfo_branch, "checkedChallenges"), tasks_map
    )
    state = MapState(
        chunk_info=chunk_info,
        rules=decode_payload(_mapping(payload, "rules")),
        settings=_mapping(payload, "settings"),
        manual_sections=decode_payload(_mapping(chunkinfo_branch, "manualSections")),
        manual_areas=decode_payload(_mapping(chunkinfo_branch, "manualAreas")),
        manual_monsters=decode_payload(_mapping(chunkinfo_branch, "manualMonsters")),
        manual_equipment=decode_payload(_mapping(chunkinfo_branch, "manualEquipment")),
        backlogged_sources=decode_payload(_mapping(chunkinfo_branch, "backloggedSources")),
        max_skill=decode_payload(_mapping(chunkinfo_branch, "maxSkill")),
        passive_skill=decode_payload(_mapping(chunkinfo_branch, "passiveSkill")),
        completed_challenges=_merge_challenge_keyed(
            decode_challenge_keyed(_mapping(chunkinfo_branch, "completedChallenges"), tasks_map),
            checked_challenges,
        ),
        checked_challenges=checked_challenges,
        manual_tasks=decode_challenge_keyed(
            _mapping(chunkinfo_branch, "manualTasks"), tasks_map, skip_task_ids=True
        ),
        backlog=decode_challenge_keyed(_mapping(chunkinfo_branch, "backlog"), tasks_map),
        active_tasks=decode_challenge_keyed(_mapping(chunkinfo_branch, "activeTasks"), tasks_map),
        construction_locked=bool(chunkinfo_branch.get("constructionLocked")),
    )
    return state, unlocked
