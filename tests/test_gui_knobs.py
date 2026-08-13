"""Tests for `gui/knobs.py`: what an override path means.

Pure - paths and dicts in, dicts out - so nothing here touches disk.
"""

from __future__ import annotations

from typing import Any

import pytest

from fray_claude.gui import knobs


def test_a_path_must_name_a_real_branch() -> None:
    """**The guard, not a nicety.** These paths address a file that is read
    back and parsed, so an unchecked one is a way to write arbitrary JSON into
    it - the discipline `settings.sanitise` applies to keys, applied here to
    paths."""
    for hostile in ("", "monsters", "nonsense/Goblin", "/", "monsters/"):
        with pytest.raises(knobs.KnobError):
            knobs.split(hostile)

    assert knobs.split("monsters/Abyssal demon") == ("monsters", "Abyssal demon")
    assert knobs.split("slayer/Duradel/Abyssal demons") == (
        "slayer",
        "Duradel",
        "Abyssal demons",
    )


def test_a_one_level_branch_keeps_the_separators_in_its_key() -> None:
    """**Real quest names contain a slash.** `Recipe for Disaster/Freeing Evil
    Dave` is one key of the `quests` branch, not a path into a nesting that
    does not exist - and reading it as the latter resolves to nothing while a
    *write* builds an object `load` ignores. A correction that silently does
    not apply is the worst of the three outcomes.
    """
    assert knobs.split("quests/Recipe for Disaster/Freeing Evil Dave") == (
        "quests",
        "Recipe for Disaster/Freeing Evil Dave",
    )


def test_a_two_level_branch_splits_at_the_last_separator() -> None:
    """The leaf of a two-level branch is the simple half - a skill, an item, an
    assignment - and the container is where a slash would turn up."""
    assert knobs.split("shops/Bob's Brilliant Axes/Bronze axe") == (
        "shops",
        "Bob's Brilliant Axes",
        "Bronze axe",
    )
    # One key is the container itself, which is a real thing to ask about.
    assert knobs.split("slayer/Duradel") == ("slayer", "Duradel")


def test_a_knob_reports_every_layer_and_which_one_won() -> None:
    """**"Why is that number what it is" usually answers "because you set it
    three maps ago"**, and only a full stack can say so."""
    resolved = knobs.resolve(
        "monsters/Goblin",
        scraped={"monsters": {"Goblin": {"value": 100.0}}},
        site={"monsters": {"Goblin": {"value": 200.0}}},
        map_overrides={"monsters": {"Goblin": {"value": 300.0}}},
    )

    assert resolved["layer"] == "map"
    assert resolved["number"] == 300.0
    assert [resolved["layers"][name]["number"] for name in ("scraped", "site", "map")] == [
        100.0,
        200.0,
        300.0,
    ]


def test_the_deepest_layer_present_wins_even_when_others_are_absent() -> None:
    resolved = knobs.resolve(
        "currencies/Coins", scraped={}, site={"currencies": {"Coins": 5.0}},
        map_overrides={},
    )

    assert resolved["layer"] == "site"
    assert resolved["number"] == 5.0


def test_a_knob_nobody_has_touched_is_still_offerable() -> None:
    """Otherwise the only numbers you could correct are the ones somebody
    already corrected."""
    resolved = knobs.resolve(
        "monsters/Goblin", scraped={}, site={}, map_overrides={}
    )

    assert resolved["layer"] is None
    assert resolved["number"] is None
    assert resolved["editable"] is True


def test_a_branch_shaped_path_is_shown_rather_than_edited() -> None:
    """`slayer/Duradel` is what the superior shared table reads, and the number
    came off the whole table - so there is no one entry to put in a box.

    An editor offering one anyway would be a lie with a cursor in it.
    """
    resolved = knobs.resolve(
        "slayer/Duradel",
        scraped={"slayer": {"Duradel": {"Abyssal demons": {"kills_per_hour": 60.0}}}},
        site={},
        map_overrides={},
    )

    assert resolved["layer"] == "scraped"
    assert resolved["number"] is None
    assert resolved["editable"] is False


def test_writing_a_leaf_that_is_a_bare_number() -> None:
    assert knobs.written("currencies/Coins", 500.0, {}) == {"currencies": {"Coins": 500.0}}


def test_writing_a_leaf_that_is_an_object_keeps_the_rest_of_it() -> None:
    """And stamps a `source`: every other entry carries one, and an entry that
    appeared without provenance would be indistinguishable from a scrape that
    went wrong."""
    current = {"monsters": {"Goblin": {"value": 100.0, "match": "exact"}}}

    written = knobs.written("monsters/Goblin", 250.0, current)

    assert written["monsters"]["Goblin"]["value"] == 250.0
    assert written["monsters"]["Goblin"]["match"] == "exact"
    assert "hand:" in written["monsters"]["Goblin"]["source"]
    # The input is untouched: this is what gets written to disk, and a
    # half-applied edit is worse than a refused one.
    assert current["monsters"]["Goblin"]["value"] == 100.0


def test_clearing_a_knob_prunes_the_branches_it_empties() -> None:
    """So removing the last correction leaves `{}`, and the file can be
    deleted - which keeps "no corrections" one state on disk rather than two
    that price identically."""
    current = {"monsters": {"Goblin": {"value": 100.0}}}

    assert knobs.written("monsters/Goblin", None, current) == {}


def test_clearing_one_of_several_leaves_the_others() -> None:
    current = {"monsters": {"Goblin": {"value": 1.0}, "Rat": {"value": 2.0}}}

    assert knobs.written("monsters/Goblin", None, current) == {
        "monsters": {"Rat": {"value": 2.0}}
    }


@pytest.mark.parametrize("value", [0.0, -1.0, float("inf"), float("nan"), True])
def test_a_value_that_is_not_a_positive_finite_number_is_refused(value: Any) -> None:
    """**Refused, not clamped.** The estimator would rather say nothing than
    say something plausible; a knob quietly rounded to something else would be
    that failure moved into the editor."""
    with pytest.raises(knobs.KnobError):
        knobs.written("monsters/Goblin", value, {})


def test_a_branch_with_no_numeric_field_refuses_a_write() -> None:
    """`monster_stats` is scraped structure, not a figure to argue with."""
    with pytest.raises(knobs.KnobError):
        knobs.written("monster_stats/Goblin", 5.0, {})


def test_a_knob_nobody_set_still_resolves_to_the_number_in_force() -> None:
    """**"Default" is not a number and the reader wants the number.**

    There is no config-shaped layer of defaults to lay under the other three -
    a fallback is applied per field and often depends on something the file
    does not hold, which is why this asks the built `Heuristics` rather than
    reconstructing it. `Cerberus` is a boss and answers 20/hr; a plain monster
    answers the ordinary floor.
    """
    from fray_claude.costing.heuristics import Heuristics

    heuristics = Heuristics(boss_monsters=frozenset({"Cerberus"}))

    boss = knobs.effective("monsters/Cerberus", heuristics)
    ordinary = knobs.effective("monsters/Goblin", heuristics)

    assert boss is not None and ordinary is not None
    assert boss != ordinary, "the fallback depends on what kind of monster it is"


def test_an_override_is_what_the_knob_resolves_to() -> None:
    from fray_claude.costing.heuristics import Heuristics, Rate

    heuristics = Heuristics(monsters={"Goblin": Rate(value=250.0)})

    assert knobs.effective("monsters/Goblin", heuristics) == 250.0


def test_a_branch_shaped_path_resolves_to_no_single_number() -> None:
    """`slayer/Duradel` is a table. A caller must read `None` as "no single
    number" rather than as zero."""
    from fray_claude.costing.heuristics import Heuristics

    assert knobs.effective("slayer/Duradel", Heuristics()) is None


def test_the_split_is_reported_so_the_page_need_not_know_the_depths() -> None:
    """A second copy of `BRANCH_DEPTH` in JavaScript is a second thing to get
    wrong about a key with a slash in it."""
    resolved = knobs.resolve(
        "quests/Recipe for Disaster/Freeing Evil Dave",
        scraped={}, site={}, map_overrides={},
    )

    assert resolved["parts"] == ["quests", "Recipe for Disaster/Freeing Evil Dave"]
