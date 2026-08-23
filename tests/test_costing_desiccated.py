"""Desiccated pages: the contribution cancels and the rate falls out."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import desiccated
from chunksim.costing.gathering import CONFIRMED
from chunksim.model.chunkinfo import ChunkInfo

_ALL: dict[str, dict[str, object]] = {
    "Runecraft": {task: {} for task in desiccated.TASKS}
}


class TestTheArithmetic:
    def test_three_published_numbers_and_nothing_else(self) -> None:
        """`10-19 Always` under `dropversion=Take pages` (the wiki takes its
        own mean, 14.5), `kph = 48` on both money-making guides, and 50
        experience a page stated on the item and on the plinth."""
        assert desiccated.PAGES_PER_KILL == 14.5
        assert desiccated.KILLS_PER_HOUR == 48.0
        assert desiccated.XP_PER_PAGE == 50.0
        assert desiccated.pages_per_hour() == 348.0
        assert desiccated.xp_per_hour() == 17_400.0

    def test_the_contribution_cancels(self) -> None:
        """**The reason this model never asks how many players there are.**
        Quantities scale linearly with damage dealt, so halving the
        contribution halves the pages and doubles the kills. A solo player at
        100% and the guides' duo at 50% land on the same figure."""
        duo = desiccated.KILLS_PER_HOUR * 0.5 * desiccated.PAGES_PER_KILL
        solo = (desiccated.KILLS_PER_HOUR * 0.5) * 1.0 * desiccated.PAGES_PER_KILL
        assert duo == solo == desiccated.pages_per_hour()

    def test_the_guides_own_factor_is_what_is_spent(self) -> None:
        """Not an assumption about how anybody plays: every `Output` on both
        guides carries `*0.5`, which is the duo the fight is built around."""
        assert desiccated.CONTRIBUTION == 0.5

    def test_it_opens_where_the_conversion_does(self) -> None:
        """50 Runecraft, boostable "No" - the item page, the plinth page and
        upstream's own `Level` all agree."""
        assert desiccated.LEVEL == 50
        bands = desiccated.methods(_ALL)["Runecraft"]
        assert {b.level for b in bands} == {50}


class TestOneRateThreeChallenges:
    def test_each_plinth_gets_the_same_bands(self) -> None:
        """The page is the same page; the plinth decides which one comes out,
        not how fast - `courses.Course.also`'s rule."""
        bands = desiccated.methods(_ALL)["Runecraft"]
        assert len(bands) == 3
        assert {b.xp_per_hour for b in bands} == {17_400.0}
        assert {b.knob for b in bands} == {
            f"training/{task}/Runecraft" for task in desiccated.TASKS
        }

    def test_only_the_plinths_the_map_holds(self) -> None:
        one = desiccated.methods(
            {"Runecraft": {"Craft a ~|soaked page|~ from a desiccated page": {}}}
        )
        assert len(one["Runecraft"]) == 1

    def test_nothing_without_a_plinth(self) -> None:
        """Upstream's challenge asks for the plinth *and* for `Desiccated
        page*`, so its absence is the statement that this map cannot do it -
        no level and no monster is compared here."""
        assert desiccated.methods({}) == {}
        assert desiccated.methods({"Runecraft": {}}) == {}


class TestNothingHereIsInvented:
    def test_every_band_is_confirmed(self) -> None:
        """A ceiling - the `Reinvigorate` cadence and the plinth trip are not
        charged, because nothing states either and a page is stackable - but
        a ceiling with no invented number in it."""
        bands = desiccated.methods(_ALL)["Runecraft"]
        assert {b.match for b in bands} == {CONFIRMED}


@pytest.mark.real_export
class TestUpstreamStillCarriesWhatThisNames:
    def test_the_three_conversions_exist_and_are_primary(
        self, real_export: ChunkInfo
    ) -> None:
        """**A key that matches nothing is silently inert.** These are the
        only three challenges this module can ever land on."""
        runecraft = real_export.challenges.get("Runecraft") or {}
        for task in desiccated.TASKS:
            challenge = runecraft.get(task)
            assert isinstance(challenge, dict), f"upstream lost {task}"
            assert challenge.get("Primary") is True
            assert challenge.get("Level") == desiccated.LEVEL

    def test_a_page_comes_only_from_the_titans(self, real_export: ChunkInfo) -> None:
        """The rate is the Royal Titans' kill rate, so a second source of
        desiccated pages would make it wrong rather than incomplete."""
        from chunksim.derive.search import build_world_index

        world = build_world_index(real_export)
        sources = world.item_sources.get("Desiccated page") or ()
        assert sources
        assert {source.name for source in sources} <= {
            "Eldric the Ice King",
            "Branda the Fire Queen",
            "Loot desiccated pages from the Royal Titans*",
        }


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "desiccated.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = (
            pathlib.Path(desiccated.__file__)
            .with_name("__init__.py")
            .read_text(encoding="utf-8")
        )
        assert "`desiccated.py`" in listing
