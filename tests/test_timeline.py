"""Tests for replaying a simulated run.

The property that matters is that a run replays *without its base map* - that
is what makes a timeline a JSON read rather than a derivation, so it is
asserted directly rather than assumed from the arithmetic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fray_claude.runs.batch import run_batch
from fray_claude.store.cache import ROLLS_FILE_NAME, read_cache, sims_root, write_blob, write_cache
from fray_claude.costing.estimate import EstimateResult, ItemEstimate, SkillEstimate
from fray_claude.runs.timeline import (
    Step,
    added_hours,
    count_check,
    replay,
    rolled_chunks,
    series,
    starting_set,
)

#: 100 starts unlocked; its grid neighbours declare a connection back, so a
#: roll has somewhere to go. Same shape as `tests/test_batch.py`'s.
_CHUNKINFO: dict[str, Any] = {
    "sections": {
        "99": {"0": ["100"]},
        "101": {"0": ["100"]},
        "356": {"0": ["100"]},
        "98": {"0": ["99"]},
        "102": {"0": ["101"]},
        "612": {"0": ["356"]},
    }
}

_PAYLOAD: dict[str, Any] = {"chunks": {"unlocked": {"100": "100"}}}


def _record(order: int, chunk_id: str, **kw: Any) -> dict[str, Any]:
    return {
        "order": order,
        "chunk_id": chunk_id,
        "new_sections": kw.get("sections", {}),
        "new_tasks": kw.get("tasks", {}),
        "new_unsupported": [],
        "bis_upgrades": kw.get("bis", {}),
    }


@pytest.fixture
def root(tmp_path: Path, no_ambient_chunkinfo: None) -> Path:
    write_blob("chunkinfo", _CHUNKINFO, "test", root=tmp_path)
    return tmp_path


def test_a_run_replays_one_state_per_roll_plus_a_baseline() -> None:
    ledger = [_record(1, "101"), _record(2, "102"), _record(3, "99")]

    steps = replay({"100", "101", "102", "99"}, ledger)

    assert len(steps) == 4
    assert [s.order for s in steps] == [0, 1, 2, 3]
    assert [s.chunk_id for s in steps] == [None, "101", "102", "99"]
    assert [sorted(s.unlocked) for s in steps] == [
        ["100"],
        ["100", "101"],
        ["100", "101", "102"],
        ["100", "101", "102", "99"],
    ]


def test_the_starting_set_is_whatever_the_rolls_did_not_add() -> None:
    """The subtraction that makes a run self-contained."""
    assert starting_set({"100", "101", "102"}, ["101", "102"]) == frozenset({"100"})
    assert count_check({"100", "101", "102"}, ["101", "102"])


@pytest.mark.parametrize(
    ("final", "rolls"),
    [
        ({"100", "101"}, ["101", "101"]),        # a chunk rolled twice
        ({"100", "101"}, ["101", "999"]),        # a roll the payload never gained
    ],
)
def test_a_ledger_that_does_not_account_for_the_payload_is_reported(
    final: set[str], rolls: list[str]
) -> None:
    """Neither is possible today and both would shift every step by one."""
    assert not count_check(final, rolls)


def test_the_check_cannot_see_a_roll_of_a_chunk_already_held() -> None:
    """**Stated as a test so the guarantee is not read as stronger than it is.**

    Subtracting an already-held chunk leaves a set one smaller and the counts
    still balance, so step 0 would quietly show one chunk too few. Catching it
    needs the base map, which is the very thing `replay` is built not to
    require - so the invariant lives in `neighbours.py`, which never offers an
    unlocked chunk, and not here.
    """
    assert count_check({"100", "101"}, ["100"])
    assert starting_set({"100", "101"}, ["100"]) == frozenset({"101"})


def test_rolls_are_ordered_by_the_record_not_the_file() -> None:
    """The ledger is what dates a step; a reordered file must not invent a
    sequence that never happened."""
    shuffled = [_record(3, "99"), _record(1, "101"), _record(2, "102")]

    assert rolled_chunks(shuffled) == ("101", "102", "99")


def test_a_step_counts_what_its_roll_added() -> None:
    ledger = [
        _record(
            1,
            "101",
            tasks={"Slayer": {"~|abyssal whip|~": {"level": 85}}, "Mining": {}},
            sections={"101": {"0": True, "1": True}},
            bis={"melee/weapon": ["", "whip"]},
        )
    ]

    step = replay({"100", "101"}, ledger)[1]

    assert step.task_count == 1
    # An empty skill is not a skill with tasks - it must not reach the graph.
    assert step.as_dict()["tasks_by_skill"] == {"Slayer": 1}
    assert step.sections_added == 2
    assert step.bis_upgrades == 1
    # The raw markup-bearing key survives; stripping is display-only.
    assert step.tasks_added["Slayer"] == ("~|abyssal whip|~",)


def test_the_baseline_step_has_no_bar_and_no_chunk() -> None:
    """Step 0 is where the run *started*, not something it did."""
    steps = replay({"100", "101"}, [_record(1, "101")])

    rows = series(steps, totals=[10.0, 12.5], added=[0.0, 4.0])

    assert rows[0]["chunk"] is None and rows[0]["hours"] is None
    # The bar is what the roll cost; the total is carried for the tooltip.
    assert rows[1]["hours"] == 4.0
    assert rows[1]["total_hours"] == 12.5


def test_hours_are_none_rather_than_zero_when_nobody_computed_them() -> None:
    """**"Not computed" and "added no work" are different answers.**

    Both are common - most rolls of a real run add nothing - so a graph that
    drew them the same would be unreadable *and* wrong.
    """
    steps = replay({"100", "101"}, [_record(1, "101")])

    assert [row["hours"] for row in series(steps)] == [None, None]
    # A list that does not line up is refused for the same reason: a run
    # re-rolled under one name has a different number of steps.
    assert [row["hours"] for row in series(steps, added=[1.0])] == [None, None]


def test_a_falling_total_is_not_negative_work() -> None:
    """**The semantics the bars were changed to.**

    The estimate really can go down - a new chunk can open a cheaper route to
    something already needed, measured at -2.4h on step 6 of a 12-roll early
    map. But a timeline walks one history forward, so by then the earlier work
    is behind you and the saving is not something this roll *did*. The bar is
    `added_hours`, which is a diff of what is being costed rather than of the
    totals, so it never reports a saving as negative work.
    """
    steps = replay({"100", "101"}, [_record(1, "101")])

    rows = series(steps, totals=[17.9, 15.5], added=[0.0, 0.0])

    assert rows[1]["hours"] == 0.0
    assert rows[1]["total_hours"] == 15.5, "the total still fell, and still says so"


def test_an_empty_ledger_still_has_its_baseline() -> None:
    steps = replay({"100"}, [])

    assert len(steps) == 1 and steps[0] == Step(0, None, frozenset({"100"}), {}, 0, 0)


def test_a_real_run_replays_to_the_payload_simulate_wrote(root: Path) -> None:
    """**The end-to-end property, against a batch this test actually rolled.**

    Every intermediate state is checked against the arithmetic, and the last
    one against the payload on disk - so a drift between what `simulate`
    saves and what this replays fails here rather than on screen.
    """
    write_cache("base", _PAYLOAD, root=root)
    batch = run_batch(
        name="tl", payload=_PAYLOAD, base_map="base", rolls=4, seed=11, root=root
    )
    run = sims_root(root) / batch.name / batch.runs[0].name
    ledger = json.loads((run / ROLLS_FILE_NAME).read_text())["rolls"]
    final = read_cache(f"{batch.name}/{batch.runs[0].name}", root)["data"]["chunks"]["unlocked"]

    steps = replay(final, ledger)

    assert count_check(final, rolled_chunks(ledger))
    assert len(steps) == 5
    assert steps[0].unlocked == frozenset({"100"}), "the run started where the base map was"
    assert steps[-1].unlocked == frozenset(final)
    # Each step adds exactly its own chunk and nothing else.
    for before, after in zip(steps, steps[1:]):
        assert after.unlocked - before.unlocked == {after.chunk_id}


def test_a_run_replays_with_its_base_map_deleted(root: Path) -> None:
    """**What makes a timeline a JSON read.** The run carries its own past, so
    nothing has to still be on disk for it to be stepped through."""
    write_cache("base", _PAYLOAD, root=root)
    batch = run_batch(
        name="tl", payload=_PAYLOAD, base_map="base", rolls=3, seed=5, root=root
    )
    map_id = f"{batch.name}/{batch.runs[0].name}"
    final = read_cache(map_id, root)["data"]["chunks"]["unlocked"]
    ledger = json.loads(
        (sims_root(root) / batch.name / batch.runs[0].name / ROLLS_FILE_NAME).read_text()
    )["rolls"]

    (root / "cache" / "maps" / "fetched" / "base.json").unlink()

    steps = replay(final, ledger)

    assert steps[0].unlocked == frozenset({"100"})
    assert len(steps) == 4


# --- what a roll cost ------------------------------------------------------


def _result(*, items: Any = (), tasks: Any = (), skills: Any = ()) -> EstimateResult:
    return EstimateResult(items=tuple(items), tasks=tuple(tasks), skills=tuple(skills))


def _item(name: str, hours: float, source: str = "", bucket: str = "boss drops") -> ItemEstimate:
    return ItemEstimate(item=name, bucket=bucket, hours=hours, source=source or name)


def _skill(name: str, hours: float) -> SkillEstimate:
    return SkillEstimate(
        skill=name, goal="g", current_level=1, target_level=99, xp=1,
        xp_per_hour=1.0, method="m", hours=hours,
    )


def test_a_roll_is_charged_for_what_it_newly_put_in_front_of_you() -> None:
    before = _result(items=[_item("whip", 10.0)])
    after = _result(items=[_item("whip", 10.0), _item("tentacle", 4.0)])

    assert added_hours(before, after) == 4.0


def test_an_item_you_already_had_to_get_is_not_charged_twice() -> None:
    """Even if it got cheaper. By the time this roll lands the earlier grind
    is behind you, so its new price is not something this roll did."""
    before = _result(items=[_item("whip", 10.0)])
    after = _result(items=[_item("whip", 2.0)])

    assert added_hours(before, after) == 0.0


def test_a_skill_goal_that_moved_up_is_charged_for_the_difference() -> None:
    before = _result(skills=[_skill("Slayer", 100.0)])
    after = _result(skills=[_skill("Slayer", 130.0)])

    assert added_hours(before, after) == 30.0


def test_a_skill_that_got_cheaper_contributes_nothing_rather_than_a_credit() -> None:
    """**Where "we do not care that it got cheaper" is actually spent.**"""
    before = _result(skills=[_skill("Slayer", 100.0)])
    after = _result(skills=[_skill("Slayer", 60.0)])

    assert added_hours(before, after) == 0.0


def test_new_items_off_one_source_are_clamped_together() -> None:
    """The estimator's own per-source rule, reused rather than reimplemented:
    two drops off one monster cost the longer of the two, not their sum."""
    before = _result()
    after = _result(
        items=[
            _item("dagger", 533.0, source="Abyssal demon"),
            _item("head", 100.0, source="Abyssal demon"),
        ]
    )

    assert added_hours(before, after) == 533.0


def test_the_first_roll_is_charged_for_everything() -> None:
    """With nothing before it there is nothing already done, so the baseline
    step carries the whole outstanding cost."""
    after = _result(items=[_item("whip", 10.0)], skills=[_skill("Slayer", 5.0)])

    assert added_hours(None, after) == 15.0
