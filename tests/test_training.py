"""Tests for `costing/training.py`: the band walk and what feeds it."""

from __future__ import annotations

from typing import Any

from fray_claude.costing.heuristics import Heuristics, Rate
from fray_claude.costing.training import training_options
from fray_claude.derive.challenges import ChallengeResult
from fray_claude.derive.pipeline import Derived
from fray_claude.derive.active_tasks import TaskClassification
from fray_claude.derive.bis import BisResult
from fray_claude.derive.other_tasks import OtherTasks
from fray_claude.derive.sources import SourceIndex
from fray_claude.model.chunkinfo import ChunkInfo



def _derived(**overrides: Any) -> Derived:
    """A `Derived` carrying only what the training layer reads.

    Local rather than shared with `test_estimate.py`: this module asks about
    challenge validity and nothing else, so a fixture that also builds a
    `SourceIndex` and a `BisResult` would be describing a different question.
    """
    defaults: dict[str, Any] = {
        "reachable_sections": {},
        "expanded_chunks": {},
        "source_index": SourceIndex(
            items={}, objects={}, monsters={}, npcs={}, shops={}, drop_rates={}
        ),
        "challenges": ChallengeResult(valid={}, unsupported=frozenset()),
        "bis": BisResult(picks={}),
        "task_classification": TaskClassification(),
        "other_tasks": OtherTasks(),
    }
    defaults.update(overrides)
    return Derived(**defaults)


def test_training_options_lists_only_methods_with_a_real_rate() -> None:
    """**The answer to "why is this skill so slow".**

    `_training_rate` takes the fastest method available at the *current* level
    and applies it to the whole climb, so when nothing open at that level has a
    scraped rate the climb is priced at the 1,000 xp/hr floor - Herblore 1-99
    comes out at 13,034 hours on a map that knows real rates for eighteen
    Herblore methods, none of them reachable at level 1.

    That is deliberately conservative, but a reader cannot see it. So the panel
    lists what the estimator knew and could not use, and the floor itself is
    excluded: a list of level-1 options all sitting at 1,000/hr would say "here
    are your alternatives" and mean "there are none".
    """
    info = ChunkInfo(
        {
            "challenges": {
                "Herblore": {
                    "Mix a ~|super combat potion|~": {"Primary": True, "Level": 90},
                    "Clean a ~|grimy guam|~": {"Primary": True, "Level": 3},
                    "Drink a ~|potion|~": {"Primary": False, "Level": 1},
                }
            }
        }
    )
    derived = _derived(
        challenges=ChallengeResult(
            valid={
                "Herblore": {
                    "Mix a ~|super combat potion|~": True,
                    "Clean a ~|grimy guam|~": True,
                    "Drink a ~|potion|~": True,
                }
            },
            unsupported=frozenset(),
        )
    )
    heuristics = Heuristics(
        training={"Mix a ~|super combat potion|~": {"Herblore": Rate(315000.0, "mmg", "exact")}}
    )

    options = training_options(derived, info, heuristics, "Herblore")

    # The guam has no rate, so it is the floor and says nothing; the potion is
    # not a training method at all.
    assert [(o.method, o.level, o.xp_per_hour) for o in options] == [
        ("super combat potion", 90, 315000.0)
    ]
