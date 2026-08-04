"""Tests for the on-disk derivation cache.

The one that matters is `a hit and a miss are the same derivation` - everything
else here guards the ways a cache can be silently wrong (a stale key that still
loads, a corrupt entry raising instead of missing) rather than merely slow.
"""

from __future__ import annotations

import dataclasses
import pickle
from pathlib import Path
from typing import Any

import pytest

from fray_claude.chunkinfo import ChunkInfo
from fray_claude.derived_cache import (
    CacheBehaviour,
    Digests,
    RollCache,
    _structure_digest,
    cached_derive,
    decode,
    derivation_key,
    encode,
)
from fray_claude.pipeline import MapState, derive

_DIGESTS = Digests(chunkinfo="abc123", tasks_map="def456")


def _chunk_info(**data: Any) -> ChunkInfo:
    return ChunkInfo(data)


def _state(**overrides: Any) -> MapState:
    defaults: dict[str, Any] = {
        "chunk_info": _chunk_info(
            chunks={"100": {"Monster": {"Goblin": True}}},
            drops={"Goblin": {"Bones": {"1": "Always"}}},
            challenges={"Prayer": {"Bury bones": {"Items": ["Bones"], "Level": 1}}},
        ),
        "rules": {},
        "settings": {},
        "manual_sections": {},
        "manual_areas": {},
        "manual_monsters": {},
        "manual_equipment": {},
        "backlogged_sources": {},
        "max_skill": {},
        "passive_skill": {},
        "completed_challenges": {},
        "checked_challenges": {},
        "manual_tasks": {},
        "backlog": {},
        "active_tasks": {},
    }
    defaults.update(overrides)
    return MapState(**defaults)


def _entries(root: Path) -> list[Path]:
    directory = root / "cache" / "derived"
    return sorted(directory.iterdir()) if directory.is_dir() else []


def test_a_hit_and_a_miss_are_the_same_derivation(tmp_path: Path) -> None:
    """The whole point: reading the cache must be indistinguishable from
    computing, or the cache is a bug generator."""
    state, unlocked = _state(), {"100": True}
    expected = derive(state, unlocked)

    miss = cached_derive(state, unlocked, _DIGESTS, root=tmp_path)
    hit = cached_derive(state, unlocked, _DIGESTS, root=tmp_path)

    assert len(_entries(tmp_path)) == 1
    for result in (miss, hit):
        assert result.reachable_sections == expected.reachable_sections
        assert result.challenges.as_dict() == expected.challenges.as_dict()
        assert result.source_index.items == expected.source_index.items
        assert result.bis.picks == expected.bis.picks
        assert result.task_classification.as_dict() == expected.task_classification.as_dict()
        assert result.other_tasks.as_dict() == expected.other_tasks.as_dict()


def test_encoding_round_trips_every_field(tmp_path: Path) -> None:
    derived = derive(_state(), {"100": True})

    restored = decode(encode(derived))

    assert restored is not None
    for field in dataclasses.fields(derived):
        original = getattr(derived, field.name)
        copy = getattr(restored, field.name)
        assert (copy.as_dict() if hasattr(copy, "as_dict") else copy) == (
            original.as_dict() if hasattr(original, "as_dict") else original
        )


def test_the_same_inputs_produce_the_same_key() -> None:
    """Determinism across processes is what lets parallel workers share
    entries without coordinating."""
    assert derivation_key(_state(), {"100": True}, _DIGESTS) == derivation_key(
        _state(), {"100": True}, _DIGESTS
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rules", {"F2P": True}),
        ("settings", {"optOutSections": True}),
        ("max_skill", {"Mining": 70}),
        ("passive_skill", {"Mining": 10}),
        ("completed_challenges", {"Prayer": {"Bury bones": True}}),
        ("checked_challenges", {"Prayer": {"Bury bones": True}}),
        ("manual_tasks", {"Prayer": {"Bury bones": True}}),
        ("manual_areas", {"Zanaris": True}),
        ("manual_sections", {"100": {"1": True}}),
        ("manual_monsters", {"Goblin": True}),
        ("manual_equipment", {"Bronze axe": True}),
        ("backlogged_sources", {"Bones": True}),
        ("backlog", {"Prayer": {"Bury bones": True}}),
        ("construction_locked", True),
    ],
)
def test_any_change_to_the_state_changes_the_key(field: str, value: Any) -> None:
    base = derivation_key(_state(), {"100": True}, _DIGESTS)

    assert derivation_key(_state(**{field: value}), {"100": True}, _DIGESTS) != base


def test_a_different_unlocked_set_changes_the_key() -> None:
    """`unlock` and `simulate` derive states the map itself never had."""
    base = derivation_key(_state(), {"100": True}, _DIGESTS)

    assert derivation_key(_state(), {"100": True, "101": True}, _DIGESTS) != base
    # Order is not identity: the same set keyed either way is the same state.
    assert derivation_key(_state(), {"101": True, "100": True}, _DIGESTS) == derivation_key(
        _state(), {"100": True, "101": True}, _DIGESTS
    )


@pytest.mark.parametrize("digests", [Digests("other", "def456"), Digests("abc123", "other")])
def test_new_reference_data_changes_the_key(digests: Digests) -> None:
    """A re-run `fray chunkinfo` must not be served last week's answer."""
    assert derivation_key(_state(), {"100": True}, digests) != derivation_key(
        _state(), {"100": True}, _DIGESTS
    )


def test_the_structural_digest_tracks_the_result_classes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adding a field to any result dataclass must strand old entries rather
    than unpickle them into an object missing an attribute."""
    before = _structure_digest()

    @dataclasses.dataclass(frozen=True)
    class Extended:
        picks: dict[str, str]
        surprise: int

    monkeypatch.setattr("fray_claude.derived_cache._RESULT_TYPES", (Extended,))

    assert _structure_digest() != before


@pytest.mark.parametrize(
    "blob",
    [b"", b"not a pickle at all", b"\x28\xb5\x2f\xfd\x00", pickle.dumps({"not": "derived"})],
)
def test_an_unusable_entry_reads_as_a_miss(blob: bytes) -> None:
    """Truncated, corrupt, foreign or simply the wrong object - every one of
    them means recompute, and none of them means raise."""
    assert decode(blob) is None


def test_a_corrupt_entry_is_recomputed_and_replaced(tmp_path: Path) -> None:
    state, unlocked = _state(), {"100": True}
    cached_derive(state, unlocked, _DIGESTS, root=tmp_path)
    entry = _entries(tmp_path)[0]
    entry.write_bytes(b"shredded")

    result = cached_derive(state, unlocked, _DIGESTS, root=tmp_path)

    assert result.challenges.valid == derive(state, unlocked).challenges.valid
    assert entry.read_bytes() != b"shredded"


def test_refresh_ignores_a_stored_entry_and_rewrites_it(tmp_path: Path) -> None:
    state, unlocked = _state(), {"100": True}
    cached_derive(state, unlocked, _DIGESTS, root=tmp_path)
    entry = _entries(tmp_path)[0]
    entry.write_bytes(encode(derive(_state(rules={"F2P": True}), {})))

    refreshed = cached_derive(state, unlocked, _DIGESTS, root=tmp_path, refresh=True)

    assert refreshed.challenges.valid == derive(state, unlocked).challenges.valid
    assert decode(entry.read_bytes()) is not None


def test_store_off_computes_without_writing(tmp_path: Path) -> None:
    """How `simulate` keeps its per-roll states out of the cache."""
    result = cached_derive(_state(), {"100": True}, _DIGESTS, root=tmp_path, store=False)

    assert result.challenges.valid == derive(_state(), {"100": True}).challenges.valid
    assert _entries(tmp_path) == []


def test_store_off_still_reads_an_existing_entry(tmp_path: Path) -> None:
    state, unlocked = _state(), {"100": True}
    cached_derive(state, unlocked, _DIGESTS, root=tmp_path)

    result = cached_derive(state, unlocked, _DIGESTS, root=tmp_path, store=False)

    assert len(_entries(tmp_path)) == 1
    assert result.challenges.valid == derive(state, unlocked).challenges.valid


# --- which of a simulation's states are kept ---------------------------------


def _roll_cache(behaviour: CacheBehaviour, root: Path) -> RollCache:
    return RollCache(_DIGESTS, behaviour, root)


def test_all_keeps_every_state_it_derives(tmp_path: Path) -> None:
    cache = _roll_cache(CacheBehaviour.ALL, tmp_path)
    state = _state()

    cache.derive_state(state, {"100": True}, start=True)
    cache.derive_state(state, {"100": True, "101": True}, start=False)

    assert len(_entries(tmp_path)) == 2


def test_extremities_keeps_the_start_but_not_what_it_passes_through(tmp_path: Path) -> None:
    cache = _roll_cache(CacheBehaviour.EXTREMITIES, tmp_path)
    state = _state()

    cache.derive_state(state, {"100": True}, start=True)
    cache.derive_state(state, {"100": True, "101": True}, start=False)

    assert len(_entries(tmp_path)) == 1


def test_extremities_keeps_the_state_the_run_finished_on(tmp_path: Path) -> None:
    """`keep_final` exists because a run's last roll is only identifiable after
    the loop - it ends at `rolls` or at the first empty pool, and the second is
    a whole iteration late."""
    cache = _roll_cache(CacheBehaviour.EXTREMITIES, tmp_path)
    state, final = _state(), {"100": True, "101": True}
    derived = cache.derive_state(state, final, start=False)
    assert _entries(tmp_path) == []

    cache.keep_final(state, final, derived)

    key = derivation_key(state, final, _DIGESTS)
    assert [path.name for path in _entries(tmp_path)] == [key]


def test_none_keeps_nothing_at_all(tmp_path: Path) -> None:
    cache = _roll_cache(CacheBehaviour.NONE, tmp_path)
    state = _state()

    derived = cache.derive_state(state, {"100": True}, start=True)
    cache.keep_final(state, {"100": True}, derived)

    assert _entries(tmp_path) == []


def test_none_does_not_read_the_cache_either(tmp_path: Path) -> None:
    """"None" means "don't touch it", not "no new entries" - so a stored answer
    is not consulted, which is also why it is the slowest setting."""
    state, unlocked = _state(), {"100": True}
    cached_derive(state, unlocked, _DIGESTS, root=tmp_path)
    _entries(tmp_path)[0].write_bytes(encode(derive(_state(rules={"F2P": True}), {})))

    result = _roll_cache(CacheBehaviour.NONE, tmp_path).derive_state(
        state, unlocked, start=True
    )

    assert result.challenges.valid == derive(state, unlocked).challenges.valid


def test_keep_final_is_a_no_op_when_every_state_was_already_kept(tmp_path: Path) -> None:
    cache = _roll_cache(CacheBehaviour.ALL, tmp_path)
    state, final = _state(), {"100": True}
    derived = cache.derive_state(state, final, start=False)
    before = _entries(tmp_path)[0].stat().st_mtime_ns

    cache.keep_final(state, final, derived)

    assert len(_entries(tmp_path)) == 1
    assert _entries(tmp_path)[0].stat().st_mtime_ns == before


def test_a_cached_state_is_the_same_derivation_whichever_behaviour_stored_it(
    tmp_path: Path,
) -> None:
    expected = derive(_state(), {"100": True})

    for behaviour in CacheBehaviour:
        result = _roll_cache(behaviour, tmp_path).derive_state(
            _state(), {"100": True}, start=True
        )
        assert result.challenges.as_dict() == expected.challenges.as_dict()
