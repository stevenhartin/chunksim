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
from fray_claude.derive.other_tasks import CATEGORIES, group_of
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

#: The tiers a diary-like group can end in, hardest last. Two ladders share
#: this list because they are the same shape and never collide: achievement
#: diaries run Easy -> Elite, Combat Achievements Easy -> Grandmaster. Sorting
#: alphabetically put Elite before Hard and Grandmaster before Master, which
#: is every tier out of order in a list whose whole meaning is its order.
_TIERS: tuple[str, ...] = (
    "easy", "medium", "hard", "elite", "expert", "master", "grandmaster",
)

#: The badge each Combat Achievement tier draws, served by `/assets/ca/`.
#: Diaries have no equivalent - the wiki draws them as plain text - so a
#: non-CA group keeps the diary icon its section already carries.
_CA_GROUP = "Combat Achievements"


def _tier_of(group: str) -> str:
    """The tier a group name ends in, lower-cased, or `""` if it has none.

    Group names arrive as `<ladder> - <tier>`, which is upstream's own `#`
    separator rendered by `other_tasks`. Read off the end rather than parsed,
    because a diary's name can hold anything at all before it (`Lumbridge and
    Draynor Diary`).
    """
    tail = group.rsplit(" - ", 1)[-1].strip().lower()
    return tail if tail in _TIERS else ""


def _group_sort(group: Mapping[str, Any]) -> tuple[str, int, str]:
    """Ladder first, then tier in difficulty order, then name.

    The ladder is the part before the tier, so every `Varrock Diary` tier sits
    together and reads Easy to Elite - which is the order the game unlocks
    them in and the only order the list means anything in.
    """
    name = str(group.get("name", ""))
    tier = _tier_of(name)
    ladder = name.rsplit(" - ", 1)[0] if tier else name
    return (ladder, _TIERS.index(tier) if tier else len(_TIERS), name)


def _display_name(name: str) -> str:
    """A task name as a column of them should read.

    Two things, and the second is deliberately conservative. The raw form
    keeps upstream's `<group>#<tier>` prefix - `Combat Achievements#Grandmaster
    Wasn't Event Close` - which is the heading repeated in every row under it,
    so it comes off. And the first character is capitalised, because the export
    writes `unholy symbol` beside `Falador shield 1` and a column that starts
    in two cases reads as two lists.

    **Only the first character.** Lower-casing the rest would be the way to
    make the whole string consistent and it destroys the names it touches:
    `TzHaar-Hur`, `Ardougne`, `BiS`. Title-casing them is worse the other way.
    So this makes the *column* consistent and leaves the words as upstream
    wrote them, which is the split `strip_task_markup` already draws between
    display and identity.
    """
    plain = strip_task_markup(name)
    head, sep, tail = plain.partition("#")
    if sep:
        # `Combat Achievements#Grandmaster Wasn't Event Close` -> the part
        # after the tier. The tier is one word, so one split does it.
        rest = tail.split(" ", 1)
        plain = rest[1] if len(rest) > 1 else tail
    return plain[:1].upper() + plain[1:] if plain else plain


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
    """One sub-heading. `icon` is set only where something knows one - a
    Combat Achievement tier badge - and stays `None` everywhere else rather
    than the panel guessing from the name."""
    return {"name": name, "active": list(active), "completed": list(completed), "icon": None}


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


def _cased(name: str) -> str:
    """First character up, the rest exactly as the export wrote it. See
    `_display_name` for why the rest is left alone."""
    return name[:1].upper() + name[1:] if name else name


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
        return _entry(name, _display_name(name))
    return _entry(name, _cased(_subject(found.group("rest"))), found.group("source"))


def _plain_groups(
    category: Mapping[str, Any], *, split_sources: bool = False, tiered: bool = False
) -> list[dict[str, Any]]:
    """`Diary` and `Extra`: upstream's own groups, entries formatted per row.

    `tiered` sorts the groups by difficulty and hands each one its Combat
    Achievement badge - both facts about a ladder rather than about a list, so
    `Extra` asks for neither.
    """
    shape = _extra_entry if split_sources else (lambda n: _entry(n, _display_name(n)))
    groups = [
        _group(
            str(group.get("name", "")),
            [shape(name) for name in group.get("active", ())],
            [shape(name) for name in group.get("completed", ())],
        )
        for group in category.get("groups", [])
    ]
    if not tiered:
        return groups
    groups.sort(key=_group_sort)
    for group in groups:
        tier = _tier_of(group["name"])
        if tier and group["name"].startswith(_CA_GROUP):
            group["icon"] = "ca:" + tier
    return groups


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
                _entry(key, _cased(_subject(key)), note, category="BiS")
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
            active.append(
                _entry(current, _cased(_subject(current)), skill, icon=skill, category=skill)
            )
        for done in entry.get("completed", ()):
            completed.append(
                _entry(done, _cased(_subject(done)), skill, icon=skill, category=skill)
            )
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


#: A roll's ledger records a challenge's *value* beside its name, which is
#: `challenges._challenge_value`: the `Level` for a skill task, the `Label` for
#: an `Extra` one, and `True` for the rest. That is exactly the two things the
#: shaping below needs - which skill task is furthest, and which `Extra` group
#: a row belongs to - so a roll can be shaped without the 10MB export.
_SKILL_EXCLUDED = frozenset({*CATEGORIES, "Nonskill", "BiS"})


def _roll_level(value: Any) -> float | None:
    """A ledger value read as a level, or `None` where the challenge has none.

    The two are different answers and collapsing them was a bug: a task with
    no `Level` is not a task at level 0, it is a task with **no ladder** - so
    nothing can be ahead of it and `surpassed` must not filter it out.
    `_highest_completed_level` draws the same distinction from the other side,
    where a levelless completion proves nothing.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _roll_classification(
    added: Mapping[str, Any], surpassed: Mapping[str, float]
) -> dict[str, Any]:
    """`task_classification`'s shape, over one roll's additions.

    **One task per skill, the furthest one, and only if it is further than
    what you already had.** Two rules, and the overlay had neither.

    The first is upstream's display rule and the whole reason the Tasks tab is
    readable: unlocking a Construction chunk opens sixty build tasks and you
    care about the one at the top.

    The second is what makes a roll's list mean "news". A Crafting chunk opens
    `Cook a ~|cup of tea (porcelain)|~` at Cooking 20, and on a map that has
    already ticked the 99 Cooking cape that is not a Cooking goal - the Tasks
    tab does not show it, because `active_tasks` gates candidacy on the
    highest level among a skill's *completed* challenges. `surpassed` is that
    ceiling per skill, carrying the run's own earlier rolls as well; see
    `routes_view.roll_baseline`. A skill whose whole addition sits under it
    contributes nothing rather than a row nobody wanted.

    Ties break on the name so two additions at the same level cannot make the
    answer depend on dictionary order.
    """
    classified: dict[str, Any] = {}
    for category, tasks in added.items():
        if category in _SKILL_EXCLUDED or not isinstance(tasks, dict) or not tasks:
            continue
        ceiling = surpassed.get(category, 0.0)
        better = [
            item for item in tasks.items()
            if (_roll_level(item[1]) or 0.0) > ceiling or _roll_level(item[1]) is None
        ]
        if not better:
            continue
        winner = max(better, key=lambda item: (_roll_level(item[1]) or 0.0, item[0]))
        classified[category] = {"active": winner[0], "completed": []}
    return classified


def _roll_challenge(category: str, name: str, value: Any) -> dict[str, Any]:
    """The two export fields `group_of` reads, recovered from the ledger.

    `Extra`'s group *is* its `Label`, which the ledger already carries as the
    value; a quest's is its `BaseQuest`, which is the name's own marked span;
    and a diary tier's comes out of the name unaided. So the export's own
    grouping function does the work here rather than a second copy of it.
    """
    if category == "Extra":
        return {"Label": value} if isinstance(value, str) else {}
    if category == "Quest":
        return {"BaseQuest": _subject(name)}
    return {}


def _roll_category(added: Mapping[str, Any], category: str) -> dict[str, Any]:
    """`other_tasks`' category shape, over one roll's additions."""
    tasks = added.get(category)
    grouped: dict[str, list[str]] = {}
    for name, value in (tasks or {}).items():
        if isinstance(name, str):
            grouped.setdefault(
                group_of(category, name, _roll_challenge(category, name, value)), []
            ).append(name)
    return {
        "groups": [
            {"name": group, "active": sorted(names), "completed": []}
            for group, names in sorted(grouped.items())
        ]
    }


def _roll_bis(upgrades: Mapping[str, Any]) -> dict[str, Any]:
    """`bis.as_dict()`'s shape, over one roll's upgrades.

    The ledger keys them `<style>-<slot>` and records what each replaced;
    `_bis_groups` wants the label upstream writes (`Melee BiS shield`) and the
    bare slot beside it, which is the same pair spelled differently.
    """
    active: dict[str, str] = {}
    slots: dict[str, str] = {}
    for key, change in upgrades.items():
        gained = change.get("new") if isinstance(change, dict) else None
        style, _, slot = str(key).partition("-")
        if not isinstance(gained, str) or not slot:
            continue
        active[gained] = f"{style} BiS {slot}"
        slots[gained] = slot
    return {"active": active, "completed": {}, "slots": slots}


def roll_panel(
    record: Mapping[str, Any], surpassed: Mapping[str, float] = {}
) -> dict[str, Any]:
    """What one roll opened, in `task_panel`'s exact shape.

    **The same rules, over a filtered list.** The overlay used to render the
    ledger raw - every new task, flat, one heading per skill - which made it a
    different interface answering the same question two panes away: a
    Construction chunk listed sixty builds where the Tasks tab shows the
    furthest one, and `Combat Achievements#Grandmaster Wasn't Event Close`
    kept a prefix the tab drops.

    Nothing here re-implements those rules; it reconstructs the *inputs* the
    panel's own builders take and calls them. That is possible without the
    10MB export because the ledger records each challenge's value alongside
    its name - see `_SKILL_EXCLUDED` - which is what keeps `/api/roll` at a
    millisecond.

    `surpassed` is the level each skill had already reached before this roll,
    and a skill task at or below it is not news - see `_roll_classification`.
    Only skills have it: a quest step, a diary task and a collection-log row
    are each their own thing, with no ladder to be behind on.

    `Nonskill` is dropped, as the Tasks tab drops it: `other_tasks.CATEGORIES`
    is `Diary`/`Quest`/`Extra`, so there is no section for it to land in and
    inventing one here would be the inconsistency this replaces.
    """
    added = _mapping(record, "new_tasks")
    sections = [
        _section("skills", "Skills", _skill_groups(_roll_classification(added, surpassed))),
        _section("bis", "Best in slot", _bis_groups(_roll_bis(_mapping(record, "bis_upgrades")))),
    ]
    for key, label, groups in (
        ("Diary", "Diaries", _plain_groups(_roll_category(added, "Diary"), tiered=True)),
        ("Quest", "Quests", _quest_groups(_roll_category(added, "Quest"))),
        ("Extra", "Other", _plain_groups(_roll_category(added, "Extra"), split_sources=True)),
    ):
        sections.append(_section(key, label, _with_category(groups, key)))
    return {"sections": sections}


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
        ("Diary", "Diaries", _plain_groups(_mapping(other, "Diary"), tiered=True)),
        ("Quest", "Quests", _quest_groups(_mapping(other, "Quest"))),
        ("Extra", "Other", _plain_groups(_mapping(other, "Extra"), split_sources=True)),
    ):
        # These three are the one case where the section key *is* the payload's
        # category, so it is stamped here rather than threaded through two
        # group builders that have no other use for it.
        sections.append(_section(key, label, _with_category(groups, key)))
    return {"sections": sections}


__all__ = ["roll_panel", "task_panel"]
