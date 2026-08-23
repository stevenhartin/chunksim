"""The Theatre of Blood: six fixed rooms, a trio, and a third of the chest."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import encounter, theatre
from chunksim.costing.dps_bridge import load_monster_index


def _seconds(target: str) -> float | None:
    return 60.0


class TestTheRooms:
    def test_six_rooms_in_the_published_order(self) -> None:
        assert [room for room, _ in theatre.ROOMS] == [
            "The Maiden",
            "The Pestilent Bloat",
            "The Nylocas",
            "Sotetseg",
            "Xarpus",
            "Verzik Vitur",
        ]

    def test_verzik_is_three_targets(self) -> None:
        """`osrs-dps` models her phases apart and a run fights all three."""
        _room, targets = theatre.ROOMS[-1]
        assert len(targets[theatre.NORMAL]) == 3

    def test_every_mode_names_every_room(self) -> None:
        for _room, targets in theatre.ROOMS:
            assert set(targets) == {theatre.ENTRY, theatre.NORMAL, theatre.HARD}

    def test_the_keys_are_spelled_out_because_the_suffixes_disagree(self) -> None:
        """**A suffix rule would have looked tidier and silently missed
        rooms**: the same mode is `#Normal`, `#Normal mode` and `#Normal Mode`
        across the six."""
        normals = {
            target
            for _room, targets in theatre.ROOMS
            for target in targets[theatre.NORMAL]
        }
        suffixes = {target.partition("#")[2] for target in normals}
        assert len(suffixes) > 1


class TestTheChest:
    def test_the_unique_table_sums_to_one(self) -> None:
        for mode in (theatre.NORMAL, theatre.HARD):
            assert sum(theatre.UNIQUE_TABLE[mode].values()) == pytest.approx(1.0)

    def test_the_published_team_chances(self) -> None:
        """Deathless, from `Monumental chest`."""
        assert theatre.TEAM_UNIQUE_CHANCE[theatre.NORMAL] == pytest.approx(1 / 9.1)
        assert theatre.TEAM_UNIQUE_CHANCE[theatre.HARD] == pytest.approx(1 / 7.7)

    def test_entry_mode_grants_no_uniques_at_all(self) -> None:
        """"Entry Mode does not grant pre-rolls for uniques" - so however fast
        it runs it can never close a collection log, which is why `best` does
        not consider it."""
        assert theatre.TEAM_UNIQUE_CHANCE[theatre.ENTRY] == 0.0
        assert theatre.personal_unique_chance(theatre.ENTRY) == 0.0
        assert theatre.ENTRY not in (theatre.NORMAL, theatre.HARD)

    def test_a_bigger_team_divides_the_same_roll(self) -> None:
        """**The single most important line in the module.** The roll is once
        per team - "the drop rate is the same regardless of the number of
        players ... the item is allocated to one player" - so a party does not
        roll more often, it shares one roll. Forgetting it reports the log
        closing three times too fast."""
        solo = theatre.personal_unique_chance(theatre.NORMAL, party_size=1)
        trio = theatre.personal_unique_chance(theatre.NORMAL, party_size=3)
        assert trio == pytest.approx(solo / 3)
        assert trio == pytest.approx(1 / 27.3, rel=1e-3)

    def test_hard_mode_shifts_weight_off_the_hilt(self) -> None:
        """The wiki's own reason for the different denominator: "with the
        weighting for the avernic defender hilt reduced in order to make the
        other uniques more common"."""
        normal = theatre.UNIQUE_TABLE[theatre.NORMAL]["Avernic defender hilt"]
        hard = theatre.UNIQUE_TABLE[theatre.HARD]["Avernic defender hilt"]
        assert hard < normal
        for item, weight in theatre.UNIQUE_TABLE[theatre.HARD].items():
            if item != "Avernic defender hilt":
                assert weight >= theatre.UNIQUE_TABLE[theatre.NORMAL][item]


class TestTheAnswer:
    def test_a_run_is_the_six_rooms_and_the_walking(self) -> None:
        got = theatre.answer(theatre.NORMAL, _seconds)
        assert got is not None
        fights = sum(len(t[theatre.NORMAL]) for _r, t in theatre.ROOMS)
        walking = theatre.BETWEEN_ROOMS_SECONDS * theatre.ROOM_TRANSITIONS
        assert got.run.seconds == pytest.approx(
            fights * 60.0 / theatre.PARTY_SIZE / theatre.UPTIME + walking
        )

    def test_a_named_unique_is_its_own_expectation(self) -> None:
        got = theatre.answer(
            theatre.NORMAL, _seconds,
            encounter.Objective.for_unique("Scythe of Vitur (uncharged)"),
        )
        assert got is not None
        chance = theatre.item_chances(theatre.NORMAL)["Scythe of Vitur (uncharged)"]
        assert got.runs == pytest.approx(1 / chance)

    def test_the_green_log_needs_more_runs_than_any_one_item(self) -> None:
        every = theatre.answer(theatre.NORMAL, _seconds)
        scythe = theatre.answer(
            theatre.NORMAL, _seconds,
            encounter.Objective.for_unique("Scythe of Vitur (uncharged)"),
        )
        assert every is not None and scythe is not None
        assert every.runs > scythe.runs

    def test_experience_is_declined_rather_than_guessed(self) -> None:
        """A raid's combat experience is its bosses' hitpoints against a
        party's damage share, which is `costing/combat_xp.py`'s question."""
        assert theatre.answer(
            theatre.NORMAL, _seconds, encounter.Objective(kind=encounter.EXPERIENCE)
        ) is None

    def test_an_unpriceable_room_drops_the_mode(self) -> None:
        assert theatre.answer(theatre.NORMAL, lambda target: None) is None

    def test_the_shroud_binds_and_that_reverses_the_answer(self) -> None:
        """**Two thousand completions is a collection log entry**, and once it
        binds the drop rate stops deciding anything: the fastest qualifying
        mode wins instead. Hard mode is better per raid and still loses,
        because both modes need the same 2,000 raids and its rooms are
        longer. Missed when this module was written and found by the Tombs,
        which has the same constraint under another name."""
        every = theatre.answer(theatre.HARD, _seconds)
        assert every is not None
        assert every.runs == theatre.CAPE_COMPLETIONS
        assert every.bound_by == "cape"
        got = theatre.best(_seconds)
        assert got is not None and got.mode == theatre.NORMAL

    def test_a_named_unique_is_not_capped_by_the_shroud(self) -> None:
        """The cape is a green-log constraint, not a drop-rate one - so asking
        for one item still gets hard mode, where it is likelier."""
        scythe = encounter.Objective.for_unique("Scythe of Vitur (uncharged)")
        got = theatre.best(_seconds, scythe)
        assert got is not None and got.mode == theatre.HARD


@pytest.mark.real_export
class TestAgainstTheLibrary:
    def test_every_room_of_every_mode_is_a_target_osrs_dps_knows(self) -> None:
        """**A key that matches nothing drops the whole raid**, and silently:
        `encounter.build` returns `None` and the mode simply vanishes."""
        idx = load_monster_index()
        for _room, targets in theatre.ROOMS:
            for mode, keys in targets.items():
                for key in keys:
                    assert key in idx, f"{mode}: {key}"

    def test_the_guide_is_twenty_minutes(self) -> None:
        assert theatre.PUBLISHED_SECONDS == pytest.approx(1200.0)


@pytest.mark.real_cache
class TestAgainstARealMapsGear:
    """**The floor, checked with real damage rather than a stub.**

    `Money making guide/Theatre of Blood` states `kph = 3` for a trio - but
    its gear list includes a Scythe of Vitur, a Theatre drop, so it describes
    an established raider re-running content they have already looted. It is
    kept as a floor rather than a fit: fitted to it, every map would report
    twenty minutes and the gear a map actually reached - the thing this
    project exists to compute - would have been divided out.
    """

    def test_a_real_partys_raid_is_slower_than_an_established_ones(self) -> None:
        import argparse

        from osrs_dps import RaidInputs

        from chunksim.cli import common
        from chunksim.costing import dps_bridge, inputs
        from chunksim.costing.levels import infer_levels
        from chunksim.derive import pipeline
        from chunksim.model.chunkinfo import ChunkInfo
        from chunksim.store.cache import read_chunkinfo

        if not dps_bridge.DPS_AVAILABLE:
            pytest.skip("needs the dps extra")
        info = ChunkInfo(read_chunkinfo())
        args = argparse.Namespace(map_id=None, chunkinfo=None)
        try:
            state, unlocked = common.load_state(args, "fray-uber", chunk_info=info)
        except Exception:  # pragma: no cover - the map is a developer's
            pytest.skip("needs the every-rollable-chunk map")
        derived = pipeline.derive(state, unlocked)
        blobs = inputs.load_reference(None, "fray-uber")
        levels = {**infer_levels(state), **blobs.levels}
        kit = dps_bridge.assemble_kit(
            state.chunk_info, levels,
            items=derived.challenges.available_items,
            source_index=derived.source_index,
        )
        loadouts = dps_bridge.build_loadouts(
            state.chunk_info, derived.bis.picks, levels, kit
        )
        index = dps_bridge.load_monster_index()
        versions = dps_bridge.version_index(index)
        raid = RaidInputs(party_size=theatre.PARTY_SIZE)

        def seconds(target: str) -> float | None:
            kill = dps_bridge.best_kill(
                loadouts, target,
                dps_bridge.candidate_targets(index, target, versions),
                boss=True, raid=raid,
            )
            return kill.ttk if kill else None

        got = theatre.answer(theatre.NORMAL, seconds)
        assert got is not None, "every room should price on the ceiling map"
        assert got.run.seconds > theatre.PUBLISHED_SECONDS


class TestItIsListed:
    def test_the_modules_are_listed_where_a_module_is_listed(self) -> None:
        listing = (
            pathlib.Path(theatre.__file__)
            .with_name("__init__.py")
            .read_text(encoding="utf-8")
        )
        assert "`theatre.py`" in listing
        assert "`encounter.py`" in listing
