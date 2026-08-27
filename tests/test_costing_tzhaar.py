"""The Fight Caves and the Inferno: one wave schedule, two rosters."""

from __future__ import annotations

import pytest

from chunksim.costing import encounter, raids, tzhaar
from chunksim.costing.dps_bridge import load_monster_index


def _seconds(target: str) -> float | None:
    return 5.0


class TestTheSchedule:
    def test_the_published_wave_counts(self) -> None:
        """63 and 69, as both pages state."""
        assert tzhaar.WAVES[tzhaar.FIGHT_CAVES] == 63
        assert tzhaar.WAVES[tzhaar.INFERNO] == 69

    def test_the_five_tiers_have_identical_counts_across_the_two(self) -> None:
        """**The module's central claim**, read off the two wave tables: the
        caves' 48/40/36/34/33 is the Inferno's 48/40/36/34/33.
        """
        caves = [
            tzhaar.WAVE_ROSTER[tzhaar.FIGHT_CAVES][t]
            for t in tzhaar.TIERS[tzhaar.FIGHT_CAVES]
        ]
        inferno = [
            tzhaar.WAVE_ROSTER[tzhaar.INFERNO][t]
            for t in tzhaar.TIERS[tzhaar.INFERNO]
        ]
        assert caves == [48, 40, 36, 34, 33]
        assert caves == inferno

    def test_the_roles_do_not_match_even_though_the_counts_do(self) -> None:
        """The other half of the claim, and the reason the tiers are ordered
        by *introduction* rather than by role: the caves' third monster is a
        ranger and the Inferno's is a meleer.
        """
        caves = tzhaar.TIERS[tzhaar.FIGHT_CAVES]
        inferno = tzhaar.TIERS[tzhaar.INFERNO]
        assert caves[2].startswith("Tok-Xil")  # ranger
        assert inferno[2].startswith("Jal-ImKot")  # meleer
        assert caves[3].startswith("Yt-MejKot")  # meleer
        assert inferno[3].startswith("Jal-Xil")  # ranger

    def test_the_published_split_mechanics_are_folded_in(self) -> None:
        """Two level-22 per level-45 killed, three small blobs per blob."""
        caves = tzhaar.WAVE_ROSTER[tzhaar.FIGHT_CAVES]
        assert caves["Tz-Kek#Level 22"] == 2 * caves["Tz-Kek#Level 45"]

        inferno = tzhaar.WAVE_ROSTER[tzhaar.INFERNO]
        for small in ("Jal-AkRek-Xil", "Jal-AkRek-Mej", "Jal-AkRek-Ket"):
            assert inferno[small] == inferno["Jal-Ak"]

    def test_the_inferno_carries_its_two_hundred_and_ten_nibblers(self) -> None:
        """Three a wave over sixty-six waves plus the odd extra - the biggest
        single difference between the two rosters."""
        assert tzhaar.WAVE_ROSTER[tzhaar.INFERNO]["Jal-Nib"] == 210

    def test_jad_healer_counts_follow_the_published_rule(self) -> None:
        """Four for TzTok-Jad; five for the first JalTok-Jad and three for
        each on waves 68 and 69."""
        assert tzhaar.WAVE_ROSTER[tzhaar.FIGHT_CAVES]["Yt-HurKot#Level 108"] == 4
        # Wave 67's five and wave 68's three apiece; Zuk's own three are in
        # `ZUK_ROOM`, not here.
        assert tzhaar.WAVE_ROSTER[tzhaar.INFERNO]["Yt-HurKot#Level 141"] == 5 + 3 * 3
        assert tzhaar.roster(tzhaar.INFERNO)["Yt-HurKot#Level 141"] == 5 + 3 * 3 + 3

    def test_every_target_is_a_key_the_dps_library_knows(self) -> None:
        """A misspelt key prices as `None` and `encounter.build` refuses the
        whole run, so this is the difference between a model and a silence."""
        idx = load_monster_index()
        for variant in (tzhaar.FIGHT_CAVES, tzhaar.INFERNO):
            for target in tzhaar.roster(variant):
                assert target in idx, f"{variant}: {target}"


class TestThePet:
    def test_the_cape_can_be_exchanged_for_a_second_roll(self) -> None:
        """Published on both pages, and worth nearly a factor of two. `1 -
        (1-p)^2`, not `2p`."""
        assert tzhaar.pet_chance(tzhaar.INFERNO) == pytest.approx(
            1.0 - 0.99**2
        )
        assert tzhaar.pet_chance(tzhaar.FIGHT_CAVES) == pytest.approx(
            1.0 - 0.995**2
        )

    def test_the_inferno_pet_is_twice_as_likely_as_the_caves(self) -> None:
        """1/100 against 1/200, before the exchange roll and after it."""
        assert tzhaar.PET_CHANCE[tzhaar.INFERNO] == 2 * tzhaar.PET_CHANCE[
            tzhaar.FIGHT_CAVES
        ]

    def test_a_pet_costs_about_fifty_runs_not_one_kill(self) -> None:
        """**The defect this module exists for.** The export files the pet as
        a 1/100 drop off a monster, and the walk read twenty of that monster
        an hour - five hours for something that is fifty Infernos.
        """
        runs = encounter.expected_runs(tzhaar.pet_chance(tzhaar.INFERNO))
        assert 45 < runs < 55


class TestTheItemWalk:
    def test_both_capes_and_both_pets_are_priced(self) -> None:
        priced = tzhaar.item_seconds()
        assert set(priced) == {
            "Fire cape",
            "Infernal cape",
            "Tzrek-jad",
            "Jal-nib-rek",
        }

    def test_the_inferno_carries_the_fight_caves_entry_fee(self) -> None:
        """A fire cape buys entry, one time - so an infernal cape is one run
        of each."""
        priced = tzhaar.item_seconds()
        assert priced["Infernal cape"] == pytest.approx(
            tzhaar.RUN_SECONDS[tzhaar.FIGHT_CAVES]
            + tzhaar.RUN_SECONDS[tzhaar.INFERNO]
        )

    def test_the_pet_is_two_orders_of_magnitude_off_the_cape(self) -> None:
        """The shape that matters: a cape is one run and a pet is fifty."""
        priced = tzhaar.item_seconds()
        assert priced["Jal-nib-rek"] > 20 * priced["Infernal cape"]

    def test_nothing_collides_with_the_raids(self) -> None:
        """`estimate._run_priced_items` merges the two, so a shared key would
        be one silently winning rather than a tie-break."""
        assert not set(tzhaar.item_seconds()) & set(raids.item_seconds())

    def test_nothing_collides_across_all_eight_run_priced_families(self) -> None:
        """`estimate._run_priced_items` merges `raids`, `tzhaar`,
        `barrows`, `colosseum`, `moons`, `gauntlet`, `wintertodt` and
        `tempoross` - a shared key anywhere in that eight-way merge would
        be one silently winning rather than a tie-break, the same contract
        the two-way check above pins."""
        from chunksim.costing import barrows, colosseum, gauntlet, moons, tempoross, wintertodt

        families = {
            "raids": set(raids.item_seconds()),
            "tzhaar": set(tzhaar.item_seconds()),
            "barrows": set(barrows.item_seconds()),
            "colosseum": set(colosseum.item_seconds()),
            "moons": set(moons.item_seconds()),
            "gauntlet": set(gauntlet.item_seconds()),
            "wintertodt": set(wintertodt.item_seconds()),
            "tempoross": set(tempoross.item_seconds()),
        }
        names = list(families)
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                assert not families[a] & families[b], (a, b, families[a] & families[b])

    def test_the_activity_is_named_for_the_run_that_earns_it(self) -> None:
        """`raid: 1 Jal-nib-rek` sent a reader to `costing/raids.py`, which
        has never heard of it."""
        assert tzhaar.activity_for("Jal-nib-rek") == tzhaar.INFERNO
        assert tzhaar.activity_for("jal-nib-rek") == tzhaar.INFERNO
        assert tzhaar.activity_for("Fire cape") == tzhaar.FIGHT_CAVES
        assert tzhaar.activity_for("Twisted bow") is None


class TestTheSequencer:
    def test_a_run_prices_every_monster_or_none_at_all(self) -> None:
        """`encounter.build`'s all-or-nothing rule: a run missing one
        monster's time is not slightly shorter, it is a number with an
        invisible hole."""
        assert tzhaar.run(tzhaar.INFERNO, lambda target: None) is None

    def test_the_inferno_is_the_longer_of_the_two(self) -> None:
        caves = tzhaar.run(tzhaar.FIGHT_CAVES, _seconds)
        inferno = tzhaar.run(tzhaar.INFERNO, _seconds)
        assert caves is not None and inferno is not None
        assert inferno.seconds > caves.seconds

    def test_the_per_wave_cost_scales_with_the_wave_count(self) -> None:
        """The one term that is not a fight, and the one that is invented."""
        for variant in (tzhaar.FIGHT_CAVES, tzhaar.INFERNO):
            waiting = [
                plan
                for plan in tzhaar.plans(variant)
                if isinstance(plan, encounter.PuzzlePlan)
            ]
            assert len(waiting) == 1
            assert waiting[0].seconds == pytest.approx(
                tzhaar.PER_WAVE_SECONDS * tzhaar.WAVES[variant]
            )

    def test_the_inferno_answer_pays_the_entry_fee_once(self) -> None:
        """Once, not per run - "This is a one-time fee"."""
        got = tzhaar.answer(tzhaar.INFERNO, _seconds)
        caves = tzhaar.run(tzhaar.FIGHT_CAVES, _seconds)
        assert got is not None and caves is not None
        assert got.entry_seconds == pytest.approx(caves.seconds)

    def test_experience_is_refused_rather_than_guessed(self) -> None:
        """`costing/combat_xp.py`'s question, not this module's."""
        objective = encounter.Objective(kind=encounter.EXPERIENCE)
        assert tzhaar.answer(tzhaar.INFERNO, _seconds, objective) is None

    def test_an_unknown_unique_is_refused(self) -> None:
        objective = encounter.Objective.for_unique("Twisted bow")
        assert tzhaar.answer(tzhaar.INFERNO, _seconds, objective) is None

    def test_a_cape_is_one_run(self) -> None:
        objective = encounter.Objective.for_unique("Infernal cape")
        got = tzhaar.answer(tzhaar.INFERNO, _seconds, objective)
        assert got is not None and got.runs == 1.0


class TestTheBandsAgree:
    """`RUN_SECONDS` is the flat band the item walk spends - these four only
    check its own internal shape (ordering, midpoint, the stated figures).

    **The comparison against the sequencer's own gear-sensitive answer lives
    elsewhere**, not here: `tests/test_dps_bridge.py`'s
    `TestTzhaarKillSeconds` exercises `tzhaar_kill_seconds` against real
    monster data, and `tests/test_costing_inputs.py`'s
    `TestTzhaarRunSeconds` exercises the wiring
    (`costing/inputs.py`'s `_tzhaar_run_seconds`) that feeds `run`'s answer
    into `Heuristics.run_seconds`. This class's own docstring used to
    promise that comparison without making it - see this module's own
    docstring on the claim that stood unchecked until now.
    """

    def test_the_band_is_ordered_best_typical_poor(self) -> None:
        for variant, (best, typical, poor) in tzhaar.RUN_BAND.items():
            assert best < typical < poor, variant

    def test_the_spent_figure_is_the_bands_midpoint(self) -> None:
        for variant, band in tzhaar.RUN_BAND.items():
            assert tzhaar.RUN_SECONDS[variant] == band[1]

    def test_the_stated_bands_are_the_ones_asked_for(self) -> None:
        """A maintainer's figures rather than a publication - pinned so a
        later edit is a deliberate one."""
        best, typical, poor = tzhaar.RUN_BAND[tzhaar.INFERNO]
        assert (best / 60, typical / 60, poor / 60) == (30.0, 52.5, 120.0)
        best, typical, poor = tzhaar.RUN_BAND[tzhaar.FIGHT_CAVES]
        assert (best / 60, typical / 60, poor / 60) == (30.0, 37.5, 75.0)

    def test_the_caves_are_the_easier_and_shorter_of_the_two(self) -> None:
        assert (
            tzhaar.RUN_SECONDS[tzhaar.FIGHT_CAVES]
            < tzhaar.RUN_SECONDS[tzhaar.INFERNO]
        )


class TestAKillThatIsARun:
    """**A task wanting a kill is not cheaper than one wanting the drop.**
    `costing/estimate.py` prices a kill goal at `1 / kills_per_hour`, which is
    right for something you can walk up to and wrong by three orders of
    magnitude for something sixty-eight waves in.
    """

    def test_the_two_final_bosses_are_the_runs_themselves(self) -> None:
        assert tzhaar.variant_of_boss("TzKal-Zuk") == tzhaar.INFERNO
        assert tzhaar.variant_of_boss("TzTok-Jad") == tzhaar.FIGHT_CAVES

    def test_killing_zuk_costs_a_whole_inferno_plus_its_entry_fee(self) -> None:
        got = tzhaar.kill_seconds("TzKal-Zuk")
        assert got == pytest.approx(
            tzhaar.RUN_SECONDS[tzhaar.INFERNO]
            + tzhaar.RUN_SECONDS[tzhaar.FIGHT_CAVES]
        )

    def test_killing_jad_costs_one_fight_caves_run(self) -> None:
        """No entry fee - the caves are free to enter."""
        assert tzhaar.kill_seconds("TzTok-Jad") == pytest.approx(
            tzhaar.RUN_SECONDS[tzhaar.FIGHT_CAVES]
        )

    def test_it_is_three_orders_of_magnitude_off_the_kill_rate(self) -> None:
        """The defect's size: four Combat Achievements naming `TzKal-Zuk`
        shared 0.05 hours between them at the fallback 20/hr."""
        fallback = 3600.0 / 20.0
        got = tzhaar.kill_seconds("TzKal-Zuk")
        assert got is not None and got > 25 * fallback

    def test_the_rank_and_file_are_refused_rather_than_guessed(self) -> None:
        """They are just as unreachable without a run, but the cheapest way
        to reach one is its first wave - and the wave ordering is exactly what
        this module does not carry."""
        for monster in ("Jal-Zek", "JalTok-Jad", "Ket-Zek#Standard", "Jal-Nib"):
            assert tzhaar.kill_seconds(monster) is None

    def test_an_ordinary_monster_is_left_alone(self) -> None:
        assert tzhaar.kill_seconds("Abyssal demon") is None


class TestTheEstimateRowIsHonest:
    """**A knob in the panel is a promise that editing it changes the
    number.** `actions/raids` and `actions/Inferno` kept that promise to
    nobody: neither name is in `action_seconds`, so the stack resolved to the
    bare `DEFAULT_ACTION_SECONDS` and showed an editable "2.4" - four ticks,
    the generic seconds-per-action - beside a forty-minute run.
    """

    def test_the_generic_action_default_is_four_ticks(self) -> None:
        """What the panel was showing, and what it is not: 2.4 *seconds per
        action*, not runs per hour."""
        from chunksim.costing.estimate import DEFAULT_ACTION_SECONDS

        assert DEFAULT_ACTION_SECONDS == pytest.approx(4 * 0.6)

    def test_no_run_name_resolves_to_an_action_rate(self) -> None:
        """The reason the knob was inert. If a later change puts one of these
        in `action_seconds`, the knob becomes meaningful and this test is the
        prompt to reattach it deliberately."""
        from chunksim.costing.heuristics import Heuristics

        actions = Heuristics().action_seconds
        for name in (tzhaar.INFERNO, tzhaar.FIGHT_CAVES, "raids"):
            assert name not in actions
