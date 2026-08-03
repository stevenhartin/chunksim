"""Classify each skill's valid challenges into active/obsolete/completed.

`challenges.calc_challenges` presence-checks every requirement, so once a
skill has several tiered challenges available (e.g. "Chop with a bronze axe"
*and* "Chop with a rune axe"), every tier stays in `ChallengeResult.valid`
simultaneously - there's no notion of a lower tier being superseded. This
module adds that on top, for the ~25 real skill categories only
(`challenges._SKILL_NAMES` - Quest/Diary/Extra/Nonskill/BiS are structurally
flat lists with no tier progression, and BiS gets its own completed/active
split in `bis.py` instead, since its own argmax already discards lower-tier
candidates before a task is ever generated).

Port of `calcCurrentChallenges2`'s selection (worker.js:8383-8727) - a
different mechanism from `challenges._group_processing_skill_challenges`
("Highest Level" grouping), which governs *fixed-point membership* for the 9
processing skills only. This module runs after that fixed point, over
whatever ended up valid for *any* skill, and picks a single *display*
winner - it never changes `ChallengeResult.valid` itself.

Verified against upstream and real map data before porting:
- There is no "obsolete" bookkeeping anywhere upstream (`grep -i
  "obsolete\\|supersed"` across index.js/worker.js: zero hits). "Only show
  the highest" is a pure per-recompute display choice; a lower tier is never
  flagged, deleted, or retroactively completed - it just stops winning the
  comparison once a higher one qualifies. So `obsolete` here is computed
  fresh every call, not read from any stored field.
- `completedChallenges` is never auto-derived from "a higher task became
  valid" - its only writer (`completeChallenges()`, index.js:12718) bulk-
  migrates whatever the user manually ticked (`checkedChallenges`) into it,
  triggered by unlocking/rolling a chunk or a manual button. It's a real,
  independent ledger, not something this module could reproduce from chunk
  state - it must be read from `MapState.completed_challenges`.
- `Primary` (32% of real challenges) and `Priority` (30%) are real fields
  this eligibility gate and tie-break need; getting them wrong changes which
  challenge "wins" for a meaningful fraction of skills.

The completed-level ceiling (`_completed_level_ceiling`) is upstream's
`highestChallengeLevelArr` (worker.js:8392): the highest `Level` among the
skill's *completed* challenges, which a candidate must **strictly exceed**
(`realLevel > highestChallengeLevelArr`, worker.js:8438) to compete. So a
candidate at or below it is settled and lands in `obsolete`. Completing a
task proves the level it needs, so everything no harder is done with,
whatever order it happened in - which matters because a temporary boost lets
a task be completed above the player's natural level. Four reported bugs
were this one mechanism, two of them equal-level (the reason `<=` and not
`<` is load-bearing):
- `Agility`: `Revenant Caves jump (hard)` (89, boosted) completed, yet the
  Level 81 ivy shortcut was proposed.
- `Woodcutting`/`Mining`: a 99 skillcape completed, yet Level 75/85 tasks
  proposed.
- `Firemaking`: `Burn magic logs` (75) completed, yet `Burn magic logs at a
  fire` - also 75 - proposed.
- `Smithing`: `rune platebody` (99) completed, yet `rune plateskirt` - also
  99, and only a worse `Priority` - proposed.

When it rules out every candidate the skill simply has no active pick, which
is the honest answer and common on a maxed account.

Scoped to *selection*: the ceiling is not fed back as an implied skill level
into `challenges.py`'s `Level` gate, which would change what is `valid` and
cascade well beyond this module.

Not ported, documented rather than silently wrong:
- **Boosting's level adjustment** (worker.js:8394-8430/8440-8466). `rules
  ['Boosting']` is on for real maps, and upstream compares a *boosted*
  `realLevel = Level - bestBoost` on both sides of the ceiling test, taking
  the best `codeItems.boostItems[skill]` entry the player can reach (plus a
  `+3` Construction Crystal saw case, `codeItems.boostTaskBans` exclusions,
  and `"N%+M"` proportional boosts), skipping any challenge flagged
  `NoBoost`. Nothing here models boost *ownership*, so comparisons use the
  raw `Level`. The consequence: a pick can be off whenever two candidates
  are within one boost of each other. It does not affect the oracle case -
  `activeTasks.Slayer` records `Slay an araxyte#Level 96` as `"92{5}"`, i.e.
  Level 92 less a 5-point `Wild pie` boost, and that challenge wins on raw
  level too - but it is the largest remaining gap in this module.
- The `tempAlwaysGlobal` backlog-alternate promotion: upstream, when the
  winning candidate is backlogged, promotes a same-item alternate recorded
  by the "Highest Level"-off grouping path. This module doesn't track that
  alternates list, so a backlogged winner simply means no active pick for
  that skill - backlogged and ordinary superseded entries both land in
  `obsolete` undifferentiated (backlog had exactly one real-data entry when
  this was built, so the cost of this simplification is low).
- Sub-skill `Skills`-requirement cross-propagation (a winning challenge also
  promoting itself as the pick for a sub-skill it requires) and the
  `Multi Step Processing` self-recursion.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from fray_claude.challenges import _SKILL_NAMES, _check_primary_method
from fray_claude.chunkinfo import ChunkInfo
from fray_claude.sources import SourceIndex

_EMPTY_SOURCE_INDEX = SourceIndex(
    items={}, objects={}, monsters={}, npcs={}, shops={}, drop_rates={}
)


@dataclass(frozen=True)
class SkillClassification:
    """One skill's challenges, partitioned. `active` is `None` when nothing
    qualifies (no eligible candidate, or the sole winner was a trivial
    `Level <= 1` non-`Primary` task - see the module docstring's step 4).
    """

    active: str | None
    obsolete: frozenset[str]
    completed: frozenset[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "obsolete": sorted(self.obsolete),
            "completed": sorted(self.completed),
        }


@dataclass(frozen=True)
class TaskClassification:
    """`skills` covers only `challenges._SKILL_NAMES` categories present in
    the `valid` passed to `classify_tasks` - every other category (Quest,
    Diary, Extra, Nonskill, BiS, ...) is absent, not empty.
    """

    skills: dict[str, SkillClassification] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {skill: classification.as_dict() for skill, classification in self.skills.items()}


def _is_eligible(
    name: str,
    level: float,
    *,
    skill: str,
    skill_is_primary: bool,
    passive_skill: Mapping[str, int],
    manual_tasks: Mapping[str, Mapping[str, Any]],
) -> bool:
    """Port of `calcCurrentChallenges2`'s candidacy gate (worker.js:8437):
    `isPrimary || realLevel === 1 || passiveSkill[skill] >= realLevel ||
    manualTasks[skill][challenge] || userTasks[skill][challenge]`.

    `skill_is_primary` is `checkPrimaryMethod(skill, ...)` - **one boolean
    per skill** ("can this skill be trained here at all"), not the
    challenge's own `Primary` field. An earlier version of this port read
    the per-challenge flag, which is a different thing entirely and broke
    both directions: `Slayer` challenges are almost all `Primary: false`, so
    only ones under the passive floor could ever be picked (the Level 92
    araxyte upstream records as the active task was unreachable), while
    `Herblore` - which `checkPrimaryMethod` reports untrainable on the real
    map - still offered a Level 90 potion.

    `manualTasks` is a real, per-account recorded override; unlike
    `challenges.py`'s requirement-checking, which deliberately never applies
    `manualTasks`/`userTasks`, this *selection* layer does, since here it
    means "treat this as the skill's active method" rather than a
    requirement bypass. `userTasks` is empty in real data and unmodelled.
    """
    if skill_is_primary:
        return True
    if level == 1:
        return True
    passive_level = passive_skill.get(skill)
    if isinstance(passive_level, (int, float)) and passive_level >= level:
        return True
    return name in manual_tasks.get(skill, {})


def _never_show(
    skill: str, name: str, challenge: Mapping[str, Any], rules: Mapping[str, Any]
) -> bool:
    """Upstream's `NeverShow` flag, which `calcChallengesWork` *sets* while
    checking validity (worker.js:3776/3782/3794) and `calcCurrentChallenges2`
    then honours when picking the active task.

    It never appears statically in the export (0 entries), so it has to be
    recomputed rather than read: three rules each hide a family of `Level > 1`
    challenges without invalidating them. On the map this was built against
    only the `Combat and Teleport Spells` arm fires, over 15 Magic
    challenges - a skill `checkPrimaryMethod` already reports untrainable
    there, so this changes nothing today and exists so it stays right if that
    changes.
    """
    level = challenge.get("Level")
    if not (isinstance(level, (int, float)) and level > 1):
        return False
    categories = challenge.get("Category") or []
    if not rules.get("Shortcut Task") and "Shortcut" in categories:
        return True
    if not rules.get("Combat and Teleport Spells") and "Combat and Teleport Spells Task" in categories:
        return True
    return (
        not rules.get("Cleaning Herbs")
        and skill == "Herblore"
        and ("Clean a" in name or "(unf)" in name)
    )


def _completed_level_ceiling(
    completed: Mapping[str, Any], skill_challenges: Mapping[str, Any]
) -> float | None:
    """The highest `Level` among this skill's already-completed challenges,
    or `None` if none of them carries one.

    Completing a task proves the level it needs, so anything easier is
    settled - see `_classify_skill` for why that has to gate candidacy.
    Reads the whole `completed` ledger, not just its currently-*valid*
    intersection: a completed task is evidence regardless of whether the
    present chunk set still makes it reachable. Entries with no `Level`, or
    none in the export at all (real data files diary tasks under a skill:
    `Woodcutting`'s completed set holds `~|Wilderness Diary#Medium|~ Task
    2`), contribute nothing rather than defaulting to a level.
    """
    levels = [
        float(level)
        for name in completed
        if isinstance(challenge := skill_challenges.get(name), dict)
        and isinstance(level := challenge.get("Level"), (int, float))
    ]
    return max(levels) if levels else None


def _classify_skill(
    skill: str,
    valid_names: Mapping[str, Any],
    skill_challenges: Mapping[str, Any],
    *,
    completed: Mapping[str, Any],
    backlog: Mapping[str, Any],
    manual_tasks: Mapping[str, Mapping[str, Any]],
    passive_skill: Mapping[str, int],
    skill_is_primary: bool,
    rules: Mapping[str, Any],
) -> SkillClassification:
    completed_names = {name for name in valid_names if name in completed}
    remaining = [name for name in valid_names if name not in completed_names]
    # A task no harder than one already completed is settled - see the module
    # docstring.
    ceiling = _completed_level_ceiling(completed, skill_challenges)

    winner: str | None = None
    winner_level = float("-inf")
    winner_priority: float | None = None
    for name in remaining:
        challenge = skill_challenges.get(name)
        if not isinstance(challenge, dict) or name in backlog:
            continue
        if _never_show(skill, name, challenge, rules):
            continue
        level = challenge.get("Level")
        level = float(level) if isinstance(level, (int, float)) else 1.0
        if ceiling is not None and level <= ceiling:
            continue
        if not _is_eligible(
            name,
            level,
            skill=skill,
            skill_is_primary=skill_is_primary,
            passive_skill=passive_skill,
            manual_tasks=manual_tasks,
        ):
            continue
        if winner is None or level > winner_level:
            winner, winner_level, winner_priority = name, level, challenge.get("Priority")
        elif level == winner_level:
            priority = challenge.get("Priority")
            if (
                isinstance(priority, (int, float))
                and isinstance(winner_priority, (int, float))
                and priority < winner_priority
            ):
                winner, winner_priority = name, priority

    if winner is not None:
        winner_challenge = skill_challenges.get(winner, {})
        if winner_level <= 1 and winner_challenge.get("Primary") is not True:
            winner = None

    obsolete = frozenset(name for name in remaining if name != winner)
    return SkillClassification(active=winner, obsolete=obsolete, completed=frozenset(completed_names))


def classify_tasks(
    valid: Mapping[str, Mapping[str, Any]],
    chunk_info: ChunkInfo,
    *,
    completed_challenges: Mapping[str, Mapping[str, Any]],
    manual_tasks: Mapping[str, Mapping[str, Any]],
    backlog: Mapping[str, Mapping[str, Any]],
    passive_skill: Mapping[str, int],
    source_index: SourceIndex | None = None,
    rules: Mapping[str, Any] | None = None,
) -> TaskClassification:
    """Classify every `challenges._SKILL_NAMES` category present in `valid`.

    `source_index` is what `checkPrimaryMethod` needs to decide whether each
    skill is trainable at all (see `_is_eligible`). It defaults to an empty
    index rather than being required, which reports every skill untrainable -
    fine for a fixture exercising one rule, wrong for real data, so callers
    deriving a real map must pass it (`pipeline.derive` does).
    """
    challenges = chunk_info.challenges
    index = source_index if source_index is not None else _EMPTY_SOURCE_INDEX
    rules = rules or {}
    skills: dict[str, SkillClassification] = {}
    for skill, valid_names in valid.items():
        if skill not in _SKILL_NAMES or not valid_names:
            continue
        skills[skill] = _classify_skill(
            skill,
            valid_names,
            challenges.get(skill, {}),
            completed=completed_challenges.get(skill, {}),
            backlog=backlog.get(skill, {}),
            manual_tasks=manual_tasks,
            passive_skill=passive_skill,
            rules=rules,
            skill_is_primary=_check_primary_method(
                skill,
                valid,
                index,
                chunk_info,
                passive_skill=passive_skill,
                backlog=backlog,
                manual_tasks=manual_tasks,
            ),
        )
    return TaskClassification(skills=skills)
