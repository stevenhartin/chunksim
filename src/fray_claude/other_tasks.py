"""Group the non-skill task categories: Quest, Diary and Extra ("Other").

These three work nothing like the skill categories `active_tasks.py` handles,
which is why they get their own module. `calcCurrentChallenges2` **excludes**
`Extra`/`Quest`/`Diary`/`BiS` from its per-skill loop outright
(worker.js:8390), so there is no single highest-level winner to compute:
upstream's panel renders *every* valid challenge in the category that isn't
completed or backlogged (index.js:6702/6744/6767), grouped for display.

Two details of that guard matter, and both were wrong here before:

- It tests `completedChallenges` **alone** (index.js:6745), so a task merely
  ticked this chunk still renders in the active list, just with its checkbox
  set (index.js:6663). A terminal has no checkbox, so this module
  **deliberately diverges**: a ticked task is reported as *completed*, sorted
  to the front of its group and of the category, and marked
  `challenges.CURRENT_CHUNK_SUFFIX` - the same treatment `bis.py` gives its own
  current-chunk acquisitions. `CategoryTasks.current_chunk` names them, so the
  panel's own count is still recoverable as `active_total + len(current_chunk)`
  and the opt-in oracle test compares against that.
- Completions are reported whether or not the challenge is still valid, the
  same rule `active_tasks.py` follows: a requirement added by a later game
  update must not erase the fact that the task was done.

`Quest` gets two extra passes, both about the same fact - a quest is a step
chain, so progress at one point settles everything before it:

- `_implied_completions` closes the *recorded* completions transitively.
  Ticking a quest off stores only `~|X|~ Complete the quest`, so every
  prerequisite it reaches counts as done too.
- `_superseded` is a port of upstream's `markSubTasks(..., false)`
  (worker.js:485, called at :1486 for every fully-valid challenge). Being
  able to *reach* a step means its prerequisites are behind you whether or
  not anything recorded them; upstream writes `false` into the step's valid
  value and the panel's `&& globalValids['Quest'][challenge]` guard hides it.
  Only the furthest reachable step of a quest shows. It is kept as a set here
  rather than written into `ChallengeResult.valid`, whose values mean
  "requirements met" everywhere else and which `unlock.py`/`simulate.py` diff.
  `[+]` families expand to **every** member (worker.js:498/512): `~|Shield of
  Arrav|~ 3` needs `ShieldOfArrav2Final[+]`, the last step of either route,
  and reaching it means whichever route you took is done - upstream cannot
  tell which either. Note the family key is
  `name.split('[+]x')[0].replace('[+]','') + '[+]'`: an existing `[+]` comes
  *off* before one is appended, or `X[+]` looks up as `X[+][+]` and silently
  finds nothing. Both passes are guarded on a matching `BaseQuest`.

Together those two took `Quest` active from 94 to 7 to 0 on the real map, and
0 is right: only 13 quests are fully reachable there, and all 13 are done.

`Diary` gets `_implied_completions` too, but seeded from a **tier completion
only** (`_implies_from` - the challenges carrying a `Reward`, whose `Tasks`
list every task in that tier). Real data had ten of Morytania Easy's eleven
tasks marked individually plus the tier itself, leaving `Task 8` looking
outstanding. An ordinary diary task implies nothing, its `Tasks` being
ordinary requirements rather than a roster.

Grouping mirrors the panel's own: `Quest` by `BaseQuest`; `Diary` by the
diary and tier encoded in the name (`~|Morytania Diary#Elite|~ Task 5` ->
*Morytania Diary - Elite*); `Extra` by its `Label` field, whose values are
exactly the user-facing groups - `Collection Log`, `Permanent Unlockables`,
`Untracked Uniques`, plus `Fill POH`/`Fill Stashes`/`BIS Skilling`/
`Stuffables` when their rules are on. Which labels appear is already handled
upstream of here: `challenges._category_gate_met` drops a challenge whose
`Category` names a rule that is off.

`Extra` is the export's own key and stays the key in `--export-json`;
**`Other` is the display name** (`display_name`), and `fray tasks` accepts
either.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from fray_claude.active_tasks import _recorded
from fray_claude.challenges import CURRENT_CHUNK_SUFFIX, strip_task_markup
from fray_claude.model.chunkinfo import ChunkInfo

#: The categories this module owns, in the order the CLI prints them.
CATEGORIES = ("Diary", "Quest", "Extra")

#: `Extra` is the export's key; "Other" is what the app calls it and what the
#: CLI shows. Both are accepted as a `fray tasks` argument.
DISPLAY_NAMES = {"Extra": "Other"}

_MARKED_SPAN = re.compile(r"~\|([^|]*)\|~")
_UNGROUPED = "Ungrouped"


def display_name(category: str) -> str:
    """`Extra` -> `Other`; every other category is its own name."""
    return DISPLAY_NAMES.get(category, category)


def _diary_group(name: str, challenge: Mapping[str, Any]) -> str:
    """`~|Morytania Diary#Elite|~ Task 5` -> `Morytania Diary - Elite`.

    The tier lives inside the marked span, after a `#`. Falls back to
    `BaseQuest` when a name carries no tier (the tier-completion challenges
    do carry one, so this is mostly the odd malformed entry).
    """
    match = _MARKED_SPAN.search(name)
    if match is not None:
        base, _, tier = match.group(1).partition("#")
        if tier:
            return f"{base} - {tier}"
        if base:
            return base
    base_quest = challenge.get("BaseQuest")
    return base_quest if isinstance(base_quest, str) else _UNGROUPED


def group_of(category: str, name: str, challenge: Mapping[str, Any]) -> str:
    """Which display group a challenge belongs to, per category."""
    if category == "Diary":
        return _diary_group(name, challenge)
    key = "Label" if category == "Extra" else "BaseQuest"
    value = challenge.get(key)
    return value if isinstance(value, str) and value else _UNGROUPED


def task_text(name: str, challenge: Mapping[str, Any]) -> str:
    """What to show for one task: its `Description` when the export has one
    (Quest and Diary do, `Extra` doesn't), else the markup-stripped name."""
    description = challenge.get("Description")
    if isinstance(description, str) and description:
        return description
    return strip_task_markup(name)


@dataclass(frozen=True)
class TaskGroup:
    """One display group's tasks, each list sorted by `task_text`."""

    name: str
    active: tuple[str, ...] = ()
    completed: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "active": list(self.active), "completed": list(self.completed)}


@dataclass(frozen=True)
class CategoryTasks:
    """One category's groups, plus its totals. `active` counts every valid,
    uncompleted, unbacklogged challenge - not a single pick."""

    category: str
    groups: tuple[TaskGroup, ...] = ()
    active_total: int = 0
    completed_total: int = 0
    #: Completed names ticked off during the chunk in play. Upstream's panel
    #: would still list these as active, so its own count is
    #: `active_total + len(current_chunk)`.
    current_chunk: frozenset[str] = frozenset()

    @property
    def label(self) -> str:
        return display_name(self.category)

    def completed_text(self, name: str, challenge: Mapping[str, Any]) -> str:
        """`task_text` plus the current-chunk marker where it applies."""
        text = task_text(name, challenge)
        return f"{text} {CURRENT_CHUNK_SUFFIX}" if name in self.current_chunk else text

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "label": self.label,
            "active_total": self.active_total,
            "completed_total": self.completed_total,
            "current_chunk": sorted(self.current_chunk),
            "groups": [group.as_dict() for group in self.groups],
        }


@dataclass(frozen=True)
class OtherTasks:
    """`categories` is keyed by the export's own name (`Extra`, not `Other`),
    matching `ChallengeResult.valid` and `--export-json`."""

    categories: dict[str, CategoryTasks] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {name: tasks.as_dict() for name, tasks in self.categories.items()}


#: Categories whose `Tasks` edges prove their prerequisites were done, rather
#: than merely stating a requirement. `Quest` because a quest is a step chain;
#: `Diary` only from a *tier completion* (see `_implies_from`).
_CHAINED_CATEGORIES = frozenset({"Quest", "Diary"})

#: `Quest` supersession (`_superseded`) is a chain property and applies to
#: quests alone - a diary tier's tasks are independent of one another, so
#: reaching one says nothing about the rest.
_SUPERSEDING_CATEGORIES = frozenset({"Quest"})


def _implies_from(category: str, challenge: Mapping[str, Any]) -> bool:
    """May completing `challenge` be taken as proof of its `Tasks`?

    For `Quest`, always: the steps form a chain. For `Diary`, only from a
    *tier completion* - the challenges carrying a `Reward`, whose `Tasks` list
    every task in that tier. Completing the Easy diary proves all eleven of
    its tasks; completing one ordinary diary task proves nothing about the
    others, and its own `Tasks` are ordinary requirements (a quest, or the
    previous tier) rather than steps it must have walked through.
    """
    if category == "Diary":
        return "Reward" in challenge
    return True


def _implied_completions(
    category: str, completed: Mapping[str, Any], challenges: Mapping[str, Any]
) -> frozenset[str]:
    """Prerequisite steps a recorded completion implies, transitively.

    A quest is a chain: `~|Gertrude's Cat|~ Complete the quest` requires step
    7, which requires 6, and so on to 1. Ticking a quest off records only the
    final entry, so all seven steps stayed "active" here while the quest was
    demonstrably finished - the bulk of the Quest category's noise.

    `Diary` gets the same treatment from a *tier completion* only
    (`_implies_from`): `~|Morytania Diary#Easy|~ Complete the Easy Diary`
    lists all eleven Easy tasks and is itself recorded, so all eleven are
    done - real data had ten of them marked individually and left `Task 8`
    looking outstanding. Recursion through tier completions carries earlier
    tiers along, since each tier's completion requires the one below it.

    Only edges that stay inside the category are followed. Across categories a
    `Tasks` entry is an ordinary requirement, and inferring completion from
    one would be inventing history rather than reading it.
    """
    if category not in _CHAINED_CATEGORIES:
        return frozenset()
    implied: set[str] = set()
    pending = [name for name in completed]
    while pending:
        name = pending.pop()
        challenge = challenges.get(name)
        if not isinstance(challenge, dict) or not _implies_from(category, challenge):
            continue
        tasks = challenge.get("Tasks")
        if not isinstance(tasks, dict):
            continue
        for prerequisite, task_category in tasks.items():
            if task_category != category or prerequisite in completed or prerequisite in implied:
                continue
            implied.add(prerequisite)
            pending.append(prerequisite)
    return frozenset(implied)


def _plus_members(chunk_info: ChunkInfo, name: str) -> tuple[str, ...] | None:
    """`codeItems.tasksPlus` members of a `[+]` / `[+]xN` family name."""
    if "[+]" not in name:
        return None
    # `subTask.split('[+]x')[0].replaceAll('[+]', '') + '[+]'` - the existing
    # `[+]` has to come off before one is appended, or a plain `X[+]` name
    # looks up as `X[+][+]` and silently finds nothing.
    family = name.split("[+]x")[0].replace("[+]", "") + "[+]"
    members = (chunk_info.code_items.get("tasksPlus") or {}).get(family)
    return tuple(m for m in members if isinstance(m, str)) if isinstance(members, list) else None


def _prerequisites(
    category: str,
    name: str,
    challenges: Mapping[str, Any],
    chunk_info: ChunkInfo,
    base_quest: Any,
) -> list[str]:
    """The same-quest steps `name` depends on, `[+]` families expanded.

    Upstream marks *every* member of a family, not one (worker.js:498/512) -
    `~|Shield of Arrav|~ 3` needs `ShieldOfArrav2Final[+]`, i.e. the last step
    of either route, and reaching it means whichever route you took is behind
    you. The `BaseQuest` match is upstream's own guard against a dependency
    on an unrelated quest dragging that quest's steps in with it.
    """
    challenge = challenges.get(name)
    tasks = challenge.get("Tasks") if isinstance(challenge, dict) else None
    if not isinstance(tasks, dict):
        return []
    found: list[str] = []
    for raw, task_category in tasks.items():
        if task_category != category:
            continue
        members = _plus_members(chunk_info, raw)
        for candidate in members if members is not None else (raw,):
            step = candidate.split("--")[0]
            other = challenges.get(step)
            if isinstance(other, dict) and other.get("BaseQuest") == base_quest:
                found.append(step)
    return found


def _superseded(
    category: str,
    valid_names: Mapping[str, Any],
    challenges: Mapping[str, Any],
    chunk_info: ChunkInfo,
) -> frozenset[str]:
    """Steps a *reachable* later step has left behind - port of
    `markSubTasks(..., false)` (worker.js:485, called at :1486 for every
    fully-valid challenge).

    Being able to do step 4 means steps 1-3 are behind you whether or not
    anything recorded them, so upstream sets each prerequisite's valid value
    to `false` and the panel's `&& globalValids['Quest'][challenge]` guard
    then hides it. Only the furthest reachable step of a quest shows.

    Computed as a set here rather than by writing `false` into
    `ChallengeResult.valid`: validity means "requirements met" everywhere
    else in this project, and `unlock.py`/`simulate.py` diff that mapping.
    """
    if category not in _SUPERSEDING_CATEGORIES:
        return frozenset()
    superseded: set[str] = set()
    pending = list(valid_names)
    while pending:
        name = pending.pop()
        challenge = challenges.get(name)
        base_quest = challenge.get("BaseQuest") if isinstance(challenge, dict) else None
        if base_quest is None:
            continue
        for step in _prerequisites(category, name, challenges, chunk_info, base_quest):
            if step not in superseded:
                superseded.add(step)
                pending.append(step)
    return frozenset(superseded)


def _classify_category(
    category: str,
    valid_names: Mapping[str, Any],
    challenges: Mapping[str, Any],
    chunk_info: ChunkInfo,
    *,
    completed: Mapping[str, Any],
    checked: Mapping[str, Any],
    backlog: Mapping[str, Any],
) -> CategoryTasks:
    implied = _implied_completions(category, completed, challenges)
    # `completed` is the merged view, so this drops what was ticked this chunk
    # as well - those move to `completed` with a marker rather than staying
    # active. See the module docstring.
    done = frozenset(completed) | implied
    superseded = _superseded(category, valid_names, challenges, chunk_info)
    active = [
        name
        for name in valid_names
        if name not in superseded
        and not _recorded(name, done)
        and not _recorded(name, backlog)
    ]
    completed_names = [*completed, *sorted(implied)]
    current_chunk = frozenset(checked) & frozenset(completed_names)

    grouped: dict[str, tuple[list[str], list[str]]] = {}

    def bucket(name: str) -> tuple[list[str], list[str]]:
        challenge = challenges.get(name)
        challenge = challenge if isinstance(challenge, dict) else {}
        return grouped.setdefault(group_of(category, name, challenge), ([], []))

    for name in active:
        bucket(name)[0].append(name)
    for name in completed_names:
        bucket(name)[1].append(name)

    def sort_key(name: str) -> str:
        challenge = challenges.get(name)
        return task_text(name, challenge if isinstance(challenge, dict) else {})

    def completed_key(name: str) -> tuple[bool, str]:
        return (name not in current_chunk, sort_key(name))

    built = [
        TaskGroup(
            name=group_name,
            active=tuple(sorted(members[0], key=sort_key)),
            completed=tuple(sorted(members[1], key=completed_key)),
        )
        for group_name, members in sorted(grouped.items())
    ]
    # A group holding this chunk's work sorts to the front of the category,
    # so "ticked just now" is the first thing the completed listing shows.
    groups = tuple(
        sorted(built, key=lambda g: (not (current_chunk & set(g.completed)), g.name))
    )
    return CategoryTasks(
        category=category,
        groups=groups,
        active_total=len(active),
        completed_total=len(completed_names),
        current_chunk=current_chunk,
    )


def classify_other_tasks(
    valid: Mapping[str, Mapping[str, Any]],
    chunk_info: ChunkInfo,
    *,
    completed_challenges: Mapping[str, Mapping[str, Any]],
    checked_challenges: Mapping[str, Mapping[str, Any]],
    backlog: Mapping[str, Mapping[str, Any]],
) -> OtherTasks:
    """Group `CATEGORIES` into their display groups.

    `completed_challenges` is the merged view (`MapState.completed_challenges`)
    and `checked_challenges` its ticked-this-chunk half; the two together
    reconstruct the stored branch the panel actually filters on.
    """
    challenges = chunk_info.challenges
    categories = {
        category: _classify_category(
            category,
            valid.get(category) or {},
            challenges.get(category) or {},
            chunk_info,
            completed=completed_challenges.get(category) or {},
            checked=checked_challenges.get(category) or {},
            backlog=backlog.get(category) or {},
        )
        for category in CATEGORIES
    }
    return OtherTasks(categories=categories)
