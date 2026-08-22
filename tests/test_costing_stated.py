"""`costing/stated.py`: rates that are stated rather than computed."""

from __future__ import annotations

import pytest

from chunksim.costing import stated
from chunksim.costing.gathering import GUESS, Tables
from chunksim.model.chunkinfo import ChunkInfo

INFO = ChunkInfo({"challenges": {}})


class TestMossLizard:
    @pytest.mark.parametrize("level,paid", [(20, 18), (50, 45), (99, 89), (120, 90)])
    def test_nine_tenths_of_the_level_floored_and_capped(
        self, level: int, paid: float
    ) -> None:
        assert stated.moss_lizard_experience(level) == paid

    def test_the_cap_binds_above_a_hundred(self) -> None:
        assert stated.moss_lizard_experience(126) == stated.MOSS_LIZARD_CAP

    def test_the_rate_is_the_formula_times_the_guessed_pace(self) -> None:
        (found,) = stated.methods(INFO, {"Hunter": {stated.MOSS_LIZARD_TASK: True}}).values()
        top = max(method.xp_per_hour for method in found)
        assert top == pytest.approx(89 * stated.MOSS_LIZARD_PER_HOUR)

    def test_the_pace_makes_every_band_a_guess(self) -> None:
        # The experience is exact; three in thirty seconds is not.
        (found,) = stated.methods(INFO, {"Hunter": {stated.MOSS_LIZARD_TASK: True}}).values()
        assert {method.match for method in found} == {GUESS}

    def test_it_never_opens_below_its_level(self) -> None:
        (found,) = stated.methods(INFO, {"Hunter": {stated.MOSS_LIZARD_TASK: True}}).values()
        assert min(method.level or 0 for method in found) == 20


class TestTheMossLizardCook:
    """**The same trap spent a second time.** `Cooked moss lizard`'s
    `{{Recipe}}` is entirely published - level 30, 60 experience, one tick -
    and the answer is still decided by how fast lizards are caught."""

    _BOTH: dict[str, dict[str, object]] = {
        "Hunter": {stated.MOSS_LIZARD_TASK: True},
        "Cooking": {stated.MOSS_LIZARD_COOK_TASK: True},
    }

    def test_the_published_terms(self) -> None:
        assert (
            stated.MOSS_LIZARD_COOK_XP,
            stated.MOSS_LIZARD_COOK_TICKS,
            stated.MOSS_LIZARD_COOK_LEVEL,
        ) == (60.0, 1.0, 30)

    def test_the_headline_is_the_recipe_read_literally(self) -> None:
        """60 experience every tick, which is not a method - it is what the
        material cost exists to correct."""
        assert stated.moss_lizard_cook_per_hour() == pytest.approx(360_000.0)

    def test_the_supply_is_charged_and_it_is_nearly_all_of_it(self) -> None:
        per_xp = stated.moss_lizard_cook_material_seconds_per_xp(self._BOTH)
        effective = 3600.0 / (
            3600.0 / stated.moss_lizard_cook_per_hour()
            + per_xp[stated.MOSS_LIZARD_COOK_TASK]
        )

        assert effective == pytest.approx(20_377.0, abs=1.0)

    def test_it_is_the_trapping_pace_and_nothing_else(self) -> None:
        """Ten seconds a lizard over sixty experience - so a measurement of
        the catch retires this and the Hunter bands together, which is the
        reason both live in one file."""
        assert stated.moss_lizard_cook_seconds_per_xp() == pytest.approx(
            (3600.0 / stated.MOSS_LIZARD_PER_HOUR) / stated.MOSS_LIZARD_COOK_XP
        )

    def test_the_band_is_a_guess_although_the_recipe_is_not(self) -> None:
        """`costing/tempoross.py`'s rule: the effective rate contains an
        invented pace, so the product is invented."""
        found = stated.methods(INFO, self._BOTH)["Cooking"]

        assert {method.match for method in found} == {GUESS}
        assert {method.level for method in found} == {stated.MOSS_LIZARD_COOK_LEVEL}

    def test_both_challenges_are_needed(self) -> None:
        """A map holding the campsite and not the cavern can cook nothing."""
        only_cooking = {"Cooking": self._BOTH["Cooking"]}
        only_hunter = {"Hunter": self._BOTH["Hunter"]}

        assert "Cooking" not in stated.methods(INFO, only_cooking)
        assert "Cooking" not in stated.methods(INFO, only_hunter)
        assert stated.moss_lizard_cook_material_seconds_per_xp(only_cooking) == {}
        assert stated.moss_lizard_cook_material_seconds_per_xp(only_hunter) == {}

    def test_the_hunter_band_does_not_change(self) -> None:
        """Catching without cooking is still a method, and still 360 an hour -
        the 0.6-second cook is charged to the Cooking side only."""
        alone = stated.methods(INFO, {"Hunter": {stated.MOSS_LIZARD_TASK: True}})["Hunter"]
        both = stated.methods(INFO, self._BOTH)["Hunter"]

        assert [m.xp_per_hour for m in alone] == [m.xp_per_hour for m in both]

    def test_it_is_wired_in(self) -> None:
        import pathlib

        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "stated.moss_lizard_cook_material_seconds_per_xp(" in source


class TestTheRiftsCraftingHalf:
    """**The same fragments, spent a second time.** One fragment makes one
    essence, so this must assume the same count the Mining ceiling does - and
    that is why both live in one file."""

    _VALID: dict[str, dict[str, object]] = {
        "Crafting": {stated.RIFT_ESSENCE_TASK: True}
    }

    def test_the_payout_is_the_recipes_own_formula(self) -> None:
        """"The experience is `CraftingLevel / 10`, clamped between 1 and 5
        experience (1xp below level 10; 5xp above level 50)"."""
        assert stated.rift_essence_experience(1) == 1.0
        assert stated.rift_essence_experience(9) == 1.0
        assert stated.rift_essence_experience(25) == 2.5
        assert stated.rift_essence_experience(50) == 5.0
        assert stated.rift_essence_experience(99) == 5.0

    def test_it_spends_the_same_fragment_count_as_the_mining_side(self) -> None:
        assert stated.rift_fragments_per_hour() == (
            stated.RIFT_FRAGMENT_CAP * stated.RIFT_GAMES_PER_HOUR
        )
        assert stated.rift_rate() == (
            stated.rift_fragments_per_hour() * stated.RIFT_FRAGMENT_EXPERIENCE
        )

    def test_the_curve_runs_from_fifteen_hundred_to_seventy_five_hundred(
        self,
    ) -> None:
        assert stated.rift_essence_rate(1) == 1_500.0
        assert stated.rift_essence_rate(50) == 7_500.0
        assert stated.rift_essence_rate(99) == stated.rift_essence_rate(50)

    def test_the_bands_are_a_guess_because_the_count_is(self) -> None:
        """The payout is published exactly; "six games an hour" and "mining
        constantly" are not - `costing/tempoross.py`'s rule."""
        found = stated.methods(INFO, self._VALID)["Crafting"]

        assert {m.match for m in found} == {GUESS}
        assert min(m.level or 0 for m in found) == 1

    def test_nothing_when_unreachable(self) -> None:
        assert "Crafting" not in stated.methods(INFO, {})
        assert "Crafting" not in stated.methods(INFO, {"Crafting": {}})

    def test_gotrs_recovered_essence_count_is_not_what_this_spends(self) -> None:
        """**Recorded because it is the tempting number.** `costing/gotr.py`
        recovers throughput by dividing published Runecraft bands by its own
        modelled mix - exact for reproducing those bands, never checked as a
        count, and six times the fragments the Mining ceiling here assumes,
        because the published rate includes experience the imbue does not
        pay."""
        import pathlib

        from chunksim.costing import gotr

        source = pathlib.Path(stated.__file__).read_text(encoding="utf-8")
        assert "calibrated, not modelled" in source
        assert hasattr(gotr, "essence_per_hour")
        assert stated.rift_fragments_per_hour() == 1_500.0


class TestTroubleBrewing:
    _VALID = {
        "Cooking": {"Participate in ~|Trouble Brewing|~": True},
        "Hunter": {"Participate in ~|Trouble Brewing|~ for Hunter xp": True},
        "Extra": {"Participate in ~|Trouble Brewing|~ for Extra xp": True},
    }

    def test_every_secondary_skill_it_pays_gets_the_figure(self) -> None:
        found = stated.methods(INFO, self._VALID)
        assert "Hunter" in found

    def test_a_non_skill_branch_is_not_a_training_rate(self) -> None:
        # `Extra` is one of upstream's three non-skill categories; a minigame
        # listed under one must not become experience an hour for it.
        assert "Extra" not in stated.methods(INFO, self._VALID)

    def test_it_is_a_guess_and_says_so(self) -> None:
        found = stated.methods(INFO, self._VALID)["Hunter"]
        assert {method.match for method in found} == {GUESS}
        assert found[0].xp_per_hour == stated.TROUBLE_BREWING_PER_HOUR

    def test_the_minigames_own_skill_is_left_to_the_model(self) -> None:
        """**Seven of the eight challenges say `for <skill> xp` and Cooking's
        does not**, because brewing the rum is the minigame and the rest are
        side-effects of running about doing it. That one is counted rather
        than guessed - see `costing/troublebrewing.py` - and a guess left here
        beside it would win wherever the count happened to be lower."""
        found = stated.methods(INFO, self._VALID)

        assert "Cooking" not in found
        assert found["Hunter"][0].xp_per_hour == stated.TROUBLE_BREWING_PER_HOUR

    def test_a_map_reaching_neither_gets_nothing(self) -> None:
        assert stated.methods(INFO, {"Hunter": {}}) == {}


class TestLanternHarpoon:
    """Two squid off one spot, with the split read and the pace guessed."""

    _TABLES = Tables(
        skill_info={
            "Fishing": {
                "raw swordtip squid": (52, 55.0),
                "raw jumbo squid": (69, 75.0),
            }
        }
    )
    _VALID = {"Fishing": {stated.LANTERN_TASKS[0][0]: True}}

    def test_only_the_lesser_squid_before_the_jumbo_opens(self) -> None:
        assert stated.lantern_swordtip_share(60) == 1.0

    def test_the_published_split_is_reproduced_at_both_ends(self) -> None:
        # The page states 69% swordtip at 69 Fishing and 62% at 91.
        assert stated.lantern_swordtip_share(69) == pytest.approx(0.69)
        assert stated.lantern_swordtip_share(91) == pytest.approx(0.62)

    def test_the_share_keeps_drifting_past_the_second_point(self) -> None:
        # Two points describe a drift rather than a ceiling.
        assert stated.lantern_swordtip_share(99) < stated.lantern_swordtip_share(91)

    def test_the_pace_is_held_inside_the_levels_it_was_quoted_at(self) -> None:
        assert stated.lantern_catches_per_hour(1) == 250.0
        assert stated.lantern_catches_per_hour(120) == 400.0

    def test_the_rate_is_the_pace_times_the_blended_experience(self) -> None:
        share = stated.lantern_swordtip_share(99)
        assert stated.lantern_rate(self._TABLES, 99) == pytest.approx(
            400.0 * (share * 55.0 + (1 - share) * 75.0)
        )

    def test_it_is_a_guess_because_the_pace_is(self) -> None:
        found = stated.methods(INFO, self._VALID, self._TABLES)["Fishing"]
        assert {method.match for method in found} == {GUESS}

    def test_it_opens_where_the_spot_does(self) -> None:
        found = stated.methods(INFO, self._VALID, self._TABLES)["Fishing"]
        assert min(method.level or 0 for method in found) == stated.LANTERN_OPENS

    def test_no_experience_table_prices_nothing(self) -> None:
        assert stated.lantern_rate(Tables(), 99) == 0.0

    def test_a_map_without_the_spot_gets_nothing(self) -> None:
        assert "Fishing" not in stated.methods(INFO, {"Fishing": {}}, self._TABLES)


class TestTempleTrekking:
    _VALID = {
        "Woodcutting": {"Read a ~|woodcutting tome|~ from Temple Trekking": True},
        "Slayer": {"Read a ~|slayer tome|~ from Temple Trekking": True},
        "Extra": {"Read a ~|nonsense tome|~ from Temple Trekking": True},
    }

    def test_every_skill_with_a_tome_can_train_on_it(self) -> None:
        found = stated.methods(INFO, self._VALID, None, frozenset(), {})
        assert {"Woodcutting", "Slayer"} <= set(found)

    def test_the_ramble_doubles_it(self) -> None:
        # Burgh de Rott Ramble is the same trek in reverse at twice the pace,
        # and finishing Darkness of Hallowvale is what unlocks it.
        plain = stated.methods(INFO, self._VALID, None, frozenset(), {})["Slayer"]
        ramble = stated.methods(
            INFO, self._VALID, None, frozenset(), {stated.RAMBLE_QUEST: True}
        )["Slayer"]
        assert plain[0].xp_per_hour == stated.TOME_PER_HOUR
        assert ramble[0].xp_per_hour == 2 * plain[0].xp_per_hour

    def test_a_non_skill_branch_gets_no_tome(self) -> None:
        assert "Extra" not in stated.methods(INFO, self._VALID, None, frozenset(), {})

    def test_the_quest_is_read_from_the_export_branch(self) -> None:
        assert stated.tome_rate({}) == stated.TOME_PER_HOUR
        assert stated.tome_rate({stated.RAMBLE_QUEST: True}) == stated.TOME_RAMBLE_PER_HOUR


class TestFishingTrawler:
    def test_it_is_a_flat_figure(self) -> None:
        found = stated.methods(
            INFO, {"Fishing": {stated.TRAWLER_TASK: True}}, None, frozenset(), {}
        )["Fishing"]
        assert [m.xp_per_hour for m in found] == [stated.TRAWLER_PER_HOUR]
        assert found[0].level == stated.TRAWLER_OPENS

    def test_a_map_without_it_gets_nothing(self) -> None:
        assert stated.methods(INFO, {"Fishing": {}}, None, frozenset(), {}) == {}


class TestGuardiansOfTheRift:
    def test_the_ceiling_is_the_cap_times_the_games_times_the_experience(self) -> None:
        # 250 fragments a game, six games an hour, 5 experience a fragment.
        assert stated.rift_rate() == 250.0 * 6.0 * 5.0 == 7_500.0

    def test_it_reaches_mining_and_opens_at_one(self) -> None:
        found = stated.methods(
            INFO, {"Mining": {stated.RIFT_TASK: True}}, None, frozenset(), {}
        )["Mining"]
        assert [m.xp_per_hour for m in found] == [7_500.0]
        assert found[0].level == 1

    def test_it_is_a_guess_because_a_ceiling_is_not_a_rate(self) -> None:
        # The cap is arithmetic; "six games an hour" and "mining constantly"
        # are readings, and a ceiling overstates anyone who stops to do the
        # rest of the minigame.
        found = stated.methods(
            INFO, {"Mining": {stated.RIFT_TASK: True}}, None, frozenset(), {}
        )["Mining"]
        assert found[0].match == GUESS

    def test_a_map_that_cannot_reach_the_rift_gets_nothing(self) -> None:
        assert stated.methods(INFO, {"Mining": {}}, None, frozenset(), {}) == {}
