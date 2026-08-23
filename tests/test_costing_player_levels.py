"""Three layers deciding a skill's level, and the floor none of them may cross."""

from __future__ import annotations

from pathlib import Path

import pytest

from chunksim.costing import levels as L
from chunksim.model.experience import MAX_SKILL_LEVEL, xp_for_level
from chunksim.store import cache


class _State:
    """The two branches `infer_levels` reads, and nothing else."""

    def __init__(self, passive: dict[str, int]) -> None:
        self.passive_skill = passive
        self.completed_challenges: dict[str, dict[str, bool]] = {}

        class _Info:
            challenges: dict[str, dict[str, object]] = {}

        self.chunk_info = _Info()


def _state(**passive: int) -> object:
    return _State(dict(passive))


class TestTheOrdering:
    def test_the_floor_answers_when_nothing_else_does(self) -> None:
        found = L.resolve_levels(_state(Attack=70))  # type: ignore[arg-type]
        assert found["Attack"] == L.SkillLevel(70, L.FLOOR, 70, 0)

    def test_a_linked_account_beats_the_floor(self) -> None:
        found = L.resolve_levels(
            _state(Attack=70), linked_experience={"Attack": xp_for_level(90)}  # type: ignore[arg-type]
        )
        assert found["Attack"].level == 90
        assert found["Attack"].source == L.LINKED

    def test_experience_set_by_hand_beats_a_linked_account(self) -> None:
        """Most specific first: what a person typed for this map wins."""
        found = L.resolve_levels(
            _state(Attack=70),  # type: ignore[arg-type]
            linked_experience={"Attack": xp_for_level(90)},
            set_experience={"Attack": xp_for_level(95)},
        )
        assert found["Attack"].level == 95
        assert found["Attack"].source == L.SET


class TestNoLayerMayLower:
    def test_a_linked_account_below_the_floor_is_refused_and_named(self) -> None:
        """**A floor is a proof.** A ticked `Buy the ~|Defence cape|~` is 99
        Defence whatever an account says - and the usual cause of a real
        disagreement is a *boosted* completion, which proves the boosted level
        rather than the base one. Reported rather than quietly raised, because
        silently agreeing with a number you refused is the worse failure."""
        found = L.resolve_levels(
            _state(Fishing=85), linked_experience={"Fishing": xp_for_level(80)}  # type: ignore[arg-type]
        )
        assert found["Fishing"].level == 85
        assert found["Fishing"].source == L.BELOW_FLOOR
        assert found["Fishing"].floor == 85

    def test_a_hand_set_figure_below_the_floor_is_refused_too(self) -> None:
        found = L.resolve_levels(
            _state(Attack=70), set_experience={"Attack": 0}  # type: ignore[arg-type]
        )
        assert found["Attack"].level == 70
        assert found["Attack"].source == L.BELOW_FLOOR

    def test_a_hand_set_level_override_raises_the_floor_itself(self) -> None:
        """`overrides.json`'s levels are part of what this project answered
        with before an account could be linked, so they are the floor rather
        than a layer over it."""
        found = L.resolve_levels(
            _state(Attack=70), {"Attack": 80}  # type: ignore[arg-type]
        )
        assert found["Attack"].level == 80 and found["Attack"].floor == 80


class TestTheSkillCeiling:
    def test_a_skill_stops_at_ninety_nine(self) -> None:
        """`level_for_xp` is the curve's inverse and the curve runs to 126
        because it also answers for Combat level - so 30m Strength reads 107
        unless this clamps."""
        found = L.resolve_levels(
            _state(Strength=70), linked_experience={"Strength": 30_000_000}  # type: ignore[arg-type]
        )
        assert found["Strength"].level == MAX_SKILL_LEVEL == 99


class TestTheStore:
    def test_a_round_trip_keeps_both_kinds_of_experience(self, tmp_path: Path) -> None:
        cache.write_player(
            "fray", "canifischunk", {"Attack": 100}, {"Magic": 200}, "now", tmp_path
        )
        found = cache.read_player("fray", tmp_path)
        assert found["rsn"] == "canifischunk"
        assert found["linked_xp"] == {"Attack": 100}
        assert found["xp"] == {"Magic": 200}

    def test_unlinking_removes_the_file(self, tmp_path: Path) -> None:
        """"Unlinked" is the absence the reader already treats as the default
        rather than a second way of saying it."""
        cache.write_player("fray", "someone", {"Attack": 1}, root=tmp_path)
        cache.write_player("fray", "", {}, {}, "", tmp_path)
        assert not cache.player_path("fray", tmp_path).exists()
        assert cache.read_player("fray", tmp_path) == {}

    def test_a_map_id_with_a_run_mirrors_the_path(self, tmp_path: Path) -> None:
        path = cache.player_path("batch/run-001", tmp_path)
        assert path.relative_to(tmp_path).as_posix() == (
            "cache/players/batch/run-001.json"
        )

    def test_a_corrupt_file_degrades_to_the_floor(self, tmp_path: Path) -> None:
        """A link is a convenience laid over an answer this project can
        already give."""
        path = cache.player_path("fray", tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        assert cache.read_player("fray", tmp_path) == {}

class TestInheritance:
    """A map made from another one is played by the same person."""

    def test_a_run_reads_its_batch_s_account(self, tmp_path: Path) -> None:
        cache.write_player("batch", "someone", {"Attack": 100}, root=tmp_path)
        assert cache.read_player("batch/run-003", tmp_path)["rsn"] == "someone"

    def test_a_run_s_own_file_shadows_the_batch_s(self, tmp_path: Path) -> None:
        cache.write_player("batch", "someone", {"Attack": 100}, root=tmp_path)
        cache.write_player("batch/run-003", "somebody", {"Attack": 200}, root=tmp_path)
        assert cache.read_player("batch/run-003", tmp_path)["rsn"] == "somebody"
        assert cache.read_player("batch/run-004", tmp_path)["rsn"] == "someone"

    def test_copying_carries_the_link_to_a_new_map(self, tmp_path: Path) -> None:
        cache.write_player("fray", "someone", {"Attack": 100}, root=tmp_path)
        assert cache.copy_player("fray", "fray-sim", tmp_path) is not None
        assert cache.read_player("fray-sim", tmp_path)["linked_xp"] == {"Attack": 100}

    def test_copying_follows_a_run_up_to_its_batch(self, tmp_path: Path) -> None:
        """A snapshot of `batch/run-003` is played by whoever the batch is."""
        cache.write_player("batch", "someone", {"Attack": 100}, root=tmp_path)
        assert cache.copy_player("batch/run-003", "snap", tmp_path) is not None
        assert cache.read_player("snap", tmp_path)["rsn"] == "someone"

    def test_copying_never_overwrites(self, tmp_path: Path) -> None:
        """A `replace` Commit must not undo the link made on the copy."""
        cache.write_player("fray", "someone", {"Attack": 100}, root=tmp_path)
        cache.write_player("fray-edit", "somebody", {"Attack": 200}, root=tmp_path)
        assert cache.copy_player("fray", "fray-edit", tmp_path) is None
        assert cache.read_player("fray-edit", tmp_path)["rsn"] == "somebody"

    def test_copying_nothing_writes_nothing(self, tmp_path: Path) -> None:
        assert cache.copy_player("fray", "fray-sim", tmp_path) is None
        assert not cache.player_path("fray-sim", tmp_path).exists()

    def test_both_files_a_run_resolves_through_are_stamped(self, tmp_path: Path) -> None:
        """Linking on a batch has to move the stamp its runs are drawn from,
        or every panel keeps the levels it had before."""
        before = cache.reference_stamp(tmp_path, "batch/run-003")
        cache.write_player("batch", "someone", {"Attack": 100}, root=tmp_path)
        assert cache.reference_stamp(tmp_path, "batch/run-003") != before


class TestRemoval:
    """A name is reclaimable, so what was keyed by it goes with it."""

    def test_removing_a_map_takes_its_link_with_it(self, tmp_path: Path) -> None:
        cache.write_cache("fray", {"chunks": {}}, tmp_path)
        cache.write_player("fray", "someone", {"Attack": 100}, root=tmp_path)
        cache.remove_map("fray", tmp_path, include_fetched=True)
        assert cache.read_player("fray", tmp_path) == {}

    def test_removing_a_batch_takes_its_runs_files_too(self, tmp_path: Path) -> None:
        directory = cache.claim_sim_batch("batch", tmp_path)
        cache.write_sim_run(
            cache.run_dir(directory, 1),
            map_id="batch/run-001",
            data={"chunks": {}},
            simulation={},
            ledger=[],
        )
        cache.write_player("batch", "someone", {"Attack": 100}, root=tmp_path)
        cache.write_player("batch/run-001", "somebody", {"Attack": 2}, root=tmp_path)
        cache.remove_map("batch", tmp_path)
        assert cache.read_player("batch/run-001", tmp_path) == {}


class TestThePricingKey:
    def test_a_run_s_key_follows_the_file_it_reads(self, tmp_path: Path) -> None:
        """**Keyed on the run's own path, every simulated map digested an
        empty input** - so linking an account served back the answer computed
        at the floor, to the person who had just linked it."""
        from chunksim.store import derived_cache

        before = derived_cache.pricing_digests(tmp_path, "batch/run-001").player
        cache.write_player("batch", "someone", {"Attack": 100}, root=tmp_path)
        after = derived_cache.pricing_digests(tmp_path, "batch/run-001").player
        assert before == ""
        assert after and after != before

    def test_it_is_in_the_pricing_key(self) -> None:
        """**Without it a fresh link served the answer computed against the
        floor**, which is the one failure a cache key exists to prevent."""
        from chunksim.store import derived_cache

        assert "player" in {
            field.name for field in derived_cache.PricingDigests.__dataclass_fields__.values()
        }
