"""All three raids at once: summed, not compared, and bound by three capes."""

from __future__ import annotations

import math
import pathlib

import pytest

from chunksim.costing import encounter, raids, theatre, tombs, xeric


def _cox(mode: str) -> encounter.KillSeconds:
    return lambda target: 60.0


def _tob(target: str) -> float | None:
    return 60.0


def _toa(level: int) -> tombs.StatsFor:
    return lambda target: (60.0, 4_000.0)


class TestTheThreeAreAdded:
    def test_the_total_is_the_sum_and_not_the_minimum(self) -> None:
        """**The shape of the goal, not a modelling choice.** The export
        carries all three raids' rewards as separate collection log entries,
        so a player needs all three logs."""
        got = raids.compare(_cox, _tob, _toa)
        assert len(got.answers) == 3
        assert got.hours == pytest.approx(sum(a.hours for a in got.answers))
        assert got.hours > max(a.hours for a in got.answers)

    def test_every_raid_is_named(self) -> None:
        got = raids.compare(_cox, _tob, _toa)
        assert {a.raid for a in got.answers} == {
            raids.CHAMBERS, raids.THEATRE, raids.TOMBS
        }

    def test_the_slowest_leg_is_reported(self) -> None:
        got = raids.compare(_cox, _tob, _toa)
        slowest = got.slowest()
        assert slowest is not None
        assert slowest.hours == max(a.hours for a in got.answers)


class TestTwoThousandThreeTimes:
    def test_every_cape_is_the_same_two_thousand(self) -> None:
        assert xeric.CAPE_COMPLETIONS == 2_000
        assert theatre.CAPE_COMPLETIONS == 2_000
        assert tombs.CAPE_COMPLETIONS == 2_000

    def test_the_capes_bind_rather_than_the_tables(self) -> None:
        got = raids.compare(_cox, _tob, _toa)
        bound = {a.raid: a.bound_by for a in got.answers}
        assert bound[raids.CHAMBERS] == "cape"
        assert bound[raids.THEATRE] == "cape"


class TestPickingIsOnlyForOneItem:
    def test_best_for_answers_a_named_unique(self) -> None:
        got = raids.compare(
            _cox, _tob, _toa, encounter.Objective.for_unique("Twisted bow")
        )
        best = raids.best_for(got)
        assert best is not None and best.raid == raids.CHAMBERS

    def test_an_item_only_one_raid_gives_leaves_the_others_infinite(self) -> None:
        got = raids.compare(
            _cox, _tob, _toa,
            encounter.Objective.for_unique("Scythe of Vitur (uncharged)"),
        )
        best = raids.best_for(got)
        assert best is not None and best.raid == raids.THEATRE
        others = [a for a in got.answers if a.raid != raids.THEATRE]
        assert all(a.hours == math.inf for a in others)

    def test_an_unreachable_raid_leaves_the_comparison_incomplete(self) -> None:
        got = raids.compare(lambda mode: lambda target: None, _tob, _toa)
        assert len(got.answers) == 2
        assert raids.CHAMBERS not in {a.raid for a in got.answers}


class TestTheItemWalkSeam:
    def test_the_lily_is_priced_from_the_guide_not_the_model(self) -> None:
        """**`estimate.material_seconds` runs before the DPS enrichment**, so
        it has no raid duration of its own - the guide answers directly.
        `Money making guide/Tombs of Amascut (Expert)` states the yield as
        `3 * ((1/27) * 19) * regchance` beside `kph = 1.75`."""
        seconds = tombs.guide_item_seconds("Lily of the Sands")
        assert seconds is not None
        assert 600 < seconds < 1_800

    def test_both_spellings_are_emitted(self) -> None:
        """Upstream writes a small `s` and the wiki now capitalises it, and
        the walk is keyed by the export's vocabulary."""
        found = tombs.item_seconds()
        assert "Lily of the sands" in found
        assert "Lily of the Sands" in found
        assert found["Lily of the sands"] == found["Lily of the Sands"]

    def test_the_guide_measures_this_modules_understatement(self) -> None:
        """Nineteen is `Points / 1100 * 1.15`, so the guide asserts 18,174
        points where `points_for` derives 7,475 - the six health bars are 41%
        of a raid's score. Recorded, and deliberately not corrected by a
        fitted multiplier."""
        assert tombs.guide_implied_points() == pytest.approx(18_174, abs=10)

    def test_an_item_the_guide_does_not_state_is_not_invented(self) -> None:
        assert tombs.guide_item_seconds("Dragon med helm") is None

    def test_estimate_merges_it(self) -> None:
        from chunksim.costing import estimate

        source = pathlib.Path(estimate.__file__).read_text(encoding="utf-8")
        assert "tombs.item_seconds()" in source


class TestItIsListed:
    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = (
            pathlib.Path(raids.__file__)
            .with_name("__init__.py")
            .read_text(encoding="utf-8")
        )
        assert "`raids.py`" in listing
