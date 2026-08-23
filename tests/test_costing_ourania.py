"""The Ourania Altar: the published column read back out of its components."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import ourania
from chunksim.costing.gathering import CONFIRMED
from chunksim.model.chunkinfo import ChunkInfo

_VALID: dict[str, dict[str, object]] = {"Runecraft": {ourania.TASK: {}}}


class TestThePublishedColumnIsTheOracle:
    def test_every_row_is_reproduced_to_the_experience(self) -> None:
        """**Not agreement, an identity** - each cell of the wiki's table is
        `{{#expr:xp_per_ess * ess_per_lap * (3600 - lost) / 48}}`, and this
        reads the same three components. What that buys is a check rather than
        a fit: the day the wiki re-times a lap or re-derives the distribution,
        this fails instead of the two drifting apart."""
        for band in ourania.BANDS:
            assert round(ourania.rate_at(band)) == band.published, band.level

    def test_the_table_is_the_pages_own_bands(self) -> None:
        assert [band.level for band in ourania.BANDS] == [
            1, 10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 85, 90, 99
        ]

    def test_the_lap_is_the_pages_stated_assumption(self) -> None:
        assert ourania.LAP_SECONDS == 48.0


class TestTheComponentsAreMechanicsRatherThanNumbers:
    def test_every_essence_step_is_a_pouch(self) -> None:
        """28 slots less the rune pouch and one per essence pouch, plus what
        they hold - and the colossal pouch at 85 replacing all four."""
        assert [band.essence_per_lap for band in ourania.BANDS] == [
            29, 29, 29,          # small:              26 + 3
            34, 34, 34,          # + medium:       25 + 3+6
            42, 42, 42,          # + large:      24 + 3+6+9
            53, 53,              # + giant:   23 + 3+6+9+12
            66, 66, 66,          # colossal:          26 + 40
        ]
        assert 26 + 3 == 29
        assert 25 + 3 + 6 == 34
        assert 24 + 3 + 6 + 9 == 42
        assert 23 + 3 + 6 + 9 + 12 == 53
        assert 26 + 40 == 66

    def test_the_contact_cost_steps_with_the_tiers_and_ends_at_99(self) -> None:
        """15 seconds an hour per pouch tier unlocked - and **zero at 99**,
        because the Runecraft cape stops pouches degrading, which is why the
        last band jumps. A quotient would have hidden that."""
        assert [band.contact_seconds for band in ourania.BANDS] == [
            0.0, 0.0, 0.0, 15.0, 15.0, 15.0, 30.0, 30.0, 30.0,
            45.0, 45.0, 60.0, 60.0, 0.0,
        ]

    def test_the_cape_is_worth_more_than_the_distribution_at_the_top(self) -> None:
        """90-98 and 99 differ in two things at once, and the smaller
        distribution step is not the bigger half of the jump."""
        ninety, ninetynine = ourania.BANDS[-2], ourania.BANDS[-1]
        assert ninety.essence_per_lap == ninetynine.essence_per_lap
        assert ninetynine.published > ninety.published


class TestTheEssenceIsMostOfTheAnswer:
    def test_mining_it_costs_three_quarters_of_a_lap(self) -> None:
        """66 essence at 2.4 seconds is 158 against a 48-second lap."""
        top = ourania.BANDS[-1]
        mined = ourania.rate_at(top, 2.4)
        assert round(mined) == 17_935
        assert mined < top.published / 4

    def test_the_correction_flattens_the_curve(self) -> None:
        """**The finding.** A bigger pouch buys fewer trips and buys nothing
        at the rock, so the pouch tiers - which are the published column's
        biggest steps - are worth far less to a map that mines its own."""
        first, last = ourania.BANDS[0], ourania.BANDS[-1]
        published_span = last.published / first.published
        mined_span = ourania.rate_at(last, 2.4) / ourania.rate_at(first, 2.4)
        assert published_span == pytest.approx(3.78, abs=0.02)
        assert mined_span == pytest.approx(2.15, abs=0.02)
        assert mined_span < published_span

    def test_the_bands_are_folded_rather_than_declared(self) -> None:
        """`Heuristics.material_seconds_per_xp` is one number per task and the
        cost per experience moves with the band, since `xp_per_essence` rises
        while an essence keeps costing the same - `costing/crane.py`'s
        reason."""
        bands = ourania.methods(_VALID, lambda item, qty: 2.4)["Runecraft"]
        assert [round(b.xp_per_hour) for b in bands][:3] == [8_336, 9_339, 10_067]


class TestReachability:
    def test_nothing_without_the_altar(self) -> None:
        assert ourania.methods({}) == {}
        assert ourania.methods({"Runecraft": {}}) == {}

    def test_no_route_to_an_essence_is_no_rate(self) -> None:
        """`costing/crane.py`'s refusal: tick-math over an input nothing can
        price is a made-up number, and here it would be the whole method."""
        assert ourania.methods(_VALID, lambda item, qty: None) == {}

    def test_the_walk_is_asked_for_the_essence_upstream_names(self) -> None:
        asked: list[tuple[str, float]] = []

        def seconds(item: str, qty: float) -> float:
            asked.append((item, qty))
            return 2.4

        ourania.methods(_VALID, seconds)
        assert asked == [("Pure essence", 1.0)]

    def test_omitting_the_walk_leaves_the_published_ceiling(self) -> None:
        bands = ourania.methods(_VALID)["Runecraft"]
        assert [round(b.xp_per_hour) for b in bands] == [
            band.published for band in ourania.BANDS
        ]

    def test_every_band_lands_on_the_one_challenge(self) -> None:
        bands = ourania.methods(_VALID, lambda item, qty: 2.4)["Runecraft"]
        assert {b.knob for b in bands} == {f"training/{ourania.TASK}/Runecraft"}
        assert {b.match for b in bands} == {CONFIRMED}


@pytest.mark.real_export
class TestUpstreamStillCarriesWhatThisNames:
    def test_the_challenge_exists_and_names_pure_essence(
        self, real_export: ChunkInfo
    ) -> None:
        """**Daeyalt is why this is asserted.** The page tabulates it at a flat
        1.5x, and the reason it is not modelled is that upstream's `Items` says
        pure essence and nothing else."""
        challenge = (real_export.challenges.get("Runecraft") or {}).get(ourania.TASK)
        assert isinstance(challenge, dict), "upstream lost the Ourania challenge"
        assert challenge.get("Primary") is True
        assert challenge.get("Items") == ["Pure essence*"]
        assert challenge.get("Level") == 1


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "ourania.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = (
            pathlib.Path(ourania.__file__)
            .with_name("__init__.py")
            .read_text(encoding="utf-8")
        )
        assert "`ourania.py`" in listing
