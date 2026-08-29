"""`runs/surrogate.py`: the per-batch cost table and its verdicts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from chunksim.runs import surrogate
from chunksim.runs.surrogate import BIG_HOURS, Guess, Sample


def _table(*rows: tuple[str, set[str], float]) -> dict[str, Any]:
    return surrogate.build(Sample(chunk=c, held=frozenset(h), added=a) for c, h, a in rows)


def test_a_chunks_cost_is_keyed_on_which_big_chunks_are_already_held() -> None:
    """**The bimodal case the context key exists for.** `11574` costs 904 hours
    or nothing depending on whether `11573` came first: the skill requirement
    is attributed to whichever chunk introduces it."""
    table = _table(
        ("11573", set(), 544.0), ("11573", set(), 552.0),
        ("11574", set(), 904.0), ("11574", set(), 903.0),
        ("11574", {"11573"}, 0.02), ("11574", {"11573"}, 0.02),
    )
    assert set(table[surrogate.BIG]) == {"11573", "11574"}
    first = surrogate.lookup(table, "11574", set())
    after = surrogate.lookup(table, "11574", {"11573", "99999"})
    assert first is not None and after is not None
    assert first.median > BIG_HOURS > after.median
    # A chunk that is not big does not shape the context.
    assert surrogate.lookup(table, "11574", {"99999"}) == first


def test_an_unseen_context_falls_back_to_the_chunk_alone() -> None:
    table = _table(("13104", set(), 2.018), ("13104", {"11573"}, 2.018))
    seen = surrogate.lookup(table, "13104", {"11574"})
    assert seen is not None and seen.median == 2.018 and seen.samples == 2
    assert surrogate.lookup(table, "unknown", set()) is None


def test_a_verdict_needs_every_sample_on_one_side_of_the_limit() -> None:
    """Straddling the limit is the case the exact walk exists for, so it is
    never guessed at - whichever side the median sits."""
    assert Guess(median=0.1, low=0.0, high=0.5, samples=3).verdict(25.0) == "under"
    assert Guess(median=900.0, low=544.0, high=1448.0, samples=3).verdict(25.0) == "over"
    assert Guess(median=8.0, low=7.6, high=34.0, samples=4).verdict(25.0) == "uncertain"
    # A single sample says nothing about spread and is never enough.
    assert Guess(median=0.0, low=0.0, high=0.0, samples=1).verdict(25.0) == "uncertain"
    # The limit itself is not over: the grind stops on `cost > limit`.
    assert Guess(median=25.0, low=25.0, high=25.0, samples=2).verdict(25.0) == "under"


def test_samples_come_from_exact_rolls_only_and_carry_what_was_held() -> None:
    """`added[0]` is the baseline; a guessed index must not teach the table,
    while a root-discard skip (exact zero) must."""
    rows = surrogate.samples_from(
        base_held=["1"], rolled=["A", "B", "C"], added=[0.0, 5.0, 0.0, 7.0], guessed=[3]
    )
    assert [(s.chunk, sorted(s.held), s.added) for s in rows] == [
        ("A", ["1"], 5.0),
        ("B", ["1", "A"], 0.0),
    ]


def test_the_table_pickles_as_plain_data() -> None:
    import pickle

    table = _table(("A", set(), 1.0), ("A", {"B"}, 2.0), ("B", set(), 30.0))
    again = pickle.loads(pickle.dumps(table))
    assert again == table
    assert surrogate.lookup(again, "A", {"B"}) == surrogate.lookup(table, "A", {"B"})


@pytest.mark.slow
@pytest.mark.real_cache
def test_a_surrogate_batch_stops_every_run_where_the_exact_one_does(
    real_export: Any, real_tasks_map: dict[str, str], tmp_path: Path
) -> None:
    """**The whole evidence for the surrogate, and it is measurement.**

    A guessed roll can only ever be one whose every sample sat on one side of
    the limit, so the stopping decision should be the exact path's whether or
    not a roll took the table. That is the claim; this runs a real batch both
    ways from the same seeds and compares each run's outcome, step and chunk,
    and asserts the table was actually consulted so the comparison means
    something. Minutes, not seconds - hence `slow`.
    """
    from chunksim.runs import grind
    from chunksim.runs.batch import run_batch
    from chunksim.store.cache import data_root, read_cache
    from chunksim.store.derived_cache import CacheBehaviour

    envelope = read_cache("fray", root=data_root())
    payload = envelope["data"]
    decisions: dict[str, dict[int, tuple[Any, Any, Any]]] = {}
    guessed = 0
    for label, fraction in (("exact", None), ("surrogate", 0.2)):
        root = tmp_path / label
        (root / "cache" / "maps").mkdir(parents=True)
        (root / "cache" / "derived").mkdir(parents=True)
        (root / "src").mkdir()
        for link in ("cache/reference", "cache/maps/fetched", "pyproject.toml", "src/chunksim"):
            (root / link).symlink_to(data_root() / link)
        batch = run_batch(
            name=f"surrogate-oracle-{label}", payload=payload, base_map="fray",
            rolls=8, runs=16, jobs=4, seed=20260829, root=root,
            cache_behaviour=CacheBehaviour.ALL, body=grind.run_grind,
            legs=grind.leg_plan(), stop_over_hours=25.0, surrogate=fraction,
        )
        rows: dict[int, tuple[Any, Any, Any]] = {}
        for result in batch.runs:
            outcome = result.extra.get("grind", {})
            rows[result.seed] = (outcome.get("outcome"), outcome.get("step"), outcome.get("chunk"))
            guessed += len(result.extra.get("provisional_added") or ()) if label == "surrogate" else 0
        decisions[label] = rows

    assert set(decisions["exact"]) == set(decisions["surrogate"])
    differing = [
        seed for seed in decisions["exact"]
        if decisions["exact"][seed] != decisions["surrogate"][seed]
    ]
    assert not differing, f"runs whose stopping decision the surrogate changed: {differing}"
    assert guessed, "no roll was ever priced from the table, so this asserts nothing"
