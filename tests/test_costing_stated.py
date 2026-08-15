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


class TestTroubleBrewing:
    _VALID = {
        "Cooking": {"Participate in ~|Trouble Brewing|~": True},
        "Hunter": {"Participate in ~|Trouble Brewing|~ for Hunter xp": True},
        "Extra": {"Participate in ~|Trouble Brewing|~ for Extra xp": True},
    }

    def test_every_skill_it_pays_gets_the_figure(self) -> None:
        found = stated.methods(INFO, self._VALID)
        assert {"Cooking", "Hunter"} <= set(found)

    def test_a_non_skill_branch_is_not_a_training_rate(self) -> None:
        # `Extra` is one of upstream's three non-skill categories; a minigame
        # listed under one must not become experience an hour for it.
        assert "Extra" not in stated.methods(INFO, self._VALID)

    def test_it_is_a_guess_and_says_so(self) -> None:
        found = stated.methods(INFO, self._VALID)["Cooking"]
        assert {method.match for method in found} == {GUESS}
        assert found[0].xp_per_hour == stated.TROUBLE_BREWING_PER_HOUR

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
