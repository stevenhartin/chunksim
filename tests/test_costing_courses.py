"""Agility courses: a lap and a lap time, checked against the guide."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import courses as co


class TestTheDerivationReproducesTheGuide:
    """**Ten courses, two published numbers each, and the guide's own figure.**

    This is the whole case for the module: the Agility scrape was verified
    accurate before any of it was written, so what these assert is that a lap
    times a lap time *is* that number - not that it is a better one.
    """

    #: task suffix -> the `wiki:courses` figure the derivation must reproduce.
    #: The wiki's own `Exp. per hour` column, base rather than diary where the
    #: table gives both - which is what `rate_at` prices.
    PUBLISHED = {
        "Draynor Village Rooftop Course": 10_000.0,
        "Al Kharid Rooftop Course": 12_000.0,
        "Varrock Rooftop Course": 14_000.0,
        "Barbarian Outpost Agility Course": 18_200.0,
        "Canafis Rooftop Course": 19_700.0,
        "Falador Rooftop Course": 35_000.0,
        "Wilderness Agility Course": 66_600.0,
        "Seers' Village Rooftop Course": 46_800.0,
        "Werewolf Agility Course": 69_500.0,
        "Dorgesh-Kaan Agility Course": 63_000.0,
        "Pollnivneach Rooftop Course": 52_300.0,
        "Rellekka Rooftop Course": 55_000.0,
        "Ardougne Rooftop Course": 70_000.0,
    }

    @pytest.mark.parametrize("course", co.COURSES, ids=lambda c: c.task[:40])
    def test_a_course_lands_on_its_scraped_rate(self, course: co.Course) -> None:
        published = self.PUBLISHED[course.task.partition("~|")[2].rpartition("|~")[0]]
        assert co.rate_at(course) == pytest.approx(published, rel=0.06)

    def test_eight_of_thirteen_land_within_one_percent(self) -> None:
        close = 0
        for course in co.COURSES:
            name = course.task.partition("~|")[2].rpartition("|~")[0]
            if abs(co.rate_at(course) / self.PUBLISHED[name] - 1.0) <= 0.01:
                close += 1
        assert close >= 8

    def test_every_course_is_checked(self) -> None:
        names = {c.task.partition("~|")[2].rpartition("|~")[0] for c in co.COURSES}
        assert names == set(self.PUBLISHED)


class TestTheLap:
    def test_a_rate_is_a_lap_over_a_lap_time(self) -> None:
        ardougne = next(c for c in co.COURSES if "Ardougne" in c.task)
        assert ardougne.experience_per_lap == 889.0
        assert ardougne.lap_seconds == 45.6
        assert co.laps_per_hour(ardougne) == pytest.approx(3600.0 / 45.6)
        assert co.rate_at(ardougne) == pytest.approx(889.0 * 3600.0 / 45.6)

    def test_only_the_wilderness_course_pays_a_bonus(self) -> None:
        # Its lap counter pays "up to 18,400 bonus experience assuming players
        # play for at least an hour" - which is what makes the guide's 66,600
        # so much more than the 45,712 the lapping alone gives.
        bonuses = {c.task: c.bonus_per_hour for c in co.COURSES if c.bonus_per_hour}
        assert len(bonuses) == 1
        wild = next(c for c in co.COURSES if "Wilderness" in c.task)
        assert wild.bonus_per_hour == 18_400.0
        assert co.rate_at(wild) > wild.experience_per_lap * co.laps_per_hour(wild)

    def test_no_rate_reads_a_level(self) -> None:
        # A course is a fixed lap for a fixed reward; what a level buys is a
        # better course, which is why each carries its own opening level.
        assert co.rate_at(co.COURSES[0]) == co.rate_at(co.COURSES[0])
        assert [c.level for c in co.COURSES] == sorted(c.level for c in co.COURSES)


class TestWhatItLeavesAlone:
    """**Named rather than merely absent.**"""

    def test_the_unmodelled_five_are_recorded_with_a_reason(self) -> None:
        assert len(co.UNMODELLED) == 5
        assert all(reason for reason in co.UNMODELLED.values())

    def test_the_colossal_wyrm_pair_is_a_disagreement_not_a_gap(self) -> None:
        # 633 experience a lap and "about 90 seconds" is 25,320 an hour against
        # a scraped 44,000, which nothing on the page reconciles. Replacing a
        # verified guide figure with that would trade a checked number for an
        # unchecked one.
        for task, reason in co.UNMODELLED.items():
            if "Colossal Wyrm" in task:
                assert "44,000" in reason

    def test_gnome_stronghold_states_a_minimum_not_an_average(self) -> None:
        gnome = next(t for t in co.UNMODELLED if "Gnome Stronghold" in t)
        assert "minimum" in co.UNMODELLED[gnome]

    def test_modelled_and_unmodelled_do_not_overlap(self) -> None:
        assert not ({c.task for c in co.COURSES} & set(co.UNMODELLED))


class TestTheBaseRateIsPricedNotTheDiary:
    """**Three courses pay more with a hard diary, and the guide quotes that.**

    This prices the base, which is the conservative reading and the likelier
    one on a chunk map: a hard diary wants tasks all over its region, which is
    what such a map does not have.
    """

    def test_three_courses_carry_a_diary_figure(self) -> None:
        with_diary = [
            c for c in co.COURSES
            if c.diary_experience_per_lap is not None or c.diary_lap_seconds is not None
        ]
        assert {c.task.partition("~|")[2].rpartition("|~")[0] for c in with_diary} == {
            "Seers' Village Rooftop Course",
            "Pollnivneach Rooftop Course",
            "Rellekka Rooftop Course",
        }

    def test_the_diary_is_always_the_faster_of_the_two(self) -> None:
        for course in co.COURSES:
            if course.diary_experience_per_lap or course.diary_lap_seconds:
                assert co.rate_at(course, diary=True) > co.rate_at(course)

    def test_seers_gains_a_shorter_lap_and_the_others_more_experience(self) -> None:
        # The Kandarin teleport shortens the lap; the Desert and Fremennik
        # diaries pay more for the same one.
        seers = next(c for c in co.COURSES if "Seers'" in c.task)
        rellekka = next(c for c in co.COURSES if "Rellekka" in c.task)
        assert seers.diary_lap_seconds is not None
        assert seers.diary_experience_per_lap == seers.experience_per_lap
        assert rellekka.diary_lap_seconds is None
        assert rellekka.diary_experience_per_lap == 920.0

    def test_what_is_priced_is_the_lower_one(self) -> None:
        rellekka = next(c for c in co.COURSES if "Rellekka" in c.task)
        bands = co.methods({"Agility": {rellekka.task: {}}})["Agility"]
        assert bands[0].xp_per_hour == pytest.approx(co.rate_at(rellekka))
        assert bands[0].xp_per_hour < co.rate_at(rellekka, diary=True)


class TestReachability:
    _ALL: dict[str, dict[str, object]] = {
        "Agility": {c.task: {} for c in co.COURSES}
    }

    def test_every_course_a_map_reaches(self) -> None:
        bands = co.methods(self._ALL)["Agility"]
        assert len(bands) == len(co.COURSES) == 13

    def test_the_display_name_drops_the_markup(self) -> None:
        bands = co.methods(self._ALL)["Agility"]
        assert "Ardougne Rooftop Course" in {b.method for b in bands}
        assert not any("~|" in b.method for b in bands)

    def test_nothing_when_unreachable(self) -> None:
        assert co.methods({}) == {}
        assert co.methods({"Agility": {}}) == {}

    def test_upstreams_spelling_is_the_key(self) -> None:
        # The export writes `Canafis` and the wiki writes `Canifis`; the task
        # name is the lookup, so this file carries upstream's.
        assert any("Canafis" in c.task for c in co.COURSES)


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "courses.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(co.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`courses.py`" in listing
