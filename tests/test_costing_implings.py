"""`costing/implings.py`: Puro-Puro as one method.

The arithmetic is a knapsack over an hour, so the tests are about the ordering
and the two gates - the realm, and the level - rather than about the total,
which no published figure checks.
"""

from __future__ import annotations

import pytest

from chunksim.costing import implings
from chunksim.costing.gathering import Tables

TABLES = Tables(
    curves={
        "baby impling": (("Baby impling", 200.0, 400.0, 17),),
        "eclectic impling": (("Eclectic impling", 100.0, 400.0, 50),),
        "nature impling": (("Nature impling", 100.0, 400.0, 58),),
        "lucky impling": (("Lucky impling", 50.0, 300.0, 89),),
    },
    experience={
        "Hunter": {
            "baby impling": (18.0, "Butterfly net"),
            "eclectic impling": (32.0, "Butterfly net"),
            "nature impling": (34.0, "Butterfly net"),
            "lucky impling": (80.0, "Butterfly net"),
        }
    },
    spawn_tiers={
        "Low-tier": (("Baby impling", 0.5), ("Eclectic impling", 0.5)),
        "Mid-tier": (("Nature impling", 1.0),),
        "High-tier (Puro-Puro)": (("Lucky impling", 1.0),),
    },
)
VALID = {"Hunter": {implings.PURO_PURO_TASK: True}}


class TestSupply:
    def test_a_point_yields_once_per_invisible_cycle(self) -> None:
        # 12 mid-tier points, two minutes each, one impling in that table.
        supply = implings.supply_per_hour(TABLES)
        assert supply["Nature impling"] == pytest.approx(12 * 3600.0 / 120.0)

    def test_the_low_tier_is_not_counted(self) -> None:
        # 51 fixed spawns on a 4.2-second respawn make it a floor rather than
        # a supply; `puro_puro_rate` treats absence as "always available".
        assert "Baby impling" not in implings.supply_per_hour(TABLES)


class TestRate:
    def test_the_best_impling_is_taken_first(self) -> None:
        _total, caught = implings.puro_puro_rate(TABLES, 99, 4.2) or (0.0, {})
        # Every lucky impling the two high-tier points offer, and no more.
        assert caught["Lucky impling"] == pytest.approx(
            implings.supply_per_hour(TABLES)["Lucky impling"]
        )

    def test_the_low_tier_fills_whatever_time_is_left(self) -> None:
        _total, caught = implings.puro_puro_rate(TABLES, 99, 4.2) or (0.0, {})
        assert caught["Eclectic impling"] > caught["Nature impling"]

    def test_a_level_that_unlocks_nothing_prices_nothing(self) -> None:
        assert implings.puro_puro_rate(TABLES, 16, 4.2) is None

    def test_the_rate_climbs_as_levels_unlock_better_implings(self) -> None:
        low = implings.puro_puro_rate(TABLES, 17, 4.2)
        high = implings.puro_puro_rate(TABLES, 99, 4.2)
        assert low is not None and high is not None
        assert high[0] > low[0]

    def test_empty_tables_price_nothing(self) -> None:
        assert implings.puro_puro_rate(Tables(), 99, 4.2) is None


class TestGate:
    def test_a_map_without_the_realm_gets_nothing(self) -> None:
        # Upstream's gate, not this project's: the challenge carries
        # `Chunks: ["Puro-Puro"]`, so it is absent from `valid` without it.
        assert implings.methods(TABLES, {"Hunter": {}}) == {}

    def test_a_map_with_the_realm_gets_one_method(self) -> None:
        found = implings.methods(TABLES, VALID)
        assert list(found) == [implings.PURO_PURO_TASK]

    def test_it_opens_at_seventeen_not_at_the_challenges_level(self) -> None:
        # The export says `Level: 1` because what gates it is holding the
        # realm; the method itself needs 17.
        (rates,) = implings.methods(TABLES, VALID).values()
        assert min(rate.level for rate in rates) == implings.PURO_PURO_OPENS

    def test_every_rate_is_one_method_under_one_name(self) -> None:
        (rates,) = implings.methods(TABLES, VALID).values()
        assert {rate.node for rate in rates} == {"Puro-Puro"}
        assert {rate.task for rate in rates} == {implings.PURO_PURO_TASK}
