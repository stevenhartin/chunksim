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

Not ported, documented rather than silently wrong:
- Boosting's level adjustment (owned boost items, Crystal saw) - no
  boost-ownership state exists anywhere in this codebase, the same class of
  gap as `checkPrimaryMethod` (see `challenges.py`/`sources.py`'s
  docstrings). Comparisons here use each challenge's raw `Level`.
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

from fray_claude.challenges import _SKILL_NAMES
from fray_claude.chunkinfo import ChunkInfo


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
    challenge: Mapping[str, Any],
    level: float,
    *,
    skill: str,
    passive_skill: Mapping[str, int],
    manual_tasks: Mapping[str, Mapping[str, Any]],
) -> bool:
    """Port of `calcCurrentChallenges2`'s candidacy gate (worker.js:~8420):
    a challenge only competes for "active" if it's flagged `Primary`, is a
    trivial `Level == 1` task, is already covered by a passive-skill floor,
    or has a `manualTasks` entry (a real, per-account recorded override -
    unlike `challenges.py`'s requirement-checking, which deliberately never
    applies `manualTasks`/`userTasks`, this *selection* layer does, since
    `manualTasks` here means "treat this as the skill's active method"
    rather than a requirement bypass).
    """
    if challenge.get("Primary") is True:
        return True
    if level == 1:
        return True
    passive_level = passive_skill.get(skill)
    if isinstance(passive_level, (int, float)) and passive_level >= level:
        return True
    return name in manual_tasks.get(skill, {})


def _classify_skill(
    skill: str,
    valid_names: Mapping[str, Any],
    skill_challenges: Mapping[str, Any],
    *,
    completed: Mapping[str, Any],
    backlog: Mapping[str, Any],
    manual_tasks: Mapping[str, Mapping[str, Any]],
    passive_skill: Mapping[str, int],
) -> SkillClassification:
    completed_names = {name for name in valid_names if name in completed}
    remaining = [name for name in valid_names if name not in completed_names]

    winner: str | None = None
    winner_level = float("-inf")
    winner_priority: float | None = None
    for name in remaining:
        challenge = skill_challenges.get(name)
        if not isinstance(challenge, dict) or name in backlog:
            continue
        level = challenge.get("Level")
        level = float(level) if isinstance(level, (int, float)) else 1.0
        if not _is_eligible(
            name, challenge, level, skill=skill, passive_skill=passive_skill, manual_tasks=manual_tasks
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
) -> TaskClassification:
    """Classify every `challenges._SKILL_NAMES` category present in `valid`."""
    challenges = chunk_info.challenges
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
        )
    return TaskClassification(skills=skills)
