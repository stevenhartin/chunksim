"""Tests for `gui/actions.py`: the eleven POSTs and the jobs they hand work to.

`handle_request` is pure - strings in, a `Response` out - so every test
here exercises the real routing without binding a socket.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import threading
from types import SimpleNamespace
import time
from http import HTTPStatus
from pathlib import Path
from typing import Any

import pytest

from chunksim.model.rules import DEFAULT_RULES
from chunksim.remote.api import FetchError
from chunksim.store import cache
from chunksim.gui.browser import window_flags
from chunksim.gui.server import Context, Response, handle_request


LUMBRIDGE = "12850"

NORTH = "12851"  # one region north of Lumbridge


class _FakeBatch:
    """Stands in for `batch.run_batch`, which would want a real export."""

    def __init__(self, name: str, runs: int, on_complete: Any) -> None:
        self.name = name
        self.runs = [_FakeRun(f"run-{n:03d}") for n in range(1, runs + 1)]
        for run in self.runs:
            if on_complete:
                on_complete(run)


class _FakeRun:
    def __init__(self, name: str) -> None:
        self.name = name
        self.unlocked_chunks = 1
        self.rolls = ("100",)
        self.cancelled = False


def _write_map(root: Path, map_id: str, unlocked: list[str]) -> None:
    """A cached map holding `unlocked`.

    The values are the id strings again, not `True` - that is what the real
    payload holds, and a test that wrote `True` would let a truthiness bug
    through.
    """
    cache.write_cache(
        map_id,
        {"chunks": {"unlocked": {chunk: chunk for chunk in unlocked}}},
        root=root,
    )

@pytest.fixture
def ctx(tmp_path: Path) -> Context:
    _write_map(tmp_path, "fray", [LUMBRIDGE])
    return Context(root=tmp_path)


def _get(path: str, ctx: Context, **query: str) -> Response:
    return handle_request("GET", path, {k: [v] for k, v in query.items()}, ctx)


def _body(response: Response) -> Any:
    return json.loads(response.body.decode("utf-8"))


def _post(path: str, ctx: Context, payload: Any = None, **headers: str) -> Response:
    body = b"" if payload is None else json.dumps(payload).encode("utf-8")
    return handle_request("POST", path, {}, ctx, body=body, headers=headers)


def _wait(ctx: Context, job_id: str, timeout: float = 5.0) -> dict[str, Any]:
    """Poll a job to completion, the way the browser does."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = ctx.jobs.get(job_id)
        assert job is not None
        if job.state != "running":
            return job.as_dict()
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


def _derived_ctx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, chunkinfo: dict[str, Any]
) -> Context:
    """A context whose derivations read a hand-built export.

    Same idiom as `tests/test_cli.py`: patch the reader rather than write a
    10MB file, so the fixture is the few keys under test.
    """
    monkeypatch.setattr(
        "chunksim.gui.derivation.cache.read_chunkinfo",
        lambda override=None, root=None: chunkinfo,
    )
    monkeypatch.setattr(
        "chunksim.gui.derivation.cache.read_blob",
        lambda name, root=None, hint=None: {"data": {}},
    )
    monkeypatch.setattr(
        "chunksim.gui.derivation.cache.file_digest", lambda path: "digest"
    )
    # **Under `tmp_path`, not bare names.** These patch attributes on the
    # *shared* `cache` module, so anything that later writes through
    # `blob_path` writes wherever this points - and `Path("y")` is relative,
    # which put a stray file in the repo root the first time a test using
    # this fixture wrote a blob for real.
    monkeypatch.setattr(
        "chunksim.gui.derivation.cache.chunkinfo_source", lambda o, r: tmp_path / "x"
    )
    monkeypatch.setattr(
        "chunksim.gui.derivation.cache.blob_path", lambda n, r: tmp_path / f"{n}.json"
    )
    return Context(root=tmp_path)


def _capture(registry: Any, action: str, work: Any, seen: list[str]) -> Any:
    """Run a job inline and keep every progress line it emitted."""
    work(seen.append, lambda: False)

    class _Job:
        id = "inline"

    return _Job()


def test_a_simulate_post_returns_a_job_that_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of the job shape: a POST answers before the work does."""
    monkeypatch.setattr(
        "chunksim.gui.actions.run_batch",
        lambda **kw: _FakeBatch(kw["name"], kw["runs"], kw["on_complete"]),
    )
    ctx = Context(root=tmp_path, check_origin=False)
    _write_map(tmp_path, "fray", [LUMBRIDGE])

    response = _post("/api/simulate", ctx, {"map": "fray", "name": "sim", "rolls": 2})

    assert response.status == HTTPStatus.ACCEPTED
    job = _wait(ctx, _body(response)["job"])
    assert job["state"] == "done"
    assert job["result"]["batch"] == "sim"


def test_a_failing_job_reports_its_reason_without_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The traceback names paths on this machine, so it stays in the terminal."""
    def explode(**kw: Any) -> None:
        raise RuntimeError("the pool caught fire")

    monkeypatch.setattr("chunksim.gui.actions.run_batch", explode)
    ctx = Context(root=tmp_path, check_origin=False)
    _write_map(tmp_path, "fray", [LUMBRIDGE])

    response = _post("/api/simulate", ctx, {"map": "fray", "name": "sim", "rolls": 1})
    job = _wait(ctx, _body(response)["job"])

    assert job["state"] == "failed"
    assert job["error"] == "RuntimeError: the pool caught fire"
    assert "Traceback" not in json.dumps(job)


def test_a_bad_base_map_fails_the_post_not_the_job(tmp_path: Path) -> None:
    """Catching it here means the browser sees it immediately, not after a poll."""
    ctx = Context(root=tmp_path, check_origin=False)

    response = _post("/api/simulate", ctx, {"map": "nope", "name": "sim", "rolls": 1})

    assert response.status == HTTPStatus.NOT_FOUND


@pytest.mark.parametrize(
    "payload",
    [{"name": "sim"}, {"map": "fray"}, {}],
)
def test_a_simulate_without_its_required_fields_is_a_400(
    ctx: Context, payload: dict[str, Any]
) -> None:
    ctx = Context(root=ctx.root, check_origin=False)
    assert _post("/api/simulate", ctx, payload).status == HTTPStatus.BAD_REQUEST


def test_a_malformed_body_is_a_400(ctx: Context) -> None:
    ctx = Context(root=ctx.root, check_origin=False)
    response = handle_request("POST", "/api/fetch", {}, ctx, body=b"{not json")

    assert response.status == HTTPStatus.BAD_REQUEST


def test_a_cross_site_post_is_refused(ctx: Context) -> None:
    """A loopback bind stops other machines, not other tabs.

    Any page you have open can POST to 127.0.0.1 and the browser will send it.
    It cannot read the reply, so the exposure is nuisance-grade - but the
    header says plainly that the request is cross-site, and it costs nothing to
    believe it.
    """
    response = _post(
        "/api/fetch", ctx, {"map": "fray"}, **{"Sec-Fetch-Site": "cross-site", "Host": "localhost:8731"}
    )

    assert response.status == HTTPStatus.FORBIDDEN
    assert "cross-site" in _body(response)["error"]


def test_a_rebound_host_is_refused(ctx: Context) -> None:
    """DNS rebinding: a hostile domain resolving to 127.0.0.1, so its page's
    origin *is* this server and Sec-Fetch-Site reads same-origin."""
    response = _post(
        "/api/fetch", ctx, {"map": "fray"}, **{"Sec-Fetch-Site": "same-origin", "Host": "evil.example.com"}
    )

    assert response.status == HTTPStatus.FORBIDDEN
    assert "Host" in _body(response)["error"]


def test_a_same_origin_post_is_allowed(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "chunksim.gui.actions.fetch_map",
        lambda map_id, timeout=30.0: {"chunks": {"unlocked": {LUMBRIDGE: LUMBRIDGE}}},
    )
    response = _post(
        "/api/fetch", ctx, {"map": "fray"}, **{"Sec-Fetch-Site": "same-origin", "Host": "127.0.0.1:8731"}
    )

    assert response.status == HTTPStatus.ACCEPTED
    assert _wait(ctx, _body(response)["job"])["state"] == "done"


def test_a_post_from_an_allowed_host_is_accepted(
    ctx: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--host <tailnet address>` has to serve a page that can act.

    Loopback-only left the remote page rendering in full with every button
    403ing, which reads as a broken GUI rather than as a refusal.
    """
    monkeypatch.setattr(
        "chunksim.gui.actions.fetch_map",
        lambda map_id, timeout=30.0: {"chunks": {"unlocked": {LUMBRIDGE: LUMBRIDGE}}},
    )
    remote = Context(root=ctx.root, allowed_hosts=frozenset({"100.93.219.108"}))

    response = _post(
        "/api/fetch",
        remote,
        {"map": "fray"},
        **{"Sec-Fetch-Site": "same-origin", "Host": "100.93.219.108:8731"},
    )

    assert response.status == HTTPStatus.ACCEPTED
    assert _wait(remote, _body(response)["job"])["state"] == "done"


def test_the_allowlist_does_not_open_the_door_to_anything_else(ctx: Context) -> None:
    """Naming one address is not naming every address: rebinding still fails."""
    remote = Context(root=ctx.root, allowed_hosts=frozenset({"100.93.219.108"}))

    response = _post(
        "/api/fetch",
        remote,
        {"map": "fray"},
        **{"Sec-Fetch-Site": "same-origin", "Host": "evil.example.com"},
    )

    assert response.status == HTTPStatus.FORBIDDEN
    assert "Host" in _body(response)["error"]


def test_an_unknown_job_is_a_404(ctx: Context) -> None:
    assert _get("/api/jobs/nope", ctx).status == HTTPStatus.NOT_FOUND


def test_the_page_reports_its_window_and_the_next_launch_reads_it_back(
    tmp_path: Path,
) -> None:
    """Chrome will not remember this for us; see `browser.window_flags`."""
    ctx = Context(root=tmp_path, check_origin=False)

    _post("/api/window", ctx, {"width": 1600, "height": 900, "x": 20, "y": 40})

    assert cache.read_gui_window(tmp_path) == {
        "width": 1600,
        "height": 900,
        "x": 20,
        "y": 40,
        "maximised": False,
    }
    assert window_flags(cache.read_gui_window(tmp_path)) == [
        "--window-size=1600,900",
        "--window-position=20,40",
    ]


def test_settings_round_trip_through_the_disk(tmp_path: Path) -> None:
    ctx = Context(root=tmp_path, check_origin=False)
    reply = _post("/api/settings", ctx, {"hours_scale": "linear"})
    assert _body(reply)["hours_scale"] == "linear"
    assert cache.read_gui_settings(tmp_path)["hours_scale"] == "linear"


def test_saving_settings_answers_inline_rather_than_with_a_job(tmp_path: Path) -> None:
    """`app.js` polls any reply carrying a `job` key, so a handler that has
    already finished must not look like one that has not started."""
    ctx = Context(root=tmp_path, check_origin=False)
    assert "job" not in _body(_post("/api/settings", ctx, {"hours_scale": "log"}))


def test_the_reply_is_what_was_stored_not_what_was_sent(tmp_path: Path) -> None:
    """A refusal has to be visible, and `sanitise` refuses by keeping the old
    value - so the page redraws from the answer rather than from its request."""
    ctx = Context(root=tmp_path, check_origin=False)
    _post("/api/settings", ctx, {"hours_scale": "linear"})
    reply = _body(_post("/api/settings", ctx, {"hours_scale": "sqrt"}))
    assert reply["hours_scale"] == "linear"


def test_a_hostile_settings_payload_writes_nothing_it_invented(tmp_path: Path) -> None:
    ctx = Context(root=tmp_path, check_origin=False)
    _post("/api/settings", ctx, {"evil": "--headless", "hours_bands": "nonsense"})
    stored = cache.read_gui_settings(tmp_path)
    assert "evil" not in stored
    assert [band["upto"] for band in stored["hours_bands"]] == [1.0, 10.0, 100.0, 300.0, None]


def test_a_partial_or_hostile_window_report_is_ignored(tmp_path: Path) -> None:
    """The file is read back as command-line arguments, so its keys are fixed."""
    ctx = Context(root=tmp_path, check_origin=False)

    _post("/api/window", ctx, {"width": 800, "evil": "--headless"})

    assert cache.read_gui_window(tmp_path) == {}


def test_a_fetch_can_name_any_map_and_blank_means_the_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**The point of the box is fetching a map you have never cached.**

    Every source-chunk map is a public unauthenticated read, so the id you can
    type is not limited to the ids already in the picker - which is exactly
    what "Fetch This Map", driven off the selected option, could not do.
    """
    seen: list[str] = []

    def pretend(map_id: str, timeout: float = 0.0) -> dict[str, Any]:
        seen.append(map_id)
        return {"chunks": {"unlocked": {LUMBRIDGE: LUMBRIDGE}}}

    monkeypatch.setattr("chunksim.gui.actions.fetch_map", pretend)
    ctx = Context(root=tmp_path, check_origin=False)

    named = _wait(ctx, _body(_post("/api/fetch", ctx, {"map": "someone-else"}))["job"])
    blank = _post("/api/fetch", ctx, {"map": "  "})

    # A blank box is refused rather than defaulted: there is no house map id,
    # and nothing local can imply which world you meant to download.
    assert blank.status == 400
    assert seen == ["someone-else"]
    assert named["result"]["map"] == "someone-else"
    # It landed where `chunksim fetch` puts one, so the picker can see it.
    assert cache.read_cache("someone-else", tmp_path)["kind"] == cache.FETCHED


def test_a_fetch_refuses_to_ask_firebase_for_a_run(tmp_path: Path) -> None:
    """`batch/run-001` is something this project computed. Upstream has never
    heard of it, so asking is a mistake rather than a fetch."""
    ctx = Context(root=tmp_path, check_origin=False)

    response = _post("/api/fetch", ctx, {"map": "sim/run-001"})

    assert response.status == HTTPStatus.BAD_REQUEST
    assert "run" in _body(response)["error"]


def test_refreshing_the_rates_runs_the_same_scrape_the_cli_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**One scraper, two callers.** `chunksim heuristics` and this button must
    write the same file; a sixteen-step sequence kept in two places would
    not stay the same for long. So this asserts the wiring - that the button
    reaches `scrape.scrape` - rather than re-testing the scrape."""
    ctx = _derived_ctx(tmp_path, monkeypatch, {"chunks": {}, "sections": {}})
    ctx = Context(root=tmp_path, check_origin=False, derivations=ctx.derivations)
    from chunksim.remote.scrape import ScrapeResult

    monkeypatch.setattr(
        "chunksim.gui.actions.scrape",
        lambda info, timeout=0.0, progress=None: ScrapeResult(
            config={"quests": {"Cook's Assistant": 5}},
            coverage={"quests": (1, 1)},
            sources={"quest pages": (1, 1)},
        ),
    )

    job = _wait(ctx, _body(_post("/api/refresh", ctx, {"what": "heuristics"}))["job"])

    assert job["state"] == "done", job.get("error")
    assert job["result"]["refreshed"] == "heuristics"
    # Read off disk, not through `cache.read_blob`: `_derived_ctx` patches that
    # on the shared module, so it would answer with the fixture's stub.
    written = json.loads(cache.blob_path(cache.WIKI_RATES_BLOB_NAME, tmp_path).read_text())
    assert written["data"] == {"quests": {"Cook's Assistant": 5}}


def test_cancelling_is_a_request_and_leaves_the_job_running(tmp_path: Path) -> None:
    """**A request, not a kill.** The work stops where it safely can - a
    simulation finishes the roll it is on - so the job is still `running`
    when the cancel answers, and the page has to keep polling rather than
    assume it is over."""
    ctx = Context(root=tmp_path, check_origin=False)
    started, release = threading.Event(), threading.Event()

    def work(progress: Any, stop: Any) -> dict[str, Any]:
        started.set()
        while not stop():
            if release.wait(timeout=0.01):
                break
        return {"stopped": stop()}

    job = ctx.jobs.submit("simulate", work)
    started.wait(timeout=5)

    reply = _body(_post("/api/cancel", ctx, {"job": job.id}))

    assert reply["state"] == "running", "it must not claim to have stopped already"
    assert reply["stopping"] is True
    finished = _wait(ctx, job.id)
    # Stopped on purpose is its own state: a page that coloured this like a
    # crash would be calling the user's own click a failure.
    assert finished["state"] == "cancelled"
    assert finished["error"] is None
    assert finished["result"] == {"stopped": True}


def test_cancelling_a_finished_job_is_not_an_error(tmp_path: Path) -> None:
    """The button and the last poll race, and "it had already finished" needs
    no handling by anyone."""
    ctx = Context(root=tmp_path, check_origin=False)
    job = ctx.jobs.submit("fetch", lambda _p, _s: {"done": True})
    _wait(ctx, job.id)

    reply = _body(_post("/api/cancel", ctx, {"job": job.id}))

    assert reply["state"] == "done"
    assert reply["stopping"] is False


def test_cancelling_an_unknown_job_is_a_404(tmp_path: Path) -> None:
    ctx = Context(root=tmp_path, check_origin=False)

    assert _post("/api/cancel", ctx, {"job": "nope"}).status == HTTPStatus.NOT_FOUND
    assert _post("/api/cancel", ctx, {}).status == HTTPStatus.BAD_REQUEST


def test_simulate_progress_counts_rolls_not_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**`2/3 runs` on a 3x100 job is three updates across four minutes.**
    The bar should count the thing that takes the time, and `countsIn` reads
    `k/N` either way.

    Asked of the inline path, which is the one that can report per roll: a
    worker has no channel back, so a pooled batch catches the count up per
    run instead - see the test below.
    """
    seen: list[str] = []

    def fake(**kw: Any) -> Any:
        roll = kw["on_roll"]
        for run in range(kw["runs"]):
            for order in range(1, kw["rolls"] + 1):
                roll(run, order, "12850")
        return _FakeBatch(kw["name"], kw["runs"], kw["on_complete"])

    monkeypatch.setattr("chunksim.gui.actions.run_batch", fake)
    monkeypatch.setattr(
        "chunksim.gui.jobs.JobRegistry.submit",
        lambda self, action, work: _capture(self, action, work, seen),
    )
    ctx = Context(root=tmp_path, check_origin=False)
    _write_map(tmp_path, "fray", [LUMBRIDGE])

    _post(
        "/api/simulate", ctx,
        {"map": "fray", "name": "sim", "rolls": 4, "runs": 3, "jobs": 1},
    )

    assert seen[0] == "0/12 rolls"
    assert seen[-1].startswith("12/12 rolls")
    assert not any("runs" in line for line in seen), seen


def test_a_pooled_simulation_still_counts_rolls_and_asks_for_no_roll_callback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**The default is wide now, so this is the path a user actually gets.**

    `run_batch` cannot call back per roll from a worker, so the page must not
    ask it to - and the bar still has to read in rolls, which it does by
    catching up as each run lands. The old `jobs > 1` test for this would have
    left `jobs=0` reporting as if it were inline, freezing the bar at zero.
    """
    seen: list[str] = []
    asked: dict[str, Any] = {}

    def fake(**kw: Any) -> Any:
        asked.update(kw)
        return _FakeBatch(kw["name"], kw["runs"], kw["on_complete"])

    monkeypatch.setattr("chunksim.gui.actions.run_batch", fake)
    # Pinned: whether this reports per roll or per run depends on how many
    # cores the batch will really get, and a test must not.
    monkeypatch.setattr("chunksim.gui.actions.os.process_cpu_count", lambda: 8)
    monkeypatch.setattr(
        "chunksim.gui.jobs.JobRegistry.submit",
        lambda self, action, work: _capture(self, action, work, seen),
    )
    ctx = Context(root=tmp_path, check_origin=False)
    _write_map(tmp_path, "fray", [LUMBRIDGE])

    _post("/api/simulate", ctx, {"map": "fray", "name": "sim", "rolls": 4, "runs": 3})

    assert asked["jobs"] == 0, "the page should ask for every core"
    assert asked["on_roll"] is None, "a pooled run cannot report per roll"
    assert seen[0] == "0/12 rolls"
    assert seen[-1].startswith("12/12 rolls"), seen


def test_committing_an_edit_writes_a_map_of_its_own_kind(ctx: Context) -> None:
    """**An edit is not an unlock.** That kind means precisely one thing - one
    candidate chunk, priced - and calling a map with six ticked tasks an
    unlock is the same wrong that split `unlocked` out of `simulated`."""
    reply = _body(
        _post(
            "/api/commit",
            ctx,
            {
                "map": "fray",
                "name": "hand-made",
                "ticked": {"Slayer": ["Kill a ~|goblin|~"], "Diary": ["Varrock Diary#Easy 1"]},
                "unlocked": [NORTH],
            },
        )
    )
    job = _wait(ctx, reply["job"])
    assert job["state"] == "done", job
    result = job["result"]
    assert result["open"] == "hand-made"
    assert result["ticks"] == 2
    assert result["chunks"] == [NORTH]

    # It lands under its own kind, and resolves by its bare name.
    root = ctx.root
    assert root is not None
    assert (root / "cache" / "maps" / "edited" / "hand-made").is_dir()
    envelope = cache.read_cache("hand-made", ctx.root)
    assert envelope["kind"] == "edited"
    assert NORTH in envelope["data"]["chunks"]["unlocked"]


def test_a_committed_tick_reads_back_as_completed(ctx: Context) -> None:
    """**The one place this can be quietly wrong.** A mis-encoded key writes a
    tick nothing can read back, and the map derives exactly as though the task
    had never been ticked - no error anywhere. So the assertion is the round
    trip through the decoder every derivation actually uses, not the presence
    of some key."""
    from chunksim.model.firebase import decode_challenge_keyed

    name = "Mine 5 ~|iron ore|~ (2/3 of it)"
    job = _wait(
        ctx,
        _body(_post("/api/commit", ctx, {"map": "fray", "name": "ticked", "ticked": {"Mining": [name]}}))["job"],
    )
    assert job["state"] == "done", job

    completed = cache.read_cache("ticked", ctx.root)["data"]["chunkinfo"]["completedChallenges"]
    assert name not in completed["Mining"], "stored raw rather than encoded"
    assert decode_challenge_keyed(completed, {})["Mining"] == {name: True}


def test_a_commit_with_nothing_in_it_is_refused(ctx: Context) -> None:
    """A map identical to its base under a new name is not an edit."""
    assert _post("/api/commit", ctx, {"map": "fray"}).status == HTTPStatus.BAD_REQUEST
    assert _post("/api/commit", ctx, {"map": "fray", "ticked": {}, "unlocked": []}).status == (
        HTTPStatus.BAD_REQUEST
    )


def test_a_bad_map_fails_the_post_rather_than_the_job(ctx: Context) -> None:
    """Read eagerly, like every other action that writes: a job that starts
    and then fails has already told the page it was working."""
    assert _post("/api/commit", ctx, {"map": "nope", "unlocked": [NORTH]}).status == (
        HTTPStatus.NOT_FOUND
    )
    # And a chunk the map already holds would write a copy under a new name.
    assert _post("/api/commit", ctx, {"map": "fray", "unlocked": [LUMBRIDGE]}).status == (
        HTTPStatus.BAD_REQUEST
    )


def test_the_claimed_name_comes_back_when_the_requested_one_collides(ctx: Context) -> None:
    """`claim_batch` suffixes `-2`, so the name that landed is not always the
    name that was typed - and the page selects what came back."""
    first = _wait(ctx, _body(_post("/api/commit", ctx, {"map": "fray", "name": "twice", "unlocked": [NORTH]}))["job"])
    second = _wait(ctx, _body(_post("/api/commit", ctx, {"map": "fray", "name": "twice", "unlocked": [NORTH]}))["job"])
    assert first["result"]["open"] == "twice"
    assert second["result"]["open"] == "twice-2"


def _sim_run(root: Path, batch: str, chunks: list[str]) -> str:
    """A run directory the snapshot route can read: a base payload, a ledger
    and a map. Written through `_write_one_run_batch` so the metadata is the
    real shape rather than a guess at it."""
    from chunksim.runs.batch import _write_one_run_batch
    from chunksim.runs.simulate import UnlockRecord, simulated_payload

    base = {"chunks": {"unlocked": {LUMBRIDGE: LUMBRIDGE}}}
    records = [
        UnlockRecord(
            order=index,
            chunk_id=chunk,
            new_sections={},
            new_tasks={},
            new_unsupported=frozenset(),
            bis_upgrades={},
        )
        for index, chunk in enumerate(chunks, start=1)
    ]
    written = _write_one_run_batch(
        name=batch,
        kind=cache.SIMULATED,
        origin="simulate",
        base_payload=base,
        data=simulated_payload(base, records),
        ledger=[record.as_dict() for record in records],
        rolls=chunks,
        base_map="fray",
        base_fetched_at=None,
        source="test",
        root=root,
    )
    return written.name


def test_a_snapshot_is_the_run_truncated_at_that_roll(ctx: Context) -> None:
    """**A truncation, not a replay** - `simulated_payload` reads only
    `chunk_id`, so the world after k rolls needs no export and no `derive`."""
    root = ctx.root
    assert root is not None
    batch = _sim_run(root, "sim", ["100", "200", "300"])

    job = _wait(ctx, _body(_post("/api/snapshot", ctx, {"map": batch, "step": 2, "name": "half"}))["job"])
    assert job["state"] == "done", job
    assert job["result"]["open"] == "half"

    held = cache.read_cache("half", root)["data"]["chunks"]["unlocked"]
    assert set(held) == {LUMBRIDGE, "100", "200"}, "the third roll came along"
    # Its own history is the real one, truncated - not a hollowed-out copy.
    assert [roll["chunk_id"] for roll in cache.read_rolls("half", root)] == ["100", "200"]
    assert cache.read_cache("half", root)["kind"] == "edited"


def test_step_zero_is_the_base_map_rather_than_a_snapshot(ctx: Context) -> None:
    """Writing it would put a copy of something that already exists on disk
    under a second name."""
    root = ctx.root
    assert root is not None
    batch = _sim_run(root, "sim", ["100", "200"])

    assert _post("/api/snapshot", ctx, {"map": batch, "step": 0}).status == HTTPStatus.BAD_REQUEST
    assert _post("/api/snapshot", ctx, {"map": batch, "step": 9}).status == HTTPStatus.BAD_REQUEST
    assert _post("/api/snapshot", ctx, {"map": batch}).status == HTTPStatus.BAD_REQUEST


def test_a_snapshot_of_the_last_roll_is_the_run_itself(ctx: Context) -> None:
    """The end of the ledger and the stored map are the same world, and the
    two paths reaching it must agree - one replays the base, the other was
    written at roll time."""
    root = ctx.root
    assert root is not None
    batch = _sim_run(root, "sim", ["100", "200", "300"])

    _wait(ctx, _body(_post("/api/snapshot", ctx, {"map": batch, "step": 3, "name": "whole"}))["job"])
    assert (
        cache.read_cache("whole", root)["data"]["chunks"]["unlocked"]
        == cache.read_cache(batch, root)["data"]["chunks"]["unlocked"]
    )


def test_an_edited_map_can_be_edited_again(ctx: Context) -> None:
    """**A cached map is immutable and an edit is not.**

    Fetching gives you upstream's state, which nothing here may write over -
    so the first change forks it. What has to follow from that is that the
    fork is an ordinary map: you cannot plan a chunk run by committing one
    edit and then being told the result is read-only.

    Nothing in the write path was ever kind-specific, so this is a property to
    pin rather than a feature to add - the risk is a later "only fetched maps
    can be edited" guard, which would look like tidiness and remove the point.
    """
    from chunksim.model.firebase import decode_challenge_keyed

    first = _wait(
        ctx,
        _body(_post("/api/commit", ctx, {
            "map": "fray", "name": "step-1",
            "ticked": {"Mining": ["Mine ~|copper ore|~"]},
        }))["job"],
    )
    assert first["state"] == "done", first

    second = _wait(
        ctx,
        _body(_post("/api/commit", ctx, {
            "map": "step-1", "name": "step-2",
            "ticked": {"Mining": ["Mine ~|tin ore|~"]},
            "unlocked": [NORTH],
        }))["job"],
    )
    assert second["state"] == "done", second

    envelope = cache.read_cache("step-2", ctx.root)
    assert envelope["kind"] == "edited"
    # Both edits are present: the second was applied *to* the first rather
    # than to whatever the first was forked from.
    ticked = decode_challenge_keyed(envelope["data"]["chunkinfo"]["completedChallenges"], {})
    assert ticked["Mining"] == {"Mine ~|copper ore|~": True, "Mine ~|tin ore|~": True}
    assert NORTH in envelope["data"]["chunks"]["unlocked"]
    # And it records what it was actually made from.
    batch = cache.read_batch("step-2", ctx.root, kind=cache.EDITED)
    assert batch.get("base_map") == "step-1"


def test_the_uber_sentinel_builds_every_chunk_onto_the_open_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**A development escape hatch, and the base is the interesting half.**

    A map carries the player's rules, their `maxSkill` and their completed
    challenges, so "everything unlocked" is only useful as *this* map with the
    chunk constraint removed - which is exactly the map half of `CLAUDE.md`'s
    measurements are quoted against.
    """
    _write_map(tmp_path, "fray", [LUMBRIDGE])
    derived = _derived_ctx(tmp_path, monkeypatch, {"chunks": {LUMBRIDGE: {}, NORTH: {}}})
    ctx = Context(root=tmp_path, check_origin=False, derivations=derived.derivations)

    job = _wait(ctx, _body(_post("/api/fetch", ctx, {"map": "__UBER__", "base": "fray"}))["job"])
    assert job["state"] == "done", job

    envelope = cache.read_cache(job["result"]["open"], ctx.root)
    assert envelope["kind"] == "edited"
    assert set(envelope["data"]["chunks"]["unlocked"]) == {LUMBRIDGE, NORTH}


def test_the_uber_sentinel_is_refused_off_loopback(ctx: Context) -> None:
    """It is not a permission system; it is a statement that this is a local
    tool. `allowed_hosts` is non-empty exactly when `--host`/`--allow-host`
    was passed, which is the only way this server is reachable from elsewhere.
    """
    remote = Context(root=ctx.root, allowed_hosts=frozenset({"box.tailnet"}))

    reply = _post("/api/fetch", remote, {"map": "__UBER__", "base": "fray"})

    assert reply.status == HTTPStatus.BAD_REQUEST
    assert b"loopback-only" in reply.body


def test_an_edited_map_is_updated_in_place_rather_than_forked_again(ctx: Context) -> None:
    """**A fetched map is immutable and an edited one is not.**

    The first change to upstream's state has to write somewhere new; every
    change after that is a change to *your* map. Forking each time minted
    `-2`, `-3`, `-4` down the chunk you were planning - a new map per click
    rather than a map you were working on.

    The accumulated history is what makes it a map rather than a snapshot: the
    batch keeps the payload it was originally forked from and the ledger
    grows, so it still replays every chunk added by hand.
    """
    from chunksim.model.firebase import decode_challenge_keyed

    first = _wait(ctx, _body(_post("/api/commit", ctx, {
        "map": "fray", "name": "mine", "ticked": {"Mining": ["Mine ~|copper ore|~"]},
    }))["job"])
    assert first["state"] == "done", first

    second = _wait(ctx, _body(_post("/api/commit", ctx, {
        "map": "mine", "replace": True,
        "ticked": {"Mining": ["Mine ~|tin ore|~"]}, "unlocked": [NORTH],
    }))["job"])
    assert second["state"] == "done", second
    assert second["result"]["open"] == "mine", "it forked instead of updating"

    root = ctx.root
    assert root is not None
    assert not (root / "cache" / "maps" / "edited" / "mine-2").exists()

    envelope = cache.read_cache("mine", ctx.root)
    ticked = decode_challenge_keyed(envelope["data"]["chunkinfo"]["completedChallenges"], {})
    assert ticked["Mining"] == {"Mine ~|copper ore|~": True, "Mine ~|tin ore|~": True}
    assert NORTH in envelope["data"]["chunks"]["unlocked"]
    # Still forked from `fray`, not from itself, and the same job throughout.
    batch = cache.read_batch("mine", ctx.root, kind=cache.EDITED)
    assert batch["base_map"] == "fray"
    assert batch["base_payload"]["chunks"]["unlocked"] == {LUMBRIDGE: LUMBRIDGE}


def test_only_an_edited_map_can_be_replaced(ctx: Context) -> None:
    """`replace` is a request, and the kind is the answer: a browser cannot be
    the authority on what it may overwrite, and upstream's own state is the
    one thing nothing here writes to."""
    job = _wait(ctx, _body(_post("/api/commit", ctx, {
        "map": "fray", "replace": True, "ticked": {"Mining": ["Mine ~|copper ore|~"]},
    }))["job"])

    assert job["state"] == "done", job
    assert job["result"]["open"] == "fray-edit", "a fetched map was overwritten"
    assert cache.read_cache("fray", ctx.root)["kind"] == "fetched"


def test_an_auto_refresh_is_refused_once_the_blob_is_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**The page warms the reference blobs on boot; a press is a decision.**

    `warmReference` asks for both wiki scrapes when they are missing, which is
    worth about sixty requests on a fresh cache and worth none on every reload
    after. `auto` marks the request as the page's idea so the server can say
    no; a button sends no `auto` and is never refused.
    """
    ctx = _derived_ctx(tmp_path, monkeypatch, {"chunks": {}, "sections": {}})
    ctx = Context(root=tmp_path, check_origin=False, derivations=ctx.derivations)
    cache.write_blob(cache.RECIPES_BLOB_NAME, {"Cooking": []}, "test", tmp_path)

    reply = _body(_post("/api/refresh", ctx, {"what": "recipes", "auto": True}))

    assert reply == {"skipped": "recipes", "why": "cached"}


def test_an_auto_refresh_does_not_retry_a_scrape_that_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**Attempted, not succeeded.** A scrape that fails should report and
    stop. Keying the guard on the blob alone would restart it on every reload
    - which is the same thirty-odd requests again, against a wiki that just said
    no - so the second ask is refused by this run having tried.
    """
    ctx = _derived_ctx(tmp_path, monkeypatch, {"chunks": {}, "sections": {}})
    ctx = Context(root=tmp_path, check_origin=False, derivations=ctx.derivations)

    def explode(timeout: float = 0.0) -> dict[str, Any]:
        raise OSError("the wiki said no")

    monkeypatch.setattr("chunksim.gui.actions.scrape_recipes", explode)

    first = _body(_post("/api/refresh", ctx, {"what": "recipes", "auto": True}))
    job = _wait(ctx, first["job"])
    second = _body(_post("/api/refresh", ctx, {"what": "recipes", "auto": True}))

    assert job["state"] == "failed"
    assert second == {"skipped": "recipes", "why": "attempted"}
    # The button still works: it is a decision, and the user can see the error.
    assert "job" in _body(_post("/api/refresh", ctx, {"what": "recipes"}))


def test_a_blank_map_is_a_real_map_carrying_upstream_rules(tmp_path: Path) -> None:
    """**The reason `/api/blank` exists rather than the page faking one.**

    A map with no `rules` branch is not a neutral map: a missing rule key skips
    its gate where `False` refuses it, so an empty one is the most permissive
    world there is. `model/rules.py` owns the table and the measurement; this
    asserts the action actually seeds it.
    """
    ctx = Context(root=tmp_path, check_origin=False)

    reply = _body(_post("/api/blank", ctx, {}))

    assert reply == {"map": "untitled", "open": "untitled"}
    envelope = cache.read_cache("untitled", tmp_path)
    assert envelope["kind"] == cache.EDITED
    assert envelope["data"]["chunks"]["unlocked"] == {}
    assert envelope["data"]["rules"] == dict(DEFAULT_RULES)


def test_a_blank_map_answers_inline_because_the_page_needs_the_name(tmp_path: Path) -> None:
    """No job: it writes four small files and does no network. And the name
    comes back because `claim_batch` suffixes when the last draft is still
    there, so the page cannot assume what it asked for is what it got."""
    ctx = Context(root=tmp_path, check_origin=False)

    first = _body(_post("/api/blank", ctx, {}))
    second = _body(_post("/api/blank", ctx, {}))

    assert "job" not in first and "job" not in second
    assert (first["open"], second["open"]) == ("untitled", "untitled-2")
    assert {entry.map_id for entry in cache.list_maps(tmp_path)} == {"untitled", "untitled-2"}


def test_a_blank_map_opens_in_edit_mode(tmp_path: Path) -> None:
    """`modeForMap` in `app.js` opens an `edited` map in edit mode, which is
    what makes every square unlockable by hand - a map with nothing unlocked
    has no eligible neighbours, so a first chunk cannot come from the
    candidate list."""
    ctx = Context(root=tmp_path, check_origin=False)

    _post("/api/blank", ctx, {})

    rows = _body(handle_request("GET", "/api/maps", {}, ctx))
    # The listing expands a batch's runs, and a hand-made map is a batch of
    # one - so the row the picker opens is the bare name, not `.../run-001`.
    assert ("untitled", cache.EDITED) in [(row["map_id"], row["kind"]) for row in rows]


_INSTALLER: dict[str, Any] = {
    "name": "chunksim-9.9.9-setup.exe",
    "url": "https://example/chunksim-9.9.9-setup.exe",
    "size": 4,
    "digest": "sha256:" + hashlib.sha256(b"MZ\x00\x00").hexdigest(),
}

_UPDATE_RELEASE: dict[str, Any] = {
    "version": "9.9.9",
    "url": "https://example/releases/9.9.9",
    "installer": _INSTALLER,
}


def test_a_newer_release_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = Context(root=tmp_path, check_origin=False)
    monkeypatch.setattr(
        "chunksim.gui.actions.fetch_latest_release",
        lambda: SimpleNamespace(as_dict=lambda: _UPDATE_RELEASE),
    )

    reply = _body(_post("/api/update", ctx, {}))

    assert (reply["available"], reply["latest"]) == (True, "9.9.9")
    # Remembered, so opening the GUI five times in an afternoon asks once.
    assert cache.read_update(tmp_path)[0]["version"] == "9.9.9"


def test_an_unreachable_check_says_nothing_and_remembers_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**Silence is the design.** Nobody asked for this, so a check that cannot
    run must not interrupt - and must not write a "no update" that would then
    stand for a day."""
    ctx = Context(root=tmp_path, check_origin=False)

    def unreachable() -> None:
        raise FetchError("network error checking for updates: unreachable")

    monkeypatch.setattr("chunksim.gui.actions.fetch_latest_release", unreachable)

    reply = _body(_post("/api/update", ctx, {}))

    assert reply["available"] is False and reply["checked"] is False
    with pytest.raises(cache.CacheMissError):
        cache.read_update(tmp_path)


def test_the_check_can_be_turned_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = Context(root=tmp_path, check_origin=False)
    cache.write_gui_settings({"update_check": False}, tmp_path)
    monkeypatch.setattr(
        "chunksim.gui.actions.fetch_latest_release",
        lambda: pytest.fail("the network must not be touched when the check is off"),
    )

    reply = _body(_post("/api/update", ctx, {}))

    assert reply["checked"] is False and reply["why"] == "disabled"


def test_an_installer_without_a_checksum_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**An executable is not run on the strength of the transport alone.**
    HTTPS says who served it; the digest says it is the file the release names.
    Without one there is nothing to check the download against."""
    monkeypatch.setattr("chunksim.gui.actions.sys.platform", "win32")
    ctx = Context(root=tmp_path, check_origin=False)
    installer = {**_INSTALLER, "digest": None}

    response = _post("/api/update/install", ctx, {"installer": installer})

    assert response.status == 400
    assert "checksum" in _body(response)["error"]


def test_an_installer_served_over_http_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("chunksim.gui.actions.sys.platform", "win32")
    ctx = Context(root=tmp_path, check_origin=False)
    installer = {**_INSTALLER, "url": "http://example/x-setup.exe"}

    response = _post("/api/update/install", ctx, {"installer": installer})

    assert response.status == 400


def test_a_download_that_does_not_match_its_checksum_is_deleted_unrun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one that matters: a wrong file must not survive the failure, or it
    sits on disk waiting to be found and double-clicked."""
    monkeypatch.setattr("chunksim.gui.actions.sys.platform", "win32")
    started: list[Any] = []
    monkeypatch.setattr(
        "chunksim.gui.actions.subprocess.Popen",
        lambda *args, **kwargs: started.append(args),
    )
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda url, timeout=0: io.BytesIO(b"NOT THE FILE"),
    )
    ctx = Context(root=tmp_path, check_origin=False)

    job = _wait(ctx, _body(_post("/api/update/install", ctx, {"installer": _INSTALLER}))["job"])

    assert job["state"] == "failed"
    assert "checksum" in (job["error"] or "")
    assert not started, "nothing may be executed after a checksum mismatch"
    assert ctx.stopping[0] is False


def test_a_verified_installer_is_launched_and_the_server_stands_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The server has to go: the installer is about to replace the files this
    process is running from."""
    monkeypatch.setattr("chunksim.gui.actions.sys.platform", "win32")
    started: list[Any] = []
    monkeypatch.setattr(
        "chunksim.gui.actions.subprocess.Popen",
        lambda *args, **kwargs: started.append(args[0]),
    )
    monkeypatch.setattr("urllib.request.urlopen", lambda url, timeout=0: io.BytesIO(b"MZ\x00\x00"))
    ctx = Context(root=tmp_path, check_origin=False)

    job = _wait(ctx, _body(_post("/api/update/install", ctx, {"installer": _INSTALLER}))["job"])

    assert job["state"] == "done"
    assert started and started[0][1] == "/SILENT"
    assert ctx.stopping[0] is True


def test_stopping_beats_keep_alive(tmp_path: Path) -> None:
    """`--keep-alive` keeps a server useful; it cannot keep one running out of
    files that are being replaced underneath it."""
    from chunksim.gui.http import should_stop

    ctx = Context(root=tmp_path, keep_alive=True)
    assert should_stop(ctx) is False

    ctx.stopping[0] = True
    assert should_stop(ctx) is True
