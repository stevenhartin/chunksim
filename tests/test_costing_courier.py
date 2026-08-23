"""Courier tasks: the best leg a map's ports and water allow."""

from __future__ import annotations

import pathlib
from typing import Any

import pytest

from chunksim.costing import courier
from chunksim.costing.gathering import GUESS
from chunksim.costing.heuristics import ComputedMethod
from chunksim.model.chunkinfo import ChunkInfo

#: Four ports in a row on one east-west line, so the sea hops are readable:
#: chunk ids differ by 1 along x. `Cove` has no board.
_BLOB: dict[str, object] = {
    "ports": {
        "Alpha": {"chunk": "1000", "x": 0, "y": 0, "board": True},
        "Beta": {"chunk": "1002", "x": 0, "y": 0, "board": True},
        "Gamma": {"chunk": "1006", "x": 0, "y": 0, "board": True},
        "Cove": {"chunk": "1004", "x": 0, "y": 0, "board": False},
    },
    "tasks": [
        # Alpha <-> Beta: two hops, a plain task and a displaced one.
        {"level": 1, "experience": 100, "notice_board": "Alpha",
         "cargo": "Alpha", "destination": "Beta", "crates": 1},
        {"level": 1, "experience": 200, "notice_board": "Beta",
         "cargo": "Alpha", "destination": "Beta", "crates": 1},
        # Alpha -> Gamma: six hops, far more experience.
        {"level": 40, "experience": 900, "notice_board": "Alpha",
         "cargo": "Alpha", "destination": "Gamma", "crates": 1},
        # Only Cove's board could offer this one, and Cove has none.
        {"level": 1, "experience": 5000, "notice_board": "Cove",
         "cargo": "Cove", "destination": "Alpha", "crates": 1},
    ],
}
_OCEAN = [str(1000 + n) for n in range(7)]
_SECTIONS: dict[str, dict[str, object]] = {}
_HELD = {chunk: True for chunk in _OCEAN}
_VALID: dict[str, dict[str, object]] = {
    "Sailing": {
        courier.TASK: {},
        courier.BOARD_TASK.format(port="Alpha"): {},
        courier.BOARD_TASK.format(port="Beta"): {},
        courier.BOARD_TASK.format(port="Gamma"): {},
    }
}


def _methods(**kw: Any) -> dict[str, tuple[ComputedMethod, ...]]:
    args: dict[str, Any] = {
        "valid": _VALID, "held": _HELD, "ocean": _OCEAN,
        "sections": _SECTIONS, "blob": _BLOB,
    }
    args.update(kw)
    return courier.methods(**args)


class TestTheSea:
    def test_a_coastal_chunk_is_navigable_through_its_water_section(self) -> None:
        """A port is land; what makes it sailable is the `W` section beside
        the land ones, which is how the export carries a chunk's water."""
        found = courier.navigable_chunks(
            ["50"], {"60": {"1": [], "W1": []}, "70": {"1": [], "2": []}}
        )
        assert found == frozenset({"50", "60"})

    def test_hops_are_grid_adjacency_over_water_the_map_holds(self) -> None:
        hops = courier.sea_hops("1000", frozenset(_OCEAN), frozenset(_OCEAN))
        assert hops["1002"] == 2
        assert hops["1006"] == 6

    def test_water_the_map_lacks_blocks_the_crossing(self) -> None:
        """**The chunks in between.** Upstream gates courier tasks on two port
        locations and says nothing about the sea; requiring the crossing is
        stricter than upstream, deliberately."""
        held = frozenset(_OCEAN) - {"1003"}
        hops = courier.sea_hops("1000", frozenset(_OCEAN), held)
        assert "1002" in hops
        assert "1006" not in hops

    def test_a_chunk_the_map_does_not_hold_is_not_a_source(self) -> None:
        assert courier.sea_hops("1000", frozenset(_OCEAN), frozenset()) == {}


class TestWhatCounts:
    def test_a_ledger_only_port_is_reachable_by_its_chunk(self) -> None:
        ports = courier.ports_from(_BLOB)
        usable, boards = courier.reachable_ports(ports, _VALID, frozenset(_OCEAN))
        assert usable == {"Alpha", "Beta", "Gamma", "Cove"}
        assert boards == {"Alpha", "Beta", "Gamma"}

    def test_a_board_port_needs_upstreams_own_challenge(self) -> None:
        """No level is compared here - upstream's challenge carries the chunk,
        the level and any quest, so its validity is the whole gate."""
        ports = courier.ports_from(_BLOB)
        thin: dict[str, dict[str, object]] = {
            "Sailing": {courier.BOARD_TASK.format(port="Alpha"): {}}
        }
        usable, boards = courier.reachable_ports(ports, thin, frozenset(_OCEAN))
        assert boards == {"Alpha"}
        assert "Beta" in usable  # its chunk is held, so it can still be a ledger

    def test_a_task_from_a_boardless_port_is_never_offered(self) -> None:
        """Cove's 5,000-experience delivery is the best in the fixture and
        unreachable: nothing there hands it out."""
        bands = _methods()["Sailing"]
        assert all("Cove" not in band.method for band in bands)


class TestTheBestLeg:
    def test_the_displaced_task_is_worth_double_and_wins(self) -> None:
        legs = courier.legs_for(
            courier.tasks_from(_BLOB),
            courier.ports_from(_BLOB),
            frozenset({"Alpha", "Beta", "Gamma"}),
            frozenset({"Alpha", "Beta", "Gamma"}),
            {"1000": {"1002": 2, "1006": 6}},
            1,
        )
        (leg,) = legs
        assert (leg.origin, leg.destination) == ("Alpha", "Beta")
        # One slot at level 1, so only the better of the two is carried.
        assert leg.experience == 200
        assert leg.tasks == 1

    def test_a_second_slot_carries_the_second_task(self) -> None:
        """The slot table is published - 1/2/3/4/5 at levels 1/7/28/56/84."""
        assert courier.slots_at(1) == 1
        assert courier.slots_at(7) == 2
        assert courier.slots_at(84) == 5
        legs = courier.legs_for(
            courier.tasks_from(_BLOB),
            courier.ports_from(_BLOB),
            frozenset({"Alpha", "Beta"}),
            frozenset({"Alpha", "Beta"}),
            {"1000": {"1002": 2}},
            7,
        )
        (leg,) = legs
        assert leg.experience == 300 and leg.tasks == 2

    def test_the_overhead_stops_short_legs_winning(self) -> None:
        """**Without it the model chases adjacent ports.** A one-hop leg has
        almost no sailing in it, so experience per hop is unbounded; the
        per-task term is what makes a long leg the better route."""
        near = courier.Leg("A", "B", hops=1, experience=400, tasks=1)
        far = courier.Leg("A", "C", hops=8, experience=3200, tasks=1)
        assert courier.rate_of(far) > courier.rate_of(near)

    def test_best_leg_is_none_without_any(self) -> None:
        assert courier.best_leg(()) is None


class TestTheBands:
    def test_a_band_opens_where_the_best_route_improves(self) -> None:
        bands = _methods()["Sailing"]
        assert [b.level for b in bands] == [1, 40]
        assert bands[1].xp_per_hour > bands[0].xp_per_hour
        assert "Alpha to Gamma" in bands[1].method

    def test_every_band_is_a_guess(self) -> None:
        """Two fitted constants, so `costing/tempoross.py`'s rule twice over."""
        assert {b.match for b in _methods()["Sailing"]} == {GUESS}

    def test_every_band_lands_on_upstreams_own_challenge(self) -> None:
        assert {b.knob for b in _methods()["Sailing"]} == {
            f"training/{courier.TASK}/Sailing"
        }


class TestReachability:
    def test_nothing_without_upstreams_challenge(self) -> None:
        assert _methods(valid={"Sailing": {}}) == {}

    def test_nothing_with_only_one_board(self) -> None:
        """Upstream gates the challenge on `PortTaskLocations[+]x2`, and a
        single board cannot supply a delivery to anywhere else."""
        one: dict[str, dict[str, object]] = {
            "Sailing": {courier.TASK: {}, courier.BOARD_TASK.format(port="Alpha"): {}}
        }
        assert _methods(valid=one) == {}

    def test_nothing_when_the_water_between_is_missing(self) -> None:
        held = {chunk: True for chunk in _OCEAN if chunk != "1001"}
        assert _methods(held=held) == {}

    def test_nothing_without_the_scrape(self) -> None:
        """The blob ships with the package, so a checkout that has not run
        `chunksim heuristics` prices no courier tasks rather than failing."""
        assert _methods(blob={}) == {}


@pytest.mark.real_export
class TestAgainstTheRealTable:
    def test_the_fitted_constants_still_reproduce_the_published_figure(
        self, real_export: ChunkInfo
    ) -> None:
        """**The calibration, pinned.** Both constants are fitted, and the only
        anchor is the optimisation guide's "around 200k/hr" for a good route on
        a complete port set. If the table or the sea changes under them, this
        is what says so."""
        from chunksim.store import cache

        blob = cache.read_blob(cache.COURIER_BLOB_NAME)["data"]
        ports = courier.ports_from(blob)
        every = frozenset(ports)
        boards = frozenset(n for n, p in ports.items() if p.board)
        navigable = courier.navigable_chunks(
            real_export.rolling_chunks.get("ocean") or (), real_export.sections
        )
        distances = {
            ports[n].chunk: courier.sea_hops(ports[n].chunk, navigable, navigable)
            for n in every
        }
        leg = courier.best_leg(
            courier.legs_for(courier.tasks_from(blob), ports, every, boards, distances, 99)
        )
        assert leg is not None
        assert courier.rate_of(leg) == pytest.approx(
            courier.PUBLISHED_XP_PER_HOUR, rel=0.02
        )

    def test_the_best_route_is_one_the_guide_names(
        self, real_export: ChunkInfo
    ) -> None:
        """The second half of the calibration, and the only check available on
        the *ranking*: `Guide:Courier Task Optimizations` names prif-to-lunar
        among its routes, and the model picks it out of 271 legs."""
        from chunksim.store import cache

        blob = cache.read_blob(cache.COURIER_BLOB_NAME)["data"]
        ports = courier.ports_from(blob)
        every = frozenset(ports)
        boards = frozenset(n for n, p in ports.items() if p.board)
        navigable = courier.navigable_chunks(
            real_export.rolling_chunks.get("ocean") or (), real_export.sections
        )
        distances = {
            ports[n].chunk: courier.sea_hops(ports[n].chunk, navigable, navigable)
            for n in every
        }
        leg = courier.best_leg(
            courier.legs_for(courier.tasks_from(blob), ports, every, boards, distances, 99)
        )
        assert leg is not None
        assert (leg.origin, leg.destination) == ("Prifddinas", "Lunar Isle")

    def test_the_whole_sea_is_one_body_of_water(
        self, real_export: ChunkInfo
    ) -> None:
        """**Why grid adjacency and not the `sections` branch.** That branch is
        walking connectivity and breaks the water into dozens of pieces; open
        water should be one."""
        navigable = courier.navigable_chunks(
            real_export.rolling_chunks.get("ocean") or (), real_export.sections
        )
        first = next(iter(sorted(navigable)))
        assert len(courier.sea_hops(first, navigable, navigable)) == len(navigable)


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "courier.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = (
            pathlib.Path(courier.__file__)
            .with_name("__init__.py")
            .read_text(encoding="utf-8")
        )
        assert "`courier.py`" in listing
