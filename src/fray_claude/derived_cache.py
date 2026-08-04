"""Cache `pipeline.derive`'s result on disk, keyed by everything it read.

`derive` costs ~1.0s on the real map and is ~100% of every derivation command's
runtime, while its inputs change only when you fetch, roll, or update the
chunkinfo export. Storing the result turns a repeat command into ~0.15s, the
floor being the chunkinfo parse `fray show` already pays.

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
harmless. That matters because `fray simulate --jobs N` has several processes
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

**Scope.** `cli.py`'s commands and `unlock.py` read and write. `simulate.py`
caches only the *base* state every run starts from - one entry shared by all of
a batch's runs - and never its per-roll intermediates: at 0.118MB each, a
`--rolls 50 --runs 100` batch would write ~5,000 entries for states no second
command will ever ask for.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pickle
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from fray_claude.active_tasks import TaskClassification
from fray_claude.bis import BisResult
from fray_claude.cache import read_derived, write_derived
from fray_claude.challenges import ChallengeResult
from fray_claude.other_tasks import OtherTasks
from fray_claude.pipeline import Derived, MapState, derive
from fray_claude.sources import SourceIndex

try:  # Python 3.14 stdlib (PEP 784), absent if CPython was built without libzstd.
    from compression import zstd

    _COMPRESSED = True
    SUFFIX = "pkl.zst"
except ImportError:  # pragma: no cover - depends on the interpreter build
    _COMPRESSED = False
    SUFFIX = "pkl"

#: Bump when the encoding changes in a way the structural digest can't see.
_FORMAT = "1"

#: zstd's own default. Level 9 buys 2.6 percentage points for 4x the write
#: cost, which is the wrong trade for something written once and read often.
_LEVEL = 3

#: The result types whose shape an entry depends on. Adding one here (or a
#: field to any of them) invalidates every stored entry, by design.
_RESULT_TYPES = (
    Derived,
    SourceIndex,
    ChallengeResult,
    BisResult,
    TaskClassification,
    OtherTasks,
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


def encode(derived: Derived) -> bytes:
    """Serialise a derivation for storage."""
    blob = pickle.dumps(derived, protocol=pickle.HIGHEST_PROTOCOL)
    return zstd.compress(blob, _LEVEL) if _COMPRESSED else blob


def decode(blob: bytes) -> Derived | None:
    """Deserialise a stored derivation, or `None` if it is unusable.

    Every failure mode - truncated file, wrong codec, a pickle from an
    incompatible build - answers `None`, because the caller's response to all
    of them is identical and correct: recompute it. A cache is never a reason
    for a command to fail.
    """
    try:
        raw = zstd.decompress(blob) if _COMPRESSED else blob
        derived = pickle.loads(raw)
    except Exception:  # noqa: BLE001 - any failure here means "recompute"
        return None
    return derived if isinstance(derived, Derived) else None


def cached_derive(
    state: MapState,
    unlocked: Mapping[str, bool],
    digests: Digests,
    *,
    root: Path | None = None,
    refresh: bool = False,
    store: bool = True,
) -> Derived:
    """`derive`, served from disk when the inputs are unchanged.

    `refresh` ignores any stored entry and rewrites it (`--recompute`);
    `store` off computes without writing, which is how `simulate` avoids
    filling the cache with per-roll states nothing will ask for again.
    """
    key = derivation_key(state, unlocked, digests)
    if not refresh:
        blob = read_derived(key, root)
        if blob is not None:
            hit = decode(blob)
            if hit is not None:
                return hit

    derived = derive(state, unlocked)
    if store:
        write_derived(key, encode(derived), root)
    return derived
