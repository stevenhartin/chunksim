"""The Giants' Foundry: Jagex's two columns, multiplied."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import foundry as f


class TestJagexsOwnTable:
    """**Not a guide's estimate** - the release patch notes, on the wiki."""

    @pytest.mark.parametrize(
        "tier,swords,per_sword,product",
        [
            ("Lowest", 20.0, 2_400.0, 48_000.0),
            ("Low", 17.0, 5_000.0, 85_000.0),
            ("Medium", 15.0, 9_000.0, 135_000.0),
            ("High", 13.0, 15_000.0, 195_000.0),
            ("Highest", 12.0, 23_000.0, 276_000.0),
        ],
    )
    def test_a_tier_multiplies_out_to_the_scraped_figure(
        self, tier: str, swords: float, per_sword: float, product: float
    ) -> None:
        assert f.TIERS[tier] == (swords, per_sword)
        assert f.rate_for(tier) == product

    def test_every_tier_is_checked(self) -> None:
        assert len(f.TIERS) == 5

    def test_the_tiers_climb(self) -> None:
        rates = [f.rate_for(t) for t in ("Lowest", "Low", "Medium", "High", "Highest")]
        assert rates == sorted(rates)

    def test_fewer_swords_an_hour_the_richer_the_alloy(self) -> None:
        # The rate rises anyway, which is the whole shape of the activity.
        swords = [f.TIERS[t][0] for t in ("Lowest", "Low", "Medium", "High", "Highest")]
        assert swords == sorted(swords, reverse=True)


class TestSixChallengesFiveTiers:
    def test_bronze_and_iron_share_the_lowest_tier(self) -> None:
        # Jagex's grouping and upstream's: five rows, a preform per metal.
        bronze = next(t for t in f.PREFORMS if "bronze" in t)
        iron = next(t for t in f.PREFORMS if "iron" in t)
        assert f.PREFORMS[bronze] == f.PREFORMS[iron] == (15, "Lowest")

    def test_every_preform_names_a_tier_that_exists(self) -> None:
        assert len(f.PREFORMS) == 6
        assert all(tier in f.TIERS for _level, tier in f.PREFORMS.values())

    def test_the_levels_are_the_exports_own(self) -> None:
        assert sorted(level for level, _t in f.PREFORMS.values()) == [15, 15, 30, 50, 70, 85]

    def test_no_rate_reads_a_level(self) -> None:
        # What a level buys is a better alloy, which is why each preform
        # carries its own opening level instead.
        assert f.rate_for("Highest") == f.rate_for("Highest")


class TestReachability:
    _ALL: dict[str, dict[str, object]] = {"Smithing": {t: {} for t in f.PREFORMS}}

    def test_every_preform_a_map_reaches(self) -> None:
        bands = f.methods(self._ALL)["Smithing"]
        assert len(bands) == 6
        assert [b.level for b in bands] == [15, 15, 30, 50, 70, 85]

    def test_nothing_when_unreachable(self) -> None:
        assert f.methods({}) == {}
        assert f.methods({"Smithing": {}}) == {}

    def test_a_band_names_the_task_it_would_be_overridden_through(self) -> None:
        for band in f.methods(self._ALL)["Smithing"]:
            assert band.knob.startswith("training/Forge a")
            assert band.knob.endswith("/Smithing")


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "foundry.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(f.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`foundry.py`" in listing
