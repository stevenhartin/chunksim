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
        "willow tree": (("Bronze", 16.0, 50.0, 1, "confirmed"), ("Rune", 56.0, 175.0, 1, "confirmed")),
        "iron rocks": (("Iron rocks", 96.0, 350.0, 1, "confirmed"),),
        "raw lobster": (("Raw lobster", 6.0, 95.0, 1, "confirmed"),),
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
        # `Iron[+]` is not a page; `Iron rocks` is, and the expansion is what
        # says so.
        profile = gathering.SkillProfile(tool_axis="interval")
        assert (
            gathering.rate_at(
                TABLES, FAMILIES, profile, "Mine iron", "Mining", IRON, 99,
                tool="Rune pickaxe",
            )
            is not None
        )

    def test_the_rock_stem_reaches_the_chart_where_no_family_does(self) -> None:
        # **The second route to the same page, and it used to be the only
        # failure.** Drop the expansion and `Iron[+]` says nothing, but the
        # challenge's `Output` is `Iron ore` and `Iron ore` -> `Iron rocks` is
        # the rewrite `_ROCK_SUFFIX` exists for. Two rocks the wiki charts
        # under a name no task uses - limestone and basalt - joined nothing at
        # all until it did.
        profile = gathering.SkillProfile(tool_axis="interval")
        assert (
            gathering.rate_at(
                TABLES, {}, profile, "Mine iron", "Mining", IRON, 99, tool="Rune pickaxe"
            )
            is not None
        )

    def test_a_name_that_is_not_a_rock_is_left_alone(self) -> None:
        # The guard: without it every join in the project grew a
        # `Willow tree rocks`, which is noise in the one place a miss has to
        # stay readable.
        keys = gathering._join_keys({"Objects": ["Willow tree"]}, {}, gathering._NAME_FIELDS)
        assert not any("rock" in key for key in keys)

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
        assert tables.curves["willow tree"][0] == ("Bronze", 16.0, 50.0, 1, "confirmed")
        assert tables.cycles["willow tree"] == (30.0, 8.4)
        assert tables.experience["Woodcutting"]["willow logs"] == (67.5, "Regular")
        assert tables.empty is False


TRAPPING = gathering.Tables(
    curves={
        "black chinchompa (hunter)": (("Black chinchompa", -78.0, 228.0, 1, "confirmed"),),
        "carnivorous chinchompa": (("Carnivorous chinchompa", -78.0, 228.0, 1, "confirmed"),),
        "magic stall": (("Magic Stall", 20.0, 180.0, 1, "confirmed"),),
        "knight of ardougne": (("Normal", 50.0, 240.0, 1, "confirmed"),),
        "vegetable stall": (("Vegetable Stall", 50.0, 500.0, 1, "confirmed"),),
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
        "leaping sturgeon": (("Leaping sturgeon", 8.0, 64.0, 1, "confirmed"),),
        "leaping salmon": (("Leaping salmon", 16.0, 96.0, 1, "confirmed"),),
        "leaping trout": (("Leaping trout", 32.0, 128.0, 1, "confirmed"),),
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
            curves={"leaping sturgeon": (("Leaping sturgeon", 8.0, 64.0, 1, "confirmed"),)},
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
    worked_at={"chest (rogues' castle)": 3.0},
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
        alone = dataclasses.replace(ROTATED, worked_at={})
        assert self._rate(alone).xp_per_hour == pytest.approx(701.7 * 3600.0 / 20.4)

    def test_rotation_never_speeds_up_the_looting_itself(self) -> None:
        # The opposite of a trap line: you still open one chest at a time, so
        # the cycle is untouched and only the wait is shared.
        assert self._rate(ROTATED).roll_seconds == pytest.approx(15.5 * 0.6)


class TestUnitsWorked:
    """`units_worked` is the one place "how many at once" is decided.

    Three layers and one number; what the number *buys* is `rate_at`'s
    business, and the point of the split is that a skill nobody has modelled
    yet gets the idea for free rather than by copying Thieving.
    """

    _TABLES = gathering.Tables(
        parallel={"Hunter": {"": ((1, 1.0), (80, 5.0)), "Crab trapping": ((21, 2.0),)}}
    )

    def _units(self, profile: gathering.SkillProfile, kind: str, node: str, level: int) -> float:
        return gathering.units_worked(self._TABLES, profile, "Hunter", kind, node, level)

    def test_a_skill_default_applies_where_nothing_else_speaks(self) -> None:
        assert self._units(gathering.SkillProfile(worked=2.0), "Regular", "Oak tree", 99) == 2.0

    def test_a_published_table_beats_the_default(self) -> None:
        profile = gathering.SkillProfile(worked=2.0, parallel_kinds=frozenset({"Box trap"}))
        assert self._units(profile, "Box trap", "Ferret", 99) == 5.0

    def test_the_table_only_reaches_the_loops_it_names(self) -> None:
        # The Hunter page's table is about trapping; falconry is not trapping,
        # and the prose that says so has to live in the profile.
        profile = gathering.SkillProfile(parallel_kinds=frozenset({"Box trap"}))
        assert self._units(profile, "Falconry", "Dark kebbit", 99) == 1.0

    def test_a_per_node_count_beats_everything(self) -> None:
        profile = gathering.SkillProfile(
            worked=2.0,
            parallel_kinds=frozenset({"Box trap"}),
            worked_at={"ferret": 3.0},
        )
        assert self._units(profile, "Box trap", "Ferret", 99) == 3.0

    def test_a_bonus_adds_to_the_table_rather_than_replacing_it(self) -> None:
        # The Wilderness trap has to keep tracking the table below level 80,
        # which writing `6` outright would not.
        profile = gathering.SkillProfile(
            parallel_kinds=frozenset({"Box trap"}),
            parallel_bonus={"black chinchompa": 1.0},
        )
        assert self._units(profile, "Box trap", "Black chinchompa", 99) == 6.0
        assert self._units(profile, "Box trap", "Black chinchompa", 1) == 2.0


class TestUnitsAreSpentByWhatTheNodeWaitsFor:
    """The same count, three different payoffs - none of them per skill."""

    _TABLES = gathering.Tables(
        curves={"n": (("n", 500.0, 500.0, 1, "confirmed"),)},
        experience={"S": {"n": (100.0, "K")}},
        cycles={"cycling": (30.0, 30.0)},
        respawns={"restocking": 60.0},
    )

    def _rate(self, node: str, profile: gathering.SkillProfile) -> gathering.NodeRate:
        tables = dataclasses.replace(
            self._TABLES,
            curves={node.lower(): (("n", 500.0, 500.0, 1, "confirmed"),)},
            experience={"S": {node.lower(): (100.0, "K")}},
        )
        rate = gathering.rate_at(
            tables, {}, profile, "t", "S",
            {"Level": 1, "Primary": True, "Objects": [node]}, 99,
        )
        assert rate is not None
        return rate

    def test_a_restocking_node_divides_its_wait(self) -> None:
        one = self._rate("restocking", gathering.SkillProfile(roll_ticks=2.0, depletes=False))
        three = self._rate(
            "restocking",
            gathering.SkillProfile(roll_ticks=2.0, depletes=False, worked=3.0),
        )
        assert one.xp_per_hour * 3.0 == pytest.approx(three.xp_per_hour)

    def test_a_rock_pays_the_hop_as_well_as_the_respawn(self) -> None:
        # **`hops` is the whole of the Mining rework.** A stall's restock is
        # the whole story because you stand at it; a rock makes you walk, and
        # where the cluster is big enough that the respawn stops binding the
        # hop is the *only* downtime left. Without this a rock reads as pure
        # rolling.
        plain = gathering.SkillProfile(roll_ticks=2.0, node_seconds=5.0, worked=100.0)
        hopping = dataclasses.replace(plain, hops=True)
        assert self._rate("restocking", plain).xp_per_hour > self._rate(
            "restocking", hopping
        ).xp_per_hour

    def test_a_stall_pays_its_restock_and_nothing_on_top(self) -> None:
        # The default, and why it is the default: `hops` off means a published
        # restock replaces the flat charge rather than adding to it.
        charged = gathering.SkillProfile(roll_ticks=2.0, node_seconds=5.0)
        free = gathering.SkillProfile(roll_ticks=2.0)
        assert self._rate("restocking", charged).xp_per_hour == pytest.approx(
            self._rate("restocking", free).xp_per_hour
        )

    def test_rotation_never_divides_the_rolling(self) -> None:
        # A restocking node worked three ways still opens one at a time, so
        # once the wait stops binding the count buys nothing more.
        slow = gathering.SkillProfile(roll_ticks=200.0, depletes=False, worked=3.0)
        alone = gathering.SkillProfile(roll_ticks=200.0, depletes=False)
        assert self._rate("restocking", slow).xp_per_hour == pytest.approx(
            self._rate("restocking", alone).xp_per_hour
        )

    def test_a_simultaneous_loop_divides_the_rolling_instead(self) -> None:
        one = self._rate("plain", gathering.SkillProfile(roll_ticks=10.0, depletes=False))
        many = self._rate(
            "plain",
            gathering.SkillProfile(
                roll_ticks=10.0, depletes=False, worked=3.0,
                parallel_kinds=frozenset({"K"}),
            ),
        )
        assert one.xp_per_hour * 3.0 == pytest.approx(many.xp_per_hour)

    def test_a_cycling_node_spends_it_on_the_duty_cycle(self) -> None:
        one = self._rate("cycling", gathering.SkillProfile(roll_ticks=4.0))
        two = self._rate("cycling", gathering.SkillProfile(roll_ticks=4.0, worked=2.0))
        assert two.duty > one.duty
        assert two.duty == 1.0


class TestTheShippedCountsAreConservative:
    """`worked_at` is a judgement per method, so the default has to be safe.

    Nothing publishes whether you can get back to a node before its restock
    finishes - it depends on the route, and the export knows only which chunk a
    thing is in - so the count is written by hand where somebody has decided,
    and is one everywhere else.
    """

    def test_a_stall_is_worked_one_at_a_time(self) -> None:
        # Ardougne market holds several stalls of one type and they are too far
        # apart to beat the restock, so the count stays one. It is also what
        # keeps the model reproducing the wiki's own per-stall maximum: a count
        # here would move every stall off the only figure that checks it.
        profile = gathering.PROFILES["Thieving"]
        assert (
            gathering.units_worked(
                gathering.Tables(), profile, "Thieving", "Stalls", "Fruit stall", 99
            )
            == 1.0
        )

    def test_only_the_rogues_castle_chest_is_rotated(self) -> None:
        assert set(gathering.PROFILES["Thieving"].worked_at) == {"chest (rogues' castle)"}

    def test_a_node_nobody_has_judged_waits_out_its_restock(self) -> None:
        tables = gathering.Tables(
            experience={"Thieving": {"somewhere": (100.0, "Chests")}},
            respawns={"somewhere": 60.0},
        )
        rate = gathering.rate_at(
            tables, {}, gathering.PROFILES["Thieving"], "Loot it", "Thieving",
            {"Level": 1, "Primary": True, "Objects": ["Somewhere"]}, 99,
        )
        assert rate is not None
        assert rate.xp_per_hour == pytest.approx(100.0 * 3600.0 / 60.0)


BUTTERFLIES = gathering.Tables(
    curves={
        "black warlock": (
            ("Butterfly net", 20.0, 296.0, 45, "confirmed"),
            ("Barehanded or Magic butterfly net", 40.0, 316.0, 45, "confirmed"),
        ),
        "moonlight moth": (("Butterfly net", 0.0, 276.0, 75, "confirmed"),),
    },
    experience={
        "Hunter": {
            "black warlock": (54.0, "Butterfly net"),
            "moonlight moth": (75.0, "Butterfly net"),
            "ruby harvest": (24.0, "Butterfly net"),
            "baby impling": (18.0, "Butterfly net"),
        }
    },
)

NETTING = gathering.SkillProfile(
    depletes=False,
    strict_kinds=True,
    roll_ticks_by_kind={"Butterfly net": 7.0},
    assumed_curves={"ruby harvest": "Black warlock"},
    refuses=frozenset({"baby impling"}),
)


def _netted(node: str, level: int, opens: int) -> gathering.NodeRate | None:
    return gathering.rate_at(
        BUTTERFLIES, {}, NETTING, f"Catch a ~|{node}|~", "Hunter",
        {"Level": opens, "Primary": True, "NPCs": [node.title()]}, level,
    )


class TestBorrowedCurves:
    def test_a_borrower_opens_where_its_donor_opens(self) -> None:
        # The whole construction: black warlock is worth 0.5664 of a catch at
        # its own level 45, so a creature unlocked at 15 is worth that at 15.
        donor = gathering.success_chance(45, 20.0, 296.0)
        borrowed = _netted("ruby harvest", 15, 15)
        assert borrowed is not None
        assert borrowed.chance == pytest.approx(donor, abs=1 / 256)

    def test_the_slope_is_kept_when_the_line_is_moved(self) -> None:
        # Same climb per level, thirty levels earlier.
        low = _netted("ruby harvest", 15, 15)
        high = _netted("ruby harvest", 45, 15)
        assert low is not None and high is not None
        assert high.chance - low.chance == pytest.approx(
            gathering.success_chance(75, 20.0, 296.0)
            - gathering.success_chance(45, 20.0, 296.0),
            abs=2 / 256,
        )

    def test_a_charted_creature_is_never_given_a_borrowed_curve(self) -> None:
        # `assumed_curves` fills a gap; it must not override a measurement.
        rate = _netted("moonlight moth", 99, 75)
        assert rate is not None
        assert rate.chance == gathering.success_chance(99, 0.0, 276.0)

    def test_the_donors_first_series_is_the_one_lent(self) -> None:
        # The unassisted tier, matching what `_tool_curve` falls back to - a
        # borrowed number should not assume the better net as well.
        borrowed = _netted("ruby harvest", 15, 15)
        assert borrowed is not None
        assert borrowed.chance != pytest.approx(
            gathering.success_chance(45, 40.0, 316.0), abs=1 / 512
        )

    def test_nothing_is_borrowed_without_an_entry(self) -> None:
        assert _netted("snowy knight", 99, 35) is None

    def test_an_impling_is_refused_though_it_shares_the_loop(self) -> None:
        # `Butterfly net` is a grab-bag: the interval is fitted against static
        # butterfly fields and an impling is a wandering rare spawn.
        assert _netted("baby impling", 99, 17) is None


class TestCurvesCarryTheirRequirement:
    def test_the_level_a_chart_was_drawn_from_survives_the_load(self) -> None:
        # Without it a borrowed curve cannot be re-anchored, since the whole
        # construction is "move this line to where the borrower opens".
        tables = gathering.load_tables(
            {"curves": {"Black warlock": [{"label": "Butterfly net", "low": 20, "high": 296, "requirement": 45}]}}
        )
        assert tables.curves["black warlock"][0] == ("Butterfly net", 20.0, 296.0, 45, "confirmed")

    def test_a_chart_with_no_requirement_reads_as_level_one(self) -> None:
        tables = gathering.load_tables(
            {"curves": {"X": [{"label": "a", "low": 1, "high": 2}]}}
        )
        assert tables.curves["x"][0][3] == 1


class TestBirdSnaring:
    """The one interval derived from another model's output rather than fitted.

    Worth pinning because it is three inferences deep - the borrowed butterfly
    curve, the butterfly interval, and the guide's combined figure - so a
    change to any of them should show up here rather than quietly move a band.
    """

    _TABLES = gathering.Tables(
        curves={"copper longtail": (("Copper longtail", 85.0, 390.0, 9, "confirmed"),)},
        experience={"Hunter": {"copper longtail": (61.0, "Bird snare")}},
        parallel={"Hunter": {"": ((1, 1.0), (20, 2.0), (80, 5.0))}},
    )

    def _rate(self, level: int) -> gathering.NodeRate:
        rate = gathering.rate_at(
            self._TABLES, {}, gathering.PROFILES["Hunter"],
            "Catch a ~|copper longtail|~", "Hunter",
            {"Level": 9, "Primary": True, "NPCs": ["Copper longtail"]}, level,
        )
        assert rate is not None
        return rate

    def test_it_reproduces_the_bird_half_of_the_guides_figure(self) -> None:
        # "up to 20,000 experience per hour with two traps" at levels 15-21 is
        # ruby harvests caught while two snares run; this model puts the
        # butterflies at 13,018 there, leaving 6,982 for the birds.
        assert self._rate(21).xp_per_hour == pytest.approx(6_982, rel=0.02)

    def test_it_beats_the_floor_at_the_bottom_of_the_skill(self) -> None:
        # The only thing between level 1 and the butterflies at 15.
        assert self._rate(9).xp_per_hour > 1_000.0

    def test_traps_divide_the_interval(self) -> None:
        # The step that is extrapolation past two traps - see the profile.
        assert self._rate(80).xp_per_hour / self._rate(21).xp_per_hour > 2.0


class TestProvenance:
    """Every success chance says where it came from, in three words.

    The point is that a reading, a construction and an invention are all
    numbers by the time they reach a rate, and nothing downstream could tell
    them apart afterwards - so it is recorded where it is decided.
    """

    _TABLES = gathering.Tables(
        curves={"black warlock": (("Butterfly net", 20.0, 296.0, 45, "confirmed"),)},
        experience={
            "Hunter": {
                "black warlock": (54.0, "Butterfly net"),
                "ruby harvest": (24.0, "Butterfly net"),
                "sunlight antelope": (380.0, "Pitfall"),
                "spined larupia": (180.0, "Pitfall"),
            }
        },
    )
    _PROFILE = gathering.SkillProfile(
        depletes=False,
        strict_kinds=True,
        roll_ticks_by_kind={"Butterfly net": 7.0, "Pitfall": 28.5},
        assumed_curves={"ruby harvest": "Black warlock"},
        fixed_chances={
            "sunlight antelope": (1.0, gathering.CONFIRMED),
            "spined larupia": (0.5, gathering.GUESS),
        },
    )

    def _rate(self, node: str, opens: int) -> gathering.NodeRate:
        rate = gathering.rate_at(
            self._TABLES, {}, self._PROFILE, "t", "Hunter",
            {"Level": opens, "Primary": True, "NPCs": [node]}, 99,
        )
        assert rate is not None
        return rate

    def test_a_chart_is_confirmed(self) -> None:
        assert self._rate("Black warlock", 45).provenance == gathering.CONFIRMED

    def test_a_borrowed_curve_is_inferred(self) -> None:
        assert self._rate("Ruby harvest", 15).provenance == gathering.INFERRED

    def test_prose_stating_the_odds_is_confirmed_too(self) -> None:
        # "players will always succeed in hunting sunlight antelopes" is a
        # reading, even though there is no chart to read it off.
        rate = self._rate("Sunlight antelope", 72)
        assert rate.chance == 1.0
        assert rate.provenance == gathering.CONFIRMED

    def test_a_made_up_number_says_so(self) -> None:
        rate = self._rate("Spined larupia", 31)
        assert rate.chance == 0.5
        assert rate.provenance == gathering.GUESS

    def test_it_survives_serialisation(self) -> None:
        assert self._rate("Spined larupia", 31).as_dict()["provenance"] == gathering.GUESS

    def test_a_fixed_chance_does_not_move_with_level(self) -> None:
        # There is no curve behind it, and pretending otherwise would dress a
        # guess up as a measurement.
        low = gathering.rate_at(
            self._TABLES, {}, self._PROFILE, "t", "Hunter",
            {"Level": 31, "Primary": True, "NPCs": ["Spined larupia"]}, 31,
        )
        assert low is not None
        assert low.chance == self._rate("Spined larupia", 31).chance

    def test_the_shipped_guesses_are_the_three_the_wiki_has_not_measured(self) -> None:
        guessed = {
            node
            for node, (_chance, source) in gathering.PROFILES["Hunter"].fixed_chances.items()
            if source == gathering.GUESS
        }
        assert guessed == {"spined larupia", "horned graahk", "sabre-toothed kyatt"}


class TestLoopOverride:
    """The calculator's `type` is a display choice; the export names the trap.

    Two rows needed this and neither is an edge case: a tropical wagtail is
    filed under no loop at all, and a white rabbit under `Other` beside an imp,
    which is a different activity entirely.
    """

    _TABLES = gathering.Tables(
        curves={
            "white rabbit": (("Flushing a rabbit hole", 190.0, 255.0, 27, "confirmed"),),
            "tropical wagtail": (("Tropical wagtail", 75.0, 370.0, 19, "confirmed"),),
        },
        experience={
            "Hunter": {
                "white rabbit": (144.0, "Other"),
                "tropical wagtail": (95.0, ""),
            }
        },
        parallel={"Hunter": {"": ((1, 1.0), (80, 5.0))}},
    )

    def _rate(self, node: str, opens: int) -> gathering.NodeRate | None:
        return gathering.rate_at(
            self._TABLES, {}, gathering.PROFILES["Hunter"], "t", "Hunter",
            {"Level": opens, "Primary": True, "NPCs": [node]}, 99,
        )

    def test_a_blank_loop_is_read_off_the_export_instead(self) -> None:
        assert self._rate("Tropical wagtail", 19) is not None

    def test_a_grab_bag_loop_is_overridden(self) -> None:
        assert self._rate("White rabbit", 27) is not None

    def test_a_borrowed_interval_caps_the_provenance(self) -> None:
        # Rabbit snaring has no published rate anywhere, so its cadence is box
        # trapping's - and a measured chance over a borrowed cadence is not a
        # measurement.
        rate = self._rate("White rabbit", 27)
        assert rate is not None
        assert rate.provenance == gathering.INFERRED

    def test_a_loop_with_its_own_evidence_keeps_confirmed(self) -> None:
        rate = self._rate("Tropical wagtail", 19)
        assert rate is not None
        assert rate.provenance == gathering.CONFIRMED

    def test_the_borrowed_loops_are_the_two_with_no_evidence(self) -> None:
        # Rabbit snaring and magic box trapping both take box trapping's
        # cadence, because nothing published prices either one. Every other
        # loop was fitted or derived against a figure of its own.
        assert gathering.PROFILES["Hunter"].inferred_loops == frozenset(
            {"Rabbit snare", "Magic box"}
        )


class TestSeriesMatchedToTheCreature:
    """A chart shared by a family is drawn once and carries a series each.

    The `Chinchompa` chart appears verbatim on all three chinchompa pages with
    Grey at 53, Red at 63 and Black at 73. Taking the first gave every one of
    them the grey series, which is certain at 99 where the other two are 0.895 -
    and the fitted box-trap interval absorbed the difference, so nothing in the
    ratios showed it.
    """

    _CHART = (
        ("Grey", 6.0, 268.0, 53, "confirmed"),
        ("Red", -78.0, 228.0, 63, "confirmed"),
        ("Black", -78.0, 228.0, 73, "confirmed"),
    )
    _TABLES = gathering.Tables(
        curves={"chinchompa (hunter)": _CHART, "black chinchompa (hunter)": _CHART},
        experience={
            "Hunter": {
                "chinchompa (hunter)": (198.4, "Box trap"),
                "black chinchompa (hunter)": (315.0, "Box trap"),
            }
        },
    )

    def _chance(self, node: str, opens: int) -> float:
        rate = gathering.rate_at(
            self._TABLES, {}, gathering.PROFILES["Hunter"], "t", "Hunter",
            {"Level": opens, "Primary": True, "NPCs": [node]}, 99,
        )
        assert rate is not None
        return rate.chance

    def test_each_creature_takes_the_series_drawn_for_it(self) -> None:
        assert self._chance("Chinchompa (Hunter)", 53) == gathering.success_chance(99, 6.0, 268.0)
        assert self._chance("Black chinchompa (Hunter)", 73) == gathering.success_chance(
            99, -78.0, 228.0
        )

    def test_the_grey_series_no_longer_prices_every_chinchompa(self) -> None:
        assert self._chance("Black chinchompa (Hunter)", 73) < self._chance(
            "Chinchompa (Hunter)", 53
        )

    def test_an_unmatched_level_still_falls_back_to_the_first(self) -> None:
        # A single-series chart has nothing else, and neither does a family
        # whose member opens at a level the chart does not draw.
        assert self._chance("Chinchompa (Hunter)", 41) == gathering.success_chance(
            99, 6.0, 268.0
        )


class TestBorrowTakesTheWorstSeries:
    def test_the_donors_weakest_series_is_the_one_lent(self) -> None:
        # An assumed number should be the pessimistic one, and "first" only
        # happened to mean that for the butterflies: the chinchompa chart opens
        # with grey, which is the easiest of its three.
        tables = gathering.Tables(
            curves={
                "chinchompa (hunter)": (
                    ("Grey", 6.0, 268.0, 53, "confirmed"),
                    ("Red", -78.0, 228.0, 63, "confirmed"),
                )
            },
            experience={"Hunter": {"ferret (hunter)": (115.0, "Box trap")}},
        )
        profile = dataclasses.replace(
            gathering.PROFILES["Hunter"],
            assumed_curves={"ferret (hunter)": "Chinchompa (Hunter)"},
        )
        rate = gathering.rate_at(
            tables, {}, profile, "t", "Hunter",
            {"Level": 27, "Primary": True, "NPCs": ["Ferret (Hunter)"]}, 27,
        )
        assert rate is not None
        # Red is worth less where it opens than grey is where grey opens, so
        # the borrower opens at Red's 63 rather than at Grey's 53.
        assert rate.chance == pytest.approx(
            gathering.success_chance(63, -78.0, 228.0), abs=1 / 256
        )
        assert rate.chance != pytest.approx(
            gathering.success_chance(53, 6.0, 268.0), abs=1 / 512
        )

    def test_the_box_trap_creatures_borrow_the_charted_chinchompa(self) -> None:
        # The ferret's page states the technique is shared and the trap says
        # the same for the rest, so all three uncharted box-trap creatures take
        # the one chart there is.
        borrowed = gathering.PROFILES["Hunter"].assumed_curves
        assert {
            borrowed[node]
            for node in ("ferret (hunter)", "embertailed jerboa", "letvek (hunter)")
        } == {"Chinchompa (Hunter)"}


class TestTracking:
    """Noose-wand tracking: one chart lent to five, and a checkable interval.

    The strongest evidence in the Hunter profile, and worth saying why: two of
    the five carry published rates and they sit 42 levels apart, so a single
    interval reproducing both is a real constraint rather than an exactly
    identified fit.
    """

    def test_the_four_uncharted_trails_borrow_the_charted_one(self) -> None:
        borrowed = gathering.PROFILES["Hunter"].assumed_curves
        assert {
            "common kebbit",
            "feldip weasel",
            "desert devil",
            "razor-backed kebbit",
        } <= set(borrowed)
        assert set(borrowed[node] for node in ("common kebbit", "desert devil")) == {
            "Polar kebbit"
        }

    def test_every_box_trap_creature_borrows_the_chinchompa(self) -> None:
        # The ferret's page states the technique is shared; the trap says the
        # same for the jerboa and the letvek.
        borrowed = gathering.PROFILES["Hunter"].assumed_curves
        assert {"ferret (hunter)", "embertailed jerboa", "letvek (hunter)"} <= set(borrowed)

    def test_tracking_is_not_a_multi_trap_loop(self) -> None:
        # You follow one trail at a time; there is no trap to set several of.
        assert "Tracking" not in gathering.PROFILES["Hunter"].parallel_kinds

    def test_a_borrowed_curve_is_reachable_through_a_monsters_field(self) -> None:
        # The jerboa names itself in `Monsters` where everything else uses
        # `NPCs`, and the borrow lookup has to see the same fields the curve
        # lookup does.
        tables = gathering.Tables(
            curves={"chinchompa (hunter)": (("Grey", 6.0, 268.0, 53, "confirmed"),)},
            experience={"Hunter": {"embertailed jerboa": (137.0, "Box trap")}},
        )
        rate = gathering.rate_at(
            tables, {}, gathering.PROFILES["Hunter"], "t", "Hunter",
            {"Level": 39, "Primary": True, "Monsters": ["Embertailed jerboa"]}, 99,
        )
        assert rate is not None
        assert rate.provenance == gathering.INFERRED


class TestNameFieldsAreOneList:
    """Every lookup that turns a challenge into a name reads the same fields.

    Three separate defects came from keeping four copies in step, all of them
    `Monsters` missing from one of them, and all of them silent: a method was
    simply refused, with no way to tell a gap from a bug.
    """

    _CHALLENGE = {"Level": 71, "Primary": True, "Monsters": ["Imp"]}
    _TABLES = gathering.Tables(
        curves={"imp": (("Imp", 0.0, 197.0, 71, "confirmed"),)},
        experience={"Hunter": {"imp": (450.0, "Other")}},
        parallel={"Hunter": {"": ((1, 1.0), (80, 5.0))}},
    )

    def test_a_monsters_only_challenge_reaches_every_lookup(self) -> None:
        # Experience, curve and loop all have to find it, and the imp names
        # itself in `Monsters` alone.
        rate = gathering.rate_at(
            self._TABLES, {}, gathering.PROFILES["Hunter"], "t", "Hunter",
            self._CHALLENGE, 99,
        )
        assert rate is not None
        assert rate.experience == 450.0
        assert rate.chance == gathering.success_chance(99, 0.0, 197.0)

    def test_the_loop_override_reaches_it_too(self) -> None:
        # Without this the imp keeps the calculator's `Other`, which has no
        # interval, and is refused for a reason that is not true.
        assert gathering.PROFILES["Hunter"].loop_at["imp"] == "Magic box"

    def test_a_borrowed_interval_still_caps_the_provenance(self) -> None:
        rate = gathering.rate_at(
            self._TABLES, {}, gathering.PROFILES["Hunter"], "t", "Hunter",
            self._CHALLENGE, 99,
        )
        assert rate is not None
        assert rate.provenance == gathering.INFERRED


class TestInfoboxExperienceFallback:
    """A creature's own infobox, where no calculator lists it.

    The letvek is in the game, on the Box trap page and in the export, and
    absent from `Module:Skill calc/Hunter` entirely - so "no experience row"
    was reporting a gap in one source rather than in the wiki.
    """

    _TABLES = gathering.Tables(
        curves={"chinchompa (hunter)": (("Grey", 6.0, 268.0, 53, "confirmed"),)},
        experience={"Hunter": {"ferret (hunter)": (115.2, "Box trap")}},
        skill_info={"Hunter": {"letvek (hunter)": (76, 208.5), "ferret (hunter)": (27, 115.2)}},
    )

    def _rate(self, node: str, opens: int) -> gathering.NodeRate | None:
        return gathering.rate_at(
            self._TABLES, {}, gathering.PROFILES["Hunter"], "t", "Hunter",
            {"Level": opens, "Primary": True, "NPCs": [node]}, 99,
        )

    def test_a_creature_no_calculator_lists_is_still_priced(self) -> None:
        rate = self._rate("Letvek (Hunter)", 76)
        assert rate is not None
        assert rate.experience == 208.5

    def test_the_calculator_still_wins_where_it_has_a_row(self) -> None:
        # Read as a fallback and never as an override: the calculator is the
        # one with the loop attached.
        rate = self._rate("Ferret (Hunter)", 27)
        assert rate is not None
        assert rate.experience == 115.2

    def test_a_fallback_row_carries_no_loop_of_its_own(self) -> None:
        # An infobox states a trap, not a calculator grouping, so the loop has
        # to come from `loop_at` - which is why the letvek has an entry there.
        assert gathering.PROFILES["Hunter"].loop_at["letvek (hunter)"] == "Box trap"


class TestStatedChanceOutranksAChart:
    """The one precedence that runs the other way, and why.

    A profile states a chance only where the chart is answering a different
    question. The sandworm is the case: its two series are the split between a
    bucket of sandworms and a bucket of sand, and they sum to one, so reading
    either as a success rate charges a failure for a dig that never fails.
    """

    _TABLES = gathering.Tables(
        curves={
            "sandworm castings": (
                ("Bucket of sandworms", 148.0, 178.0, 15, "confirmed"),
                ("Bucket of sand", 107.0, 77.0, 15, "confirmed"),
            )
        },
        experience={"Hunter": {"sandworm castings": (10.0, "")}},
    )

    def test_the_stated_chance_wins(self) -> None:
        rate = gathering.rate_at(
            self._TABLES, {}, gathering.PROFILES["Hunter"], "t", "Hunter",
            {"Level": 15, "Primary": True, "Objects": ["Sandworm castings"]}, 99,
        )
        assert rate is not None
        assert rate.chance == 1.0

    def test_the_two_series_really_do_sum_to_one(self) -> None:
        # The evidence for calling it a split rather than a success rate.
        worms = gathering.success_chance(15, 148.0, 178.0)
        sand = gathering.success_chance(15, 107.0, 77.0)
        assert worms + sand == pytest.approx(1.0, abs=0.01)

    def test_a_dig_is_five_ticks_and_twelve_thousand_an_hour(self) -> None:
        rate = gathering.rate_at(
            self._TABLES, {}, gathering.PROFILES["Hunter"], "t", "Hunter",
            {"Level": 15, "Primary": True, "Objects": ["Sandworm castings"]}, 99,
        )
        assert rate is not None
        assert rate.xp_per_hour == pytest.approx(12_000)


class TestLootStemKey:
    def test_an_output_named_loot_offers_the_creature_too(self) -> None:
        # `Stymphike loot` is the `Output`; the article is `Stymphike`.
        keys = gathering._join_keys(
            {"Output": "Stymphike loot"}, {}, gathering._NAME_FIELDS, "Hunter"
        )
        assert "Stymphike" in keys

    def test_the_plain_form_still_comes_first(self) -> None:
        keys = gathering._join_keys(
            {"Output": "Stymphike loot"}, {}, gathering._NAME_FIELDS, "Hunter"
        )
        assert keys.index("Stymphike loot") < keys.index("Stymphike")


class TestDeepSeaTrawling:
    """The shoals, and the constant three guides agree on.

    Every shoal rolls on the same cadence and states its own experience, so the
    only thing that had to be worked out was how many rolls an hour - and three
    of the four money-making guides put it at `9,880 x chance` within 4% of
    each other. Marlin is the fourth and does not fit, because its shoals are
    the rarest and the hour goes on sailing between them rather than on the
    roll at one.
    """

    _TABLES = gathering.Tables(
        curves={
            "bluefin shoal": (("Trawling net", -200.0, 24.0, 87, "confirmed"),),
            "haddock shoal": (("Trawling net", -200.0, 29.0, 73, "confirmed"),),
        },
        experience={"Fishing": {}},
        skill_info={"Fishing": {"bluefin shoal": (87, 220.5), "haddock shoal": (73, 128.5)}},
    )

    def _rate(self, node: str, opens: int) -> gathering.NodeRate:
        rate = gathering.rate_at(
            self._TABLES, {}, gathering.PROFILES["Fishing"], "t", "Fishing",
            {"Level": opens, "Primary": True, "Objects": [node]}, 99,
        )
        assert rate is not None
        return rate

    def test_a_shoal_is_priced_off_its_own_chart_and_experience(self) -> None:
        rate = self._rate("Bluefin shoal", 87)
        assert rate.experience == 220.5
        assert rate.roll_seconds == pytest.approx(2.43 * 0.6)

    def test_the_krill_experience_is_recovered_from_its_rod_figure(self) -> None:
        # It states only `skill1exp2`, and the rod pays exactly a fifth on all
        # five shoals that publish both.
        assert 22.5 * 5 == 112.5

    def test_marlin_is_slower_because_its_shoals_are_scarce(self) -> None:
        profile = gathering.PROFILES["Fishing"]
        assert profile.loop_at["marlin shoal"] == "Trawling (scarce)"
        assert (
            profile.roll_ticks_by_kind["Trawling (scarce)"]
            > profile.roll_ticks_by_kind["Trawling"]
        )

    def test_no_trip_is_charged_for_a_shoal(self) -> None:
        # Caught from a boat, and the guides quote it that way.
        assert self._rate("Haddock shoal", 73).bank_seconds_per_item == 0.0

    def test_every_shoal_shares_the_shallow_cadence_but_marlin(self) -> None:
        loops = gathering.PROFILES["Fishing"].loop_at
        shoals = [node for node in loops if node.endswith("shoal")]
        assert {loops[node] for node in shoals if node != "marlin shoal"} == {"Trawling"}


class TestTaskSpanIsTheLastJoinKey:
    """What a task calls itself, for the challenges that name nothing else.

    Two shapes needed it. `Catch a ~|raw bream|~` states only a level and a
    chunk, so no field offers a name at all; and `Mine a ~|gem rock|~` states
    the export's plural `Gem rocks` where the calculator lists the singular,
    so its experience never joined. Offered after every field, so it can add a
    join and never change one.
    """

    def test_a_challenge_naming_nothing_still_offers_its_span(self) -> None:
        keys = gathering._join_keys(
            {"Level": 20}, {}, gathering._NAME_FIELDS, "Fishing",
            "Catch a ~|raw bream|~",
        )
        assert keys[0] == "raw bream"

    def test_the_span_comes_after_every_field(self) -> None:
        keys = gathering._join_keys(
            {"Objects": ["Gem rocks"]}, {}, gathering._NAME_FIELDS, "Mining",
            "Mine a ~|gem rock|~",
        )
        assert keys.index("Gem rocks") < keys.index("gem rock")

    def test_no_task_leaves_the_keys_as_they_were(self) -> None:
        assert gathering._join_keys(
            {"Objects": ["Willow tree"]}, {}, gathering._NAME_FIELDS, "Woodcutting"
        ) == ("Willow tree", "Willow tree (Woodcutting)")


class TestBreamBorrowsTheLeechfin:
    def test_it_takes_the_leechfins_curve_and_its_own_experience(self) -> None:
        profile = gathering.PROFILES["Fishing"]
        assert profile.assumed_curves["raw bream"] == "Leechfin"
        assert profile.loop_at["raw bream"] == "Big net"

    def test_the_borrow_opens_where_the_bream_does(self) -> None:
        tables = gathering.Tables(
            curves={"leechfin": (("Leechfin", 30.0, 220.0, 78, "confirmed"),)},
            skill_info={"Fishing": {"raw bream": (20, 20.0)}},
        )
        rate = gathering.rate_at(
            tables, {}, gathering.PROFILES["Fishing"], "Catch a ~|raw bream|~",
            "Fishing", {"Level": 20, "Primary": True}, 20,
        )
        assert rate is not None
        assert rate.experience == 20.0
        assert rate.chance == pytest.approx(
            gathering.success_chance(78, 30.0, 220.0), abs=1 / 256
        )
        assert rate.provenance == gathering.INFERRED
