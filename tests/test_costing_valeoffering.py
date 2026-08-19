"""Rummaging vale offerings, where the totem you built decides the loot rate."""

from __future__ import annotations

import pathlib
from typing import Callable

import pytest

from chunksim.costing import valeoffering as vo, valetotems as vt

_VALID: dict[str, dict[str, object]] = {
    "Fletching": {vt.TASKS["Fletching"]: {}}
}


def _logs(
    seconds: float, per_log: dict[str, float] | None = None
) -> Callable[[str, float], float | None]:
    """A stub log bill: a flat per-log cost, or one per log type."""

    def priced(item: str, quantity: float) -> float | None:
        return (per_log or {}).get(item, seconds) * quantity

    return priced


class TestThePublishedChain:
    def test_a_rummage_is_a_hundred_offerings_and_one_roll(self) -> None:
        """"Rummaging the offerings consumes 100 of them for one Vale Research
        Point and one roll of the loot table"."""
        assert vo.OFFERINGS_PER_RUMMAGE == 100.0

    def test_the_ent_branch_share_is_the_pages_own_fraction(self) -> None:
        # `Ent branch` is `65/399` on the Resources table, whose six rows are
        # stated out of 399 - one branch every 6.14 rummages.
        assert vo.SHARES["Ent branch"] == pytest.approx(65 / 399)
        assert vo.rummages_for("Ent branch") == pytest.approx(6.138, abs=0.001)

    def test_the_mask_is_the_pre_roll(self) -> None:
        """The pre-roll's three rows sum to the 1/100 the page names, and the
        mask is 2/1000 of them - one every 500 rummages."""
        assert vo.rummages_for("Greenman mask") == pytest.approx(500.0)

    def test_something_off_the_table_is_not_priced(self) -> None:
        assert vo.rummages_for("Feather") is None
        assert vo.seconds_for("Feather", 99, _logs(10.0)) is None


class TestTheOfferingsColumnIsPerTotem:
    """**The page's hourly column disagrees with the page.** It divides by 112
    on every row where the prose says "13 loops (104 totems) per hour" and the
    Construction table divides out to exactly 104."""

    @pytest.mark.parametrize(
        "log,per_totem,per_hour",
        [
            ("Oak logs", 20.0, 2240.0),
            ("Willow logs", 30.0, 3360.0),
            ("Redwood logs", 105.0, 11760.0),
        ],
    )
    def test_the_hourly_column_is_a_hundred_and_twelve_times(
        self, log: str, per_totem: float, per_hour: float
    ) -> None:
        (totem,) = [t for t in vt.TOTEMS if t.log == log]
        assert totem.offerings == per_totem
        assert per_totem * 112.0 == per_hour
        assert vt.TOTEMS_PER_HOUR == 104.0


class TestTheTierIsChosenByWhatABranchCosts:
    def test_a_dearer_log_can_still_win(self) -> None:
        """Offerings rise with the log - 20 to 105 - so a tier five times the
        chopping can still be cheaper per branch."""
        cheap = vo.seconds_for("Ent branch", 99, _logs(1.0))
        oak_only = vo.seconds_for("Ent branch", 20, _logs(1.0))
        assert cheap is not None and oak_only is not None
        assert cheap < oak_only

    def test_and_an_expensive_log_can_lose(self) -> None:
        """Redwood is 5.25x oak's offerings, so it wins on a flat log bill -
        but a redwood log is not a flat log bill. Charge it ten times oak's
        chopping and oak wins at 99, which is the trade-off this exists to
        make rather than assume."""
        dear = _logs(30.0, {"Redwood logs": 300.0})
        best = vo.seconds_for("Ent branch", 99, dear)
        redwood = vo.seconds_for("Ent branch", 99, _logs(300.0))
        assert best is not None and redwood is not None
        # Magic wins on this bill - 90 offerings at the cheap price - and
        # redwood alone would be a third slower despite paying the most.
        assert best < redwood
        flat = vo.seconds_for("Ent branch", 99, _logs(30.0))
        assert flat is not None and flat < best

    def test_no_route_to_the_logs_is_no_price(self) -> None:
        assert vo.seconds_for("Ent branch", 99, lambda item, q: None) is None


class TestReachability:
    def test_it_is_gated_on_upstreams_own_challenge(self) -> None:
        assert vo.costs({}, {"Fletching": 99}, _logs(10.0)) == {}
        assert vo.costs(_VALID, {"Fletching": 99}, _logs(10.0))

    def test_the_level_is_floored_at_the_minigames_own(self) -> None:
        """`costing/wintertodt.solo_methods`' rule: the challenge being valid
        *is* the statement that this map can play, and the export census
        infers no Fletching level at all - comparing `1 < 20` there reported a
        routable material as unroutable."""
        found = vo.costs(_VALID, {}, _logs(10.0))
        assert set(found) == set(vo.SHARES)
        assert found == vo.costs(_VALID, {"Fletching": vt.OPENS_AT}, _logs(10.0))


class TestItIsWiredIn:
    def test_the_walk_reads_it(self) -> None:
        from chunksim.costing import estimate

        source = pathlib.Path(estimate.__file__).read_text(encoding="utf-8")
        assert "valeoffering.costs(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(vo.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`valeoffering.py`" in listing
