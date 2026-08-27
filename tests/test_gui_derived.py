"""Tests for `gui/routes_derived.py`: the routes that need a ChunkInfo and a derive.

`handle_request` is pure - strings in, a `Response` out - so every test
here exercises the real routing without binding a socket.
"""

from __future__ import annotations

import json
import time
from http import HTTPStatus
from pathlib import Path
from typing import Any

import pytest

from chunksim.store import cache
from chunksim.gui.server import Context, Response, handle_request


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


def test_a_split_chunks_contents_are_found_and_attributed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**Contents live in one of two places and reading one is wrong.**

    An unsplit chunk carries Monster/NPC/Object at its top level; a split one
    carries nothing there and puts each branch inside `Sections`. 512 of the
    real export's chunks are split - Lumbridge among them - so a top-level
    read reported the castle as empty.

    They are collated into one list per kind, because the question is "what
    is in this square" - but which section something sits in still decides
    whether you can reach it, so that survives as a per-entity flag.
    """
    _write_map(tmp_path, "fray", [LUMBRIDGE])
    ctx = _derived_ctx(
        tmp_path,
        monkeypatch,
        {
            "chunks": {
                LUMBRIDGE: {
                    "Nickname": "Lumbridge Castle",
                    "Sections": {
                        "1": {"Monster": {"Duck": 11}, "NPC": {"Hans": 1}},
                        "2": {"Monster": {"Giant rat": 3}},
                    },
                }
            },
            "sections": {LUMBRIDGE: {"1": [], "2": []}},
        },
    )

    payload = _body(_get("/api/chunk", ctx, map="fray", chunk=LUMBRIDGE))

    assert payload["nickname"] == "Lumbridge Castle"
    monsters = {row["name"]: row for row in payload["contents"]["monster"]}
    assert sorted(monsters) == ["Duck", "Giant rat"]
    assert monsters["Duck"]["sections"] == ["1"]
    assert monsters["Giant rat"]["sections"] == ["2"]
    assert [row["name"] for row in payload["contents"]["npc"]] == ["Hans"]
    assert {s["section"] for s in payload["sections"]} == {"1", "2"}


def test_an_unsplit_chunk_reads_its_top_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_map(tmp_path, "fray", [LUMBRIDGE])
    ctx = _derived_ctx(
        tmp_path,
        monkeypatch,
        {"chunks": {LUMBRIDGE: {"Monster": {"Cow": 4}}}, "sections": {}},
    )

    payload = _body(_get("/api/chunk", ctx, map="fray", chunk=LUMBRIDGE))

    assert [row["name"] for row in payload["contents"]["monster"]] == ["Cow"]
    assert payload["contents"]["monster"][0]["reachable"] is True
    assert payload["sections"][0]["reachable"] is True


def test_a_locked_chunk_reports_nothing_reachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """You can see what is in a square without being able to get to it."""
    _write_map(tmp_path, "fray", [LUMBRIDGE])
    ctx = _derived_ctx(
        tmp_path,
        monkeypatch,
        {"chunks": {"13106": {"Monster": {"Cow": 4}}}, "sections": {}},
    )

    payload = _body(_get("/api/chunk", ctx, map="fray", chunk="13106"))

    assert payload["unlocked"] is False
    assert payload["reachable_sections"] == 0
    assert [row["name"] for row in payload["contents"]["monster"]] == ["Cow"]
    assert payload["contents"]["monster"][0]["reachable"] is False


def test_every_placed_chunk_gets_a_section_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**An unsplit chunk is one section, and the overlay has to say so.**

    Only split chunks used to appear, so shading the map left every unsplit
    square bare - which reads as missing data rather than as "this chunk is
    not divided". They carry `WHOLE_CHUNK_SECTION` instead, because upstream
    drew no mask for a shape that is the whole square: the browser fills it.

    Locked chunks are in, all-red, since "what is behind this square" is
    asked hardest about one you have not got.
    """
    from chunksim.gui.routes_derived import WHOLE_CHUNK_SECTION

    _write_map(tmp_path, "fray", [LUMBRIDGE])
    ctx = _derived_ctx(
        tmp_path,
        monkeypatch,
        {
            "chunks": {
                LUMBRIDGE: {"Sections": {"0": {}, "1": {}}},
                NORTH: {"Monster": {"Cow": 4}},
                "Abyss": {"Monster": {"Abyssal leech": 1}},
            },
            "sections": {LUMBRIDGE: {"0": [], "1": []}},
        },
    )

    chunks = _body(_get("/api/sections", ctx, map="fray"))["chunks"]

    # Split and unlocked: section 0 comes free with the chunk, 1 does not.
    assert chunks[LUMBRIDGE] == {"0": True, "1": False}
    # Unsplit and locked: one section, and you cannot reach it.
    assert chunks[NORTH] == {WHOLE_CHUNK_SECTION: False}
    # A named area has no square, so there is nothing to shade.
    assert "Abyss" not in chunks


def test_the_full_diff_reports_both_directions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`/api/diff` is `chunksim diff`, and the one route allowed to derive twice.

    The map view answers the *chunks* question from a set difference in
    microseconds, which is why it does not call `compare_maps`. This one has
    to: sections, tasks, sources and BiS have no cheap answer.
    """
    _write_map(tmp_path, "before", [LUMBRIDGE])
    _write_map(tmp_path, "after", [LUMBRIDGE, NORTH])
    ctx = _derived_ctx(
        tmp_path,
        monkeypatch,
        {
            "chunks": {LUMBRIDGE: {"Monster": {"Cow": 4}}, NORTH: {"Monster": {"Duck": 11}}},
            "sections": {},
        },
    )

    payload = _body(_get("/api/diff", ctx, map1="before", map2="after"))

    assert payload["counts"]["chunks"] == {"added": 1, "removed": 0}
    assert list(payload["chunks"]["added"]) == [NORTH]
    assert payload["chunks"]["removed"] == []
    # The Duck comes with the chunk, so the sources branch moves too.
    assert payload["counts"]["sources"]["added"] >= 1
    assert payload["before_map"] == "before"
    assert payload["after_map"] == "after"


def test_the_full_diff_needs_both_maps(tmp_path: Path) -> None:
    response = _get("/api/diff", Context(root=tmp_path), map1="before")

    assert response.status == HTTPStatus.BAD_REQUEST
    assert "map2" in _body(response)["error"]


def test_the_areas_route_names_every_region_that_is_part_of_a_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Static per export, so no `map` and no derivation - just the parse.

    Which region is part of `Kurask Lair` does not depend on anybody's map,
    which is why the browser asks once at boot and never invalidates it.
    """
    _write_map(tmp_path, "fray", [LUMBRIDGE])
    ctx = _derived_ctx(
        tmp_path,
        monkeypatch,
        {
            "chunks": {
                "4751": {"Name": "Kurask Lair"},
                LUMBRIDGE: {"Monster": {"Cow": 4}},
            },
            "sections": {},
        },
    )

    payload = _body(_get("/api/areas", ctx))

    assert payload["areas"] == {"4751": "Kurask Lair"}


def test_unlocking_a_chunk_you_already_have_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The question has no meaning, and a zero-delta answer would look like a
    verdict rather than a category error."""
    _write_map(tmp_path, "fray", [LUMBRIDGE])
    ctx = _derived_ctx(
        tmp_path, monkeypatch, {"chunks": {LUMBRIDGE: {}}, "sections": {}}
    )

    response = _get("/api/unlock", ctx, map="fray", chunk=LUMBRIDGE)

    assert response.status == HTTPStatus.BAD_REQUEST
    assert "already unlocked" in _body(response)["error"]


def test_unlocking_a_chunk_writes_a_map_of_its_own_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`chunksim unlock --chunk X --cache-map NAME`, reached from the chunk panel.

    The kind is the assertion that matters: a map made by adding one chunk by
    hand is `unlocked`, not `simulated`, because the picker has to say which.
    """
    _write_map(tmp_path, "fray", [LUMBRIDGE])
    ctx = _derived_ctx(
        tmp_path,
        monkeypatch,
        {"chunks": {LUMBRIDGE: {}, NORTH: {}}, "sections": {}},
    )
    ctx = Context(root=tmp_path, check_origin=False, derivations=ctx.derivations)

    job = _wait(ctx, _body(_post("/api/unlock", ctx, {"map": "fray", "chunk": NORTH}))["job"])

    assert job["state"] == "done", job.get("error")
    saved = job["result"]
    assert saved["chunk"] == NORTH
    assert saved["unlocked_chunks"] == 2
    envelope = cache.read_cache(saved["open"], tmp_path)
    assert envelope["kind"] == cache.EDITED
    assert set(envelope["data"]["chunks"]["unlocked"]) == {LUMBRIDGE, NORTH}
    # One job, recorded on the run as well as the batch - see `batch.py`.
    assert cache.read_batch(saved["name"], tmp_path, kind=cache.EDITED)["batch_id"]


def test_unlocking_a_chunk_you_already_hold_fails_the_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The preview refuses it too. Saving a copy of the map under a new name
    and calling it an unlock would be the worse answer of the two."""
    _write_map(tmp_path, "fray", [LUMBRIDGE])
    ctx = _derived_ctx(tmp_path, monkeypatch, {"chunks": {LUMBRIDGE: {}}, "sections": {}})
    ctx = Context(root=tmp_path, check_origin=False, derivations=ctx.derivations)

    job = _wait(ctx, _body(_post("/api/unlock", ctx, {"map": "fray", "chunk": LUMBRIDGE}))["job"])

    assert job["state"] == "failed"
    assert "already unlocked" in job["error"]
    assert not (tmp_path / "cache" / "maps" / cache.EDITED).exists()


def test_an_unlock_against_a_missing_map_fails_the_post_not_the_job(tmp_path: Path) -> None:
    """Same rule `simulate` follows: a bad base map is answered immediately."""
    ctx = Context(root=tmp_path, check_origin=False)

    assert _post("/api/unlock", ctx, {"map": "nope", "chunk": NORTH}).status == (
        HTTPStatus.NOT_FOUND
    )


@pytest.mark.parametrize("payload", [{"chunk": NORTH}, {"map": "fray"}, {}])
def test_an_unlock_without_its_required_fields_is_a_400(
    tmp_path: Path, payload: dict[str, Any]
) -> None:
    ctx = Context(root=tmp_path, check_origin=False)
    assert _post("/api/unlock", ctx, payload).status == HTTPStatus.BAD_REQUEST


def test_a_step_against_a_map_with_no_history_is_refused(ctx: Context) -> None:
    """**Not a silent fall-through to the map.** A caller asking about roll 0
    of something that never rolled is asking about a history that does not
    exist, and answering a different question is how a panel comes to describe
    a different world than the map beside it.

    It also matters that this is refused rather than tolerated: `load_step`
    commits the ticked-this-chunk ledger, which is right for a simulated world
    and wrong for a real one, so step 0 of a fetched map would quietly blank
    its `(Active)` markers.
    """
    response = _get("/api/tasks", ctx, map="fray", step="0")

    assert response.status == HTTPStatus.BAD_REQUEST
    assert "no rolls to step through" in _body(response)["error"]


def test_a_step_that_is_not_a_number_is_refused(ctx: Context) -> None:
    """Refused before anything is loaded - it is a malformed URL, not a miss."""
    response = _get("/api/tasks", ctx, map="fray", step="halfway")

    assert response.status == HTTPStatus.BAD_REQUEST
    assert "not a number" in _body(response)["error"]


def test_every_derivation_route_takes_the_same_step(ctx: Context) -> None:
    """**One resolver, six routes.** Each would otherwise decide for itself
    what a step meant, and the first to forget would show the finished run
    under a rewound world."""
    for path, extra in (
        ("/api/tasks", {}),
        ("/api/estimate", {}),
        ("/api/training", {}),
        ("/api/training-method", {"skill": "Crafting", "task": "Cut a ~|ruby|~"}),
        ("/api/item-sources", {"item": "Bronze axe"}),
        ("/api/item-route-materials", {"item": "Bronze axe", "route": "make", "provider": "x"}),
        ("/api/sections", {}),
        ("/api/chunk", {"chunk": LUMBRIDGE}),
        ("/api/unlock", {"chunk": NORTH}),
        ("/api/search", {"q": "bronze"}),
    ):
        response = _get(path, ctx, map="fray", step="1", **extra)
        assert response.status == HTTPStatus.BAD_REQUEST, f"{path} ignored the step"


def _knob(ctx: Context, path: str, map_id: str = "fray") -> Response:
    """`/api/heuristic`, whose own parameter is called `path` - which collides
    with `_get`'s first argument, hence a helper rather than a keyword."""
    return handle_request(
        "GET", "/api/heuristic", {"path": [path], "map": [map_id]}, ctx
    )


def test_a_knob_reports_where_its_number_came_from(ctx: Context) -> None:
    """The row already had the number; what the dialog adds is the layer."""
    cache.write_overrides({"monsters": {"Goblin": {"value": 200.0}}}, ctx.root)

    body = _body(_knob(ctx, "monsters/Goblin"))

    assert body["layer"] == "site"
    assert body["number"] == 200.0
    assert body["editable"] is True


def test_a_knob_nobody_has_set_is_still_offered(ctx: Context) -> None:
    """Otherwise the only numbers you could correct are the corrected ones."""
    body = _body(_knob(ctx, "monsters/Goblin"))

    assert body["layer"] is None and body["editable"] is True


def test_a_knob_path_that_is_not_a_branch_is_a_400(ctx: Context) -> None:
    """These paths address a file that is read back and parsed."""
    response = _knob(ctx, "nonsense/Goblin")

    assert response.status == HTTPStatus.BAD_REQUEST
    assert "not an override branch" in _body(response)["error"]


def test_writing_a_map_scoped_override_moves_that_map_only(ctx: Context) -> None:
    """**Which file is the page's decision, carried as `scope`.** Browse is the
    standing opinion and writes the checked-in file; a map's own is what
    somebody learned about that map."""
    reply = _body(
        _post(
            "/api/heuristic",
            ctx,
            {"path": "monsters/Goblin", "value": 250.0, "scope": "map", "map": "fray"},
        )
    )

    assert reply["layer"] == "map" and reply["number"] == 250.0
    assert cache.read_map_overrides("fray", ctx.root)["monsters"]["Goblin"]["value"] == 250.0
    assert cache.read_overrides(ctx.root) == {}


def test_clearing_an_override_removes_the_file(ctx: Context) -> None:
    """"No corrections" stays one state on disk rather than two that price
    identically - see `cache.write_map_overrides`."""
    _post(
        "/api/heuristic",
        ctx,
        {"path": "monsters/Goblin", "value": 250.0, "scope": "map", "map": "fray"},
    )

    reply = _body(
        _post(
            "/api/heuristic",
            ctx,
            {"path": "monsters/Goblin", "value": None, "scope": "map", "map": "fray"},
        )
    )

    assert reply["layer"] is None
    assert not cache.map_overrides_path("fray", ctx.root).exists()


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"path": "nonsense/x", "value": 1.0, "scope": "map", "map": "fray"}, "branch"),
        ({"path": "monsters/Goblin", "value": -5.0, "scope": "map", "map": "fray"}, "positive"),
        ({"path": "monsters/Goblin", "value": 1.0, "scope": "nope", "map": "fray"}, "scope"),
        ({"path": "monsters/Goblin", "value": 1.0, "scope": "map"}, "needs a map"),
        ({"path": "monsters/Goblin", "value": "fast", "scope": "map", "map": "fray"}, "number"),
    ],
)
def test_a_refused_override_is_a_400_rather_than_a_quiet_no_op(
    ctx: Context, payload: dict[str, Any], expected: str
) -> None:
    """**Visible refusal.** A 200 saying nothing happened is the silent failure
    `gui/settings.py` already records having shipped once."""
    response = _post("/api/heuristic", ctx, payload)

    assert response.status == HTTPStatus.BAD_REQUEST
    assert expected in _body(response)["error"]
    assert not cache.map_overrides_path("fray", ctx.root).exists()


def test_a_reachable_area_names_squares_the_map_has_not_rolled(ctx: Context) -> None:
    """**The join is the name and only the name.**

    `derive`'s area fold puts entries like `Dwarven Mine` in
    `expanded_chunks` beside the numeric ids, and those names are also the
    `Name` of real squares. The `sections` graph is *not* the mechanism: of
    the chunks in the block north of the surface, none has a `sections`
    branch and not one edge crosses into it.
    """
    cache.write_cache(
        "named",
        {"chunks": {"unlocked": {LUMBRIDGE: LUMBRIDGE}}},
        root=ctx.root,
    )

    response = _get("/api/reachable", ctx, map="named")

    # Without an export this is a 400 rather than a wrong answer; with one it
    # is a list. Either way it never reports a chunk already unlocked.
    if response.status == HTTPStatus.OK:
        ids = {entry["chunk_id"] for entry in _body(response)["chunks"]}
        assert LUMBRIDGE not in ids


def test_reachable_needs_a_map(ctx: Context) -> None:
    response = _get("/api/reachable", ctx)

    assert response.status == HTTPStatus.BAD_REQUEST


@pytest.mark.real_cache
def test_a_square_you_can_walk_into_is_not_greyed_out() -> None:
    """**The panel used to contradict the map, on the real export.**

    `_chunk_detail` asked `chunk_id in unlocked` alone, so a chunk behind a
    dungeon entrance - which costs no roll and which the map already outlines
    as somewhere you can go - had every section reported unreached and every
    monster in it greyed out. Needs the real cache because `expanded_chunks`
    only names an area after a real derivation folds one in; there is nothing
    to hand-build that would be this rather than a restatement of the code.
    """
    from chunksim.gui.routes_derived import reachable_by_area, walked_into
    from chunksim.gui.server import _state_at
    from chunksim.store.cache import data_root

    ctx = Context(root=data_root(), check_origin=False)
    state = _state_at({"map": ["fray"]}, ctx, "fray")
    assert not isinstance(state, Response)

    walk_ins = [str(c["chunk_id"]) for c in reachable_by_area(state)["chunks"]]
    assert walk_ins, "the reference map should reach areas by name"

    detail = _body(_get("/api/chunk", ctx, map="fray", chunk=walk_ins[0]))

    assert walked_into(state, walk_ins[0]) is True
    # Reachable, not held: the count in the bar is chunks the map *has*.
    assert detail["unlocked"] is False
    assert detail["walk_in"] is True
    assert all(section["reachable"] for section in detail["sections"])
    for rows in detail["contents"].values():
        assert all(row["reachable"] for row in rows), "a walk-in square must not grey its contents"


@pytest.mark.real_cache
def test_a_chunk_you_would_have_to_roll_is_still_greyed_out() -> None:
    """The other half, or the change would just be greying nothing at all. A
    roll candidate is locked by definition - the reachable, rollable and held
    sets do not intersect."""
    from chunksim.gui.server import _state_at
    from chunksim.store.cache import data_root

    ctx = Context(root=data_root(), check_origin=False)
    state = _state_at({"map": ["fray"]}, ctx, "fray")
    assert not isinstance(state, Response)

    candidates = _body(_get("/api/neighbours", ctx, map="fray"))["neighbours"]
    assert candidates

    detail = _body(_get("/api/chunk", ctx, map="fray", chunk=str(candidates[0]["chunk_id"])))

    assert detail["unlocked"] is False and detail["walk_in"] is False
    assert not any(section["reachable"] for section in detail["sections"])


def test_training_method_needs_skill_and_task(ctx: Context) -> None:
    """No fallback shape here, unlike `/api/training`'s own optional `skill` -
    a caller asking for one method has to name it."""
    response = _get("/api/training-method", ctx, map="fray")

    assert response.status == HTTPStatus.BAD_REQUEST


def _cache_minimal_chunkinfo(root: Path | None, challenges: dict[str, Any]) -> None:
    """A `chunkinfo`/`tasks_map` pair just real enough for `/api/training-method`
    to run against, without needing the real export. Both blobs, for the
    reason `cached_map`'s own docstring gives about two readers - the route
    reads `cache.read_chunkinfo` directly, and an empty `tasks_map` is a
    legitimate answer `reverse_tasks_map` handles."""
    cache.write_blob(cache.CHUNKINFO_BLOB_NAME, {"challenges": challenges}, "test", root=root)
    cache.write_blob(cache.TASKS_MAP_BLOB_NAME, {}, "test", root=root)


def test_an_unpriced_task_answers_no_tree_not_an_error(ctx: Context) -> None:
    """A task that is not a recipe-sourced method - here, one nothing has
    ever priced at all - is `training.trace_option`'s own scope refusal, not
    a lookup failure. The route must say so plainly rather than raising."""
    _cache_minimal_chunkinfo(
        ctx.root,
        {
            "Crafting": {
                "Cut a ~|ruby|~": {
                    "Primary": True,
                    "Output": "Ruby",
                    "Items": ["Chisel", "Uncut ruby*"],
                    "Level": 34,
                }
            }
        },
    )

    response = _get(
        "/api/training-method", ctx, map="fray", skill="Crafting", task="Cut a ~|ruby|~"
    )

    assert response.status == HTTPStatus.OK
    body = _body(response)
    assert body["tree"] is None
    assert body["skill"] == "Crafting"
    assert body["task"] == "Cut a ~|ruby|~"


def test_an_unknown_task_answers_no_tree_not_an_error(ctx: Context) -> None:
    _cache_minimal_chunkinfo(ctx.root, {})

    response = _get(
        "/api/training-method", ctx, map="fray", skill="Crafting", task="Cut a ~|sapphire|~"
    )

    assert response.status == HTTPStatus.OK
    assert _body(response)["tree"] is None


@pytest.mark.real_cache
def test_ruby_traces_to_the_gem_it_is_cut_from() -> None:
    """The feature's own worked example, against the real export: Ruby tops
    Crafting on `verf` (`chunksim training Crafting --map verf`), priced off
    a real wiki recipe, so it must have exactly one child - the uncut gem -
    and no more."""
    from chunksim.gui.server import _state_at
    from chunksim.store.cache import data_root

    ctx = Context(root=data_root(), check_origin=False)
    state = _state_at({"map": ["verf"]}, ctx, "verf")
    assert not isinstance(state, Response)

    response = _get(
        "/api/training-method", ctx, map="verf", skill="Crafting", task="Cut a ~|ruby|~"
    )

    assert response.status == HTTPStatus.OK
    tree = _body(response)["tree"]
    assert tree is not None
    assert tree["source"] == "recipe"
    assert len(tree["children"]) == 1
    assert tree["children"][0]["label"] == "Uncut ruby"
    assert tree["children"][0]["hours"] > 0
    # ~1,000 an hour, per the feature's own worked example - see
    # `training.rate_material_tree`.
    assert tree["per_hour"] == pytest.approx(tree["children"][0]["per_hour"])


def test_item_sources_needs_an_item(ctx: Context) -> None:
    """No fallback shape here either - the Find pane always names one."""
    response = _get("/api/item-sources", ctx, map="fray")

    assert response.status == HTTPStatus.BAD_REQUEST


def test_item_sources_lists_a_ground_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A spawn needs no scraped rate at all, which is what makes it the
    simplest real route to pin against - see `estimate.SPAWN_HOPS_PER_HOUR`."""
    _write_map(tmp_path, "fray", [LUMBRIDGE])
    ctx = _derived_ctx(
        tmp_path, monkeypatch, {"chunks": {LUMBRIDGE: {"Spawn": {"Widget": 2}}}}
    )

    payload = _body(_get("/api/item-sources", ctx, map="fray", item="Widget"))

    assert payload["item"] == "Widget"
    assert len(payload["routes"]) == 1
    (route,) = payload["routes"]
    assert route["route"] == "spawn"
    assert route["provider"] == LUMBRIDGE
    assert route["hours"] > 0


def test_item_sources_sorts_fastest_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two spawns of the same item, at different counts - a real choice
    between two routes, not one route asked about twice."""
    _write_map(tmp_path, "fray", [LUMBRIDGE, NORTH])
    ctx = _derived_ctx(
        tmp_path,
        monkeypatch,
        {
            "chunks": {
                LUMBRIDGE: {"Spawn": {"Widget": 1}},
                NORTH: {"Spawn": {"Widget": 10}},
            }
        },
    )

    payload = _body(_get("/api/item-sources", ctx, map="fray", item="Widget"))

    providers = [route["provider"] for route in payload["routes"]]
    hours = [route["hours"] for route in payload["routes"]]
    assert providers == [NORTH, LUMBRIDGE]
    assert hours == sorted(hours)


def test_item_sources_answers_no_routes_rather_than_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A thing nothing in the world provides is an empty list, the same
    "nothing found" every other Find answer already gives - not a 404 for
    what is an ordinary, expected outcome."""
    _write_map(tmp_path, "fray", [LUMBRIDGE])
    ctx = _derived_ctx(tmp_path, monkeypatch, {"chunks": {LUMBRIDGE: {}}})

    response = _get("/api/item-sources", ctx, map="fray", item="Nothing at all")

    assert response.status == HTTPStatus.OK
    assert _body(response)["routes"] == []


def test_item_route_materials_needs_all_four_params(ctx: Context) -> None:
    """The drill-down panel always names the exact row it is opening -
    no fallback shape, same contract `/api/item-sources` keeps for `item`."""
    response = _get(
        "/api/item-route-materials", ctx, map="fray", item="Widget", route="make"
    )

    assert response.status == HTTPStatus.BAD_REQUEST


def test_item_route_materials_lists_the_production_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A "make" row's own materials, kept - the click `item_routes`' docstring
    describes: `Amulet of power`'s `Enchant a diamond amulet` naming
    `Diamond amulet` and its runes."""
    _write_map(tmp_path, "fray", [LUMBRIDGE])
    ctx = _derived_ctx(
        tmp_path,
        monkeypatch,
        {
            "challenges": {
                "Extra": {
                    "Make a ~|widget|~": {
                        "Objects": ["Bench"],
                        "Items": ["Cog", "Widget metal"],
                        "Output": "Widget",
                    }
                }
            },
            "chunks": {LUMBRIDGE: {"Spawn": {"Cog": 1, "Widget metal": 1}}},
        },
    )

    payload = _body(
        _get(
            "/api/item-route-materials", ctx, map="fray",
            item="Widget", route="make", provider="Make a ~|widget|~",
        )
    )

    assert payload["item"] == "Widget"
    step = payload["step"]
    assert step is not None
    assert step["label"] == "Widget"
    assert {child["label"] for child in step["children"]} == {"Cog", "Widget metal"}


def test_item_route_materials_answers_none_for_a_non_drillable_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A kill, a shop trip, a ground spawn are *obtained*, not made from
    other items - the panel renders "nothing to drill into" rather than an
    error, the same `None` contract `/api/training-method`'s `tree` keeps."""
    _write_map(tmp_path, "fray", [LUMBRIDGE])
    ctx = _derived_ctx(
        tmp_path, monkeypatch, {"chunks": {LUMBRIDGE: {"Spawn": {"Widget": 2}}}}
    )

    payload = _body(
        _get(
            "/api/item-route-materials", ctx, map="fray",
            item="Widget", route="spawn", provider=LUMBRIDGE,
        )
    )

    assert payload["step"] is None


@pytest.mark.real_cache
def test_amulet_of_power_traces_through_its_enchant() -> None:
    """The feature's own worked example: `Enchant a diamond amulet` names
    `Diamond amulet` among its materials, and `Diamond amulet` itself has a
    real production chain underneath it (`String a ~|diamond amulet|~`) -
    the recursion the side panel exists for, in one response."""
    from chunksim.gui.server import _state_at
    from chunksim.store.cache import data_root

    ctx = Context(root=data_root(), check_origin=False)
    state = _state_at({"map": ["fray"]}, ctx, "fray")
    assert not isinstance(state, Response)

    sources = _body(_get("/api/item-sources", ctx, map="fray", item="Amulet of power"))
    make_row = next(r for r in sources["routes"] if r["route"] == "make")

    payload = _body(
        _get(
            "/api/item-route-materials", ctx, map="fray",
            item="Amulet of power", route="make", provider=make_row["provider"],
        )
    )

    step = payload["step"]
    assert step is not None
    diamond_amulet = next(
        child for child in step["children"] if child["label"] == "Diamond amulet"
    )
    assert diamond_amulet["children"]


@pytest.mark.real_cache
def test_mahogany_plank_traces_to_the_sawmill() -> None:
    """The feature's own worked example, against the real export: a
    mahogany plank has exactly one route on a real map - chop the logs, then
    the sawmill - which this project only found by asking this question by
    hand first (see `costing/estimate.py`'s `item_routes` docstring)."""
    from chunksim.gui.server import _state_at
    from chunksim.store.cache import data_root

    ctx = Context(root=data_root(), check_origin=False)
    state = _state_at({"map": ["fray"]}, ctx, "fray")
    assert not isinstance(state, Response)

    response = _get("/api/item-sources", ctx, map="fray", item="Mahogany plank")

    assert response.status == HTTPStatus.OK
    routes = _body(response)["routes"]
    assert routes
    assert routes[0]["route"] == "make"
    assert "process" in routes[0]["detail"].lower()
    assert routes[0]["hours"] > 0
    assert routes == sorted(routes, key=lambda r: r["hours"])
