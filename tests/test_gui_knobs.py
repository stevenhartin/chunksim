"""Tests for `gui/knobs.py`: what an override path means.

Pure - paths and dicts in, dicts out - so nothing here touches disk.
"""

from __future__ import annotations

from typing import Any

import pytest

from chunksim.gui import knobs


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
    from chunksim.costing.heuristics import Heuristics

    heuristics = Heuristics(boss_monsters=frozenset({"Cerberus"}))

    boss = knobs.effective("monsters/Cerberus", heuristics)
    ordinary = knobs.effective("monsters/Goblin", heuristics)

    assert boss is not None and ordinary is not None
    assert boss != ordinary, "the fallback depends on what kind of monster it is"


def test_an_override_is_what_the_knob_resolves_to() -> None:
    from chunksim.costing.heuristics import Heuristics, Rate

    heuristics = Heuristics(monsters={"Goblin": Rate(value=250.0)})

    assert knobs.effective("monsters/Goblin", heuristics) == 250.0


def test_a_branch_shaped_path_resolves_to_no_single_number() -> None:
    """`slayer/Duradel` is a table. A caller must read `None` as "no single
    number" rather than as zero."""
    from chunksim.costing.heuristics import Heuristics

    assert knobs.effective("slayer/Duradel", Heuristics()) is None


def test_the_split_is_reported_so_the_page_need_not_know_the_depths() -> None:
    """A second copy of `BRANCH_DEPTH` in JavaScript is a second thing to get
    wrong about a key with a slash in it."""
    resolved = knobs.resolve(
        "quests/Recipe for Disaster/Freeing Evil Dave",
        scraped={}, site={}, map_overrides={},
    )

    assert resolved["parts"] == ["quests", "Recipe for Disaster/Freeing Evil Dave"]


def test_a_wait_knob_carries_a_note_explaining_what_it_is() -> None:
    """**The bug this exists to stop.** A task-gated item's own knob list
    used to point at `slayer/<master>/<task>`, whose `kills_per_hour` is
    the task's average clear speed for Slayer XP - not the wait before the
    task is assigned, and not read by `_task_hours` at all any more
    (`MasterRate.hours_to_be_assigned` excludes the gate task from its own
    wait). `wait/<master>/<task>` is what the knob list names instead: the
    actual figure the price depends on, with nothing else beside it to
    misread. The note is what the dialog prints to explain where the
    number comes from when nothing has been set."""
    resolved = knobs.resolve(
        "wait/Konar quo Maten/Hydras - Karuulm Slayer Dungeon",
        scraped={}, site={}, map_overrides={},
    )

    assert resolved["note"]
    assert "assigned" in resolved["note"].lower()
    assert resolved["editable"]


def test_a_branch_with_no_note_reports_an_empty_string() -> None:
    """A branch whose leaf needs no explanation - `rarities` is a bare word
    to probability table, not read through a dialog that shows layers - has
    no entry in `BRANCH_NOTES`, and the dialog must not print a blank
    explanatory line for it."""
    resolved = knobs.resolve("rarities/Common", scraped={}, site={}, map_overrides={})

    assert resolved["note"] == ""


class TestATrainingKnobDoesNotQuoteAFallback:
    """**The dialog promises "the number the estimate spent".** For a training
    method it was quoting `DEFAULT_XP_PER_HOUR` - a flat 1,000/hr - whenever
    nothing was pinned, which is almost always: the rate actually spent comes
    from `Heuristics.computed`, and the `Heuristics` this route builds is
    config-only, so that layer is empty here.
    """

    def test_an_unpinned_method_has_no_opinion(self) -> None:
        from chunksim.costing.heuristics import Heuristics

        path = "training/Burn wood at ~|Wintertodt|~/Firemaking"
        assert knobs.effective(path, Heuristics()) is None

    def test_a_pin_is_reported_because_a_pin_really_is_spent(self) -> None:
        """The `training` branch outranks every model, so where it holds a
        value that value is the answer."""
        from chunksim.costing.heuristics import Heuristics, Rate

        path = "training/Burn wood at ~|Wintertodt|~/Firemaking"
        pinned = Heuristics(
            training={"Burn wood at ~|Wintertodt|~": {"Firemaking": Rate(value=250000.0)}}
        )
        assert knobs.effective(path, pinned) == 250000.0

    def test_the_model_really_does_price_that_knob(self) -> None:
        """Why 1,000 was so wrong: `costing/wintertodt.py` stamps this exact
        knob on a curve running to six figures."""
        from chunksim.costing import wintertodt

        methods = wintertodt.methods(
            {"Firemaking": {"Burn wood at ~|Wintertodt|~": 50}}
        )
        firemaking = methods["Firemaking"]
        assert firemaking
        for band in firemaking:
            assert band.knob == "training/Burn wood at ~|Wintertodt|~/Firemaking"
        assert max(band.xp_per_hour for band in firemaking) > 100_000

    def test_the_other_branches_still_answer(self) -> None:
        """The correction is to `training` alone - a `monsters` fallback is a
        real fallback and the estimate really does spend it."""
        from chunksim.costing.heuristics import Heuristics

        assert knobs.effective("monsters/Abyssal demon", Heuristics()) == 150.0
        assert knobs.effective("runs/Inferno", Heuristics()) is not None


class TestATrainingKnobReadsTheModelledLayer:
    """**The fix for the flat 1,000.** `Heuristics.computed` is where a
    modelled rate lives, and `routes_view.resolve_knob` now pays for a priced
    `Heuristics` so this layer is populated when the dialog asks.
    """

    @staticmethod
    def _computed(**rates: float) -> dict[str, tuple[Any, ...]]:
        from chunksim.costing.heuristics import ComputedMethod

        return {
            "Firemaking": tuple(
                ComputedMethod(
                    method="Wintertodt (world-hopped)",
                    xp_per_hour=value,
                    level=int(level),
                    knob="training/Burn wood at ~|Wintertodt|~/Firemaking",
                )
                for level, value in rates.items()
            )
        }

    def test_the_modelled_band_is_reported(self) -> None:
        from chunksim.costing.heuristics import Heuristics

        path = "training/Burn wood at ~|Wintertodt|~/Firemaking"
        heuristics = Heuristics(computed=self._computed(**{"30": 126720.0, "99": 418176.0}))
        assert knobs.effective(path, heuristics) == 418176.0

    def test_the_highest_band_wins_not_the_opening_one(self) -> None:
        """`training_bands` takes a running maximum, so a curve's top is what
        the method is worth - quoting the opening band understates Wintertodt
        by a factor of three."""
        from chunksim.costing.heuristics import Heuristics

        path = "training/Burn wood at ~|Wintertodt|~/Firemaking"
        heuristics = Heuristics(computed=self._computed(**{"30": 126720.0, "99": 418176.0}))
        assert knobs.effective(path, heuristics) != 126720.0

    def test_a_pin_still_outranks_the_model(self) -> None:
        from chunksim.costing.heuristics import Heuristics, Rate

        path = "training/Burn wood at ~|Wintertodt|~/Firemaking"
        heuristics = Heuristics(
            computed=self._computed(**{"99": 418176.0}),
            training={"Burn wood at ~|Wintertodt|~": {"Firemaking": Rate(value=250000.0)}},
        )
        assert knobs.effective(path, heuristics) == 250000.0

    def test_another_methods_band_is_not_borrowed(self) -> None:
        """The match is on the knob path the model stamped, so a skill's other
        methods cannot answer for this one."""
        from chunksim.costing.heuristics import ComputedMethod, Heuristics

        heuristics = Heuristics(
            computed={
                "Firemaking": (
                    ComputedMethod(
                        method="a forester's campfire",
                        xp_per_hour=189969.0,
                        knob="training/Burn ~|magic logs|~ at a fire/Firemaking",
                    ),
                )
            }
        )
        path = "training/Burn wood at ~|Wintertodt|~/Firemaking"
        assert knobs.effective(path, heuristics) is None
