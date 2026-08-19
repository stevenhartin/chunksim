"""Methods whose own source says they are not for training."""

from __future__ import annotations

from chunksim.costing import disclaimed
from chunksim.costing.heuristics import Rate


def test_the_one_entry_is_the_stranglewood() -> None:
    """Kept short on purpose: this is for a source contradicting itself, not
    for methods that merely look slow. A slow method has a rate and
    `training_bands` will decline to use it."""
    assert list(disclaimed.DISCLAIMED) == ["Fish at a ~|fishing spot (The Stranglewood)|~"]


def test_each_entry_quotes_the_sentence_that_disclaims_it() -> None:
    """So a reader can check the judgement rather than take it."""
    for task, quote in disclaimed.DISCLAIMED.items():
        assert "not recommended" in quote or "not " in quote, task
        assert len(quote) > 30, task


def test_a_scraped_rate_is_taken_away() -> None:
    training = {
        "Fish at a ~|fishing spot (The Stranglewood)|~": {
            "Fishing": Rate(750.0, "mmg:Money making guide/Stranglewood fishing", "exact")
        },
        "Catch a ~|raw shark|~": {"Fishing": Rate(50_000.0, "wiki:fishing", "exact")},
    }

    kept = disclaimed.refuse(training)

    assert "Fish at a ~|fishing spot (The Stranglewood)|~" not in kept
    assert "Catch a ~|raw shark|~" in kept


def test_a_modelled_rate_survives() -> None:
    """**The day somebody finds the cadence the model wins**, without this
    having to be edited. Only the scrape's own tiers are taken away."""
    training = {
        "Fish at a ~|fishing spot (The Stranglewood)|~": {
            "Fishing": Rate(1_234.0, "computed:gathering", "modelled")
        }
    }

    assert disclaimed.refuse(training) == training


def test_a_hand_pin_survives() -> None:
    """`overrides.json` is the top of the layering, and somebody who has sat at
    the dock and counted outranks a wiki sentence."""
    task = "Fish at a ~|fishing spot (The Stranglewood)|~"
    training = {task: {"Fishing": Rate(750.0, "hand: measured", "exact")}}

    assert disclaimed.refuse(training, frozenset({task})) == training


def test_another_skill_on_a_disclaimed_task_is_dropped_with_it() -> None:
    """The disclaimer is about the method, not about one skill's share of it -
    so a scraped rate under any skill goes, and a modelled one under any skill
    stays."""
    task = "Fish at a ~|fishing spot (The Stranglewood)|~"
    training = {
        task: {
            "Fishing": Rate(750.0, "mmg:x", "exact"),
            "Hunter": Rate(10.0, "computed:gathering", "modelled"),
        }
    }

    assert set(disclaimed.refuse(training)[task]) == {"Hunter"}


def test_the_sentence_is_what_the_report_prints() -> None:
    """`DISCLAIMED` is keyed by task and valued by the wiki's own words, which
    is exactly the shape `Heuristics.refused` wants - so the entry is written
    once and the row reads `refused` with its reason rather than `unpriced`.
    See `coverage.REFUSED`."""
    for task, why in disclaimed.DISCLAIMED.items():
        assert task.startswith(("Fish", "Catch", "Cast", "Build", "Mine", "Chop")), task
        assert why.strip()
