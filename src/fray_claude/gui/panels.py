"""Shaping a `Derived` into what the panel draws. Pure.

**The panel needs one shape, and `Derived` offers five.** `bis` is a flat
dict of task name to slot label; `task_classification` is 21 skills each with
one active pick; `other_tasks` is three categories of groups already carrying
`active`/`completed`. Rendering those five differently is how the first
version of the tasks tab ended up printing `active_total` and `groups` as if
they were task names - it walked `Object.keys` over a category envelope. So
everything here lands in one envelope:

    Panel  -> sections[]        one per heading: bis, skills, Diary, ...
    Section-> groups[]          one per sub-heading
    Group  -> active[]/completed[]  of Entry

and `Entry` is always `{key, name, note, icon}`: `key` the raw
markup-bearing string everything else is keyed by, `name` the part worth
reading, `note` the part worth reading second. **That split is the whole
point** - "Melee BiS weapon" and "abyssal whip" are not equally important,
and neither are "Barrows Chests" and "dharok's greataxe".

Three category-specific rules, each of which is domain knowledge rather than
formatting, which is why this is a module and not a template:

- **A quest is a chain, so only its furthest step means anything.** The
  *active* side is already the frontier - `other_tasks._superseded` ports
  upstream's `markSubTasks` and hides every step you can see past - but the
  *completed* side lists all of them, and "Cook's Assistant 1, 2a, 2b, 2c, 3,
  Complete the quest" is six rows saying one thing. Both sides are reduced to
  their furthest step by `_step_order`, and a quest with an active step is
  **not** also listed as completed: it is in progress, and saying so twice in
  two places is how a list stops being scannable.
- **`Extra`'s collection-log entries carry their source in parentheses**, and
  that source is the useful half - "(Barrows Chests) Obtain a
  ~|dharok's greataxe|~" is really *Barrows Chests* / *dharok's greataxe*.
- **BiS groups by combat style**, which is what its slot labels encode
  (`Melee BiS weapon`, `Ranged/<zwsp>Magic BiS ring`). Grouping by slot
  instead would put a shared cape in four groups or none.

`strip_task_markup` is display-only and `key` keeps the raw form, so nothing
downstream loses the thing it looks tasks up by.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from fray_claude.derive.task_names import strip_task_markup
from fray_claude.derive.pipeline import Derived
from fray_claude.model.summary import _mapping

#: A quest step token, split so `2c10` sorts after `2c4` rather than before
#: it. Purely lexical: `10` beats `4` only once the digits are read as a
#: number, which is the one thing a plain sort cannot do.
_STEP_CHUNK = re.compile(r"(\d+)")

#: The step every quest ends on. Sorts last by construction rather than by
#: luck - it is a sentence, and sentences do not compare usefully against
#: `2c4`.
_FINAL_STEP = "complete the quest"

#: `(Source) Obtain a ~|thing|~` - the collection-log shape. The source is
#: what the parenthesis holds and the item is what the markup holds; the verb
#: between them says nothing a reader needs.
_LOG_ENTRY = re.compile(r"^\((?P<source>[^)]+)\)\s*(?P<rest>.*)$")

#: The markup a task name wraps its subject in. `challenges.strip_task_markup`
#: removes it; this one *extracts* it, which is what turns "Obtain an
#: ~|abyssal whip|~" into "abyssal whip".
_MARKED = re.compile(r"~\|(?P<subject>[^|]+)\|~")

#: `Melee BiS weapon` -> `Melee`. The zero-width space is upstream's own, put
#: between styles so `Ranged/Magic` wraps; it is invisible and must not become
#: part of a group name.
_ZWSP = "​"


def _entry(
    key: str,
    name: str,
    note: str | None = None,
    icon: str | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    """One row. `category` is which `completedChallenges` branch it lives in.

    **Not the same thing as the section it is drawn under.** The panel's five
    sections are a reading order - all 21 skills share one, because a skill
    contributes at most one active task and 21 headings would be 21 lists of
    one - where the payload keys ticks by challenge category, one per skill.
    The GUI's edit mode writes a tick, so it needs the payload's answer rather
    than the panel's, and the row is the only place both are known.
    """
    return {"key": key, "name": name, "note": note, "icon": icon, "category": category}


def _group(name: str, active: Sequence[Any], completed: Sequence[Any]) -> dict[str, Any]:
    return {"name": name, "active": list(active), "completed": list(completed)}


def _section(
    key: str, label: str, groups: Sequence[Any], *, icon: str | None = None
) -> dict[str, Any]:
    """One heading, with its totals counted here so nothing has to re-add them."""
    return {
        "key": key,
        "label": label,
        "icon": icon,
        "groups": [g for g in groups if g["active"] or g["completed"]],
        "active_total": sum(len(g["active"]) for g in groups),
        "completed_total": sum(len(g["completed"]) for g in groups),
    }


def _subject(name: str) -> str:
    """The marked-up subject of a task name, or the whole name without markup.

    A task is usually a sentence about one thing - "Obtain an ~|abyssal
    whip|~" - and the thing is what belongs in the column you read down. When
    there is no markup the sentence *is* the subject ("Buy a Player-owned
    house" has its own), so it is returned whole rather than blanked.
    """
    found = _MARKED.search(name)
    return found.group("subject") if found else strip_task_markup(name)


def _step_order(step: str) -> tuple[int, list[Any]]:
    """Sort key for a quest step: `1 < 2a < 2c4 < 2c10 < 3 < Complete the quest`.

    Two tiers, because the final step is not comparable with the numbered
    ones. Within the numbered tier, digit runs compare as numbers and the rest
    as text, which is what makes `2c10` follow `2c4`.
    """
    if step.strip().lower() == _FINAL_STEP:
        return (1, [])
    parts: list[Any] = []
    for piece in _STEP_CHUNK.split(step):
        if piece.isdigit():
            parts.append((0, int(piece)))
        elif piece:
            parts.append((1, piece))
    return (0, parts)


def _quest_step(name: str, quest: str) -> str:
    """The step half of `~|Cook's Assistant|~ 2b`, given the quest's own name."""
    plain = strip_task_markup(name)
    return plain.removeprefix(quest).strip() or plain


def _furthest(names: Iterable[str], quest: str) -> str | None:
    """The last step of a quest chain, or `None` if there are none."""
    ordered = sorted(names, key=lambda n: _step_order(_quest_step(n, quest)))
    return ordered[-1] if ordered else None


def _quest_groups(category: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One row per quest, carrying only the step that is actually the answer."""
    active: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    for group in category.get("groups", []):
        quest = str(group.get("name", ""))
        furthest_active = _furthest(group.get("active", ()), quest)
        if furthest_active is not None:
            active.append(
                _entry(furthest_active, quest, _quest_step(furthest_active, quest))
            )
            # In progress, so not also done. See the module docstring.
            continue
        furthest_done = _furthest(group.get("completed", ()), quest)
        if furthest_done is not None:
            completed.append(_entry(furthest_done, quest, _quest_step(furthest_done, quest)))
    return [_group("Quests", active, completed)]


def _extra_entry(name: str) -> dict[str, Any]:
    """A collection-log row split into its source and its item, or left whole."""
    found = _LOG_ENTRY.match(name)
    if found is None:
        return _entry(name, strip_task_markup(name))
    return _entry(name, _subject(found.group("rest")), found.group("source"))


def _plain_groups(
    category: Mapping[str, Any], *, split_sources: bool = False
) -> list[dict[str, Any]]:
    """`Diary` and `Extra`: upstream's own groups, entries formatted per row."""
    shape = _extra_entry if split_sources else (lambda n: _entry(n, strip_task_markup(n)))
    return [
        _group(
            str(group.get("name", "")),
            [shape(name) for name in group.get("active", ())],
            [shape(name) for name in group.get("completed", ())],
        )
        for group in category.get("groups", [])
    ]


def _bis_style(slot_label: str) -> str:
    """`Melee BiS weapon` -> `Melee`; anything worn by several styles -> `Shared`.

    A Hitpoints cape is `Melee/<zwsp>Ranged/<zwsp>Magic/<zwsp>Prayer BiS cape`,
    and the real map has four such labels holding one item each. Kept
    verbatim they are four headings that say "this works for everything" four
    different ways; collapsed, they are the group that means exactly that.
    """
    head = slot_label.split(" BiS ")[0].replace(_ZWSP, "")
    if not head:
        return slot_label
    return "Shared" if "/" in head else head


def _bis_groups(bis: Mapping[str, Any]) -> list[dict[str, Any]]:
    """BiS by combat style, each row *item first* and slot second.

    `bis.slots` gives the bare slot (`weapon`), which is what the note wants -
    the style is already the heading, so repeating it in every row would say
    it three times.
    """
    slots = _mapping(bis, "slots")
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for state in ("active", "completed"):
        for key, label in sorted(_mapping(bis, state).items()):
            style = _bis_style(str(label))
            note = str(slots.get(key) or label)
            grouped.setdefault(style, {"active": [], "completed": []})[state].append(
                _entry(key, _subject(key), note, category="BiS")
            )
    return [_group(style, rows["active"], rows["completed"]) for style, rows in sorted(grouped.items())]


def _skill_groups(classification: Mapping[str, Any]) -> list[dict[str, Any]]:
    """All 21 skills as **one** list, each row labelled by its skill's icon.

    One group rather than 21 headings: a skill contributes at most one active
    task, so 21 headings would be 21 sub-lists of one - and the question the
    panel answers is "what am I doing next", which is a single list.
    `obsolete` is deliberately dropped; it is what a *previous* chunk wanted.
    """
    active: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    for skill, entry in sorted(classification.items()):
        current = entry.get("active")
        if isinstance(current, str) and current:
            active.append(_entry(current, _subject(current), skill, icon=skill, category=skill))
        for done in entry.get("completed", ()):
            completed.append(_entry(done, _subject(done), skill, icon=skill, category=skill))
    return [_group("Skills", active, completed)]


def _with_category(groups: Sequence[Any], category: str) -> list[dict[str, Any]]:
    """Every row in `groups` given `category`, where it has none."""
    return [
        {
            **group,
            "active": [{**row, "category": row.get("category") or category} for row in group["active"]],
            "completed": [
                {**row, "category": row.get("category") or category} for row in group["completed"]
            ],
        }
        for group in groups
    ]


def task_panel(derived: Derived) -> dict[str, Any]:
    """Every task the panel shows, in one shape.

    Ordered as the panel reads: what you are training now, what you are
    hunting, then the three long-tail categories. `valid` is deliberately
    absent - it is 2,700 entries meaning "the requirements are met", which is
    not a to-do list and drowns one if put in the same panel.
    """
    other = derived.other_tasks.as_dict()
    sections = [
        _section("skills", "Skills", _skill_groups(derived.task_classification.as_dict())),
        _section("bis", "Best in slot", _bis_groups(derived.bis.as_dict())),
    ]
    for key, label, groups in (
        ("Diary", "Diaries", _plain_groups(_mapping(other, "Diary"))),
        ("Quest", "Quests", _quest_groups(_mapping(other, "Quest"))),
        ("Extra", "Other", _plain_groups(_mapping(other, "Extra"), split_sources=True)),
    ):
        # These three are the one case where the section key *is* the payload's
        # category, so it is stamped here rather than threaded through two
        # group builders that have no other use for it.
        sections.append(_section(key, label, _with_category(groups, key)))
    return {"sections": sections}


__all__ = ["task_panel"]
