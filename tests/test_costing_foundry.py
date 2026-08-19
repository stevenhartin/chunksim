"""The Giants' Foundry: an alloy, a mould, and a closed formula."""

from __future__ import annotations

import math
import pathlib

import pytest

from chunksim.costing import foundry as f


class TestTheExperienceFormula:
    """`(floor(q^2 / 73) + floor(1.5q) + 1) * 30`, off the main page."""

    def test_the_worked_example(self) -> None:
        # 14 mithril and 14 adamant is a metal score of 95; with the purchased
        # moulds' 59 that is quality 154, and 154 pays 16,680.
        assert f.quality(95) == 154.0
        assert f.experience_per_sword(154) == 16_680.0

    def test_the_ends_the_page_quotes(self) -> None:
        # "ranges from 30 experience for turning in a sword of 0 quality, up
        # to 25,230 experience for a sword with the maximum quality of 199".
        assert f.experience_per_sword(0) == 30.0
        assert f.experience_per_sword(199) == 25_230.0

    def test_it_is_the_formula_and_not_a_table(self) -> None:
        for q in (17, 88, 123, 176):
            assert f.experience_per_sword(q) == (
                math.floor(q * q / 73) + math.floor(1.5 * q) + 1
            ) * 30


class TestTheAlloyTable:
    def test_the_best_ratios_are_the_strategy_pages(self) -> None:
        best = {(a.first, a.second): (a.metal_score, a.ratio) for a in f.ALLOYS}
        assert best[("mithril", "adamant")] == (95, (14, 14))
        assert best[("adamant", "rune")] == (130, (14, 14))
        assert best[("bronze", "iron")] == (21, (9, 19))
        assert best[("bronze", "rune")] == (60, (4, 24))

    def test_every_ratio_is_twenty_eight_bars(self) -> None:
        # "the user must provide a combined total of 28 bars".
        assert f.BARS_PER_PREFORM == 28
        for alloy in f.ALLOYS:
            assert sum(alloy.ratio) == f.BARS_PER_PREFORM

    def test_all_fifteen_pairs_are_carried(self) -> None:
        assert len(f.ALLOYS) == 15
        assert len({(a.first, a.second) for a in f.ALLOYS}) == 15

    def test_a_pair_needs_its_higher_metals_level(self) -> None:
        rune = [a for a in f.ALLOYS if "rune" in (a.first, a.second)]
        assert {a.level for a in rune} == {85}


class TestDifficulty:
    @pytest.mark.parametrize(
        "score,sections",
        [(10, 3), (19, 3), (20, 4), (59, 4), (60, 5), (89, 5), (90, 6), (119, 6), (120, 7), (130, 7)],
    )
    def test_the_bands_are_the_pages(self, score: int, sections: int) -> None:
        assert f.sections_for(score) == sections

    def test_a_sword_costs_the_preamble_and_its_sections(self) -> None:
        assert f.PREAMBLE_SECONDS == 30.0
        assert f.SECONDS_PER_SECTION == 45.0
        assert f.seconds_per_sword(95) == 30.0 + 45.0 * 6
        assert f.swords_per_hour(95) == pytest.approx(12.0)


class TestTheBestAlloyIsNotTheHighestScoring:
    """**The whole reason a tier summary was the wrong model.**

    The tier is the thing being chosen against, so a model built on tiers
    cannot express that a lower-scoring alloy can be faster.
    """

    ALL = frozenset(f.PREFORMS)

    def test_bronze_and_rune_lose_to_bronze_and_adamant(self) -> None:
        rune = next(a for a in f.ALLOYS if (a.first, a.second) == ("bronze", "rune"))
        adam = next(a for a in f.ALLOYS if (a.first, a.second) == ("bronze", "adamant"))
        assert rune.metal_score > adam.metal_score
        assert f.rate_for(rune) < f.rate_for(adam)
        assert f.sections_for(rune.metal_score) > f.sections_for(adam.metal_score)

    def test_level_fifty_picks_iron_mithril_over_steel_mithril(self) -> None:
        # 51 points in four sections beats 65 in five.
        chosen = f.best_alloy(50, self.ALL)
        assert chosen is not None
        assert (chosen.first, chosen.second) == ("iron", "mithril")

    def test_the_chosen_alloy_climbs_with_the_level(self) -> None:
        rates = [f.rate_for(a) for lvl in f.BANDS if (a := f.best_alloy(lvl, self.ALL))]
        assert rates == sorted(rates)


class TestAgainstTheStrategyPagesHourlyTable:
    """Five alloys with a published swords-an-hour and experience-an-hour."""

    PUBLISHED = {
        ("bronze", "iron"): 97_920.0,
        ("iron", "steel"): 133_920.0,
        ("steel", "mithril"): 164_640.0,
        ("mithril", "adamant"): 198_000.0,
        ("adamant", "rune"): 253_110.0,
    }

    @pytest.mark.parametrize("pair,published", sorted(PUBLISHED.items()))
    def test_a_row_lands_within_a_tenth(
        self, pair: tuple[str, str], published: float
    ) -> None:
        alloy = next(a for a in f.ALLOYS if (a.first, a.second) == pair)
        assert f.rate_for(alloy) == pytest.approx(published, rel=0.10)

    def test_the_two_richest_alloys_land_within_two_percent(self) -> None:
        # The rows a player at 70+ would actually run. The loose ones are the
        # four-section alloys, where the table's integer swords-an-hour of 16
        # implies 225 seconds against this model's 210.
        for pair in (("mithril", "adamant"), ("steel", "mithril")):
            alloy = next(a for a in f.ALLOYS if (a.first, a.second) == pair)
            assert f.rate_for(alloy) == pytest.approx(
                self.PUBLISHED[pair], rel=0.022
            )

    def test_the_four_section_rows_are_the_loose_ones(self) -> None:
        for pair in (("bronze", "iron"), ("iron", "steel")):
            alloy = next(a for a in f.ALLOYS if (a.first, a.second) == pair)
            assert f.sections_for(alloy.metal_score) == 4
            assert 1.05 < f.rate_for(alloy) / self.PUBLISHED[pair] < 1.10

    def test_the_pages_own_table_implies_a_mould_of_fifty_eight(self) -> None:
        # **Followed as stated rather than back-fitted.** The prose says 59
        # and the table says 58 on every row; using the prose figure is what
        # makes the residual above readable instead of tuned away.
        assert f.MOULD_SCORE == 59.0
        for pair, published in self.PUBLISHED.items():
            alloy = next(a for a in f.ALLOYS if (a.first, a.second) == pair)
            per_sword = published / f.swords_per_hour(alloy.metal_score)
            implied = f.quality(alloy.metal_score, mould_score=58.0)
            assert f.experience_per_sword(implied) == pytest.approx(
                per_sword, rel=0.10
            )

    def test_the_default_moulds_are_carried_and_not_spent(self) -> None:
        assert f.DEFAULT_MOULD_SCORE == 38.0
        assert f.rate_for(f.ALLOYS[0], mould_score=f.DEFAULT_MOULD_SCORE) < f.rate_for(
            f.ALLOYS[0]
        )


class TestReachableBarsDecideTheAlloy:
    def test_a_map_without_rune_never_runs_a_rune_alloy(self) -> None:
        metals = frozenset({"bronze", "iron", "steel", "mithril", "adamant"})
        chosen = f.best_alloy(99, metals)
        assert chosen is not None
        assert "rune" not in (chosen.first, chosen.second)
        assert (chosen.first, chosen.second) == ("mithril", "adamant")

    def test_one_metal_alone_can_make_no_alloy(self) -> None:
        assert f.best_alloy(99, frozenset({"rune"})) is None

    def test_nothing_below_the_first_alloys_level(self) -> None:
        assert f.best_alloy(14, frozenset(f.PREFORMS)) is None


class TestReachability:
    _ALL: dict[str, dict[str, object]] = {"Smithing": {t: {} for t in f.PREFORMS.values()}}

    def test_one_band_a_level_on_its_dearer_metals_challenge(self) -> None:
        # **One band, one task, one material cost.** Putting every alloy on
        # every preform let the walk pair an adamant-and-rune rate with the
        # bronze preform's bar cost.
        bands = f.methods(self._ALL)["Smithing"]
        assert len(bands) == len(f.BANDS)
        assert {b.level for b in bands} == set(f.BANDS)
        assert len({b.knob for b in bands}) == len(f.BANDS)

    def test_bronze_carries_no_band_because_it_is_never_the_dearer_half(self) -> None:
        # The activity is still covered: bronze's one good alloy is
        # bronze-and-iron, emitted on the iron challenge.
        knobs = {b.knob for b in f.methods(self._ALL)["Smithing"]}
        assert f"training/{f.PREFORMS['bronze']}/Smithing" not in knobs
        assert any("bronze" in b.method for b in f.methods(self._ALL)["Smithing"])
        assert all(a.second != "bronze" for a in f.ALLOYS)

    def test_a_map_with_one_metal_is_offered_nothing(self) -> None:
        one: dict[str, dict[str, object]] = {"Smithing": {f.PREFORMS["rune"]: {}}}
        assert f.methods(one) == {}

    def test_nothing_when_unreachable(self) -> None:
        assert f.methods({}) == {}
        assert f.methods({"Smithing": {}}) == {}


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


class TestTheBronzePreformCarriesNoBandOnPurpose:
    """**A decision that was reading as a gap.** Bronze is never an alloy's
    dearer half, so `methods` emits nothing on its challenge - and the
    activity is fully covered, because bronze's one good alloy is filed on the
    *iron* preform. Moving it would attach bronze's cheap bars to an alloy
    that is 23 parts adamant."""

    _ALL: dict[str, dict[str, object]] = {
        "Smithing": {task: {} for task in f.PREFORMS.values()}
    }

    def test_no_band_lands_on_it(self) -> None:
        knobs = {band.knob for band in f.methods(self._ALL)["Smithing"]}
        assert f"training/{f.PREFORMS['bronze']}/Smithing" not in knobs

    def test_so_it_says_so_rather_than_reading_unpriced(self) -> None:
        why = f.refused(self._ALL)
        assert set(why) == {f.PREFORMS["bronze"]}
        assert "iron preform" in why[f.PREFORMS["bronze"]]

    def test_bronzes_own_alloy_is_on_the_iron_challenge(self) -> None:
        bands = f.methods(self._ALL)["Smithing"]
        first = min(bands, key=lambda band: band.level or 0)
        assert first.method == "Giants' Foundry (bronze/iron)"
        assert first.knob == f"training/{f.PREFORMS['iron']}/Smithing"

    def test_a_map_with_only_bronze_gets_the_ordinary_unpriced(self) -> None:
        """One preform needs 28 bars of *two* metals, so there the activity
        really is out of reach rather than filed elsewhere - and a refusal
        pointing at the iron preform would be a lie."""
        only: dict[str, dict[str, object]] = {
            "Smithing": {f.PREFORMS["bronze"]: {}}
        }
        assert f.methods(only) == {}
        assert f.refused(only) == {}
