"""Tests for `gui/routes_view.py`: the cheap path - view, revision, summary, timeline, roll, maps.

`handle_request` is pure - strings in, a `Response` out - so every test
here exercises the real routing without binding a socket.
"""

from __future__ import annotations

import json
import re
import time
from http import HTTPStatus
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from fray_claude.store import cache
from fray_claude.gui.server import Context, Response, handle_request


LUMBRIDGE = "12850"


NORTH = "12851"  # one region north of Lumbridge


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


def _write_run(root: Path, batch: str, unlocked: list[str], rolls: list[str]) -> str:
    """A one-run computed batch: the payload it ended on, and how it got there.

    `unlocked` is the *final* set, `rolls` what the run added - which is the
    pair a timeline replays. Deliberately does not write the base map, since
    a run replaying without one is the property under test.
    """
    directory = cache.claim_batch(batch, root, kind=cache.SIMULATED)
    run = cache.run_dir(directory, 1)
    cache.write_sim_run(
        run,
        map_id=f"{directory.name}/{run.name}",
        data={"chunks": {"unlocked": {chunk: chunk for chunk in unlocked}}},
        simulation={"run": run.name, "batch": directory.name, "rolls": list(rolls)},
        ledger=[
            {
                "order": index,
                "chunk_id": chunk,
                "new_sections": {chunk: {"0": True}},
                "new_tasks": {"Slayer": {f"task-{chunk}": {}}},
                "new_unsupported": [],
                "bis_upgrades": {},
            }
            for index, chunk in enumerate(rolls, start=1)
        ],
    )
    return f"{directory.name}/{run.name}"


def _capture(registry: Any, action: str, work: Any, seen: list[str]) -> Any:
    """Run a job inline and keep every progress line it emitted."""
    work(seen.append, lambda: False)

    class _Job:
        id = "inline"

    return _Job()


def test_a_view_carries_the_unlocked_cells(ctx: Context) -> None:
    response = _get("/api/view", ctx, map="fray")

    assert response.status == HTTPStatus.OK
    assert response.content_type.startswith("application/json")
    payload = _body(response)
    assert payload["map_id"] == "fray"
    assert [cell["chunk_id"] for cell in payload["cells"]] == [LUMBRIDGE]
    assert payload["counts"]["unlocked"] == 1


def test_a_comparison_marks_gains_and_losses_in_the_right_direction(
    tmp_path: Path,
) -> None:
    """Green is what the compared map has and the base does not.

    Backwards, this paints every gain red, which is the kind of thing that
    looks plausible in a screenshot.
    """
    _write_map(tmp_path, "before", [LUMBRIDGE, NORTH])
    _write_map(tmp_path, "after", [LUMBRIDGE, "13106"])
    ctx = Context(root=tmp_path)

    payload = _body(_get("/api/view", ctx, map="before", compare="after"))
    states = {cell["chunk_id"]: cell["state"] for cell in payload["cells"]}

    assert states["13106"] == "added"
    assert states[NORTH] == "removed"
    assert states[LUMBRIDGE] == "unlocked"
    assert payload["compare_map_id"] == "after"


def test_the_revision_moves_when_the_map_changes(ctx: Context, tmp_path: Path) -> None:
    """The live-reload token. A stat, not a hash - see the module docstring."""
    first = _body(_get("/api/revision", ctx, map="fray"))["revision"]

    _write_map(tmp_path, "fray", [LUMBRIDGE, NORTH])
    second = _body(_get("/api/revision", ctx, map="fray"))["revision"]

    assert first != second
    assert second == _body(_get("/api/view", ctx, map="fray"))["revision"]


def test_a_comparison_notices_either_side_changing(tmp_path: Path) -> None:
    _write_map(tmp_path, "before", [LUMBRIDGE])
    _write_map(tmp_path, "after", [LUMBRIDGE])
    ctx = Context(root=tmp_path)
    first = _body(_get("/api/revision", ctx, map="before", compare="after"))["revision"]

    _write_map(tmp_path, "after", [LUMBRIDGE, NORTH])
    second = _body(_get("/api/revision", ctx, map="before", compare="after"))["revision"]

    assert first != second


def test_maps_lists_what_is_cached(ctx: Context) -> None:
    payload = _body(_get("/api/maps", ctx))

    assert [entry["map_id"] for entry in payload] == ["fray"]


def test_an_unknown_map_is_a_404_carrying_the_cache_message(ctx: Context) -> None:
    """`CacheMissError`'s own text already names the fixing command."""
    response = _get("/api/view", ctx, map="nope")

    assert response.status == HTTPStatus.NOT_FOUND
    assert "nope" in _body(response)["error"]


def test_a_view_without_a_map_is_a_400(ctx: Context) -> None:
    response = _get("/api/view", ctx)

    assert response.status == HTTPStatus.BAD_REQUEST
    assert "map" in _body(response)["error"]


def test_an_unknown_method_is_refused(ctx: Context) -> None:
    assert handle_request("PUT", "/api/view", {}, ctx).status == (
        HTTPStatus.METHOD_NOT_ALLOWED
    )


def test_posting_to_a_read_only_route_is_a_404(ctx: Context) -> None:
    """Only the action routes accept a POST; the rest simply are not there."""
    assert handle_request("POST", "/api/view", {}, ctx).status == HTTPStatus.NOT_FOUND


@pytest.mark.parametrize(
    "map_id",
    ["../../etc/passwd", "..", "../fray", "fray/../../etc/passwd", "/etc/passwd"],
)
def test_a_map_id_cannot_escape_the_cache(ctx: Context, map_id: str) -> None:
    """The guard is `cache.split_map_id`, not anything in the server.

    Pinned here so the reliance is visible: a second, weaker check in the
    server is exactly how two guards drift apart, so there deliberately isn't
    one.
    """
    assert _get("/api/view", ctx, map=map_id).status == HTTPStatus.NOT_FOUND


def test_a_map_holding_a_named_area_pays_for_the_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one case where `/api/view` is allowed to parse the 10MB export.

    A named id has no coordinates, so there is no cheaper way to draw it. The
    parse is conditional on the map actually holding one - see the companion
    test that an all-numeric map still never touches the export.
    """
    _write_map(tmp_path, "fray", [LUMBRIDGE, "Kurask Lair"])
    ctx = _derived_ctx(
        tmp_path,
        monkeypatch,
        {"chunks": {"4751": {"Name": "Kurask Lair"}}, "sections": {}},
    )

    payload = _body(_get("/api/view", ctx, map="fray"))
    drawn = {cell["chunk_id"]: cell["area"] for cell in payload["cells"]}

    assert drawn == {LUMBRIDGE: None, "4751": "Kurask Lair"}
    assert payload["counts"]["skipped"] == 0
    assert ctx.derivations.loaded


def test_the_summary_answers_what_fray_show_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_map(tmp_path, "fray", [LUMBRIDGE, NORTH])
    ctx = Context(root=tmp_path)

    payload = _body(_get("/api/summary", ctx, map="fray"))

    assert payload["unlocked_chunks"] == 2
    assert payload["kind"] == "fetched"


def test_the_map_view_never_parses_the_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The property the whole server is built around.

    Rendering needs only the unlocked set, so a view request must not touch
    the 10MB export - that is what keeps it milliseconds and why nothing has
    to be invalidated.
    """
    _write_map(tmp_path, "fray", [LUMBRIDGE])

    def explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the map view parsed the chunkinfo export")

    monkeypatch.setattr("fray_claude.gui.derivation.cache.read_chunkinfo", explode)
    ctx = Context(root=tmp_path)

    assert _get("/api/view", ctx, map="fray").status == HTTPStatus.OK
    assert _get("/api/revision", ctx, map="fray").status == HTTPStatus.OK
    assert _get("/api/summary", ctx, map="fray").status == HTTPStatus.OK
    assert not ctx.derivations.loaded


def test_a_timeline_replays_a_run_without_parsing_the_export(tmp_path: Path) -> None:
    """**The property that makes the slider usable.**

    Dragging it refetches a view per step, so a step that cost a 10MB parse
    or a `derive` would stutter. The ledger and the saved payload are the
    whole input - and the base map is deliberately absent here, because a run
    carries its own past.

    `/api/timeline` itself is fetched once when a run is *opened*, and does
    pay the parse where there is a base map to measure a roll's tasks against
    - see `roll_panels`. This run has none, so the whole route stays cold; the
    per-drag route below is the one that must never warm it.
    """
    ctx = Context(root=tmp_path)
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH, "12852"], [NORTH, "12852"])

    payload = _body(_get("/api/timeline", ctx, map=map_id))

    assert not ctx.derivations.loaded, "the timeline parsed the export"
    assert [row["step"] for row in payload["steps"]] == [0, 1, 2]
    assert [row["chunk"] for row in payload["steps"]] == [None, NORTH, "12852"]
    assert [row["unlocked_chunks"] for row in payload["steps"]] == [1, 2, 3]
    assert [row["tasks"] for row in payload["steps"]] == [0, 1, 1]
    # Nobody has paid for the hours, and that is not the same as zero hours.
    assert payload["has_hours"] is False
    assert all(row["hours"] is None for row in payload["steps"])


def test_a_view_can_be_rewound_to_a_step(tmp_path: Path) -> None:
    """Everything rolled so far is `added`, so the growth accumulates green
    against the world the run started from."""
    ctx = Context(root=tmp_path)
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH, "12852"], [NORTH, "12852"])

    at_zero = _body(_get("/api/view", ctx, map=map_id, step="0"))
    at_one = _body(_get("/api/view", ctx, map=map_id, step="1"))

    assert not ctx.derivations.loaded
    assert at_zero["counts"] == {"unlocked": 1, "added": 0, "removed": 0, "skipped": 0}
    assert at_one["counts"]["added"] == 1
    assert {cell["chunk_id"] for cell in at_one["cells"]} == {LUMBRIDGE, NORTH}
    assert at_one["step"] == 1


def test_a_step_outside_the_run_is_a_400_not_a_guess(tmp_path: Path) -> None:
    ctx = Context(root=tmp_path)
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH], [NORTH])

    assert _get("/api/view", ctx, map=map_id, step="9").status == HTTPStatus.BAD_REQUEST
    assert _get("/api/view", ctx, map=map_id, step="-1").status == HTTPStatus.BAD_REQUEST
    assert _get("/api/view", ctx, map=map_id, step="soon").status == HTTPStatus.BAD_REQUEST


def test_a_fetched_map_has_no_timeline(tmp_path: Path) -> None:
    """No ledger, so nothing to step through - and that is the test the page
    uses to decide whether the strip appears at all."""
    ctx = Context(root=tmp_path)
    _write_map(tmp_path, "fray", [LUMBRIDGE])

    assert _get("/api/timeline", ctx, map="fray").status == HTTPStatus.NOT_FOUND
    # A plain view of it is unaffected.
    assert _get("/api/view", ctx, map="fray").status == HTTPStatus.OK


def test_stored_hours_are_served_and_a_moved_world_discards_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**A stamp mismatch reads as absent, not as an error.**

    The numbers are recomputable, so offering to recompute beats refusing to
    draw. A moved export, tasks map, rate scrape or overrides file all count -
    the last because it is hand-edited and checked in, so it moves without any
    fetch having happened.
    """
    ctx = _derived_ctx(tmp_path, monkeypatch, {"chunks": {}, "sections": {}})
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH], [NORTH])
    from fray_claude.gui.routes_view import _timeline_stamp

    stamp = _timeline_stamp(ctx, enriched=False)
    cache.write_timeline(map_id, {"stamp": stamp, "added": [0.0, 2.5], "totals": [10.0, 12.5]}, tmp_path)

    fresh = _body(_get("/api/timeline", ctx, map=map_id))
    assert fresh["has_hours"] is True
    assert [row["hours"] for row in fresh["steps"]] == [None, 2.5]
    assert [row["total_hours"] for row in fresh["steps"]] == [10.0, 12.5]

    cache.write_timeline(
        map_id, {"stamp": {**stamp, "rates": "moved"}, "added": [0.0, 2.5], "totals": [10.0, 12.5]}, tmp_path
    )
    stale = _body(_get("/api/timeline", ctx, map=map_id))

    assert stale["has_hours"] is False
    assert all(row["hours"] is None for row in stale["steps"])


def test_cheap_hours_are_not_stale_merely_because_dps_is_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**`enriched` is recorded and deliberately not compared.**

    A simulation prices its own rolls with the estimator alone, because the
    derivation is already in hand and costs nothing more; `dps_bridge.enrich`
    adds ~1.3s a roll and would have tripled every batch. So the cheap answer
    is what a run is born with. Treating it as *stale* once the extra is
    installed would blank a graph that is perfectly good - it is a coarser
    answer, not an out-of-date one, and worth showing until the better one
    exists.
    """
    ctx = _derived_ctx(tmp_path, monkeypatch, {"chunks": {}, "sections": {}})
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH], [NORTH])
    from fray_claude.gui.routes_view import _timeline_stamp

    cache.write_timeline(
        map_id,
        {"stamp": _timeline_stamp(ctx, enriched=False), "added": [0.0, 2.5], "totals": [10.0, 12.5]},
        tmp_path,
    )
    monkeypatch.setattr("fray_claude.gui.routes_view.dps_bridge.DPS_AVAILABLE", True)

    payload = _body(_get("/api/timeline", ctx, map=map_id))

    assert payload["has_hours"] is True, "the cheap numbers were thrown away"
    assert payload["enriched"] is False
    # And the page is told there is a better answer to be had.
    assert payload["can_enrich"] is True


def test_enriched_hours_leave_nothing_to_upgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The button costs a minute on a long run, so it goes once it would only
    rewrite the same numbers."""
    ctx = _derived_ctx(tmp_path, monkeypatch, {"chunks": {}, "sections": {}})
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH], [NORTH])
    from fray_claude.gui.routes_view import _timeline_stamp

    cache.write_timeline(
        map_id,
        {"stamp": _timeline_stamp(ctx, enriched=True), "added": [0.0, 2.5], "totals": [10.0, 12.5]},
        tmp_path,
    )
    monkeypatch.setattr("fray_claude.gui.routes_view.dps_bridge.DPS_AVAILABLE", True)

    payload = _body(_get("/api/timeline", ctx, map=map_id))

    assert payload["enriched"] is True and payload["can_enrich"] is False


def test_without_the_extra_there_is_nothing_better_to_offer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`can_enrich` is about whether a *better* answer exists, so on a machine
    without the extra it is false however the numbers were computed."""
    ctx = _derived_ctx(tmp_path, monkeypatch, {"chunks": {}, "sections": {}})
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH], [NORTH])
    from fray_claude.gui.routes_view import _timeline_stamp

    cache.write_timeline(
        map_id,
        {"stamp": _timeline_stamp(ctx, enriched=False), "added": [0.0, 2.5], "totals": [10.0, 12.5]},
        tmp_path,
    )
    monkeypatch.setattr("fray_claude.gui.routes_view.dps_bridge.DPS_AVAILABLE", False)

    payload = _body(_get("/api/timeline", ctx, map=map_id))

    assert payload["has_hours"] is True and payload["can_enrich"] is False


def test_a_totals_list_that_does_not_fit_the_run_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run re-rolled under the same name has a different number of steps.
    Drawing the old numbers against the new chunks would be silently wrong."""
    ctx = _derived_ctx(tmp_path, monkeypatch, {"chunks": {}, "sections": {}})
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH], [NORTH])
    from fray_claude.gui.routes_view import _timeline_stamp

    cache.write_timeline(
        map_id,
        {"stamp": _timeline_stamp(ctx, enriched=False), "added": [1.0, 2.0, 3.0, 4.0], "totals": [1.0, 2.0, 3.0, 4.0]},
        tmp_path
    )

    assert _body(_get("/api/timeline", ctx, map=map_id))["has_hours"] is False


def test_a_timeline_post_without_a_map_is_a_400(tmp_path: Path) -> None:
    ctx = Context(root=tmp_path, check_origin=False)
    assert _post("/api/timeline", ctx, {}).status == HTTPStatus.BAD_REQUEST
    assert _post("/api/timeline", ctx, {"map": "nope"}).status == HTTPStatus.NOT_FOUND


def test_the_timeline_job_reports_slices_for_the_bar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**`k/N` is not decoration** - `app.js`'s `countsIn` parses exactly that
    into a real bar, and anything else leaves it indeterminate. The count is of
    slices, because a worker cannot report from inside one."""
    ctx = _derived_ctx(tmp_path, monkeypatch, {"chunks": {}, "sections": {}})
    ctx = Context(root=tmp_path, check_origin=False, derivations=ctx.derivations)
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH], [NORTH])
    seen: list[str] = []

    def fake(**kw: Any) -> tuple[list[float], list[float]]:
        report = kw["on_progress"]
        report(1, 2)
        report(2, 2)
        return [0.0, 1.0], [1.0, 2.0]

    monkeypatch.setattr("fray_claude.gui.actions.price_steps", fake)
    monkeypatch.setattr(
        "fray_claude.gui.jobs.JobRegistry.submit",
        lambda self, action, work: _capture(self, action, work, seen),
    )

    _post("/api/timeline", ctx, {"map": map_id, "jobs": 2})

    assert any(re.fullmatch(r"\d+/\d+ slices - \d+ workers", line) for line in seen), seen


def test_the_timeline_job_passes_jobs_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Omitted means auto, and auto is `price_steps`' call to make - the server
    must not resolve it to a number and hard-code today's core count into a
    stored answer."""
    ctx = _derived_ctx(tmp_path, monkeypatch, {"chunks": {}, "sections": {}})
    ctx = Context(root=tmp_path, check_origin=False, derivations=ctx.derivations)
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH], [NORTH])
    asked: list[int] = []

    def fake(**kw: Any) -> tuple[list[float], list[float]]:
        asked.append(kw["jobs"])
        return [0.0, 1.0], [1.0, 2.0]

    monkeypatch.setattr("fray_claude.gui.actions.price_steps", fake)

    _wait(ctx, _body(_post("/api/timeline", ctx, {"map": map_id, "jobs": 4}))["job"])
    _wait(ctx, _body(_post("/api/timeline", ctx, {"map": map_id}))["job"])

    assert asked == [4, 0]


def test_a_timeline_written_under_the_old_meaning_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**A file with `totals` and no `added` predates the semantics change.**

    The bars used to be a delta of the totals and are now what each roll cost,
    which is a different number computed a different way. Reading an old file
    would draw perfectly plausible bars under a meaning nobody computed them
    for - the worst kind of wrong, because nothing looks broken.
    """
    ctx = _derived_ctx(tmp_path, monkeypatch, {"chunks": {}, "sections": {}})
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH], [NORTH])
    from fray_claude.gui.routes_view import _timeline_stamp

    cache.write_timeline(
        map_id, {"stamp": _timeline_stamp(ctx, enriched=False), "totals": [10.0, 12.5]}, tmp_path
    )

    payload = _body(_get("/api/timeline", ctx, map=map_id))

    assert payload["has_hours"] is False
    assert all(row["hours"] is None for row in payload["steps"])


@pytest.mark.real_export
def test_two_roll_clicks_parse_the_export_once(tmp_path: Path) -> None:
    """**The click used to bring its own 10MB export, and throw it away.**

    `roll_detail` prices through `batch._walk`, which loads the export, the
    tasks map and the rate scrape for itself - correct in a pool worker, where
    under `forkserver` the parent's copy would not be shared anyway, and pure
    waste in the server process, which is holding all three already. So the
    in-process caller hands `_walk` a `_Prepared` and the parse is the one the
    context did, however many rolls somebody opens.
    """
    reads: list[str] = []
    real = cache.read_chunkinfo

    def counting(*args: Any, **kwargs: Any) -> Any:
        reads.append("parse")
        return real(*args, **kwargs)

    ctx = Context(root=tmp_path)
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH, "12852"], [NORTH, "12852"])

    with mock.patch("fray_claude.gui.derivation.cache.read_chunkinfo", counting), \
         mock.patch("fray_claude.runs.batch.read_chunkinfo", counting):
        _get("/api/roll", ctx, map=map_id, step="1")
        first = len(reads)
        _get("/api/roll", ctx, map=map_id, step="2")

    assert first <= 1, "the first roll parsed the export more than once"
    assert len(reads) == first, "the second roll parsed it again"


def test_a_roll_serves_the_task_names_a_step_summary_leaves_out(tmp_path: Path) -> None:
    """**One roll of the real export opened 239 tasks**, so `/api/timeline`
    carries counts and this carries names - the same ledger read, one step at
    a time and only when somebody asks to see it."""
    ctx = Context(root=tmp_path)
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH], [NORTH])

    payload = _body(_get("/api/roll", ctx, map=map_id, step="1"))

    # Whether this warms the context's export depends on whether there is one
    # to warm, so that question lives in its own test below rather than here -
    # `roll_baseline` needs no export for a run with no base map, but
    # `roll_detail` prices, and pricing walks the item graph.
    assert payload["chunk"] == NORTH
    # **The Tasks tab's own shape, over this roll's additions.** The overlay
    # used to render the ledger raw - every new task, flat, one heading per
    # skill - which listed sixty Construction builds where the tab shows the
    # furthest one. `panels.roll_panel` reconstructs the panel's inputs rather
    # than re-implementing its rules, so both draw from one `Panel` envelope.
    skills = next(s for s in payload["panel"]["sections"] if s["key"] == "skills")
    assert skills["active_total"] == 1
    (group,) = skills["groups"]
    assert group["active"] == [
        {
            "key": f"task-{NORTH}",
            "name": f"Task-{NORTH}",
            # The same name with its markup still on - here there is none, so
            # the two agree. See `panels._marked_name`.
            "marked": f"Task-{NORTH}",
            "note": "Slayer",
            "icon": "Slayer",
            "category": "Slayer",
        }
    ]
    # The counts still agree with what the timeline said.
    assert payload["tasks"] == 1


def test_a_roll_outside_the_run_is_a_400(tmp_path: Path) -> None:
    ctx = Context(root=tmp_path)
    map_id = _write_run(tmp_path, "sim", [LUMBRIDGE, NORTH], [NORTH])

    assert _get("/api/roll", ctx, map=map_id, step="9").status == HTTPStatus.BAD_REQUEST
    assert _get("/api/roll", ctx, map=map_id, step="x").status == HTTPStatus.BAD_REQUEST
    assert _get("/api/roll", ctx, map=map_id).status == HTTPStatus.BAD_REQUEST


def test_a_rolls_breakdown_is_absent_rather_than_wrong_when_it_cannot_be_priced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**The pie is an addition, not a precondition.**

    Pricing one roll needs the export and the scraped rates. A run cached
    without either still has a ledger, so the overlay must keep showing what it
    always showed - the chunk, the counts, the task names - with `hours: None`
    rather than a 500 or a zeroed chart that reads as "this roll cost nothing".
    """
    _write_run(tmp_path, "batch", [LUMBRIDGE, NORTH], [NORTH])
    ctx = Context(root=tmp_path)

    payload = _body(_get("/api/roll", ctx, map="batch", step="1"))

    assert payload["chunk"] == NORTH
    assert payload["hours"] is None


def test_step_zero_has_no_breakdown_because_it_is_not_a_roll(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 0 is the state the run started from - a baseline, not a roll - so
    there is no "hours this roll added" to break down."""
    _write_run(tmp_path, "batch", [LUMBRIDGE, NORTH], [NORTH])

    payload = _body(_get("/api/roll", Context(root=tmp_path), map="batch", step="0"))

    assert payload["chunk"] is None
    assert payload["hours"] is None


def test_a_roll_hides_a_skill_the_base_map_has_already_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**A roll's list has to mean "news".**

    Unlocking a chunk opens a Cooking task at level 20; a base map that has
    already ticked the 99 Cooking cape is not looking for one, and the Tasks
    tab would not show it. The ceiling comes from the base payload's completed
    challenges, levelled through the export - which is why this route parses
    it, and why the slider's routes still do not.
    """
    export = {
        "chunks": {LUMBRIDGE: {}, NORTH: {}},
        "challenges": {
            "Cooking": {
                "Buy the ~|cooking cape|~": {"Level": 99},
                "Cook a ~|cup of tea|~": {"Level": 20},
            }
        },
    }
    ctx = _derived_ctx(tmp_path, monkeypatch, export)
    directory = cache.claim_batch("sim", tmp_path, kind=cache.SIMULATED)
    run = cache.run_dir(directory, 1)
    cache.write_sim_run(
        run,
        map_id=f"{directory.name}/{run.name}",
        data={"chunks": {"unlocked": {LUMBRIDGE: LUMBRIDGE, NORTH: NORTH}}},
        simulation={"run": run.name, "batch": directory.name, "rolls": [NORTH]},
        ledger=[{
            "order": 1,
            "chunk_id": NORTH,
            "new_sections": {},
            "new_tasks": {"Cooking": {"Cook a ~|cup of tea|~": 20}},
            "new_unsupported": [],
            "bis_upgrades": {},
        }],
    )
    cache.write_sim_batch(
        directory,
        {"base_payload": {
            "chunks": {"unlocked": {LUMBRIDGE: LUMBRIDGE}},
            "chunkinfo": {"completedChallenges": {"Cooking": {"Buy the ~|cooking cape|~": True}}},
        }},
    )
    map_id = f"{directory.name}/{run.name}"

    skills = next(
        section
        for section in _body(_get("/api/roll", ctx, map=map_id, step="1"))["panel"]["sections"]
        if section["key"] == "skills"
    )

    assert skills["groups"] == [], "a task below the completed ceiling is not news"


def test_the_graph_counts_what_the_overlay_lists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**A column that says 2 and opens to show 1 is worse than either.**

    The bars measured `Step.task_count` - the raw ledger - while the overlay
    under them showed the filtered set, so hovering said `Cooking: 3` on a
    roll whose panel was empty. Both now come from `roll_panels`, one walk.
    """
    export = {
        "chunks": {LUMBRIDGE: {}, NORTH: {}},
        "challenges": {
            "Cooking": {
                "Buy the ~|cooking cape|~": {"Level": 99},
                "Cook a ~|cup of tea|~": {"Level": 20},
            },
            "Thieving": {"Rob a ~|gem stall|~": {"Level": 75}},
        },
    }
    ctx = _derived_ctx(tmp_path, monkeypatch, export)
    directory = cache.claim_batch("sim", tmp_path, kind=cache.SIMULATED)
    run = cache.run_dir(directory, 1)
    cache.write_sim_run(
        run,
        map_id=f"{directory.name}/{run.name}",
        data={"chunks": {"unlocked": {LUMBRIDGE: LUMBRIDGE, NORTH: NORTH}}},
        simulation={"run": run.name, "batch": directory.name, "rolls": [NORTH]},
        ledger=[{
            "order": 1,
            "chunk_id": NORTH,
            "new_sections": {},
            "new_tasks": {
                "Cooking": {"Cook a ~|cup of tea|~": 20},
                "Thieving": {"Rob a ~|gem stall|~": 75},
            },
            "new_unsupported": [],
            "bis_upgrades": {},
        }],
    )
    cache.write_sim_batch(
        directory,
        {"base_payload": {
            "chunks": {"unlocked": {LUMBRIDGE: LUMBRIDGE}},
            "chunkinfo": {"completedChallenges": {"Cooking": {"Buy the ~|cooking cape|~": True}}},
        }},
    )
    map_id = f"{directory.name}/{run.name}"

    graph = _body(_get("/api/timeline", ctx, map=map_id))["steps"][1]
    overlay = _body(_get("/api/roll", ctx, map=map_id, step="1"))

    # Two tasks in the ledger, one of them behind a 99 Cooking cape.
    assert graph["tasks"] == 1
    assert graph["tasks_by_group"] == {"Skills": 1}
    assert (overlay["tasks"], overlay["tasks_by_group"]) == (graph["tasks"], graph["tasks_by_group"])
    # And the breakdown names the overlay's headings, not the skills - after
    # the filter a skill contributes at most one row.
    assert "Cooking" not in graph["tasks_by_group"]


def test_settings_are_served_whole_even_when_nothing_is_stored(ctx: Context) -> None:
    """The page carries no defaults of its own, so a first run must still get a
    complete settings object rather than an empty one."""
    body = _body(_get("/api/settings", ctx))
    assert body["hours_scale"] == "log"
    assert len(body["hours_bands"]) == 5
    assert body["hours_bands"][-1]["upto"] is None


def test_reading_settings_never_parses_the_export(ctx: Context) -> None:
    _get("/api/settings", ctx)
    assert not ctx.derivations.loaded


def test_a_hand_edited_settings_file_is_validated_on_the_way_out(ctx: Context) -> None:
    """`read_gui_settings` is deliberately tolerant, so the nonsense has to be
    caught here - otherwise editing the file by hand goes round the POST
    handler and puts an unusable band into the page."""
    cache.write_gui_settings({"hours_scale": "sqrt", "hours_bands": []}, ctx.root)
    body = _body(_get("/api/settings", ctx))
    assert body["hours_scale"] == "log"
    assert len(body["hours_bands"]) == 5

