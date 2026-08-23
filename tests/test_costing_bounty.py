"""Bounty tasks: damage is experience, and the hand-in is most of the rate."""

from __future__ import annotations

import pathlib
from typing import Any

import pytest

from chunksim.costing import bounty, courier
from chunksim.costing.gathering import GUESS
from chunksim.model.chunkinfo import ChunkInfo

_BLOB: dict[str, Any] = {
    "tasks": [
        {"level": 30, "experience": 10_000, "notice_board": "Alpha",
         "monster": "Tern", "item": "Tern beak", "quantity": 5,
         "rarity": "1/10"},
        {"level": 30, "experience": 10_000, "notice_board": "Alpha",
         "monster": "Tern", "item": "Tern feather", "quantity": 20,
         "rarity": "1/2"},
        {"level": 80, "experience": 40_000, "notice_board": "Alpha",
         "monster": "Orca", "item": "Orca tooth", "quantity": 5,
         "rarity": "1/10"},
        {"level": 30, "experience": 99_000, "notice_board": "Nowhere",
         "monster": "Tern", "item": "Tern eye", "quantity": 1,
         "rarity": "1/2"},
    ],
    "hitpoints": {"Tern": 22, "Orca": 370},
}
_COURIER: dict[str, Any] = {
    "ports": {"Alpha": {"chunk": "1000", "x": 0, "y": 0, "board": True}},
    "tasks": [],
}
_OCEAN = [str(1000 + n) for n in range(5)]
_CHUNKS: dict[str, Any] = {
    "1002": {"Monster": {"Tern": 3}},
    "1004": {"Sections": {"W1": {"Monster": {"Orca": 1}}}},
}
_HELD = {chunk: True for chunk in _OCEAN}
_VALID: dict[str, dict[str, object]] = {
    "Sailing": {bounty.TASK: {}, courier.BOARD_TASK.format(port="Alpha"): {}}
}
_KPH = {"Tern": 720.0, "Orca": 90.0}


def _methods(**kw: Any) -> dict[str, tuple[Any, ...]]:
    args: dict[str, Any] = {
        "valid": _VALID, "derived_monsters": ["Tern", "Orca"], "chunks": _CHUNKS,
        "held": _HELD, "ocean": _OCEAN, "sections": {},
        "courier_blob": _COURIER, "bounty_blob": _BLOB, "kills_per_hour": _KPH,
    }
    args.update(kw)
    return bounty.methods(**args)


class TestTheArithmetic:
    def test_damage_is_experience(self) -> None:
        """`Boat combat`: one Sailing experience a point of damage. So a kill
        is worth the monster's hitpoints before the bounty pays anything."""
        assert bounty.XP_PER_DAMAGE == 1.0
        hunt = bounty.Hunt(
            monster="Tern", hitpoints=22, hops=0,
            tasks=bounty.bounties_from(_BLOB)[:1], player_dps=10.0,
        )
        assert hunt.kills == 50.0
        assert hunt.experience == 50 * 22 + 10_000

    def test_the_hand_in_dominates_the_damage(self) -> None:
        """Which is what makes this a training method rather than an hour of
        shooting things: 1,100 of damage against a 10,000 bounty."""
        hunt = bounty.Hunt(
            monster="Tern", hitpoints=22, hops=0,
            tasks=bounty.bounties_from(_BLOB)[:1], player_dps=10.0,
        )
        assert hunt.kills * hunt.hitpoints < sum(t.experience for t in hunt.tasks)

    def test_stacking_is_sequential_rather_than_parallel(self) -> None:
        """**The trap.** Since 17 June 2026 a kill rolls one bounty item, so
        two tasks cost the sum of their kills, not the larger. Taking the
        maximum would roughly halve every figure here."""
        both = bounty.bounties_from(_BLOB)[:2]
        hunt = bounty.Hunt("Tern", 22, 0, both, player_dps=10.0)
        assert hunt.kills == 50.0 + 40.0
        assert hunt.kills != max(t.kills for t in both)

    def test_the_sail_is_charged_both_ways(self) -> None:
        near = bounty.Hunt("Tern", 22, 0, bounty.bounties_from(_BLOB)[:1], 10.0)
        far = bounty.Hunt("Tern", 22, 5, bounty.bounties_from(_BLOB)[:1], 10.0)
        assert far.seconds - near.seconds == 2 * 5 * courier.SECONDS_PER_HOP

    def test_the_cannon_constant_fitted_to_zero(self) -> None:
        """**Kept as a named term rather than deleted.** `kills_per_hour` is a
        wall-clock rate carrying banking and respawn that boat combat has
        neither of, so the overhead it charges and the crew's damage are the
        same size and cancel. Nothing here can separate them."""
        assert bounty.CANNON_DPS == 0.0


class TestWhatIsHeld:
    def test_slots_open_where_the_page_says(self) -> None:
        assert bounty.slots_at(29) == 0
        assert bounty.slots_at(30) == 3
        assert bounty.slots_at(56) == 4
        assert bounty.slots_at(84) == 5

    def test_one_task_per_distinct_item(self) -> None:
        """Two bounties for the same drop cannot be held at once."""
        rows = bounty.bounties_from(_BLOB)
        same = [rows[0], rows[0]]
        assert len(bounty._chosen(same, 99)) == 1

    def test_the_fewest_kills_are_taken_first(self) -> None:
        chosen = bounty._chosen(list(bounty.bounties_from(_BLOB))[:2], 30)
        assert [t.item for t in chosen] == ["Tern feather", "Tern beak"]


class TestGating:
    def test_a_monster_the_map_lacks_is_not_hunted(self) -> None:
        bands = _methods(derived_monsters=["Tern"])["Sailing"]
        assert all("Orca" not in band.method for band in bands)

    def test_a_monster_with_no_sea_route_is_not_hunted(self) -> None:
        """**The chunks in between.** Upstream gates on a port and a monster
        and says nothing about the water; this is stricter, deliberately."""
        held = {chunk: True for chunk in _OCEAN if chunk != "1003"}
        bands = _methods(held=held)["Sailing"]
        assert all("Orca" not in band.method for band in bands)

    def test_a_bounty_from_an_unreachable_board_is_never_offered(self) -> None:
        """A bounty is taken at a board, so one offered only where this map
        cannot go must change nothing. The fixture's `Nowhere` row is the
        richest on the table, which is what makes its absence visible."""
        without = dict(_BLOB)
        without["tasks"] = [
            row for row in _BLOB["tasks"] if row["notice_board"] != "Nowhere"
        ]
        assert [b.xp_per_hour for b in _methods()["Sailing"]] == [
            b.xp_per_hour for b in _methods(bounty_blob=without)["Sailing"]
        ]

    def test_nothing_without_upstreams_challenge(self) -> None:
        assert _methods(valid={"Sailing": {}}) == {}

    def test_nothing_without_a_board(self) -> None:
        assert _methods(valid={"Sailing": {bounty.TASK: {}}}) == {}

    def test_nothing_without_the_scrape(self) -> None:
        assert _methods(bounty_blob={}) == {}

    def test_the_monster_alias_runs_one_way(self) -> None:
        """The wiki's bounty table says `Mogre (sea)` and the export says
        `Mogre (Sailing)`; the table takes the first to the second."""
        assert bounty.MONSTER_ALIASES["Mogre (sea)"] == "Mogre (Sailing)"


class TestTheBands:
    def test_bands_open_where_the_best_hunt_improves(self) -> None:
        bands = _methods()["Sailing"]
        assert [b.level for b in bands][0] == 30
        assert {b.match for b in bands} == {GUESS}
        assert {b.knob for b in bands} == {f"training/{bounty.TASK}/Sailing"}

    def test_a_monster_is_found_in_a_section_as_well_as_a_chunk(self) -> None:
        placed = bounty.monster_chunks(_CHUNKS)
        assert placed["Tern"] == frozenset({"1002"})
        assert placed["Orca"] == frozenset({"1004"})


@pytest.mark.real_export
class TestAgainstTheRealTables:
    def test_every_bounty_monster_upstream_names_is_in_the_table(
        self, real_export: ChunkInfo
    ) -> None:
        """`BountyMonster[+]` and the wiki's table are two vocabularies for one
        set, and `MONSTER_ALIASES` is what reconciles them. A miss here is a
        monster silently priced at nothing."""
        from chunksim.store import cache

        blob = cache.read_blob(cache.BOUNTY_BLOB_NAME)["data"]
        family = real_export.code_items["monstersPlus"]["BountyMonster[+]"]
        named = {
            bounty.MONSTER_ALIASES.get(row["monster"], row["monster"])
            for row in blob["tasks"]
        }
        assert named == set(family)

    def test_the_rate_lands_between_trials_and_salvaging(
        self, real_export: ChunkInfo
    ) -> None:
        """**The only published check, and the whole calibration.** `Sailing
        training` says bounty tasks are "a middle ground between salvaging and
        trials, with optimal rates in-between the two", which is why
        `CANNON_DPS` is zero: five damage a second of crew puts the ceiling map
        at 211,027, outside the band on the wrong side."""
        from chunksim.store import cache

        blob = cache.read_blob(cache.BOUNTY_BLOB_NAME)["data"]
        rows = bounty.bounties_from(blob)
        health = bounty.hitpoints_from(blob)
        assert rows and health
        # A generous stand-in for a complete map: every monster reachable,
        # every board three hops away.
        family = real_export.code_items["monstersPlus"]["BountyMonster[+]"]
        hunts = bounty.hunts_for(
            rows, health, family, bounty.monster_chunks(real_export.chunks),
            {"board": {chunk: 3 for chunk in real_export.chunks}},
            {name: 120.0 for name in family}, 99,
        )
        assert hunts
        best = max(h.xp_per_hour for h in hunts)
        assert 80_000 < best < 200_000, best


class TestItIsWiredIn:
    def test_inputs_calls_it_after_the_dps_enrichment(self) -> None:
        """**Order is load-bearing.** Before `enrich` the kill rates are
        `DEFAULT_KPH`, so boat combat would price off a stand-in and throw the
        simulated answer away."""
        from chunksim.costing import inputs

        source = pathlib.Path(inputs.__file__).read_text(encoding="utf-8")
        assert "bounty.methods(" in source
        assert source.index("dps_bridge.enrich(") < source.index("bounty.methods(")

    def test_the_module_is_listed_where_a_module_is_listed(self) -> None:
        listing = (
            pathlib.Path(bounty.__file__)
            .with_name("__init__.py")
            .read_text(encoding="utf-8")
        )
        assert "`bounty.py`" in listing
