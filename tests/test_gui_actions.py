"""Tests for `gui/actions.py`: the ten POSTs and the jobs they hand work to.

`handle_request` is pure - strings in, a `Response` out - so every test
here exercises the real routing without binding a socket.
"""

from __future__ import annotations

import json
import re
import threading
import time
from http import HTTPStatus
from pathlib import Path
from typing import Any

import pytest

from fray_claude.store import cache
from fray_claude.gui.browser import window_flags
from fray_claude.gui.server import Context, Response, handle_request


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
        "fray_claude.gui.derivation.cache.read_chunkinfo",
        lambda override=None, root=None: chunkinfo,
    )
    monkeypatch.setattr(
        "fray_claude.gui.derivation.cache.read_blob",
        lambda name, root=None, hint=None: {"data": {}},
    )
    monkeypatch.setattr(
        "fray_claude.gui.derivation.cache.file_digest", lambda path: "digest"
    )
    # **Under `tmp_path`, not bare names.** These patch attributes on the
    # *shared* `cache` module, so anything that later writes through
    # `blob_path` writes wherever this points - and `Path("y")` is relative,
    # which put a stray file in the repo root the first time a test using
    # this fixture wrote a blob for real.
    monkeypatch.setattr(
        "fray_claude.gui.derivation.cache.chunkinfo_source", lambda o, r: tmp_path / "x"
    )
    monkeypatch.setattr(
        "fray_claude.gui.derivation.cache.blob_path", lambda n, r: tmp_path / f"{n}.json"
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
        "fray_claude.gui.actions.run_batch",
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

    monkeypatch.setattr("fray_claude.gui.actions.run_batch", explode)
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
        "fray_claude.gui.actions.fetch_map",
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
        "fray_claude.gui.actions.fetch_map",
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

    monkeypatch.setattr("fray_claude.gui.actions.fetch_map", pretend)
    ctx = Context(root=tmp_path, check_origin=False)

    named = _wait(ctx, _body(_post("/api/fetch", ctx, {"map": "someone-else"}))["job"])
    blank = _wait(ctx, _body(_post("/api/fetch", ctx, {"map": "  "}))["job"])

    assert seen == ["someone-else", cache.DEFAULT_MAP_ID]
    assert named["result"]["map"] == "someone-else"
    assert blank["result"]["map"] == cache.DEFAULT_MAP_ID
    # Both landed where `fray fetch` puts one, so the picker can see them.
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
    """**One scraper, two callers.** `fray heuristics` and this button must
    write the same file; an eighteen-step sequence kept in two places would
    not stay the same for long. So this asserts the wiring - that the button
    reaches `scrape.scrape` - rather than re-testing the scrape."""
    ctx = _derived_ctx(tmp_path, monkeypatch, {"chunks": {}, "sections": {}})
    ctx = Context(root=tmp_path, check_origin=False, derivations=ctx.derivations)
    from fray_claude.remote.scrape import ScrapeResult

    monkeypatch.setattr(
        "fray_claude.gui.actions.scrape",
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
    `k/N` either way."""
    seen: list[str] = []

    def fake(**kw: Any) -> Any:
        roll = kw["on_roll"]
        for run in range(kw["runs"]):
            for order in range(1, kw["rolls"] + 1):
                roll(run, order, "12850")
        return _FakeBatch(kw["name"], kw["runs"], kw["on_complete"])

    monkeypatch.setattr("fray_claude.gui.actions.run_batch", fake)
    monkeypatch.setattr(
        "fray_claude.gui.jobs.JobRegistry.submit",
        lambda self, action, work: _capture(self, action, work, seen),
    )
    ctx = Context(root=tmp_path, check_origin=False)
    _write_map(tmp_path, "fray", [LUMBRIDGE])

    _post("/api/simulate", ctx, {"map": "fray", "name": "sim", "rolls": 4, "runs": 3})

    assert seen[0] == "0/12 rolls"
    assert seen[-1].startswith("12/12 rolls")
    assert not any("runs" in line for line in seen), seen


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
    from fray_claude.model.firebase import decode_challenge_keyed

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
