"""Pest Control barricades: an upper bound, and which of its terms is a guess."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import barricade
from chunksim.costing.gathering import GUESS
from chunksim.model.chunkinfo import ChunkInfo

_VALID: dict[str, dict[str, object]] = {"Crafting": {barricade.TASK: {}}}


class TestThePublishedTerms:
    def test_five_experience_a_repair(self) -> None:
        """`Pest Control/Strategies` states it; the barricade's own page says
        only "some Crafting experience"."""
        assert barricade.XP_PER_REPAIR == 5.0

    def test_two_minutes_is_the_wikis_own_idealisation(self) -> None:
        """Not this module's: the commendation table says its estimates "are
        under ideal conditions ... and assume 2 minutes per game", and adds
        that reality is nearer three times that."""
        assert barricade.GAME_MINUTES == 2.0
        assert barricade.games_per_hour() == 30.0


class TestTheGuessedTerm:
    def test_the_floor_is_a_threshold_the_game_dropped(self) -> None:
        """**Evidence, not a round number.** Ten a game was the commendation
        requirement until players complained it was too easy to meet and idle
        afterwards, which is the wiki's own account of why it went."""
        assert barricade.MINIMUM_REPAIRS_PER_GAME == 10.0

    def test_forty_is_four_times_that_floor(self) -> None:
        """Chosen to be plainly optimistic rather than plausible."""
        assert barricade.REPAIRS_PER_GAME == 4 * barricade.MINIMUM_REPAIRS_PER_GAME

    def test_the_answer_is_six_thousand(self) -> None:
        assert barricade.xp_per_hour() == 6_000.0


class TestTheWholeRangeLoses:
    def test_even_the_ceiling_is_six_times_under_the_slowest_band(self) -> None:
        """**`costing/toymouse.py`'s argument, and the reason a guess closes
        this row.** The slowest Crafting band on either cached map is 37,462;
        nothing in the plausible range can decide a band, so the invented term
        cannot change an answer."""
        assert barricade.xp_per_hour() * 6 < 37_462

    def test_the_floor_is_lower_still(self) -> None:
        floor = barricade.xp_per_hour(barricade.MINIMUM_REPAIRS_PER_GAME)
        assert floor == 1_500.0
        assert floor < barricade.xp_per_hour()


class TestTheBand:
    def test_one_band_at_level_one(self) -> None:
        (band,) = barricade.methods(_VALID)["Crafting"]
        assert band.level == barricade.LEVEL == 1
        assert band.match == GUESS
        assert band.knob == f"training/{barricade.TASK}/Crafting"

    def test_nothing_without_the_challenge(self) -> None:
        assert barricade.methods({}) == {}
        assert barricade.methods({"Crafting": {}}) == {}


@pytest.mark.real_export
class TestUpstreamStillCarriesIt:
    def test_the_challenge_is_where_this_expects(self, real_export: ChunkInfo) -> None:
        challenge = (real_export.challenges.get("Crafting") or {}).get(barricade.TASK)
        assert isinstance(challenge, dict), "upstream lost the barricade challenge"
        assert challenge.get("Primary") is True
        assert challenge.get("Level") == barricade.LEVEL


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "barricade.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = (
            pathlib.Path(barricade.__file__)
            .with_name("__init__.py")
            .read_text(encoding="utf-8")
        )
        assert "`barricade.py`" in listing
