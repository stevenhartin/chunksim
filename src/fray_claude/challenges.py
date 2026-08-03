"""Which challenges (tasks) are valid, given the unlocked chunks' sources.

Port of the core of `calcChallenges`/`calcChallengesWork` (worker.js): a
fixed point over 28 of the 29 challenge categories (all but `BiS`, ported
separately in `bis.py`, since it's its own ~3,000-line subsystem). Each
challenge's `Chunks`/`Items`/`Objects`/`Monsters`/`NPCs`/`Skills`/`Tasks`
requirements are checked against the source index (`sources.py`) and the
running set of already-valid challenges; a valid challenge with an `Output`
feeds back as a new item source, so another pass may unlock further
challenges - repeating until nothing changes.

Scope: BASIC. `calcChallengesWork` is ~1,500 extremely dense lines with deep
special-casing (item-family `[+]` matching combined with a `*` secondary/
primary reclassification, tool-level gating, an entire "Multi Step
Processing" rule chain, elemental-staff rune substitution, dynamic Max
Cape/Quest Point Cape challenge injection, Slayer-lock and Mahogany Homes
gates, and a "Highest Level" grouping pass). Porting all of it is out of
scope for this increment; what's implemented, and what isn't, below.

Implemented:
- `Chunks`/`Objects`/`Monsters`/`NPCs`/`Mix` requirements: full presence
  checking, including `[+]` family matching (`objectsPlus`-style groups,
  ported via `chunkinfo.json`'s `codeItems`) and `[+]xN` "at least N of"
  counting for `Chunks`. These have no secondary/primary reclassification
  nuance upstream, so presence checking is faithful here, not a
  simplification.
- `Items` requirements: basic presence only (`item in source_index.items`,
  with `AllowedSources`/`NonShop` filtering). A requirement item containing
  `[+]` (a family) or `*` (the secondary marker) - the overwhelming majority
  of `Items` entries in practice - is not evaluable, since those carry the
  reclassification logic this module does not implement. Rather than abort
  the whole computation, `calc_challenges` catches this *per challenge*: an
  unsupported challenge is simply never valid, and its `skill/name` is
  collected in `ChallengeResult.unsupported` so the gap stays visible
  instead of silently reading as "checked and invalid".
- `Skills` requirements (a challenge needing another skill category to
  already have a valid entry): checked via `_has_any_valid`, a simplified
  stand-in for upstream's `checkPrimaryMethod` - "the skill has *a* valid
  entry" rather than one meeting upstream's primary/secondary nuance.
- `Tasks` requirements (a challenge needing a specific *other* challenge
  already valid): checked exactly.
- `MaxSkill`/`Not F2P`/`Not Skiller` gates, and the general category-rule
  gate (a `Category` naming a rule that's off invalidates the challenge,
  unless the category is in `maybePrimary` or is the `Secondary Primary`
  special case) plus the `InsidePOH Primary` category's hard block.

Not implemented - each raises `NotImplementedError` naming the mechanic,
except where noted as a silent, documented approximation instead:
- `QuestPointsNeeded`/`CombatPointsNeeded`/`KudosNeeded`/`TotalLevelNeeded`/
  `CombatLevelNeeded` gates: correctly computing those aggregates needs
  state (quest points earned, kudos, etc.) this module does not derive.
  Rare in the export (single digits to low tens of challenges).
- **Silent approximation, not a raise**: `processingSkill` categories
  (Runecraft, Magic, Herblore, Cooking, Firemaking, Fletching, Smithing,
  Crafting, Construction) get the same basic `Items` check as everything
  else, not upstream's "Highest Level" grouping/multi-step-chain pass - so
  several level tiers of the same task may show valid simultaneously where
  upstream, with the `Highest Level` rule *off*, would surface only the
  highest. (With that rule *on* - true of the map this was built against -
  upstream itself marks every tier valid, so this happens to match.) The
  `Multi Step Processing` rule's chain-of-crafted-items requirement is not
  checked at all, which can over-include processing-skill tasks when that
  rule is on.
- Dynamic Max Cape / Quest Point Cape challenge injection, Slayer-lock,
  Mahogany Homes, Collection Log Clues thresholds: not implemented. Shortcut
  Task / Combat and Teleport Spells / Cleaning Herbs only ever set
  `NeverShow` upstream, which is a display-only panel filter - out of scope
  per this project's attribution rule (see the stage-3 plan), so correctly
  not needed here regardless.
- Manual per-task overrides (`manualTasks`/`userTasks`) are not applied: a
  simulated roll has no such history to replay, so this module derives
  validity purely from chunk/rule state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fray_claude.chunkinfo import ChunkInfo
from fray_claude.sources import SourceIndex
from fray_claude.summary import _mapping

_MAYBE_PRIMARY = frozenset({"Normal Farming", "Sulphurous Fertiliser", "Shortcut", "InsidePOH Primary"})

_PROCESSING_SKILLS = frozenset(
    {"Runecraft", "Magic", "Herblore", "Cooking", "Firemaking", "Fletching", "Smithing", "Crafting", "Construction"}
)

_LEVEL_GATES_NOT_SUPPORTED = (
    "QuestPointsNeeded",
    "CombatPointsNeeded",
    "KudosNeeded",
    "TotalLevelNeeded",
    "CombatLevelNeeded",
)


@dataclass(frozen=True)
class ChallengeResult:
    """`valid[skill][name]` mirrors upstream's `globalValids` value shape:
    the challenge's `Level`, or its `Label`, or bare `True` if neither
    exists - `True` always for `Quest`/`Diary`, matching upstream exactly.

    `unsupported` lists every `skill/name` challenge that could not be
    evaluated at all (it uses a mechanic this module doesn't implement, e.g.
    an item family or the `*` secondary marker) - such a challenge is never
    valid here, which is a real gap, not a probably-harmless one: report
    `unsupported` alongside `valid` rather than silently treating an absence
    from `valid` as "checked and invalid".
    """

    valid: dict[str, dict[str, int | str | bool]]
    unsupported: frozenset[str]

    def as_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "unsupported": sorted(self.unsupported)}


def contains_sections(chunk_str: str) -> bool:
    """Port of `containsSections`: does `chunk_str` look like `NUM-SECTION`
    (a plain number, or a plain number, or `W` followed by one)?
    """
    base, sep, section = chunk_str.partition("-")
    if not sep or not _looks_numeric(base):
        return False
    if _looks_numeric(section):
        return True
    return section.startswith("W") and _looks_numeric(section[1:])


def _looks_numeric(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def only_shop(sources: Mapping[str, str]) -> bool:
    """Port of `onlyShop`: are every one of `sources`'s tags `'shop'`?"""
    return all(tag == "shop" for tag in sources.values())


def has_allowed_source(sources: Mapping[str, str], allowed_sources: Any) -> bool:
    """Port of `hasAllowedSource`: no restriction, or at least one of
    `sources`'s *keys* (source names) is in `allowed_sources`.
    """
    if not isinstance(allowed_sources, list) or not allowed_sources:
        return True
    return any(source in allowed_sources for source in sources)


def _chunk_reachable(
    chunk_ref: str, chunk_ids: Mapping[str, bool], reachable_sections: Mapping[str, Mapping[str, bool]]
) -> bool:
    if not contains_sections(chunk_ref):
        return chunk_ref in chunk_ids
    base, _, section = chunk_ref.partition("-")
    return base in chunk_ids and bool(reachable_sections.get(base, {}).get(section))


def _plus_family(chunk_info: ChunkInfo, key: str, name: str) -> list[str] | None:
    family = _mapping(chunk_info.code_items, key).get(name)
    return family if isinstance(family, list) else None


def _chunks_requirement_met(
    challenge: Mapping[str, Any],
    chunk_ids: Mapping[str, bool],
    reachable_sections: Mapping[str, Mapping[str, bool]],
    chunk_info: ChunkInfo,
) -> bool:
    chunk_refs = challenge.get("Chunks")
    if not isinstance(chunk_refs, list):
        return True
    for chunk_ref in chunk_refs:
        if not isinstance(chunk_ref, str):
            continue
        if "[+]" in chunk_ref:
            base_name, marker, count_str = chunk_ref.partition("[+]x")
            family_name = f"{base_name}[+]" if marker else chunk_ref
            family = _plus_family(chunk_info, "chunksPlus", family_name)
            if family is None:
                return False
            matches = sum(1 for ref in family if _chunk_reachable(ref, chunk_ids, reachable_sections))
            needed = int(count_str) if marker else 1
            if matches < needed:
                return False
        elif not _chunk_reachable(chunk_ref, chunk_ids, reachable_sections):
            return False
    return True


def _presence_requirement_met(
    challenge: Mapping[str, Any],
    field: str,
    index: Mapping[str, Mapping[str, Any]],
    chunk_info: ChunkInfo,
    plus_key: str,
) -> bool:
    names = challenge.get(field)
    if not isinstance(names, list):
        return True
    for name in names:
        if not isinstance(name, str):
            continue
        if "[+]" in name:
            family = _plus_family(chunk_info, plus_key, name)
            if family is None or not any(member in index for member in family):
                return False
        elif name not in index:
            return False
    return True


def _mix_requirement_met(
    challenge: Mapping[str, Any],
    monsters: Mapping[str, Mapping[str, Any]],
    npcs: Mapping[str, Mapping[str, Any]],
    chunk_info: ChunkInfo,
) -> bool:
    names = challenge.get("Mix")
    if not isinstance(names, list):
        return True
    for name in names:
        if not isinstance(name, str):
            continue
        if "[+]" in name:
            family = _plus_family(chunk_info, "mixPlus", name)
            if family is None or not any(member in monsters or member in npcs for member in family):
                return False
        elif name not in monsters and name not in npcs:
            return False
    return True


def _items_requirement_met(
    challenge: Mapping[str, Any], items: Mapping[str, Mapping[str, str]]
) -> bool:
    item_refs = challenge.get("Items")
    if not isinstance(item_refs, list):
        return True
    allowed_sources = challenge.get("AllowedSources")
    non_shop = challenge.get("NonShop") is True
    for item_ref in item_refs:
        if not isinstance(item_ref, str):
            continue
        if "[+]" in item_ref or "*" in item_ref:
            raise NotImplementedError(
                f"item-family/secondary matching for {item_ref!r} is not supported"
            )
        sources = items.get(item_ref)
        if sources is None:
            return False
        if non_shop and only_shop(sources):
            return False
        if not has_allowed_source(sources, allowed_sources):
            return False
    return True


def _has_any_valid(skill: str, valid: Mapping[str, Mapping[str, Any]]) -> bool:
    """Simplified stand-in for `checkPrimaryMethod`: does `skill` have any
    valid entry at all? Upstream's version additionally weighs primary vs.
    secondary sourcing, not modelled here.
    """
    return bool(valid.get(skill))


def _skills_requirement_met(
    challenge: Mapping[str, Any], max_skill: Mapping[str, int], valid: Mapping[str, Mapping[str, Any]]
) -> bool:
    skills = challenge.get("Skills")
    if not isinstance(skills, dict):
        return True
    for sub_skill, required_level in skills.items():
        if not _has_any_valid(sub_skill, valid):
            return False
        if isinstance(required_level, (int, float)) and sub_skill in max_skill:
            if required_level > max_skill[sub_skill]:
                return False
    return True


def _tasks_requirement_met(challenge: Mapping[str, Any], valid: Mapping[str, Mapping[str, Any]]) -> bool:
    tasks = challenge.get("Tasks")
    if not isinstance(tasks, dict):
        return True
    for task_name, task_skill in tasks.items():
        if not isinstance(task_skill, str):
            continue
        if task_name not in valid.get(task_skill, {}):
            return False
    return True


def _category_gate_met(
    challenge: Mapping[str, Any], rules: Mapping[str, Any], secondary_primary_amount: str
) -> bool:
    categories = challenge.get("Category")
    if not isinstance(categories, list):
        return True
    for category in categories:
        if category == "InsidePOH Primary" and rules.get("InsidePOH") is not True:
            level = challenge.get("Level")
            if isinstance(level, (int, float)) and level > 1:
                return False
        if category in _MAYBE_PRIMARY:
            continue
        if category not in rules:
            continue
        if rules[category] is True:
            continue
        if category == "Secondary Primary" and secondary_primary_amount != "1":
            continue
        return False
    return True


def _level_gates_met(challenge: Mapping[str, Any], skill: str, max_skill: Mapping[str, int], rules: Mapping[str, Any]) -> bool:
    for gate in _LEVEL_GATES_NOT_SUPPORTED:
        if gate in challenge:
            raise NotImplementedError(f"the {gate!r} gate is not supported")
    level = challenge.get("Level")
    if isinstance(level, (int, float)) and skill in max_skill and level > max_skill[skill]:
        return False
    if challenge.get("Not F2P") is True and rules.get("F2P") is True:
        return False
    if challenge.get("Not Skiller") is True and rules.get("Skiller") is True:
        return False
    return True


def _challenge_value(challenge: Mapping[str, Any], skill: str) -> int | str | bool:
    if skill in ("Quest", "Diary"):
        return True
    level = challenge.get("Level")
    if isinstance(level, (int, str)):
        return level
    label = challenge.get("Label")
    if isinstance(label, str):
        return label
    return True


def _evaluate_challenge(
    skill: str,
    name: str,
    challenge: Mapping[str, Any],
    *,
    chunk_ids: Mapping[str, bool],
    reachable_sections: Mapping[str, Mapping[str, bool]],
    items: Mapping[str, Mapping[str, str]],
    objects: Mapping[str, Mapping[str, Any]],
    monsters: Mapping[str, Mapping[str, Any]],
    npcs: Mapping[str, Mapping[str, Any]],
    valid: Mapping[str, Mapping[str, Any]],
    chunk_info: ChunkInfo,
    rules: Mapping[str, Any],
    max_skill: Mapping[str, int],
    secondary_primary_amount: str,
) -> int | str | bool | None:
    if not _level_gates_met(challenge, skill, max_skill, rules):
        return None
    if not _category_gate_met(challenge, rules, secondary_primary_amount):
        return None
    if not _chunks_requirement_met(challenge, chunk_ids, reachable_sections, chunk_info):
        return None
    if not _presence_requirement_met(challenge, "Objects", objects, chunk_info, "objectsPlus"):
        return None
    if not _presence_requirement_met(challenge, "Monsters", monsters, chunk_info, "monstersPlus"):
        return None
    if not _presence_requirement_met(challenge, "NPCs", npcs, chunk_info, "npcsPlus"):
        return None
    if not _mix_requirement_met(challenge, monsters, npcs, chunk_info):
        return None
    if not _items_requirement_met(challenge, items):
        return None
    if not _skills_requirement_met(challenge, max_skill, valid):
        return None
    if not _tasks_requirement_met(challenge, valid):
        return None
    return _challenge_value(challenge, skill)


def _seed_items_with_outputs(
    base_items: Mapping[str, Mapping[str, str]],
    valid: Mapping[str, Mapping[str, Any]],
    challenges: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, str]]:
    """A valid challenge with an `Output` becomes a new item source for the
    next pass. This is this module's own design for the feedback loop
    upstream's fixed point relies on - see the module docstring.
    """
    items: dict[str, dict[str, str]] = {item: dict(sources) for item, sources in base_items.items()}
    for skill, names in valid.items():
        skill_challenges = challenges.get(skill, {})
        for name in names:
            challenge = skill_challenges.get(name)
            output = challenge.get("Output") if isinstance(challenge, dict) else None
            if isinstance(output, str):
                items.setdefault(output, {})[name] = f"primary-{skill}"
    return items


def calc_challenges(
    chunk_ids: Mapping[str, bool],
    reachable_sections: Mapping[str, Mapping[str, bool]],
    source_index: SourceIndex,
    chunk_info: ChunkInfo,
    *,
    rules: Mapping[str, Any],
    max_skill: Mapping[str, int] | None = None,
    max_iterations: int = 15,
) -> ChallengeResult:
    """Port of `calcChallenges`/`calcChallengesWork`'s core fixed point - see
    the module docstring for exactly what is and is not implemented.
    """
    challenges = chunk_info.challenges
    max_skill = max_skill or {}
    secondary_primary_amount = str(rules.get("Secondary Primary Amount", "1"))

    items: Mapping[str, Mapping[str, str]] = source_index.items
    valid: dict[str, dict[str, int | str | bool]] = {}
    unsupported: set[str] = set()

    for _ in range(max_iterations):
        new_valid: dict[str, dict[str, int | str | bool]] = {}
        for skill, skill_challenges in challenges.items():
            if not isinstance(skill_challenges, dict):
                continue
            for name, challenge in skill_challenges.items():
                if not isinstance(challenge, dict):
                    continue
                try:
                    result = _evaluate_challenge(
                        skill,
                        name,
                        challenge,
                        chunk_ids=chunk_ids,
                        reachable_sections=reachable_sections,
                        items=items,
                        objects=source_index.objects,
                        monsters=source_index.monsters,
                        npcs=source_index.npcs,
                        valid=new_valid,
                        chunk_info=chunk_info,
                        rules=rules,
                        max_skill=max_skill,
                        secondary_primary_amount=secondary_primary_amount,
                    )
                except NotImplementedError:
                    # A single challenge using a mechanic this module
                    # doesn't implement (e.g. an item family, `*`) must not
                    # abort every other, evaluable challenge - see
                    # `ChallengeResult.unsupported`.
                    unsupported.add(f"{skill}/{name}")
                    continue
                if result is not None:
                    new_valid.setdefault(skill, {})[name] = result
        if new_valid == valid:
            break
        valid = new_valid
        items = _seed_items_with_outputs(source_index.items, valid, challenges)

    return ChallengeResult(valid=valid, unsupported=frozenset(unsupported))
