"""`costing/gathering.py`: the model, its refusals, and its two layerings.

The success formula is checked against the wiki's **own worked examples** rather
than against numbers taken from this implementation - that is the only check
here that could catch the arithmetic being wrong rather than merely stable.
"""

from __future__ import annotations

import dataclasses

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


TRAPPING = gathering.Tables(
    curves={
        "black chinchompa (hunter)": (("Black chinchompa", -78.0, 228.0),),
        "carnivorous chinchompa": (("Carnivorous chinchompa", -78.0, 228.0),),
        "magic stall": (("Magic Stall", 20.0, 180.0),),
        "knight of ardougne": (("Normal", 50.0, 240.0),),
        "vegetable stall": (("Vegetable Stall", 50.0, 500.0),),
    },
    experience={
        "Hunter": {
            "black chinchompa (hunter)": (315.0, "Box trap"),
            "carnivorous chinchompa": (265.0, "Box trap"),
        },
        "Thieving": {
            "magic stall": (90.0, "Stalls"),
            "knight of ardougne": (84.3, "Pickpocket"),
            "vegetable stall": (10.0, "Stalls"),
        },
    },
    respawns={"magic stall": 7.2, "vegetable stall": 1.2},
    parallel={"Hunter": {"": ((1, 1.0), (20, 2.0), (40, 3.0), (60, 4.0), (80, 5.0))}},
)

BLACK_CHIN = {"Level": 73, "Primary": True, "NPCs": ["Black chinchompa"]}
RED_CHIN = {"Level": 63, "Primary": True, "NPCs": ["Carnivorous chinchompa"]}
MAGIC_STALL = {"Level": 65, "Primary": True, "Objects": ["Magic Stall"]}
VEG_STALL = {"Level": 2, "Primary": True, "Objects": ["Vegetable stall"]}
KNIGHT = {"Level": 55, "Primary": True, "NPCs": ["Knight of Ardougne"]}

HUNTER = gathering.SkillProfile(
    depletes=False,
    strict_kinds=True,
    roll_ticks_by_kind={"Box trap": 101.0},
    parallel_kinds=frozenset({"Box trap"}),
    parallel_bonus={"black chinchompa (hunter)": 1.0},
)
THIEVING = gathering.SkillProfile(
    depletes=False,
    strict_kinds=True,
    roll_ticks_by_kind={"Pickpocket": 2.0, "Stalls": 2.0},
    fail_seconds=3.6,
    fail_seconds_by_kind={"Stalls": 0.0},
)


class TestUnitsAt:
    def test_takes_the_last_step_at_or_below_the_level(self) -> None:
        steps = ((1, 1.0), (20, 2.0), (40, 3.0))
        assert gathering.units_at(steps, 1) == 1.0
        assert gathering.units_at(steps, 39) == 2.0
        assert gathering.units_at(steps, 99) == 3.0

    def test_an_empty_table_is_one_unit(self) -> None:
        assert gathering.units_at((), 99) == 1.0


class TestParallelUnits:
    def _rate(self, challenge: dict[str, object], level: int) -> gathering.NodeRate:
        rate = gathering.rate_at(
            TRAPPING, {}, HUNTER, "Catch it", "Hunter", challenge, level
        )
        assert rate is not None
        return rate

    def test_more_traps_at_a_higher_level_is_faster(self) -> None:
        # The published step table is most of why hunting speeds up with
        # level; the success curve alone barely moves across this stretch.
        assert self._rate(RED_CHIN, 80).xp_per_hour > self._rate(RED_CHIN, 60).xp_per_hour

    def test_the_step_divides_the_rolling_outright(self) -> None:
        three = self._rate(RED_CHIN, 40)
        five = self._rate(RED_CHIN, 80)
        # Units multiply throughput; the curve is the only other thing moving,
        # so dividing it out has to leave exactly the ratio of the steps.
        assert (five.xp_per_hour / three.xp_per_hour) / (
            five.chance / three.chance
        ) == pytest.approx(5.0 / 3.0)

    def test_the_wilderness_trap_is_what_separates_two_identical_curves(self) -> None:
        # Black and carnivorous chinchompas share a curve exactly; the only
        # thing the model can see between them is the sixth trap.
        black = self._rate(BLACK_CHIN, 99)
        red = self._rate(RED_CHIN, 99)
        assert black.chance == red.chance
        assert black.xp_per_hour / red.xp_per_hour == pytest.approx(
            (6.0 / 5.0) * (315.0 / 265.0)
        )

    def test_a_loop_outside_parallel_kinds_gets_one_unit(self) -> None:
        alone = gathering.SkillProfile(
            depletes=False, strict_kinds=True, roll_ticks_by_kind={"Box trap": 101.0}
        )
        rate = gathering.rate_at(
            TRAPPING, {}, alone, "Catch it", "Hunter", RED_CHIN, 99
        )
        assert rate is not None
        assert rate.xp_per_hour == pytest.approx(self._rate(RED_CHIN, 99).xp_per_hour / 5.0)


class TestRespawnFloor:
    def _rate(self, challenge: dict[str, object], level: int) -> gathering.NodeRate:
        rate = gathering.rate_at(
            TRAPPING, {}, THIEVING, "Steal it", "Thieving", challenge, level
        )
        assert rate is not None
        return rate

    def test_a_restocking_stall_is_priced_at_its_respawn(self) -> None:
        # 90 xp every 7.2 seconds, which is the wiki's own `Max XP/Hr`.
        assert self._rate(MAGIC_STALL, 99).xp_per_hour == pytest.approx(45_000.0)

    def test_a_fast_respawn_leaves_the_rolling_in_charge(self) -> None:
        # 1.2s respawn against a 1.2s roll: at certainty the two meet at the
        # wiki's own maximum, and below it the *roll* is what you wait for -
        # which is the half the published `Max XP/Hr` column cannot express.
        assert self._rate(VEG_STALL, 99).xp_per_hour == pytest.approx(30_000.0)
        assert self._rate(VEG_STALL, 20).xp_per_hour < 30_000.0

    def test_the_floor_does_not_depend_on_level(self) -> None:
        assert self._rate(MAGIC_STALL, 65).xp_per_hour == self._rate(MAGIC_STALL, 99).xp_per_hour


class TestFailureCost:
    def test_a_stun_is_charged_only_to_the_loop_that_stuns(self) -> None:
        knight = gathering.rate_at(
            TRAPPING, {}, THIEVING, "Pickpocket", "Thieving", KNIGHT, 99
        )
        assert knight is not None
        chance = gathering.success_chance(99, 50.0, 240.0)
        expected = 1.2 / chance + 3.6 * ((1.0 / chance) - 1.0)
        assert knight.xp_per_hour == pytest.approx(84.3 * 3600.0 / expected)

    def test_the_stall_loop_pays_no_stun(self) -> None:
        # A failed stall steal costs the attempt and nothing else, so the
        # per-kind entry has to beat the profile-wide 3.6 seconds. Read off a
        # stall whose respawn does *not* dominate, or the floor would hide it.
        stunned = gathering.rate_at(
            TRAPPING, {}, THIEVING, "Steal it", "Thieving", VEG_STALL, 20
        )
        unstunned = gathering.rate_at(
            TRAPPING,
            {},
            gathering.SkillProfile(
                depletes=False,
                strict_kinds=True,
                roll_ticks_by_kind={"Stalls": 2.0},
            ),
            "Steal it",
            "Thieving",
            VEG_STALL,
            20,
        )
        assert stunned is not None and unstunned is not None
        assert stunned.xp_per_hour == pytest.approx(unstunned.xp_per_hour)


class TestSkillDisambiguator:
    def test_a_bare_export_name_reaches_the_wikis_hunter_page(self) -> None:
        # The export says `Black chinchompa`; the wiki page is `Black
        # chinchompa (Hunter)`, which is how it separates the creature you
        # hunt from the item it drops.
        rate = gathering.rate_at(
            TRAPPING, {}, HUNTER, "Catch it", "Hunter", BLACK_CHIN, 99
        )
        assert rate is not None
        assert rate.node == "Black chinchompa (Hunter)"

    def test_a_plainly_titled_page_still_wins(self) -> None:
        rate = gathering.rate_at(
            TRAPPING, {}, HUNTER, "Catch it", "Hunter", RED_CHIN, 99
        )
        assert rate is not None
        assert rate.node == "Carnivorous chinchompa"


@pytest.mark.real_export
class TestTheScrapeIsNotRedundant:
    """**The measurement that says "do not delete the scrape".**

    The obvious cleanup, once all five gathering skills are modelled, is to
    drop the training-guide stages that the model outranks. It would be wrong,
    and the reason is structural rather than a matter of coverage improving
    later: the model prices a *node, a roll and a chance*, and the methods only
    the scrape reaches have none of those. Forestry events, Wintertodt bruma
    roots, Pyramid Plunder rooms, shooting stars, Rogues' Castle chests and
    barbarian fishing are activities, and no skill calculator states an
    experience-per-action for an activity because there is no repeatable action
    to state one for.

    So this asserts the two sets do not nest, per skill. Sizes are not pinned -
    upstream grows - but zero would kill the claim, which is the rule
    `CLAUDE.md` sets for a count quoted in defence of an argument.
    """

    def _split(
        self, real_export: ChunkInfo, skill: str
    ) -> tuple[int, int]:
        """`(modelled, scrape-only)` over every primary method in the export."""
        from chunksim.costing import inputs

        blobs = inputs.load_reference()
        scraped, _ = inputs.load_heuristics(real_export, None, blobs)
        tables = blobs.gathering
        families = gathering.expand_families(real_export)
        profile = gathering.PROFILES[skill]
        best = {"Axe[+]": "Dragon axe", "Pickaxe[+]": "Dragon pickaxe"}

        modelled = scrape_only = 0
        for task, challenge in (real_export.challenges.get(skill) or {}).items():
            if not isinstance(challenge, dict) or challenge.get("Primary") is not True:
                continue
            family = gathering._tool_family(challenge)
            rate = gathering.rate_at(
                tables, families, profile, task, skill, challenge, 99,
                tool=best.get(family, ""),
            )
            has_model = rate is not None and rate.xp_per_hour > 0
            has_scrape = bool((scraped.training.get(task) or {}).get(skill))
            modelled += has_model
            scrape_only += has_scrape and not has_model
        return modelled, scrape_only

    @pytest.mark.parametrize(
        "skill", ["Fishing", "Hunter", "Mining", "Thieving", "Woodcutting"]
    )
    def test_each_source_reaches_methods_the_other_cannot(
        self, real_export: ChunkInfo, skill: str
    ) -> None:
        modelled, scrape_only = self._split(real_export, skill)
        assert modelled > 0, f"the model prices nothing for {skill}"
        assert scrape_only > 0, (
            f"every {skill} method the scrape prices is now modelled - if that is "
            "really true the guide stage could go, but check it is not a join "
            "regression first"
        )


CASCADE = gathering.Tables(
    curves={
        "leaping sturgeon": (("Leaping sturgeon", 8.0, 64.0),),
        "leaping salmon": (("Leaping salmon", 16.0, 96.0),),
        "leaping trout": (("Leaping trout", 32.0, 128.0),),
        "red crab (hunter)": (),
    },
    experience={
        "Fishing": {
            "leaping sturgeon": (80.0, "Miscellaneous"),
            "leaping salmon": (70.0, "Miscellaneous"),
            "leaping trout": (50.0, "Miscellaneous"),
        },
        "Hunter": {"red crab (hunter)": (64.0, "Crab trapping")},
        "Thieving": {
            "chest (rogues' castle)": (701.7, "Chests"),
            "shop counter (ore)": (100.0, "Stalls"),
        },
    },
    respawns={"chest (rogues' castle)": 20.4},
    parallel={"Hunter": {"": ((1, 1.0), (80, 5.0)), "Crab trapping": ((21, 2.0), (80, 5.0))}},
)

BARBARIAN = gathering.SkillProfile(
    depletes=False,
    strict_kinds=True,
    roll_ticks_by_kind={"Miscellaneous": 5.0},
    unbanked=frozenset({"leaping sturgeon", "leaping salmon", "leaping trout"}),
    cascades={
        node: ("Leaping sturgeon", "Leaping salmon", "Leaping trout")
        for node in ("leaping sturgeon", "leaping salmon", "leaping trout")
    },
    bank_seconds=74.0,
)
CHESTS = gathering.SkillProfile(
    depletes=False,
    strict_kinds=True,
    roll_ticks_by_kind={"Chests": 2.0, "Stalls": 2.0},
    certain_kinds=frozenset({"Chests", "Stalls"}),
    restock_kinds=frozenset({"Chests", "Stalls"}),
)
CRABS = gathering.SkillProfile(
    depletes=False,
    strict_kinds=True,
    roll_ticks_by_kind={"Crab trapping": 57.0},
    certain_kinds=frozenset({"Crab trapping"}),
    parallel_kinds=frozenset({"Crab trapping"}),
)


def _fish(node: str, level: int) -> gathering.NodeRate:
    rate = gathering.rate_at(
        CASCADE, {}, BARBARIAN, f"Catch a ~|{node}|~", "Fishing",
        {"Level": 48, "Primary": True, "Output": node.capitalize()}, level,
    )
    assert rate is not None
    return rate


class TestCascade:
    def test_every_fish_in_one_cascade_prices_the_same_action(self) -> None:
        # Three challenges, one roll: what the action pays cannot depend on
        # which of its outcomes the task happens to name.
        rates = {
            node: _fish(node, 99).xp_per_hour
            for node in ("leaping sturgeon", "leaping salmon", "leaping trout")
        }
        assert len(set(round(value, 6) for value in rates.values())) == 1

    def test_the_action_pays_more_than_its_best_fish_alone(self) -> None:
        # The whole point: priced as a single roll, two of the three rolls an
        # action makes went uncounted and barbarian fishing read 0.73x.
        single = gathering.SkillProfile(
            depletes=False, strict_kinds=True, roll_ticks_by_kind={"Miscellaneous": 5.0}
        )
        alone = gathering.rate_at(
            CASCADE, {}, single, "Catch a ~|leaping sturgeon|~", "Fishing",
            {"Level": 70, "Primary": True, "Output": "Leaping sturgeon"}, 99,
        )
        assert alone is not None
        assert _fish("leaping sturgeon", 99).xp_per_hour > alone.xp_per_hour

    def test_a_rarer_fish_costs_more_to_obtain_than_a_common_one(self) -> None:
        # One rate for training, but the item walk still has to know that a
        # sturgeon is not an average fish: `chance` stays the marginal.
        assert _fish("leaping trout", 99).chance < _fish("leaping sturgeon", 99).chance
        assert (
            _fish("leaping trout", 99).seconds_per_item
            > _fish("leaping sturgeon", 99).seconds_per_item
        )

    def test_the_rate_climbs_with_level(self) -> None:
        assert _fish("leaping trout", 48).xp_per_hour < _fish("leaping trout", 99).xp_per_hour

    def test_an_unbanked_node_is_charged_no_trip(self) -> None:
        assert _fish("leaping sturgeon", 99).bank_seconds_per_item == 0.0

    def test_half_a_cascade_is_refused_rather_than_shortened(self) -> None:
        partial = gathering.Tables(
            curves={"leaping sturgeon": (("Leaping sturgeon", 8.0, 64.0),)},
            experience={"Fishing": {"leaping sturgeon": (80.0, "Miscellaneous")}},
        )
        assert (
            gathering.rate_at(
                partial, {}, BARBARIAN, "Catch a ~|leaping sturgeon|~", "Fishing",
                {"Level": 70, "Primary": True, "Output": "Leaping sturgeon"}, 99,
            )
            is None
        )


class TestRestockGate:
    def test_a_chest_is_priced_at_its_restock(self) -> None:
        rate = gathering.rate_at(
            CASCADE, {}, CHESTS, "Loot a ~|chest|~", "Thieving",
            {"Level": 84, "Primary": True, "Objects": ["Chest (Rogues' Castle)"]}, 99,
        )
        assert rate is not None
        assert rate.xp_per_hour == pytest.approx(701.7 * 3600.0 / 20.4)

    def test_a_restock_bound_node_with_no_restock_is_refused(self) -> None:
        # Without the gate this falls back to the two-tick interaction cadence
        # and reads as the fastest method in the game.
        assert (
            gathering.rate_at(
                CASCADE, {}, CHESTS, "Steal from a ~|shop counter|~", "Thieving",
                {"Level": 1, "Primary": True, "Objects": ["Shop Counter (ore)"]}, 99,
            )
            is None
        )


class TestCrabTrapping:
    def _rate(self, level: int) -> gathering.NodeRate:
        rate = gathering.rate_at(
            CASCADE, {}, CRABS, "Catch a ~|red crab|~", "Hunter",
            {"Level": 21, "Primary": True, "NPCs": ["Red crab"]}, level,
        )
        assert rate is not None
        return rate

    def test_a_trap_that_cannot_fail_needs_no_curve(self) -> None:
        # "players cannot fail to catch a crab" - so a missing chart is the
        # statement, not the gap.
        assert self._rate(99).chance == 1.0

    def test_it_uses_its_own_trap_table_not_the_skills(self) -> None:
        # Crab trapping opens at 21 with two traps where hunting generally
        # opens at 1 with one; the general table would hand a level-21 player
        # the wrong count.
        assert self._rate(21).xp_per_hour == pytest.approx(2.0 * self._rate(1).xp_per_hour)

    def test_a_node_with_no_restock_is_still_priced(self) -> None:
        # Certain *and* not restock-bound: its rate is the interval, so the
        # `restock_kinds` guard must not reach it.
        assert self._rate(99).xp_per_hour > 0


ROTATED = gathering.SkillProfile(
    depletes=False,
    strict_kinds=True,
    roll_ticks_by_kind={"Chests": 15.5},
    certain_kinds=frozenset({"Chests"}),
    restock_kinds=frozenset({"Chests"}),
    parallel_kinds=frozenset({"Chests"}),
    parallel_bonus={"chest (rogues' castle)": 2.0},
)


class TestRotationDividesTheWait:
    def _rate(
        self, profile: gathering.SkillProfile
    ) -> gathering.NodeRate:
        rate = gathering.rate_at(
            CASCADE, {}, profile, "Loot a ~|chest|~", "Thieving",
            {"Level": 84, "Primary": True, "Objects": ["Chest (Rogues' Castle)"]}, 99,
        )
        assert rate is not None
        return rate

    def test_three_chests_share_one_restock(self) -> None:
        # 20.4s three ways is 6.8s, which is shorter than the 9.3s cycle - so
        # the wait stops binding entirely and the cycle is the whole cost.
        assert self._rate(ROTATED).xp_per_hour == pytest.approx(701.7 * 3600.0 / 9.3)

    def test_one_chest_waits_out_its_whole_restock(self) -> None:
        alone = dataclasses.replace(ROTATED, parallel_bonus={})
        assert self._rate(alone).xp_per_hour == pytest.approx(701.7 * 3600.0 / 20.4)

    def test_rotation_never_speeds_up_the_looting_itself(self) -> None:
        # The opposite of a trap line: you still open one chest at a time, so
        # the cycle is untouched and only the wait is shared.
        assert self._rate(ROTATED).roll_seconds == pytest.approx(15.5 * 0.6)
