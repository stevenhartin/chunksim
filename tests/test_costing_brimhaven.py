"""The Brimhaven Agility Arena: a tag rate plus a downtime rate.

**The tagging half is checked against five published figures and the
downtime half against one**, which is the split the module is built around -
everything derivable is derived and the one term nothing states is recovered
from a figure at a different level with different gear from the one it is
checked against.
"""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import brimhaven as arena
from chunksim.model.chunkinfo import ChunkInfo


class TestTheTaggingHalfDerivesExactly:
    """`60 x (30 x (level // 10) + 345)`, against the arena page's own table.

    Four figures, no free parameter, and they land to the hundred - which is
    what makes the recovered travel constant the *only* thing in the module
    that is not arithmetic.
    """

    @pytest.mark.parametrize(
        "level,gloves,published",
        [
            (40, False, 28_000.0),
            (40, True, 30_000.0),
            (80, False, 35_000.0),
            (80, True, 37_000.0),
        ],
    )
    def test_a_passive_rate_is_the_pages(
        self, level: int, gloves: bool, published: float
    ) -> None:
        # The page rounds its own figures to the nearest thousand ("roughly
        # 35,000 ... or roughly 37,000 with Karamja gloves 2"), so this is
        # within 0.5% on all four rather than exact.
        assert arena.tagging_xp_per_hour(level, gloves=gloves) == pytest.approx(
            published, rel=0.005
        )

    def test_the_elite_diary_bonus_is_the_pages(self) -> None:
        """"Roughly 2,277 experience per hour added onto these rates
        (regardless of Agility level)" - which is 6 extra tickets at the
        *gloved* 379.5, and reproducing it is what pins the reading of the
        10% as a chance of a second ticket rather than a bonus on the tag."""
        for level in (40, 80, 99):
            with_elite = arena.tagging_xp_per_hour(level, gloves=True, elite=True)
            without = arena.tagging_xp_per_hour(level, gloves=True)
            assert with_elite - without == pytest.approx(2_277.0, abs=1.0)

    def test_a_tag_pays_thirty_per_ten_levels(self) -> None:
        assert arena.tag_experience(9) == 0.0
        assert arena.tag_experience(10) == 30.0
        assert arena.tag_experience(40) == 120.0
        assert arena.tag_experience(99) == 270.0

    def test_the_three_hundred_cap_needs_a_boost_nobody_here_models(self) -> None:
        """"Maxing out at 300 if boosting to level 100 Agility" - so the cap
        is real and a climb cannot reach it."""
        assert arena.TAG_XP_CAP == 300.0
        assert arena.tag_experience(99) < arena.TAG_XP_CAP
        assert arena.tag_experience(100) == arena.TAG_XP_CAP


class TestTheDowntimeHalf:
    def test_the_floor_spikes_alone_are_the_guides_figure(self) -> None:
        """"Additionally, the floor spike obstacle can be used ... and can
        achieve approximately 36,000 experience per hour" - the downtime
        arithmetic with the travel term removed, and it is exact."""
        spikes = next(o for o in arena.OBSTACLES if o.name == "Floor spikes")
        assert spikes.xp_per_second * arena.SECONDS_PER_HOUR == pytest.approx(36_000.0)

    def test_the_travel_constant_is_recovered_from_the_guides_band(self) -> None:
        """One unpublished term, solved out of "around 45,000-50,000
        experience per hour" at level 40 without gloves."""
        assert arena.rate_at(arena.CALIBRATION_LEVEL) == pytest.approx(
            sum(arena.CALIBRATION_BAND) / 2.0
        )
        low, high = arena.CALIBRATION_BAND
        assert low < arena.rate_at(arena.CALIBRATION_LEVEL) < high

    def test_it_is_the_right_size_for_crossing_an_arena(self) -> None:
        """A number recovered rather than read still has to be plausible as
        the thing it claims to be: 27.3 seconds is about 45 ticks, and the
        obstacles it is made of run 4 to 13."""
        assert 20.0 < arena.TRAVEL_SECONDS_PER_TAG < 35.0

    def test_travel_is_less_than_the_cycle(self) -> None:
        assert arena.TRAVEL_SECONDS_PER_TAG < arena.SECONDS_PER_HOUR / arena.TAGS_PER_HOUR


class TestThePredictionAtTheOtherEnd:
    """**A check rather than an identity**, which is the whole reason the
    calibration was taken from the guide at 40 and not from this figure.
    The arena page says "at level 99 with the elite diary complete, expect to
    be able to achieve up to 68,000"; this predicts it with different gear at
    a different level, and lands under it because the recovered constant
    carries a level-40 player's failures into every band above."""

    def test_it_lands_just_under_the_published_ceiling(self) -> None:
        got = arena.rate_at(arena.TOP_END_LEVEL, gloves=True, elite=True)
        assert 0.90 < got / arena.TOP_END_XP_PER_HOUR < 0.95

    def test_it_does_not_exceed_a_figure_the_page_hedges_with_up_to(self) -> None:
        assert arena.rate_at(99, gloves=True, elite=True) < arena.TOP_END_XP_PER_HOUR


class TestWhatLevelFortyActuallyBuys:
    """**Not a faster method**, which is the module's finding and the opposite
    of what upstream's three tiers suggest."""

    def test_the_floor_spikes_still_win_at_forty(self) -> None:
        assert arena.best_obstacle(40).name == "Floor spikes"
        assert arena.best_obstacle(99).name == "Floor spikes"

    def test_both_level_forty_obstacles_are_slower_per_tick(self) -> None:
        spikes = arena.best_obstacle(20)
        for name in ("Spinning blades", "Darts"):
            row = next(o for o in arena.OBSTACLES if o.name == name)
            assert row.level == 40
            assert row.xp_per_tick < spikes.xp_per_tick

    def test_forty_adds_no_band_boundary_of_its_own(self) -> None:
        """Every boundary is the tag formula's, so they are the multiples of
        ten - if 40 unlocked a better obstacle there would be one at 40 that
        the tag formula did not put there, and there is not."""
        assert {level for level, _ in arena.bands()} == set(range(20, 100, 10))

    def test_the_rope_swing_is_what_forty_would_have_to_beat_below_twenty(
        self,
    ) -> None:
        assert arena.best_obstacle(19).name == "Rope swing"
        assert arena.best_obstacle(19).xp_per_tick < arena.best_obstacle(20).xp_per_tick


class TestThePressurePadIsTheTrap:
    """The highest-paying crossing in the arena and not the best method, since
    the 17 July 2024 change put an 8-tick dead time after two consecutive
    uses. Its headline number would have won."""

    _PAD = next(o for o in arena.OBSTACLES if o.name == "Pressure pad")

    def test_its_headline_rate_would_have_won(self) -> None:
        assert self._PAD.experience / self._PAD.ticks > arena.best_obstacle(99).xp_per_tick

    def test_the_lockout_is_two_paid_crossings_then_eight_dead_ticks(self) -> None:
        assert self._PAD.paid_uses == 2
        assert self._PAD.lockout_ticks == 8.0
        # 2 x 26 experience per (2 x 4 + 8) ticks.
        assert self._PAD.xp_per_tick == pytest.approx(3.25)

    def test_an_obstacle_with_no_lockout_is_the_plain_quotient(self) -> None:
        spikes = arena.best_obstacle(20)
        assert spikes.lockout_ticks == 0.0
        assert spikes.xp_per_tick == pytest.approx(spikes.experience / spikes.ticks)


class TestNothingIsOfferedBelowTwenty:
    """**Where the evidence stops**, not where the arena opens. Level 20 is
    where the floor spikes open and where every published figure about this
    arena starts, and below it the model would be optimistic in two
    unquantified ways at once."""

    def test_the_rate_is_nothing_below_it(self) -> None:
        assert arena.OPENS_AT == 20
        assert arena.rate_at(19) == 0.0
        assert arena.rate_at(1) == 0.0
        assert arena.rate_at(20) > 0.0

    def test_no_band_opens_before_it_whichever_challenge_asked(self) -> None:
        """Upstream's `Access the low-level obstacles` is level 1. All three
        take the same bands, which is what stops it claiming a rate for a
        regime nothing describes - `costing/pyramid.py`'s arrangement."""
        bands = arena.methods({"Agility": {t: {} for t in arena.TASKS}})["Agility"]
        assert min(b.level for b in bands if b.level is not None) == arena.OPENS_AT

    def test_what_it_would_have_read_at_level_one(self) -> None:
        """Recorded rather than asserted away: the ticket is level-independent
        and dominates, so an unguarded model reads ~37,000/hr at level 1 and
        would own the bottom of every Agility climb."""
        unguarded = arena.tagging_xp_per_hour(1) + arena.downtime_xp_per_hour(1)
        assert 35_000.0 < unguarded < 40_000.0


class TestTheBands:
    _ALL: dict[str, dict[str, object]] = {"Agility": {t: {} for t in arena.TASKS}}

    def test_they_only_rise(self) -> None:
        rates = [rate for _, rate in arena.bands()]
        assert rates == sorted(rates)
        assert len(set(rates)) == len(rates)

    def test_each_reachable_challenge_gets_them(self) -> None:
        found = arena.methods(self._ALL)["Agility"]
        assert len(found) == len(arena.TASKS) * len(arena.bands())

    def test_one_challenge_alone_still_works(self) -> None:
        one: dict[str, dict[str, object]] = {"Agility": {arena.TASKS[0]: {}}}
        assert len(arena.methods(one)["Agility"]) == len(arena.bands())

    def test_nothing_when_unreachable(self) -> None:
        assert arena.methods({}) == {}
        assert arena.methods({"Agility": {}}) == {}

    def test_every_band_names_its_own_task(self) -> None:
        knobs = {b.knob for b in arena.methods(self._ALL)["Agility"]}
        assert knobs == {f"training/{t}/Agility" for t in arena.TASKS}

    def test_they_are_inferred_and_that_reads_as_modelled(self) -> None:
        """**`INFERRED`, never `CONFIRMED`** - the split between travelling
        and crossing is this project's arithmetic over somebody's figure. It
        still belongs in `MODELLED_MATCHES`, because `published` means a guide
        decided the number and here one did not."""
        from chunksim.costing import coverage
        from chunksim.costing.gathering import INFERRED

        found = arena.methods(self._ALL)["Agility"]
        assert {b.match for b in found} == {INFERRED}
        assert INFERRED in coverage.MODELLED_MATCHES
        assert coverage.status_of(INFERRED) == "modelled"


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "brimhaven.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = pathlib.Path(arena.__file__).with_name("__init__.py").read_text(
            encoding="utf-8"
        )
        assert "`brimhaven.py`" in listing

    @pytest.mark.real_export
    def test_the_three_challenges_are_one_activity(self, real_export: ChunkInfo) -> None:
        """**One arena, three obstacle tiers** - upstream files them under the
        same chunk with the same `Output`, which is what makes giving all
        three the same bands right rather than a convenience. A key that
        matches nothing is silently inert, so this also pins the names."""
        agility = real_export.challenges["Agility"]
        seen = []
        for task in arena.TASKS:
            entry = agility.get(task)
            assert isinstance(entry, dict), task
            assert entry.get("Primary") is True, task
            seen.append((tuple(entry.get("Chunks") or ()), entry.get("Output")))
        assert len(set(seen)) == 1, seen
        assert [agility[t].get("Level") for t in arena.TASKS] == [1, 20, 40]
