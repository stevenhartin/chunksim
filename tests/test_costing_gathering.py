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
from chunksim.store import cache


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

    def test_a_tree_offers_what_it_yields(self) -> None:
        # **Fourteen Forestry methods turned on this.** `Participate in
        # ~|Forestry events|~ while chopping oak trees` states
        # `Output: Anima-infused bark` - the event currency - so the only name
        # it offers for the tree is `Oak tree`, and no calculator row is called
        # that. They had a curve and a tool and were refused for want of a
        # numerator.
        keys = gathering._join_keys(
            {"Objects": ["Oak tree"], "Output": "Anima-infused bark"},
            {}, gathering._NAME_FIELDS, "Woodcutting",
        )
        assert "Oak logs" in keys

    def test_another_skill_does_not_grow_logs(self) -> None:
        keys = gathering._join_keys(
            {"Objects": ["Oak tree"]}, {}, gathering._NAME_FIELDS, "Mining"
        )
        assert not any("logs" in key for key in keys)

    def test_a_plural_is_offered_for_every_skill(self) -> None:
        # A spelling rule, not a mechanic: the export writes
        # `Mine a size-1 ~|shooting star|~` and the chart is on
        # `Shooting Stars`. Measured over the whole export it changes no
        # existing join and adds those nine.
        keys = gathering._join_keys(
            {"Objects": ["Shooting star#landing site"]}, {}, gathering._NAME_FIELDS, "Mining"
        )
        assert "Shooting stars" in keys

    def test_another_skill_is_left_alone(self) -> None:
        # The guard is the skill, not the name: widened to every skill, every
        # join in the project grew a `Willow tree rocks`.
        keys = gathering._join_keys(
            {"Objects": ["Willow tree"]}, {}, gathering._NAME_FIELDS, "Woodcutting"
        )
        assert not any("rock" in key for key in keys)

    def test_a_bare_material_reaches_the_rock_page(self) -> None:
        # `Mine ~|limestone|~` states `Output: Limestone` and the wiki charts
        # `Limestone rock`. Gated on the *name* carrying a suffix - which is
        # what this was first - that join never happened.
        keys = gathering._join_keys(
            {"Output": "Limestone"}, {}, gathering._NAME_FIELDS, "Mining"
        )
        assert "Limestone rock" in keys

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
            refuses={"raw lobster": "the kind is a grab-bag"},
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


class TestAnInfoboxCanStateItsLoop:
    """`strict_kinds` needs a loop, and for Thieving the calculator has none."""

    _TABLES = gathering.Tables(
        curves={"somebody": (("", 90.0, 200.0, 20, gathering.CONFIRMED),)},
        skill_info={"Thieving": {"somebody": (20, 22.2)}},
        skill_loops={"Thieving": {"somebody": "Pickpocket"}},
    )
    _PROFILE = gathering.SkillProfile(
        depletes=False,
        strict_kinds=True,
        roll_ticks_by_kind={"Pickpocket": 2.0},
        fail_seconds=3.6,
    )

    def _rate(self, tables: gathering.Tables) -> gathering.NodeRate | None:
        return gathering.rate_at(
            tables, {}, self._PROFILE, "Pickpocket them", "Thieving",
            {"NPCs": ["somebody"], "Level": 20}, 99,
        )

    def test_experience_and_a_loop_together_price_it(self) -> None:
        rate = self._rate(self._TABLES)
        assert rate is not None and rate.xp_per_hour > 0
        assert rate.experience == pytest.approx(22.2)

    def test_experience_alone_does_not(self) -> None:
        # **The measurement that redirected this.** Reading 240 Thieving
        # infoboxes for their experience gained nothing at all, because a node
        # priced from one carried no loop and `strict_kinds` refuses that - a
        # loop is what says whether you roll every 2 ticks or every 15.5.
        loopless = dataclasses.replace(self._TABLES, skill_loops={})
        assert self._rate(loopless) is None

    def test_a_calculator_row_still_wins(self) -> None:
        # The infobox is the fallback, so a skill the calculator describes is
        # untouched by any of this.
        both = dataclasses.replace(
            self._TABLES, experience={"Thieving": {"somebody": (99.0, "Pickpocket")}}
        )
        rate = self._rate(both)
        assert rate is not None and rate.experience == pytest.approx(99.0)


@pytest.mark.real_cache
class TestThePickpocketGuideIsAFlatCadence:
    """**`wiki:pickpockets` has no success chance in it, and that is measured.**

    It is the reason the model disagrees with that source in both directions,
    and the reason neither disagreement is a defect to fix. Pinned here so a
    later "the model reads 2.3x fast on pickpockets" cannot be answered by
    moving `fail_seconds` to match a figure that prices a 94%-success target
    and a 59% one at the same seconds per attempt.
    """

    def test_every_row_is_experience_times_one_cadence(
        self, real_export: ChunkInfo
    ) -> None:
        from chunksim.costing import inputs

        blobs = inputs.load_reference()
        scraped, _ = inputs.load_heuristics(real_export, None, blobs)
        families = gathering.expand_families(real_export)
        implied = []
        for task, challenge in (real_export.challenges.get("Thieving") or {}).items():
            if not isinstance(challenge, dict) or not task.startswith("Pickpocket"):
                continue
            rate = (scraped.training.get(task) or {}).get("Thieving")
            if rate is None or rate.source != "wiki:pickpockets":
                continue
            paid, _kind = gathering._experience_for(
                blobs.gathering, families, "Thieving", challenge, task
            )
            if paid > 0:
                implied.append(rate.value / paid)
        assert len(implied) > 10, "no pickpocket rows joined - check the source name"
        # 3600 / 3.5 seconds, on every one of them.
        for cadence in implied:
            assert cadence == pytest.approx(3600.0 / 3.5, rel=0.03)


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

    **Mining is the one skill that has since reached zero, and it is out of the
    parametrised list rather than silently passing.** That is the outcome this
    class exists to make someone justify, so: its three scrape-only methods
    were shooting stars, volcanic ash and infernal shale, and each was closed
    by finding the mechanic rather than by trusting the guide. Stars have a
    real `{{Skilling success chart}}` and the model reproduces the page's own
    30,000/hr at level 90. Ash piles publish a certainty, a 1/4 depletion
    chance and a 30-second respawn, and the walk between them was recovered
    from the page's 6,500 ash an hour. Infernal shale rocks are priced as
    ordinary mining because their published figures are all Jim's wet cloth,
    which this model declines to represent exactly as it declines 3-tick
    granite.

    **The general claim is untouched**: the scrape still owns Forestry,
    Pyramid Plunder, Wintertodt, the Stranglewood and barbarian fishing, and
    the other four skills still assert it. What Mining shows is that "only the
    scrape reaches it" was a statement about *those three pages*, not a law -
    and the way to move one out of that set is to read the page, not to delete
    the stage.
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
        "skill", ["Fishing", "Hunter", "Thieving", "Woodcutting"]
    )
    def test_each_source_reaches_methods_the_other_cannot(
        self, real_export: ChunkInfo, skill: str
    ) -> None:
        modelled, scrape_only = self._split(real_export, skill)
        assert modelled > 0, f"the model prices nothing for {skill}"
        assert scrape_only > 0, (
            f"every {skill} method the scrape prices is now modelled - if that is "
            "really true the guide stage could go, but check it is not a join "
            "regression first, and record it the way Mining is recorded below"
        )

    def test_mining_alone_has_closed_the_gap(self, real_export: ChunkInfo) -> None:
        """Mining's exception, asserted rather than assumed.

        Pinned in both directions on purpose. If it goes back above zero the
        model has *lost* a method and this says so; if the model stops pricing
        anything the first assertion catches that instead. Read the class
        docstring before changing either number.
        """
        modelled, scrape_only = self._split(real_export, "Mining")
        assert modelled > 0
        assert scrape_only == 0, (
            "Mining has a scrape-only method again - the model used to price "
            "every one of them, so this is a regression to find rather than a "
            "number to update"
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

    Four layers and one number; what the number *buys* is `rate_at`'s
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

    def test_a_flat_loop_limit_beats_the_table(self) -> None:
        """**A limit the game states without a level cannot go in the
        table.** The deadfall's is "increased from 1 to 2" and nothing more,
        while `Tables.parallel` describes the four snare-and-box loops - so
        left to fall through, a deadfall would be handed five traps at level
        80, which the game does not allow."""
        profile = gathering.SkillProfile(
            parallel_kinds=frozenset({"Box trap", "Deadfall"}),
            worked_by_kind={"Deadfall": 2.0},
        )

        assert self._units(profile, "Deadfall", "Wild kebbit", 99) == 2.0
        assert self._units(profile, "Deadfall", "Wild kebbit", 1) == 2.0
        assert self._units(profile, "Box trap", "Ferret", 99) == 5.0, "table untouched"

    def test_a_per_node_count_still_beats_a_flat_loop_limit(self) -> None:
        """The same update states the exception in the same breath - "maniacal
        monkeys remain limited to one trap" - and it is also the row the
        deadfall interval is fitted against, so it has to stay at one."""
        profile = gathering.SkillProfile(
            parallel_kinds=frozenset({"Deadfall"}),
            worked_by_kind={"Deadfall": 2.0},
            worked_at={"maniacal monkey (hunter)": 1.0},
        )

        assert self._units(profile, "Deadfall", "Maniacal monkey (Hunter)", 99) == 1.0


class TestCurvesThisProjectSuppliesItself:
    """The two sources below a real chart, and what each refuses."""

    #: A stand-in for Mining's ore ladder: three rungs, decaying.
    _TABLES = gathering.Tables(
        curves={
            "low rock": (("Low rock", 100.0, 350.0, 10, "confirmed"),),
            "mid rock": (("Mid rock", 16.0, 100.0, 30, "confirmed"),),
            "high rock": (("High rock", 2.0, 25.0, 70, "confirmed"),),
        },
        experience={"S": {"new rock": (50.0, "K")}},
    )
    _LADDER = ("low rock", "mid rock", "high rock")

    def _profile(self, **extra: object) -> gathering.SkillProfile:
        return gathering.SkillProfile(roll_ticks=2.0, **extra)  # type: ignore[arg-type]

    def _rate(
        self, profile: gathering.SkillProfile, level: int, opens: int = 50
    ) -> gathering.NodeRate | None:
        return gathering.rate_at(
            self._TABLES, {}, profile, "t", "S",
            {"Level": opens, "Primary": True, "Objects": ["New rock"]}, level,
        )

    def test_an_interpolated_curve_sits_between_its_neighbours(self) -> None:
        profile = self._profile(
            interpolated=frozenset({"new rock"}), curve_ladder=self._LADDER
        )
        got = self._rate(profile, 99)
        assert got is not None
        below = gathering.success_chance(99, 16.0, 100.0)
        above = gathering.success_chance(99, 2.0, 25.0)
        assert above < got.chance < below

    def test_an_interpolated_curve_is_never_confirmed(self) -> None:
        # It is built from measurements of the rocks either side and of nothing
        # about this one, which is exactly what INFERRED means.
        profile = self._profile(
            interpolated=frozenset({"new rock"}), curve_ladder=self._LADDER
        )
        got = self._rate(profile, 99)
        assert got is not None and got.provenance == gathering.INFERRED

    def test_a_rung_at_the_same_level_wins_outright(self) -> None:
        # Daeyalt opens at exactly silver's level. Taking that chart beats
        # interpolating across the ladder's one discontinuity.
        profile = self._profile(
            interpolated=frozenset({"new rock"}), curve_ladder=self._LADDER
        )
        got = self._rate(profile, 99, opens=30)
        assert got is not None
        assert got.chance == pytest.approx(gathering.success_chance(99, 16.0, 100.0))

    def test_a_level_off_the_end_of_the_ladder_is_refused(self) -> None:
        # Extrapolating past the hardest rung would be inventing a rock harder
        # than the hardest one there is.
        profile = self._profile(
            interpolated=frozenset({"new rock"}), curve_ladder=self._LADDER
        )
        assert self._rate(profile, 99, opens=90) is None
        assert self._rate(profile, 99, opens=5) is None

    def test_geometric_interpolation_sits_below_the_linear_one(self) -> None:
        # The whole reason it is geometric: the ladder decays, so a straight
        # line between two rungs sits above the curve every time. The error is
        # one-sided, which is what the hold-out test measured.
        assert gathering._geometric(16.0, 2.0, 0.5) < (16.0 + 2.0) / 2

    def test_stated_experience_overrides_the_tables(self) -> None:
        # **Not a better estimate of the same quantity - a different one.**
        # `{{Mining info}}` writes sunstone as `xp = 23-28`, the scrape takes
        # the low end, and 28 is what the momentum the curve assumes actually
        # pays. Layering it under the tables would price every swing as though
        # momentum never happened.
        profile = self._profile(
            stated_curves={"new rock": (60.0, 240.0)},
            stated_experience={"new rock": 80.0},
        )
        got = self._rate(profile, 99)
        assert got is not None and got.experience == 80.0

    def test_a_stated_curve_outranks_an_interpolated_one(self) -> None:
        # Recovered from this node's own published rates, against a guess from
        # its neighbours - the first is about this rock and the second is not.
        profile = self._profile(
            stated_curves={"new rock": (60.0, 240.0)},
            interpolated=frozenset({"new rock"}),
            curve_ladder=self._LADDER,
        )
        got = self._rate(profile, 99)
        assert got is not None
        assert got.chance == pytest.approx(gathering.success_chance(99, 60.0, 240.0))

    def test_a_real_chart_outranks_both(self) -> None:
        profile = self._profile(
            stated_curves={"mid rock": (60.0, 240.0)},
            interpolated=frozenset({"mid rock"}),
            curve_ladder=self._LADDER,
        )
        got = gathering.rate_at(
            dataclasses.replace(
                self._TABLES, experience={"S": {"mid rock": (50.0, "K")}}
            ),
            {}, profile, "t", "S",
            {"Level": 30, "Primary": True, "Objects": ["Mid rock"]}, 99,
        )
        assert got is not None and got.provenance == gathering.CONFIRMED

    def test_a_node_naming_neither_is_still_refused(self) -> None:
        assert self._rate(self._profile(), 99) is None

    def test_a_stated_interval_is_used_where_no_tool_applies(self) -> None:
        # A soil spot is dug with a trowel, and Mining is priced off pickaxe
        # intervals - so the tool lookup found nothing and a four-tick action
        # was refused outright.
        profile = gathering.SkillProfile(
            tool_axis="interval",
            fixed_chances={"new rock": (1.0, gathering.CONFIRMED)},
            fixed_interval={"new rock": 4.0},
            endless=frozenset({"new rock"}),
        )
        got = self._rate(profile, 99)
        assert got is not None
        assert got.xp_per_hour == pytest.approx(50.0 * 3600.0 / (4.0 * 0.6))

    def test_a_stated_interval_beats_the_tool_where_both_apply(self) -> None:
        # An amalgamation averages 2.5 ticks whoever swings at it.
        tables = dataclasses.replace(self._TABLES, tool_ticks={"Dragon pickaxe": 2.83})
        profile = gathering.SkillProfile(
            tool_axis="interval",
            fixed_chances={"new rock": (1.0, gathering.CONFIRMED)},
            fixed_interval={"new rock": 2.5},
            endless=frozenset({"new rock"}),
        )
        got = gathering.rate_at(
            tables, {}, profile, "t", "S",
            {"Level": 50, "Primary": True, "Objects": ["New rock"]}, 99,
            tool="Dragon pickaxe",
        )
        assert got is not None
        assert got.roll_seconds == pytest.approx(2.5 * 0.6)


class TestNamesNoRuleBridges:
    def test_an_alias_reaches_the_page_the_wiki_wrote_it_up_on(self) -> None:
        # Upstream puts the qualifier where the wiki puts the noun:
        # `Rocks (Barronite)` against `Barronite rocks`. No rewrite recovers
        # that, and one general enough to would match far more than it should.
        keys = gathering._join_keys(
            {"Objects": ["Rocks (Barronite)"]}, {}, gathering._NAME_FIELDS, "Mining"
        )
        assert "Barronite rocks" in keys

    def test_a_named_state_reaches_the_one_page_it_is_a_state_of(self) -> None:
        # `Kharidian cactus (Healthy)` is the wiki's `Kharidian cactus`, whose
        # infobox reads `version = Healthy` - upstream is naming a version of
        # one page, not a second object.
        keys = gathering._join_keys(
            {"Objects": ["Kharidian cactus (Healthy)"]},
            {}, gathering._NAME_FIELDS, "Woodcutting",
        )
        assert "Kharidian cactus" in keys

    def test_the_general_rule_it_replaces_would_have_been_wrong(self) -> None:
        # **Why this is an alias and not a trailing-parenthesis strip.** That
        # rule gains exactly two joins across the export and the other one is
        # false: `Guard (H.A.M. storeroom)` is level 20 for 22.2 experience
        # where the plain `Guard` is level 40 for 46.8. Nothing here may bridge
        # the two, by any route.
        keys = gathering._join_keys(
            {"NPCs": ["Guard (H.A.M. storeroom)"]},
            {}, gathering._NAME_FIELDS, "Thieving",
        )
        assert "Guard" not in keys

    def test_an_alias_is_a_whole_name_and_not_a_pattern(self) -> None:
        # Seven entries is a vocabulary gap; a rule wearing a dict would be
        # twenty, and each of these is one object with two spellings.
        assert set(gathering._ALIASES) == {
            "rocks (barronite)",
            "crystals (ancient essence)",
            "kharidian cactus (healthy)",
            "al-kharid warrior",
            "guard (h.a.m. storeroom)",
            "chest (chaos druid tower)",
            "ore stall",
            "underground pass",
        }

    def test_an_aliased_page_is_still_confirmed(self) -> None:
        # The point of doing this in the join rather than through
        # `assumed_curves`: a page reached under a different name is still that
        # page, and calling it INFERRED would say something untrue.
        tables = gathering.Tables(
            curves={"barronite rocks": (("Barronite rock", 80.0, 100.0, 14, "confirmed"),)},
            experience={"Mining": {"barronite rocks": (16.0, "")}},
        )
        got = gathering.rate_at(
            tables, {}, gathering.SkillProfile(roll_ticks=4.0), "t", "Mining",
            {"Level": 14, "Primary": True, "Objects": ["Rocks (Barronite)"]}, 99,
        )
        assert got is not None and got.provenance == gathering.CONFIRMED

    def test_a_refusal_matches_any_name_the_challenge_offers(self) -> None:
        # **A refusal is about the method, not about the name a curve happened
        # to resolve under.** The sunstone monolith states `Output: Sunstone`,
        # which the rock rewrite turns into `Sunstone rocks` - so it reached
        # the rocks' curve and priced at 43,864/hr, being a different object.
        # Refusing on the resolved node cannot say that; the resolved node is
        # the rocks'.
        tables = gathering.Tables(
            curves={"sunstone rocks": (("Sunstone", 200.0, 255.0, 50, "confirmed"),)},
            experience={"Mining": {"sunstone rocks": (28.0, "")}},
        )
        challenge = {
            "Level": 50, "Primary": True,
            "Objects": ["Sunstone monolith"], "Output": "Sunstone",
        }
        priced = gathering.SkillProfile(roll_ticks=4.0)
        assert gathering.rate_at(
            tables, {}, priced, "t", "Mining", challenge, 99
        ) is not None
        refusing = dataclasses.replace(
            priced, refuses={"sunstone monolith": "a quest-line object"}
        )
        assert gathering.rate_at(
            tables, {}, refusing, "t", "Mining", challenge, 99
        ) is None

    def test_the_rock_rewrite_can_make_two_methods_share_a_name(self) -> None:
        # **The trap the widened refusal set, caught by a fit that produced no
        # rows at all.** `Mine an ~|infernal shale deposit|~` states
        # `Output: Infernal shale`, which the rock rewrite turns into
        # `Infernal shale rocks` - the *other* method's name. So refusing the
        # rocks refused the deposit beside them. Anything keyed by name has to
        # know this is possible.
        keys = gathering._join_keys(
            {"Objects": ["Infernal shale deposit"], "Output": "Infernal shale"},
            {}, gathering._NAME_FIELDS, "Mining",
        )
        assert "Infernal shale rocks" in keys

    def test_the_alias_list_stays_short(self) -> None:
        # A handful is a vocabulary gap; twenty would mean a rule is missing.
        assert len(gathering._ALIASES) <= 10

    def test_an_alias_supplies_and_never_displaces(self) -> None:
        """**The hazard of `_ALIASES` is that it redirects every lookup, not
        just the one that was short.** `Shop Counter (gems)` needed a restock
        the stall table files under `Gem stall (Mor Ul Rek)`, and aliasing the
        name would have taken the *calculator's* 160 experience for that row
        over the 408 both its own infobox and the stall table state - so its
        restock is read off its own page instead. Every alias kept here was
        checked for this: the original name is offered first, so an alias can
        only fill what nothing else answered."""
        assert "shop counter (gems)" not in gathering._ALIASES
        assert "shop counter (ore)" not in gathering._ALIASES
        keys = gathering._join_keys(
            {"Objects": ["Ore stall"]}, {}, gathering._NAME_FIELDS, "Thieving"
        )
        assert keys.index("Ore stall") < keys.index("Ore stall (Mor Ul Rek)")


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

    def test_a_node_that_never_depletes_pays_only_its_roll(self) -> None:
        # The rune essence rock: no respawn to share, no hop to anywhere.
        charged = gathering.SkillProfile(roll_ticks=2.0, node_seconds=5.0, hops=True)
        endless = dataclasses.replace(charged, endless=frozenset({"restocking"}))
        rate = self._rate("restocking", endless)
        assert rate.xp_per_hour == pytest.approx(100.0 * 3600.0 / (2.0 * 0.6))
        assert rate.xp_per_hour > self._rate("restocking", charged).xp_per_hour

    def test_a_yield_is_shared_over_what_the_depletion_paid_for(self) -> None:
        # **A rock is not always one ore.** Rubium hands over seven splinters
        # before it goes, so its 35.4-second respawn is charged once per seven
        # rather than once per splinter - priced the other way it read
        # 9,153/hr against a published 39,000.
        one = gathering.SkillProfile(roll_ticks=2.0, worked=1.0)
        seven = dataclasses.replace(one, yields={"restocking": 7.0})
        assert self._rate("restocking", seven).xp_per_hour == pytest.approx(
            self._rate("restocking", one).xp_per_hour * 7.0
        )

    def test_a_stated_cycle_replaces_the_respawn_rather_than_joining_it(self) -> None:
        # **The bug this caught, and it only exists for a node that states
        # both.** A duty cycle spends the wait as a share of the hour and a
        # restock floor spends it per resource; charged together, calcified
        # rocks sat flat at 11,880/hr while the cycle said there was no wait at
        # all. No tree ever hit it - the wiki gives a tree one or the other.
        cycling = gathering.SkillProfile(
            roll_ticks=2.0, stated_cycles={"restocking": (70.0, 30.0)}, worked=3.0
        )
        rate = self._rate("restocking", cycling)
        assert rate.duty == pytest.approx(1.0)
        assert rate.xp_per_hour == pytest.approx(100.0 * 3600.0 / (2.0 * 0.6))

    def test_a_per_node_walk_replaces_the_skill_default(self) -> None:
        # **`node_seconds` is one tick because it was calibrated on a cluster.**
        # Ash piles are sixteen spots over a volcano and the running is the
        # method; charged the iron-rock tick they read 14,400/hr against a
        # published 10,833.
        # `worked` high enough that the fixture's 60-second respawn cannot
        # bind, so what is left to measure is the walk.
        near = gathering.SkillProfile(
            roll_ticks=2.0, node_seconds=0.6, hops=True, worked=100.0
        )
        far = dataclasses.replace(near, node_seconds_at={"restocking": 6.5})
        assert self._rate("restocking", far).xp_per_hour < self._rate(
            "restocking", near
        ).xp_per_hour

    def test_a_recovered_walk_caps_the_provenance(self) -> None:
        # A confirmed chance divided by a fitted walk is not a confirmed rate.
        profile = gathering.SkillProfile(
            roll_ticks=2.0,
            node_seconds_at={"restocking": 6.5},
            hops=True,
            worked=100.0,
            fixed_chances={"restocking": (1.0, gathering.CONFIRMED)},
        )
        assert self._rate("restocking", profile).provenance == gathering.INFERRED

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


class TestCuttingJungle:
    """The one activity whose cadence is the level's, not the tool's.

    All three jungle pages carry the same sentence: "At Woodcutting level 10,
    players cut jungle in 16 tick intervals. Every 10 woodcutting levels the
    time to cut is decreased by 1 tick, until at 90 Woodcutting players cut at
    a speed of 8 ticks." The machete is still the chance - four charted series
    of it.
    """

    _TABLES = gathering.Tables(
        curves={"jungle": (("Plain Machete", 49.0, 169.0, 10, gathering.CONFIRMED),)},
        skill_info={"Woodcutting": {"jungle": (10, 32.0)}},
    )
    _PROFILE = gathering.SkillProfile(
        roll_ticks=4.0,
        tool_axis="chance",
        stepped_interval={"jungle": gathering._JUNGLE_TICKS},
    )

    def _rate(self, level: int, profile: gathering.SkillProfile) -> gathering.NodeRate:
        rate = gathering.rate_at(
            self._TABLES, {}, profile, "Chop it", "Woodcutting",
            {"Objects": ["jungle"], "Level": 10}, level,
        )
        assert rate is not None
        return rate

    def test_the_table_transcribes_the_sentence(self) -> None:
        steps = dict(gathering._JUNGLE_TICKS)
        assert steps[10] == 16.0 and steps[90] == 8.0
        assert [steps[lvl] for lvl in range(10, 100, 10)] == [
            16.0, 15.0, 14.0, 13.0, 12.0, 11.0, 10.0, 9.0, 8.0
        ]

    def test_the_interval_reads_the_level(self) -> None:
        assert self._rate(10, self._PROFILE).roll_seconds == pytest.approx(16 * 0.6)
        assert self._rate(50, self._PROFILE).roll_seconds == pytest.approx(12 * 0.6)
        assert self._rate(99, self._PROFILE).roll_seconds == pytest.approx(8 * 0.6)

    def test_it_beats_the_skill_cadence_rather_than_joining_it(self) -> None:
        # Without the table the roll is Woodcutting's flat four ticks, which is
        # twice as fast as jungle ever gets and four times as fast as it opens.
        flat = dataclasses.replace(self._PROFILE, stepped_interval={})
        assert self._rate(99, flat).roll_seconds == pytest.approx(4 * 0.6)
        assert self._rate(10, self._PROFILE).roll_seconds > self._rate(
            99, self._PROFILE
        ).roll_seconds

    def test_a_patch_is_four_sections(self) -> None:
        # "Jungle is cut in four sections, and once all four sections are cut
        # the jungle becomes depleted."
        profile = gathering.PROFILES["Woodcutting"]
        for node in ("light jungle", "medium jungle", "dense jungle"):
            assert profile.yields[node] == 4.0
            assert profile.stepped_interval[node] == gathering._JUNGLE_TICKS


class TestASharedChartKeepsItsToolTiers:
    """Why juniper does not go through `assumed_curves`.

    That mechanism takes the donor's worst series and moves it, which is right
    where the series are three creatures and wrong where they are nine axes:
    it would make a tree's rate the same whatever you swing, which is the one
    thing a tree's chart exists to say.
    """

    _TABLES = gathering.Tables(
        curves={
            "maple tree": (
                ("Bronze", 8.0, 25.0, 45, gathering.CONFIRMED),
                ("Dragon", 30.0, 93.0, 61, gathering.CONFIRMED),
            )
        },
        experience={"Woodcutting": {"juniper": (35.0, "Regular")}},
    )
    _PROFILE = gathering.SkillProfile(
        roll_ticks=4.0,
        tool_axis="chance",
        tool_tiers=True,
        shared_curves={"juniper": "Maple tree"},
    )

    def _rate(self, tool: str) -> gathering.NodeRate:
        rate = gathering.rate_at(
            self._TABLES, {}, self._PROFILE, "Chop it", "Woodcutting",
            {"Objects": ["juniper"], "Level": 42}, 99, tool=tool,
        )
        assert rate is not None
        return rate

    def test_the_axe_still_decides(self) -> None:
        assert self._rate("Dragon axe").chance > self._rate("Bronze axe").chance

    def test_it_spends_the_donors_own_numbers(self) -> None:
        assert self._rate("Dragon axe").chance == pytest.approx(
            gathering.success_chance(99, 30.0, 93.0)
        )

    def test_a_shared_chart_is_inferred(self) -> None:
        # The shape is a measurement of something else, so it may not claim to
        # be a reading of this.
        assert self._rate("Dragon axe").provenance == gathering.INFERRED

    def test_an_uncharted_donor_refuses_rather_than_falls_through(self) -> None:
        # A donor that stopped being charted must read as the entry naming it
        # being wrong, not as this node quietly losing its rate to some later
        # branch.
        profile = dataclasses.replace(
            self._PROFILE, shared_curves={"juniper": "Nothing tree"}
        )
        assert gathering._shared_curve(
            self._TABLES, profile, {}, {"Objects": ["juniper"]}, "Woodcutting", ""
        ) is None


class TestTheJuniperTree:
    """Every half of the loop is read; only the chance is assumed."""

    def test_a_depletion_covers_sixteen_logs(self) -> None:
        # "Mature juniper trees have a 1 in 16 chance of depleting when
        # receiving a log."
        assert gathering.PROFILES["Woodcutting"].yields["mature juniper tree"] == 16.0

    def test_the_chance_is_the_one_thing_borrowed(self) -> None:
        profile = gathering.PROFILES["Woodcutting"]
        assert profile.shared_curves["mature juniper tree"] == "Maple tree"
        # The roll is the skill's own four ticks, which the page states too, so
        # nothing about the cadence is assumed alongside it.
        assert "mature juniper tree" not in profile.fixed_interval
        assert "mature juniper tree" not in profile.stepped_interval


class TestTheChambersSapling:
    """A payout that climbs, which is the third thing a level can buy here.

    The wiki gives the table and two twitter citations give the formulas
    behind it. This asserts the formulas, because the table has an error in it
    and the formulas are what catch it.
    """

    @staticmethod
    def _xp(k: int) -> float:
        """`30 * H_k` - what one chop pays for `k` kindling."""
        return 30.0 * sum(1.0 / i for i in range(1, k + 1))

    @staticmethod
    def _cap(level: int) -> int:
        """Mod Ash: "the max is your visible Woodcutting level divided by 12"."""
        return max(1, min(8, level // 12))

    def _average(self, level: int) -> float:
        """Mean over "a random number 0-max inclusive ... 0 ... treated as 1"."""
        cap = self._cap(level)
        return sum(self._xp(max(1, roll)) for roll in range(cap + 1)) / (cap + 1)

    @pytest.mark.parametrize(
        "kindling,published",
        [(1, 30.0), (2, 45.0), (3, 55.0), (4, 62.5), (5, 68.5), (6, 73.5)],
    )
    def test_the_harmonic_formula_is_the_published_column(
        self, kindling: int, published: float
    ) -> None:
        assert self._xp(kindling) == pytest.approx(published)

    @pytest.mark.parametrize("kindling,published", [(7, 77.7), (8, 81.5)])
    def test_the_last_two_rows_are_the_wiki_truncating(
        self, kindling: int, published: float
    ) -> None:
        # 77.7857 and 81.5357 shown to one decimal, not a different formula.
        assert self._xp(kindling) == pytest.approx(published, abs=0.09)
        assert self._xp(kindling) > published

    def test_the_shipped_table_is_the_average_at_each_step(self) -> None:
        for level, paid in gathering._SAPLING_EXPERIENCE:
            assert paid == pytest.approx(self._average(level))

    @pytest.mark.parametrize(
        "level,published",
        [(1, 30.0), (24, 35.0), (36, 40.0), (48, 44.5), (60, 48.5), (72, 52.0714)],
    )
    def test_it_reproduces_the_wikis_own_average(
        self, level: int, published: float
    ) -> None:
        assert self._average(level) == pytest.approx(published, abs=0.0001)

    def test_the_wikis_kindling_column_has_one_typo(self) -> None:
        # **The reason this table is computed and not transcribed.** Its
        # avg-kindling column reads 2.2667 at level 60; the distribution gives
        # 2.6667, and the wiki's *own* 48.5 experience on that row is what
        # settles it, since only the correct one pays that.
        rolls = [max(1, roll) for roll in range(self._cap(60) + 1)]
        assert sum(rolls) / len(rolls) == pytest.approx(2.6667, abs=0.0001)
        assert self._average(60) == pytest.approx(48.5)

    def test_a_step_holds_until_the_next_one(self) -> None:
        table = gathering._SAPLING_EXPERIENCE
        assert gathering.units_at(table, 23) == pytest.approx(30.0)
        assert gathering.units_at(table, 24) == pytest.approx(35.0)
        assert gathering.units_at(table, 99) == pytest.approx(table[-1][1])

    def test_the_payout_climbs_where_a_chart_would_not(self) -> None:
        # The point of the field: a level buys a bigger drop here, not a
        # faster swing or a better chance.
        profile = gathering.PROFILES["Woodcutting"]
        node = "sapling (chambers of xeric)"
        assert node in profile.stated_experience_at
        assert node not in profile.stepped_interval
        assert profile.shared_curves[node] == "Tree"


class TestTheInfectedRoot:
    """The page states the whole loop, and then checks it for you."""

    def test_its_experience_is_the_mean_of_the_drop_table(self) -> None:
        # 10 for a tear at 15/17 and 25 for a log at 2/17. The infobox says
        # `10 - 35`, which reads as its floor; this is what a cut pays.
        paid = gathering.PROFILES["Woodcutting"].stated_experience["infected root"]
        assert paid == pytest.approx((10 * 15 + 25 * 2) / 17)

    def test_it_never_depletes(self) -> None:
        # "Infected roots don't deplete, so one action will continue cutting
        # until a player's inventory is filled with logs", and `time = 0
        # seconds`. No respawn to share and nowhere to hop to.
        assert "infected root" in gathering.PROFILES["Woodcutting"].endless

    def test_it_is_not_refused(self) -> None:
        # It was, on a reading of "rates *up to* ... ~9,100 experience per
        # hour" as a ceiling. See the next test for what settled that.
        assert "infected root" not in gathering.PROFILES["Woodcutting"].refuses

    def test_the_pages_worked_example_is_this_models_answer(self) -> None:
        # **The check that reversed the refusal.** "A single click will yield
        # an average of 202.5 demon tears and 2,700 Woodcutting experience
        # before the inventory is filled with 27 logs." Twenty-seven logs at
        # 2/17 is 229.5 successes; at four ticks and the charted 0.7344 that
        # is 750 seconds, so the page's own example is 12,960/hr - and the
        # ~9,100 headline is the same activity measured over the trips too.
        successes = 27 / (2 / 17)
        assert successes * (15 / 17) == pytest.approx(202.5)
        paid = successes * (10 * 15 + 25 * 2) / 17
        assert paid == pytest.approx(2700.0)
        seconds = successes / gathering.success_chance(99, 60.0, 187.0) * 4 * 0.6
        assert paid * 3600.0 / seconds == pytest.approx(12960.0, rel=1e-3)

    def test_an_outfit_is_refused_for_the_other_reason(self) -> None:
        # Not "the model cannot see enough of it" but "there is no action
        # here": an outfit is a bonus on whatever you were already chopping.
        refuses = gathering.PROFILES["Woodcutting"].refuses
        assert {"lumberjack outfit", "forestry outfit"} <= set(refuses)
        # And the reason is data, because the report prints it - see
        # `coverage.REFUSED`.
        assert "not an action" in refuses["lumberjack outfit"]

    def test_the_swaying_tree_is_refused_for_being_worth_one(self) -> None:
        # One object, a `Branch`, and an infobox stating 1 experience. There
        # is nothing repeatable here for a chart or a respawn to describe.
        assert "swaying tree" in gathering.PROFILES["Woodcutting"].refuses

    def test_nothing_else_in_the_skill_is_refused(self) -> None:
        assert set(gathering.PROFILES["Woodcutting"].refuses) == {
            "lumberjack outfit",
            "forestry outfit",
            "swaying tree",
        }

    def test_its_experience_is_the_mean_and_not_the_range(self) -> None:
        # The infobox says `10 - 35`; the page's drop table and its three
        # experience values say (10*15 + 25*2) / 17, and its own "202.5 tears
        # and 2,700 experience" per inventory checks it.
        paid = gathering.PROFILES["Woodcutting"].stated_experience["infected root"]
        assert paid == pytest.approx(200.0 / 17.0)
        assert 202.5 * 10.0 + 27.0 * 25.0 == pytest.approx(229.5 * paid)


class TestTheBlisterwoodTree:
    """The one tree that does not fall, and the one that states so.

    `{{Woodcutting info}}` gives it `time = 0 seconds` and the prose gives it
    "a 1/10 chance of 'depleting' with every log chopped ... the player stops
    woodcutting and must click again to resume". Both halves are read off the
    page; neither is fitted.
    """

    def test_a_depletion_covers_ten_logs(self) -> None:
        assert gathering.PROFILES["Woodcutting"].yields["blisterwood tree"] == 10.0

    def test_the_interruption_is_a_click_and_not_a_walk(self) -> None:
        # `node_seconds` is 2.4 because an ordinary tree vanishes and you walk
        # to the next. There is one blisterwood tree, sealed in the Arboretum,
        # and it is still there - so what a depletion costs is the tick to
        # click it again.
        profile = gathering.PROFILES["Woodcutting"]
        assert profile.node_seconds_at == {"blisterwood tree": 0.6}
        assert profile.node_seconds_at["blisterwood tree"] < profile.node_seconds

    def test_no_other_tree_is_exempted(self) -> None:
        # The re-click is the exception, and an exception that spread would be
        # `node_seconds` quietly changing. `yields` is shared with the jungle,
        # which states four sections for its own reasons.
        profile = gathering.PROFILES["Woodcutting"]
        assert set(profile.node_seconds_at) == {"blisterwood tree"}
        assert set(profile.yields) == {
            "blisterwood tree", "light jungle", "medium jungle", "dense jungle",
            "mature juniper tree",
        }


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
    refuses={"baby impling": "a wandering rare spawn"},
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
        # The unassisted tier, matching what `tool_curve` falls back to - a
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
        ) == (
            "Willow tree",
            "Willow trees",
            "Willow logs",
            "Willow tree (Woodcutting)",
            "Willow trees (Woodcutting)",
            "Willow logs (Woodcutting)",
        )


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


class TestAFallibleChestIsRetriedNotWalkedAwayFrom:
    """**Two published chest figures, and one interval could not serve both.**

    `roll_ticks_by_kind["Chests"]` is 15.5 ticks, fitted to the Rogues' Castle
    guide's 270,154/hr, and its comment used to say "nothing else published can
    check it". Something does: `Chest (Aldarin Villas)` states "approximately
    400 chests can be successfully opened per hour" at level 60, which 15.5
    ticks misses by 2.9x.

    The two measure different things. Every Rogues' Castle attempt succeeds, so
    the cost per chest is the walk to the next of three; a chest you fail at
    stays shut in front of you and is retried where you stand. So the fallible
    ones name their own interval and the walk-shaped number is left to the case
    it was measured on.
    """

    #: The Aldarin chest's own plain and lockpick curves, off its page.
    PLAIN = (0.0, 150.0)
    LOCKPICK = (25.0, 175.0)

    #: Its page's other two figures: 200 experience a chest and a 1.8-second
    #: reset, which is far shorter than either interval and so never binds.
    TABLES = gathering.Tables(
        curves={
            "chest (aldarin villas)": (
                ("Normal", 0.0, 150.0, 36, "confirmed"),
                ("Lockpick", 25.0, 175.0, 36, "confirmed"),
            ),
            "chest (rogues' castle)": (),
        },
        experience={
            "Thieving": {
                "chest (aldarin villas)": (200.0, "Chests"),
                "chest (rogues' castle)": (701.7, "Chests"),
            }
        },
        respawns={"chest (aldarin villas)": 1.8, "chest (rogues' castle)": 20.4},
    )

    def _rate(
        self, level: int, profile: gathering.SkillProfile | None = None
    ) -> gathering.NodeRate:
        rate = gathering.rate_at(
            self.TABLES, {}, profile or gathering.PROFILES["Thieving"],
            "Loot a ~|chest (Aldarin Villas)|~", "Thieving",
            {"Level": 36, "Primary": True, "Objects": ["Chest (Aldarin Villas)"]}, level,
        )
        assert rate is not None
        return rate

    def test_the_interval_reproduces_the_pages_own_four_hundred_an_hour(self) -> None:
        """**Against the curve that figure assumes**, which `Thieving training`
        states in the same breath: "bring a lockpick and some stamina or super
        energy potions". 400 successes an hour at the lockpick chance is 883
        attempts, so 4.08 seconds each."""
        attempts = 400.0 / gathering.success_chance(60, *self.LOCKPICK)

        assert self._rate(60).roll_seconds == pytest.approx(3600.0 / attempts, rel=0.01)

    def test_what_is_spent_is_still_the_plain_curve(self) -> None:
        """A lockpick is an item this map may not hold, so the interval is
        calibrated on the geared figure and the chance is not - the same split
        `costing/pickpocket.py` makes."""
        assert self._rate(60).chance == pytest.approx(
            gathering.success_chance(60, *self.PLAIN)
        )
        assert self._rate(60).xp_per_hour == pytest.approx(62_730, rel=0.001)

    def test_the_walk_shaped_interval_would_have_been_almost_three_times_slow(self) -> None:
        walked = dataclasses.replace(gathering.PROFILES["Thieving"], fixed_interval={})

        ratio = self._rate(60).xp_per_hour / self._rate(60, walked).xp_per_hour

        assert ratio == pytest.approx(2.28, rel=0.02)

    def test_the_second_published_sentence_is_the_residual(self) -> None:
        """"Without a lockpick or energy potions, only rates up to 40,000 can
        be expected" over levels 36-45. This reads 37,905 to 46,868 - high at
        the top of that band, because losing the potions lengthens the run back
        from the failure teleport and nothing here has a term for it."""
        assert self._rate(36).xp_per_hour == pytest.approx(37_905, rel=0.001)
        assert self._rate(45).xp_per_hour == pytest.approx(46_868, rel=0.001)

    def test_the_rogues_castle_chest_keeps_the_number_measured_on_it(self) -> None:
        """It cannot fail, so nothing about this changes it - which is the
        point of naming the fallible ones rather than moving the default."""
        rate = gathering.rate_at(
            self.TABLES, {}, gathering.PROFILES["Thieving"], "Loot a ~|chest|~", "Thieving",
            {"Level": 84, "Primary": True, "Objects": ["Chest (Rogues' Castle)"]}, 99,
        )
        assert rate is not None
        assert rate.roll_seconds == pytest.approx(15.5 * 0.6)
        assert rate.chance == 1.0


class TestARefusalCarriesItsOwnReason:
    """The sentence is data rather than a comment because the report prints
    it: a refusal reported as `unpriced` reads as the gap it was made to deny.
    See `coverage.REFUSED`."""

    def test_every_named_refusal_states_one(self) -> None:
        for skill, profile in gathering.PROFILES.items():
            for key, why in profile.refuses.items():
                assert why.strip(), f"{skill}/{key}"

    def test_it_is_asked_of_every_name_the_challenge_offers(self) -> None:
        """The sunstone monolith is why: its `Output` is `Sunstone`, so the
        rock rewrite reaches it under the *rocks'* name and refusing on the
        resolved node cannot express the refusal at all."""
        profile = gathering.SkillProfile(
            refuses={"sunstone monolith": "a quest-line object"}
        )
        challenge = {"Output": "Sunstone", "Objects": ["Sunstone monolith"]}
        assert gathering.refusal(TABLES, profile, {}, challenge, "Mining", "t") == (
            "a quest-line object"
        )
        assert gathering.refusal(TABLES, profile, {}, {"Output": "Sunstone"}, "Mining", "t") == ""

    def test_a_refused_method_is_reported_rather_than_counted_as_a_miss(self) -> None:
        """`no_curve` means "this named a node the wiki charts nothing for",
        which is a gap somebody could close. A refusal is the opposite claim
        and must not be filed under it."""
        info = ChunkInfo(
            {
                "challenges": {
                    "Woodcutting": {
                        "Chop the ~|swaying tree|~": {"Primary": True, "Level": 40}
                    }
                }
            }
        )
        _, coverage = gathering.priced_methods(
            info, {"Woodcutting": {"Chop the ~|swaying tree|~": {}}}, TABLES, frozenset()
        )
        assert "Chop the ~|swaying tree|~" in coverage.refused
        assert "one experience" in coverage.refused["Chop the ~|swaying tree|~"]
        assert coverage.no_curve == ()
        assert coverage.no_experience == ()


class TestARefusalByKind:
    """A `Trap` is the one Thieving kind that pays nothing - six of its seven
    pages state `xp = 0`. Doors were refused beside it and are not any more:
    `costing/shortcuts.py` prices an Agility shortcut, the same shape, at a
    stated eight ticks."""

    def _tables(self) -> gathering.Tables:
        return gathering.Tables(skill_loops={"Thieving": {"door (yanille dungeon)": "Door"}})

    def _profile(self) -> gathering.SkillProfile:
        return gathering.SkillProfile(
            refused_kinds={"Door": "a lock you pick to get through"}
        )

    def test_the_kind_is_read_off_the_infobox(self) -> None:
        challenge = {"Objects": ["Door (Yanille Dungeon)"], "Level": 82}
        assert gathering.refusal(
            self._tables(), self._profile(), {}, challenge, "Thieving", "t"
        ) == "a lock you pick to get through"

    def test_a_node_of_another_kind_is_untouched(self) -> None:
        challenge = {"Objects": ["Silk stall"]}
        assert gathering.refusal(
            self._tables(), self._profile(), {}, challenge, "Thieving", "t"
        ) == ""

    def test_a_name_outranks_a_kind(self) -> None:
        """The more specific statement wins, so a profile can say "no door is
        a training method" and "not this one either, for its own reason"."""
        profile = dataclasses.replace(
            self._profile(), refuses={"door (yanille dungeon)": "its own reason"}
        )
        challenge = {"Objects": ["Door (Yanille Dungeon)"]}
        assert gathering.refusal(
            self._tables(), profile, {}, challenge, "Thieving", "t"
        ) == "its own reason"

    def test_the_export_carries_no_priced_door(self) -> None:
        """`strict_kinds` is what refuses the rate and this only says why, so
        naming the kinds cannot take a number away: no profile gives one of
        them a roll interval."""
        for profile in gathering.PROFILES.values():
            assert not set(profile.refused_kinds) & set(profile.roll_ticks_by_kind)


class TestAZeroRestockIsARestock:
    """The same `> 0` guard was in two places, and both read a real nought as
    a missing figure - see `remote/gathering.parse_stall_respawns`."""

    def test_load_tables_keeps_it(self) -> None:
        tables = gathering.load_tables({"respawns": {"Stone chest": 0, "Silk stall": 4.8}})
        assert tables.respawns == {"stone chest": 0.0, "silk stall": 4.8}

    def test_a_negative_is_still_unreadable(self) -> None:
        assert gathering.load_tables({"respawns": {"Nonsense": -1}}).respawns == {}

    def test_the_four_instant_chests_are_shipped_with_one(self) -> None:
        """They are what the guard was costing: the rusty, tarnished, stone and
        reinforced chests, all `0 seconds` on the Thieving page's own table."""
        shipped = gathering.load_tables(cache.read_gathering())
        for chest in ("rusty chest", "tarnished chest", "stone chest", "reinforced chest"):
            assert shipped.respawns[chest] == 0.0


class TestADoorIsAnObstacleAndIsPricedLikeOne:
    """**The refusal that was reversed, and why.** "You unlock a door once and
    it stays unlocked" is not what disqualifies a method - `shortcuts.py`
    prices an Agility shortcut, a thing in the way with an experience for
    getting past it, at a stated eight ticks and reports the honest low
    numbers. Measured over the wiki, not one of the 22 `Door`/`Trap`/
    `Trapdoor` pages carries a `time`, so the borrow is from the nearest
    published obstacle rather than from inside the family."""

    _PROFILE = gathering.PROFILES["Thieving"]

    def test_the_interval_is_the_shortcut_modules_own(self) -> None:
        from chunksim.costing.shortcuts import SHORTCUT_TICKS

        assert self._PROFILE.roll_ticks_by_kind["Door"] == SHORTCUT_TICKS
        assert self._PROFILE.roll_ticks_by_kind["Trapdoor"] == SHORTCUT_TICKS

    def test_a_borrowed_interval_caps_the_provenance(self) -> None:
        # A rate is only as good as its weakest input; saying `confirmed`
        # because the chance was charted is what provenance exists to stop.
        assert {"Door", "Trapdoor"} <= self._PROFILE.inferred_loops

    def test_a_door_with_no_chart_cannot_fail(self) -> None:
        """The wiki's own convention, and its own prose for the one door that
        says anything: `Gate (Underground Pass Shortcut)` is "100% successful
        below the required level"."""
        assert {"Door", "Trapdoor"} <= self._PROFILE.certain_kinds

    def test_a_chart_still_wins_where_there_is_one(self) -> None:
        # `certain_kinds` is the fallback, checked after every curve source -
        # seven doors carry a chart and the Yanille one is brutal.
        tables = gathering.Tables(
            curves={"door (yanille dungeon)": (("Unlocking the door", 4.0, 40.0, 82, "confirmed"),)},
            skill_info={"Thieving": {"door (yanille dungeon)": (82, 50.0)}},
            skill_loops={"Thieving": {"door (yanille dungeon)": "Door"}},
        )
        challenge = {"Objects": ["Door (Yanille Dungeon)"], "Level": 82, "Primary": True}
        rate = gathering.rate_at(
            tables, {}, self._PROFILE, "t", "Thieving", challenge, 99
        )
        assert rate is not None
        assert rate.chance < 0.2
        assert rate.provenance == gathering.INFERRED

    def test_a_door_has_nothing_to_restock(self) -> None:
        assert "Door" not in self._PROFILE.restock_kinds

    def test_a_trap_is_still_refused(self) -> None:
        # Six of the seven `Trap` pages state `xp = 0`; a trap is a hazard to
        # avoid rather than an action that pays.
        assert set(self._PROFILE.refused_kinds) == {"Trap"}


class TestATaskCanNameTheWrongThingEntirely:
    """`Unlock the ~|paladin|~ door` states no `Objects`, so its only key is
    the span - and `paladin` is a real page with a real chart. It priced at
    117,670/hr, a door read as a pickpocket."""

    def test_the_table_replaces_the_keys_rather_than_leading_them(self) -> None:
        """**Leading was not enough**: `_experience_for` scans the calculator
        across every key before it looks at any infobox, and the calculator
        has a `Paladin` row and no door - so the door kept the NPC's 131.8
        experience and its two-tick cadence."""
        keys = gathering._join_keys(
            {"Chunks": ["10291"]},
            {},
            gathering._NAME_FIELDS,
            "Thieving",
            "Unlock the ~|paladin|~ door",
        )
        assert keys == ("Door (Ardougne Castle)",)

    def test_it_is_keyed_by_whole_task_and_stays_tiny(self) -> None:
        # A task name cannot be reached by accident, which is what makes a
        # replacement safe; twenty entries would mean a rule is missing.
        assert len(gathering._TASK_NODES) <= 3
        for task in gathering._TASK_NODES:
            assert task.startswith(("Unlock", "Steal", "Loot", "Pickpocket", "Crack"))

    def test_an_ordinary_task_is_untouched(self) -> None:
        keys = gathering._join_keys(
            {"Monsters": ["Paladin"]}, {}, gathering._NAME_FIELDS, "Thieving",
            "Pickpocket a ~|paladin|~",
        )
        assert keys[0] == "Paladin"
        assert "Door (Ardougne Castle)" not in keys


class TestOnlyOneChartOnAPageIsAboutIt:
    """**Measured before it was fixed**: 31 of the 643 pages carrying
    `{{Skilling success chart}}` carry more than one, and on 29 the first is
    the one about the page's own action. The two that are not are NPCs you can
    also fight, and both were priced off the wrong curve."""

    def test_the_hand_table_names_both_and_no_more(self) -> None:
        from chunksim.remote.gathering import CHART_LABELS

        assert set(CHART_LABELS) == {"H.A.M. Member", "Menaphite Thug"}

    def test_the_shipped_curve_is_the_pickpocket_one(self) -> None:
        """The H.A.M. Member's first chart is "Avoiding concussions using
        Agility" - `low=0 high=254` - which read the NPC at 99.6% at level 99
        against a true 93.8%, and 65,571/hr against 49,950."""
        tables = gathering.load_tables(cache.read_gathering())
        first = tables.curves["h.a.m. member"][0]
        assert (first[1], first[2]) == (135.0, 239.0)

    def test_and_the_thug_is_not_on_its_blackjack_chart(self) -> None:
        # `Menaphite Thug knockout chance` is `78/240` and priced the NPC at
        # **330,274/hr**, which would have beaten the Rogues' Castle chest.
        tables = gathering.load_tables(cache.read_gathering())
        first = tables.curves["menaphite thug"][0]
        assert (first[1], first[2]) == (50.0, 160.0)


class TestACurveCanBeSharedWholesale:
    """`Guard (H.A.M. Storerooms)` has no chart anywhere and is not like the
    six uncharted pickpockets that stay refused: it is a H.A.M. member with a
    different loot table, paying the same 22.2 experience, and the member's
    chart is its chart."""

    def test_the_guard_borrows_the_members_line_unmoved(self) -> None:
        profile = gathering.PROFILES["Thieving"]
        assert profile.shared_curves["guard (h.a.m. storerooms)"] == "H.A.M. Member"

    def test_shared_not_assumed_because_the_chance_is_the_same(self) -> None:
        """`assumed_curves` would re-anchor the line to open at 20 with the
        member's level-15 chance; the claim here is that the chance is the same
        function of level, so the line is taken where it is drawn."""
        assert "guard (h.a.m. storerooms)" not in gathering.PROFILES["Thieving"].assumed_curves


class TestAFailedAttemptCanPayToo:
    """Three pages in the whole `{{Thieving info}}` corpus state one, all of
    them 0.5 - and it matters most where the model is worst."""

    def test_the_table_is_the_measured_three(self) -> None:
        assert set(gathering.PROFILES["Thieving"].fail_experience) == {
            "ogre coffin",
            "door (h.a.m. hideout jail)",
            "door (port sarim jail)",
        }

    def test_it_is_worth_a_sixth_of_a_coffin_at_the_opening_level(self) -> None:
        # One attempt in ten succeeds at level 20, so eight and a half misses
        # pay 4.4 against the success's 27.
        tables = gathering.Tables(
            curves={"ogre coffin": (("Toolless", 0.0, 127.0, 20, "confirmed"),)},
            skill_info={"Thieving": {"ogre coffin": (20, 27.0)}},
            skill_loops={"Thieving": {"ogre coffin": "Chests"}},
        )
        challenge = {"Objects": ["Ogre Coffin"], "Level": 20, "Primary": True}
        profile = gathering.PROFILES["Thieving"]
        paid = gathering.rate_at(tables, {}, profile, "t", "Thieving", challenge, 20)
        bare = gathering.rate_at(
            tables, {}, dataclasses.replace(profile, fail_experience={}),
            "t", "Thieving", challenge, 20,
        )
        assert paid is not None and bare is not None
        assert paid.xp_per_hour / bare.xp_per_hour == pytest.approx(1.164, abs=0.005)


class TestAStatedRestockIsNotAMissingOne:
    """`restock_kinds` refuses a chest with no entry in `Tables.respawns`, and
    rightly - but a node the wiki never tabulated is refused for a reason about
    the *table* rather than about the node."""

    def test_the_ogre_coffin_states_its_own(self) -> None:
        # "They can be safespotted by standing between the northern coffin and
        # the centre coffin allowing you to continuously pick the coffins."
        assert gathering.PROFILES["Thieving"].stated_respawns["ogre coffin"] == 0.0

    def test_a_chest_with_neither_is_still_refused(self) -> None:
        tables = gathering.Tables(
            curves={"nowhere chest": (("", 100.0, 200.0, 1, "confirmed"),)},
            skill_info={"Thieving": {"nowhere chest": (1, 50.0)}},
            skill_loops={"Thieving": {"nowhere chest": "Chests"}},
        )
        challenge = {"Objects": ["Nowhere chest"], "Level": 1, "Primary": True}
        assert gathering.rate_at(
            tables, {}, gathering.PROFILES["Thieving"], "t", "Thieving", challenge, 99
        ) is None


class TestACandleStandThatIsNotAStall:
    """`Candles` states a level and 20 experience and leaves `type` blank, and
    its prose says why the obvious answer is wrong: "this stand is unique
    compared to stalls where there is no respawn time to continue to steal
    from it, and it can be failed"."""

    _PROFILE = gathering.PROFILES["Thieving"]

    def test_its_loop_is_a_pickpockets(self) -> None:
        # A roll, a stun on failure and nothing to wait for. A stall is
        # certain and restock-bound and this is neither.
        assert self._PROFILE.loop_at["candles"] == "Pickpocket"
        assert "Pickpocket" not in self._PROFILE.certain_kinds
        assert "Pickpocket" not in self._PROFILE.restock_kinds

    def test_the_stun_is_charged(self) -> None:
        # "Upon failing to steal the candle, the player is ... stunned for a
        # few seconds" - so the failure costs more than the retry.
        assert "Pickpocket" not in self._PROFILE.fail_seconds_by_kind
        assert self._PROFILE.fail_seconds > 0

    def test_its_chance_is_borrowed_from_the_nearest_charted_thing(self) -> None:
        """The warrior is a fallible steal that stuns, opening five levels
        above the candles and paying 26 against 20 - and nothing charts the
        candles at all."""
        assert self._PROFILE.assumed_curves["candles"] == "Warrior (Thieving)"

    def test_a_borrow_reports_itself(self) -> None:
        # `inferred`, and `assumed as <donor>` in the rate's own label, which
        # is what `assumed_curves` exists to make visible.
        tables = gathering.Tables(
            curves={"warrior (thieving)": (("Normal", 100.0, 240.0, 25, "confirmed"),)},
            skill_info={"Thieving": {"candles": (20, 20.0)}},
        )
        challenge = {"Objects": ["Candles"], "Level": 20, "Primary": True}
        rate = gathering.rate_at(
            tables, {}, self._PROFILE, "t", "Thieving", challenge, 20
        )
        assert rate is not None
        assert rate.provenance == gathering.INFERRED
        assert "Warrior (Thieving)" in rate.tool
        # The warrior's own opening chance, reached where the candles open.
        assert rate.chance == pytest.approx(
            gathering.success_chance(25, 100.0, 240.0), abs=0.005
        )

    def test_the_page_states_it_has_no_respawn(self) -> None:
        # Carried even though a `Pickpocket` needs none, so the fact sits next
        # to the loop it explains.
        assert self._PROFILE.stated_respawns["candles"] == 0.0


class TestTheDeadfallRunsTwoTraps:
    """The 19 August 2026 `Summer Sweep Up - Hunter & Skilling` rebalance.

    It moved two things at once and reading only one of them was wrong in a
    way no total would show: Hunter experience from the deadfall creatures
    fell ~20% (prickly kebbit ~27%, oak birdhouse 60%), and **the deadfall
    trap limit went from 1 to 2**. Taking the cut without the doubling made
    every deadfall creature read a fifth slow.
    """

    def test_the_limit_is_flat_rather_than_a_level_table(self) -> None:
        """Neither the update note nor the `Deadfall` page puts a level on it,
        and `Tables.parallel` is a scrape of the *multi-trap* table, which is
        about box, net, bird and rabbit."""
        profile = gathering.PROFILES["Hunter"]

        assert profile.worked_by_kind == {"Deadfall": 2.0}

    def test_the_loop_is_simultaneous_so_the_count_divides_the_rolling(self) -> None:
        """**`parallel_kinds` carries two meanings and this is the second.**
        Two boulders set at once really do halve the wait, where rotating
        between three chests never makes one chest open faster."""
        assert "Deadfall" in gathering.PROFILES["Hunter"].parallel_kinds

    def test_the_maniacal_monkey_is_exempt(self) -> None:
        """Stated in the same breath - "maniacal monkeys remain limited to one
        trap" - and it matters twice over, because it is also the single row
        the 105-tick deadfall interval is fitted against."""
        profile = gathering.PROFILES["Hunter"]

        assert profile.worked_at["maniacal monkey (hunter)"] == 1.0
        assert profile.roll_ticks_by_kind["Deadfall"] == 105.0

    def test_the_exemption_is_what_leaves_the_fit_standing(self) -> None:
        """Had the monkey taken the second trap, the interval fitted to
        `wiki:hunter`'s 51,000 would have reproduced 1.6x its own source - so
        this is the fit's own precondition, not a detail of one creature."""
        tables = gathering.Tables(
            parallel={"Hunter": {"": ((1, 2.0), (80, 5.0))}},
        )
        profile = gathering.PROFILES["Hunter"]

        monkey = gathering.units_worked(
            tables, profile, "Hunter", "Deadfall", "Maniacal monkey (Hunter)", 99
        )
        kebbit = gathering.units_worked(
            tables, profile, "Hunter", "Deadfall", "Wild kebbit", 99
        )

        assert (monkey, kebbit) == (1.0, 2.0)


class TestTheCivitasFishingSpot:
    """**One published row, solved and borrowed from in equal parts.**

    `Fishing spot (Civitas illa Fortis)` is tagged "Needs skilling success
    chart" and never charted, so the curve here is recovered from the single
    sentence its page does state.
    """

    NODE = "fishing spot (civitas illa fortis)"

    def test_the_two_published_figures_say_the_same_thing(self) -> None:
        """"20-30 house keys per hour and around 2,000 Fishing experience" at
        99, against 7.5 experience a catch and house keys at 1/10. Two figures
        written for different reasons, agreeing - which is what makes this
        evidence rather than a reading."""
        catches = 2_000 / 7.5
        assert catches == pytest.approx(266.7, abs=0.1)
        assert 20 <= catches / 10 <= 30

    def test_the_high_end_reproduces_both(self) -> None:
        """A big net rolls every 5 ticks, so an hour is 1,200 rolls."""
        low, high = gathering.PROFILES["Fishing"].stated_curves[self.NODE]
        rolls = 3600 / (gathering.PROFILES["Fishing"].roll_ticks_by_kind["Big net"] * 0.6)
        assert rolls == 1200.0
        catches = gathering.success_chance(99, low, high) * rolls
        assert catches * 7.5 == pytest.approx(2_000, rel=0.01)
        assert 20 <= catches / 10 <= 30

    def test_the_low_end_is_borrowed_from_the_shrimp_curve(self) -> None:
        """Nothing below 99 is published, so the level-1 end takes the shape of
        the only other level-1 net curve the wiki draws. Borrowed, and nothing
        checks it - which is why the entry is `INFERRED`."""
        low, high = gathering.PROFILES["Fishing"].stated_curves[self.NODE]
        assert low / high == pytest.approx(gathering.SHRIMP_LOW / gathering.SHRIMP_HIGH)

    def test_it_needs_the_loop_as_well_as_the_curve(self) -> None:
        """The calculator files this spot under no loop at all, so
        `strict_kinds` refused it however well the chance were known."""
        assert gathering.PROFILES["Fishing"].loop_at[self.NODE] == "Big net"

    def test_the_junk_loot_is_refused_by_output_not_by_node(self) -> None:
        """**Measured, not theoretical.** The junk loot shares `Fishing spot
        (big net, harpoon)` with raw bass, cod, mackerel and shark; keying the
        refusal on the node refused all four and dropped shark onto a
        money-making guide."""
        refuses = gathering.PROFILES["Fishing"].refuses
        assert "big net junk loot" in refuses
        assert "fishing spot (big net, harpoon)" not in refuses
