"""`costing/forestry.py`: nine events, none of them chosen."""

from __future__ import annotations

from typing import Any

import pytest

from chunksim.costing import forestry
from chunksim.costing.gathering import Tables
from chunksim.model.chunkinfo import ChunkInfo

TABLES = Tables(
    forestry={
        "Woodcutting": {1: 2985.6, 50: 18400.0, 99: 33238.0},
        "Hunter": {1: 7.5, 50: 375.0, 99: 742.5},
    },
    forestry_events=9,
)
CHALLENGES: dict[str, dict[str, dict[str, Any]]] = {
    "Woodcutting": {
        "Gain xp in the Poacher ~|Forestry|~ event": {
            "Category": ["ForestryXp"], "Primary": True
        },
        "Chop ~|willow logs|~": {"Primary": True},
    },
    "Hunter": {
        "Gain xp in the Poacher ~|Forestry|~ event": {
            "Category": ["ForestryXp"], "Primary": True
        },
    },
    "Smithing": {
        "Make a ~|rune felling axe|~ (alt)": {"Category": ["ForestryXp"], "Primary": True},
    },
}
INFO = ChunkInfo({"challenges": CHALLENGES})
VALID = {skill: {task: True for task in tasks} for skill, tasks in CHALLENGES.items()}


class TestRate:
    def test_each_event_comes_up_a_ninth_of_the_time(self) -> None:
        # 30 an hour over nine events is 3.33 of each, so the sum over all
        # nine is scaled once rather than counted nine times.
        assert forestry.rate_at(TABLES, "Woodcutting", 99) == pytest.approx(
            33238.0 * forestry.EVENTS_PER_HOUR / 9
        )

    def test_a_skill_no_event_pays_earns_nothing(self) -> None:
        assert forestry.rate_at(TABLES, "Fishing", 99) == 0.0

    def test_no_events_prices_nothing(self) -> None:
        assert forestry.rate_at(Tables(forestry=TABLES.forestry), "Woodcutting", 99) == 0.0

    def test_it_climbs_with_level(self) -> None:
        assert forestry.rate_at(TABLES, "Woodcutting", 1) < forestry.rate_at(
            TABLES, "Woodcutting", 99
        )


class TestMethods:
    def test_every_skill_an_event_pays_gets_a_rate(self) -> None:
        assert set(forestry.methods(TABLES, INFO, VALID)) == {"Woodcutting", "Hunter"}

    def test_the_felling_axes_are_not_events(self) -> None:
        # Smithing shares the category and is a recipe, not an event.
        assert "Smithing" not in forestry.methods(TABLES, INFO, VALID)

    def test_the_method_is_named_for_the_activity(self) -> None:
        # A reader picking `Poacher` out of a tooltip would be picking an hour
        # of all nine.
        (found,) = {
            skill: methods
            for skill, methods in forestry.methods(TABLES, INFO, VALID).items()
            if skill == "Hunter"
        }.values()
        assert {method.method for method in found} == {"Forestry events"}

    def test_a_map_with_no_event_challenge_gets_nothing(self) -> None:
        assert forestry.methods(TABLES, INFO, {"Woodcutting": {}}) == {}

    def test_no_table_prices_nothing(self) -> None:
        assert forestry.methods(Tables(), INFO, VALID) == {}
