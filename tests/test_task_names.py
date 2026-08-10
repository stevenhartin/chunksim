"""Tests for `derive/task_names.py`: the display form of a task name.

The raw `~|...|~` form is the key everywhere else, so these assert that
stripping changes nothing but the punctuation.
"""

from __future__ import annotations

from fray_claude.derive.task_names import strip_task_markup


def test_strip_task_markup_keeps_the_text_and_its_casing() -> None:
    assert strip_task_markup("Obtain a ~|Karil's coif|~") == "Obtain a Karil's coif"


def test_strip_task_markup_leaves_an_unmarked_name_alone() -> None:
    assert strip_task_markup("Mine a size-9 shooting star") == "Mine a size-9 shooting star"


def test_strip_task_markup_handles_several_marked_spans() -> None:
    assert strip_task_markup("Use ~|bones|~ on the ~|altar|~") == "Use bones on the altar"


def test_strip_task_markup_repairs_the_malformed_canoe_names() -> None:
    """Four real export names put the opening `|` several characters late.
    Removing the delimiter characters renders them correctly; removing
    `~|`/`|~` pairs would leave `Carve a ~log |canoe`.
    """
    assert strip_task_markup("Carve a ~log |canoe|~") == "Carve a log canoe"
    assert strip_task_markup("Carve a ~stable dugout |canoe|~") == "Carve a stable dugout canoe"


def test_strip_task_markup_leaves_the_variant_separator_and_secondary_marker() -> None:
    """Both are real parts of the stored name, and how upstream renders them
    isn't something this project has located - so they pass through rather
    than being guessed at."""
    assert strip_task_markup("Build a ~|wooden hull#Raft|~") == "Build a wooden hull#Raft"
    assert strip_task_markup("Kill a runite golem*") == "Kill a runite golem*"
