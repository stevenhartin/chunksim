"""Group the non-skill task categories: Quest, Diary and Extra ("Other").

These three work nothing like the skill categories `active_tasks.py` handles,
which is why they get their own module. `calcCurrentChallenges2` **excludes**
`Extra`/`Quest`/`Diary`/`BiS` from its per-skill loop outright
(worker.js:8390), so there is no single highest-level winner to compute:
upstream's panel renders *every* valid challenge in the category that isn't
completed or backlogged (index.js:6702/6744/6767), grouped for display.

Two details of that guard matter, and both were wrong here before:

- It tests `completedChallenges` **alone** (index.js:6745). A task merely
  ticked this chunk still renders, just with its checkbox set
  (index.js:6663), so the merged `MapState.completed_challenges` is the wrong
  view - it hid 9 `Extra` entries the map's own `activeTasks` oracle lists.
  `_committed` reconstructs the stored branch by removing
  `checked_challenges`, which is exact because upstream migrates the checked
  set into `completedChallenges` and clears it in one step
  (`completeChallenges`, index.js:12718) - the two are never both populated
  for the same task.
- Completions are reported whether or not the challenge is still valid, the
  same rule `active_tasks.py` follows: a requirement added by a later game
  update must not erase the fact that the task was done.

`Quest` additionally closes its completions transitively
(`_implied_completions`): a quest is a step chain and ticking it off records
only `~|X|~ Complete the quest`, so every prerequisite reachable through
`Tasks` counts as done as well.

Grouping mirrors the panel's own: `Quest` by `BaseQuest`; `Diary` by the
diary and tier encoded in the name (`~|Morytania Diary#Elite|~ Task 5` ->
*Morytania Diary - Elite*); `Extra` by its `Label` field, whose values are
exactly the user-facing groups - `Collection Log`, `Permanent Unlockables`,
`Untracked Uniques`, plus `Fill POH`/`Fill Stashes`/`BIS Skilling`/
`Stuffables` when their rules are on. Which labels appear is already handled
upstream of here: `challenges._category_gate_met` drops a challenge whose
`Category` names a rule that is off.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from fray_claude.active_tasks import _recorded
from fray_claude.challenges import strip_task_markup
from fray_claude.chunkinfo import ChunkInfo

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

    @property
    def label(self) -> str:
        return display_name(self.category)

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "label": self.label,
            "active_total": self.active_total,
            "completed_total": self.completed_total,
            "groups": [group.as_dict() for group in self.groups],
        }


@dataclass(frozen=True)
class OtherTasks:
    """`categories` is keyed by the export's own name (`Extra`, not `Other`),
    matching `ChallengeResult.valid` and `--export-json`."""

    categories: dict[str, CategoryTasks] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {name: tasks.as_dict() for name, tasks in self.categories.items()}


#: Categories whose `Tasks` edges form a *step chain* rather than general
#: requirements, so completing a later step proves every earlier one.
_CHAINED_CATEGORIES = frozenset({"Quest"})


def _implied_completions(
    category: str, completed: Mapping[str, Any], challenges: Mapping[str, Any]
) -> frozenset[str]:
    """Prerequisite steps a recorded completion implies, transitively.

    A quest is a chain: `~|Gertrude's Cat|~ Complete the quest` requires step
    7, which requires 6, and so on to 1. Ticking a quest off records only the
    final entry, so all seven steps stayed "active" here while the quest was
    demonstrably finished - the bulk of the Quest category's noise.

    Only `Quest` gets this (`_CHAINED_CATEGORIES`), and only along edges that
    stay inside the category. Elsewhere a `Tasks` entry is an ordinary
    requirement - a `Diary` task needing a quest done says nothing about the
    diary task itself - and inferring completion across that would be
    inventing history rather than reading it.
    """
    if category not in _CHAINED_CATEGORIES:
        return frozenset()
    implied: set[str] = set()
    pending = [name for name in completed]
    while pending:
        name = pending.pop()
        challenge = challenges.get(name)
        if not isinstance(challenge, dict):
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


def _committed(
    completed: Mapping[str, Any], checked: Mapping[str, Any]
) -> frozenset[str]:
    """The stored `completedChallenges` branch, i.e. the merged view less what
    is only ticked this chunk. See the module docstring for why the panel
    keys off this rather than the merged set."""
    return frozenset(completed) - frozenset(checked)


def _classify_category(
    category: str,
    valid_names: Mapping[str, Any],
    challenges: Mapping[str, Any],
    *,
    completed: Mapping[str, Any],
    checked: Mapping[str, Any],
    backlog: Mapping[str, Any],
) -> CategoryTasks:
    implied = _implied_completions(category, completed, challenges)
    committed = _committed(completed, checked) | implied
    active = [
        name
        for name in valid_names
        if not _recorded(name, committed) and not _recorded(name, backlog)
    ]
    completed_names = [*completed, *sorted(implied)]

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

    groups = tuple(
        TaskGroup(
            name=group_name,
            active=tuple(sorted(members[0], key=sort_key)),
            completed=tuple(sorted(members[1], key=sort_key)),
        )
        for group_name, members in sorted(grouped.items())
    )
    return CategoryTasks(
        category=category,
        groups=groups,
        active_total=len(active),
        completed_total=len(completed_names),
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
            completed=completed_challenges.get(category) or {},
            checked=checked_challenges.get(category) or {},
            backlog=backlog.get(category) or {},
        )
        for category in CATEGORIES
    }
    return OtherTasks(categories=categories)
