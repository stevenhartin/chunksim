"""Run the full sections -> sources -> challenges pipeline for a chunk set.

`MapState` bundles the per-map inputs that stay fixed across a single `chunksim`
invocation (the chunkinfo export, decoded rules/settings, manual overrides);
`derive` runs the pipeline for a given *set of unlocked chunk ids*, so
`unlock.py` and `simulate.py` can call it twice - once for the current
state, once for a candidate chunk added - without duplicating the
`unlocked_sections` -> `gather_chunks_info` -> `calc_challenges` -> `compute_bis` ->
`classify_tasks` wiring that `cli.py`'s `sections`/`sources`/`tasks` subcommands also share.

`derive` runs that chain in a **loop**, while newly-valid challenges keep
unlocking further named areas. This is where upstream's circularity lives: an
`UnlocksArea` challenge only becomes valid once its requirements are met, and
the area it unlocks adds *new sources* that can validate more challenges
(upstream re-runs `gatherChunksInfo` mid-`calcChallenges` for the same
reason). Keeping the loop here is what lets `sections.py`, `sources.py` and
`challenges.py` each stay one-directional and separately testable. The same
loop feeds each pass's challenge validity back into `gather_chunks_info` as
`valid_tasks`, which `sources.py`'s `taskUnlocks` gating needs.

`load_map_state` decodes a raw cached-map payload into a `MapState` once,
including `passive_skill` for `bis.py`'s skill-requirement gate and
`completed_challenges`/`manual_tasks`/`backlog`/`active_tasks` for
`active_tasks.py` and `bis.py`'s completed split.

`completed_challenges` **merges `checkedChallenges` into
`completedChallenges`**. Upstream keeps those apart only as a commit step:
ticking a task writes `checkedChallenges`, and rolling the next chunk
migrates the lot and clears it (`completeChallenges`, index.js:12718).
Anything obtained during the *current* chunk therefore sits only in
`checkedChallenges`, and ignoring it reported items you already hold as still
to get. `MapState.checked_challenges` keeps that half addressable un-merged
as well, feeding `compute_bis`'s `checked_bis` - but it is a **display view,
not a second source of truth**: every completion *test* reads the merged
`completed_challenges`, of which it is a strict subset.

**Slayer can be blocked, and that is a cap rather than a special case.**
`chunkinfo.slayerLocked` records a player stuck on an assignment they cannot
complete and cannot afford to skip. Upstream reads it at eleven sites and ten
of them are the `maxSkill` test written a second time, so
`slayer_capped_max_skill` folds it into `max_skill['Slayer']` once and every
module below inherits the gate unchanged - no new argument, no new branch in
`sources.py`, `challenges.py`, `bis.py` or `sections.py`, all four of which
already cap on that mapping. The eleventh site is the escape: reach a monster
that satisfies the blocked task and the lock lifts entirely
(`slayer_unblocked`). Neither cached map sets the branch, so **this changes no
number today and has no oracle** - it is ported because the alternative is a
map that derives Slayer as though nothing were wrong.

Those fields need the optional `tasks_map` argument (the reverse map from
`firebase.reverse_tasks_map`) to resolve `t_N` ids. Without one, every
`t_N`-keyed entry is *dropped* rather than kept raw, so they decode empty -
except `BiS` and `manualTasks`, which never need it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from chunksim.derive.active_tasks import TaskClassification, classify_tasks
from chunksim.derive.bis import BisResult, compute_bis
from chunksim.derive import boosts
from chunksim.derive.challenges import (
    ChallengeResult,
    _check_primary_method,
    _ItemPlan,
    calc_challenges,
)
from chunksim.derive.injected import (
    SynthesisInputs,
    forced_valid_from,
    injected_challenges,
    synthesised_challenges,
)
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.derive.other_tasks import OtherTasks, classify_other_tasks
from chunksim.model.firebase import decode_challenge_keyed, decode_payload
from chunksim.derive.sections import expand_chunk_areas, unlockable_areas, unlocked_sections
from chunksim.derive.sources import (
    SourceIndex,
    gather_chunks_info,
    slayer_gate_can_bite,
    slayer_output_tasks,
    task_unlock_pairs,
)
from chunksim.model.summary import _mapping


@dataclass(frozen=True)
class SlayerLock:
    """`chunkinfo.slayerLocked`: the player is sitting on a Slayer assignment
    they cannot complete and cannot afford to skip, so Slayer stops at
    `level` until the block clears.

    Upstream stores `{'level': <string>, 'monster': <task name>}` - the level
    comes off a text input, so it is a **string** in the payload and
    `worker.js:3446` `parseInt`s it. `monster` is a key of
    `codeItems.slayerTasks` (`'Aberrant spectres'`), which is the *task*
    name rather than any one monster's.
    """

    level: int
    monster: str


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
    #: Whether a section whose only recorded connection is the export's
    #: `"???"` placeholder opens with its chunk - see
    #: `sections._unresolved_only`. On by default because off makes 33 real
    #: places, the Pandemonium Shipyard among them, unreachable on every
    #: possible map. Not read from any payload key: it is this project's
    #: workaround rather than upstream state, and the per-section control a
    #: player actually reaches for is `manualSections`.
    unresolved_sections_open: bool = True
    #: `chunkinfo.slayerLocked`, or `None` when Slayer is not blocked. Read
    #: through `slayer_capped_max_skill` rather than directly: every gate
    #: upstream applies it at is a gate this project already routes through
    #: `max_skill`. See the module docstring.
    slayer_locked: SlayerLock | None = None


@dataclass(frozen=True)
class Derived:
    """One pipeline run's full output for a given unlocked-chunk-id set."""

    reachable_sections: dict[str, dict[str, bool]]
    #: The unlocked chunk ids **plus every named area they reach**, as the
    #: loop below finally settled it. Not the same as
    #: `sections.expand_chunk_areas(unlocked)`: that is only the first pass,
    #: and areas keep opening as challenges become valid - 106 entries
    #: against 166 on the real map, the 60 including `Wilderness Slayer
    #: Cave`. Anything evaluating a `Chunks` requirement outside this module
    #: wants *this*, or it will judge half the world locked.
    expanded_chunks: dict[str, bool]
    source_index: SourceIndex
    challenges: ChallengeResult
    bis: BisResult
    task_classification: TaskClassification
    other_tasks: OtherTasks
    #: The challenges upstream builds at runtime rather than reading from the
    #: export, as `{category: {name: definition}}` - see `derive/injected.py`.
    #: They are already in `challenges.valid` and in the `ChunkInfo` this run
    #: used, but a caller holding only a `MapState` has the *un*-overlaid
    #: export and would look one of these names up and find nothing. Such a
    #: caller wants `state.chunk_info.with_challenges(derived.injected)`.
    #: Almost always empty, and small when it is not, so it costs the
    #: derivation cache nothing to carry.
    injected: dict[str, dict[str, Any]] = field(default_factory=dict)


class ConvergenceError(RuntimeError):
    """`derive`'s area-unlock loop did not reach a fixed point."""


#: Upper bound on `derive`'s convergence loop (area unlocks + `taskUnlocks`
#: source gating).
#:
#: **Measured, not guessed.** The real map needs *eight* passes: seven that
#: each unlock further named areas (46, then 9, 2, 1, 1, 1, 0) and an eighth
#: that confirms nothing moved. This was 8 when it was believed the chains were
#: "a couple of links deep", i.e. the loop was silently stopping on the last
#: allowed pass and a map one link deeper would have returned a **truncated
#: derivation** - fewer reachable areas, fewer sources, fewer valid tasks, no
#: warning. Hitting the cap now raises instead: a wrong answer that looks right
#: is the worst outcome for this project, since every other module trusts
#: `Derived`.
_MAX_AREA_PASSES = 32



def slayer_unblocked(state: MapState, unlocked: Mapping[str, bool]) -> bool:
    """Whether the blocked assignment can be handed in after all - port of
    the escape at worker.js:3824.

    A lock names a *task* (`'Aberrant spectres'`); `codeItems.slayerTasks`
    expands it to the monsters that satisfy it (`Aberrant spectre`,
    `Deviant spectre`). Reach any one of them and the assignment can be
    completed, so the block lifts.

    **Approximated by the raw contents of the unlocked chunks** where
    upstream reads its live `baseChunkData['monsters']`, which the derivation
    loop goes on refining (worker.js:665-668 deletes a monster whose own
    unlock task turned out invalid, 718-720 adds one a task unlocked). Doing
    this properly would make the escape a term in the very fixed point it
    gates - Slayer validity deciding monster availability deciding Slayer
    validity - for a branch upstream's own UI clears the moment it fires
    (`checkSlayerLocked`, index.js:9787, nulls `slayerLocked` and saves). So
    the raw set is read once, before the loop, and the one case it answers
    differently is a monster reachable *only* through a challenge this lock
    invalidates.
    """
    lock = state.slayer_locked
    if lock is None:
        return False
    satisfying = state.chunk_info.slayer_tasks.get(lock.monster)
    if not isinstance(satisfying, dict):
        return False
    slayer_monsters = state.chunk_info.slayer_monsters
    for chunk_id in unlocked:
        present = _mapping(state.chunk_info.chunk(chunk_id), "Monster")
        for monster in present:
            if monster not in satisfying:
                continue
            # index.js:9790 - a monster you cannot be assigned at this level
            # does not lift the block.
            required = slayer_monsters.get(monster)
            if isinstance(required, (int, float)) and required > lock.level:
                continue
            return True
    return False


def slayer_capped_max_skill(state: MapState, unlocked: Mapping[str, bool]) -> Mapping[str, int]:
    """`state.max_skill` with `slayerLocked` folded in as a second cap on
    Slayer.

    Upstream reads `slayerLocked` at eleven sites and ten of them are
    literally the `maxSkill` test written twice: `(!slayerLocked || value <=
    slayerLocked['level']) && (!maxSkill || value <= maxSkill['Slayer'])`
    (worker.js:987, 1290, 1893, 2093, 2777, 3272, 5331, ...). Two caps ANDed
    are one cap at their minimum, so folding here reproduces all ten at the
    sites this project already routes `max_skill` through, and adds no gate
    upstream lacks - every `maxSkill` gate in `worker.js` bar three carries
    the `slayerLocked` clause beside it.

    The eleventh site is worker.js:3822, which invalidates a Slayer challenge
    whose own `Level` exceeds the lock. That is `_level_gates_met`'s
    `maxSkill` arm (worker.js:3712) applied to Slayer, so the fold reproduces
    it too - **except** for the escape it carries, which is why an unblocked
    lock is dropped here rather than capped.
    """
    lock = state.slayer_locked
    if lock is None or slayer_unblocked(state, unlocked):
        return state.max_skill
    existing = state.max_skill.get("Slayer")
    capped = lock.level if not isinstance(existing, (int, float)) else min(existing, lock.level)
    return {**state.max_skill, "Slayer": capped}



def slayer_locked_equipment(state: MapState, unlocked: Mapping[str, bool]) -> frozenset[str]:
    """The slayer gear a `slayerLocked` level puts out of reach - port of
    worker.js:3271-3278.

    `chunkinfo.slayerEquipment` is 17 items with the Slayer level each needs
    to *wear*, and the ones above the lock are moved to a starred key that
    satisfies every requirement except a combat skill's. `challenges.py`
    applies that; this decides the membership.

    **It is not redundant with the cap, which is why it is a separate port.**
    Twelve of the seventeen also appear in `chunkinfo.equipment` carrying a
    `requirements.Slayer`, so `bis.py` already refuses them through
    `slayer_capped_max_skill`. The other five do not: `Facemask`, `Earmuffs`,
    `Unlit bug lantern` and `Nose peg` are absent from `equipment` entirely
    and `Spiny helmet` lists only Defence, so **`slayerEquipment` is the only
    place their Slayer gate is written down**. They are exactly the
    protective pieces a slayer monster demands, and without this a locked map
    would happily fight dust devils bare-faced.
    """
    lock = state.slayer_locked
    if lock is None or slayer_unblocked(state, unlocked):
        return frozenset()
    return frozenset(
        item
        for item, required in _mapping(state.chunk_info.data, "slayerEquipment").items()
        if isinstance(required, (int, float)) and required > lock.level
    )




def _carried_areas(
    carried: Mapping[str, bool] | None, state: MapState
) -> dict[str, bool]:
    """The subset of `carried` this loop could have produced itself.

    **Filtered rather than trusted**, because refusing rather than
    approximating applies to a parameter as much as to a payload. The
    predicate is `unlockable_areas`' own: a key naming a `Nonskill` challenge
    with `UnlocksArea`. So a stale or wrong carry cannot introduce a *chunk
    id* - which is the dangerous failure, since that would silently unlock a
    chunk the run never rolled - and cannot name anything that is not an area.

    The survivors go back through `expand_chunk_areas` rather than being
    merged after it, so a `manualAreas` entry set to `False` still wins. Merged
    afterwards, a carry would resurrect an area the player switched off.
    """
    nonskill = state.chunk_info.challenges.get("Nonskill") or {}
    return {
        area: True
        for area, held in (carried or {}).items()
        if held
        and isinstance(nonskill.get(area), dict)
        and nonskill[area].get("UnlocksArea") is True
    }


def _gates_agree(
    pairs: frozenset[tuple[str, str]],
    valid: Mapping[str, Mapping[str, Any]],
    previous: Mapping[str, Mapping[str, Any]],
) -> bool:
    """Do these two validity maps agree everywhere `taskUnlocks` can look?

    Weaker than `valid == previous` and sufficient for the loop to stop - see
    `derive`. Subsumes equality: equal maps agree on every projection.
    """
    return all(
        (task in valid.get(skill, ())) == (task in previous.get(skill, ()))
        for skill, task in pairs
    )


def _slayer_floor(state: MapState) -> int | None:
    """`passiveSkill['Slayer']` as an int, or `None` where the map records
    none. Upstream's `Kill X` filter tests presence before comparing, so an
    absent floor must not read as zero."""
    floor = state.passive_skill.get("Slayer")
    if isinstance(floor, (int, float)) and not isinstance(floor, bool):
        return int(floor)
    return None


def _merge_by_category(
    first: Mapping[str, Mapping[str, Any]], second: Mapping[str, Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Two `{category: {name: definition}}` tables as one, `second` winning a
    clash. Neither producer can name the same challenge as the other today -
    the capes are two literals - but merging by category rather than by
    top-level key is what stops one silently replacing the other's whole
    branch."""
    return {
        category: {**first.get(category, {}), **second.get(category, {})}
        for category in first.keys() | second.keys()
    }


def derive(
    state: MapState,
    unlocked: Mapping[str, bool],
    *,
    carry_areas: Mapping[str, bool] | None = None,
) -> Derived:
    """Run `unlocked_sections` -> `gather_chunks_info` -> `calc_challenges`,
    looping while newly-valid challenges unlock further named areas.

    That loop is what makes this function, rather than any single module,
    the place upstream's circularity lives: an `UnlocksArea` challenge only
    becomes valid once its requirements are met, and unlocking the area it
    names adds that area's monsters/items as *new sources*, which can in turn
    validate more challenges (upstream does the same thing by re-running
    `gatherChunksInfo` mid-`calcChallenges`, worker.js:2153). Keeping the
    loop here lets `sections.py`/`sources.py`/`challenges.py` each stay
    one-directional and separately testable. Raises `ConvergenceError` rather
    than returning a truncated derivation if it fails to settle - see
    `_MAX_AREA_PASSES` for why that is not a theoretical concern.

    The same loop feeds each pass's validity back into `gather_chunks_info`
    as `valid_tasks`, which is how `taskUnlocks` gating works: a shop or
    monster present in a chunk can still be locked behind completing a
    challenge there (upstream's `shouldDelete` pass deletes such entries
    from an already-built index instead; iterating to a fixed point reaches
    the same answer without a mutate-after-the-fact step). The first pass
    runs ungated, so a gate can only ever *remove* a source that its own
    unlock task hadn't yet justified.

    **The loop stops on what the next pass could actually read, not on
    equality**, which is worth one whole pass in eight. `valid == valid_tasks`
    is sufficient but far stronger than needed: `calc_challenges` does not
    take `valid_tasks` at all, so last pass's validity reaches this one only
    through the gates below. So with the areas settled, the four steps chain:
    no new areas means `expanded` is unchanged, so `unlocked_sections` returns
    the same `reachable`; agreeing on everything the gates read means
    `gather_chunks_info` is handed identical inputs and builds an identical
    index; `calc_challenges` is a deterministic function of those; so the next
    pass would reproduce this one exactly, including the strict condition.
    Measured on the real map, the loop leaves at pass 7 where it used to run a
    pass 8 that was a byte-identical repeat - **0.10s of 0.87s.**

    **Three channels, not one, and only two are membership tests.**
    `taskUnlocks` asks whether a `(skill, task)` pair is in `valid`
    (`sources.task_unlock_pairs`), and the `skillItems.Slayer` gate asks the
    same of each slayer monster's own `Slay a ...` challenge
    (`sources.slayer_output_tasks`) - both membership, never a value, so a set
    of pairs covers them. The gate's third input is not: `slayer_trainable` is
    `checkPrimaryMethod('Slayer', ...)` over the *whole* validity map, so it is
    compared across passes directly. It is asked only where
    `sources.slayer_gate_can_bite` says the export could consult it, which is
    what keeps a map with no slayer monsters converging in one pass. In steady
    state it costs nothing: the flag settles alongside everything else, so by
    the pass that would exit, the previous pass already computed the same
    value.

    **This says nothing about warm-starting `valid` itself**, which
    `challenges.py` refuses and still should: this argument turns on the
    *index* being identical, and needs no monotonicity anywhere.

    **`carry_areas` is measured rather than proved, and the mechanism is
    worth stating exactly.** A simulation rolls one chunk at a time and every
    roll rediscovers the same ~70 named areas from nothing; handing back the
    areas the previous roll settled on takes this loop from eight passes to
    four, 0.87s to 0.47s.

    The risk is *not* that the loop converges somewhere odd. It is that
    **`expanded` only ever grows, so a carried area is never re-validated at
    all** - the loop adds areas and never removes one, so whatever the carry
    puts in stays in, unchecked. Demonstrated: handing the second cached map a
    carry naming `Kalphite Queen's Lair`, which that map cannot unlock, keeps it unlocked
    and adds 26 valid tasks and 15 items. `_carried_areas` does not catch that
    one - the lair really is a `Nonskill`/`UnlocksArea` challenge - so the
    filter is a guard against a *malformed* carry, not a stale one.

    For a stale carry to arise, a roll would have to **lose** an area, which
    needs `valid` to move backwards somewhere an area unlock reads. On this
    export it cannot: no `UnlocksArea` challenge carries a `BackupParent`
    (all 17 backups are Hunter, all 315 area unlocks are Nonskill); none of
    them requires a task a backup could supply, through a `tasksPlus` family
    or otherwise; and none requires one of the ten items only a dropped backup
    outputs, through an `itemsPlus` family or otherwise. Measured to match:
    across 180 rolls over six seeds and both cached maps, an area is never
    lost.

    That is an argument about *this* export, not a proof about any export -
    which is why every carried run still checks itself. The state a run
    finishes on is re-derived cold and compared, and a mismatch raises rather
    than being saved. Because an area cannot be lost and a spurious one cannot
    heal, that single check covers every state the run passed through, so a
    run that checks out may keep all of them - `simulate.simulate_rolls` sets
    out the argument and `derived_cache.RollCache` holds the states until it
    lands. See also `tests/test_simulate.py`'s carry oracle, which replays a
    full simulation on both maps and compares every state.
    """
    # Upstream's runtime-built challenges, and the export overlaid with
    # their definitions - see `derive/injected.py`. Both capes depend only on
    # the chunk list and the rules, so they can be settled before the loop;
    # everything below reads the overlaid export rather than `state`'s, the
    # way upstream reads the copy it mutated.
    injected_definitions = injected_challenges(state.chunk_info, unlocked, state.rules)
    # The bulk-built challenges are a function of the item index this loop is
    # still computing, so they start empty and are refolded at the end of each
    # pass - see below, and `derive/injected.py` for why that terminates.
    synthesised: dict[str, dict[str, Any]] = {}
    chunk_info = state.chunk_info.with_challenges(injected_definitions)
    max_skill = slayer_capped_max_skill(state, unlocked)
    locked_equipment = slayer_locked_equipment(state, unlocked)
    expanded = expand_chunk_areas(
        {**unlocked, **_carried_areas(carry_areas, state)} if carry_areas else unlocked,
        manual_areas=state.manual_areas,
    )
    reachable: dict[str, dict[str, bool]] = {}
    index: SourceIndex | None = None
    challenges: ChallengeResult | None = None
    valid_tasks: dict[str, dict[str, int | str | bool]] = {}
    # `checkPrimaryMethod('Slayer', ...)` from the previous pass, feeding the
    # `skillItems.Slayer` gate in `sources._SlayerGate`. **Starts permissive
    # for the same reason `valid_tasks` starts empty**: the first pass has no
    # previous answer, and running it ungated is what keeps the gate
    # subtractive - it can remove a source a later pass no longer justifies,
    # never invent one.
    slayer_trainable = True
    converged = False
    # Compiled `Items` plans, shared by every pass. They depend on the export,
    # the rules, the skill and `locked_equipment` - all fixed above this loop -
    # so recompiling them per pass was 50,090 calls a derivation for 6,300
    # distinct answers. A local table, passed in; see `calc_challenges`.
    item_plans: dict[tuple[str, str], _ItemPlan | None] = {}
    # The only pairs whose validity the next pass could read back; see the
    # exit test below and `sources.task_unlock_pairs`.
    gate_pairs = task_unlock_pairs(chunk_info)
    # Whether the `skillItems.Slayer` gate's trainability flag is readable at
    # all here; if it is not, it is not a reason to run another pass.
    slayer_gate_reads_trainable = slayer_gate_can_bite(chunk_info)

    for _ in range(_MAX_AREA_PASSES):
        reachable = unlocked_sections(
            expanded,
            chunk_info,
            manual_sections=state.manual_sections,
            opt_out_sections=state.settings.get("optOutSections") is True,
            opt_out_sections_water=state.settings.get("optOutSectionsWater") is True,
            unresolved_sections_open=state.unresolved_sections_open,
        )
        index = gather_chunks_info(
            expanded,
            reachable,
            chunk_info,
            rules=state.rules,
            backlogged_sources=state.backlogged_sources,
            manual_monsters=state.manual_monsters,
            manual_equipment=state.manual_equipment,
            max_skill=max_skill,
            valid_tasks=valid_tasks,
            passive_skill=state.passive_skill,
            slayer_trainable=slayer_trainable,
        )
        challenges = calc_challenges(
            expanded,
            reachable,
            index,
            chunk_info,
            rules=state.rules,
            max_skill=max_skill,
            backlogged_sources=state.backlogged_sources,
            passive_skill=state.passive_skill,
            backlog=state.backlog,
            manual_tasks=state.manual_tasks,
            completed_challenges=state.completed_challenges,
            construction_locked=state.construction_locked,
            locked_equipment=locked_equipment,
            forced_valid=forced_valid_from(synthesised),
            item_plans=item_plans,
            slayer_locked_level=state.slayer_locked.level if state.slayer_locked else None,
        )
        new_areas = unlockable_areas(
            challenges.valid,
            expanded,
            reachable,
            chunk_info,
            manual_areas=state.manual_areas,
            max_skill=max_skill,
            passive_skill=state.passive_skill,
        )
        # Upstream asks `checkPrimaryMethod('Slayer', …)` inside the `Kill X`
        # filter, once per monster, against this pass's own answer; asking it
        # here is the same question hoisted. **It has a second reader now** -
        # the next pass's `skillItems.Slayer` gate (worker.js:987), which is
        # why the exit test below compares it across passes.
        trainable_now = _check_primary_method(
            "Slayer",
            challenges.valid,
            index,
            chunk_info,
            passive_skill=state.passive_skill,
            backlog=state.backlog,
            manual_tasks=state.manual_tasks,
            rules=state.rules,
            items=challenges.available_items,
            objects=challenges.available_objects,
        )
        rebuilt = synthesised_challenges(
            chunk_info,
            SynthesisInputs(
                items=challenges.available_items,
                monsters=index.monsters,
                drop_rates=index.drop_rates,
                drop_quantities=index.drop_quantities,
                completed_extra=state.completed_challenges.get("Extra") or {},
                backlogged_sources=state.backlogged_sources or {},
                backlog=state.backlog.get("Extra") or {},
                slayer_trainable=trainable_now,
                slayer_has_tasks=bool(challenges.valid.get("Slayer")),
                slayer_cap=state.slayer_locked.level if state.slayer_locked else None,
                passive_slayer=_slayer_floor(state),
                best_slayer_boost=boosts.best_boost(
                    "Slayer",
                    "",
                    {},
                    1.0,
                    rules=state.rules,
                    chunk_info=chunk_info,
                    items=challenges.available_items,
                    source_index=index,
                )[0],
            ),
            state.rules,
        )
        settled = rebuilt == synthesised
        # The `skillItems.Slayer` gate reads the previous pass through two
        # more channels than `taskUnlocks` does, and both join the exit test
        # or it would fire a pass early on a map where the gate is still
        # moving: the trainability flag itself, and membership of each
        # monster's own `Slay a ...` challenge.
        slayer_pairs = frozenset(
            ("Slayer", task) for task in slayer_output_tasks(chunk_info).values()
        )
        if (
            not new_areas
            and settled
            and (not slayer_gate_reads_trainable or trainable_now == slayer_trainable)
            and _gates_agree(gate_pairs | slayer_pairs, challenges.valid, valid_tasks)
        ):
            converged = True
            break
        if not settled:
            # A changed set means the next pass has challenges this one never
            # saw, so nothing about this pass's answer can be trusted as final
            # - including the two tests above, which is why this is folded in
            # before them rather than after.
            synthesised = rebuilt
            chunk_info = state.chunk_info.with_challenges(
                _merge_by_category(injected_definitions, rebuilt)
            )
        valid_tasks = challenges.valid
        slayer_trainable = trainable_now
        expanded = {**expanded, **new_areas}

    assert index is not None and challenges is not None  # loop always runs at least once
    if not converged:
        raise ConvergenceError(
            f"the area-unlock loop did not settle in {_MAX_AREA_PASSES} passes "
            f"({len(expanded)} areas, {sum(len(v) for v in challenges.valid.values())} valid tasks "
            "at the cut-off); the result would be truncated, so it is not returned"
        )
    bis = compute_bis(
        chunk_info,
        # Not `index.items`: BiS candidates must include items that only
        # exist as a valid challenge's `Output` (e.g. `Granite ring (i)`,
        # obtainable solely by imbuing one) - see `ChallengeResult`.
        challenges.available_items,
        challenges.valid,
        rules=state.rules,
        max_skill=max_skill,
        passive_skill=state.passive_skill,
        completed_bis=state.completed_challenges.get("BiS", {}),
        checked_bis=state.checked_challenges.get("BiS", {}),
    )
    task_classification = classify_tasks(
        challenges.valid,
        chunk_info,
        completed_challenges=state.completed_challenges,
        manual_tasks=state.manual_tasks,
        backlog=state.backlog,
        passive_skill=state.passive_skill,
        source_index=index,
        rules=state.rules,
        available_items=challenges.available_items,
    )
    other = classify_other_tasks(
        challenges.valid,
        chunk_info,
        completed_challenges=state.completed_challenges,
        checked_challenges=state.checked_challenges,
        backlog=state.backlog,
    )
    return Derived(
        reachable_sections=reachable,
        expanded_chunks=dict(expanded),
        source_index=index,
        challenges=challenges,
        bis=bis,
        task_classification=task_classification,
        other_tasks=other,
        injected=_merge_by_category(injected_definitions, synthesised),
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



def _slayer_lock(chunkinfo_branch: Mapping[str, Any]) -> SlayerLock | None:
    """Decode `chunkinfo.slayerLocked`, or `None` when Slayer is not blocked.

    The level arrives as a string off a text input (index.js:8484), so it is
    parsed here rather than at every read. The monster is **not** touched: the
    dropdown's values are raw `codeItems.slayerTasks` keys (index.js:9590), so
    the stored string already is the lookup key - plus the sentinel
    `'Manually Locked'`, which is in no table and so never lifts, which is
    what "locked with no particular task in mind" should do. A level that will
    not parse is treated as no lock: upstream's own input handler refuses to store one
    (index.js:8481), so a payload holding one is corrupt rather than
    meaningful, and guessing a cap would silently invalidate Slayer.
    """
    branch = chunkinfo_branch.get("slayerLocked")
    if not isinstance(branch, dict):
        return None
    monster = decode_payload(branch).get("monster")
    if not isinstance(monster, str) or not monster:
        return None
    try:
        level = int(branch.get("level"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return SlayerLock(level=level, monster=monster)


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
        slayer_locked=_slayer_lock(chunkinfo_branch),
    )
    return state, unlocked
