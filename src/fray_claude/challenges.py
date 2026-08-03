"""Which challenges (tasks) are valid, given the unlocked chunks' sources.

Port of the core of `calcChallenges`/`calcChallengesWork` (worker.js): a
fixed point over 28 of the 29 challenge categories - all but `BiS`. Each
challenge's `Chunks`/`Items`/`Objects`/`Monsters`/`NPCs`/`Skills`/`Tasks`
requirements are checked against the source index (`sources.py`) and the
running set of already-valid challenges; a valid challenge with an `Output`
feeds back as a new item source, so another pass may unlock further
challenges - repeating until nothing changes.

**`BiS` is never evaluated *here*, but it is computed - by `bis.py`, not
this module.** Unlike the other 28 categories, `BiS` challenges have no
static definition anywhere in `chunkinfo.json` - `challenges.BiS` doesn't
exist in the export at all, so it shares no structure with the
requirement-checking this module does for every other category (upstream's
`calcBIS` compares the `equipment` table's combat stats across weapon/armour
slots per combat style instead - see `bis.py`'s module docstring for the
full port). `UNSUPPORTED_CATEGORIES` and the `skill in UNSUPPORTED_CATEGORIES`
skip below exist only to guard against a hypothetical/malformed export that
*does* carry a literal `challenges.BiS` branch: presence-checking it with
this module's generic engine would produce nonsense (real BiS validity isn't
a presence check at all), so it's skipped rather than silently mis-evaluated.
Callers wanting BiS should read `pipeline.Derived.bis`, not
`ChallengeResult.valid['BiS']`, which this module never populates.

Scope: `calcChallengesWork` is ~1,500 extremely dense lines. What's implemented, and what isn't,
below.

Implemented:
- `Chunks`/`Objects`/`Monsters`/`NPCs`/`Mix` requirements: full presence
  checking, including `[+]` family matching (`objectsPlus`-style groups,
  ported via `chunkinfo.json`'s `codeItems`) and `[+]xN` "at least N of"
  counting for `Chunks`.
- `Items` requirements: presence checking, including `[+]`/`[+]xN` family
  matching via `codeItems.itemsPlus`, and `AllowedSources`/`NonShop`
  filtering. The `*` secondary marker is stripped and otherwise ignored -
  verified against upstream (worker.js:4046,4064) it does **not** gate
  validity, only a `Secondary` flag feeding `checkPrimaryMethod` (not ported)
  and a `forcedPrimary` gate with zero real-export uses, so it isn't
  threaded through here; see `_items_requirement_met`'s docstring. For
  combat skills and challenges whose `Category` includes `BIS Skilling`, an
  item sourced *only* from another skill's crafted output is additionally
  rejected unless `Not Equip`/`Wield Crafted Items`/a Slayer source/the
  requiring skill being Magic excuses it - see `_source_quality_ok`.
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
- The `processingSkill` categories' (Runecraft, Magic, Herblore, Cooking,
  Firemaking, Fletching, Smithing, Crafting, Construction) "Highest Level"
  grouping (`_group_processing_skill_challenges`, worker.js:4413-4680):
  **when `rules['Highest Level']` is off**, a challenge that consumes an
  available ingredient is valid only if it is the *lowest*-`Level`-consumer
  of at least one such ingredient (e.g. smelting a bronze bar lets you smith
  a bronze dagger, not simultaneously every higher-tier bronze item) - not
  "surface only the highest", the docstring here previously had this
  backwards. **When the rule is on** (true of the map this was built
  against), every consumer is valid, matching the plain per-challenge
  checking above with no grouping needed.

Not implemented - each raises `NotImplementedError` naming the mechanic,
except where noted as a silent, documented approximation instead:
- `QuestPointsNeeded`/`CombatPointsNeeded`/`KudosNeeded`/`TotalLevelNeeded`/
  `CombatLevelNeeded` gates: correctly computing those aggregates needs
  state (quest points earned, kudos, etc.) this module does not derive.
  Rare in the export (single digits to low tens of challenges; 42 on the
  map this was built against, all of them one of these five gates).
- **Silent approximation, not a raise**: the "Highest Level" grouping above
  doesn't model upstream's `tools`/`ManualNonProcessing`/Quest-Diary-sub-task
  direct-add escapes, its `Boosting` level-shift, its multi-pass re-pick
  after `Tasks`/`Skills` pruning, or the `nonskill` chain-flattening that
  lets a group's own `Items` re-expand mid-walk. It also runs once, after
  the fixed point converges, rather than feeding grouped-out challenges'
  `Output` back out of `_seed_items_with_outputs` - so item-seeding can be
  mildly over-inclusive relative to the final grouped `valid`. The
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
from dataclasses import dataclass, field
from typing import Any

from fray_claude.chunkinfo import ChunkInfo
from fray_claude.sources import SourceIndex
from fray_claude.summary import _mapping

_MAYBE_PRIMARY = frozenset({"Normal Farming", "Sulphurous Fertiliser", "Shortcut", "InsidePOH Primary"})

#: Categories `calc_challenges` never evaluates - their absence from
#: `ChallengeResult.valid` means "not computed", not "nothing is valid".
#: See the module docstring for why `BiS` specifically is out of scope.
UNSUPPORTED_CATEGORIES = frozenset({"BiS"})

_PROCESSING_SKILLS = frozenset(
    {"Runecraft", "Magic", "Herblore", "Cooking", "Firemaking", "Fletching", "Smithing", "Crafting", "Construction"}
)

#: index.js's `skillNames`/`combatSkills` - every real skill category, and
#: the 7 combat ones. Used by `_source_quality_ok`'s source-tag check.
_SKILL_NAMES = frozenset(
    {
        "Slayer", "Thieving", "Attack", "Defence", "Strength", "Hitpoints", "Ranged",
        "Prayer", "Magic", "Farming", "Herblore", "Hunter", "Cooking", "Woodcutting",
        "Firemaking", "Fletching", "Fishing", "Mining", "Runecraft", "Sailing",
        "Smithing", "Crafting", "Agility", "Construction", "Combat",
    }
)
_COMBAT_SKILLS = frozenset({"Attack", "Strength", "Defence", "Hitpoints", "Ranged", "Magic", "Prayer"})

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

    `available_items` is `SourceIndex.items` plus every valid challenge's
    `Output` (the fixed point's own `_seed_items_with_outputs` result, at
    the pass matching `valid`). It is what downstream consumers wanting "what
    can I actually get" should read - `SourceIndex.items` alone omits
    anything only obtainable by *making* it, e.g. `Granite ring (i)`, which
    exists solely as the output of an imbue challenge. Deliberately excluded
    from `as_dict`: it's a pipeline artifact (thousands of entries), not part
    of the user-facing task result.
    """

    valid: dict[str, dict[str, int | str | bool]]
    unsupported: frozenset[str]
    available_items: dict[str, dict[str, str]] = field(default_factory=dict)

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


def _item_source_ok(
    sources: Mapping[str, str] | None, non_shop: bool, allowed_sources: Any
) -> bool:
    if sources is None:
        return False
    if non_shop and only_shop(sources):
        return False
    return has_allowed_source(sources, allowed_sources)


def _source_quality_ok(
    sources: Mapping[str, str], *, skill: str, challenge: Mapping[str, Any], rules: Mapping[str, Any]
) -> bool:
    """Port of the combat/`BIS Skilling` source-quality gate
    (worker.js:4067-4082): for combat skills and challenges whose `Category`
    includes `BIS Skilling`, an item only counts if at least one of its
    sources is *not* a plain skill-training output (a `primary-<Skill>` /
    `secondary-<Skill>` tag where `<Skill>` is a real skill name, i.e. an
    output fed back by `_seed_items_with_outputs`) - don't require training a
    skill just to wield its product - unless `Not Equip` is set,
    `rules['Wield Crafted Items']` is on, the training skill is Slayer, or
    the requiring skill is Magic. Upstream's escape hatch for a matching
    Quest/Diary `Tasks` sub-task (the `'--'`-joined naming convention) is not
    ported - it has no real-export uses worth the complexity.
    """
    if skill not in _COMBAT_SKILLS:
        categories = challenge.get("Category")
        if not (isinstance(categories, list) and "BIS Skilling" in categories):
            return True
    for tag in sources.values():
        source_skill = tag.partition("-")[2]
        if (
            "-" not in tag
            or source_skill not in _SKILL_NAMES
            or challenge.get("Not Equip") is True
            or rules.get("Wield Crafted Items") is True
            or source_skill == "Slayer"
            or skill == "Magic"
        ):
            return True
    return False


def _item_usable(
    sources: Mapping[str, str] | None,
    *,
    non_shop: bool,
    allowed_sources: Any,
    skill: str,
    challenge: Mapping[str, Any],
    rules: Mapping[str, Any],
) -> bool:
    if not _item_source_ok(sources, non_shop, allowed_sources):
        return False
    assert sources is not None  # narrowed by _item_source_ok
    return _source_quality_ok(sources, skill=skill, challenge=challenge, rules=rules)


def _items_requirement_met(
    challenge: Mapping[str, Any],
    items: Mapping[str, Mapping[str, str]],
    chunk_info: ChunkInfo,
    *,
    skill: str,
    rules: Mapping[str, Any],
) -> bool:
    """Port of the `Items` block (worker.js:3899-4121). The `*` secondary
    marker is stripped and otherwise ignored here: verified against upstream
    (worker.js:4046,4064), it does **not** gate validity - it only sets a
    per-challenge `Secondary` flag that feeds `checkPrimaryMethod` (not
    ported; see `_has_any_valid`'s docstring) and a `forcedPrimary` gate that
    has zero real-export uses, so it isn't threaded through here. `[+]`
    resolves through `codeItems.itemsPlus`, the same shape `_plus_family`
    already handles for `Chunks`/`Objects`/`Monsters`/`NPCs`/`Mix`.
    """
    item_refs = challenge.get("Items")
    if not isinstance(item_refs, list):
        return True
    allowed_sources = challenge.get("AllowedSources")
    non_shop = challenge.get("NonShop") is True
    for item_ref in item_refs:
        if not isinstance(item_ref, str):
            continue
        name = item_ref.replace("*", "")
        if "[+]" in name:
            base_name, marker, count_str = name.partition("[+]x")
            family_name = f"{base_name}[+]" if marker else name
            family = _plus_family(chunk_info, "itemsPlus", family_name)
            if family is None:
                return False
            needed = int(count_str) if marker else 1
            matches = sum(
                1
                for member in family
                if _item_usable(
                    items.get(member),
                    non_shop=non_shop,
                    allowed_sources=allowed_sources,
                    skill=skill,
                    challenge=challenge,
                    rules=rules,
                )
            )
            if matches < needed:
                return False
        elif not _item_usable(
            items.get(name),
            non_shop=non_shop,
            allowed_sources=allowed_sources,
            skill=skill,
            challenge=challenge,
            rules=rules,
        ):
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
    if not _items_requirement_met(challenge, items, chunk_info, skill=skill, rules=rules):
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
    chunk_info: ChunkInfo,
    rules: Mapping[str, Any],
    backlogged_sources: Mapping[str, Any],
) -> dict[str, dict[str, str]]:
    """A valid challenge's `Output` becomes a new item source for the next
    pass - and, when that `Output` names an activity in
    `skillItems[<that skill>]`, so does every item that activity yields.

    The second half is what makes non-Slayer `skillItems` reachable at all.
    Upstream's link (worker.js:2848, index.js:8603) is exactly this: a
    challenge's `Output` doubles as the *activity key* into `skillItems`.
    `Master wand`, for instance, exists only in
    `skillItems.Nonskill['Pizazz points loot']`, reached because the
    `~|Pizazz points|~*` challenge has `Output: 'Pizazz points loot'` -
    without this it is unobtainable, and BiS picks a worse Magic weapon.
    Note the activity key is *not* an entity name, which is why
    `sources.py`'s chunk-presence route can't find these (it handles the
    other `skillItems` path: a Slayer monster physically in an unlocked
    chunk - see `_slayer_skill_items_for`).

    Upstream accumulates these in an `outputs` map tagged
    `'<primary|secondary>-' + the challenge's own Source` before merging
    into the item index (worker.js:2894, 3037). Simplified here: everything
    is tagged `primary-`, since upstream's primary/secondary split is a
    drop-rate comparison against `Secondary Primary Amount` that this
    module doesn't compute, and the `Rare Drop Amount` rate filter on the
    activity's items isn't applied either (both admit everything on the map
    this was built against). The `bossLogs` gate *is* applied - it excludes
    8 real activities and is live whenever the `Boss` rule is off.

    `backloggedSources['items']` is honoured, matching upstream's own gate
    on this merge (worker.js:3030) and `sources.py`'s handling of the
    ordinary routes. It is *not* cosmetic: a user backlogs a source to say
    "I will not do this", so leaving it in silently readmits it as a
    prerequisite. Real example - `Uncut onyx` is backlogged on the map this
    was built against, and without this gate it re-entered through
    `skillItems.Nonskill['Bag full of gems loot']` at a 1/100,000,000 rate,
    dragged in the whole onyx -> onyx bracelet -> `Regen bracelet` crafting
    chain, and displaced the correct Melee-hands BiS pick.
    """
    items: dict[str, dict[str, str]] = {item: dict(sources) for item, sources in base_items.items()}
    skill_items = chunk_info.skill_items
    boss_logs = _mapping(chunk_info.code_items, "bossLogs")
    allow_boss = rules.get("Boss") is True
    backlogged_items = _mapping(backlogged_sources, "items")

    for skill, names in valid.items():
        skill_challenges = challenges.get(skill, {})
        activities = skill_items.get(skill)
        activities = activities if isinstance(activities, dict) else {}
        for name in names:
            challenge = skill_challenges.get(name)
            if not isinstance(challenge, dict):
                continue
            output = challenge.get("Output")
            if not isinstance(output, str):
                continue
            if backlogged_items.get(output) is not True:
                items.setdefault(output, {})[name] = f"primary-{skill}"

            table = activities.get(output)
            if not isinstance(table, dict) or (not allow_boss and output in boss_logs):
                continue
            source = challenge.get("Source")
            tag = f"primary-{source}" if isinstance(source, str) and source else f"primary-{skill}"
            for item in table:
                if isinstance(item, str) and backlogged_items.get(item) is not True:
                    items.setdefault(item, {}).setdefault(name, tag)
    return items


def _group_processing_skill_challenges(
    valid: Mapping[str, Mapping[str, int | str | bool]],
    challenges: Mapping[str, Mapping[str, Any]],
    items: Mapping[str, Mapping[str, str]],
    rules: Mapping[str, Any],
) -> dict[str, dict[str, int | str | bool]]:
    """Port of the "Highest Level" grouping fork (worker.js:4413-4680), run
    once after `calc_challenges`'s fixed point converges.

    When `rules['Highest Level']` is off, a `_PROCESSING_SKILLS` challenge
    that consumes an available ingredient is valid only if it is the
    lowest-`Level` consumer of at least one such ingredient - ties keep
    whichever consumer is seen first, in `chunk_info.challenges`' own key
    order (upstream's further `Priority`/`Primary`/`Secondary` tie-break
    isn't modelled - see the module docstring). When the rule is on, every
    consumer of an available ingredient is valid, which is exactly what the
    per-challenge checking already produced, so this is a no-op.
    """
    if rules.get("Highest Level") is True:
        return {skill: dict(names) for skill, names in valid.items()}

    result: dict[str, dict[str, int | str | bool]] = {
        skill: dict(names) for skill, names in valid.items() if skill not in _PROCESSING_SKILLS
    }
    for skill in _PROCESSING_SKILLS:
        skill_valid = valid.get(skill)
        if not skill_valid:
            continue
        skill_challenges = challenges.get(skill, {})
        groups: dict[str, list[str]] = {}
        winners: dict[str, int | str | bool] = {}
        for name in skill_valid:
            challenge = skill_challenges.get(name)
            item_refs = challenge.get("Items") if isinstance(challenge, dict) else None
            if not isinstance(item_refs, list) or not item_refs:
                winners[name] = skill_valid[name]
                continue
            for item_ref in item_refs:
                if not isinstance(item_ref, str):
                    continue
                ingredient = item_ref.replace("*", "").split("[+]x")[0]
                if ingredient in items:
                    groups.setdefault(ingredient, []).append(name)

        def _level(name: str) -> float:
            level = skill_challenges.get(name, {}).get("Level")
            return level if isinstance(level, (int, float)) else float("inf")

        for names in groups.values():
            winner = min(names, key=_level)
            winners[winner] = skill_valid[winner]
        if winners:
            result[skill] = winners
    return result


def calc_challenges(
    chunk_ids: Mapping[str, bool],
    reachable_sections: Mapping[str, Mapping[str, bool]],
    source_index: SourceIndex,
    chunk_info: ChunkInfo,
    *,
    rules: Mapping[str, Any],
    max_skill: Mapping[str, int] | None = None,
    backlogged_sources: Mapping[str, Any] | None = None,
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
            if skill in UNSUPPORTED_CATEGORIES or not isinstance(skill_challenges, dict):
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
        items = _seed_items_with_outputs(
            source_index.items, valid, challenges, chunk_info, rules, backlogged_sources or {}
        )

    grouped = _group_processing_skill_challenges(valid, challenges, items, rules)
    return ChallengeResult(
        valid=grouped,
        unsupported=frozenset(unsupported),
        available_items={item: dict(sources) for item, sources in items.items()},
    )
