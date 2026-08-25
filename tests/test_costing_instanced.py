"""The one place that says what killing a run's boss costs."""

from __future__ import annotations

import pytest

from chunksim.costing import instanced, raids, tzhaar
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.store.cache import read_chunkinfo


class TestTheContract:
    """**What stops this happening again.** Three layers each decided for
    themselves what a boss kill was worth and two were wrong; these assert the
    single answer stays complete.
    """

    def test_every_final_boss_has_a_run_behind_it(self) -> None:
        """A boss whose place has no duration falls back on a kills-per-hour,
        which is exactly what priced four Grandmaster achievements at 0.05
        hours between them."""
        assert instanced.unpriced_bosses() == frozenset()

    def test_every_final_boss_names_a_place_that_is_run_only(self) -> None:
        for boss, place in instanced.FINAL_BOSS.items():
            assert place in instanced.RUN_ONLY_PLACES, boss

    def test_every_final_boss_prices(self) -> None:
        """`None` here would silently drop the boss back to a kills-per-hour
        that does not describe the activity."""
        for boss in instanced.FINAL_BOSS:
            got = instanced.kill_seconds(boss)
            assert got is not None and got > 0, boss

    def test_no_final_boss_is_cheaper_than_five_minutes(self) -> None:
        """The shape of the defect, stated as a floor: whatever else changes,
        a run's boss must never read as something you pop in and kill. Not
        the ten-minute figure every other raid clears - the regular
        Gauntlet's own published run is 514 seconds, under ten minutes but
        nowhere near the fractions-of-a-minute the original defect read as -
        so the floor here is five, wide enough to still catch that class of
        regression."""
        for boss in instanced.FINAL_BOSS:
            got = instanced.kill_seconds(boss)
            assert got is not None and got > 300.0, boss


class TestPlacesComeFromTheExport:
    def test_a_numbered_square_is_resolved_by_its_name(self) -> None:
        """**The hole the name-only frozenset had.** The export files the same
        place under a name *and* a numbered chunk, and only the name was in the
        set - so a map holding `9551` read Tz-Kih as an ordinary monster."""
        info = ChunkInfo(
            {"chunks": {"9551": {"Name": "Fight Caves"}, "1234": {"Name": "Varrock"}}}
        )
        places = instanced.place_ids(info)
        assert "9551" in places
        assert "Fight Caves" in places
        assert "1234" not in places

    def test_the_names_survive_an_empty_export(self) -> None:
        """Degrading to the names alone is the old behaviour, which is wrong
        but not catastrophic; degrading to nothing would make every raid
        monster farmable."""
        assert instanced.place_ids(ChunkInfo({})) == instanced.RUN_ONLY_PLACES

    def test_run_only_needs_every_chunk_to_be_a_run(self) -> None:
        """A lizardman shaman is in the Chambers *and* the Lizardman Temple,
        and the temple is a place you can stand."""
        places = frozenset({"Chambers of Xeric"})
        assert instanced.run_only(["Chambers of Xeric"], places)
        assert not instanced.run_only(
            ["Chambers of Xeric", "Lizardman Temple"], places
        )

    def test_nowhere_is_not_run_only(self) -> None:
        """An empty `where` is a monster nothing placed, not a monster in a
        raid."""
        assert not instanced.run_only([], frozenset({"Inferno"}))


class TestTheBosses:
    def test_a_version_suffix_is_ignored(self) -> None:
        """The export writes `Great Olm#Head`, `#Left claw` and `#Right claw`,
        and killing any of them is the same one raid."""
        for version in ("Great Olm", "Great Olm#Head", "Great Olm#Left claw"):
            assert instanced.place_of_boss(version) == "Chambers of Xeric"
            assert instanced.kill_seconds(version) == instanced.kill_seconds(
                "Great Olm"
            )

    def test_the_raids_spend_their_published_figure(self) -> None:
        assert instanced.kill_seconds("Great Olm") == pytest.approx(
            raids.PUBLISHED_RAID_SECONDS[raids.CHAMBERS]
        )
        assert instanced.kill_seconds("Verzik Vitur") == pytest.approx(
            raids.PUBLISHED_RAID_SECONDS[raids.THEATRE]
        )

    def test_both_tombs_wardens_end_the_same_raid(self) -> None:
        assert instanced.kill_seconds("Tumeken's Warden") == instanced.kill_seconds(
            "Elidinis' Warden"
        )

    def test_the_wave_minigames_defer_to_tzhaar(self) -> None:
        """**One arithmetic, not two.** `tzhaar` owns the Inferno's entry fee,
        so this module asks rather than re-deriving it."""
        for boss in ("TzKal-Zuk", "TzTok-Jad"):
            assert instanced.kill_seconds(boss) == tzhaar.kill_seconds(boss)

    def test_an_ordinary_monster_has_no_opinion(self) -> None:
        assert instanced.place_of_boss("Abyssal demon") is None
        assert instanced.kill_seconds("Abyssal demon") is None

    def test_the_gauntlet_is_priced_by_variant_not_by_place(self) -> None:
        """Both Hunllefs share the one `Gauntlet Lobby` chunk but need
        different durations - `costing/gauntlet.py`'s reason for a
        monster-level dispatch rather than the place-level one every other
        entry here uses."""
        assert "Gauntlet Lobby" in instanced.RUN_ONLY_PLACES
        assert set(
            boss for boss, place in instanced.FINAL_BOSS.items() if place == "Gauntlet Lobby"
        ) == {"Crystalline Hunllef", "Corrupted Hunllef"}
        regular = instanced.kill_seconds("Crystalline Hunllef")
        corrupted = instanced.kill_seconds("Corrupted Hunllef")
        assert regular is not None and corrupted is not None
        # Corrupted carries a regular completion as its published unlock
        # cost, so it must read slower than the regular run alone.
        assert corrupted > regular

    def test_the_rank_and_file_of_a_run_are_refused(self) -> None:
        """Unreachable too, but the cheapest way to reach one is a *partial*
        run and no module here carries the room ordering that would need."""
        for monster in ("Tekton", "Jal-Zek", "Ket-Zek", "Kephri"):
            assert instanced.kill_seconds(monster) is None


@pytest.mark.real_export
class TestAgainstTheRealExport:
    def test_the_export_really_does_alias_these_places(self) -> None:
        """The measurement behind `place_ids`: fourteen numbered squares carry
        an instanced place's `Name`. Quoted as "more than one" rather than
        exactly, because the export grows."""
        info = ChunkInfo(read_chunkinfo())
        numbered = instanced.place_ids(info) - instanced.RUN_ONLY_PLACES
        assert len(numbered) > 5
        # The two this project has already been bitten by.
        names = {
            chunk_id: info.chunks[chunk_id].get("Name") for chunk_id in numbered
        }
        assert "Fight Caves" in names.values()
        assert "Inferno" in names.values()

    def test_every_final_boss_the_export_places_is_inside_its_run(self) -> None:
        """A boss the export also puts somewhere you can stand would make
        `run_only` false for it, and the kill-goal path would be right to
        price it by a rate. None are."""
        info = ChunkInfo(read_chunkinfo())
        places = instanced.place_ids(info)
        where: dict[str, set[str]] = {}
        for chunk_id, body in info.chunks.items():
            if not isinstance(body, dict):
                continue
            for monster in body.get("Monster") or ():
                base = monster.split("#")[0]
                if base in instanced.FINAL_BOSS:
                    where.setdefault(base, set()).add(chunk_id)
        assert where, "the export places no final boss at all - check the branch"
        for boss, chunks in sorted(where.items()):
            assert instanced.run_only(chunks, places), f"{boss}: {sorted(chunks)}"


class TestTheDurationIsTunable:
    """**A run's duration is the one number here nothing publishes**, so it is
    the one most worth letting somebody correct - `runs` in
    `heuristics/overrides.json` or a map's own file.
    """

    def test_an_override_wins(self) -> None:
        got = instanced.run_seconds("Inferno", {"Inferno": 1800.0})
        assert got == pytest.approx(1800.0)

    def test_no_override_is_the_models_own_figure(self) -> None:
        assert instanced.run_seconds("Inferno", {}) == pytest.approx(
            tzhaar.RUN_SECONDS[tzhaar.INFERNO]
        )
        assert instanced.run_seconds("Chambers of Xeric", {}) == pytest.approx(
            instanced.DEFAULT_RUN_SECONDS["Chambers of Xeric"]
        )

    def test_a_nonsense_override_is_ignored(self) -> None:
        """Zero and negative are refused rather than believed - a run taking
        no time would divide the pet's expectation to nothing."""
        for bad in (0.0, -60.0):
            assert instanced.run_seconds("Inferno", {"Inferno": bad}) == pytest.approx(
                tzhaar.RUN_SECONDS[tzhaar.INFERNO]
            )

    def test_the_override_reaches_the_boss_kill(self) -> None:
        """The point of the funnel: one correction moves every answer that
        spends a run."""
        overrides = {"Inferno": 1800.0, "Fight Caves": 1200.0}
        assert instanced.kill_seconds("TzKal-Zuk", overrides) == pytest.approx(
            1800.0 + 1200.0
        )

    def test_the_knob_path_is_spelled_in_one_place(self) -> None:
        assert instanced.knob_for("Inferno") == "runs/Inferno"
        assert instanced.KNOB_BRANCH == "runs"

    def test_the_branch_is_writable_config(self) -> None:
        """A knob the panel offers must name a branch `heuristics.load`
        actually reads, or the write lands somewhere nothing loads."""
        from chunksim.costing.heuristics import CONFIG_BRANCHES

        assert instanced.KNOB_BRANCH in CONFIG_BRANCHES

    def test_the_panel_resolves_every_run_knob(self) -> None:
        """**What the old `actions/Inferno` failed.** Every place this project
        prices must resolve to its real duration, not to a fallback."""
        from chunksim.costing.heuristics import Heuristics
        from chunksim.gui import knobs

        heuristics = Heuristics()
        for place in instanced.DEFAULT_RUN_SECONDS:
            got = knobs.effective(instanced.knob_for(place), heuristics)
            # See `test_no_final_boss_is_cheaper_than_five_minutes` on why
            # this is 300 rather than 600 - the Gauntlet's own regular run
            # publishes at 514 seconds.
            assert got is not None and got > 300.0, place
