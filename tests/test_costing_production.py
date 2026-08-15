"""`costing/production.py`: the join, and what it refuses.

The join is the whole module, so the tests are about which name reaches a
calculator row - and in particular about the two shapes that had already cost
something: a task with a trailing qualifier, and a skill whose rows describe
what it produces rather than what it consumes.
"""

from __future__ import annotations

from typing import Any

from chunksim.costing import production
from chunksim.costing.gathering import Tables
from chunksim.costing.heuristics import MaterialCost
from chunksim.model.chunkinfo import ChunkInfo


TABLES = Tables(
    curves={"willow tree": (("Bronze", 16.0, 50.0, 1),)},
    experience={
        "Firemaking": {
            "magic logs": (303.8, "Regular"),
            "oak logs": (60.0, "Regular"),
        },
        "Crafting": {"ruby amulet": (85.0, "Jewellery")},
        "Smithing": {"iron bar": (12.5, "Smelting")},
        "Woodcutting": {"willow logs": (67.5, "Regular")},
    },
    materials={
        "Firemaking": {
            "magic logs": (("Magic logs", 1.0),),
            "oak logs": (("Oak logs", 1.0),),
        },
        "Crafting": {"ruby amulet": (("Gold bar", 1.0), ("Ruby", 1.0))},
        "Smithing": {"iron bar": (("Iron ore", 1.0),)},
        "Woodcutting": {"willow logs": ()},
    },
)

CHALLENGES: dict[str, dict[str, dict[str, Any]]] = {
    "Firemaking": {
        "Burn ~|magic logs|~": {
            "Primary": True,
            "Items": ["Magic logs", "Tinderbox"],
            "Output": "Ashes",
            "Output Object": "Player fire",
        },
        "Burn ~|magic logs|~ at a fire": {"Primary": True, "Items": ["Magic logs*"]},
        "Burn ~|oak logs|~": {"Primary": True, "Output": "Ashes"},
        "Light a beacon": {"Primary": True},
        "Burn ~|magic logs|~ twice": {"Primary": False},
    },
    "Crafting": {
        "Craft a ~|ruby amulet|~": {"Primary": True, "Output": "Ruby amulet"},
    },
    "Woodcutting": {
        "Chop ~|willow logs|~": {"Primary": True, "Output": "Willow logs"},
    },
}

VALID: dict[str, dict[str, bool]] = {
    "Firemaking": {name: True for name in CHALLENGES["Firemaking"]},
    "Crafting": {"Craft a ~|ruby amulet|~": True},
    "Woodcutting": {"Chop ~|willow logs|~": True},
}


def _costs(skills: frozenset[str] = production.PRODUCTION_SKILLS) -> dict[str, MaterialCost]:
    return production.calculator_costs(
        ChunkInfo({"challenges": CHALLENGES}), VALID, TABLES, skills
    )


class TestJoinKeys:
    def test_the_span_is_the_first_key(self) -> None:
        keys = production.join_keys({"Output": "Ashes"}, "Burn ~|magic logs|~")
        assert keys[0] == "magic logs"

    def test_a_trailing_qualifier_does_not_reach_the_key(self) -> None:
        # The miss that mattered: stripping a leading verb left `magic logs at
        # a fire`, so this task joined nothing and, charged nothing, outranked
        # the twin that was charged.
        assert production.join_keys({}, "Burn ~|magic logs|~ at a fire")[0] == "magic logs"

    def test_the_output_follows_for_a_skill_that_names_its_product(self) -> None:
        keys = production.join_keys(
            {"Output": "Ruby amulet", "Output Object": "Furnace"},
            "Craft a ~|ruby amulet|~",
        )
        assert keys == ("ruby amulet", "Ruby amulet", "Furnace")

    def test_a_task_with_no_span_still_offers_its_output(self) -> None:
        assert production.join_keys({"Output": "Ashes"}, "Light a beacon") == ("Ashes",)

    def test_the_first_span_wins_when_a_name_carries_two(self) -> None:
        keys = production.join_keys({}, "Fletch ~|logs|~ into ~|javelin shafts|~")
        assert keys == ("logs",)


class TestCalculatorCosts:
    def test_charges_a_burn_for_the_log_it_consumes(self) -> None:
        cost = _costs()["Burn ~|magic logs|~"]
        assert cost.experience == 303.8
        assert cost.items == {"Magic logs": 1.0}

    def test_both_twins_are_charged_so_neither_can_outrank_the_other(self) -> None:
        costs = _costs()
        assert "Burn ~|magic logs|~" in costs
        assert "Burn ~|magic logs|~ at a fire" in costs

    def test_a_tool_in_items_is_not_charged(self) -> None:
        # `Tinderbox` is in the challenge's `Items` and is not a material: the
        # quantities come from the calculator row, which names only the log.
        assert "Tinderbox" not in _costs()["Burn ~|magic logs|~"].items

    def test_a_non_primary_method_is_not_costed(self) -> None:
        assert "Burn ~|magic logs|~ twice" not in _costs()

    def test_a_method_that_joins_nothing_is_left_alone(self) -> None:
        assert "Light a beacon" not in _costs()

    def test_a_gathering_skill_is_outside_the_bucket(self) -> None:
        # Woodcutting consumes nothing and `costing/gathering.py` prices it;
        # its row is present in the tables and must still not be charged.
        assert "Chop ~|willow logs|~" not in _costs()

    def test_a_row_consuming_nothing_is_skipped_rather_than_recorded_free(self) -> None:
        widened = production.PRODUCTION_SKILLS | {"Woodcutting"}
        assert "Chop ~|willow logs|~" not in _costs(widened)

    def test_widening_the_bucket_is_one_edit(self) -> None:
        # The shape a per-skill quirk takes everywhere in `costing/`: a set,
        # not a branch.
        assert "Smithing" in production.PRODUCTION_SKILLS
        assert not production.PRODUCTION_SKILLS & {
            "Fishing", "Mining", "Woodcutting", "Hunter", "Thieving", "Prayer",
            "Magic", "Farming",
        }

    def test_empty_tables_price_nothing(self) -> None:
        assert (
            production.calculator_costs(
                ChunkInfo({"challenges": CHALLENGES}), VALID, Tables()
            )
            == {}
        )
