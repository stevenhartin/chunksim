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
  the tie-break needs; getting them wrong changes which challenge "wins" for
  a meaningful fraction of skills. Note `Primary` is **not** the eligibility
  gate (that is the skill-wide `checkPrimaryMethod` - see `_is_eligible`); it
  is a tie-breaker, via `_wins_tie`'s second branch.
- `ForcedSecondary` plays no part in this selection at all. Its only three
  upstream uses (worker.js:2971/2976/3008) are in the `skillItems` drop-rate
  classification, deciding whether an activity's item counts as a primary or
  secondary source - a distinction `challenges._seed_items_with_outputs`
  deliberately flattens. A `ForcedSecondary` challenge is superseded here by
  the ordinary `BackupParent`/`Priority`/ceiling machinery, not by the flag.

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

Every level this module compares is a *boosted* level (`boosts.py`): the
ceiling uses `boosts.completed_ceiling`, each candidate `boosts.real_level`,
and `_is_eligible`'s `level == 1` test therefore fires on the boosted value
too, exactly as upstream's `realLevel === 1` does. That last one is not a
technicality - it is how a skill `checkPrimaryMethod` calls untrainable can
still have an active task: on the real map `Clean a ~|grimy guam leaf|~`
(Level 3) boosts to 1 via `Greenman's ale(m)` and becomes `Herblore`'s pick.

Not ported, documented rather than silently wrong:
- The `tempAlwaysGlobal` backlog-alternate promotion: upstream, when the
  winning candidate is backlogged, promotes a same-item alternate recorded
  by the "Highest Level"-off grouping path. This module doesn't track that
  alternates list, so a backlogged winner simply means no active pick for
  that skill - backlogged and ordinary superseded entries both land in
  `obsolete` undifferentiated (backlog had exactly one real-data entry when
  this was built, so the cost of this simplification is low).
- Sub-skill `Skills`-requirement cross-propagation (a winning challenge also
  promoting itself as the pick for a sub-skill it requires) and the
  `Multi Step Processing` self-recursion. The related *filter* on the winner
  (worker.js:8472 - every sub-skill in a winner's `Skills` must be trainable,
  or covered by `passiveSkill`, and never above `maxSkill`) is also unported;
  it was checked against the real map and rejects nothing there.

The `Herblore Unlocked`/`Herblore Unlocked Snake Weed` rules need no code of
their own: they are ordinary `Category` values on the seven `Unlock
~|Herblore|~ ...` challenges, so `challenges._category_gate_met` already
handles them, and the `Druidic Ritual` gate is that unlock challenge's own
`Tasks` requirement. Nothing anywhere references those challenges in turn -
grepped both upstream files and the whole export - so an unreachable
`Druidic Ritual` makes `Herblore` untrainable via `checkPrimaryMethod` (no
`Level == 1` `Primary` route survives) but does **not** invalidate the
skill's other challenges. A Level 3 herb clean boosted to `realLevel == 1`
is therefore still eligible, which is upstream's own rule, not a gap here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from fray_claude import boosts
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


def _recorded(name: str, ledger: Mapping[str, Any]) -> bool:
    """Is `name` in a stored `{name: value}` ledger, under either spelling?

    Upstream pairs every `completedChallenges`/`backlog` lookup with a second
    one on `challenge.replaceAll('#', '/')` (worker.js:8438, 8471, ...). The
    `#` in a name like `~|Morytania Diary#Easy|~ Task 3` separates a variant,
    and older records store it as `/`, so a single-spelling check silently
    treats an already-completed task as outstanding.
    """
    return name in ledger or name.replace("#", "/") in ledger


def _lower_priority(challenger: Any, incumbent: Any) -> bool:
    """`challenger['Priority'] < incumbent['Priority']`, numeric only."""
    return (
        isinstance(challenger, (int, float))
        and isinstance(incumbent, (int, float))
        and challenger < incumbent
    )


def _wins_tie(challenger: Mapping[str, Any], incumbent: Mapping[str, Any]) -> bool:
    """Does `challenger` displace `incumbent` at equal boosted level?

    Upstream tries two branches in turn (worker.js:8469, then 8493 when the
    first fails), and they are not the same test:

    - **A**: the incumbent has no *truthy* `Priority`, or the challenger has
      a truthy one that is lower. (`Priority: 0` reads as "none" here, since
      JS tests it for truthiness.)
    - **B**: failing that, a challenger flagged `Primary` still wins if
      *either* side simply has no `Priority` **key**, or its own is lower.

    B is what makes `Primary` a tie-breaker in its own right: a `Primary`
    challenge carrying no `Priority` at all displaces an incumbent that has
    one, which branch A alone would never allow. Only the per-challenge flag
    is meant here - the *skill*-wide `checkPrimaryMethod` boolean is a
    different thing entirely and gates eligibility, not this (see
    `_is_eligible`).
    """
    challenger_priority = challenger.get("Priority")
    incumbent_priority = incumbent.get("Priority")
    if not incumbent_priority:
        return True
    if challenger_priority and _lower_priority(challenger_priority, incumbent_priority):
        return True
    if not challenger.get("Primary"):
        return False
    if "Priority" not in challenger or "Priority" not in incumbent:
        return True
    return _lower_priority(challenger_priority, incumbent_priority)


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
    skill: str,
    completed: Mapping[str, Any],
    skill_challenges: Mapping[str, Any],
    *,
    rules: Mapping[str, Any],
    chunk_info: ChunkInfo,
    items: Mapping[str, Any],
    source_index: SourceIndex,
) -> float | None:
    """Upstream's `highestChallengeLevelArr[skill]` (worker.js:8392-8430):
    the highest *boost-adjusted* level among this skill's already-completed
    challenges, or `None` if none of them carries a `Level`.

    Completing a task proves the level it needs, so anything no harder is
    settled - see `_classify_skill` for why that gates candidacy. Reads the
    whole `completed` ledger, not just its currently-*valid* intersection: a
    completed task is evidence regardless of whether the present chunk set
    still makes it reachable. Entries with no `Level`, or none in the export
    at all (real data files diary tasks under a skill: `Woodcutting`'s
    completed set holds `~|Wilderness Diary#Medium|~ Task 2`), contribute
    nothing rather than defaulting to a level.

    Uses `boosts.completed_ceiling`, not `boosts.real_level` - the two clamp
    differently upstream and this is the completed side. Boosting *lowers*
    the ceiling: a task you only managed with a Wild pie proves less than
    its face level.
    """
    levels = [
        boosts.completed_ceiling(
            skill,
            name,
            challenge,
            float(level),
            rules=rules,
            chunk_info=chunk_info,
            items=items,
            source_index=source_index,
        )
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
    chunk_info: ChunkInfo,
    items: Mapping[str, Any],
    source_index: SourceIndex,
) -> SkillClassification:
    completed_names = {name for name in valid_names if _recorded(name, completed)}
    remaining = [name for name in valid_names if name not in completed_names]
    # A task no harder than one already completed is settled - see the module
    # docstring.
    ceiling = _completed_level_ceiling(
        skill,
        completed,
        skill_challenges,
        rules=rules,
        chunk_info=chunk_info,
        items=items,
        source_index=source_index,
    )

    winner: str | None = None
    winner_level = float("-inf")
    winner_challenge: Mapping[str, Any] = {}
    for name in remaining:
        challenge = skill_challenges.get(name)
        if not isinstance(challenge, dict) or _recorded(name, backlog):
            continue
        if _never_show(skill, name, challenge, rules):
            continue
        raw_level = challenge.get("Level")
        raw_level = float(raw_level) if isinstance(raw_level, (int, float)) else 1.0
        # Every comparison from here down is against the *boosted* level,
        # exactly as upstream's `realLevel` is (worker.js:8436-8466).
        level = boosts.real_level(
            skill,
            name,
            challenge,
            raw_level,
            rules=rules,
            chunk_info=chunk_info,
            items=items,
            source_index=source_index,
        )
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
        if winner is None or level > winner_level or (
            level == winner_level and _wins_tie(challenge, winner_challenge)
        ):
            winner, winner_level, winner_challenge = name, level, challenge

    if winner is not None and winner_level <= 1 and winner_challenge.get("Primary") is not True:
        # `realLevel <= 1 && !Primary` -> discarded entirely (worker.js:8521).
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
    available_items: Mapping[str, Any] | None = None,
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
    # `ChallengeResult.available_items`, not `SourceIndex.items` - boosts are
    # often crafted (`Wild pie`). See `boosts._available`.
    available_items = index.items if available_items is None else available_items
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
            chunk_info=chunk_info,
            items=available_items,
            source_index=index,
            skill_is_primary=_check_primary_method(
                skill,
                valid,
                index,
                chunk_info,
                passive_skill=passive_skill,
                backlog=backlog,
                manual_tasks=manual_tasks,
                rules=rules,
                items=available_items,
            ),
        )
    return TaskClassification(skills=skills)
