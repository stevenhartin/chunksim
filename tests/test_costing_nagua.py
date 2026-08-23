"""Sulphurous essence: 12.5 experience a kill, and the kills are the map's."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import nagua
from chunksim.costing.gathering import CONFIRMED, INFERRED
from chunksim.costing.heuristics import Rate
from chunksim.model.chunkinfo import ChunkInfo

_VALID: dict[str, dict[str, object]] = {"Runecraft": {nagua.TASK: {"Level": 20}}}


def _measured(value: float) -> Rate:
    return Rate(value=value, source="dps", match="exact")


def _defaulted(value: float = 60.0) -> Rate:
    return Rate(value=value, source="default:slayer")


class TestThePublishedFiguresCheckEachOther:
    def test_fifty_and_twelve_and_a_half_are_one_essence_in_four_kills(self) -> None:
        """The page states a per-essence figure and a per-kill one in different
        sections; their ratio is the drop share written twice."""
        assert nagua.XP_PER_ESSENCE / nagua.XP_PER_KILL == 4.0

    def test_the_recovered_kill_rate_reproduces_the_published_band(self) -> None:
        """**Recovered, not stated** - `costing/strut.py`'s move. Dividing the
        page's own hourly band by 12.5 gives the kills an hour behind it, and
        multiplying back has to land on both ends."""
        low, high = nagua.PUBLISHED_XP_PER_HOUR
        assert nagua.PUBLISHED_KILLS_PER_HOUR == 200.0
        assert nagua.XP_PER_KILL * nagua.PUBLISHED_KILLS_PER_HOUR == low
        assert nagua.XP_PER_KILL * (high / nagua.XP_PER_KILL) == high

    def test_the_low_end_of_a_hedged_range_is_what_is_spent(self) -> None:
        """"Roughly 2,500 to 3,400" over "mid-game stats and ... moonlight
        potions" - `costing/pyramid.py`'s rule."""
        (band,) = nagua.methods(_VALID, lambda m: _defaulted())["Runecraft"]
        assert band.xp_per_hour == nagua.PUBLISHED_XP_PER_HOUR[0]


class TestTheKillRateIsTheWholeClock:
    def test_a_measured_rate_is_spent_and_reported_confirmed(self) -> None:
        (band,) = nagua.methods(_VALID, lambda m: _measured(240.0))["Runecraft"]
        assert band.xp_per_hour == 3_000.0
        assert band.match == CONFIRMED

    def test_a_bare_default_is_displaced_and_reported_inferred(self) -> None:
        """**A default is not a measurement.** `DEFAULT_KPH`'s 60 for a Slayer
        monster is 750 an hour against a page saying 2,500-3,400, so the page
        wins - and says so in the provenance, because a figure divided out of
        a published rate is this project computing rather than reading."""
        assert nagua.kills_for(_defaulted()) == (200.0, INFERRED)
        (band,) = nagua.methods(_VALID, lambda m: _defaulted())["Runecraft"]
        assert band.match == INFERRED

    def test_a_measured_rate_below_the_page_still_wins(self) -> None:
        """Not a maximum: a map whose gear really is worse than the page's
        mid-game player should read worse, which is the whole point of
        preferring a measurement."""
        (band,) = nagua.methods(_VALID, lambda m: _measured(80.0))["Runecraft"]
        assert band.xp_per_hour == 1_000.0
        assert band.match == CONFIRMED

    def test_it_asks_about_the_monster_upstream_names(self) -> None:
        asked: list[str] = []

        def kph(monster: str) -> Rate:
            asked.append(monster)
            return _measured(200.0)

        nagua.methods(_VALID, kph)
        assert asked == ["Sulphur Nagua"]

    def test_one_band_and_no_curve(self) -> None:
        """A nagua drops what it drops at every level; what moves the rate is
        the gear, not the Runecraft."""
        assert len(nagua.methods(_VALID, lambda m: _measured(200.0))["Runecraft"]) == 1


class TestTheLevelIsUpstreams:
    def test_upstream_wins_over_the_infobox(self) -> None:
        """`{{Skill info}}` says 1 and upstream says 20. Upstream's is the gate
        the derivation applied and the conservative direction."""
        (band,) = nagua.methods(_VALID, lambda m: _measured(200.0))["Runecraft"]
        assert band.level == 20
        assert nagua.STATED_LEVEL == 1

    def test_the_infobox_is_the_fallback(self) -> None:
        valid: dict[str, dict[str, object]] = {"Runecraft": {nagua.TASK: {}}}
        (band,) = nagua.methods(valid, lambda m: _measured(200.0))["Runecraft"]
        assert band.level == nagua.STATED_LEVEL


class TestReachability:
    def test_nothing_without_eyatlalli(self) -> None:
        assert nagua.methods({}, lambda m: _measured(200.0)) == {}
        assert nagua.methods({"Runecraft": {}}, lambda m: _measured(200.0)) == {}

    def test_a_zero_kill_rate_is_no_rate(self) -> None:
        assert nagua.methods(_VALID, lambda m: _measured(0.0)) == {}

    def test_the_band_names_the_task_it_is_overridden_through(self) -> None:
        (band,) = nagua.methods(_VALID, lambda m: _measured(200.0))["Runecraft"]
        assert band.knob == f"training/{nagua.TASK}/Runecraft"


@pytest.mark.real_export
class TestUpstreamStillCarriesWhatThisNames:
    def test_the_challenge_and_the_monster_spelling(
        self, real_export: ChunkInfo
    ) -> None:
        """**The monster's spelling is the join.** `Heuristics.kills_per_hour`
        is keyed by upstream's name, and `Sulphur nagua` finds nothing."""
        challenge = (real_export.challenges.get("Runecraft") or {}).get(nagua.TASK)
        assert isinstance(challenge, dict), "upstream lost the Eyatlalli challenge"
        assert challenge.get("Primary") is True
        assert challenge.get("Level") == 20
        slayer = real_export.challenges.get("Slayer") or {}
        drops = [
            name
            for name, entry in slayer.items()
            if isinstance(entry, dict) and nagua.MONSTER in (entry.get("Monsters") or ())
        ]
        assert drops, f"upstream no longer names {nagua.MONSTER}"


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "nagua.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = (
            pathlib.Path(nagua.__file__)
            .with_name("__init__.py")
            .read_text(encoding="utf-8")
        )
        assert "`nagua.py`" in listing
