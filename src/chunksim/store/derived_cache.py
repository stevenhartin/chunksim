"""Cache the two expensive per-state computations on disk, keyed by their inputs.

`pipeline.derive` is one; `dps_bridge.enrich` is the other, and the second was
added after measuring where an estimate actually goes. The tempting thing to
cache is the `EstimateResult`, and it would be pointless: on the real map
`estimate` is **7.9ms** and `enrich` is **699ms**, so caching the answer saves
3ms and caching the *pricing* saves 662. An `EstimateResult` is also only valid
for one set of level overrides, where an enriched `Heuristics` serves anything
that needs a kill rate.

The two share `cache/derived/` and one `chunksim derived clean` ages out both, but
they are keyed separately: `derivation_key` and `enrichment_key`, the latter
carrying a `kind` tag so a collision is impossible by construction rather than
merely unlikely. **An enrichment's key is a strict superset of a derivation's**,
because `enrich` reads the derived state *and* the scraped rates, the
hand-written overrides and the calculator itself - see `PricingDigests`.

`derive` costs ~0.76s on the real map and is ~100% of every derivation command's
runtime, while its inputs change only when you fetch, roll, or update the
chunkinfo export. Storing the result turns a repeat command into ~0.12s, the
floor being the chunkinfo parse and interpreter start `chunksim show` already pays
at 0.05s.

**The key is the inputs, not a version number.** `derive(state, unlocked)`
reads exactly two things, so `derivation_key` hashes exactly two things: every
data field of `MapState` (canonically serialised - *not* the raw payload, so
editing an unrelated branch like `topbarSelection` doesn't needlessly
invalidate) and the `unlocked` set, plus content digests of the chunkinfo
export and the tasks map, since those decide what `load_map_state` produced in
the first place. Two more components exist only to make a *stale-but-loadable*
entry impossible, that being the single way a cache like this can be silently
wrong rather than merely useless:

- `_structure_digest()` hashes the field names of all six result dataclasses.
  Add, rename or drop a field and every existing entry becomes unreachable,
  instead of unpickling into an object missing an attribute that blows up
  somewhere unrelated much later.
- the running Python's `major.minor` and `_FORMAT`, a manual tag to bump if the
  encoding itself ever changes.

**Storage is one file per key and no ledger** (`cache.py` owns the bytes).
Nothing here needs a lock: two workers computing the same key produce the same
bytes, and the write is an atomic rename, so a concurrent double-write is
harmless. That matters because `chunksim simulate --jobs N` has several processes
live at once, and a shared index would be the project's first piece of mutable
shared state.

**Pickle, compressed with zstd.** Pickle round-trips `Derived` exactly, with no
hand-written `from_dict` per result class to drift out of step with the classes
themselves - the structural digest above is what makes that safe. zstd was
picked on measurement, over the real map's 0.473MB pickle:

    zstd-3   0.118MB (25%)   compress 1.1ms   decompress 0.3ms
    gzip-6   0.118MB (25%)   compress 9.6ms   decompress 0.8ms
    lzma     0.088MB (19%)   compress 55.7ms  decompress 2.0ms

Same ratio as gzip at nine times the write speed, and decompressing costs less
than reading the 355KB it saves. It is stdlib in Python 3.14 (PEP 784), which
this project already requires, so it adds no dependency - but a CPython built
without `_zstd` falls back to plain pickle, and the suffix in the key records
which was used so the two can never be confused for one another.

**Scope.** `cli.py`'s commands and `unlock.py` read and write, always. A
simulation's states are governed by `CacheBehaviour` (`--cache-behaviour`),
which defaults to keeping every one of them; `RollCache` is the implementation
of `simulate.StateCache` that applies it. The sizing to keep in mind is
~118KiB per state, so a 50-roll, 100-run batch can reach ~600MB under `all` -
reclaimed with `chunksim derived clean`, and avoided with `extremities`.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pickle
import sys
from enum import StrEnum
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from pathlib import Path

from chunksim.derive.active_tasks import SkillClassification, TaskClassification
from chunksim.derive.bis import BisResult
from chunksim.store.cache import (
    RECIPES_BLOB_NAME,
    WIKI_RATES_BLOB_NAME,
    CacheMissError,
    blob_path,
    file_digest,
    gathering_source,
    map_overrides_path,
    overrides_source,
    read_derived,
    write_derived,
)
from chunksim.derive.challenges import ChallengeResult
from chunksim.costing.heuristics import (
    ComputedMethod,
    Heuristics,
    MaterialCost,
    QuestRate,
    Rate,
    SlayerTask,
    Superior,
    TaskLength,
)
# Scraped shapes that `Heuristics` carries verbatim. Imported here only so the
# structural digest can see them - see `_PRICING_TYPES`.
from chunksim.remote.combat import AttackSpell, MonsterStats
from chunksim.remote.farming import Crop
from chunksim.remote.prayer import Altar, Bone
from chunksim.remote.stores import ShopPrice
from chunksim.derive.other_tasks import CategoryTasks, OtherTasks, TaskGroup
from chunksim.derive.pipeline import Derived, MapState, derive
from chunksim.derive.sources import SourceIndex

try:  # Python 3.14 stdlib (PEP 784), absent if CPython was built without libzstd.
    from compression import zstd

    _COMPRESSED = True
    SUFFIX = "pkl.zst"
except ImportError:  # pragma: no cover - depends on the interpreter build
    _COMPRESSED = False
    SUFFIX = "pkl"

#: Bump when the encoding changes in a way the structural digest can't see.
_FORMAT = "1"

#: Bumped when the *arithmetic* behind an enrichment changes, as opposed to the
#: data it reads. Every other term in `enrichment_key` is a content digest, so a
#: change to what `priced_heuristics` computes leaves every stored entry looking
#: fresh while holding numbers from the old model - and the only symptom is a
#: total that will not move. `runs/timeline.py` carries the same idea for the
#: series it stores, and for the same reason.
#:
#: 2: the timeline stopped layering its own rates. It had `load_heuristics` plus
#: `dps_bridge.enrich_incremental` where the estimate has `recipe_priced`,
#: `enrich` and the combat rates - two different computations behind one key,
#: last writer winning.
#: 3: `costing/gathering.py` arrived. Its tables ship inside the package, so
#: adding `PricingDigests.gathering` moved the key for anyone who refetches
#: them - but not for the entries already stored against the same scrape.
#: 4: `costing/production.py` arrived, charging a production method for what it
#: consumes wherever no `{{Recipe}}` reaches it. Same shape as 3 and a bigger
#: move: Fletching 1 -> 99 went 30.0h to 244.9h on the reference map.
_PRICING_MODEL = "41"

#: zstd's own default. Level 9 buys 2.6 percentage points for 4x the write
#: cost, which is the wrong trade for something written once and read often.
_LEVEL = 3

#: The result types whose shape an entry depends on. Adding one here (or a
#: field to any of them) invalidates every stored entry, by design.
#:
#: **Nested types count, and listing only the top six was a real hole.**
#: `TaskClassification`'s only field is `skills`, so a field added to
#: `SkillClassification` changed no digest at all and every stored entry
#: stayed reachable - unpickling into an object missing the attribute, which
#: is exactly the stale-but-loadable state the digest exists to make
#: impossible. `OtherTasks` -> `CategoryTasks` -> `TaskGroup` is the same
#: shape one level deeper. Pickle stores the whole graph, so the digest has to
#: describe the whole graph.
#:
#: Kept as a written-out tuple rather than a walk over field types, because
#: this is computed on every key and resolving annotations is not free.
#: `tests/test_derived_cache.py` does the walk instead and fails if a new
#: nested dataclass is missing from here.
_RESULT_TYPES = (
    Derived,
    SourceIndex,
    ChallengeResult,
    BisResult,
    TaskClassification,
    SkillClassification,
    OtherTasks,
    CategoryTasks,
    TaskGroup,
)


#: The pricing types, hashed the same way and for the same reason. Kept
#: separate from `_RESULT_TYPES` so a field added to one kind of entry does
#: not throw away the other.
#: **Nested ones too, for `_RESULT_TYPES`' reason and after the same bug.**
#: `ComputedMethod` hangs off `Heuristics.computed` and was not listed, so
#: adding a field to it - the override path behind a computed training rate -
#: changed no key, and every stored enrichment went on serving methods with
#: that field empty. The symptom was a skilling row that had lost its knobs
#: for no visible reason. Seven more sat in the same position.
_PRICING_TYPES = (
    Heuristics,
    Rate,
    SlayerTask,
    Superior,
    QuestRate,
    TaskLength,
    Altar,
    AttackSpell,
    Bone,
    ComputedMethod,
    Crop,
    MaterialCost,
    MonsterStats,
    ShopPrice,
)


@dataclass(frozen=True)
class Digests:
    """Content hashes of the reference data a derivation was computed against.

    Carried alongside `MapState` rather than inside it because `MapState` holds
    the *parsed* export, and hashing 10MB of parsed dicts costs far more than
    hashing the file it came from (`cache.file_digest`: 4ms).
    """

    chunkinfo: str
    tasks_map: str = ""


@dataclass(frozen=True)
class PricingDigests:
    """What an *enrichment* was computed against, beyond the derivation.

    **Deliberately not folded into `Digests`.** A derivation does not depend on
    any of this - `derive` has never heard of a kill rate - so adding these
    fields there would throw away every stored derivation whenever the rates
    were re-scraped, for nothing.

    `library` is the part that is easy to get wrong. `osrs-dps` is installed
    editable during development, so its *version* is `0.0.1` and stays there
    however much of the calculator changes underneath. A content digest of its
    16 source files costs 3ms and actually moves - see `dps_library_digest`.
    """

    rates: str = ""
    overrides: str = ""
    #: `cache/overrides/<map_id>.json`, kept apart from `overrides` for the
    #: reason `recipes` is kept apart from `rates`: the two move on different
    #: cadences and folding them would throw away every other map's stored
    #: enrichment whenever one map's corrections changed.
    map_overrides: str = ""
    library: str = ""
    #: The `chunksim recipes` blob. Separate from `rates` because it is a
    #: different API on a different cadence, and folding the two would
    #: invalidate every stored enrichment whenever either moved.
    recipes: str = ""
    #: `heuristics/gathering.json`, the checked-in gathering tables.
    #:
    #: **The third time this dataclass fell behind its own inputs**, and the
    #: first where the missing field was not merely stale but *invisible*: the
    #: tables ship inside the package rather than under `cache/`, so nothing
    #: about them moved when the gathering model arrived and every stored
    #: enrichment kept serving the scraped rates it had been computed with.
    #: A Woodcutting climb read 176.4h from `wiki:woodcutting` where the model
    #: says 210.3h, on a machine where the model was installed and working.
    #: Digested from `cache.gathering_source`, the file actually read.
    gathering: str = ""


def _structure_digest() -> str:
    """Hash the result dataclasses' shape, so a schema change invalidates."""
    shape = [
        (result.__name__, [field.name for field in dataclasses.fields(result)])
        for result in _RESULT_TYPES
    ]
    return hashlib.sha256(json.dumps(shape, sort_keys=True).encode()).hexdigest()[:16]


def _state_digest(state: MapState) -> str:
    """Hash every `MapState` field `derive` can read, except the export itself.

    `chunk_info` is excluded deliberately - `Digests.chunkinfo` covers it far
    more cheaply. Everything else is small decoded dicts, so a canonical dump
    is effectively free (measured under a millisecond).
    """
    fields = {
        field.name: getattr(state, field.name)
        for field in dataclasses.fields(state)
        if field.name != "chunk_info"
    }
    return hashlib.sha256(
        json.dumps(fields, sort_keys=True, default=str).encode()
    ).hexdigest()


def derivation_key(state: MapState, unlocked: Mapping[str, bool], digests: Digests) -> str:
    """The cache key for `derive(state, unlocked)`.

    Deterministic across processes and runs: every component is either a
    content hash or a sorted list, so two invocations with the same inputs
    agree without having to coordinate.
    """
    material = json.dumps(
        {
            "format": _FORMAT,
            "python": f"{sys.version_info[0]}.{sys.version_info[1]}",
            "structure": _structure_digest(),
            "chunkinfo": digests.chunkinfo,
            "tasks_map": digests.tasks_map,
            "state": _state_digest(state),
            "unlocked": sorted(unlocked),
        },
        sort_keys=True,
    )
    return f"{hashlib.sha256(material.encode()).hexdigest()}.{SUFFIX}"


def _pack(value: object) -> bytes:
    blob = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    return zstd.compress(blob, _LEVEL) if _COMPRESSED else blob


def _unpack(blob: bytes) -> Any:
    """Whatever was stored, or `None` if the bytes are unusable.

    Every failure mode - truncated file, wrong codec, a pickle from an
    incompatible build - answers `None`, because the caller's response to all
    of them is identical and correct: recompute it. A cache is never a reason
    for a command to fail.
    """
    try:
        raw = zstd.decompress(blob) if _COMPRESSED else blob
        return pickle.loads(raw)
    except Exception:  # noqa: BLE001 - any failure here means "recompute"
        return None


def encode(derived: Derived) -> bytes:
    """Serialise a derivation for storage."""
    return _pack(derived)


def decode(blob: bytes) -> Derived | None:
    """Deserialise a stored derivation, or `None` if it is unusable."""
    value = _unpack(blob)
    return value if isinstance(value, Derived) else None


def encode_pricing(priced: tuple[Heuristics, Any]) -> bytes:
    """Serialise an enrichment - the heuristics and what it managed to price."""
    return _pack(priced)


def decode_pricing(blob: bytes) -> tuple[Heuristics, Any] | None:
    """Deserialise an enrichment, or `None` if it is unusable.

    The coverage half is typed `Any` because it is `dps_bridge.DpsCoverage`,
    and this module must not import that: `dps_bridge` is the seam to an
    optional extra, so importing it here to name a type would make the whole
    cache depend on something that may not be installed.
    """
    value = _unpack(blob)
    if not isinstance(value, tuple) or len(value) != 2:
        return None
    return value if isinstance(value[0], Heuristics) else None


class CacheBehaviour(StrEnum):
    """Which of a simulation's derived states are worth keeping.

    Every roll of a run derives a state, and they are not equally useful:

    - `ALL` (the default) keeps all of them, so re-running a seed, or asking
      about a chunk some run passed through, is served from disk. Costs the
      most: ~118KiB per state, so up to ~600MB for a 50-roll, 100-run batch
      before counting the overlap between runs that reached the same chunk set.
    - `EXTREMITIES` keeps only the state each run starts from and the one it
      finishes on. The start is shared by every run in a batch; the finish is
      exactly the state the saved simulated map holds, so a later
      `chunksim tasks --map <that run>` is immediate. Two entries per run.
    - `NONE` keeps nothing and reads nothing - a genuine "don't touch my disk",
      not "no new intermediates". It is therefore also the slowest, since even
      the shared starting state is recomputed per run.
    """

    ALL = "all"
    EXTREMITIES = "extremities"
    NONE = "none"


@dataclass(frozen=True)
class RollCache:
    """`simulate.StateCache` for one run: the policy `CacheBehaviour` names.

    Frozen and self-contained so it can be built inside a worker process -
    nothing here is shared between runs, which is what keeps `--jobs` honest.
    """

    digests: Digests
    behaviour: CacheBehaviour = CacheBehaviour.ALL
    root: Path | None = None
    #: Whether this run is carrying areas between rolls (`pipeline.derive`).
    carry_areas: bool = False
    #: Encoded states a carrying run has computed but not yet earned the right
    #: to write. Mutable, but per-run and inside the worker that made it -
    #: nothing is shared, which is what keeps `--jobs` honest. ~118KiB a state,
    #: so a fifty-roll run holds about 6MB before it flushes.
    _pending: list[tuple[str, bytes]] = field(default_factory=list)

    def derive_state(
        self,
        state: MapState,
        unlocked: Mapping[str, bool],
        *,
        start: bool,
        carry: Mapping[str, bool] | None = None,
    ) -> Derived:
        if self.behaviour is CacheBehaviour.NONE:
            return derive(state, unlocked, carry_areas=carry)
        wanted = self.behaviour is CacheBehaviour.ALL or start
        if carry is None:
            return cached_derive(
                state, unlocked, self.digests, root=self.root, store=wanted
            )
        # **Held, not written.** A carried state is not this key's answer to
        # give until the run has checked itself (`simulate.simulate_rolls`), so
        # it waits in memory and `keep_final` releases it. A run that diverges
        # raises before that, and the buffer dies with it.
        derived = cached_derive(
            state, unlocked, self.digests, root=self.root, store=False, carry_areas=carry
        )
        if wanted:
            self._pending.append(
                (derivation_key(state, unlocked, self.digests), encode(derived))
            )
        return derived

    def keep_final(
        self, state: MapState, unlocked: Mapping[str, bool], derived: Derived
    ) -> None:
        """Store the state the run finished on.

        Under `ALL` it is already there (`derive_state` stored it as it went);
        under `NONE` it must not be. That leaves `EXTREMITIES`, which is why
        this exists at all: a run's last roll is only identifiable *after* the
        loop, so it cannot be flagged when it is derived without deriving it
        twice.
        """
        if self.behaviour is CacheBehaviour.NONE:
            self._pending.clear()
            return
        # The run checked out, so everything it held is released. See
        # `simulate_rolls` for why one check at the end covers every state.
        for key, blob in self._pending:
            write_derived(key, blob, self.root)
        self._pending.clear()
        if self.behaviour is not CacheBehaviour.EXTREMITIES and not self.carry_areas:
            # `ALL` already stored it on the way past.
            return
        # What arrives here is the *cold* re-derivation the run checked itself
        # against, so it is written last and is the copy that stands.
        key = derivation_key(state, unlocked, self.digests)
        write_derived(key, encode(derived), self.root)


def cached_derive(
    state: MapState,
    unlocked: Mapping[str, bool],
    digests: Digests,
    *,
    root: Path | None = None,
    refresh: bool = False,
    store: bool = True,
    carry_areas: Mapping[str, bool] | None = None,
) -> Derived:
    """`derive`, served from disk when the inputs are unchanged.

    `refresh` ignores any stored entry and rewrites it (`--recompute`);
    `store` off computes without writing, which is how `simulate` avoids
    filling the cache with per-roll states nothing will ask for again.

    **A carried derivation may be read from the cache but never written to
    it**, and this refuses the combination rather than trusting a caller to
    remember. `carry_areas` is an unproven optimisation (`pipeline.derive`),
    so a result computed with one is not necessarily the answer this key
    names - and the key cannot be made to name it either: the carry is a
    function of the whole roll history, so folding it in would make every
    roll's key unique and destroy the cross-run sharing that is the point of
    this cache, while breaking the module's own rule that **a key separates
    inputs, never computations**. Storing it anyway would be worse: an
    unverified answer would sit under the key naming the verified one, and
    every later `chunksim tasks`, `chunksim estimate` and GUI panel would read it.

    Reading is not merely allowed but wanted: a stored entry is by definition
    the cold answer, so a hit both skips the work and re-anchors the carry
    chain on a verified state.
    """
    if carry_areas is not None and store:
        raise ValueError(
            "a carried derivation is not the computation this key names; "
            "pass store=False, and see pipeline.derive on why it is unproven"
        )
    key = derivation_key(state, unlocked, digests)
    if not refresh:
        blob = read_derived(key, root)
        if blob is not None:
            hit = decode(blob)
            if hit is not None:
                return hit

    derived = derive(state, unlocked, carry_areas=carry_areas)
    if store:
        write_derived(key, encode(derived), root)
    return derived


def _pricing_structure_digest() -> str:
    """Hash the pricing dataclasses' shape, so a schema change invalidates."""
    shape = [
        (priced.__name__, [field.name for field in dataclasses.fields(priced)])
        for priced in _PRICING_TYPES
    ]
    return hashlib.sha256(json.dumps(shape, sort_keys=True).encode()).hexdigest()[:16]


def dps_library_digest() -> str:
    """A content hash of the installed `osrs-dps`, or `""` when it is absent.

    **The version string is not usable for this.** `osrs-dps` is installed
    editable during development (`pip install -e ../osrs-dps`), so its version
    is `0.0.1` and stays there however much of the calculator changes - and a
    calculator change moves every kill rate. Hashing its 16 source files costs
    3ms and does move, which is the difference between a cache that notices
    and one that serves numbers from a library you have since edited.
    """
    try:
        import osrs_dps
    except ImportError:
        return ""
    root = Path(osrs_dps.__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def pricing_digests(root: Path | None = None, map_id: str | None = None) -> PricingDigests:
    """What this machine would price an enrichment against, right now.

    One builder for all three callers - `chunksim estimate`, the GUI's estimate
    panel and `batch.price_slice` - because a key computed two ways is a
    cache that misses for no reason, or worse, hits when it should not.

    A missing rate scrape or overrides file digests as `""` rather than
    raising: both are optional inputs, and "the file that is not there" is a
    perfectly good thing for a key to describe. `map_id` is `None` for a
    caller pricing nothing in particular, which digests the same as a map with
    no corrections - correctly, since the two price identically.
    """
    return PricingDigests(
        rates=_maybe_digest(lambda: blob_path(WIKI_RATES_BLOB_NAME, root)),
        # **`overrides_source`, not `overrides_path`.** They differ on an
        # installed build that has never had a knob edited - the write path
        # does not exist and the shipped corrections do - so digesting the
        # write path described an empty input on every such install.
        overrides=_maybe_digest(lambda: overrides_source(root)),
        map_overrides=(
            ""
            if map_id is None
            else _maybe_digest(lambda: map_overrides_path(map_id, root))
        ),
        library=dps_library_digest(),
        recipes=_maybe_digest(lambda: blob_path(RECIPES_BLOB_NAME, root)),
        gathering=_maybe_digest(lambda: gathering_source(root)),
    )


def _maybe_digest(locate: Callable[[], Path]) -> str:
    try:
        return file_digest(locate())
    except (OSError, CacheMissError):
        return ""


def enrichment_key(
    state: MapState,
    unlocked: Mapping[str, bool],
    digests: Digests,
    pricing: PricingDigests,
) -> str:
    """The cache key for `dps_bridge.enrich` over this state.

    **Everything the derivation key covers, plus everything it does not.**
    `enrich` reads the derived state (so the whole derivation key applies) and
    also every field of `PricingDigests` - the scraped rates, both layers of
    hand-written overrides, the recipes and the calculator itself - none of
    which `derive` has ever heard of. Storing an enrichment under the plain
    derivation key would serve stale kill rates after a `chunksim heuristics`, an
    edit to either overrides file, or an upgrade of `osrs-dps`, and the only
    symptom would be a total that failed to move.

    The `kind` tag makes a collision with a derivation impossible rather than
    merely unlikely, so the two can share `cache/derived/` and one
    `chunksim derived clean` ages out both.

    **A key can only separate inputs, never computations**, which is worth
    stating because this cache has already been used for two. The timeline
    layered `enrich_incremental` alone where the estimate layered recipes,
    fights and combat; both wrote here, and the last one to run decided what
    the other read back. Nothing in a digest could have caught that - the
    inputs really were identical - so the rule is that one function computes
    an enrichment (`inputs.priced_heuristics`) and `_PRICING_MODEL` retires
    what an older one left behind.
    """
    material = json.dumps(
        {
            "kind": "enrichment",
            "format": _FORMAT,
            "python": f"{sys.version_info[0]}.{sys.version_info[1]}",
            "structure": _pricing_structure_digest(),
            "chunkinfo": digests.chunkinfo,
            "tasks_map": digests.tasks_map,
            "state": _state_digest(state),
            "unlocked": sorted(unlocked),
            # **Every field, taken from the dataclass rather than listed.**
            # This was four hand-written lines and the list has fallen behind
            # `PricingDigests` twice: first `recipes`, so `chunksim recipes`
            # landing after an estimate left every stored enrichment holding
            # the recipe-free rates - a skill priced at the 1,000/hr floor
            # staying there through the very fetch that fixes it - and then
            # `map_overrides`, so a per-map correction changed no key and the
            # total simply failed to move. A digest that has to be remembered
            # is a digest that will be forgotten; `asdict` cannot be.
            "pricing": dataclasses.asdict(pricing),
            "model": _PRICING_MODEL,
        },
        sort_keys=True,
    )
    return f"{hashlib.sha256(material.encode()).hexdigest()}.{SUFFIX}"


def cached_enrich(
    compute: Callable[[], tuple[Heuristics, Any]],
    state: MapState,
    unlocked: Mapping[str, bool],
    digests: Digests,
    pricing: PricingDigests,
    *,
    root: Path | None = None,
    refresh: bool = False,
    store: bool = True,
) -> tuple[Heuristics, Any]:
    """`dps_bridge.enrich`, served from disk when the inputs are unchanged.

    **This is where an estimate's time actually goes**, which is worth stating
    because the obvious thing to cache is the `EstimateResult` and that would
    be pointless. Measured on the real map: `estimate` is 7.9ms and `enrich`
    is 699ms, so caching the answer saves 8ms and caching the *pricing* saves
    699. Storing 21KB and spending ~11ms to read it back is a 60x win on a
    repeat; storing an `EstimateResult` would be a rounding error with an
    extra invalidation problem attached.

    `compute` is a callable rather than the arguments to `enrich`, so this
    module never imports `dps_bridge` - the optional extra stays something only
    its own seam knows about.
    """
    key = enrichment_key(state, unlocked, digests, pricing)
    if not refresh:
        blob = read_derived(key, root)
        if blob is not None:
            hit = decode_pricing(blob)
            if hit is not None:
                return hit

    priced = compute()
    if store:
        write_derived(key, encode_pricing(priced), root)
    return priced
