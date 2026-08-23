"""Fixing a Dorgesh-Kaan lamp: 500 in two skills, and the orb is the cost."""

from __future__ import annotations

import pathlib
from typing import Any

import pytest

from chunksim.costing import lightorb
from chunksim.costing.gathering import GUESS
from chunksim.model.chunkinfo import ChunkInfo

_VALID: dict[str, dict[str, object]] = {
    "Crafting": {lightorb.TASK: {}},
    "Firemaking": {lightorb.TASK: {}},
}


def _orb(seconds: float | None) -> Any:
    def priced(item: str, quantity: float) -> float | None:
        assert item == lightorb.ORB
        return seconds

    return priced


class TestThePublishedHalf:
    def test_five_hundred_in_each_skill_at_fifty_two(self) -> None:
        """Stated twice on `Light orb` - in prose and in its `{{Firemaking
        info}}`, which names the action and carries both figures."""
        assert lightorb.XP_PER_LAMP == 500.0
        assert lightorb.LEVEL == 52
        assert lightorb.SKILLS == ("Crafting", "Firemaking")

    def test_both_skills_get_the_same_rate(self) -> None:
        """Honest here where it would not be for `costing/swimming.py`: the
        same click pays 500 and 500, rather than buying different amounts."""
        found = lightorb.methods(_VALID, _orb(19.19))
        assert set(found) == {"Crafting", "Firemaking"}
        rates = {band.xp_per_hour for bands in found.values() for band in bands}
        assert len(rates) == 1


class TestTheOrbIsMostOfTheCycle:
    def test_the_orb_is_folded_into_the_rate(self) -> None:
        """`costing/crane.py`'s reason: upstream files one task name under both
        skills it pays, and `material_seconds_per_xp` is keyed by task alone."""
        assert lightorb.rate_with(19.19) == pytest.approx(90_950, rel=1e-3)

    def test_the_click_alone_is_not_a_rate(self) -> None:
        """Three million an hour on paper, which is what makes the orb the
        method rather than an adjustment to it."""
        assert lightorb.rate_with(0.0) == pytest.approx(3_000_000)

    def test_no_route_to_an_orb_is_no_rate(self) -> None:
        assert lightorb.methods(_VALID, _orb(None)) == {}
        assert lightorb.methods(_VALID, _orb(0.0)) == {}

    def test_it_is_a_ceiling(self) -> None:
        """The walk between lamps is uncharged - the wiki publishes a map of
        every location precisely because they are scattered - so the action is
        the game's one-tick floor."""
        assert lightorb.ACTION_TICKS == 1.0


class TestReachability:
    def test_only_the_skills_the_map_can_reach(self) -> None:
        one: dict[str, dict[str, object]] = {"Firemaking": {lightorb.TASK: {}}}
        assert set(lightorb.methods(one, _orb(19.19))) == {"Firemaking"}

    def test_nothing_without_the_challenge(self) -> None:
        assert lightorb.methods({}, _orb(19.19)) == {}

    def test_every_band_is_a_guess(self) -> None:
        found = lightorb.methods(_VALID, _orb(19.19))
        assert {b.match for bands in found.values() for b in bands} == {GUESS}


class TestItSupersedesTheWrongJoin:
    def test_the_task_is_named_for_dropping(self) -> None:
        """**Both stale maps are keyed by task alone**, so neither can be
        corrected per skill - `inputs` drops them by name instead."""
        assert lightorb.SUPERSEDED_TASKS == (lightorb.TASK,)

    def test_inputs_drops_both_maps_not_just_the_charge(self) -> None:
        """Dropping the credit is the half that matters: blowing an orb is
        glassblowing, so it pays Crafting, and a Firemaking climb credited
        with it read 169,656 against a true 90,950."""
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "per_xp.pop(stale, None)" in source
        assert "credited.pop(stale, None)" in source


@pytest.mark.real_export
class TestUpstreamStillCarriesIt:
    def test_the_challenge_is_filed_under_both_skills(
        self, real_export: ChunkInfo
    ) -> None:
        for skill, other in (("Crafting", "Firemaking"), ("Firemaking", "Crafting")):
            challenge = (real_export.challenges.get(skill) or {}).get(lightorb.TASK)
            assert isinstance(challenge, dict), f"upstream lost the {skill} half"
            assert challenge.get("Level") == lightorb.LEVEL
            assert challenge["Skills"][other] == lightorb.LEVEL
            assert lightorb.ORB in challenge["Items"]


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "lightorb.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = (
            pathlib.Path(lightorb.__file__)
            .with_name("__init__.py")
            .read_text(encoding="utf-8")
        )
        assert "`lightorb.py`" in listing
