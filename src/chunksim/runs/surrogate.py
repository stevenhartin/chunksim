"""A per-batch table of what each chunk cost, learned from exact runs and used
to price the rest.

**Why a batch can afford to guess, when a single run cannot.** A grind prices
the whole world every roll to make one binary decision, and a batch of a
thousand grinds from one base map repeats that pricing across paths that are
mostly the same chunks in a different order. Measured on the real map: 97% of
all added hours are skill climbs, each attributed to whichever chunk
*introduces* the requirement; the small costs are properties of the chunk
alone (`13104` added 2.018h in six of six runs); and **15 of 33 chunks added
nothing in every run they appeared in**. So a table keyed on the chunk and on
which requirement-introducing chunks are already held predicts the rest -
with 10% of a batch as ground truth, **99.0% of threshold decisions right**
and 96% of costs within 25%, on the 62% of rolls it had seen at all.

**Per batch, never offline.** A chunk's cost is a property of the base map:
the rules a player set, the account's levels, what is already completed and
held. The same Construction chunk that adds 357.9 hours on one map adds nothing
on an account already past the level. So the table is built from this batch's
own exact runs and thrown away with it, which holds every one of those inputs
fixed by construction. See `batch._schedule` for where it is built and
`grind._StepPricer.price` for where it is consulted.

**A guess is only ever used where it cannot change the decision.** The stopping
question is `added > limit`, so a chunk is priced from the table only when
every sample of it lands on the same side of the limit; a chunk whose samples
straddle it, or that the table has not seen, goes to the exact path. That is
what keeps the *stopping step* honest while the recorded cost on a guessed
roll is a median rather than a walk - and every such roll is flagged
provisional, as a carried total already is.

**Only exact rolls teach.** A roll priced from the table never feeds back into
it, or the table would drift towards its own guesses. A roll skipped because
it wanted nothing new *is* exact - its cost is zero by construction - and does
teach. See `batch._learn`.

**Measured on a real batch**, forty grinds against a 25-hour wall with 10%
priced exactly, and the same forty seeds priced exactly throughout: every one
of the forty stopped at the same step on the same chunk, 66 of 292 rolls were
priced from the table, and the batch took 42.8s against 60.2s. A batch that
small barely warms the table; coverage grows with every exact roll, so the
guessed share rises with the batch.

Pure: samples in, a picklable table out, and a lookup over it.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

#: A chunk whose cost ever exceeds this is one that *introduces* a requirement
#: - a skill climb attributed to it - and the other chunks' costs depend on
#: whether it is already held. The context key is the held subset of these.
#: Measured: every bimodal chunk on the real map had one mode above this and
#: the other below one hour.
BIG_HOURS = 25.0

#: Fewer samples than this and a chunk is not guessed at, whatever they say.
MIN_SAMPLES = 2

#: The table's keys. Plain strings and tuples so it pickles through a pool
#: and reads back out of `batch.json` as it went in.
BIG = "big"
BY_CONTEXT = "by_context"
BY_CHUNK = "by_chunk"


@dataclass(frozen=True)
class Sample:
    """One exact roll: the chunk, what was held before it, what it added."""

    chunk: str
    held: frozenset[str]
    added: float


@dataclass(frozen=True)
class Guess:
    """What the table says a chunk costs here, and how sure it is."""

    median: float
    low: float
    high: float
    samples: int

    def verdict(self, limit: float) -> str:
        """`"over"`, `"under"`, or `"uncertain"` against the stopping limit.

        Every sample on one side is the only way to a decision; a spread that
        straddles the limit is the case the exact walk exists for.
        """
        if self.samples < MIN_SAMPLES:
            return "uncertain"
        if self.low > limit:
            return "over"
        if self.high <= limit:
            return "under"
        return "uncertain"


def build(samples: Iterable[Sample]) -> dict[str, Any]:
    """The table, from every exact roll the batch has so far."""
    rows = list(samples)
    big = frozenset(sample.chunk for sample in rows if sample.added > BIG_HOURS)
    by_context: dict[str, dict[tuple[str, ...], list[float]]] = {}
    by_chunk: dict[str, list[float]] = {}
    for sample in rows:
        context = tuple(sorted(sample.held & big))
        by_context.setdefault(sample.chunk, {}).setdefault(context, []).append(sample.added)
        by_chunk.setdefault(sample.chunk, []).append(sample.added)
    return {
        BIG: tuple(sorted(big)),
        BY_CONTEXT: {
            chunk: {context: _summary(values) for context, values in contexts.items()}
            for chunk, contexts in by_context.items()
        },
        BY_CHUNK: {chunk: _summary(values) for chunk, values in by_chunk.items()},
    }


def _summary(values: list[float]) -> tuple[float, float, float, int]:
    return (statistics.median(values), min(values), max(values), len(values))


def lookup(table: Mapping[str, Any], chunk: str, held: Iterable[str]) -> Guess | None:
    """What the table knows about rolling `chunk` from a state holding `held`.

    The context-keyed entry first - it is what resolves a chunk that costs 904
    hours or nothing depending on whether its sibling came first - falling
    back to the chunk alone, which is right for the many chunks whose cost is
    theirs regardless. `None` for a chunk the batch has not yet priced.
    """
    big = frozenset(table.get(BIG, ()))
    context = tuple(sorted(frozenset(held) & big))
    found = table.get(BY_CONTEXT, {}).get(chunk, {}).get(context)
    if found is None:
        found = table.get(BY_CHUNK, {}).get(chunk)
    if found is None:
        return None
    median, low, high, count = found
    return Guess(median=median, low=low, high=high, samples=count)


def samples_from(
    base_held: Iterable[str],
    rolled: Iterable[str],
    added: Iterable[float],
    guessed: Iterable[int] = (),
) -> list[Sample]:
    """The exact rolls of one finished run, as samples.

    `added[0]` is the baseline and `added[i]` belongs to `rolled[i - 1]`,
    which is `Frontier`'s own layout. `guessed` names the indices into `added`
    that came from the table and must not teach it.
    """
    skip = frozenset(guessed)
    held = set(base_held)
    out: list[Sample] = []
    costs = list(added)
    for index, chunk in enumerate(rolled, start=1):
        if index < len(costs) and index not in skip:
            out.append(Sample(chunk=chunk, held=frozenset(held), added=float(costs[index])))
        held.add(chunk)
    return out
