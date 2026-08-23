"""Trimming the sails: 120 trims an hour at the tier's own published payout."""

from __future__ import annotations

import pathlib

import pytest

from chunksim.costing import sailtrim
from chunksim.costing.gathering import CONFIRMED
from chunksim.model.chunkinfo import ChunkInfo

_BY_TIER = {mast.tier: mast for mast in sailtrim.MASTS}


def _valid(*tiers: str) -> dict[str, dict[str, object]]:
    """A valid set holding the trim challenge and the named tiers' builds."""
    builds: dict[str, object] = {}
    for tier in tiers:
        task = _BY_TIER[tier].build_task
        if task is not None:
            builds[task] = {"Skills": {"Sailing": _BY_TIER[tier].published_level}}
    return {
        "Sailing": {sailtrim.TRIM_TASK: {}},
        "Construction": builds,
    }


class TestTheCadenceIsTheWholeModel:
    def test_a_trim_every_thirty_seconds_is_a_hundred_and_twenty_an_hour(
        self,
    ) -> None:
        """`Mast and sails` states the interval in its opening paragraph and
        the payout in a column; the rate is the two multiplied."""
        assert sailtrim.TRIM_SECONDS == 30.0
        for mast in sailtrim.MASTS:
            assert mast.xp_per_hour == pytest.approx(mast.trim_experience * 120)

    def test_the_seven_tiers_read_as_the_page_tabulates_them(self) -> None:
        assert [m.trim_experience for m in sailtrim.MASTS] == [
            10.5,
            19.5,
            30.0,
            48.0,
            64.0,
            80.0,
            125.0,
        ]

    def test_the_quest_raft_is_the_floor_and_rosewood_the_ceiling(self) -> None:
        assert _BY_TIER["wooden"].xp_per_hour == 1_260.0
        assert _BY_TIER["rosewood"].xp_per_hour == 15_000.0

    def test_a_tier_is_flat_because_a_trim_pays_the_same_at_every_level(
        self,
    ) -> None:
        """What a level buys here is a *better mast*, not a better trim - so
        each tier is one band rather than a curve, and the climb reads as
        seven steps."""
        bands = sailtrim.methods(_valid(*_BY_TIER))["Sailing"]
        assert len(bands) == len(sailtrim.MASTS)
        assert len({b.level for b in bands}) == len(sailtrim.MASTS)


class TestTheLevelIsTheBuildsAndUpstreamStatesIt:
    def test_upstreams_own_skills_entry_wins(self) -> None:
        """Read off the build challenge rather than compared here, so the
        no-map census cannot report a priced method as unpriced."""
        valid = _valid("oak")
        valid["Construction"]["Build an ~|oak mast and linen sails|~"] = {
            "Skills": {"Sailing": 30}
        }
        (band,) = [
            b for b in sailtrim.methods(valid)["Sailing"] if "oak" in b.method
        ]
        assert band.level == 30

    def test_the_published_column_is_the_fallback(self) -> None:
        """A build challenge stating no `Skills` leaves the wiki's own column,
        which is what the two are asserted to agree on below."""
        valid = _valid("teak")
        valid["Construction"]["Build a ~|teak mast and canvas sails|~"] = {}
        (band,) = [
            b for b in sailtrim.methods(valid)["Sailing"] if "teak" in b.method
        ]
        assert band.level == _BY_TIER["teak"].published_level == 36

    @pytest.mark.real_export
    def test_upstream_and_the_wiki_agree_on_all_seven(
        self, real_export: ChunkInfo
    ) -> None:
        """**A cross-source check rather than a restatement.** The wiki's
        `Sailing Level` column and upstream's `Skills: {"Sailing": N}` are
        written by different people from different data, and they agree on
        every tier - which is what lets `methods` prefer upstream's without
        the model changing."""
        builds = real_export.challenges.get("Construction") or {}
        for mast in sailtrim.MASTS:
            task = mast.build_task or sailtrim.WOODEN_BUILD_TASK
            challenge = builds.get(task)
            assert isinstance(challenge, dict), f"upstream lost {task}"
            assert challenge["Skills"]["Sailing"] == mast.published_level


class TestWhatGatesEachTier:
    def test_nothing_at_all_without_a_boat(self) -> None:
        """Upstream's trim challenge asks for `AnyBoat[+]`, so its validity is
        the statement that this map can trim anything."""
        assert sailtrim.methods({}) == {}
        assert sailtrim.methods({"Construction": {}}) == {}

    def test_the_wooden_tier_needs_no_build_challenge(self) -> None:
        """It is what the Pandemonium raft arrives carrying, which is why
        `Sailing training` quotes 10.5 a trim for a player who has just
        finished the quest."""
        bands = sailtrim.methods({"Sailing": {sailtrim.TRIM_TASK: {}}})["Sailing"]
        assert [b.method for b in bands] == ["trimming wooden sails"]

    def test_a_higher_tier_needs_its_own_build(self) -> None:
        """The mast has to exist before it can be trimmed, and upstream's
        build challenge is the statement that this map could make one."""
        bands = sailtrim.methods(_valid("oak", "camphor"))["Sailing"]
        assert [b.method for b in bands] == [
            "trimming wooden sails",
            "trimming oak sails",
            "trimming camphor sails",
        ]

    def test_every_band_lands_on_the_one_challenge_upstream_carries(self) -> None:
        """Upstream does not distinguish the tiers, so a band emitted anywhere
        else would leave the trim challenge reading `unpriced`."""
        bands = sailtrim.methods(_valid(*_BY_TIER))["Sailing"]
        assert {b.knob for b in bands} == {
            f"training/{sailtrim.TRIM_TASK}/Sailing"
        }


class TestNothingHereIsInvented:
    def test_every_band_is_confirmed(self) -> None:
        """The cadence, the seven payouts and the seven levels are all
        published. It is a ceiling - an hour at sea taking every gust - but a
        ceiling with no invented number in it, which is
        `costing/blastfurnace.py`'s standing."""
        bands = sailtrim.methods(_valid(*_BY_TIER))["Sailing"]
        assert {b.match for b in bands} == {CONFIRMED}


class TestItIsWiredIn:
    def test_inputs_calls_it(self) -> None:
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "sailtrim.methods(" in source

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = (
            pathlib.Path(sailtrim.__file__)
            .with_name("__init__.py")
            .read_text(encoding="utf-8")
        )
        assert "`sailtrim.py`" in listing
