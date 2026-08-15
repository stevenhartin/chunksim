"""`costing/gathering.py`: the model, its refusals, and its two layerings.

The success formula is checked against the wiki's **own worked examples** rather
than against numbers taken from this implementation - that is the only check
here that could catch the arithmetic being wrong rather than merely stable.
"""

from __future__ import annotations

import pytest

from chunksim.costing import gathering
from chunksim.costing.heuristics import Rate
from chunksim.model.chunkinfo import ChunkInfo


TABLES = gathering.Tables(
    curves={
        "willow tree": (("Bronze", 16.0, 50.0), ("Rune", 56.0, 175.0)),
        "iron rocks": (("Iron rocks", 96.0, 350.0),),
        "raw lobster": (("Raw lobster", 6.0, 95.0),),
    },
    tool_ticks={"Bronze pickaxe": 8.0, "Rune pickaxe": 3.0},
    cycles={"willow tree": (30.0, 8.4)},
    experience={
        "Woodcutting": {"willow logs": (67.5, "Regular")},
        "Mining": {"iron ore": (35.0, "Regular")},
        "Fishing": {"raw lobster": (90.0, "Miscellaneous")},
    },
)

WILLOW = {
    "Level": 30,
    "Primary": True,
    "Items": ["Axe[+]"],
    "Objects": ["Willow tree"],
    "Output": "Willow logs",
}
IRON = {
    "Level": 15,
    "Primary": True,
    "Items": ["Pickaxe[+]"],
    "Objects": ["Iron[+]"],
    "Output": "Iron ore",
}
FAMILIES = {"Iron[+]": ("Iron rocks", "Iron vein")}


class TestSuccessChance:
    @pytest.mark.parametrize(
        "level,low,high,expected",
        [
            # `Skilling success rate`'s own worked example: raw monkfish at 74.
            (74, 48, 90, 80 / 256),
            # Its barbarian-fishing example: leaping sturgeon at 85.
            (85, 8, 64, 57 / 256),
        ],
    )
    def test_reproduces_the_wikis_worked_examples(
        self, level: int, low: float, high: float, expected: float
    ) -> None:
        assert gathering.success_chance(level, low, high) == expected

    def test_clamps_to_one_rather_than_exceeding_it(self) -> None:
        assert gathering.success_chance(99, 300, 400) == 1.0

    def test_clamps_the_level_at_99(self) -> None:
        # A visible boost over 99 is disregarded entirely.
        assert gathering.success_chance(120, 16, 50) == gathering.success_chance(99, 16, 50)


class TestDutyCycle:
    def test_one_node_waits_out_the_whole_respawn(self) -> None:
        assert gathering.duty_cycle(30.0, 10.0, 1) == pytest.approx(0.75)

    def test_enough_nodes_never_wait(self) -> None:
        assert gathering.duty_cycle(30.0, 10.0, 3) == 1.0

    def test_a_node_with_no_published_cycle_is_not_charged_one(self) -> None:
        assert gathering.duty_cycle(0.0, 0.0, 1) == 1.0


class TestRateAt:
    def test_prices_a_tree_from_curve_experience_and_interval(self) -> None:
        profile = gathering.SkillProfile(tool_axis="chance", tool_tiers=True)
        rate = gathering.rate_at(
            TABLES, {}, profile, "Chop willow", "Woodcutting", WILLOW, 99, tool="Rune axe"
        )
        assert rate is not None
        assert rate.node == "Willow tree"
        # The `Rune` series, not the `Bronze` one the chart lists first.
        assert rate.chance == gathering.success_chance(99, 56, 175)
        assert rate.experience == 67.5

    def test_a_worse_axe_takes_a_lower_curve(self) -> None:
        profile = gathering.SkillProfile(tool_axis="chance", tool_tiers=True)
        bronze = gathering.rate_at(
            TABLES, {}, profile, "Chop willow", "Woodcutting", WILLOW, 99, tool="Bronze axe"
        )
        rune = gathering.rate_at(
            TABLES, {}, profile, "Chop willow", "Woodcutting", WILLOW, 99, tool="Rune axe"
        )
        assert bronze is not None and rune is not None
        assert bronze.xp_per_hour < rune.xp_per_hour

    def test_a_pickaxe_changes_the_interval_not_the_chance(self) -> None:
        profile = gathering.SkillProfile(tool_axis="interval")
        bronze = gathering.rate_at(
            TABLES, FAMILIES, profile, "Mine iron", "Mining", IRON, 99, tool="Bronze pickaxe"
        )
        rune = gathering.rate_at(
            TABLES, FAMILIES, profile, "Mine iron", "Mining", IRON, 99, tool="Rune pickaxe"
        )
        assert bronze is not None and rune is not None
        assert bronze.chance == rune.chance
        assert bronze.roll_seconds > rune.roll_seconds
        assert rune.xp_per_hour > bronze.xp_per_hour

    def test_an_object_family_resolves_to_the_charted_page(self) -> None:
        # `Iron[+]` is not a page; `Iron rocks` is. Without the expansion the
        # whole skill joins nothing.
        profile = gathering.SkillProfile(tool_axis="interval")
        assert (
            gathering.rate_at(
                TABLES, FAMILIES, profile, "Mine iron", "Mining", IRON, 99,
                tool="Rune pickaxe",
            )
            is not None
        )
        assert (
            gathering.rate_at(
                TABLES, {}, profile, "Mine iron", "Mining", IRON, 99, tool="Rune pickaxe"
            )
            is None
        )

    def test_refuses_rather_than_guessing_a_missing_input(self) -> None:
        profile = gathering.SkillProfile()
        nowhere = {"Level": 1, "Primary": True, "Objects": ["Nowhere"], "Output": "Nothing"}
        assert (
            gathering.rate_at(
                TABLES, {}, profile, "Do nothing", "Woodcutting", nowhere, 99
            )
            is None
        )

    def test_a_strict_profile_refuses_an_unmeasured_loop(self) -> None:
        strict = gathering.SkillProfile(strict_kinds=True, roll_ticks_by_kind={})
        lobster = {"Level": 40, "Primary": True, "Output": "Raw lobster"}
        assert (
            gathering.rate_at(TABLES, {}, strict, "Catch lobster", "Fishing", lobster, 99)
            is None
        )

    def test_a_named_refusal_beats_its_own_kind_being_measured(self) -> None:
        # The mechanic, not the loop: see `SkillProfile.refuses`.
        profile = gathering.SkillProfile(
            strict_kinds=True,
            roll_ticks_by_kind={"Miscellaneous": 5.0},
            refuses=frozenset({"raw lobster"}),
        )
        lobster = {"Level": 40, "Primary": True, "Output": "Raw lobster"}
        assert (
            gathering.rate_at(TABLES, {}, profile, "Catch lobster", "Fishing", lobster, 99)
            is None
        )

    def test_banking_is_charged_to_training_and_not_to_a_material(self) -> None:
        profile = gathering.SkillProfile(
            strict_kinds=True,
            roll_ticks_by_kind={"Miscellaneous": 5.0},
            bank_seconds=54.0,
            carry=27.0,
        )
        lobster = {"Level": 40, "Primary": True, "Output": "Raw lobster"}
        rate = gathering.rate_at(
            TABLES, {}, profile, "Catch lobster", "Fishing", lobster, 99
        )
        assert rate is not None
        assert rate.bank_seconds_per_item == pytest.approx(2.0)
        # The walk pays the un-banked figure; the production action already
        # charges a trip for the material it consumes.
        assert rate.training_seconds - rate.seconds_per_item == pytest.approx(2.0)


class TestBestTool:
    def _info(self) -> ChunkInfo:
        return ChunkInfo(
            {
                "codeItems": {
                    "itemsPlus": {
                        "Pickaxe[+]": ["Bronze pickaxe", "Rune pickaxe", "Dragon pickaxe"]
                    }
                },
                "toolLevels": {
                    "Pickaxe[+]": {
                        "Bronze pickaxe": 1,
                        "Rune pickaxe": 41,
                        "Dragon pickaxe": 61,
                    }
                },
            }
        )

    def test_takes_the_best_the_level_can_hold(self) -> None:
        available = frozenset({"Bronze pickaxe", "Rune pickaxe", "Dragon pickaxe"})
        info = self._info()
        assert gathering.best_tool(info, "Pickaxe[+]", 30, available) == "Bronze pickaxe"
        assert gathering.best_tool(info, "Pickaxe[+]", 41, available) == "Rune pickaxe"
        assert gathering.best_tool(info, "Pickaxe[+]", 99, available) == "Dragon pickaxe"

    def test_a_tool_the_map_cannot_reach_is_not_held(self) -> None:
        assert (
            gathering.best_tool(
                self._info(), "Pickaxe[+]", 99, frozenset({"Bronze pickaxe"})
            )
            == "Bronze pickaxe"
        )

    def test_no_reachable_tool_is_no_tool_rather_than_the_worst(self) -> None:
        assert gathering.best_tool(self._info(), "Pickaxe[+]", 99, frozenset()) == ""


class TestLayering:
    def _rates(self) -> dict[str, tuple[gathering.NodeRate, ...]]:
        return {
            "Chop willow": (
                gathering.NodeRate(
                    task="Chop willow", skill="Woodcutting", level=30,
                    xp_per_hour=20000.0, experience=67.5, chance=0.3,
                    roll_seconds=2.4, duty=1.0, node="Willow tree",
                ),
                gathering.NodeRate(
                    task="Chop willow", skill="Woodcutting", level=90,
                    xp_per_hour=60000.0, experience=67.5, chance=0.7,
                    roll_seconds=2.4, duty=1.0, node="Willow tree",
                ),
            )
        }

    def test_a_modelled_rate_beats_a_scraped_one(self) -> None:
        # The opposite of `recipe_rates.apply`, deliberately - see `apply`.
        scraped = {"Chop willow": {"Woodcutting": Rate(74000.0, "wiki:woodcutting", "exact")}}
        merged = gathering.apply(scraped, self._rates())
        assert merged["Chop willow"]["Woodcutting"].value == 20000.0
        assert merged["Chop willow"]["Woodcutting"].match == gathering.GATHERING_MATCH

    def test_a_hand_pin_still_wins(self) -> None:
        scraped = {"Chop willow": {"Woodcutting": Rate(74000.0, "hand", "exact")}}
        merged = gathering.apply(scraped, self._rates(), frozenset({"Chop willow"}))
        assert merged["Chop willow"]["Woodcutting"].value == 74000.0

    def test_the_opening_level_is_what_lands_in_training(self) -> None:
        merged = gathering.apply({}, self._rates())
        assert merged["Chop willow"]["Woodcutting"].value == 20000.0

    def test_the_rest_of_the_curve_becomes_banded_methods(self) -> None:
        banded = gathering.banded_methods(self._rates())
        # The opening point is already in `training`; offering it twice would
        # put a duplicate in the tooltip.
        assert [(method.level, method.xp_per_hour) for method in banded["Woodcutting"]] == [
            (90, 60000.0)
        ]

    def test_nothing_priced_changes_nothing(self) -> None:
        scraped = {"Chop willow": {"Woodcutting": Rate(74000.0, "wiki:woodcutting", "exact")}}
        assert gathering.apply(scraped, {}) == scraped
        assert gathering.banded_methods({}) == {}


class TestTables:
    def test_an_absent_config_is_a_supported_state(self) -> None:
        assert gathering.load_tables({}).empty is True

    def test_indexes_lowercased_for_the_case_the_export_disagrees_on(self) -> None:
        tables = gathering.load_tables(
            {
                "curves": {"Willow Tree": [{"label": "Bronze", "low": 16, "high": 50}]},
                "cycles": {"Willow Tree": {"despawn": 30, "respawn": 8.4}},
                "actions": {
                    "Woodcutting": [
                        {"name": "Willow Logs", "experience": 67.5, "kind": "Regular"}
                    ]
                },
                "tool_ticks": {"Bronze pickaxe": 8},
            }
        )
        assert tables.curves["willow tree"][0] == ("Bronze", 16.0, 50.0)
        assert tables.cycles["willow tree"] == (30.0, 8.4)
        assert tables.experience["Woodcutting"]["willow logs"] == (67.5, "Regular")
        assert tables.empty is False
