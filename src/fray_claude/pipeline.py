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
from fray_claude.sections import expand_chunk_areas, unlocked_sections
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
    manual_monsters: Mapping[str, Any]
    manual_equipment: Mapping[str, Any]
    backlogged_sources: Mapping[str, Any]
    max_skill: Mapping[str, int]
    passive_skill: Mapping[str, int]
    completed_challenges: Mapping[str, Mapping[str, Any]]
    manual_tasks: Mapping[str, Mapping[str, Any]]
    backlog: Mapping[str, Mapping[str, Any]]
    active_tasks: Mapping[str, Mapping[str, Any]]


@dataclass(frozen=True)
class Derived:
    """One pipeline run's full output for a given unlocked-chunk-id set."""

    reachable_sections: dict[str, dict[str, bool]]
    source_index: SourceIndex
    challenges: ChallengeResult
    bis: BisResult
    task_classification: TaskClassification


def derive(state: MapState, unlocked: Mapping[str, bool]) -> Derived:
    """Run `unlocked_sections` -> `gather_chunks_info` -> `calc_challenges`."""
    reachable = unlocked_sections(
        unlocked,
        state.chunk_info,
        manual_sections=state.manual_sections,
        opt_out_sections=state.settings.get("optOutSections") is True,
        opt_out_sections_water=state.settings.get("optOutSectionsWater") is True,
    )
    expanded = expand_chunk_areas(unlocked)
    index = gather_chunks_info(
        expanded,
        reachable,
        state.chunk_info,
        rules=state.rules,
        backlogged_sources=state.backlogged_sources,
        manual_monsters=state.manual_monsters,
        manual_equipment=state.manual_equipment,
        max_skill=state.max_skill,
    )
    challenges = calc_challenges(
        expanded, reachable, index, state.chunk_info, rules=state.rules, max_skill=state.max_skill
    )
    bis = compute_bis(
        state.chunk_info,
        index.items,
        challenges.valid,
        rules=state.rules,
        max_skill=state.max_skill,
        passive_skill=state.passive_skill,
        completed_bis=state.completed_challenges.get("BiS", {}),
    )
    task_classification = classify_tasks(
        challenges.valid,
        state.chunk_info,
        completed_challenges=state.completed_challenges,
        manual_tasks=state.manual_tasks,
        backlog=state.backlog,
        passive_skill=state.passive_skill,
    )
    return Derived(
        reachable_sections=reachable,
        source_index=index,
        challenges=challenges,
        bis=bis,
        task_classification=task_classification,
    )


def load_map_state(
    payload: Mapping[str, Any], chunk_info: ChunkInfo, tasks_map: Mapping[str, str] | None = None
) -> tuple[MapState, dict[str, bool]]:
    """Decode a raw cached-map payload into a `MapState` plus its unlocked
    chunk ids. Most decoded branches hold chunk/item/monster/rule names, not
    `t_N` task ids, so decoding those needs no `tasks_map` - see
    `firebase.decode_payload`. `activeTasks`/`completedChallenges`/`backlog`
    key every category by `t_N` id *except* `BiS`, which uses literal name
    keys (see `firebase.decode_challenge_keyed`) - so without `tasks_map`
    those decode to an empty dict for every other category (an unresolved
    `t_N` key is dropped, not kept raw) rather than raising. Pass the
    reverse map from `firebase.reverse_tasks_map` (built from the cached
    `tasks_map` blob) when available.
    """
    tasks_map = tasks_map or {}
    chunkinfo_branch = _mapping(payload, "chunkinfo")
    unlocked = decode_payload(_mapping(_mapping(payload, "chunks"), "unlocked"))
    state = MapState(
        chunk_info=chunk_info,
        rules=decode_payload(_mapping(payload, "rules")),
        settings=_mapping(payload, "settings"),
        manual_sections=decode_payload(_mapping(chunkinfo_branch, "manualSections")),
        manual_monsters=decode_payload(_mapping(chunkinfo_branch, "manualMonsters")),
        manual_equipment=decode_payload(_mapping(chunkinfo_branch, "manualEquipment")),
        backlogged_sources=decode_payload(_mapping(chunkinfo_branch, "backloggedSources")),
        max_skill=decode_payload(_mapping(chunkinfo_branch, "maxSkill")),
        passive_skill=decode_payload(_mapping(chunkinfo_branch, "passiveSkill")),
        completed_challenges=decode_challenge_keyed(
            _mapping(chunkinfo_branch, "completedChallenges"), tasks_map
        ),
        manual_tasks=decode_challenge_keyed(
            _mapping(chunkinfo_branch, "manualTasks"), tasks_map, skip_task_ids=True
        ),
        backlog=decode_challenge_keyed(_mapping(chunkinfo_branch, "backlog"), tasks_map),
        active_tasks=decode_challenge_keyed(_mapping(chunkinfo_branch, "activeTasks"), tasks_map),
    )
    return state, unlocked
