"""The Agility Pyramid: a level-1 challenge that was claiming a level-30 rate."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import pyramid as py


class TestThePublishedBands:
    @pytest.mark.parametrize(
        "level,rate",
        [(55, 25_000.0), (60, 25_000.0), (67, 33_000.0), (75, 42_100.0),
         (88, 44_700.0), (99, 44_700.0)],
    )
    def test_a_band_is_the_pages(self, level: int, rate: float) -> None:
        assert py.rate_at(level) == rate

    def test_it_takes_the_low_end_of_each_range(self) -> None:
        # "Level 55-60: 25,000-30,000" and "67-70: 33,000-37,000" - the page
        # hedges them ("depending on luck with failures"), so this takes the
        # conservative end.
        assert py.rate_at(55) == 25_000.0
        assert py.rate_at(67) == 33_000.0

    def test_it_caps_where_the_page_says(self) -> None:
        # "the maximum experience rates scale with the player's Agility level,
        # capping at level 88".
        assert py.rate_at(88) == py.rate_at(99)


class TestWhatItDeclinesToSay:
    """**The wiki's limit, carried rather than papered over.**"""

    def test_nothing_below_the_rated_band(self) -> None:
        # "Due to not knowing the exact fail rates of obstacles for other
        # Agility levels, it is hard to predict the experience rates for
        # players with lower Agility levels."
        assert py.RATED_FROM == 55
        assert py.rate_at(54) == 0.0
        assert py.rate_at(30) == 0.0

    def test_the_gap_between_opening_and_rating_is_deliberate(self) -> None:
        # The course opens at 30 and the table starts at 55; the courses cover
        # the twenty-five levels between, and inventing a curve for them would
        # be the opposite of what the rest of this directory does.
        assert py.OPENS_AT == 30
        assert py.RATED_FROM > py.OPENS_AT


class TestTheJoinItReplaces:
    """**A money-making rate on a challenge that opens at level 1.**"""

    SCRAPED = 34_380.0

    def test_all_three_challenges_are_named(self) -> None:
        # Including the two climbing-rock ones, which are how you reach the
        # course rather than a method of their own - and one of which the
        # export opens at level 1.
        assert len(py.TASKS) == 3
        assert any("upper climbing rocks" in t for t in py.TASKS)

    def test_no_band_opens_before_the_wikis_table(self) -> None:
        # The defect: the scraped figure was winning from level 1 to 50 for a
        # pyramid needing 30, against courses paying 10,000.
        bands = py.methods({"Agility": {t: {} for t in py.TASKS}})["Agility"]
        assert min(b.level for b in bands if b.level is not None) == py.RATED_FROM

    def test_the_flat_figure_sat_between_the_ends(self) -> None:
        assert py.rate_at(55) < self.SCRAPED < py.rate_at(88)


class TestReachability:
    _ALL: dict[str, dict[str, object]] = {
        "Agility": {task: {} for task in py.TASKS}
    }

    def test_each_reachable_challenge_gets_the_bands(self) -> None:
        bands = py.methods(self._ALL)["Agility"]
        assert len(bands) == len(py.TASKS) * len(py.EXPERIENCE_PER_HOUR)

    def test_one_challenge_alone_still_works(self) -> None:
        one: dict[str, dict[str, object]] = {"Agility": {py.TASKS[0]: {}}}
        assert len(py.methods(one)["Agility"]) == len(py.EXPERIENCE_PER_HOUR)

    def test_nothing_when_unreachable(self) -> None:
        assert py.methods({}) == {}
        assert py.methods({"Agility": {}}) == {}

    def test_every_band_names_its_own_task(self) -> None:
        knobs = {b.knob for b in py.methods(self._ALL)["Agility"]}
        assert knobs == {f"training/{t}/Agility" for t in py.TASKS}


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "pyramid.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(py.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`pyramid.py`" in listing
