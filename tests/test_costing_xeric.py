"""The Chambers of Xeric: a drawn layout, a point system, and 2,000 raids."""

from __future__ import annotations

import math
import pathlib

import pytest

from chunksim.costing import encounter, xeric
from chunksim.costing.dps_bridge import load_monster_index


def _factory(seconds: float = 60.0) -> xeric.KillSecondsFor:
    def outer(mode: str) -> encounter.KillSeconds:
        def inner(target: str) -> float | None:
            return seconds

        return inner

    return outer


class TestTheLayout:
    def test_a_normal_raid_draws_a_fraction_of_the_rooms(self) -> None:
        """**Eight of twelve, not the wiki-quote's bare four to six.** A
        real raider's own account: the wiki's "two or three combat and/or
        skilling rooms" per floor names only the *fights* this model
        tracks and misses the resource/scavenger rooms every floor also
        carries - real, walked, timed rooms with no entry of their own
        here. `NORMAL_ROOMS_LOW`/`HIGH`'s own docstring has the full case;
        a raid timed against the bare fights-only reading came out
        implausibly fast against real completion times."""
        assert xeric.expected_normal_rooms() == 8.0
        assert len(xeric.COMBAT_ROOMS) + len(xeric.PUZZLE_ROOMS) == 12
        assert xeric.room_share(xeric.NORMAL) == pytest.approx(2 / 3)

    def test_challenge_mode_has_every_room(self) -> None:
        assert xeric.room_share(xeric.CHALLENGE) == 1.0

    def test_the_guardians_are_a_puzzle_and_not_a_fight(self) -> None:
        """**`osrs-dps` says so by refusing to price one.** They take no damage
        from a weapon and are broken with a pickaxe, which is why `RaidInputs`
        carries a `party_sum_mining_level`. Listed as combat they priced the
        whole raid at nothing, since one unpriceable room drops the run."""
        assert "Guardians" in xeric.PUZZLE_ROOMS
        assert "Guardians" not in xeric.COMBAT_ROOMS

    def test_olm_is_always_last(self) -> None:
        rooms = xeric.plans(xeric.NORMAL)
        fights = [p for p in rooms if isinstance(p, encounter.FightPlan)]
        assert fights[-1].target in xeric.OLM
        assert all(f.count == 1.0 for f in fights if f.target in xeric.OLM)


class TestOlmsOwnUptime:
    """**A real raider's account: Olm alone is "almost 50%" of a whole
    raid, both modes.** A single shared `UPTIME` could not reproduce that
    without making the six ordinary bosses implausibly slow or
    `OVERHEAD_SECONDS` implausibly large - see `OLM_UPTIME`'s own
    docstring. Olm gets its own, much lower uptime instead."""

    def test_olm_gets_its_own_lower_uptime(self) -> None:
        found = xeric.mechanics()
        for target in xeric.OLM:
            assert found[target].uptime == xeric.OLM_UPTIME
        for targets in xeric.COMBAT_ROOMS.values():
            for target in targets:
                assert found[target].uptime == xeric.UPTIME
        assert xeric.OLM_UPTIME < xeric.UPTIME

    def test_olm_dominates_the_raid_at_equal_kill_speed(self) -> None:
        """Even asking every room the *same* flat kill time (so nothing
        about relative boss difficulty can explain it), Olm's own three
        targets and lower uptime alone should make it the largest single
        contributor to the raid - the shape "almost 50%" describes."""
        run = encounter.build(
            "Chambers of Xeric (test)", xeric.plans(xeric.NORMAL),
            lambda target: 30.0, xeric.mechanics(),
        )
        assert run is not None
        olm_seconds = sum(s.seconds for s in run.stages if s.target in xeric.OLM)
        assert olm_seconds / run.seconds > 0.3


class TestPointsAreNotDamage:
    def test_the_published_solo_figure_is_what_is_spent(self) -> None:
        """A solo raid's rooms and Olm come to about 4,300 hitpoints against
        30,000 points - points are dominated by the skilling rooms, so the
        guide's own figure is the anchor rather than anything derived."""
        assert xeric.SOLO_NORMAL_POINTS == 30_000.0

    def test_it_reproduces_the_guides_other_two_figures(self) -> None:
        """"Roughly a 3.4% chance of hitting the table, equating to a ~1/33
        drop rate" - which is the check that reading it this way is right."""
        chance = xeric.unique_rolls(xeric.SOLO_NORMAL_POINTS)
        assert chance == pytest.approx(0.0346, abs=0.001)
        assert 25 < 1 / chance < 35

    def test_challenge_points_are_inferred_and_say_so(self) -> None:
        """The wiki says only "much higher", so this is the room-count ratio
        plus the 5,000 it does publish for a fast completion."""
        assert xeric.points_for(xeric.CHALLENGE, fast=True) == pytest.approx(
            xeric.SOLO_NORMAL_POINTS * xeric.CM_POINT_MULTIPLIER
            + xeric.CM_COMPLETION_POINTS
        )
        assert xeric.points_for(xeric.CHALLENGE, fast=False) < xeric.points_for(
            xeric.CHALLENGE, fast=True
        )


class TestTheChest:
    def test_the_worked_example_from_the_wiki(self) -> None:
        """"A team who possesses 855,000 points in total has a 65.7% chance to
        receive a unique loot, and then a 32.85% chance to obtain a second"."""
        assert xeric.unique_rolls(570_000) == pytest.approx(0.657, abs=5e-4)
        assert xeric.unique_rolls(855_000) == pytest.approx(0.657 + 0.3285, abs=1e-3)

    def test_the_two_pages_disagree_by_one_point(self) -> None:
        """**`Ancient chest` says 8,676 and `Chambers of Xeric/Strategies`
        says 8,675**, and the cap does not discriminate - 570,000 over either
        rounds to 65.7%. The chest's own figure is taken, being the page about
        the chest, and the difference is 0.001% on a roll."""
        assert xeric.POINTS_PER_PERCENT == 8_676.0
        other = 570_000 / 8_675 / 100
        assert abs(other - xeric.MAX_ROLL_CHANCE) < 1e-4

    def test_the_chance_is_capped_per_roll_not_overall(self) -> None:
        """Which is what lets a raid be worth more than one unique."""
        assert xeric.unique_rolls(570_000 * 3) > 1.0

    def test_never_more_than_six_rolls(self) -> None:
        huge = xeric.unique_rolls(570_000 * 50)
        assert huge == pytest.approx(xeric.MAX_ROLL_CHANCE * xeric.MAX_ROLLS)

    def test_both_tables_sum_to_one(self) -> None:
        for mode in (xeric.NORMAL, xeric.CHALLENGE):
            assert sum(xeric.UNIQUE_TABLE[mode].values()) == pytest.approx(1.0)

    def test_no_points_is_no_roll(self) -> None:
        assert xeric.unique_rolls(0.0) == 0.0


class TestOnlyChallengeModeCanCloseTheLog:
    def test_every_mode_names_every_item(self) -> None:
        """**The bug this prevents.** A normal raid that simply omitted the
        colour kit and the dust had `runs_for_all` closing a log two items
        short - 821 hours against an honest infinity."""
        normal = xeric.item_chances(xeric.NORMAL)
        challenge = xeric.item_chances(xeric.CHALLENGE)
        assert set(normal) == set(challenge)
        for item in xeric.CHALLENGE_ONLY:
            assert normal[item] == 0.0
            assert challenge[item] > 0.0

    def test_a_normal_green_log_is_infinite(self) -> None:
        got = xeric.answer(xeric.NORMAL, _factory())
        assert got is not None and got.runs == math.inf

    def test_the_cape_binds_rather_than_the_drops(self) -> None:
        """2,000 Challenge Mode completions for `Xeric's champion`, counted
        separately from normal raids - and at 1/75 those 2,000 are worth about
        26 colour kits, so no unique is the constraint."""
        got = xeric.answer(xeric.CHALLENGE, _factory())
        assert got is not None
        assert got.runs == xeric.CAPE_COMPLETIONS
        assert got.bound_by == "cape"

    def test_best_is_challenge_mode(self) -> None:
        got = xeric.best(_factory())
        assert got is not None and got.mode == xeric.CHALLENGE

    def test_a_named_unique_is_not_capped_by_the_cape(self) -> None:
        got = xeric.answer(
            xeric.NORMAL, _factory(), encounter.Objective.for_unique("Twisted bow")
        )
        assert got is not None and got.runs < math.inf


class TestReachability:
    def test_an_unpriceable_room_drops_the_mode(self) -> None:
        assert xeric.answer(xeric.NORMAL, lambda mode: lambda target: None) is None

    def test_experience_is_declined_rather_than_guessed(self) -> None:
        assert xeric.answer(
            xeric.NORMAL, _factory(),
            encounter.Objective(kind=encounter.EXPERIENCE),
        ) is None


@pytest.mark.real_export
class TestAgainstTheLibrary:
    def test_every_fight_is_a_target_osrs_dps_knows(self) -> None:
        index = load_monster_index()
        for room, targets in xeric.COMBAT_ROOMS.items():
            for target in targets:
                assert target in index, f"{room}: {target}"
        for target in xeric.OLM:
            assert target in index

    def test_challenge_mode_is_an_input_and_not_a_monster(self) -> None:
        """**There are no `#Challenge Mode` monsters and there should not be.**
        The library scales them from `RaidInputs.challenge_mode`, which is why
        `answer` takes a factory rather than a lookup - one lookup would have
        priced Challenge Mode at normal-mode health."""
        index = load_monster_index()
        assert not [key for key in index if "Challenge Mode" in key and "Xeric" in key]

    def test_the_challenge_scaling_matches_the_wikis_words(self) -> None:
        """"All enemies' stats and health (barring the Great Olm, who only has
        increased stats) are increased" - measured at 1.5x on everything but
        Olm, who is untouched."""
        from osrs_dps import RaidInputs, scale

        from chunksim.costing import dps_bridge

        index = load_monster_index()
        versions = dps_bridge.version_index(index)
        for target in ("Tekton#Normal", "Vasa Nistirio#Normal"):
            pair = dps_bridge.candidate_targets(index, target, versions)[0][1]
            plain = scale(pair, RaidInputs(party_size=1))
            hard = scale(pair, RaidInputs(party_size=1, challenge_mode=True))
            assert hard.hitpoints == pytest.approx(plain.hitpoints * 1.5)
        head = dps_bridge.candidate_targets(index, xeric.OLM[-1], versions)[0][1]
        assert scale(head, RaidInputs(party_size=1, challenge_mode=True)).hitpoints == (
            scale(head, RaidInputs(party_size=1)).hitpoints
        )


class TestItIsListed:
    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = (
            pathlib.Path(xeric.__file__)
            .with_name("__init__.py")
            .read_text(encoding="utf-8")
        )
        assert "`xeric.py`" in listing
