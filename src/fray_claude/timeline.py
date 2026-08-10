"""Replay a simulated run one roll at a time.

`simulate.py` rolls and `batch.py` saves the world it ended in; the sequence
that got there is written to `rolls.json` and, until this module, nothing read
it back. So a simulation could answer "where would I end up" and not "what did
each roll actually buy me", which is the question that decides whether a
simulation was a good one.

**A run is self-contained, and that is the whole trick.** The saved payload
holds the *final* unlocked set and the ledger holds the chunks rolled, in
order, so the state before roll k is `final - rolls[k:]` - no base map, no
derivation, no export. A run whose base map has since been deleted still
replays exactly (`tests/test_timeline.py` asserts that by deleting it), and
stepping through one costs a JSON read rather than the ~0.9s a `derive` costs.

That holds because **a roll never revisits a chunk**: `neighbours.py` offers
only chunks that are not unlocked yet, so the rolled ids are distinct and
disjoint from the starting set. `replay` states that as a precondition and
`starting_set` is where it would show up if it ever stopped being true - the
arithmetic would leave the wrong number of chunks at step 0 rather than
failing, so the count is checked and reported rather than assumed.

**Hours are not computed here.** A roll's *task* count is already in the ledger
- `unlock.delta_from` recorded it at roll time - but its *hours* need
`estimate.estimate` over a full `Derived`, which needs the 10MB export. That is
the caller's to pay for and cache (`gui/server.py` writes it to
`timeline.json`), so this module stays pure and instant. What it does own is
`added_hours`, which is the arithmetic rather than the computing.

**A bar is what the roll cost, not how the total moved.** Those are different
numbers and the difference is the point. A timeline walks one player's history
forward, so by the time roll k lands, everything roll k-1 opened is behind
them; a chunk that only makes old work *cheaper* has added nothing. Subtracting
totals says otherwise - it reports a saving as negative work, and a measured
early-game run showed a roll at -2.4h on exactly that. So the bar is the cost
of what this roll newly put in front of you, it is never negative, and **the
bars do not sum to the total** on the Estimate tab. They are what each roll
cost, not a decomposition of what is left.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fray_claude.model.summary import _mapping

if TYPE_CHECKING:  # a type only - importing `estimate` here would be a cycle
    from fray_claude.costing.estimate import EstimateResult


@dataclass(frozen=True)
class Step:
    """One point on the timeline: the world after `order` rolls.

    Step 0 is the state the run started from and has no chunk - it is a
    baseline, not a roll, which is why `chunk_id` is `None` there and why
    `series` gives it no delta.
    """

    order: int
    chunk_id: str | None
    unlocked: frozenset[str]
    #: Per skill, the tasks this roll made valid. Names are the raw
    #: markup-bearing keys - `challenges.strip_task_markup` is display-only
    #: and belongs to whoever renders them.
    tasks_added: Mapping[str, tuple[str, ...]]
    sections_added: int
    bis_upgrades: int

    @property
    def task_count(self) -> int:
        return sum(len(names) for names in self.tasks_added.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "step": self.order,
            "chunk": self.chunk_id,
            "unlocked_chunks": len(self.unlocked),
            "tasks": self.task_count,
            "tasks_by_skill": {
                skill: len(names) for skill, names in sorted(self.tasks_added.items()) if names
            },
            "sections": self.sections_added,
            "bis_upgrades": self.bis_upgrades,
        }


def rolled_chunks(ledger: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    """The chunk ids a ledger rolled, in roll order.

    Sorted by the record's own `order` rather than trusting the file's, since
    the ledger is what dates a step and a reordered file would silently
    produce a timeline that never happened.
    """
    records = [entry for entry in ledger if isinstance(entry.get("chunk_id"), str)]
    records.sort(key=lambda entry: _order_of(entry))
    return tuple(str(entry["chunk_id"]) for entry in records)


def _order_of(entry: Mapping[str, Any]) -> int:
    order = entry.get("order")
    return order if isinstance(order, int) and not isinstance(order, bool) else 0


def starting_set(final_unlocked: Iterable[str], rolls: Sequence[str]) -> frozenset[str]:
    """The unlocked set the run began with, recovered by subtraction.

    See the module docstring: this is what makes a run replayable without its
    base map. It relies on the rolled chunks being distinct and absent from
    the starting set, which `neighbours.py` guarantees - `count_check` is how
    a future violation would surface rather than quietly shifting every step
    along by one.
    """
    return frozenset(final_unlocked) - frozenset(rolls)


def count_check(final_unlocked: Iterable[str], rolls: Sequence[str]) -> bool:
    """Whether the ledger and the payload agree about what was rolled.

    Two things, and it is worth being precise about which - the arithmetic
    cannot see everything it might look like it sees:

    - **no chunk was rolled twice**, and
    - **every rolled chunk is in the final set**, i.e. the payload really did
      gain what the ledger claims.

    What it deliberately cannot detect is a roll of a chunk *already held*:
    subtracting it leaves a set one smaller and the counts still balance, so
    step 0 would silently show one chunk too few. Nothing can catch that from
    these two inputs alone - it needs the base map, which is exactly what
    `replay` is designed not to require. `neighbours.py` never offers an
    unlocked chunk, so the invariant holds upstream rather than here.
    """
    final = frozenset(final_unlocked)
    return len(set(rolls)) == len(rolls) and frozenset(rolls) <= final


def replay(final_unlocked: Iterable[str], ledger: Sequence[Mapping[str, Any]]) -> tuple[Step, ...]:
    """Every state the run passed through, oldest first.

    `len(result)` is `len(ledger) + 1`: one baseline plus one per roll.
    """
    rolls = rolled_chunks(ledger)
    by_chunk = {
        str(entry["chunk_id"]): entry
        for entry in ledger
        if isinstance(entry.get("chunk_id"), str)
    }
    held = set(starting_set(final_unlocked, rolls))

    steps = [
        Step(
            order=0,
            chunk_id=None,
            unlocked=frozenset(held),
            tasks_added={},
            sections_added=0,
            bis_upgrades=0,
        )
    ]
    for index, chunk_id in enumerate(rolls, start=1):
        held.add(chunk_id)
        entry = by_chunk.get(chunk_id, {})
        steps.append(
            Step(
                order=index,
                chunk_id=chunk_id,
                unlocked=frozenset(held),
                tasks_added=_tasks_of(entry),
                sections_added=sum(
                    len(sections) for sections in _mapping(entry, "new_sections").values()
                ),
                bis_upgrades=len(_mapping(entry, "bis_upgrades")),
            )
        )
    return tuple(steps)


def _tasks_of(entry: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    """A record's `new_tasks`, as names per skill.

    The ledger stores each skill's tasks as a *dict* keyed by name, whose
    values carry the level and the flags - which is a shape `unlock.py` needs
    and a timeline does not.
    """
    return {
        skill: tuple(sorted(names))
        for skill, names in _mapping(entry, "new_tasks").items()
        if isinstance(names, dict) and names
    }


def stamp(
    *, chunkinfo: str, tasks_map: str, rates: str, overrides: str, enriched: bool
) -> dict[str, Any]:
    """What a stored hours series was computed against.

    Both writers build it here rather than each rolling their own, because a
    reader compares them field by field: `batch.py` writes one inside a worker
    as a run finishes, and `gui/server.py` writes one when somebody presses
    the button. Two spellings of the same idea would make every stored
    timeline look stale to the other.

    `enriched` records whether `dps_bridge` priced these numbers, and is
    deliberately **not** part of the freshness comparison - see `matches`.
    """
    return {
        "chunkinfo": chunkinfo,
        "tasks_map": tasks_map,
        "rates": rates,
        "overrides": overrides,
        "enriched": enriched,
    }


def matches(stored: Any, current: Mapping[str, Any]) -> bool:
    """Whether a stored stamp still describes the world `current` describes.

    **`enriched` is excluded on purpose.** A simulation prices its rolls with
    the estimator alone, because the derivation is already in hand and costs
    nothing extra; `dps_bridge.enrich` costs ~1.3s a roll on top and would
    have tripled every batch. So the cheap numbers are what a run is born
    with, and the expensive ones are an upgrade you ask for. Comparing
    `enriched` would make the cheap ones read as *stale* the moment the extra
    was installed - which is wrong, they are simply a different, coarser
    answer, and one is worth showing until the other exists.
    """
    if not isinstance(stored, Mapping):
        return False
    return all(stored.get(key) == value for key, value in current.items() if key != "enriched")


def added_hours(previous: "EstimateResult | None", current: "EstimateResult") -> float:
    """The hours of work this roll *added*, on the assumption the rest is done.

    **A diff of what is being costed, not of the totals**, and that is the
    whole of the semantics. A timeline walks one player's history forward, so
    by the time roll k lands, everything roll k-1 opened is behind them - and
    a chunk that merely makes old work *cheaper* has added nothing. Subtracting
    one total from the next says the opposite: it reports the saving as
    negative work, which on a measured early-game run showed a roll at -2.4h.

    So an item counts when it is in this roll's estimate and was not in the
    last one. Quests likewise. Skills contribute `max(0, current - previous)`,
    which is precisely where "we do not care that it got cheaper" is spent.

    **The clamp is the estimator's own.** A filtered `EstimateResult` is built
    and its `buckets` read, rather than a second implementation of the
    per-source rule - and clamping *within* the new set is right under this
    model: if the earlier grind is finished you are not standing there any
    more, so the new drop pays full price rather than riding along.

    The consequence, which the panel has to own: **these do not sum to the
    Estimate tab's total.** They are what each roll cost you, not a
    decomposition of what is left.
    """
    if previous is None:
        return round(sum(current.buckets.values()), 4)

    had_items = {item.item for item in previous.items}
    had_tasks = {task.task for task in previous.tasks}
    before = {skill.skill: skill.hours for skill in previous.skills}

    fresh = dataclasses.replace(
        current,
        items=tuple(item for item in current.items if item.item not in had_items),
        tasks=tuple(task for task in current.tasks if task.task not in had_tasks),
        skills=tuple(
            dataclasses.replace(skill, hours=max(0.0, skill.hours - before.get(skill.skill, 0.0)))
            for skill in current.skills
        ),
    )
    return round(sum(fresh.buckets.values()), 4)


def series(
    steps: Sequence[Step],
    totals: Sequence[float] | None = None,
    added: Sequence[float] | None = None,
) -> list[dict[str, Any]]:
    """The per-roll rows the graph draws.

    `added` is what each roll *cost* - see `added_hours` - and is what the bars
    show. `totals` is what was left after it, carried alongside because a
    tooltip reading "and 2,816h to go" is worth having and cannot be recovered
    from the bars: **the bars deliberately do not sum to the total.**

    Both are optional because computing either needs the export and this module
    is pure. A list of the wrong length is refused rather than trusted, so
    `hours` reads `None` - "nobody has computed this" and "this roll added
    nothing" are different answers and a graph that conflates them is lying.
    """
    def fits(values: Sequence[float] | None) -> Sequence[float] | None:
        return values if values is not None and len(values) == len(steps) else None

    use_added, use_totals = fits(added), fits(totals)
    out: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        row = step.as_dict()
        # Step 0 is the world the run started in, not something it did.
        row["hours"] = None if use_added is None or index == 0 else round(use_added[index], 2)
        row["total_hours"] = None if use_totals is None else round(use_totals[index], 2)
        out.append(row)
    return out
