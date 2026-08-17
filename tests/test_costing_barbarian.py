"""Barbarian fishing's ancillary Strength and Agility."""

from __future__ import annotations

import pytest

from chunksim.costing import barbarian
from chunksim.costing.gathering import load_tables, success_chance
from chunksim.store import cache


@pytest.mark.real_cache
def test_the_ancillary_rate_is_a_fixed_fraction_of_the_fishing_one() -> None:
    """**The check is a ratio, not a level.** `Barbarian Fishing` publishes an
    AFK column of Fishing experience beside a Strength/Agility column, and
    their ratio runs 0.090 to 0.092 from level 48 to 99. This computes 0.089 at
    every level.

    The absolute figures differ - this project's Fishing model is more
    conservative than the guide's, 38,224 against 48,000 at level 70 - and that
    disagreement is inherited rather than patched here. What this module claims
    is only the fraction, and both sources give the same one.
    """
    tables = load_tables(cache.read_gathering())
    paid = tables.experience.get("Fishing") or {}
    if not paid.get("leaping trout"):
        pytest.skip("gathering tables carry no barbarian fishing")

    for level in (48, 58, 70, 80, 90, 99):
        survive, fishing = 1.0, 0.0
        for name in barbarian.CASCADE:
            curves = tables.curves.get(name.lower())
            figure = paid.get(name.lower())
            assert curves and figure, name
            chance = success_chance(level, curves[0][1], curves[0][2])
            fishing += survive * chance * figure[0]
            survive *= 1.0 - chance
        ancillary = barbarian._expected(tables, level)

        assert ancillary / fishing == pytest.approx(0.089, abs=0.002), level


def test_the_cascade_matches_the_one_the_fishing_model_rolls() -> None:
    """**Same rolls, different experience column.** If these two orders ever
    diverge the ancillary rate stops describing the action the Fishing rate
    prices, and nothing else would notice."""
    from chunksim.costing.gathering import PROFILES

    fishing = PROFILES["Fishing"].cascades
    assert fishing, "Fishing still cascades"
    for order in fishing.values():
        assert tuple(order) == barbarian.CASCADE


def test_all_three_challenges_share_one_rate() -> None:
    """They are the same action; which fish a task names does not change what
    an hour of it pays - the argument `aerial.py` makes for its four."""
    tables = load_tables(cache.read_gathering())
    valid: dict[str, dict[str, dict[str, object]]] = {
        skill: {f"Catch a ~|{fish.lower()}|~": {} for fish in barbarian.CASCADE}
        for skill in barbarian.ANCILLARY_SKILLS
    }

    found = barbarian.methods(tables, valid)
    if not found:
        pytest.skip("gathering tables carry no barbarian fishing")

    assert len(found) == 3, "one entry per fish"
    per_skill = {
        skill: {
            rate.xp_per_hour
            for rates in found.values()
            for rate in rates
            if rate.skill == skill and rate.level == 99
        }
        for skill in barbarian.ANCILLARY_SKILLS
    }
    for skill, values in per_skill.items():
        assert len(values) == 1, f"{skill} disagrees across the three fish"
    # Strength and Agility pay identically per catch.
    assert per_skill["Strength"] == per_skill["Agility"]


def test_fishing_is_not_priced_here() -> None:
    """The node walk already owns it, and two rates on one task is a defect
    rather than a richer answer."""
    assert "Fishing" not in barbarian.ANCILLARY_SKILLS
