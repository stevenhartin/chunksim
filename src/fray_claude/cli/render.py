"""Turning derived structures into lines on a terminal.

Shared because two families need the same shapes: the listing commands
(`sections`, `sources`, `tasks`) and `diff`, which prints the same task and
source names either side of a comparison. Nothing here decides *what* to show -
that is the family's - only how a group of names is capped, indented and
counted.

`strip_task_markup` is not here: a task's raw `~|...|~` form is the key
everywhere, so stripping it is a domain decision that belongs beside the
challenges, not a formatting one.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from fray_claude.derive.challenges import strip_task_markup
from fray_claude.derive.other_tasks import CategoryTasks, task_text
from fray_claude.model.chunkinfo import ChunkInfo


def display_tasks(names: Iterable[str]) -> list[str]:
    """Task names sorted for display, markup stripped. Sorting happens on
    the stripped form so the visible order matches what's on screen -
    `~|Zamorak|~ ...` would otherwise sort under `~`, i.e. nowhere useful.
    """
    return sorted(strip_task_markup(name) for name in names)


def print_grouped(
    tasks: CategoryTasks, chunk_info: ChunkInfo, attr: str, limit: int | None
) -> None:
    """A category's groups with headers, each group's tasks indented under it.

    `--limit` caps the *tasks* rather than the groups, so a large category
    still shows where its work is concentrated; a group with nothing in the
    requested half is skipped entirely.
    """
    challenges = chunk_info.challenges.get(tasks.category) or {}
    shown = 0
    for group in tasks.groups:
        names: tuple[str, ...] = getattr(group, attr)
        if not names:
            continue
        if limit is not None and shown >= limit:
            remaining = sum(len(getattr(g, attr)) for g in tasks.groups) - shown
            print(f"  ... and {remaining} more (--limit {shown + remaining} to see all)")
            return
        print(f"  {group.name}")
        for name in names:
            if limit is not None and shown >= limit:
                break
            challenge = challenges.get(name) or {}
            text = (
                tasks.completed_text(name, challenge)
                if attr == "completed"
                else task_text(name, challenge)
            )
            print(f"    {text}")
            shown += 1


def print_capped(names: list[str], limit: int | None) -> None:
    shown = names if limit is None else names[:limit]
    for name in shown:
        print(f"  {name}")
    if limit is not None and len(names) > limit:
        print(f"  ... and {len(names) - limit} more (--limit {len(names)} to see all)")


def name_or_none(name: str | None) -> str:
    return strip_task_markup(name) if name else "(none)"
