"""Rolling until a chunk is too expensive - see `runs/grind.py` for why the
stopping point being the measurement is what makes this a second kind of run
rather than a flag on the first.

Hand-built chunkinfo throughout, in a `tmp_path` root, so nothing here reads
the developer's own cache. The rates blob is empty on purpose: `_Pricer.build`
only needs it to *exist* (`scraped_found`), and an empty one makes every
estimate zero - which is exactly what a test of the *stopping rule* wants,
since it can then place the threshold either side of zero and know which way
the run must go.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from chunksim.runs import grind
from chunksim.runs.batch import run_batch
from chunksim.store.cache import read_sim_batch, write_blob

#: `test_batch.py`'s own shape: 100 starts unlocked, three grid neighbours
#: declare a connection back to it, so a roll has candidates and seeds diverge.
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


@pytest.fixture
def root(tmp_path: Path, no_ambient_chunkinfo: None) -> Path:
    """A cache root holding just enough to roll and to price."""
    write_blob("chunkinfo", _CHUNKINFO, "test", root=tmp_path)
    write_blob("wiki_rates", {}, "test", root=tmp_path)
    return tmp_path


def _grind(root: Path, *, name: str, hours: float, runs: int = 1, jobs: int = 1) -> Any:
    return run_batch(
        name=name,
        payload=_PAYLOAD,
        base_map="fray",
        rolls=grind.MAX_ROLLS,
        runs=runs,
        seed=7,
        jobs=jobs,
        root=root,
        body=grind.run_grind,
        stop_over_hours=hours,
        extra={"origin": "grind", "grind": {"hours": hours, "simulations": runs}},
    )


def _runs(root: Path, name: str) -> list[dict[str, Any]]:
    return list(read_sim_batch(name, root)["runs"])


class TestStopping:
    def test_a_threshold_nothing_reaches_runs_until_the_pool_is_empty(
        self, root: Path
    ) -> None:
        """**`stuck` is a real answer, not a failure.** With an empty rate
        scrape every roll adds zero hours, so no roll can ever exceed a
        positive threshold - the run rolls out the whole reachable map and
        stops because there is nothing left, which is the "completed the map"
        case."""
        batch = _grind(root, name="Wall", hours=1.0)

        run = _runs(root, "Wall")[0]
        assert run["grind"]["reason"] == grind.STUCK
        assert run["grind"]["chunk"] is None
        # Six reachable chunks besides the one it started on.
        assert len(run["rolls"]) == 6

    def test_the_roll_that_crossed_the_threshold_is_kept_and_named(
        self, root: Path
    ) -> None:
        """**The seam this whole design rests on.** `should_stop` is checked at
        the top of the *next* iteration, so the roll that tripped it has
        already been recorded - which is what makes it nameable as the wall
        rather than merely the reason a run is one roll shorter.

        A threshold below zero is crossed by the very first roll, every roll
        adding exactly zero here.
        """
        batch = _grind(root, name="First", hours=-1.0)

        run = _runs(root, "First")[0]
        assert run["grind"]["reason"] == grind.OVER
        assert run["grind"]["step"] == 1
        assert len(run["rolls"]) == 1
        # The chunk named is the one actually rolled, not an off-by-one.
        assert run["grind"]["chunk"] == run["rolls"][0]

    def test_the_cap_is_reported_rather_than_passed_off_as_a_wall(
        self, root: Path
    ) -> None:
        """A run that gives up is `capped`, never `over` with its last roll
        named - see `MAX_ROLLS`. Every roll adds zero, so only the cap can
        stop this one."""
        batch = run_batch(
            name="Capped", payload=_PAYLOAD, base_map="fray",
            rolls=2, runs=1, seed=7, root=root,
            body=grind.run_grind, stop_over_hours=1.0,
        )

        run = _runs(root, "Capped")[0]
        assert run["grind"]["reason"] == grind.CAPPED
        assert run["grind"]["chunk"] is None
        assert len(run["rolls"]) == 2


class TestWhatItWrites:
    def test_a_grind_run_is_an_ordinary_cached_map_with_a_timeline(
        self, root: Path
    ) -> None:
        """Everything the drill-down needs comes free from writing what a roll
        simulation writes - which is the reason it does."""
        from chunksim.store.cache import read_cache, read_rolls, read_timeline

        _grind(root, name="Shape", hours=1.0)

        envelope = read_cache("Shape/run-001", root)
        assert envelope["is_simulated"] is True
        assert read_rolls("Shape/run-001", root)
        stored = read_timeline("Shape/run-001", root)
        # One baseline plus one per roll, the shape `timeline.series` expects.
        assert len(stored["added"]) == len(stored["totals"])
        assert len(stored["added"]) == len(envelope["simulation"]["rolls"]) + 1

    def test_the_series_says_it_was_priced_roll_by_roll(self, root: Path) -> None:
        """The stamp is the only thing separating these numbers from a roll
        simulation's, so it has to be there - see `timeline.FINAL_BASIS`."""
        from chunksim.runs.timeline import PER_STEP_BASIS
        from chunksim.store.cache import read_timeline

        _grind(root, name="Basis", hours=1.0)

        stored = read_timeline("Basis/run-001", root)
        assert stored["stamp"]["basis"] == PER_STEP_BASIS

    def test_a_roll_simulation_still_says_it_was_priced_on_the_final_state(
        self, root: Path
    ) -> None:
        """The other half of the same claim: adding a basis must not have
        silently relabelled what was already there."""
        from chunksim.runs.timeline import FINAL_BASIS
        from chunksim.store.cache import read_timeline

        run_batch(
            name="Roll", payload=_PAYLOAD, base_map="fray",
            rolls=2, runs=1, seed=7, root=root,
        )

        assert read_timeline("Roll/run-001", root)["stamp"]["basis"] == FINAL_BASIS

    def test_the_batch_records_what_was_asked_for(self, root: Path) -> None:
        """`extra` is how a run kind's own request reaches `batch.json`, and
        the summary is read straight back by the results overlay."""
        _grind(root, name="Asked", hours=42.0, runs=2)

        summary = read_sim_batch("Asked", root)
        assert summary["origin"] == "grind"
        assert summary["grind"] == {"hours": 42.0, "simulations": 2}
        # And nothing a batch always has was displaced by it.
        assert summary["base_map"] == "fray"


def test_jobs_changes_where_a_grind_executes_and_nothing_else(root: Path) -> None:
    """The parallelism guarantee, for the second kind of run.

    `tests/test_batch.py` pins this for rolls; a grind needs its own because it
    carries something a roll does not - a stopping decision made inside the
    worker. A rule that had leaked into shared state would show up here as two
    arms disagreeing about where a run stopped, which is exactly the failure
    `runs/__init__.py`'s "`--jobs` never changes a result" is a promise about.
    """
    serial = _grind(root, name="Serial", hours=-1.0, runs=4, jobs=1)
    parallel = _grind(root, name="Pool", hours=-1.0, runs=4, jobs=2)

    assert [(r.seed, r.rolls) for r in serial.runs] == [
        (r.seed, r.rolls) for r in parallel.runs
    ]
    assert [run["grind"] for run in _runs(root, "Serial")] == [
        run["grind"] for run in _runs(root, "Pool")
    ]


class TestCollate:
    """`collate` is pure and names no chunk - see its docstring. Fed hand-built
    run entries rather than a real batch, which is what keeps these instant."""

    @staticmethod
    def _run(
        name: str, chunks: int, reason: str, chunk: str | None, hours: float | None
    ) -> dict[str, Any]:
        return {
            "run": name,
            "rolls": [str(n) for n in range(chunks)],
            "grind": {"reason": reason, "chunk": chunk, "step": chunks, "hours": hours},
        }

    def test_shares_are_of_every_grind_not_only_the_walled_ones(self) -> None:
        """Otherwise a map where most grinds simply run out of chunks reads as
        though one chunk were responsible for all of them."""
        found = grind.collate([
            self._run("run-001", 3, grind.OVER, "1111", 600.0),
            self._run("run-002", 4, grind.OVER, "1111", 700.0),
            self._run("run-003", 5, grind.STUCK, None, None),
            self._run("run-004", 6, grind.STUCK, None, None),
        ])

        assert [wall["chunk"] for wall in found["chunks"]] == ["1111"]
        assert found["chunks"][0]["share"] == pytest.approx(0.5)
        assert found["unwalled"] == {grind.STUCK: 2}

    def test_the_mean_is_over_the_grinds_that_ended_there(self) -> None:
        found = grind.collate([
            self._run("run-001", 3, grind.OVER, "1111", 600.0),
            self._run("run-002", 4, grind.OVER, "1111", 700.0),
        ])

        assert found["chunks"][0]["mean_hours"] == pytest.approx(650.0)

    def test_the_drilldown_is_ordered_longest_first(self) -> None:
        found = grind.collate([
            self._run("run-001", 3, grind.OVER, "1111", 100.0),
            self._run("run-002", 4, grind.OVER, "1111", 900.0),
            self._run("run-003", 5, grind.OVER, "1111", 500.0),
        ])

        assert [at["hours"] for at in found["chunks"][0]["at"]] == [900.0, 500.0, 100.0]

    def test_walls_are_ordered_by_how_often_they_stop_a_grind(self) -> None:
        found = grind.collate([
            self._run("run-001", 3, grind.OVER, "2222", 100.0),
            self._run("run-002", 4, grind.OVER, "1111", 100.0),
            self._run("run-003", 5, grind.OVER, "1111", 100.0),
        ])

        assert [wall["chunk"] for wall in found["chunks"]] == ["1111", "2222"]

    def test_a_tie_breaks_on_the_chunk_id_so_the_order_is_stable(self) -> None:
        """Two identical batches must not list their walls differently - a
        table read top-down that reshuffles is a bug report waiting to
        happen."""
        rows = [
            self._run("run-001", 3, grind.OVER, "2222", 100.0),
            self._run("run-002", 4, grind.OVER, "1111", 100.0),
        ]

        assert [w["chunk"] for w in grind.collate(rows)["chunks"]] == ["1111", "2222"]
        assert [w["chunk"] for w in grind.collate(rows[::-1])["chunks"]] == ["1111", "2222"]

    def test_the_distribution_is_dense(self) -> None:
        """**A chunk count nobody hit is a real zero.** Left out, the histogram
        misreports the shape of the distribution rather than merely omitting a
        bar - two runs at 3 and two at 6 is not the same picture as two
        adjacent columns."""
        found = grind.collate([
            self._run("run-001", 3, grind.STUCK, None, None),
            self._run("run-002", 6, grind.STUCK, None, None),
        ])

        assert found["distribution"] == [
            {"chunks": 3, "runs": 1},
            {"chunks": 4, "runs": 0},
            {"chunks": 5, "runs": 0},
            {"chunks": 6, "runs": 1},
        ]

    def test_a_run_that_recorded_no_grind_is_carried_not_dropped(self) -> None:
        """So the count on screen and the directory on disk agree - a run
        written before this existed, or one that failed to price, is still a
        run that happened."""
        found = grind.collate([
            {"run": "run-001", "rolls": ["1", "2"]},
            self._run("run-002", 3, grind.OVER, "1111", 100.0),
        ])

        assert [row["outcome"] for row in found["runs"]] == [None, grind.OVER]
        # And it counts against the share, being a grind that ended somewhere.
        assert found["chunks"][0]["share"] == pytest.approx(0.5)

    def test_it_names_no_chunk(self) -> None:
        """`runs/` is self-contained and never parses the export, so a chunk is
        an id here and the page joins the name it already holds."""
        found = grind.collate([self._run("run-001", 3, grind.OVER, "1111", 100.0)])

        assert set(found["chunks"][0]) == {"chunk", "runs", "share", "mean_hours", "at"}
        assert found["chunks"][0]["chunk"] == "1111"

    def test_nothing_at_all_is_an_empty_answer_rather_than_a_crash(self) -> None:
        found = grind.collate([])

        assert found == {"runs": [], "distribution": [], "chunks": [], "unwalled": {}}
