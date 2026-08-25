"""Which sections of the unlocked chunks are actually reachable.

Not every chunk is a single unit: 505 of the export's 2,222 chunks are split
into numbered sections (`Sections` in a chunk's entry), and a chunk being
"unlocked" only makes its section `0` reachable - crossing into section `1`
requires a connection (`sections[chunk][n]`, a list of other sections/chunks)
that is itself already reachable, or a static per-section `Connect` link to
another chunk that's separately unlocked. This module ports upstream's fixed
point over that connectivity: `findConnectedSections` (worker.js) plus the
one live part of `getAllChunkAreas` (worker.js).

`getAllChunkAreas`'s *auto-add* branch is dead code upstream: its filter
predicate (`.filter(subArea => { chunks.hasOwnProperty(subArea) })`) is an
arrow function with a block body and no `return`, so it always evaluates to
`undefined` and the branch it guards can never run. Only the `manualAreas`
override adds chunks there, which is all `expand_chunk_areas` reproduces.

That function's *other* output is very much live, though, and is what
`area_connections` ports: the same walk builds `areasStructure` (named area
-> the chunks connecting to it) and `possibleAreas` (its key set). Named
areas are how a chunk set reaches places like `Wilderness God Wars Dungeon`:
the export stores such an area twice - once as the numbered entrance chunk
carrying `Connect`/`Name` (`6727` -> `Grotesque Guardians' Lair`), and once
under the area's *name* as a top-level `chunks` key holding its actual
contents. Adding the name to the unlocked set is therefore what makes the
area's monsters and drops visible to `sources.gather_chunks_info`.

`unlockable_areas` ports the pass that decides when that happens
(worker.js:2102-2155, inside `calcChallenges`): a `Nonskill` challenge
carrying `UnlocksArea` that is currently *valid* unlocks the area it names,
subject to its `SkillsNeeded` gate and to the area connecting to a chunk you
already have. Missing this pass was a real reported bug: `Spiritual mage` and
`Grotesque Guardians` - and so `Dragon boots` and `Granite gloves` - were
invisible, and the BiS oracle sat at 1 of 6. Because that pass
consumes challenge validity and feeds back into source gathering, the loop
driving it lives in `pipeline.derive`, not here - see its docstring.

`sectionsLimits` is deliberately absent from this module - it gates
*rollable-neighbour* eligibility (`selectAllNeighborsCanvas`, index.js), not
the connectivity of chunks already unlocked, so it belongs with the roll
simulation instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from chunksim.model.chunkinfo import ChunkInfo

# Areas upstream explicitly excludes from cross-chunk connectivity
# (index.js `unconnectedAreas`) - not present anywhere in the export itself.
UNCONNECTED_AREAS = frozenset({"Zanaris", "Puro-Puro", "Player-owned house"})


def expand_chunk_areas(
    chunk_ids: Mapping[str, bool], *, manual_areas: Mapping[str, bool] | None = None
) -> dict[str, bool]:
    """Port of `getAllChunkAreas`'s only chunk-adding effect: the
    `manualAreas` override. Areas earned by completing an `UnlocksArea`
    challenge come from `unlockable_areas` instead."""
    expanded = dict(chunk_ids)
    for area, enabled in (manual_areas or {}).items():
        if enabled:
            expanded[area] = True
        else:
            expanded.pop(area, None)
    return expanded


def area_connections(
    chunk_ids: Mapping[str, bool], chunk_info: ChunkInfo
) -> dict[str, dict[str, bool]]:
    """Port of `getAllChunkAreas`' Connect walk: named area -> the chunks in
    `chunk_ids` that connect to it (upstream's `areasStructure`; its key set
    is upstream's `possibleAreas`).

    Walks each chunk's top-level `Connect` and every `Sections[n].Connect`,
    recording any target that carries a string `Name`. Not transitive:
    upstream pushes discovered area *names* back into the set it's walking,
    but then indexes `chunkInfo['chunks']` by that name and guards on the
    result being truthy - and the name-keyed entry holds the area's contents,
    never `Connect` - so a name never contributes further links.
    """
    structure: dict[str, dict[str, bool]] = {}

    def record(source: str, targets: Any) -> None:
        if not isinstance(targets, dict):
            return
        for target in targets:
            name = chunk_info.chunk(target).get("Name")
            if isinstance(name, str) and name:
                structure.setdefault(name, {})[source] = True

    for chunk_id in chunk_ids:
        entry = chunk_info.chunk(chunk_id)
        record(chunk_id, entry.get("Connect"))
        sections_field = entry.get("Sections")
        if isinstance(sections_field, dict):
            for section_entry in sections_field.values():
                if isinstance(section_entry, dict):
                    record(chunk_id, section_entry.get("Connect"))
    return structure


def _skills_needed_met(
    needed: Mapping[str, Any],
    *,
    valid: Mapping[str, Mapping[str, Any]],
    max_skill: Mapping[str, int],
    passive_skill: Mapping[str, int],
) -> bool:
    """Port of the `SkillsNeeded` gate (worker.js:2108): a required skill
    blocks the unlock if it isn't trainable at all or the level exceeds
    `maxSkill`, *unless* `passiveSkill` already covers it. `checkPrimaryMethod`
    is approximated by "the skill has any valid challenge" - the same shape as
    `challenges._has_any_valid`, but note that is **no longer how
    `challenges.py` decides trainability**: it ports the real thing as
    `_check_primary_method`. Calling that from here would invert the module
    layering (this module sits below `sources.py`, and imports only
    `chunkinfo`), and `unlockable_areas` isn't handed the `SourceIndex`/rules
    it needs regardless - so this stays the looser test, and is looser than
    the gate `challenges.py` applies to the same skill. The `slayerLocked`
    clause arrives folded into `max_skill['Slayer']`
    (`pipeline.slayer_capped_max_skill`), so `cap` already carries it.
    """
    for skill, level in needed.items():
        if not isinstance(level, (int, float)):
            continue
        cap = max_skill.get(skill)
        blocked = not bool(valid.get(skill)) or (isinstance(cap, (int, float)) and level > cap)
        passive = passive_skill.get(skill)
        covered = isinstance(passive, (int, float)) and passive > 1 and level <= passive
        if blocked and not covered:
            return False
    return True


def _area_is_connected(
    area: str,
    connectors: Mapping[str, bool],
    chunk_ids: Mapping[str, bool],
    reachable_sections: Mapping[str, Mapping[str, bool]],
    chunk_info: ChunkInfo,
) -> bool:
    """Port of the connectivity check (worker.js:2125-2140): at least one
    chunk connecting to `area` must be unlocked - and, when that chunk is
    split into sections, the section actually linking to `area` must be
    reachable.
    """
    for source in connectors:
        if source not in chunk_ids:
            continue
        entry = chunk_info.chunk(source)
        sections_field = entry.get("Sections")
        if not isinstance(sections_field, dict) or not sections_field:
            return True
        for section, section_entry in sections_field.items():
            if not isinstance(section_entry, dict):
                continue
            if not reachable_sections.get(source, {}).get(section):
                continue
            targets = section_entry.get("Connect")
            if not isinstance(targets, dict):
                continue
            if any(chunk_info.chunk(target).get("Name") == area for target in targets):
                return True
    return False


def unlockable_areas(
    valid: Mapping[str, Mapping[str, Any]],
    chunk_ids: Mapping[str, bool],
    reachable_sections: Mapping[str, Mapping[str, bool]],
    chunk_info: ChunkInfo,
    *,
    manual_areas: Mapping[str, bool] | None = None,
    max_skill: Mapping[str, int] | None = None,
    passive_skill: Mapping[str, int] | None = None,
) -> dict[str, bool]:
    """Named areas the currently-valid challenges unlock, not already in
    `chunk_ids` - port of worker.js:2102-2155.

    An area is unlocked by a *valid* `Nonskill` challenge whose name is the
    area's and which carries `UnlocksArea`, subject to its `SkillsNeeded`
    gate and to the area connecting to a chunk already unlocked. Upstream's
    `deadChunkArray` re-queue (which retries an area whose only connectors
    are themselves not-yet-unlocked areas) isn't reproduced here: driving
    this to a fixed point is `pipeline.derive`'s job, and re-running the
    whole pass subsumes it.
    """
    manual_areas = manual_areas or {}
    nonskill_valid = valid.get("Nonskill") or {}
    nonskill_challenges = chunk_info.challenges.get("Nonskill") or {}
    structure = area_connections(chunk_ids, chunk_info)

    unlocked: dict[str, bool] = {}
    for area in nonskill_valid:
        if area in chunk_ids or area in unlocked:
            continue
        challenge = nonskill_challenges.get(area)
        if not isinstance(challenge, dict) or challenge.get("UnlocksArea") is not True:
            continue
        if area in manual_areas and not manual_areas[area]:
            continue
        connectors = structure.get(area)
        if not connectors:
            continue
        needed = challenge.get("SkillsNeeded")
        if isinstance(needed, dict) and not _skills_needed_met(
            needed, valid=valid, max_skill=max_skill or {}, passive_skill=passive_skill or {}
        ):
            continue
        if _area_is_connected(area, connectors, chunk_ids, reachable_sections, chunk_info):
            unlocked[area] = True
    return unlocked


def connected_sections(
    valid: Mapping[str, Mapping[str, Any]],
    chunk_ids: Mapping[str, bool],
    reachable_sections: Mapping[str, Mapping[str, bool]],
    chunk_info: ChunkInfo,
    *,
    manual_sections: Mapping[str, Mapping[str, bool]] | None = None,
) -> dict[str, dict[str, bool]]:
    """Sections a valid `ConnectsSections` challenge opens, not already
    reachable - port of worker.js:2110-2124, `calcChallenges`'s own
    handling right beside the `UnlocksArea` block `unlockable_areas` above
    already ports.

    **A second way in, beside the ordinary `Connect` graph.** A `Nonskill`
    challenge carrying `ConnectsSections: true` and a `Sections` list is the
    export's own way of saying a pair of sections - or, once, a lone one -
    are joined by something `chunkinfo['sections']` cannot express: an
    Agility shortcut (`"10018-1 to 10018-3"`, gated on the shortcut task
    itself), a minigame crossing (`"Access stormy seas"`, `"Access
    crystal-flecked waters"`), a quest-built passage (Pandemonium's cargo
    hold). 260 such challenges exist on the real export and 61 of them
    name a section this project's own `Connect`-only graph could not
    otherwise reach at all - the `sections`/`graph.py` fixed point has no
    way to see any of them, because none of it is `Connect` data.

    **The gate is the challenge itself, already judged.** Once `name` is
    valid (its own `Tasks`/`Items`/`Skills`/whatever `calc_challenges`
    already checked), every chunk its `Sections` list names must already
    be in `chunk_ids` (`chunksValid`), and at least one of those sections
    must already be reachable - or the list holds exactly one entry, which
    needs nothing (`oneSectionValid`; a bare, dash-less chunk id in the
    list counts as always-open, matching a bare `Connect` ref's own
    meaning). Once both hold, every other named section opens, unless a
    `manualSections` entry seals it `False` - a player's own closed door
    still wins over a shortcut nothing here disputes they *could* use.

    **Why this is not folded into `unlocked_sections` itself**: that
    function's own fixed point runs over `chunk_info.sections` alone and
    has no `valid` to test a challenge's gates against - a section this
    unlocks can, in turn, make more `Nonskill` challenges valid, which is
    exactly the circularity `pipeline.derive`'s outer loop already exists
    to settle for `unlockable_areas`'s own result. Same shape, same loop,
    separate function for the same reason that one is.
    """
    manual = manual_sections or {}
    nonskill_valid = valid.get("Nonskill") or {}
    nonskill_challenges = chunk_info.challenges.get("Nonskill") or {}

    opened: dict[str, dict[str, bool]] = {}
    for name in nonskill_valid:
        challenge = nonskill_challenges.get(name)
        if not isinstance(challenge, dict) or challenge.get("ConnectsSections") is not True:
            continue
        sections = challenge.get("Sections")
        if not isinstance(sections, list) or not sections:
            continue
        parts: list[tuple[str, str, bool]] = []
        chunks_ok = True
        for entry in sections:
            if not isinstance(entry, str):
                chunks_ok = False
                break
            chunk_id, sep, section_id = entry.partition("-")
            if chunk_id not in chunk_ids:
                chunks_ok = False
                break
            parts.append((chunk_id, section_id, bool(sep)))
        if not chunks_ok:
            continue
        one_open = len(parts) == 1 or any(
            not has_section or reachable_sections.get(chunk_id, {}).get(section_id)
            for chunk_id, section_id, has_section in parts
        )
        if not one_open:
            continue
        for chunk_id, section_id, has_section in parts:
            if not has_section:
                continue
            if reachable_sections.get(chunk_id, {}).get(section_id):
                continue
            if manual.get(chunk_id, {}).get(section_id) is False:
                continue
            opened.setdefault(chunk_id, {})[section_id] = True
    return opened


def unlocked_sections(
    chunk_ids: Mapping[str, bool],
    chunk_info: ChunkInfo,
    *,
    manual_areas: Mapping[str, bool] | None = None,
    manual_sections: Mapping[str, Mapping[str, bool]] | None = None,
    opt_out_sections: bool = False,
    opt_out_sections_water: bool = False,
    unresolved_sections_open: bool = True,
) -> dict[str, dict[str, bool]]:
    """Which sections of `chunk_ids` are reachable, as `{chunk: {section: True}}`.

    `unresolved_sections_open` turns off the `"???"` workaround wholesale -
    see `_unresolved_only`. It defaults to *on* because leaving it off makes
    34 real places unreachable on every possible map, including the Shipyard
    the Pandemonium quest is built in; it exists so a player who would rather
    match upstream's answers exactly can have them. The finer control is
    upstream's own and needs nothing from here: `manualSections` overrides
    any single section in **either** direction, and is checked before this
    runs, so a `false` entry seals a `???` section the workaround opened.

    Runs `expand_chunk_areas` first, then `findConnectedSections`'s fixed
    point: a section becomes reachable once one of its connections is
    reachable, and that can unlock further connections, so this repeats
    until a pass adds nothing new.

    Upstream's `findConnectedSections` is also re-entrant against
    previously-computed state (an explicit `false` marker gets cleared, to
    be reconsidered next refresh) - not modelled here, since this recomputes
    from scratch every call rather than incrementally refining UI state.
    """
    expanded = expand_chunk_areas(chunk_ids, manual_areas=manual_areas)
    manual = manual_sections or {}
    sections_data = chunk_info.sections
    chunks_data = chunk_info.chunks

    # A `manualSections` entry of `true` is a direct override - upstream
    # seeds it into the accumulator (`combineJSONs`) *before* the fixed
    # point runs, so it's reachable regardless of connectivity. A `false`
    # entry blocks the section below without needing to be seeded here: see
    # the module docstring for why upstream's own re-entrant handling of it
    # is not modelled.
    reachable: dict[str, dict[str, bool]] = {}
    for chunk, chunk_manual in manual.items():
        if chunk not in expanded or not isinstance(chunk_manual, dict):
            continue
        for section_id, flag in chunk_manual.items():
            if flag is True:
                reachable.setdefault(chunk, {})[section_id] = True

    added = True
    while added:
        added = False
        for chunk, chunk_sections in sections_data.items():
            if chunk not in expanded or not isinstance(chunk_sections, dict):
                continue
            for section_id, connections in chunk_sections.items():
                if section_id == "0" or reachable.get(chunk, {}).get(section_id):
                    continue
                if manual.get(chunk, {}).get(section_id) is False:
                    continue
                if _section_is_reachable(
                    chunk,
                    section_id,
                    connections,
                    expanded,
                    reachable,
                    chunks_data,
                    opt_out_sections=opt_out_sections,
                    opt_out_sections_water=opt_out_sections_water,
                    unresolved_sections_open=unresolved_sections_open,
                ):
                    reachable.setdefault(chunk, {})[section_id] = True
                    added = True
    return reachable


def _section_is_reachable(
    chunk: str,
    section_id: str,
    connections: Any,
    chunk_ids: Mapping[str, bool],
    reachable: Mapping[str, Mapping[str, bool]],
    chunks_data: Mapping[str, Any],
    *,
    opt_out_sections: bool,
    opt_out_sections_water: bool,
    unresolved_sections_open: bool = True,
) -> bool:
    if opt_out_sections_water:
        return True
    if opt_out_sections and "W" not in section_id:
        return True
    if isinstance(connections, list) and _any_connection_open(connections, chunk_ids, reachable):
        return True
    if _any_static_connect_open(chunk, section_id, chunk_ids, chunks_data):
        return True
    return unresolved_sections_open and _unresolved_only(connections)


#: The export's unresolved-neighbour placeholder. A section whose connection
#: list is nothing but this has had no route recorded for it *yet* - it is a
#: gap in upstream's data rather than a statement that the place is sealed.
UNRESOLVED_REF = "???"


def _unresolved_only(connections: Any) -> bool:
    """**A workaround for an upstream data gap - delete it when they fill
    the gap in.** A section whose every connection is `"???"` is treated as
    reachable the moment its chunk is unlocked, exactly as section `0` is.

    Upstream filters `???` out of its own connection walk (index.js:7708),
    as `graph.py` does, which leaves such a section reachable by nothing.
    Measured against the whole export: 55 sections list it, 4 of those are
    section `0` (already free), 18 more are rescued by a `Connect`
    named-area link, and **34 remain unreachable with every chunk in the
    game unlocked**. A section no configuration of the world can enter has
    no reason to be in the export at all, so the honest reading of `???` is
    "not recorded", not "sealed".

    The consequence was not academic. Pandemonium step 5 builds the cargo
    hold in the Shipyard, `8234-1`, which is one of them - so the quest
    could never complete, its `Raft` reward never arrived, and all 243
    Sailing challenges stayed invalid on **every** map. Real players already
    work around it by hand: the second cached map carries a `manualSections`
    entry for
    `12338-2`, another of them.

    **This deliberately fires per section rather than off a hardcoded id
    list, so it disappears on its own as upstream records the routes** - a
    section that gains one real connection stops matching here with no edit.
    `tests/test_sections.py` pins the count of sections still relying on it;
    when that reaches zero, this function and its call above should go.
    """
    return (
        isinstance(connections, list)
        and len(connections) > 0
        and all(isinstance(ref, str) and UNRESOLVED_REF in ref for ref in connections)
    )


def _any_connection_open(
    connections: list[Any],
    chunk_ids: Mapping[str, bool],
    reachable: Mapping[str, Mapping[str, bool]],
) -> bool:
    for connection in connections:
        if not isinstance(connection, str):
            continue
        if "-" in connection:
            target_chunk, _, target_section = connection.partition("-")
            if reachable.get(target_chunk, {}).get(target_section):
                return True
        elif connection in chunk_ids:
            return True
    return False


def _any_static_connect_open(
    chunk: str, section_id: str, chunk_ids: Mapping[str, bool], chunks_data: Mapping[str, Any]
) -> bool:
    entry = chunks_data.get(chunk)
    sections_field = entry.get("Sections") if isinstance(entry, dict) else None
    section_entry = sections_field.get(section_id) if isinstance(sections_field, dict) else None
    connect = section_entry.get("Connect") if isinstance(section_entry, dict) else None
    if not isinstance(connect, dict):
        return False
    for sub_chunk_id in connect:
        sub_entry = chunks_data.get(sub_chunk_id)
        name = sub_entry.get("Name") if isinstance(sub_entry, dict) else None
        if not isinstance(name, str) or name in UNCONNECTED_AREAS:
            continue
        if name in chunk_ids and chunk_ids[name] is not False:
            return True
    return False


@dataclass(frozen=True)
class ChunkSections:
    """One unlocked chunk's reachable and locked sections, for `chunksim sections
    list`/`chunksim sections <chunk-id>`. Section `0` is a chunk's implicit
    "whole thing" section - always reachable once the chunk is unlocked, and
    never itself tracked in `unlocked_sections`'s output - so it's always
    included in `reachable` here rather than left for callers to add back.
    """

    chunk_id: str
    name: str | None
    reachable: list[str]
    locked: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "name": self.name,
            "reachable": self.reachable,
            "locked": self.locked,
        }


def _sort_key(chunk_id: str) -> tuple[int, object]:
    return (0, int(chunk_id)) if chunk_id.isdigit() else (1, chunk_id)


def describe_sections(
    chunk_ids: Mapping[str, bool],
    reachable: Mapping[str, Mapping[str, bool]],
    chunk_info: ChunkInfo,
) -> list[ChunkSections]:
    """One `ChunkSections` per id in `chunk_ids` (already `expand_chunk_areas`d),
    sorted numerically where chunk ids allow.
    """
    entries = []
    for chunk_id in sorted(chunk_ids, key=_sort_key):
        computed = sorted(reachable.get(chunk_id, {}))
        defined = chunk_info.sections.get(chunk_id, {})
        all_sections = set(defined) - {"0"} if isinstance(defined, dict) else set()
        locked = sorted(all_sections - set(computed))

        entry = chunk_info.chunk(chunk_id)
        name = entry.get("Nickname")
        if not isinstance(name, str):
            name = entry.get("Name") if isinstance(entry.get("Name"), str) else None

        entries.append(
            ChunkSections(chunk_id=chunk_id, name=name, reachable=["0", *computed], locked=locked)
        )
    return entries
