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
    from fray_claude.gui.routes_derived import WHOLE_CHUNK_SECTION

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
    """`/api/diff` is `fray diff`, and the one route allowed to derive twice.

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
    """`fray unlock --chunk X --cache-map NAME`, reached from the chunk panel.

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
    assert envelope["kind"] == cache.UNLOCKED
    assert set(envelope["data"]["chunks"]["unlocked"]) == {LUMBRIDGE, NORTH}
    # One job, recorded on the run as well as the batch - see `batch.py`.
    assert cache.read_batch(saved["name"], tmp_path, kind=cache.UNLOCKED)["batch_id"]


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
    assert not (tmp_path / "cache" / "maps" / cache.UNLOCKED).exists()


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
