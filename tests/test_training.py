"""Tests for `costing/training.py`: the band walk and what feeds it."""

from __future__ import annotations

from typing import Any

from fray_claude.costing.heuristics import Heuristics, Rate
from fray_claude.costing.training import (
    TrainingOption,
    quest_xp_grants,
    training_bands,
    training_options,
)
from fray_claude.derive.challenges import ChallengeResult
from fray_claude.derive.pipeline import Derived
from fray_claude.derive.active_tasks import TaskClassification
from fray_claude.derive.bis import BisResult
from fray_claude.derive.other_tasks import CategoryTasks, OtherTasks, TaskGroup
from fray_claude.derive.sources import SourceIndex
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.model.experience import MAX_LEVEL, level_for_xp, xp_between, xp_for_level



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


# --- the band walk ---------------------------------------------------------

_HERBLORE = (
    TrainingOption("grimy kwuarm", 54, 56_500.0, "contained"),
    TrainingOption("super combat potion", 90, 315_000.0, "exact"),
)


def _walk(options: Any = _HERBLORE, start: int = 1, target: int = 99) -> Any:
    return training_bands(options, xp_for_level(start), target)


def test_the_climb_splits_where_the_rate_changes() -> None:
    """The worked example: a floor band, then each method as it opens."""
    assert [
        (b.level_from, b.level_to, b.xp, b.xp_per_hour, b.method) for b in _walk()
    ] == [
        (1, 54, 150_872, 1_000.0, ""),
        (54, 90, 5_195_460, 56_500.0, "grimy kwuarm"),
        (90, 99, 7_688_099, 315_000.0, "super combat potion"),
    ]


def test_the_bands_telescope_exactly() -> None:
    """`xp_for_level` is exact integers, so the split cannot lose or invent XP -
    which is what lets the hours be summed rather than reconciled."""
    for start, target in ((1, 99), (30, 85), (54, 55), (1, MAX_LEVEL)):
        bands = _walk(start=start, target=target)
        assert sum(b.xp for b in bands) == xp_between(start, target)


def test_the_floor_can_only_ever_be_the_first_band() -> None:
    """A method open at 54 is still open at 90, so the rate only rises. That
    monotonicity is the whole of "the floor stays visible": it is a named
    stretch with its own hours, never a number averaged into the total."""
    for start in (1, 20, 53, 54, 70):
        bands = _walk(start=start)
        floored = [i for i, band in enumerate(bands) if band.match == "default"]
        assert floored in ([], [0])


def test_a_climb_already_finished_has_no_bands() -> None:
    assert _walk(start=99, target=99) == ()
    assert _walk(start=99, target=50) == ()


def test_the_band_labels_do_not_depend_on_the_input_order() -> None:
    """**`--jobs` must not change the text either.** Two methods at the same
    level and rate have to label their band identically in every worker, and a
    number that agrees while a label does not is worse than both disagreeing,
    because nothing would catch it.
    """
    import random

    tied = [
        TrainingOption("alpha", 40, 20_000.0, "exact"),
        TrainingOption("beta", 40, 20_000.0, "contained"),
        TrainingOption("gamma", 70, 90_000.0, "exact"),
    ]
    expected = [(b.level_from, b.method) for b in training_bands(tied, 0, 99)]
    for seed in range(100):
        shuffled = tied[:]
        random.Random(seed).shuffle(shuffled)
        assert [(b.level_from, b.method) for b in training_bands(shuffled, 0, 99)] == expected


def test_a_slower_method_opening_later_never_starts_a_band() -> None:
    """The step function is a running *maximum*. A worse method unlocking at a
    higher level is not a downgrade you are forced into."""
    options = (
        TrainingOption("fast", 10, 90_000.0, "exact"),
        TrainingOption("slow", 60, 5_000.0, "exact"),
    )
    assert [b.method for b in training_bands(options, 0, 99)] == ["", "fast"]


def test_starting_mid_band_charges_only_what_is_left() -> None:
    """A quest grant lands `start_xp` inside a band rather than on a boundary,
    so the first band has to be the remainder of that band and not all of it."""
    inside = xp_for_level(60) + 100_000
    bands = training_bands(_HERBLORE, inside, 99)

    assert bands[0].xp == xp_for_level(90) - inside
    assert bands[0].method == "grimy kwuarm"
    assert sum(b.xp for b in bands) == xp_for_level(99) - inside


# --- quest experience ------------------------------------------------------

_DRUIDIC = "~|Druidic Ritual|~ Complete the quest"

_QUEST_INFO = ChunkInfo(
    {
        "challenges": {
            "Quest": {
                "~|Druidic Ritual|~ 1": {"BaseQuest": "Druidic Ritual"},
                _DRUIDIC: {"BaseQuest": "Druidic Ritual", "XpReward": {"Herblore": 250}},
                "~|Dream Mentor|~ Complete the quest": {
                    "XpReward": {"Strength|Ranged|Magic|Hitpoints|Defence": 150_000}
                },
                "~|Dragon Slayer II|~ Complete the quest": {
                    "XpReward": {"Attack|Defence|Strength|Hitpointsx4": 25_000, "Smithing": 400}
                },
                "~|Recipe for Disaster|~ Complete the quest": {"XpReward": {"Anyx6": 20_000}},
            }
        }
    }
)


def _quests(*active: str) -> Derived:
    return _derived(
        other_tasks=OtherTasks(
            categories={
                "Quest": CategoryTasks(
                    category="Quest",
                    groups=(TaskGroup(name="a quest", active=tuple(active)),),
                )
            }
        )
    )


def test_a_completable_quest_pays_its_experience() -> None:
    grants, lamps = quest_xp_grants(_quests("~|Druidic Ritual|~ 1", _DRUIDIC), _QUEST_INFO)

    assert grants == {"Herblore": 250}
    assert lamps == ()


def test_a_quest_already_done_pays_nothing() -> None:
    """**The anti-double-count invariant.** A completed quest is not in
    `active`, and its XP is already reflected in the level `infer_levels` read
    out of the ledger - granting it again would pay for it twice."""
    assert quest_xp_grants(_quests(), _QUEST_INFO) == ({}, ())


def test_a_choice_of_skills_is_reported_rather_than_spent() -> None:
    """Dream Mentor pays 150,000 into one of five skills. Spending it well is
    an optimisation; guessing would quietly shrink the estimate on a choice
    nobody made."""
    grants, lamps = quest_xp_grants(_quests("~|Dream Mentor|~ Complete the quest"), _QUEST_INFO)

    assert grants == {}
    assert [(lamp.skills, lamp.xp, lamp.count) for lamp in lamps] == [
        (("Strength", "Ranged", "Magic", "Hitpoints", "Defence"), 150_000, 1)
    ]


def test_a_count_suffix_is_several_lamps_and_a_plain_key_beside_it_still_pays() -> None:
    """Dragon Slayer II hands out four 25,000 lamps *and* 400 flat Smithing."""
    grants, lamps = quest_xp_grants(
        _quests("~|Dragon Slayer II|~ Complete the quest"), _QUEST_INFO
    )

    assert grants == {"Smithing": 400}
    assert [(lamp.xp, lamp.count) for lamp in lamps] == [(25_000, 4)]


def test_any_is_a_lamp_with_no_named_skills() -> None:
    _, lamps = quest_xp_grants(_quests("~|Recipe for Disaster|~ Complete the quest"), _QUEST_INFO)

    assert [(lamp.skills, lamp.xp, lamp.count) for lamp in lamps] == [((), 20_000, 6)]


def test_a_grant_shortens_the_climb_and_skips_the_bands_below_it() -> None:
    """One operation does both, which is why they cannot disagree: the walk
    from the granted total is the same object as the walk that skipped the
    bands."""
    granted = xp_for_level(54) + 1
    bands = training_bands(_HERBLORE, granted, 99)

    assert [b.method for b in bands] == ["grimy kwuarm", "super combat potion"]
    assert sum(b.xp for b in bands) == xp_for_level(99) - granted
