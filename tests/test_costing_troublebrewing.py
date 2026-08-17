"""Trouble Brewing's Cooking, which is a woodcutting loop wearing a hat."""

from __future__ import annotations

import pytest

from chunksim.costing import troublebrewing as tb
from chunksim.costing.gathering import GUESS, Tables
from chunksim.model.chunkinfo import ChunkInfo

_TABLES = Tables(
    curves={
        "scrapey tree": (
            ("Bronze", 22.0, 74.0, 1, "confirmed"),
            ("Rune", 84.0, 263.0, 41, "confirmed"),
        )
    }
)
_INFO = ChunkInfo(
    {
        "codeItems": {"itemsPlus": {"Axe[+]": ["Bronze axe", "Rune axe"]}},
        "toolLevels": {"Axe[+]": {"Bronze axe": 1, "Rune axe": 41}},
        "challenges": {},
    }
)
_AXES = frozenset({"Bronze axe", "Rune axe"})
_VALID = {tb.SKILL: {tb.TASK: 1}}


def test_the_ceiling_is_one_log_every_four_ticks() -> None:
    """**40 minutes of play an hour and a chop attempt every 4 ticks** is at
    most 1,000 logs, and a bark pays 100 Cooking - so 100,000 an hour is what
    the mechanic allows before a second is spent fletching, hopping or walking
    to a hopper."""
    ceiling = (
        tb.GAMES_PER_HOUR * tb.GAME_MINUTES * 60.0
        / (tb.CHOP_TICKS * tb.TICK_SECONDS)
        * tb.BARK_EXPERIENCE
    )

    assert ceiling == pytest.approx(100_000.0)
    assert tb.xp_per_hour(_TABLES, _INFO, 99, _AXES) < ceiling


def test_a_published_figure_above_the_ceiling_is_not_carried() -> None:
    """Theoatrix's 1-99 Cooking guide puts Trouble Brewing at "around 200k XP
    per hour". That needs *two* logs every four ticks, so it is outside what
    the mechanic allows rather than a near miss to split the difference with.
    This is the check that says so."""
    assert tb.xp_per_hour(_TABLES, _INFO, 99, _AXES) < 200_000.0 / 2


def test_the_axe_and_the_level_both_bind() -> None:
    """The same two gates `gathering.best_tool` applies everywhere: a rune axe
    in a reachable chunk is not a rune axe at level 30."""
    assert tb.chop_chance(_TABLES, _INFO, 40, _AXES) < tb.chop_chance(
        _TABLES, _INFO, 41, _AXES
    )


def test_a_map_holding_no_axe_holds_no_woodcutting() -> None:
    assert tb.chop_chance(_TABLES, _INFO, 99, frozenset()) == 0.0
    assert tb.methods(_TABLES, _INFO, _VALID, frozenset(), 99) == {}


def test_it_is_one_flat_band_on_the_woodcutting_level() -> None:
    """Nothing about this moves with Cooking - the deposit pays 100 whoever
    does it - so there is no curve to band. What moves it is the chop chance,
    which is a fact about Woodcutting and the axe."""
    (band,) = tb.methods(_TABLES, _INFO, _VALID, _AXES, 99)[tb.SKILL]

    assert band.level == tb.OPENS_AT
    assert band.xp_per_hour == tb.xp_per_hour(_TABLES, _INFO, 99, _AXES)
    assert band.xp_per_hour > tb.methods(_TABLES, _INFO, _VALID, _AXES, 1)[tb.SKILL][0].xp_per_hour


def test_a_ceiling_quoted_as_a_rate_is_still_a_guess() -> None:
    """Every input is published and the result is still `GUESS`, because the
    fletch and the deposit are charged nothing and Trouble Brewing is a team
    game a player chopping for twenty minutes is playing badly."""
    (band,) = tb.methods(_TABLES, _INFO, _VALID, _AXES, 99)[tb.SKILL]

    assert band.match == GUESS


def test_no_tables_price_nothing() -> None:
    assert tb.methods(None, _INFO, _VALID, _AXES, 99) == {}


def test_a_map_that_cannot_reach_it_gets_nothing() -> None:
    assert tb.methods(_TABLES, _INFO, {"Cooking": {}}, _AXES, 99) == {}
