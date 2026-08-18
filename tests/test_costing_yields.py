"""A gathering action's own weight tiers, which are yields rather than drops."""

from __future__ import annotations

from typing import Any

from chunksim.costing import yields
from chunksim.costing.gathering import GATHERING_MATCH


class _Info:
    def __init__(self, challenges: dict[str, Any], skill_items: dict[str, Any]) -> None:
        self.challenges = challenges
        self.data = {"skillItems": skill_items}


def _granite() -> _Info:
    return _Info(
        {"Mining": {"Mine ~|granite|~": {"Output": "Granite", "Primary": True}}},
        {"Mining": {"Granite": {
            "Granite (500g)": {"1": "20.7/100"},
            "Granite (2kg)": {"1": "22.15/100"},
            "Granite (5kg)": {"1": "25.39/100"},
        }}},
    )


_SHARES = {"Granite (500g)": 0.207, "Granite (2kg)": 0.2215, "Granite (5kg)": 0.2539}


def _costs(match: str = GATHERING_MATCH, seconds: float = 7.1) -> dict[str, float]:
    return yields.costs(
        _granite(),
        {"Mine ~|granite|~": seconds},
        lambda task, skill: match,
        lambda activity, member: _SHARES.get(member, 0.0),
    )


def test_a_weight_tier_costs_the_action_over_its_share() -> None:
    """One mine in four is a 5kg block, so a 5kg block is four mines."""
    found = _costs()

    assert found["Granite (5kg)"] == 7.1 / 0.2539
    assert set(found) == set(_SHARES)


def test_a_pace_that_is_not_the_model_s_own_is_refused() -> None:
    """`confirmed` and `computed` are what `barbarian.py`, `gotr.py` and every
    minigame model use - trusting those was a reverted attempt."""
    assert _costs(match="confirmed") == {}
    assert _costs(match="default") == {}


def test_a_find_is_below_the_boundary_and_left_alone() -> None:
    """Digsite soil finds run 5-8% and the big fish 0.02-0.1%; nothing at all
    sits between 8.33% and 19.92%, which is where `ORDINARY_SHARE` is."""
    found = yields.costs(
        _granite(),
        {"Mine ~|granite|~": 7.1},
        lambda task, skill: GATHERING_MATCH,
        lambda activity, member: 0.05,
    )

    assert found == {}
    assert 0.0833 < yields.ORDINARY_SHARE < 0.1992


def test_an_always_member_needs_no_help() -> None:
    """The certainty gate lets it through already."""
    found = yields.costs(
        _granite(),
        {"Mine ~|granite|~": 7.1},
        lambda task, skill: GATHERING_MATCH,
        lambda activity, member: 1.0,
    )

    assert found == {}


def test_an_untimed_action_yields_nothing() -> None:
    """No pace is no cost - the whole point is that the action's own duration
    is already known."""
    found = yields.costs(
        _granite(), {}, lambda task, skill: GATHERING_MATCH,
        lambda activity, member: 0.25,
    )

    assert found == {}


def test_the_cheapest_wins_a_tie() -> None:
    """One item can be a yield of two actions, and a lower cost is a better
    route to it - the `min` `_item_hours` takes over routes."""
    info = _Info(
        {"Mining": {
            "Mine ~|a|~": {"Output": "A"},
            "Mine ~|b|~": {"Output": "B"},
        }},
        {"Mining": {
            "A": {"Rock": {"1": "25/100"}},
            "B": {"Rock": {"1": "25/100"}},
        }},
    )

    found = yields.costs(
        info,
        {"Mine ~|a|~": 40.0, "Mine ~|b|~": 10.0},
        lambda task, skill: GATHERING_MATCH,
        lambda activity, member: 0.25,
    )

    assert found["Rock"] == 40.0
