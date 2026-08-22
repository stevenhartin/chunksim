"""The two Chambers of Xeric methods the ordinary layers cannot reach."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import cox
from chunksim.model.chunkinfo import ChunkInfo


def _valid() -> dict[str, dict[str, object]]:
    return {
        "Farming": {herb.task: {} for herb in cox.HERBS},
        "Firemaking": {cox.KINDLING_TASK: {}},
    }


class TestTheHerbPatchesArePublishedEndToEnd:
    def test_the_mechanic_is_two_plots_and_thirty_seconds(self) -> None:
        """"There are two farming plots in each resource room ... herbs grow
        faster and are fully grown in 30 seconds"."""
        assert (cox.PLOTS, cox.GROW_SECONDS) == (2, 30.0)
        assert cox.cycles_per_hour() == 240.0

    @pytest.mark.parametrize(
        "name,level,plant,harvest",
        [("golpar", 27, 4.0, 10.0), ("buchu", 39, 6.0, 15.0), ("noxifer", 55, 12.0, 30.0)],
    )
    def test_each_plants_own_farming_info(
        self, name: str, level: int, plant: float, harvest: float
    ) -> None:
        herb = next(h for h in cox.HERBS if h.name == name)

        assert (herb.level, herb.plant_experience, herb.harvest_experience) == (
            level,
            plant,
            harvest,
        )

    def test_a_seed_pays_planting_and_picking(self) -> None:
        assert [herb.experience for herb in cox.HERBS] == [14.0, 21.0, 42.0]

    def test_the_rates_multiply_out(self) -> None:
        assert [round(cox.rate_for(herb)) for herb in cox.HERBS] == [3_360, 5_040, 10_080]

    def test_it_is_a_ceiling_in_two_stated_ways(self) -> None:
        """The four clicks a cycle costs are not added, and the seeds are not
        charged - both said in the module docstring rather than hidden."""
        source = pathlib.Path(cox.__file__).read_text(encoding="utf-8")

        assert "ceiling rather than a rate" in source
        assert "seeds are not\ncharged" in source

    def test_it_is_too_small_to_turn_a_climb(self) -> None:
        """Golpar is below the Sorceress's Garden's 8,500 and a quarter of
        Tithe Farm's opening band, so the ceiling costs nothing."""
        assert cox.rate_for(cox.HERBS[0]) < 8_500.0


class TestTheBands:
    def test_one_band_a_herb_at_its_own_level(self) -> None:
        found = cox.methods(_valid())["Farming"]

        assert len(found) == len(cox.HERBS)
        assert [band.level for band in found] == [27, 39, 55]

    def test_they_rise_with_the_level(self) -> None:
        rates = [band.xp_per_hour for band in cox.methods(_valid())["Farming"]]

        assert rates == sorted(rates)

    def test_nothing_when_unreachable(self) -> None:
        assert cox.methods({}) == {}
        assert cox.methods({"Farming": {}}) == {}

    def test_one_herb_alone_still_works(self) -> None:
        one: dict[str, dict[str, object]] = {"Farming": {cox.HERBS[0].task: {}}}

        assert len(cox.methods(one)["Farming"]) == 1

    def test_each_band_names_its_own_task(self) -> None:
        knobs = {band.knob for band in cox.methods(_valid())["Farming"]}

        assert knobs == {f"training/{herb.task}/Farming" for herb in cox.HERBS}


class TestTheBrazierIsRefusedRatherThanGuessed:
    """**48 experience a kindling is published and nothing times the burn.**
    That gap decides bands here, which is what separates it from
    `costing/toymouse.py`, whose whole plausible range loses to everything."""

    def test_the_payout_is_published_and_the_cadence_is_not(self) -> None:
        assert cox.KINDLING_EXPERIENCE == 48.0
        assert "nothing states how fast" in cox.KINDLING_REASON

    def test_it_is_named_with_its_reason(self) -> None:
        assert cox.refused(_valid()) == {cox.KINDLING_TASK: cox.KINDLING_REASON}

    def test_nothing_where_the_challenge_is_out_of_reach(self) -> None:
        assert cox.refused({}) == {}
        assert cox.refused({"Firemaking": {}}) == {}

    def test_a_six_figure_rate_is_what_a_guess_would_produce(self) -> None:
        """The chop is modelled at ~38,000 Woodcutting an hour, which is on
        the order of two thousand kindling - so 48 experience each is a
        six-figure Firemaking rate before any cadence is charged."""
        assert cox.KINDLING_EXPERIENCE * 2_000 > 90_000


class TestItIsWiredIn:
    def test_inputs_calls_both_halves(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "cox.methods(" in source
        assert "cox.refused(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(cox.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`cox.py`" in listing

    @pytest.mark.real_export
    def test_every_named_task_exists_and_upstream_tags_it_cox(
        self, real_export: ChunkInfo
    ) -> None:
        for skill, task in (
            *(("Farming", herb.task) for herb in cox.HERBS),
            ("Firemaking", cox.KINDLING_TASK),
        ):
            entry = real_export.challenges[skill].get(task)
            assert isinstance(entry, dict), task
            assert "CoX" in (entry.get("Category") or ()), task

    @pytest.mark.real_export
    def test_the_levels_are_upstreams_own(self, real_export: ChunkInfo) -> None:
        for herb in cox.HERBS:
            entry = real_export.challenges["Farming"][herb.task]
            assert entry.get("Level") == herb.level, herb.name
