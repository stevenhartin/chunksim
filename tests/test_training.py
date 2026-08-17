"""Tests for `costing/training.py`: the band walk and what feeds it."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from chunksim.costing.heuristics import ComputedMethod, Heuristics, Rate
from chunksim.costing.training import (
    TrainingOption,
    quest_xp_grants,
    training_bands,
    training_options,
)
from chunksim.derive.challenges import ChallengeResult
from chunksim.derive.pipeline import Derived
from chunksim.derive.active_tasks import TaskClassification
from chunksim.derive.bis import BisResult
from chunksim.derive.other_tasks import CategoryTasks, OtherTasks, TaskGroup
from chunksim.derive.sources import SourceIndex
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.model.experience import MAX_LEVEL, level_for_xp, xp_between, xp_for_level



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
    came out at 13,034 hours on a map that knows real rates for eighteen
    Herblore methods, none of them reachable at level 1. Walked in bands the
    same climb is 100 hours.

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


class TestAModelBeatsAScrapeForTheSameTask:
    """**The layering, applied where it was not being.**

    `costing/__init__.py` states `scraped < modelled < overrides`, and
    `gathering.apply` enforces it for the node walk. A `ComputedMethod` was
    *added* to the scraped list rather than replacing it, which is right for
    Prayer - burying a bone is a genuine alternative to offering fish at a
    shrine - and wrong when the two describe the same task: the flat guide
    figure stayed in and won wherever the curve was below it, which is exactly
    the low-level stretch a curve exists to correct.
    """

    _INFO = ChunkInfo(
        {"challenges": {"Hunter": {"Track a ~|herbiboar|~": {"Primary": True, "Level": 80}}}}
    )
    _DERIVED = _derived(
        challenges=ChallengeResult(
            valid={"Hunter": {"Track a ~|herbiboar|~": True}}, unsupported=frozenset()
        )
    )
    _KNOB = "training/Track a ~|herbiboar|~/Hunter"

    def _heuristics(self, **extra: object) -> Heuristics:
        return Heuristics(
            training={"Track a ~|herbiboar|~": {"Hunter": Rate(137_000.0, "wiki:hunter", "exact")}},
            computed={
                "Hunter": (
                    ComputedMethod(
                        method="herbiboar", xp_per_hour=117_000.0, level=80,
                        match="modelled", knob=self._KNOB,
                    ),
                )
            },
            **extra,  # type: ignore[arg-type]
        )

    def test_the_scrape_is_dropped_where_a_model_names_the_task(self) -> None:
        options = training_options(self._DERIVED, self._INFO, self._heuristics(), "Hunter")
        assert [(o.method, o.xp_per_hour) for o in options] == [("herbiboar", 117_000.0)]

    def test_a_pin_still_beats_the_model(self) -> None:
        # `overrides.json` is the top of the layering by design, and an
        # override lands in `training` looking exactly like the guide row it
        # replaced - which is why this needs `Heuristics.pinned` rather than a
        # source string.
        options = training_options(
            self._DERIVED, self._INFO,
            self._heuristics(pinned=frozenset({"Track a ~|herbiboar|~"})),
            "Hunter",
        )
        assert {o.xp_per_hour for o in options} == {137_000.0, 117_000.0}

    def test_a_model_about_a_different_task_leaves_the_scrape_alone(self) -> None:
        # Prayer's case: a computed bury rate is an alternative to the shrine
        # challenges, not a replacement for one of them.
        heuristics = Heuristics(
            training={"Track a ~|herbiboar|~": {"Hunter": Rate(137_000.0, "wiki:hunter", "exact")}},
            computed={
                "Hunter": (
                    ComputedMethod(
                        method="something else", xp_per_hour=50_000.0, level=1,
                        match="modelled", knob="training/Catch a ~|kebbit|~/Hunter",
                    ),
                )
            },
        )
        options = training_options(self._DERIVED, self._INFO, heuristics, "Hunter")
        assert {o.method for o in options} == {"herbiboar", "something else"}

    def test_a_knob_that_names_no_task_changes_nothing(self) -> None:
        # `combat_xp` uses `monster_stats/<monster>` and Prayer's carries no
        # task either, so neither may suppress anything.
        heuristics = Heuristics(
            training={"Track a ~|herbiboar|~": {"Hunter": Rate(137_000.0, "wiki:hunter", "exact")}},
            computed={
                "Hunter": (
                    ComputedMethod(
                        method="combat", xp_per_hour=9.0, level=None,
                        match="computed", knob="monster_stats/whatever",
                    ),
                )
            },
        )
        options = training_options(self._DERIVED, self._INFO, heuristics, "Hunter")
        assert any(o.method == "herbiboar" for o in options)


class TestAComputedMethodPaysForWhatItConsumes:
    """**The defect this caught, and it was a large one.**

    Moving the Giants' Foundry out of the scrape and into a module dropped the
    bars it eats, because `_material_cost` only ran on the challenge-derived
    branch - Smithing 1-99 read 54.5 hours against a true 144.5. A computed
    method is a different *source* for a rate, not a claim that the method has
    become free.
    """

    _INFO = ChunkInfo(
        {"challenges": {"Smithing": {"Forge a ~|preform|~": {"Primary": True, "Level": 15}}}}
    )
    _DERIVED = _derived(
        challenges=ChallengeResult(
            valid={"Smithing": {"Forge a ~|preform|~": True}}, unsupported=frozenset()
        )
    )

    def _options(self, knob: str) -> tuple[TrainingOption, ...]:
        heuristics = Heuristics(
            computed={
                "Smithing": (
                    ComputedMethod(
                        method="Giants' Foundry", xp_per_hour=48_000.0, level=15,
                        match="confirmed", knob=knob,
                    ),
                )
            },
            material_seconds_per_xp={"Forge a ~|preform|~": 0.0136},
        )
        return training_options(self._DERIVED, self._INFO, heuristics, "Smithing")

    def test_the_material_cost_is_charged(self) -> None:
        option = self._options("training/Forge a ~|preform|~/Smithing")[0]
        assert option.material_seconds_per_xp == pytest.approx(0.0136)
        assert option.effective_xp_per_hour < option.xp_per_hour

    def test_a_knob_naming_no_task_costs_nothing(self) -> None:
        # `combat_xp` uses `monster_stats/<monster>`; there is nothing to look
        # up and nothing to charge.
        option = self._options("monster_stats/whatever")[0]
        assert option.material_seconds_per_xp == 0.0

    def test_a_method_whose_task_consumes_nothing_is_untouched(self) -> None:
        heuristics = Heuristics(
            computed={
                "Smithing": (
                    ComputedMethod(
                        method="something", xp_per_hour=1_000.0, level=1,
                        match="confirmed", knob="training/Forge a ~|preform|~/Smithing",
                    ),
                )
            },
        )
        option = training_options(self._DERIVED, self._INFO, heuristics, "Smithing")[0]
        assert option.material_seconds_per_xp == 0.0
        assert option.effective_xp_per_hour == pytest.approx(option.xp_per_hour)


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


def test_a_computed_method_reaches_the_band_walk() -> None:
    """**The door for the skills the export models no training for.** Combat
    has no "Train Strength" challenge and Prayer has no "bury a bone" one,
    because neither needs a task in the game - one needs a monster and the
    other needs a bone. Their rates are computed and arrive through
    `Heuristics.computed`; without this they sit at the 1,000/hr floor with
    `(none found)` where a method should be.
    """
    heuristics = Heuristics(
        computed={"Strength": (ComputedMethod("Scurrius", 110_740.0),)}
    )

    options = training_options(_derived(), ChunkInfo({}), heuristics, "Strength")

    assert [(o.method, o.level, o.xp_per_hour) for o in options] == [
        ("Scurrius", None, 110_740.0)
    ]


def test_a_computed_method_carries_its_level() -> None:
    """Prayer's do, where combat's do not: superior dragon bones open at 70,
    and priced without that the whole climb from level 1 is walked at a rate
    nothing below 70 can use."""
    heuristics = Heuristics(
        computed={
            "Prayer": (
                ComputedMethod("Superior dragon bones (Chaos Altar)", 400_000.0, level=70),
                ComputedMethod("Big bones (Chaos Altar)", 163_558.0, level=1),
            )
        }
    )

    bands = training_bands(
        training_options(_derived(), ChunkInfo({}), heuristics, "Prayer"), 0, 99
    )

    assert [(b.level_from, b.level_to, b.method) for b in bands] == [
        (1, 70, "Big bones (Chaos Altar)"),
        (70, 99, "Superior dragon bones (Chaos Altar)"),
    ]


def test_a_computed_method_does_not_hide_the_export_s_own() -> None:
    """Prayer has six `Primary` challenges - offering fish at a shrine, shards
    at a libation bowl - and a computed bury rate is an *alternative* to them,
    not a replacement. Returning only the computed one would throw away a
    method that might be faster."""
    info = ChunkInfo(
        {"challenges": {"Prayer": {"Use ~|superior dragon bones|~": {"Primary": True, "Level": 70}}}}
    )
    derived = _derived(
        challenges=ChallengeResult(
            valid={"Prayer": {"Use ~|superior dragon bones|~": 70}}, unsupported=frozenset()
        )
    )
    heuristics = Heuristics(
        computed={"Prayer": (ComputedMethod("Big bones (buried)", 12_000.0, level=1),)},
        training={"Use ~|superior dragon bones|~": {"Prayer": Rate(500_000.0, "mmg", "exact")}},
    )

    options = training_options(derived, info, heuristics, "Prayer")

    assert [o.method for o in options] == ["superior dragon bones", "Big bones (buried)"]


def test_a_methods_materials_are_part_of_its_rate() -> None:
    """**A published rate is quoted with the materials to hand.** "299,000 an
    hour at anglerfish" describes the range, not the trip before it - and on a
    chunk map the trip is often the whole cost.

    Ranking on the published figure picked xerician robes for Crafting at
    167,200/hr on a map where one fabric takes 95 seconds to obtain and a robe
    needs four: 831/hr once the fabric is counted, and a method no player
    would touch.
    """
    option = TrainingOption("anglerfish", 84, 299_000.0, "exact", material_seconds_per_xp=0.117)

    # 3600/299000 seconds of cooking per xp, plus 0.117 of fishing.
    assert option.effective_xp_per_hour == pytest.approx(
        3600.0 / (3600.0 / 299_000.0 + 0.117)
    )
    assert option.effective_xp_per_hour < option.xp_per_hour


def test_a_method_with_no_materials_keeps_its_published_rate_exactly() -> None:
    """The common case, and it must not round-trip through the arithmetic:
    `3600 / (3600 / 50000 + 0)` is 50,000.00000000001, which is a different
    number in a test and in a rendered total."""
    option = TrainingOption("fast rocks", 50, 50_000.0, "exact")

    assert option.effective_xp_per_hour == 50_000.0


def test_the_cheaper_climb_wins_even_when_the_guide_says_otherwise() -> None:
    """The whole point: the band walk ranks on what a method costs, not on
    what its action costs. A slower action with obtainable materials beats a
    fast one whose inputs are not."""
    options = (
        TrainingOption("xerician robe", 1, 167_200.0, "exact", material_seconds_per_xp=4.309),
        TrainingOption("topaz bracelet", 1, 90_000.0, "exact"),
    )

    bands = training_bands(options, 0, 99)

    assert [band.method for band in bands] == ["topaz bracelet"]


def test_a_band_carries_both_halves_of_its_rate() -> None:
    """So a reader can see why a 290,000/hr shark reads as 148,000, rather
    than concluding the rate is wrong."""
    options = (
        TrainingOption("shark", 1, 290_000.0, "exact", material_seconds_per_xp=0.0345),
    )

    (band,) = training_bands(options, 0, 99)

    assert band.published_xp_per_hour == 290_000.0
    assert band.xp_per_hour < band.published_xp_per_hour
    assert band.material_hours == pytest.approx(
        band.xp / band.xp_per_hour - band.xp / 290_000.0
    )
    assert band.material_hours + band.xp / 290_000.0 == pytest.approx(band.hours)


def test_a_computed_rate_is_not_charged_for_its_materials_twice() -> None:
    """**The two rate sources measure different things.**

    A money-making guide quotes a method with its materials to hand, so the
    gathering has to be added. A `recipe_rates` figure is
    `experience * 3600 / (0.6*ticks + materials + overhead)` - already the
    whole cycle - so adding it again halves the method.

    Measured when this was found: 653 options on `verf-sim/run-001` carried a
    computed rate and were charged twice, against 58 with a guide rate that
    were correct.
    """
    from chunksim.costing.recipe_rates import RECIPE_SOURCE
    from chunksim.costing.training import _material_cost

    heuristics = Heuristics(material_seconds_per_xp={"Build a ~|4-poster|~": 0.05})

    guide = Rate(value=18_187.0, source="mmg:Money making guide/Something", match="exact")
    computed = Rate(value=18_187.0, source=RECIPE_SOURCE, match="computed")

    # The guide has not paid for its materials, so they are charged.
    assert _material_cost(heuristics, "Build a ~|4-poster|~", guide) == 0.05
    # The computed rate already has, so they are not.
    assert _material_cost(heuristics, "Build a ~|4-poster|~", computed) == 0.0


def test_same_skill_gathering_experience_is_credited() -> None:
    """**The generic half of it.** Sorting a salvage pays 95 Sailing and costs
    34 seconds of salvaging, which itself pays 200 Sailing - so the pair is 295
    experience for 36 seconds, not 95 for 36. Charging the time and discarding
    the experience prices the gathering as though it were somebody else's work.
    """
    without = TrainingOption(
        method="sorting", level=87, xp_per_hour=171_000.0, match="modelled",
        material_seconds_per_xp=34.2 / 95.0,
    )
    with_credit = replace(without, material_xp_per_xp=200.0 / 95.0)

    assert with_credit.effective_xp_per_hour > without.effective_xp_per_hour
    # 295 experience per (2.0s sorting + 34.2s salvaging).
    assert with_credit.effective_xp_per_hour == pytest.approx(295 / 36.2 * 3600, rel=1e-3)


def test_a_credit_of_zero_leaves_the_rate_alone() -> None:
    """The common case: a log chopped for a bow pays Woodcutting, which does
    nothing for a Fletching climb."""
    option = TrainingOption(method="fletch", level=1, xp_per_hour=50_000.0, match="modelled")

    assert option.material_xp_per_xp == 0.0
    assert option.effective_xp_per_hour == 50_000.0
