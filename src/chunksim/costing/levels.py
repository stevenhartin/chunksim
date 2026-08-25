"""What level the player is at, and which monsters they can actually reach.

Lifted out of `estimate.py` because of who imports it: `dps_bridge`, the two
apps and `runs/batch.py` all want exactly these names and were pulling in the
whole 1,100-line estimator to get them. Nothing here prices anything.

**The map records no skill levels.** `maxSkill` is a declared cap and
`passiveSkill` is what is reachable untrained, so `infer_levels` reads a *floor*
out of the completed challenges instead - a ticked `Buy the Defence cape` proves
99 Defence. `goal_levels` then answers the other question: the level the chunk
*ends* at, which is what `slayer.py` judges a master by.

`reachable_providers` is the gate `dps_bridge` prices against - 188 of the
export's 872 monsters on the real map - and it is **imported** there rather than
reimplemented, so the gate cannot drift from the thing it gates.
"""

from __future__ import annotations

from dataclasses import dataclass

from typing import Any, NamedTuple
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.model.experience import MAX_SKILL_LEVEL, level_for_xp
from chunksim.derive.pipeline import Derived
from chunksim.derive.pipeline import MapState
from collections.abc import Mapping
from chunksim.derive.search import WorldIndex
from chunksim.model.summary import _mapping
from chunksim.derive.search import normalise


@dataclass(frozen=True)
class TaskGate:
    """The assignment a monster demands, **and where it demands it**.

    **The place is not decoration.** `Konar quo Maten` assigns by location and
    every one of his 93 task keys carries a ` - <place>` suffix, so a gate
    naming the bare `Hydras` matched none of them: on a map where he is the
    only master, every task-gated monster's drops went unpriced and any item
    with a second route was silently priced by the worse one.

    Carrying the place is what lets `slayer.MasterRate` join the two exactly
    rather than by prefix. Prefix alone would have been worse than the miss it
    fixes: 23 of Konar's task families span up to six locations, and summing
    their weights would shorten the wait for an assignment that only one of
    them satisfies - a boss reading *faster* than it is, which is this
    project's most productive bug shape.
    """

    task: str
    #: The `taskUnlocks` location that demanded it, as the export spells it -
    #: `Karuulm Slayer Dungeon`, `Slayer Tower#Basement`.
    place: str


def task_gated_monsters(
    chunk_info: ChunkInfo,
    world: WorldIndex,
    reachable_places: frozenset[str],
) -> dict[str, TaskGate]:
    """Monsters you must be *on a slayer task* to fight, and which task.

    Read out of `taskUnlocks['Monsters']`, whose entries are **per location**::

        "Grotesque Guardians": {"Grotesque Guardians' Lair":
                                    [{"Gargoyle task": "Nonskill"}]}
        "Aberrant spectre":    {"Stronghold Slayer Cave":
                                    [{"Aberrant spectre task": "Nonskill"}]}

    **Per location is the whole point, and reading it as per monster is
    wrong.** Aberrant spectres need a task in the Stronghold Slayer Cave and
    nowhere else - the Slayer Tower and three other chunks place them freely -
    so gating the monster outright made a 1/512 drop off them cost 1,707 hours
    instead of 8. A monster is gated here only when *every* reachable place
    that holds it demands a task; one open door is enough to walk through.
    Grotesque Guardians stay gated because their lair is the only place they
    exist.

    A `Nonskill` requirement named `<something> task` is the export's way of
    saying "only while assigned"; the other gates there are quests and are
    ordinary validity requirements `challenges.py` already enforces. The name
    maps back to a `codeItems.slayerTasks` key - `Gargoyle task` to the
    `Gargoyles` assignment - because that is where the weight lives.
    """
    assignments = _mapping(chunk_info.code_items, "slayerTasks")
    by_normalised = {normalise(name): name for name in assignments}
    placements = _mapping(world.locations, "Monster")

    gates: dict[str, TaskGate] = {}
    for monster, locations in _mapping(chunk_info.data, "taskUnlocks").get("Monsters", {}).items():
        if not isinstance(locations, dict):
            continue
        gate = _gating_task(locations, by_normalised)
        if gate is None:
            continue
        if _has_open_door(monster, locations, placements, reachable_places):
            continue
        gates[monster] = gate
    return gates


def _gating_task(
    locations: dict[str, Any], by_normalised: dict[str, str]
) -> TaskGate | None:
    """The slayer task a location's `<X> task` requirement names, and the
    location that named it."""
    for place, requirements in locations.items():
        for requirement in requirements if isinstance(requirements, list) else ():
            if not isinstance(requirement, dict):
                continue
            for name, category in requirement.items():
                if category != "Nonskill" or not name.endswith(" task"):
                    continue
                subject = normalise(name.removesuffix(" task"))
                for candidate in (subject, f"{subject}s", f"{subject}es"):
                    if candidate in by_normalised:
                        return TaskGate(task=by_normalised[candidate], place=str(place))
    return None


def _has_open_door(
    monster: str,
    gated: dict[str, Any],
    placements: Mapping[str, Any],
    reachable_places: frozenset[str],
) -> bool:
    """Is `monster` somewhere reachable that does *not* demand a task?"""
    gated_places = {normalise(place) for place in gated}
    for place in placements.get(monster) or ():
        chunk = str(place).split("#")[0].split("-")[0]
        if normalise(str(place)) in gated_places or normalise(chunk) in gated_places:
            continue
        if str(place) in reachable_places or chunk in reachable_places:
            return True
    return False


def goal_levels(state: MapState, derived: Derived, floor: dict[str, int]) -> dict[str, int]:
    """The levels this chunk will *end* at: its floor raised to its goals.

    **What a chunk is working towards is as much a fact as what it has
    done.** The active goal for a skill carries the level it needs, and
    finishing the chunk means reaching it - Slayer here is inferred at 45 and
    aiming at 92, so 92 is the level that describes most of the chunk.

    Used for what a slayer master will *offer*, because that list is the one
    that holds for the tail of the chunk, and the tail is where the time
    goes. Not used for the XP still to earn: that is measured from the floor
    up, which is the whole point of the climb.

    Preferred over `maxSkill`, which is a cap the player declared rather than
    work they are committed to - Slayer's cap says 99 where the outstanding
    task says 92, and 92 is the number with a reason behind it.
    """
    levels = dict(floor)
    for skill, classification in derived.task_classification.skills.items():
        goal = classification.active
        if goal is None:
            continue
        challenge = _mapping(state.chunk_info.challenges, str(skill)).get(goal)
        target = challenge.get("Level") if isinstance(challenge, dict) else None
        if isinstance(target, (int, float)) and not isinstance(target, bool):
            levels[str(skill)] = max(levels.get(str(skill), 1), int(target))
    return levels


def infer_levels(state: MapState) -> dict[str, int]:
    """What the player's levels must be *at least*, from what they have done.

    **A completed challenge is proof of its own level requirement.** The map
    records no skill levels, but it does record what has been ticked off, and
    `Buy the ~|Defence cape|~` is not something a player under 99 Defence has
    done. Taking the highest `Level` among each skill's completions turns the
    ledger into a floor: on the real map that is Defence 99, Attack 75,
    Strength 70 - none of which `passiveSkill` mentions at all.

    Better evidence than the alternatives, and the reason this exists.
    `maxSkill` is a *cap* the player declared, not a level they hold;
    `passiveSkill` is what a level is reachable without training, which on
    the real map names five skills. Both are taken into account - the highest
    of the three wins - because each is a floor and the best floor is the
    highest one.

    Still a floor, not a level: a player at 99 Attack who has ticked nothing
    above 75 reads as 75. `levels` in `heuristics/overrides.json` replaces it
    outright where that matters.
    """
    levels: dict[str, int] = {}

    def raise_to(skill: str, level: Any) -> None:
        if isinstance(level, (int, float)) and not isinstance(level, bool):
            levels[skill] = max(levels.get(skill, 1), int(level))

    for skill, level in state.passive_skill.items():
        raise_to(str(skill), level)

    for skill, completed in state.completed_challenges.items():
        challenges = _mapping(state.chunk_info.challenges, str(skill))
        if not isinstance(completed, Mapping):
            continue
        for name in completed:
            challenge = challenges.get(name)
            if isinstance(challenge, dict):
                raise_to(str(skill), challenge.get("Level"))

    return levels


#: What decided a skill's level, for a reader and for the interface.
FLOOR = "floor"
LINKED = "linked"
SET = "set"
#: A figure below the floor, which is refused rather than spent - see
#: `resolve_levels`.
BELOW_FLOOR = "below-floor"


class SkillLevel(NamedTuple):
    """One skill's level and where it came from."""

    level: int
    source: str
    #: The floor, carried so a caller can say what a refused figure fell under.
    floor: int
    #: The experience behind `level`, or `0` where the floor decided it.
    experience: int = 0


def resolve_levels(
    state: MapState,
    overrides: Mapping[str, int] | None = None,
    linked_experience: Mapping[str, int] | None = None,
    set_experience: Mapping[str, int] | None = None,
) -> dict[str, SkillLevel]:
    """Every skill's level, and which of the three layers decided it.

    **Three sources, most specific first**: experience set by hand for this
    map, then the experience of the account linked to it, then the floor -
    `infer_levels` raised by any hand-set *level* in `overrides.json`, which
    is what this project answered with before an account could be linked.

    **No layer may lower a skill**, which is the rule that makes the whole
    thing safe to bolt on. A floor is a proof: a ticked `Buy the ~|Defence
    cape|~` is 99 Defence whatever an account says, and a linked account
    reading lower is a different account, a reset, or a typo. So every layer
    is `max`ed against the floor rather than trusted, and a figure that
    *would* have lowered one is reported as `BELOW_FLOOR` rather than quietly
    raised - the interface paints those red, because silently agreeing with a
    number you refused is the worse failure.

    Experience rather than levels, because that is what the hiscores publish
    and what a curve change survives. `model/experience.level_for_xp` is the
    one conversion.
    """
    floor = infer_levels(state)
    for skill, level in (overrides or {}).items():
        floor[skill] = max(floor.get(skill, 1), int(level))

    found: dict[str, SkillLevel] = {
        skill: SkillLevel(level=level, source=FLOOR, floor=level)
        for skill, level in floor.items()
    }

    def apply(experience: Mapping[str, int], source: str) -> None:
        for skill, total in experience.items():
            under = floor.get(skill, 1)
            # **A skill stops at 99.** `level_for_xp` is the curve's inverse
            # and the curve runs to 126 because it also answers for Combat
            # level, so an account with 30m Strength reads 107 unless this
            # clamps - see `experience.MAX_SKILL_LEVEL`.
            level = min(level_for_xp(int(total)), MAX_SKILL_LEVEL)
            found[skill] = SkillLevel(
                level=max(level, under),
                source=BELOW_FLOOR if level < under else source,
                floor=under,
                experience=int(total),
            )

    apply(linked_experience or {}, LINKED)
    apply(set_experience or {}, SET)
    return found


def levels_from(resolved: Mapping[str, SkillLevel]) -> dict[str, int]:
    """Just the numbers, for every caller that wants what it always wanted."""
    return {skill: found.level for skill, found in resolved.items()}


def _levels(state: MapState, overrides: dict[str, int]) -> dict[str, int]:
    """The per-skill level to count from. See the module docstring's caveat."""
    levels = infer_levels(state)
    levels.update(overrides)
    return levels


def reachable_providers(derived: Derived) -> frozenset[str]:
    """Everything on this map that can *hand you an item*, not just kill you.

    Monsters, objects and NPCs of `SourceIndex` together, all past their
    `taskUnlocks` gates. Monsters alone is the tempting wrong answer and was
    the first one: a `skillItems` activity is only *usually* a monster, so a
    monsters-only gate refused `Larran's big chest` - an Object - and with it
    the 34 drops behind it.

    **This is `_Walk.available`, and it is also the set worth pricing.**
    Every `Heuristics.kills_per_hour` lookup in this module is gated on it -
    `_kill_hours` takes a provider from it, `_superior_hours` refuses a base
    that is not in it, `_required_kills` skips a monster that is not - so a
    kill rate for anything outside it can never be spent. `dps_bridge.enrich`
    imports this rather than keeping its own copy, because the two agreeing
    is what makes restricting the pricing safe rather than lossy, and
    `tests/test_dps_bridge.py` pins them together.
    """
    return (
        frozenset(derived.source_index.monsters)
        | frozenset(derived.source_index.objects)
        | frozenset(derived.source_index.npcs)
    )
