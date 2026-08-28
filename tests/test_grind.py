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


class TestResuming:
    """**A grind split into legs must be the same grind, roll for roll.**

    This is what lets spare workers be pointed at a straggler: a whole
    simulation inside one pool task cannot be reclaimed, so a long one has to
    be breakable. But the moment the scheduler can split *some* runs and not
    others, `--jobs must never change a result` is only true if a split run
    lands on exactly the answer an unsplit one would - which is why the
    generator position travels in the frontier rather than the seed being
    replayed. See `Frontier.rng_state`.
    """

    @staticmethod
    def _spec(root: Path, name: str, hours: float) -> Any:
        from chunksim.runs.batch import RunSpec
        from chunksim.store.cache import claim_sim_batch, run_dir

        directory = claim_sim_batch(name, root)
        return RunSpec(
            directory=run_dir(directory, 1), name="run-001", seed=7,
            rolls=grind.MAX_ROLLS, payload=_PAYLOAD, base_map="fray",
            base_fetched_at=None, chunkinfo_path=None, root=root,
            stop_over_hours=hours,
        )

    def _legs(self, spec: Any, budget: int) -> Any:
        """Run a grind `budget` rolls at a time until it ends."""
        leg = grind.advance(spec, budget=budget)
        legs = 1
        while not leg.finished:
            leg = grind.advance(spec, leg.frontier, budget=budget)
            legs += 1
        return leg, legs

    def test_one_leg_and_many_reach_the_same_answer(self, root: Path) -> None:
        """The property everything else rests on. A threshold nothing reaches
        makes the run go the distance, so this compares whole sequences rather
        than two runs that both stopped on roll one."""
        whole = grind.advance(self._spec(root, "Whole", 1.0))
        split, legs = self._legs(self._spec(root, "Split", 1.0), budget=2)

        assert legs > 1, "the budget has to actually split it"
        assert whole.frontier.rolled == split.frontier.rolled
        assert whole.frontier.added == split.frontier.added
        assert whole.frontier.totals == split.frontier.totals
        assert whole.outcome == split.outcome

    def test_a_split_run_names_the_same_terminating_step(self, root: Path) -> None:
        """Steps are numbered against the whole grind, not the leg - so a
        wall found on roll 5 says 5 however the work was divided."""
        whole = grind.advance(self._spec(root, "W2", -1.0))
        split, _ = self._legs(self._spec(root, "S2", -1.0), budget=1)

        assert whole.outcome is not None and split.outcome is not None
        assert whole.outcome.reason == split.outcome.reason == grind.OVER
        assert whole.outcome.step == split.outcome.step
        assert whole.outcome.chunk == split.outcome.chunk

    def test_the_priced_series_is_not_duplicated_at_a_seam(self, root: Path) -> None:
        """A resumed leg re-derives the step it starts from, as its own step 0.
        Kept as the diff baseline and never priced again - otherwise the series
        would gain an entry per seam and every bar after it would shift."""
        leg, _ = self._legs(self._spec(root, "Seam", 1.0), budget=2)

        # One baseline plus one per roll, whatever the seams did.
        assert len(leg.frontier.added) == len(leg.frontier.rolled) + 1
        assert len(leg.frontier.totals) == len(leg.frontier.rolled) + 1

    @pytest.mark.parametrize("budget", [1, 2, 3, 5])
    def test_the_answer_does_not_depend_on_where_the_seams_fall(
        self, root: Path, budget: int
    ) -> None:
        """Not just "splitting works" but "any splitting works" - the
        scheduler chooses budgets from how busy the pool is, so the seams land
        wherever the machine happened to be."""
        whole = grind.advance(self._spec(root, f"Base{budget}", 1.0))
        split, _ = self._legs(self._spec(root, f"At{budget}", 1.0), budget=budget)

        assert split.frontier.rolled == whole.frontier.rolled
        assert split.frontier.added == whole.frontier.added

    def test_a_frontier_carries_its_state_across_a_pickle(self, root: Path) -> None:
        """It crosses a process boundary every leg, so it has to survive one -
        `random.Random().getstate()` in particular, which is a nested tuple
        rather than a plain scalar."""
        import pickle

        first = grind.advance(self._spec(root, "Pickled", 1.0), budget=2)
        revived = pickle.loads(pickle.dumps(first.frontier))
        direct = grind.advance(self._spec(root, "Direct", 1.0), first.frontier, budget=2)
        through = grind.advance(self._spec(root, "Through", 1.0), revived, budget=2)

        assert direct.frontier.rolled == through.frontier.rolled
        assert direct.frontier.added == through.frontier.added


class TestTheWavefront:
    """Rolling blind, then pricing the result in parallel.

    The trade is that a step past the wall is priced for nothing - which is
    only acceptable when the workers doing it would otherwise be idle. What
    must never differ is the *answer*: whichever steps get priced, the grind
    ends on the first one over the threshold.
    """

    @staticmethod
    def _spec(root: Path, name: str, hours: float) -> Any:
        from chunksim.runs.batch import RunSpec
        from chunksim.store.cache import claim_sim_batch, run_dir

        directory = claim_sim_batch(name, root)
        return RunSpec(
            directory=run_dir(directory, 1), name="run-001", seed=7,
            rolls=grind.MAX_ROLLS, payload=_PAYLOAD, base_map="fray",
            base_fetched_at=None, chunkinfo_path=None, root=root,
            stop_over_hours=hours,
        )

    def test_it_rolls_the_same_chunks_the_sequential_run_does(self, root: Path) -> None:
        """Rolling is a pure function of the seed - pricing only decides where
        to cut - which is the property the whole wavefront rests on."""
        straight = grind.advance(self._spec(root, "Straight", 1.0))
        wave = grind.roll_ahead(self._spec(root, "Wave", 1.0), None, depth=6)

        assert tuple(step.chunk_id for step in wave.steps) == straight.frontier.rolled

    def test_a_wave_step_prices_the_same_as_the_sequential_one(
        self, root: Path
    ) -> None:
        """The parallel half has to agree with the serial half figure for
        figure, or the wavefront would answer a different question fast."""
        spec = self._spec(root, "Agree", 1.0)
        straight = grind.advance(self._spec(root, "Serial", 1.0))
        wave = grind.roll_ahead(spec, None, depth=4)

        # Step 2, priced out of band: its predecessor is step 1's derivation,
        # and `held` is the base set plus both rolls.
        held = {"100": True, wave.steps[0].chunk_id: True, wave.steps[1].chunk_id: True}
        added, total = grind.price_wave(
            spec, held, wave.steps[0].derived, wave.steps[1].derived
        )

        assert added == pytest.approx(straight.frontier.added[2])
        assert total == pytest.approx(straight.frontier.totals[2])

    def test_a_wave_stops_at_the_pool_rather_than_inventing_rolls(
        self, root: Path
    ) -> None:
        """Asked for more depth than the map has left, it reports that it ran
        out - so the scheduler knows there is nothing after this wave."""
        wave = grind.roll_ahead(self._spec(root, "Short", 1.0), None, depth=50)

        assert len(wave.steps) == 6, "six reachable chunks besides the start"
        assert wave.exhausted is True

    def test_a_wave_resumes_from_a_frontier_like_a_leg_does(self, root: Path) -> None:
        """The scheduler alternates between the two, so they have to agree
        about where a run has got to."""
        leg = grind.advance(self._spec(root, "Part", 1.0), budget=2)
        wave = grind.roll_ahead(self._spec(root, "Rest", 1.0), leg.frontier, depth=4)
        straight = grind.advance(self._spec(root, "Whole2", 1.0))

        rolled = leg.frontier.rolled + tuple(s.chunk_id for s in wave.steps)
        assert rolled == straight.frontier.rolled


class TestTheScheduler:
    """`batch._schedule` driving grinds as legs, speculating on the drain.

    Inline pools would not exercise it - it needs more than one worker and more
    than one run - so these use a real `ProcessPoolExecutor` and stay tiny.
    """

    @staticmethod
    def _batch(root: Path, name: str, hours: float, runs: int, jobs: int, **kw: Any) -> Any:
        return run_batch(
            name=name, payload=_PAYLOAD, base_map="fray", rolls=grind.MAX_ROLLS,
            runs=runs, seed=7, jobs=jobs, root=root, body=grind.run_grind,
            stop_over_hours=hours,
            extra={"origin": "grind", "grind": {"hours": hours, "simulations": runs}},
            **kw,
        )

    def test_scheduling_reaches_the_same_answer_as_not(self, root: Path) -> None:
        """**The invariant the whole feature turns on.** The scheduler splits
        some runs and not others, depending on how busy the pool happened to
        be - so if a split changed a single roll, the answer would depend on
        the machine. It must not, and this is where that is checked
        end-to-end rather than at the level of one leg."""
        plain = self._batch(root, "Plain", 1.0, runs=4, jobs=2)
        scheduled = self._batch(root, "Sched", 1.0, runs=4, jobs=2, legs=grind.leg_plan())

        assert [(r.seed, r.rolls) for r in plain.runs] == [
            (r.seed, r.rolls) for r in scheduled.runs
        ]
        assert [run["grind"] for run in _runs(root, "Plain")] == [
            run["grind"] for run in _runs(root, "Sched")
        ]

    def test_a_scheduled_run_writes_what_an_unscheduled_one_writes(
        self, root: Path
    ) -> None:
        """Only the leg that ends a run writes it, so a run built from several
        must land the same directory as one built from a single leg."""
        from chunksim.store.cache import read_cache, read_timeline

        self._batch(root, "Plain2", 1.0, runs=2, jobs=2)
        self._batch(root, "Sched2", 1.0, runs=2, jobs=2, legs=grind.leg_plan())

        for run in ("run-001", "run-002"):
            plain = read_cache(f"Plain2/{run}", root)["data"]
            sched = read_cache(f"Sched2/{run}", root)["data"]
            assert plain["chunks"] == sched["chunks"]
            assert plain["chunkinfo"] == sched["chunkinfo"]
            # **`chunkOrder` is compared by its values, not its keys.** Its
            # keys are wall-clock milliseconds from when the payload was
            # built, so two batches always disagree there and it says nothing
            # about how the work was scheduled. The order is the claim.
            assert list(plain["chunkOrder"].values()) == list(
                sched["chunkOrder"].values()
            )
            assert read_timeline(f"Plain2/{run}", root) == read_timeline(
                f"Sched2/{run}", root
            )

    def test_the_wall_is_found_the_same_way_through_a_wave(self, root: Path) -> None:
        """A wave rolls past the wall and `settle` cuts back to it, so a
        speculated run must not record the extra rolls it took."""
        plain = self._batch(root, "P3", -1.0, runs=3, jobs=2)
        sched = self._batch(root, "S3", -1.0, runs=3, jobs=2, legs=grind.leg_plan())

        for a, b in zip(_runs(root, "P3"), _runs(root, "S3")):
            assert a["grind"]["reason"] == b["grind"]["reason"] == grind.OVER
            assert a["grind"]["step"] == b["grind"]["step"]
            assert a["grind"]["chunk"] == b["grind"]["chunk"]
            assert len(a["rolls"]) == len(b["rolls"])

    def test_one_worker_or_one_run_never_schedules(self, root: Path) -> None:
        """Neither can drain into an idle stretch, so a leg boundary would be
        pure overhead - the ordinary path has to stay exactly what it was."""
        alone = self._batch(root, "Alone", 1.0, runs=1, jobs=4, legs=grind.leg_plan())
        serial = self._batch(root, "Serial2", 1.0, runs=3, jobs=1, legs=grind.leg_plan())

        assert len(alone.runs) == 1
        assert len(serial.runs) == 3


class TestTheWalkCarry:
    """Adopting the previous roll's item table, and the check that guards it.

    Measured at **0% churn over 14 consecutive rolls** of the real map - of
    ~1,180 priced items, not one answer moved when a chunk was rolled, because
    a roll only adds providers and a route that existed still costs what it
    cost. That is evidence, not proof, which is why `advance` re-prices the
    state its leg ends on from cold and refuses a mismatch. Exactly the
    discipline `pipeline.derive`'s area carry keeps.
    """

    @staticmethod
    def _spec(root: Path, name: str, hours: float) -> Any:
        from chunksim.runs.batch import RunSpec
        from chunksim.store.cache import claim_sim_batch, run_dir

        directory = claim_sim_batch(name, root)
        return RunSpec(
            directory=run_dir(directory, 1), name="run-001", seed=7,
            rolls=grind.MAX_ROLLS, payload=_PAYLOAD, base_map="fray",
            base_fetched_at=None, chunkinfo_path=None, root=root,
            stop_over_hours=hours,
        )

    def test_a_carried_leg_prices_what_a_cold_one_does(self, root: Path) -> None:
        """The carry must not move a single figure - and `advance` would have
        raised before returning if it had, so reaching the assertions is
        already half the claim."""
        carried = grind.advance(self._spec(root, "Carried", 1.0))
        # A leg of one roll at a time inherits nothing across its seams, so
        # this is the same run with the carry largely defeated.
        cold = grind.advance(self._spec(root, "Cold", 1.0), budget=1)
        while not cold.finished:
            cold = grind.advance(self._spec(root, "Cold", 1.0), cold.frontier, budget=1)

        assert carried.frontier.rolled == cold.frontier.rolled
        assert carried.frontier.added == cold.frontier.added
        assert carried.frontier.totals == cold.frontier.totals

    def test_a_diverging_carry_is_refused_rather_than_returned(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """**The guard has to actually fire**, or it is a comment.

        A carry that changed an answer would not crash on its own - it would
        hand back plausible numbers that drift as a run goes on - so the only
        way to know the check works is to corrupt the comparison and watch it
        refuse. Driven directly rather than through a leg: `recipe_priced`
        returns early on a map with no recipe corpus, so this fixture never
        reaches the code a full grind exercises.
        """
        from chunksim.costing.heuristics import Heuristics
        from chunksim.costing.inputs import _Reuse
        from chunksim.store.derived_cache import cached_derive

        spec = self._spec(root, "Guard", 1.0)
        setup = grind._Setup.of(spec)
        derived = cached_derive(setup.state, setup.unlocked, setup.digests, root=root)
        pricer = grind._StepPricer(
            state=setup.state, base=setup.base, held=[dict(setup.unlocked)],
            limit=1.0, cap=1, previous=derived,
            reuse=_Reuse(settled={}, computed={"Nope": ()}),
        )

        # Agreeing is the ordinary case and must not raise.
        monkeypatch.setattr(
            "chunksim.runs.grind.recipe_priced",
            lambda *a, **k: (Heuristics(computed={"Nope": ()}), None),
        )
        grind._verify_carried_prices(spec, setup, pricer)

        # Disagreeing is the case the guard exists for.
        monkeypatch.setattr(
            "chunksim.runs.grind.recipe_priced",
            lambda *a, **k: (Heuristics(computed={"Different": ()}), None),
        )
        with pytest.raises(grind.PriceCarryDivergedError):
            grind._verify_carried_prices(spec, setup, pricer)


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
