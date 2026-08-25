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

    def test_it_reaches_the_walk_through_raids(self) -> None:
        """`raids.item_seconds` folds the Tombs' own answer in, so both walks
        get one map rather than two that could drift."""
        assert "Lily of the sands" in raids.item_seconds()


class TestTheGoalWalkSeam:
    """**The number this replaces was wrong by two orders of magnitude.**

    The export models each raid as a monster carrying a drop table, so
    `Heuristics.kills_per_hour` fell back to `DEFAULT_KPH` and the goal walk
    read 150 completions an hour.
    """

    def test_a_cape_is_a_counter_and_not_a_drop(self) -> None:
        """`Xeric's champion` wants 2,000 Challenge Mode raids and used to
        price at 24 seconds. There is no rate to divide by here, only a count
        to multiply - which is why no drop table could ever have said it."""
        found = raids.item_seconds()
        champion = found["Xeric's champion"]
        assert champion == pytest.approx(
            raids.PUBLISHED_RAID_SECONDS[f"{raids.CHAMBERS} (challenge)"] * 2_000
        )
        assert champion / 3600 > 1_000

    def test_every_cape_tier_of_every_raid_is_priced(self) -> None:
        found = raids.item_seconds()
        for raid, tiers in raids.CAPE_TIERS.items():
            assert len(tiers) == 5, raid
            for cape in tiers:
                assert cape in found, cape

    def test_the_tiers_rise_with_the_count(self) -> None:
        found = raids.item_seconds()
        for tiers in raids.CAPE_TIERS.values():
            ordered = sorted(tiers.items(), key=lambda pair: pair[1])
            hours = [found[cape] for cape, _n in ordered]
            assert hours == sorted(hours)

    def test_the_pets_are_tertiary_rolls_and_priced_apart(self) -> None:
        """Each raid does it differently: the olmlet is conditional on the
        raid having given a unique, Lil' Zik is flat, and Tumeken's guardian
        reuses the Tombs' own formula with other constants."""
        found = raids.item_seconds()
        for pet in ("Olmlet", "Lil' Zik", "Tumeken's guardian"):
            assert found[pet] / 3600 > 100, pet

    def test_the_olmlet_is_conditional_on_a_unique(self) -> None:
        found = raids.item_seconds()
        unique = sum(xeric.item_chances(xeric.NORMAL).values())
        assert found["Olmlet"] == pytest.approx(
            raids.PUBLISHED_RAID_SECONDS[raids.CHAMBERS]
            / (unique * raids.OLMLET_GIVEN_UNIQUE)
        )

    def test_estimate_consults_it_before_the_routes(self) -> None:
        """**Before, not as a fallback.** `yield_seconds` is a last-resort map
        that by design never displaces a route, and the route here is the
        wrong one - so this needed `herb_seconds`' position instead."""
        from chunksim.costing import estimate

        source = pathlib.Path(estimate.__file__).read_text(encoding="utf-8")
        assert "raid_seconds=" in source
        assert source.index("walk.raid_seconds.get") < source.index(
            "walk.herb_seconds.get"
        )

    def test_the_lookup_folds_case(self) -> None:
        """Three vocabularies meet: the wiki writes `Scythe of Vitur
        (uncharged)`, the export's drop table writes `Scythe of vitur`, and
        `world.item_sources` does not carry it at all."""
        from chunksim.costing import estimate

        source = pathlib.Path(estimate.__file__).read_text(encoding="utf-8")
        assert "walk.raid_seconds.get(item.lower())" in source

    def test_activity_for_names_the_earning_raid(self) -> None:
        """Every item `item_seconds()` prices traces back to one of the
        three raids, matching `xeric.py`/`theatre.py`/`colosseum.py`'s own
        `activity_for` shape - see the module's docstring for why this was
        missing entirely until now, leaving every raid reward's `source`
        reading a bare `"raids"` with no knob."""
        assert raids.activity_for("Twisted bow") == raids.CHAMBERS
        assert raids.activity_for("Scythe of Vitur (uncharged)") == raids.THEATRE
        assert raids.activity_for("Lil' Zik") == raids.THEATRE
        assert raids.activity_for("Tumeken's guardian") == raids.TOMBS
        assert raids.activity_for("Xeric's champion") == raids.CHAMBERS
        assert raids.activity_for("Not a real reward") is None

    def test_activity_for_folds_case(self) -> None:
        """`_item_hours` resolves an item to the export's own spelling
        before `activity_for` ever sees it - `Scythe of vitur (uncharged)`,
        `Lil' zik` - not the wiki's, which is what `_by_raid()`'s tables are
        keyed by. An exact-match version of this function missed both."""
        assert raids.activity_for("Scythe of vitur (uncharged)") == raids.THEATRE
        assert raids.activity_for("Lil' zik") == raids.THEATRE

    def test_by_raid_still_sums_to_item_seconds(self) -> None:
        """The refactor into three dicts must not change the merged answer -
        a key both `tombs.item_seconds()` and this module's own Tombs table
        could write still resolves the same way it did as one flat dict."""
        merged: dict[str, float] = {}
        for items in raids._by_raid().values():
            merged.update(items)
        assert merged == raids.item_seconds()


class TestItIsListed:
    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = (
            pathlib.Path(raids.__file__)
            .with_name("__init__.py")
            .read_text(encoding="utf-8")
        )
        assert "`raids.py`" in listing
