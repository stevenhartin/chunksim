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

from chunksim.model.chunkinfo import ChunkInfo
from chunksim.store.cache import (
    RECIPES_BLOB_NAME,
    WIKI_RATES_BLOB_NAME,
    blob_path,
    gathering_path,
    map_overrides_path,
    overrides_path,
)
from chunksim.store.derived_cache import (
    CacheBehaviour,
    Digests,
    PricingDigests,
    RollCache,
    _PRICING_TYPES,
    _RESULT_TYPES,
    _structure_digest,
    cached_derive,
    cached_enrich,
    decode,
    decode_pricing,
    derivation_key,
    encode,
    enrichment_key,
    pricing_digests,
)
from chunksim.costing.heuristics import Heuristics, Rate
from chunksim.derive.pipeline import MapState, derive

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
    """A re-run `chunksim chunkinfo` must not be served last week's answer."""
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

    monkeypatch.setattr("chunksim.store.derived_cache._RESULT_TYPES", (Extended,))

    assert _structure_digest() != before


def test_the_structural_digest_reaches_every_nested_pricing_class() -> None:
    """**The same hole, in the sibling structure.**

    `_RESULT_TYPES` was fixed for derivations and `_PRICING_TYPES` was not, so
    `ComputedMethod` - which hangs off `Heuristics.computed` - was unwatched.
    Adding the override path behind a computed training rate to it changed no
    key, and every stored enrichment went on serving methods with that field
    empty; the symptom was a skilling row that had quietly lost its knobs.
    Seven more types sat in the same position.
    """
    missing = sorted(
        cls.__name__ for cls in _reachable_dataclasses(_PRICING_TYPES) - set(_PRICING_TYPES)
    )
    assert missing == [], f"nested pricing dataclasses absent from _PRICING_TYPES: {missing}"


def test_the_structural_digest_reaches_every_nested_result_class() -> None:
    """**Pickle stores the whole graph, so the digest must describe it.**

    `_RESULT_TYPES` was the six top-level results, and three dataclasses hung
    below them unwatched: `SkillClassification` under `TaskClassification`
    (whose only field is `skills`), and `CategoryTasks`/`TaskGroup` under
    `OtherTasks`. A field added to any of those changed no digest at all, so
    every stored entry stayed *reachable* and unpickled into an object missing
    the attribute - which is the one way this cache can be wrong rather than
    merely useless, and the failure the digest exists to prevent.

    The walk lives here rather than in `_structure_digest` because that runs
    on every key and resolving annotations is not free. Its job is to fail the
    day someone adds a nested result type and forgets the tuple.
    """
    missing = sorted(
        cls.__name__ for cls in _reachable_dataclasses(_RESULT_TYPES) - set(_RESULT_TYPES)
    )
    assert missing == [], f"nested result dataclasses absent from _RESULT_TYPES: {missing}"


def _reachable_dataclasses(roots: tuple[type, ...]) -> set[type]:
    """Every dataclass pickle would store, reached from `roots` by field type.

    Shared by the two digest tests because the hole they check for is the same
    hole: a nested type nobody listed, whose fields the key therefore ignores.
    """
    import typing

    found: set[type] = set()

    def walk(cls: type) -> None:
        if not dataclasses.is_dataclass(cls) or cls in found:
            return
        found.add(cls)
        hints = typing.get_type_hints(cls)
        for field in dataclasses.fields(cls):
            annotation = hints.get(field.name)
            for candidate in (annotation, *typing.get_args(annotation)):
                for inner in (candidate, *typing.get_args(candidate)):
                    if dataclasses.is_dataclass(inner) and isinstance(inner, type):
                        walk(inner)

    for root in roots:
        walk(root)
    return found


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


# --- the enrichment cache --------------------------------------------------

_PRICING = PricingDigests(rates="r1", overrides="o1", library="l1")


def test_an_enrichment_can_never_collide_with_a_derivation() -> None:
    """They share `cache/derived/`, so one `chunksim derived clean` ages out both.
    A `kind` tag in the material makes that safe by construction rather than
    by the two happening to hash differently."""
    state = _state()

    assert enrichment_key(state, {"100": True}, _DIGESTS, _PRICING) != derivation_key(
        state, {"100": True}, _DIGESTS
    )


@pytest.mark.parametrize("field", ["rates", "overrides", "library"])
def test_every_pricing_input_moves_the_key(field: str) -> None:
    """**The derivation key covers none of these**, which is why an enrichment
    needs its own. Storing one under the plain derivation key would serve
    stale kill rates after a `chunksim heuristics`, an edit to
    `heuristics/overrides.json` or an `osrs-dps` upgrade - and the symptom
    would be a total that failed to move, which is invisible."""
    state = _state()
    moved = dataclasses.replace(_PRICING, **{field: "changed"})

    assert enrichment_key(state, {"100": True}, _DIGESTS, moved) != enrichment_key(
        state, {"100": True}, _DIGESTS, _PRICING
    )


def test_a_pricing_digest_is_not_the_library_version(tmp_path: Path) -> None:
    """`osrs-dps` is installed editable, so its version is `0.0.1` and stays
    there however much of the calculator changes underneath - and a calculator
    change moves every kill rate. The digest is of the source, so it moves."""
    from chunksim.store.derived_cache import dps_library_digest

    digest = dps_library_digest()

    # Either the extra is absent (empty) or we got a content hash, never a
    # version string.
    assert digest == "" or (len(digest) == 16 and digest != "0.0.1")


def test_an_enrichment_is_computed_once_and_then_read(tmp_path: Path) -> None:
    calls = []

    def price() -> tuple[Heuristics, str]:
        calls.append(1)
        return Heuristics(monsters={"Goblin": Rate(42.0)}), "coverage"

    state = _state()
    first = cached_enrich(price, state, {"100": True}, _DIGESTS, _PRICING, root=tmp_path)
    second = cached_enrich(price, state, {"100": True}, _DIGESTS, _PRICING, root=tmp_path)

    assert len(calls) == 1
    assert first[0].kills_per_hour("Goblin").value == 42.0
    assert second[0].kills_per_hour("Goblin").value == 42.0
    assert second[1] == "coverage", "the coverage half survives the round trip"


def test_refresh_recomputes_an_enrichment(tmp_path: Path) -> None:
    """`--recompute` has to mean the same thing here as for a derivation."""
    values = iter([1.0, 2.0])

    def price() -> tuple[Heuristics, None]:
        return Heuristics(monsters={"Goblin": Rate(next(values))}), None

    state = _state()
    cached_enrich(price, state, {"100": True}, _DIGESTS, _PRICING, root=tmp_path)
    again = cached_enrich(
        price, state, {"100": True}, _DIGESTS, _PRICING, root=tmp_path, refresh=True
    )

    assert again[0].kills_per_hour("Goblin").value == 2.0


def test_a_corrupt_enrichment_is_a_miss_rather_than_a_crash(tmp_path: Path) -> None:
    """Same posture as a corrupt derivation: every failure mode answers "not
    there", because the caller's response to all of them is to recompute."""
    assert decode_pricing(b"not a pickle") is None
    assert decode_pricing(encode(derive(_state(), {"100": True}))) is None, (
        "a stored *derivation* must not read back as an enrichment"
    )


def test_a_carried_derivation_refuses_to_be_stored(tmp_path: Path) -> None:
    """**A key names inputs, never a computation.**

    `carry_areas` is unproven (`pipeline.derive`), so what it returns is not
    necessarily the answer `derivation_key` names - and the carry cannot be
    folded into the key either, since it is a function of the whole roll
    history and would make every roll unique, destroying the cross-run
    sharing this cache exists for. Storing it anyway would put an unverified
    answer under the verified one's key, where every later command would read
    it. So the combination raises rather than relying on callers to remember.
    """
    state = _state()

    with pytest.raises(ValueError, match="not the computation this key names"):
        cached_derive(
            state, {"100": True}, _DIGESTS, root=tmp_path, carry_areas={"Area": True}
        )


def test_a_carrying_roll_cache_holds_its_states_until_the_run_checks_out(
    tmp_path: Path,
) -> None:
    """**Held, then released - not discarded.**

    A carried state is not this key's answer to give until the run has checked
    itself against a cold derivation, so it waits in memory. `keep_final` is
    the run saying it checked out, and that is when the lot is written.
    """
    state = _state()
    cache = RollCache(_DIGESTS, CacheBehaviour.ALL, tmp_path, True)

    first = cache.derive_state(state, {"100": True}, start=True, carry={"Area": True})
    cache.derive_state(state, {"100": True, "101": True}, start=False, carry={"Area": True})

    assert _entries(tmp_path) == [], "a carried state reached disk before the check"

    cache.keep_final(state, {"100": True, "101": True}, first)

    assert len(_entries(tmp_path)) == 2, "the checked run should release what it held"


def test_a_run_that_never_checks_out_writes_nothing(tmp_path: Path) -> None:
    """The reason the buffer exists rather than a write-then-retract. A run
    that diverges raises before `keep_final`, so the states it computed are
    still only in memory and go with it."""
    state = _state()
    cache = RollCache(_DIGESTS, CacheBehaviour.ALL, tmp_path, True)

    cache.derive_state(state, {"100": True}, start=True, carry={"Area": True})
    del cache  # what `simulate_rolls` raising amounts to

    assert _entries(tmp_path) == []


def test_a_carrying_roll_cache_still_reads_what_is_already_there(tmp_path: Path) -> None:
    """Reading is wanted - a stored entry is by definition the cold answer, so
    a hit both skips the work and re-anchors the carry chain on a verified
    state."""
    state = _state()
    unlocked = {"100": True}
    plain = RollCache(_DIGESTS, CacheBehaviour.ALL, tmp_path)
    stored = plain.derive_state(state, unlocked, start=True)
    assert len(_entries(tmp_path)) == 1

    carrying = RollCache(_DIGESTS, CacheBehaviour.ALL, tmp_path, True)
    assert carrying.derive_state(state, unlocked, start=False, carry={"Area": True}) == stored


def test_the_enrichment_key_covers_every_pricing_digest() -> None:
    """**A digest that has to be remembered is a digest that gets forgotten.**

    This key listed `PricingDigests`' fields by hand and fell behind the
    dataclass twice: `recipes`, so `chunksim recipes` landing after an estimate
    left every stored enrichment holding the recipe-free rates; then
    `map_overrides`, so a per-map correction changed no key and the total
    simply failed to move. Both are the same bug and neither was catchable by
    reading the key - the inputs really had changed and the key said they had
    not. So the assertion is structural: move any field, and the key moves.
    """
    state = _state()
    digests = Digests(chunkinfo="a", tasks_map="b")
    base = PricingDigests(rates="r", overrides="o", library="l", recipes="c")

    keys = {enrichment_key(state, {}, digests, base)}
    for field in dataclasses.fields(PricingDigests):
        moved = dataclasses.replace(base, **{field.name: "moved"})
        keys.add(enrichment_key(state, {}, digests, moved))

    assert len(keys) == 1 + len(dataclasses.fields(PricingDigests)), (
        "some PricingDigests field does not reach the enrichment key"
    )


def test_the_pricing_digests_cover_every_file_the_pricing_reads(tmp_path: Path) -> None:
    """**The other half of the key, and the half that actually broke.**

    `test_the_enrichment_key_covers_every_pricing_digest` proves every *field*
    reaches the key. It cannot prove the fields describe every *file*, and
    that is the gap the gathering tables fell through: `heuristics/gathering.json`
    ships inside the package rather than under `cache/`, so no field watched
    it, the key never moved, and every stored enrichment went on serving the
    scraped rates the model was meant to replace. The symptom was a
    Woodcutting climb reading 176.4h from `wiki:woodcutting` on a machine
    where the model said 210.3h.

    So this walks the files rather than the fields: write one, digest, change
    it, digest again. A file nothing hashes shows up here as two equal
    digests.
    """
    locations = {
        "rates": blob_path(WIKI_RATES_BLOB_NAME, tmp_path),
        "recipes": blob_path(RECIPES_BLOB_NAME, tmp_path),
        "overrides": overrides_path(tmp_path),
        "map_overrides": map_overrides_path("fray", tmp_path),
        "gathering": gathering_path(tmp_path),
    }
    for path in locations.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"data": {}}', encoding="utf-8")

    for name, path in locations.items():
        before = pricing_digests(tmp_path, "fray")
        path.write_text('{"data": {"moved": true}}', encoding="utf-8")
        after = pricing_digests(tmp_path, "fray")
        assert before != after, f"nothing in PricingDigests watches {name} ({path.name})"


def test_an_installed_build_digests_the_files_that_shipped_with_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**The `_source` half of both fixes, on the build where it is visible.**

    An install that has never had a knob edited and has never run
    `chunksim gather-tables` reads two files from inside the package and
    writes neither. Digesting the *write* paths says both inputs are empty on
    exactly those builds - so two installs with different shipped corrections
    would share a cache key. It resolves to the same file in a checkout, which
    is why this needs a root with no `src/chunksim` under it.
    """
    monkeypatch.setenv("CHUNKSIM_CACHE", str(tmp_path))

    digests = pricing_digests()

    assert digests.overrides != "", "the shipped corrections must reach the key"
    assert digests.gathering != "", "the shipped gathering tables must reach the key"
