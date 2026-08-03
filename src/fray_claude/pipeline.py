"""Run the full sections -> sources -> challenges pipeline for a chunk set.

`MapState` bundles the per-map inputs that stay fixed across a single `fray`
invocation (the chunkinfo export, decoded rules/settings, manual overrides);
`derive` runs the pipeline for a given *set of unlocked chunk ids*, so
`unlock.py` and `simulate.py` can call it twice - once for the current
state, once for a candidate chunk added - without duplicating the
`unlocked_sections` -> `gather_chunks_info` -> `calc_challenges` wiring that
`cli.py`'s `sections`/`sources`/`tasks` subcommands also share.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fray_claude.challenges import ChallengeResult, calc_challenges
from fray_claude.chunkinfo import ChunkInfo
from fray_claude.firebase import decode_payload
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


@dataclass(frozen=True)
class Derived:
    """One pipeline run's full output for a given unlocked-chunk-id set."""

    reachable_sections: dict[str, dict[str, bool]]
    source_index: SourceIndex
    challenges: ChallengeResult


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
    )
    challenges = calc_challenges(
        expanded, reachable, index, state.chunk_info, rules=state.rules, max_skill=state.max_skill
    )
    return Derived(reachable_sections=reachable, source_index=index, challenges=challenges)


def load_map_state(payload: Mapping[str, Any], chunk_info: ChunkInfo) -> tuple[MapState, dict[str, bool]]:
    """Decode a raw cached-map payload into a `MapState` plus its unlocked
    chunk ids. None of the decoded branches reference `t_N` task ids (they
    hold chunk, item, monster, and rule names), so decoding with no tasks
    map is safe - see `firebase.decode_payload`.
    """
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
    )
    return state, unlocked
