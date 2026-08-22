"""The Hosidius Mess: a Cooking minigame that charges nothing for its inputs."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import mess
from chunksim.model.chunkinfo import ChunkInfo


def _valid() -> dict[str, dict[str, object]]:
    return {"Cooking": {food.task: {} for food in mess.FOODS}}


class TestTheTwoPublishedColumnsCheckEachOther:
    """**The turn-in figure and the per-inventory figure are independent**, and
    they agree to within what the intermediate cooking is worth: cooking the
    servery raw meat and cooking the uncooked pie pay Cooking too, and only
    the per-inventory figure carries them."""

    @pytest.mark.parametrize("food", mess.FOODS, ids=lambda f: f.name)
    def test_the_turn_in_total_is_just_under_the_inventory_total(
        self, food: mess.Food
    ) -> None:
        total = food.turn_in * food.per_inventory
        ratio = total / food.inventory_experience

        assert 0.95 < ratio < 1.0, food.name

    def test_the_page_gates_each_where_upstream_does(self) -> None:
        """"20 Cooking is required to cook servery meat pie, 25 for servery
        stew, and 65 for servery pineapple pizza"."""
        assert [food.level for food in mess.FOODS] == [20, 25, 65]

    def test_the_inventories_an_hour_are_a_believable_cadence(self) -> None:
        """A rate divided by what an inventory pays has to come out as
        something a player could do - about twenty a hour here, which is three
        minutes for fourteen pies including the cupboards and the world hop."""
        for food in mess.FOODS:
            assert 15.0 < food.inventories_per_hour < 45.0, food.name


class TestWhichFigureIsSpent:
    def test_the_low_end_of_the_realistic_band(self) -> None:
        """`costing/pyramid.py`'s rule for a range the page hedges -
        "depending on Cooking level and concentration levels"."""
        for food in mess.FOODS:
            assert food.xp_per_hour == food.realistic[0]
            assert food.realistic[0] < food.realistic[1]

    def test_the_perfect_figure_is_recorded_and_not_spent(self) -> None:
        """"With perfect clicks" is a claim about a human rather than a
        mechanic - `costing/sepulchre.py`'s "tick-perfect is not a rate"."""
        for food in mess.FOODS:
            assert food.perfect > food.realistic[1]
            assert food.xp_per_hour < food.perfect

    def test_the_stew_drop_trick_is_recorded_and_not_spent(self) -> None:
        stew = next(food for food in mess.FOODS if "stew" in food.name)

        assert mess.STEW_DROP_TRICK_PER_HOUR > stew.perfect
        assert stew.xp_per_hour < mess.STEW_DROP_TRICK_PER_HOUR

    def test_the_pizza_is_the_fast_one_and_opens_last(self) -> None:
        pizza = max(mess.FOODS, key=lambda food: food.xp_per_hour)

        assert pizza.name == "servery pineapple pizza"
        assert pizza.level == max(food.level for food in mess.FOODS)


class TestTheBands:
    def test_one_band_a_food_at_its_own_level(self) -> None:
        found = mess.methods(_valid())["Cooking"]

        assert len(found) == len(mess.FOODS)
        assert {band.level for band in found} == {20, 25, 65}

    def test_they_rise_with_the_level(self) -> None:
        """Which is what gives the activity a curve without banding inside a
        food, where the page cannot locate its own range."""
        found = sorted(mess.methods(_valid())["Cooking"], key=lambda b: b.level or 0)
        rates = [band.xp_per_hour for band in found]

        assert rates == sorted(rates)

    def test_nothing_when_unreachable(self) -> None:
        assert mess.methods({}) == {}
        assert mess.methods({"Cooking": {}}) == {}

    def test_one_food_alone_still_works(self) -> None:
        one: dict[str, dict[str, object]] = {"Cooking": {mess.FOODS[0].task: {}}}

        assert len(mess.methods(one)["Cooking"]) == 1

    def test_each_band_names_its_own_task(self) -> None:
        knobs = {band.knob for band in mess.methods(_valid())["Cooking"]}

        assert knobs == {f"training/{food.task}/Cooking" for food in mess.FOODS}


class TestNoMaterialCost:
    """**The whole reason this is worth modelling.** "The Mess is notable for
    offering Cooking training without any requirements to gather materials" -
    so nothing here may charge for a servery pie shell, which is also why the
    recipe layer could never price it: the shell has no route in the export."""

    def test_nothing_here_declares_a_material_cost(self) -> None:
        assert not hasattr(mess, "material_seconds_per_xp")

    @pytest.mark.real_export
    def test_upstream_lists_no_items_either(self, real_export: ChunkInfo) -> None:
        cooking = real_export.challenges["Cooking"]
        for food in mess.FOODS:
            entry = cooking.get(food.task)
            assert isinstance(entry, dict), food.task
            assert entry.get("Primary") is True, food.task
            assert entry.get("Level") == food.level, food.task
            assert not entry.get("Items"), food.task

    @pytest.mark.real_export
    def test_all_three_are_in_one_chunk(self, real_export: ChunkInfo) -> None:
        """One kitchen: a map holds the Mess or it does not."""
        cooking = real_export.challenges["Cooking"]
        chunks = {tuple(cooking[food.task].get("Chunks") or ()) for food in mess.FOODS}

        assert len(chunks) == 1


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "mess.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(mess.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`mess.py`" in listing
