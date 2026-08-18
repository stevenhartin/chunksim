"""Vale Totems, a Fletching minigame that pays a little Construction too."""

from __future__ import annotations

import pytest

from chunksim.costing import valetotems as vale


#: `Vale Totems/Strategies`' "Base Totem XP and Offerings" - the per-totem and
#: per-hour columns, which are two separate published statements.
_PUBLISHED = {
    "Oak logs": (254.8, 26_499.2),
    "Willow logs": (634.4, 65_977.6),
    "Maple logs": (1_007.2, 104_748.8),
    "Yew logs": (1_635.2, 170_060.8),
    "Magic logs": (3_103.6, 322_774.4),
    "Redwood logs": (3_787.2, 393_868.8),
}

#: The Construction table, `104 x level` on every published row.
_CONSTRUCTION = {1: 104, 20: 2_080, 40: 4_160, 60: 6_240, 70: 7_280,
                 80: 8_320, 90: 9_360, 95: 9_880, 99: 10_296}


class TestTheTwoPublishedTablesClose:
    def test_a_totem_is_four_actions_and_four_decorations(self) -> None:
        """"the result of the building action, three carvings, and four
        decorations" - all six rows to the tenth of an experience point."""
        for totem in vale.TOTEMS:
            assert totem.fletching_xp == pytest.approx(_PUBLISHED[totem.log][0])

    def test_the_per_hour_column_is_the_same_constant(self) -> None:
        """`TOTEMS_PER_HOUR` is not fitted here - it is the Construction
        table's own divisor, and it reproduces the Fletching one too."""
        for totem in vale.TOTEMS:
            hourly = totem.fletching_xp * vale.TOTEMS_PER_HOUR
            assert hourly == pytest.approx(_PUBLISHED[totem.log][1])

    def test_construction_is_one_point_per_level_per_totem(self) -> None:
        """"one Construction experience point per level, e.g., 70XP at level
        70, unaffected by totem type" - all nine published rows."""
        for level, hourly in _CONSTRUCTION.items():
            computed = vale.CONSTRUCTION_XP_PER_LEVEL * level * vale.TOTEMS_PER_HOUR
            assert computed == pytest.approx(hourly, abs=0.5)

    def test_the_redwood_row_is_a_wiki_typo(self) -> None:
        """Five of six rows agree to the decimal, so the sixth reads as a
        digit transposition (published 393,686.8) rather than a disagreement
        about the mechanic."""
        redwood = vale.TOTEMS[-1]

        assert redwood.fletching_xp * vale.TOTEMS_PER_HOUR == pytest.approx(393_868.8)


class TestTheLogsAreCharged:
    """Every published rate assumes the logs were bought - the calculator says
    so outright. A chunk map cannot, and at 104 totems an hour five logs each
    is 520 an hour."""

    def test_the_bare_cycle_is_the_published_one(self) -> None:
        assert vale.seconds_per_totem(vale.TOTEMS[0], None) == pytest.approx(
            3600.0 / vale.TOTEMS_PER_HOUR
        )

    def test_charging_logs_lengthens_the_cycle(self) -> None:
        cycle = vale.seconds_per_totem(vale.TOTEMS[0], lambda item, qty: 10.0 * qty)

        assert cycle == pytest.approx(3600.0 / vale.TOTEMS_PER_HOUR + 50.0)

    def test_no_route_to_the_logs_is_no_rate(self) -> None:
        assert vale.seconds_per_totem(vale.TOTEMS[0], lambda i, q: None) is None
        assert vale.fletching_rate(99, lambda i, q: None) == 0.0

    def test_five_logs_a_totem(self) -> None:
        """"one to build the totem and four fletched items for decorations"."""
        asked: list[tuple[str, float]] = []

        def record(item: str, quantity: float) -> float:
            asked.append((item, quantity))
            return 1.0

        vale.seconds_per_totem(vale.TOTEMS[0], record)

        assert asked == [("Oak logs", 5.0)]


class TestTheTwoSkillsWantDifferentLogs:
    """Fletching's payout scales hard with the log; Construction's does not
    scale with it at all."""

    def _seconds(self, item: str, quantity: float) -> float:
        # Redwood far dearer than oak, as chopping really is.
        per_log = {"Oak logs": 2.0, "Redwood logs": 40.0}
        return per_log.get(item, 10.0) * quantity

    def test_fletching_takes_the_most_valuable_tier(self) -> None:
        best = vale.fletching_rate(99, self._seconds)
        oak_only = vale.fletching_rate(20, self._seconds)

        assert best > oak_only

    def test_construction_takes_the_cheapest(self) -> None:
        """Its experience is flat in the log, so a dearer tier is pure cost -
        a level-99 fletcher still builds oak totems for Construction."""
        at_99 = vale.construction_rate(70, 99, self._seconds)
        at_20 = vale.construction_rate(70, 20, self._seconds)

        assert at_99 == pytest.approx(at_20)

    def test_construction_scales_with_its_own_level(self) -> None:
        assert vale.construction_rate(80, 99, self._seconds) == pytest.approx(
            2 * vale.construction_rate(40, 99, self._seconds)
        )

    def test_a_tier_above_the_level_is_not_offered(self) -> None:
        assert vale.fletching_rate(19) == 0.0
        assert vale.fletching_rate(20) == pytest.approx(
            vale.TOTEMS[0].fletching_xp * vale.TOTEMS_PER_HOUR
        )


class TestTheGate:
    _VALID = {
        "Fletching": {vale.TASKS["Fletching"]: True},
        "Construction": {vale.TASKS["Construction"]: True},
    }

    def test_both_skills_when_both_are_reachable(self) -> None:
        found = vale.methods(self._VALID, {"Fletching": 99})

        assert set(found) == {"Fletching", "Construction"}

    def test_construction_gates_on_the_fletching_challenge(self) -> None:
        """Upstream gives its Construction twin `Level: 1`, because what
        gates the minigame is Fletching 20 and the miniquest - so a rate
        written against that level would offer it to a player who cannot
        enter."""
        found = vale.methods(
            {"Construction": self._VALID["Construction"]}, {"Fletching": 99}
        )

        assert found == {}

    def test_a_map_reaching_only_the_fletching_half_gets_only_that(self) -> None:
        """Construction experience needs a house, which upstream states as a
        chunk and the derivation enforces."""
        found = vale.methods({"Fletching": self._VALID["Fletching"]}, {"Fletching": 99})

        assert set(found) == {"Fletching"}

    def test_an_unknown_fletching_level_reads_the_minimum(self) -> None:
        """A player inside the minigame is at least 20, so Construction is
        priced on oak rather than refused."""
        found = vale.methods(self._VALID, {})

        assert found["Construction"]
