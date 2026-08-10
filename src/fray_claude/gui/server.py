"""The local HTTP server behind `fray-gui`, and the routing it does.

**`handle_request` is a pure function and the `BaseHTTPRequestHandler` below is
a thin adapter over it.** That is the whole structural decision here: routing,
error mapping and every response body are decided by a function taking strings
and returning a `Response`, so `tests/test_gui_server.py` exercises the entire
surface without binding a socket. The repo's rule that no test touches the
network then holds in letter as well as in spirit - loopback is still a socket,
still a port to collide on, still a thing a sandbox can refuse.

**This module accepts inbound connections, which no other module in the project
does.** `api.py` remains the only module making *outbound* calls; the two rules
are about opposite directions and do not conflict. It binds `127.0.0.1` unless
told otherwise, and reads maps only through `cache.read_cache`.

**A request is milliseconds, so there is no cache to invalidate.** Rendering
needs `payload["chunks"]["unlocked"]` and nothing else - no `ChunkInfo` parse
(~1s), no `derive` (~0.15s warm), because a chunk's square is fixed by its id.
Every request therefore re-reads the map file, and a `fray fetch` or
`fray simulate` in another terminal shows up on the next poll with no
invalidation machinery and no restart. `/api/revision` is a `stat`, so polling
it twice a second costs nothing.

**The map's delta is a set difference, not `delta.compare_maps`.** That
function derives *both* sides unconditionally - the two `derive_with(...)`
calls are arguments to `compare`, so passing `branches={"chunks"}` narrows the
comparison and not the work - which would spend ~2s to answer something
`delta.diff_names` answers in microseconds. `/api/view` therefore uses
`diff_names`, and `/api/diff` is where `compare_maps` belongs: a separate,
deliberately slow route behind a button, because "what did those chunks give
me" is a question about sections, tasks, sources and BiS and there is no cheap
way to it.

**The world drawn bright is the *compared* map's.** `added` and `removed` are
`diff_names(base, compare)` either way, but a comparison asks what the base
becomes, so the hull traces the compared side's own set and the browser washes
a removed square like any other locked one. See `worldmap.build_view`.

**Path traversal is closed by construction rather than by sanitising.** Static
files come from a fixed allowlist, so no user-supplied string is ever joined
onto a path. Map ids need no checking here either, because `cache.split_map_id`
already rejects anything that is not a plain name or a `<name>/run-<n>` pair -
and a second, weaker check in this module is exactly how two guards drift
apart. `tests/test_gui_server.py` pins that reliance so it cannot be quietly
removed.

Manual checks this cannot make, since none of it is reachable from Python:

- zoom stays anchored under the cursor at both ends of the clamp;
- no seam appears between two adjacent unlocked chunks at any zoom;
- a drag released off-canvas does not strand the pointer;
- Lumbridge's square lands on Lumbridge.
"""

from __future__ import annotations

import json
import os
import time
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from fray_claude import cache, dps_bridge, estimate_inputs
from fray_claude.remote.api import (
    CHUNKINFO_URL,
    DEFAULT_TIMEOUT,
    MAP_TILE_ATTRIBUTION,
    MAP_TILE_MAP_ID,
    MAP_TILE_URL,
    MAP_TILE_VERSION_URL,
    TASKS_MAP_URL,
    FetchError,
    fetch_chunkinfo,
    fetch_map,
    fetch_map_tile_version,
    fetch_section_overlay,
    fetch_skill_icon,
    fetch_tasks_map,
)
from fray_claude.batch import RunResult, price_steps, run_batch, save_unlock
from fray_claude.build_info import read_build
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.delta import MapSide, compare_maps, diff_names
from fray_claude.derived_cache import cached_derive, cached_enrich, pricing_digests
from fray_claude.estimate import estimate, goal_levels, infer_levels
from fray_claude.heuristics import Heuristics, merge
from fray_claude.heuristics import load as load_heuristics
from fray_claude.neighbours import eligible_neighbours
from fray_claude.remote.scrape import SOURCE as SCRAPE_SOURCE
from fray_claude.remote.scrape import scrape
from fray_claude.search import build_world_index, search
from fray_claude.model.summary import _mapping, summarise
from fray_claude.gui.derivation import DerivedState, Derivations, unlocked_of
from fray_claude.gui.jobs import JobRegistry, JobState, Progress, StopCheck, as_int
from fray_claude.gui.panels import task_panel
from fray_claude.gui.worldmap import MapView, build_view, grid_position
from fray_claude.timeline import Step, matches as timeline_matches, replay, series
from fray_claude.timeline import stamp as timeline_stamp

#: The port `fray-gui` binds unless told otherwise. Arbitrary, and high enough
#: to need no privileges.
DEFAULT_PORT = 8731
DEFAULT_HOST = "127.0.0.1"

#: `Host` values that name this server whatever it bound, so a POST carrying
#: one is never a rebinding attempt. Anything else has to be named - see
#: `_origin_ok`.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

#: Binds that name no particular address, so they contribute nothing to the
#: allowlist: a wildcard is every interface, not a machine anyone types.
WILDCARD_HOSTS = frozenset({"0.0.0.0", "::", ""})

#: How long the server outlives its last client when nothing is holding it
#: open. The page polls `/api/revision` every 2s, so this is roughly seven
#: missed polls - long enough to survive a slow reload or a laptop briefly
#: asleep, short enough that a closed tab does not leave a process behind.
#: Only armed when no app window was opened; see `gui/browser.py`.
IDLE_TIMEOUT_SECONDS = 15.0

#: Text assets that ship inside the package. No map imagery is here or
#: anywhere else on this machine: the browser loads tiles straight from the
#: wiki's CDN - see `api.MAP_TILE_URL`.
RESOURCE_DIR = Path(__file__).resolve().parent / "resources"

#: **The whole static surface, as a fixed allowlist.** Four entries, matched by
#: equality, so nothing a caller sends is ever joined onto a path and traversal
#: has nowhere to happen. If this ever becomes a glob, the replacement needs
#: `resolve().is_relative_to(RESOURCE_DIR)` *after* unquoting - which is the
#: bug this shape exists to avoid.
_STATIC: dict[str, tuple[str, str]] = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/static/style.css": ("style.css", "text/css; charset=utf-8"),
}

_JSON = "application/json; charset=utf-8"


@dataclass(frozen=True)
class Response:
    """One HTTP response, decided before any socket is involved."""

    status: int
    content_type: str
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Context:
    """What a request is answered against.

    `root` is the cache root, so a test can point the whole server at a
    `tmp_path` the way every other cache-touching test does.
    """

    root: Path | None = None
    resources: Path = RESOURCE_DIR
    jobs: JobRegistry = field(default_factory=JobRegistry)
    #: Loaded on the first request that needs a derivation, never for the map
    #: view. See `gui/derivation.py`.
    derivations: Derivations = field(default_factory=Derivations)
    #: When the last client was heard from, for the idle shutdown. Mutable, so
    #: it is a one-element list rather than a field on a frozen dataclass -
    #: the alternative is unfreezing `Context`, and every other field here
    #: genuinely is constant.
    last_seen: list[float] = field(default_factory=lambda: [0.0])
    #: The map-tile version last resolved, so one server run scrapes the
    #: wiki once however many times the page asks. Mutable for the same reason
    #: `last_seen` is.
    tile_version: list[str] = field(default_factory=lambda: [""])
    #: Whether the browser-origin checks apply. Off in tests, which have no
    #: browser to send the headers this asserts on.
    check_origin: bool = True
    #: `Host` values that name this server besides loopback - what `--host`
    #: and `--allow-host` were given. Empty for an ordinary loopback bind.
    allowed_hosts: frozenset[str] = frozenset()
    #: Whether the idle shutdown is disarmed (`--keep-alive`), for a server
    #: meant to outlive the browser that reads it.
    keep_alive: bool = False

    def __post_init__(self) -> None:
        # `Derivations` needs the same root the rest of the context reads
        # from, and a default factory cannot see its siblings.
        if self.derivations._root is None and self.root is not None:
            object.__setattr__(self.derivations, "_root", self.root)


def _json(payload: Any, status: int = HTTPStatus.OK) -> Response:
    body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    return Response(status=status, content_type=_JSON, body=body)


def _error(message: str, status: int) -> Response:
    return _json({"error": message}, status)


def _unlocked(map_id: str, ctx: Context) -> tuple[dict[str, Any], int]:
    """One map's unlocked set and the mtime that dates it.

    The mtime is the live-reload token. It is deliberately not a hash of the
    payload: a `stat` is cheaper than a read, and the cost of a false positive
    is one redraw the user cannot see.
    """
    path = cache.resolve_map_path(map_id, ctx.root)
    envelope = cache.read_cache(map_id, ctx.root)
    revision = path.stat().st_mtime_ns
    return unlocked_of(envelope), revision


def _areas_for(unlocked: Mapping[str, Any], ctx: Context) -> dict[str, str] | None:
    """`chunkinfo.area_names()`, but **only when something needs it**.

    Resolving `Abyss` to the regions it occupies needs the 10MB export parsed,
    and the whole reason `/api/view` is milliseconds is that it does not do
    that. So the parse is conditional on the map actually holding a
    non-numeric id: every ordinary map has none, keeps the fast path, and a
    test pins that. A map that *does* hold one has no cheaper way to be drawn
    correctly, and pays about a second, once.
    """
    if not any(not chunk_id.isdigit() for chunk_id in unlocked):
        return None
    return ctx.derivations.chunk_info().area_names()


def build_map_view(
    map_id: str, compare: str | None, ctx: Context, step: int | None = None
) -> MapView:
    """The payload for one map, or for one map against another.

    `map_id` is the base and `compare` the other side, so `added` is what
    `compare` has and the base does not. That matches
    `fray diff --map1 <base> --map2 <compare> chunks` exactly.

    `step` rewinds a simulated run to the world after that many rolls. It is
    **exclusive of `compare`** - a comparison asks about two maps and a step
    asks about one map's past, and answering both at once would need a third
    colour for "gained by the roll, lost against the other side".
    """
    if step is not None:
        return _step_view(map_id, step, ctx)

    base, revision = _unlocked(map_id, ctx)
    if compare is None:
        return build_view(
            map_id=map_id,
            unlocked=base,
            revision=revision,
            areas=_areas_for(base, ctx),
        )

    other, other_revision = _unlocked(compare, ctx)
    branch = diff_names(base, other)
    return build_view(
        map_id=map_id,
        unlocked=base,
        added=branch.added,
        removed=branch.removed,
        compare_map_id=compare,
        # Either side changing has to invalidate the view, so the token spans
        # both. Summing is enough - it moves whenever either mtime does.
        revision=revision + other_revision,
        areas=_areas_for({**base, **other}, ctx),
    )


def _run_steps(map_id: str, ctx: Context) -> tuple[Step, ...]:
    """One run replayed, or `CacheMissError` when the map is not a run.

    **No export, no derivation** - the ledger and the saved payload are the
    whole input, which is what makes dragging the slider a JSON read. See
    `timeline.py`; a test asserts this route never loads `ChunkInfo`.
    """
    envelope = cache.read_cache(map_id, ctx.root)
    return replay(unlocked_of(envelope), cache.read_rolls(map_id, ctx.root))


def _step_view(map_id: str, step: int, ctx: Context) -> MapView:
    """The world after `step` rolls of a simulated run.

    Everything the run has rolled *so far* is `added`, so the simulation's
    growth accumulates green against the map it started from and the hull
    traces the world as it stood. No new drawing concept: `added` already
    means "this side has it and the base does not", and here the base is the
    run's own past.
    """
    steps = _run_steps(map_id, ctx)
    if not 0 <= step < len(steps):
        raise ValueError(f"step {step} is outside this run's 0..{len(steps) - 1}")
    unlocked = {chunk_id: True for chunk_id in sorted(steps[step].unlocked)}
    return build_view(
        map_id=map_id,
        unlocked=unlocked,
        added=[s.chunk_id for s in steps[1 : step + 1] if s.chunk_id],
        revision=cache.resolve_map_path(map_id, ctx.root).stat().st_mtime_ns,
        areas=_areas_for(unlocked, ctx),
    )


#: The branches of a chunk entry worth showing, in the order a panel reads
#: best: what you fight, then who you talk to, then what you interact with.
_CONTENT_KEYS = ("Monster", "NPC", "Object", "Shop", "Spawn", "Quest", "Clue", "Diary")


def _section_order(section_id: str) -> tuple[int, int, str]:
    """Sort sections `0, 1, 2, 10, W1, W2` rather than `0, 1, 10, 2, W1`.

    Upstream's water sections carry a `W` prefix and its numbered ones are
    strings, so the obvious `sorted()` puts `10` before `2` and reads as a
    bug in the panel.
    """
    if section_id.isdigit():
        return (0, int(section_id), "")
    digits = section_id.lstrip("W")
    if section_id.startswith("W") and digits.isdigit():
        return (1, int(digits), "")
    return (2, 0, section_id)


def _chunk_detail(state: DerivedState, chunk_id: str, ctx: Context) -> dict[str, Any]:
    """Everything the panel shows for one chunk.

    **A chunk's contents live in one of two places and reading only one of them
    is wrong.** An unsplit chunk carries `Monster`/`NPC`/`Object` at its top
    level; a split one carries nothing there and puts each branch inside
    `Sections`. 512 of the export's chunks are split - Lumbridge among them -
    so a top-level read reports the castle as empty.

    Attribution is per section rather than pooled, because **which section
    something is in decides whether you can reach it**. Unlocking a chunk makes
    section `0` reachable and no more, and `sections.py` works out the rest; a
    flat list of everything in the square would claim you have access to things
    behind a door you cannot open. `reachable` on each section is what the
    panel greys out.
    """
    info = state.state.chunk_info
    entry = info.chunk(chunk_id)
    reached = state.derived.reachable_sections.get(chunk_id, {})
    unlocked = chunk_id in state.unlocked
    declared = _mapping(entry, "Sections")

    sections: list[dict[str, Any]] = []
    if declared:
        for section_id in sorted(declared, key=_section_order):
            # Section "0" is reachable the moment the chunk is - which is
            # exactly why `reachable_sections` omits it.
            is_reached = unlocked and (section_id == "0" or bool(reached.get(section_id)))
            sections.append(
                {
                    "section": section_id,
                    "reachable": is_reached,
                    "source": _mapping(declared, section_id),
                }
            )
    else:
        sections.append({"section": "0", "reachable": unlocked, "source": entry})

    # **Collated across the chunk, not nested under each section.** A chunk
    # with six sections showed six short lists of the same kind of thing, and
    # the question is "what is in this square", not "how did upstream file
    # it". Which section something is in still decides whether you can *get*
    # to it, so that survives as a per-entity flag rather than as structure:
    # the panel greys an unreachable row instead of hiding a heading.
    contents: dict[str, list[dict[str, Any]]] = {}
    for key in _CONTENT_KEYS:
        rows: dict[str, dict[str, Any]] = {}
        for section in sections:
            for name in sorted(_mapping(section["source"], key)):
                row = rows.setdefault(
                    name, {"name": name, "reachable": False, "sections": []}
                )
                row["sections"].append(section["section"])
                # Reachable anywhere is reachable: the same monster in a
                # reached section and an unreached one is one you can fight.
                row["reachable"] = row["reachable"] or section["reachable"]
        if rows:
            contents[key.lower()] = [rows[name] for name in sorted(rows)]

    return {
        "chunk_id": chunk_id,
        "nickname": entry.get("Nickname") or entry.get("Name") or None,
        "unlocked": unlocked,
        "contents": contents,
        "sections": [
            {"section": s["section"], "reachable": s["reachable"]} for s in sections
        ],
        "reachable_sections": sum(1 for s in sections if s["reachable"]),
    }


#: The section id standing for "this whole square". An unsplit chunk has no
#: `Sections` branch and upstream drew no mask for it, so there is no shape to
#: composite - but it still *has* one section, and the overlay that shades
#: every other square while leaving these ones bare reads as a gap in the data
#: rather than as "this chunk is not divided". The browser fills the square
#: instead of fetching `<chunk>-*.png`; `cache.section_overlay_path`'s alphabet
#: holds no `*`, so a stray request for one is a 400 rather than a fetch.
WHOLE_CHUNK_SECTION = "*"


def _section_states(state: DerivedState) -> dict[str, dict[str, bool]]:
    """Which sections of each chunk you can reach.

    The whole map in one derivation, because the overlay shades every square
    on screen and asking per chunk would be one request per square.

    **Every chunk with a square appears, split or not.** A split one carries
    its declared sections; an unsplit one carries the single
    `WHOLE_CHUNK_SECTION` its square already is, which is reachable exactly
    when the chunk is unlocked. Ids with no square - named areas, underground
    regions - are dropped here rather than in the browser, because nothing can
    shade a chunk it cannot place and 700 of them are most of the payload.

    **Locked chunks are included, all-red.** The question the overlay answers
    is "what is behind this square", and that is asked hardest about a square
    you have not got yet - a candidate whose interesting half is behind a
    door is exactly the thing worth seeing before rolling.
    """
    reached = state.derived.reachable_sections
    states: dict[str, dict[str, bool]] = {}
    for chunk_id, entry in state.state.chunk_info.chunks.items():
        if grid_position(chunk_id) is None:
            continue
        declared = _mapping(entry, "Sections")
        unlocked = chunk_id in state.unlocked
        if not declared:
            states[chunk_id] = {WHOLE_CHUNK_SECTION: unlocked}
            continue
        states[chunk_id] = {
            section: unlocked
            and (section == "0" or bool(reached.get(chunk_id, {}).get(section)))
            for section in sorted(declared, key=_section_order)
        }
    return states


def _full_diff(map1: str, map2: str, ctx: Context) -> dict[str, Any]:
    """`fray diff --map1 --map2`, over every branch.

    **This is the one route that is allowed to be slow, and the one that has
    to use `compare_maps`.** The map view answers the same question about
    *chunks* in microseconds with `diff_names`, which is why it does not call
    this - but "what did those chunks actually give me" is a question about
    sections, tasks, sources and BiS, and there is no way to it that does not
    derive both sides. Both go through `cached_derive`, so the second look at
    a pair either side has been derived against is ~0.3s.

    `counts` is lifted out of `StateDelta.counts()` because a tuple is a JSON
    array and `[3, 1]` is not readable at the other end.
    """
    before = ctx.derivations.load(map1)
    after = ctx.derivations.load(map2)
    delta = compare_maps(
        MapSide(before.state, before.unlocked, map1),
        MapSide(after.state, after.unlocked, map2),
        derive_with=lambda st, un: cached_derive(
            st, un, ctx.derivations.digests(), root=ctx.root
        ),
    )
    return {
        "counts": {
            branch: {"added": added, "removed": removed}
            for branch, (added, removed) in delta.counts().items()
        },
        **delta.as_dict(),
    }


def _unlock_preview(state: DerivedState, chunk_id: str, ctx: Context) -> dict[str, Any]:
    """What unlocking `chunk_id` would add. Two derivations, so ~0.3s warm."""
    from fray_claude.unlock import tasks_added_by

    delta = tasks_added_by(
        state.state,
        state.unlocked,
        chunk_id,
        derive_with=lambda st, un: cached_derive(
            st, un, ctx.derivations.digests(), root=ctx.root
        ),
    )
    return delta.as_dict()


#: The reference blobs the page cares whether it has, and what to call them.
#: `tile_version` is deliberately absent: it is refetched on its own whenever
#: the wiki moves a render, and nobody would press a button for it.
#: `(blob, label, what to POST to /api/refresh)`. The page is told the third
#: rather than deriving it, so "which action refreshes this" is answered in
#: one place instead of in a lookup table on each side.
_REFERENCE_BLOBS = (
    (cache.CHUNKINFO_BLOB_NAME, "Chunk data", "chunkinfo"),
    (cache.WIKI_RATES_BLOB_NAME, "Wiki rates", "heuristics"),
)


def _reference_state(ctx: Context) -> list[dict[str, Any]]:
    """What reference data is on disk and when it was fetched.

    **Cheap on purpose** - a `stat` and the envelope's own header, not the
    payload - because the page asks on boot to decide whether anything is
    missing. Reading the 10MB chunk export to find out whether it exists
    would be a poor way to answer the question.
    """
    out: list[dict[str, Any]] = []
    for name, label, refresh in _REFERENCE_BLOBS:
        path = cache.blob_path(name, ctx.root)
        fetched_at = None
        if path.is_file():
            try:
                # The envelope's `fetched_at` sits in the first few hundred
                # bytes; `read_blob` would pull the whole export in.
                head = path.read_text(encoding="utf-8", errors="replace")[:400]
                marker = '"fetched_at": "'
                if marker in head:
                    fetched_at = head.split(marker, 1)[1].split('"', 1)[0]
            except OSError:  # pragma: no cover - a file we just stat'd
                fetched_at = None
        out.append(
            {
                "name": name,
                "label": label,
                "refresh": refresh,
                "cached": path.is_file(),
                "fetched_at": fetched_at,
                "size": path.stat().st_size if path.is_file() else 0,
            }
        )
    return out


def _timeline_stamp(ctx: Context, *, enriched: bool) -> dict[str, Any]:
    """What a stored hours series was computed against. See `timeline.stamp`.

    `enriched` says whether `dps_bridge` priced these numbers. It is recorded
    but **not compared**, because a simulation prices its own rolls with the
    estimator alone - free, since the derivation is already done - and paying
    `enrich`'s ~1.3s a roll would have tripled every batch. So the cheap
    answer is what a run is born with, and this is the upgrade.
    """
    digests = ctx.derivations.digests()
    return timeline_stamp(
        chunkinfo=digests.chunkinfo,
        tasks_map=digests.tasks_map,
        rates=cache.file_digest(cache.blob_path(cache.WIKI_RATES_BLOB_NAME, ctx.root)),
        overrides=_overrides_digest(ctx),
        enriched=enriched,
    )


def _overrides_digest(ctx: Context) -> str:
    """`heuristics/overrides.json` is checked in and hand-edited, so it moves
    without any fetch having happened - which is exactly the case a digest of
    the *fetched* inputs alone would miss."""
    try:
        return cache.file_digest(cache.overrides_path(ctx.root))
    except (OSError, cache.CacheMissError):
        return ""


def _floats(value: Any) -> list[float] | None:
    if not isinstance(value, list) or not all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in value
    ):
        return None
    return [float(v) for v in value]


def _cached_hours(
    map_id: str, ctx: Context
) -> tuple[list[float] | None, list[float] | None, bool]:
    """A run's stored hours - what each roll added, what was left - and whether
    `dps_bridge` priced them.

    A stamp mismatch reads as absent rather than as an error: the numbers are
    recomputable, and offering to recompute is a better answer than refusing
    to draw anything. **A file without `added` is one written under the old
    delta-of-totals meaning**, and is refused for the same reason - the bars
    would be drawn under a meaning they were never computed for.
    """
    try:
        stored = cache.read_timeline(map_id, ctx.root)
    except cache.CacheMissError:
        return None, None, False
    if not timeline_matches(stored.get("stamp"), _timeline_stamp(ctx, enriched=False)):
        return None, None, False
    added = _floats(stored.get("added"))
    if added is None:
        return None, None, False
    enriched = bool(_mapping(stored, "stamp").get("enriched"))
    return added, _floats(stored.get("totals")), enriched


def _timeline_payload(map_id: str, ctx: Context) -> dict[str, Any]:
    """The cheap half: every step, plus whatever hours are already on disk.

    **This must not parse the export.** The steps come from the ledger and the
    saved payload, and the hours come off disk or not at all - which is what
    lets the slider redraw at JSON-read speed. `_cached_hours` reads a digest
    stamp, which needs `Derivations.digests()`, and that reads file hashes
    rather than the file: no `ChunkInfo`, and a test pins it.
    """
    steps = _run_steps(map_id, ctx)
    added, totals, enriched = _cached_hours(map_id, ctx)
    rows = series(steps, totals=totals, added=added)
    # **Read back off the shaped rows, not off the stored list.** `series`
    # refuses a totals list that does not fit the run - a run re-rolled under
    # one name has a different number of steps - so asking the store instead
    # would let the flag promise hours the graph never got.
    has_hours = any(row["hours"] is not None for row in rows)
    return {
        "map_id": map_id,
        "steps": rows,
        "has_hours": has_hours,
        "enriched": enriched and has_hours,
        # Whether there is a better answer available than the one on screen.
        # Without the extra there is not, however the numbers were computed.
        "can_enrich": dps_bridge.DPS_AVAILABLE and not (enriched and has_hours),
        "dps": dps_bridge.DPS_AVAILABLE,
    }


def _estimate_payload(state: DerivedState, ctx: Context) -> dict[str, Any]:
    """`fray estimate`, plus whether the DPS bridge contributed.

    The bridge is an optional extra, so an estimate computed with it and one
    computed without are different numbers - and the screen has to be able to
    say which it is showing.

    **The assembly is `estimate_inputs`', not this module's.** It was this
    module's, in a copy of `cli.py`'s that had already lost `pinned_slayer` -
    so the panel and the command could price one map differently, and could
    overwrite each other's answer in `cache/derived/` while doing it. Where
    this panel's time goes is unchanged: `estimate` is 3.1ms and `enrich` is
    662ms, which is why the latter is cached beside the derivation.
    """
    answer = estimate_inputs.estimate_answer(
        state.state,
        state.unlocked,
        state.derived,
        ctx.derivations.digests(),
        root=ctx.root,
    )
    return answer.as_dict(state.map_id)


def _first(query: Mapping[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _static(path: str, ctx: Context) -> Response | None:
    entry = _STATIC.get(path)
    if entry is None:
        return None
    name, content_type = entry
    try:
        body = (ctx.resources / name).read_bytes()
    except FileNotFoundError:
        # A packaging fault, not a user one: the wheel shipped without its
        # resources. Says so, rather than 404ing like a bad URL.
        return _error(f"missing packaged resource {name!r}", HTTPStatus.INTERNAL_SERVER_ERROR)
    return Response(
        status=HTTPStatus.OK,
        content_type=content_type,
        body=body,
        # These change with the install, and the install is the only thing
        # that changes them, so revalidating every time costs nothing.
        headers={"Cache-Control": "no-cache"},
    )


def _tile_source(ctx: Context) -> dict[str, Any]:
    """Where the browser should get its map tiles.

    **This hands out a URL template; it never fetches a tile.** The tiles are
    CC BY-NC-SA 3.0 and this project is MIT, so caching them under `cache/` or
    serving them off loopback would make it a redistributor of NonCommercial
    artwork. Pointing the page at the wiki's own CDN makes it a page with a
    picture on it. That also means the `User-Agent` those tiles need is the
    browser's, which browsers always send - the 403 an anonymous script gets is
    not a problem anybody here has to solve.

    Only the *version* has to be resolved, and it is the fragile part: the wiki
    publishes no index, so it is scraped out of the map page's fallback image
    (`wiki.map_tile_version`). Three layers, in order:

    - `FRAY_TILE_VERSION`, which skips the network entirely;
    - a cached answer younger than `TILE_VERSION_MAX_AGE_HOURS`;
    - the wiki, written back to the cache.

    **A failed scrape falls back to the cached version rather than to
    nothing.** A stale version still draws a map; the render it names stays on
    the CDN. `error` is reported either way so the page can say the map may be
    out of date instead of quietly showing one.
    """
    source: dict[str, Any] = {
        "template": MAP_TILE_URL,
        "map_id": MAP_TILE_MAP_ID,
        "attribution": MAP_TILE_ATTRIBUTION,
        "attribution_url": MAP_TILE_VERSION_URL,
        "version": "",
        "error": None,
    }

    pinned = cache.tile_version_override()
    if pinned:
        return {**source, "version": pinned, "pinned": True}

    if ctx.tile_version[0]:
        return {**source, "version": ctx.tile_version[0]}

    cached, age = "", float("inf")
    try:
        cached, age = cache.read_tile_version(ctx.root)
    except cache.CacheMissError:
        pass
    if cached and age < cache.TILE_VERSION_MAX_AGE_HOURS:
        ctx.tile_version[0] = cached
        return {**source, "version": cached}

    try:
        version = fetch_map_tile_version(DEFAULT_TIMEOUT)
    except FetchError as exc:
        if cached:
            ctx.tile_version[0] = cached
            return {**source, "version": cached, "error": f"{exc} (using the last known version)"}
        return {**source, "error": str(exc)}

    cache.write_tile_version(version, MAP_TILE_VERSION_URL, ctx.root)
    ctx.tile_version[0] = version
    return {**source, "version": version}


def _cached_upstream_asset(
    path: Path, fetch: Callable[[], bytes], *, what: str
) -> Response:
    """Serve a small upstream image, fetching it once if this machine lacks it.

    **A lazy proxy rather than a download step**, because the two collections
    behind it are 1,534 section masks and 24 skill icons and nobody looks at
    all of either. A chunk's masks arrive when you first shade that chunk, and
    stay; the second visit is a disk read.

    This is the GUI reaching the network, which `api.py` otherwise owns alone -
    so it does not: the fetch is an `api` function passed in, and the bytes go
    to disk through `cache.py`. The only thing decided here is *when*.

    A miss is a 404 rather than an error. Upstream has a mask for every
    section it drew and nothing promises one exists for a section it did not,
    so "there is no mask" is an ordinary answer the caller draws nothing for.
    """
    try:
        blob: bytes | None = path.read_bytes()
    except FileNotFoundError:
        blob = None
    if blob is None:
        try:
            blob = fetch()
        except FetchError as exc:
            return _error(f"could not fetch {what}: {exc}", HTTPStatus.NOT_FOUND)
        cache.write_asset_at(path, blob)
    return Response(
        status=HTTPStatus.OK,
        content_type="image/png",
        body=blob,
        # Upstream regenerates these only when it redraws the world, and the
        # URL carries the identity, so this is genuinely immutable.
        headers={"Cache-Control": "max-age=31536000, immutable"},
    )


def _window_state(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Remember the window's shape, so the next launch opens the same one.

    Sent by the page, because only the page can see it: the server launched a
    browser and has no idea what the user then did to the window. Ignoring
    anything unrecognised keeps a hostile or stale caller from writing
    arbitrary JSON into the cache - the file is *read back* as command-line
    arguments, so its keys are exactly the four this understands.
    """
    geometry = {
        key: int(value)
        for key in ("width", "height", "x", "y")
        if isinstance(value := payload.get(key), (int, float))
    }
    if len(geometry) == 4 and geometry["width"] > 0 and geometry["height"] > 0:
        geometry["maximised"] = bool(payload.get("maximised"))
        cache.write_gui_window(geometry, ctx.root)
        return {"saved": True}
    return {"saved": False}


def _fetch_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Download any named map from Firebase, not only the one on screen.

    **An empty name means `fray`**, matching every `--map` default in the CLI,
    because that is the map this project exists for and typing it every time
    is friction for nothing. `cache.split_map_id` is what makes the name safe
    to accept from a browser at all - it rejects anything that is not
    `[A-Za-z0-9_.-]+`, so no second, weaker check belongs here.
    """
    map_id = str(payload.get("map") or "").strip() or cache.DEFAULT_MAP_ID
    if cache.split_map_id(map_id)[1] is not None:
        # A run is something this project computed. Firebase has never heard
        # of one, so asking it for `batch/run-001` is a mistake, not a fetch.
        raise ValueError(f"{map_id!r} names a run, not a map on source-chunk")

    def work(progress: Progress, _stop: StopCheck) -> dict[str, Any]:
        progress(f"fetching {map_id}")
        data = fetch_map(map_id, timeout=DEFAULT_TIMEOUT)
        path = cache.write_cache(map_id, data, ctx.root)
        unlocked = data.get("chunks", {}).get("unlocked", {})
        return {"map": map_id, "path": str(path), "unlocked_chunks": len(unlocked)}

    return {"job": ctx.jobs.submit("fetch", work).id}


def _simulate_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    map_id = str(payload.get("map") or "").strip()
    name = str(payload.get("name") or "").strip()
    if not map_id:
        raise ValueError("missing 'map'")
    if not name:
        raise ValueError("missing 'name' for the simulated map")
    rolls = as_int(payload, "rolls", 1)
    runs = as_int(payload, "runs", 1)
    jobs = as_int(payload, "jobs", 1)
    seed_raw = payload.get("seed")
    seed = None if seed_raw in (None, "") else as_int({"s": seed_raw}, "s", 0) or None

    # Read the base map now, so a bad id fails the POST rather than a job.
    envelope = cache.read_cache(map_id, ctx.root)

    def work(progress: Progress, stop: StopCheck) -> dict[str, Any]:
        # **Rolls, not runs.** A run's cost is its rolls, so `2/3 runs` on a
        # 3x100 job is three updates across four minutes and the two in
        # between say nothing. `countsIn` in `app.js` reads `k/N` either way.
        total = rolls * runs
        rolled = 0
        finished = 0

        def roll(_run: int, _order: int, chunk_id: str) -> None:
            nonlocal rolled
            rolled += 1
            progress(f"{rolled}/{total} rolls - {chunk_id}" + (" - stopping" if stop() else ""))

        def report(result: RunResult) -> None:
            nonlocal finished, rolled
            finished += 1
            # Pooled runs report nothing per roll, so the count catches up
            # here; inline it is already there and this only re-states it.
            rolled = max(rolled, finished * rolls)
            if jobs > 1:
                progress(f"{rolled}/{total} rolls - {finished}/{runs} runs")

        progress(f"0/{total} rolls")
        batch = run_batch(
            name=name,
            payload=envelope["data"],
            base_map=map_id,
            base_fetched_at=envelope.get("fetched_at"),
            rolls=rolls,
            runs=runs,
            jobs=jobs,
            seed=seed,
            root=ctx.root,
            on_complete=report,
            # Only inline: a worker has no channel back, so `run_batch`
            # ignores this above `--jobs 1` and reports per run instead.
            on_roll=roll if jobs == 1 else None,
            should_stop=stop,
        )
        kept = sum(len(run.rolls) for run in batch.runs)
        return {
            "batch": batch.name,
            "runs": len(batch.runs),
            "rolls": kept,
            "rolls_requested": total,
            "cancelled": stop(),
            # What to put in the map picker afterwards, resolved the way
            # `cache.read_cache` resolves a bare batch name. A batch stopped
            # before its first roll finished has no run to open.
            "open": (
                ""
                if not batch.runs
                else batch.name
                if len(batch.runs) == 1
                else f"{batch.name}/{batch.runs[0].name}"
            ),
        }

    return {"job": ctx.jobs.submit("simulate", work).id}


def _unlock_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """`fray unlock --chunk X --cache-map NAME`: add one chunk by hand.

    **The same path as `GET /api/unlock`, one step further on.** The GET
    answers "what would this give me" and keeps nothing; this saves the world
    it was describing. Both derive twice, which is why this is a job rather
    than an inline action even though the write itself is instant - cold, the
    export parse alone is a second.

    The eligibility check is deliberately *not* made: `fray unlock` will price
    any chunk on the map, candidate or not, because "what if I could get
    there" is a fair question. Already-unlocked is refused, since adding a
    chunk that is already held would write a copy of the map under a new name
    and call it an unlock.
    """
    map_id = str(payload.get("map") or "").strip()
    chunk_id = str(payload.get("chunk") or "").strip()
    if not map_id:
        raise ValueError("missing 'map'")
    if not chunk_id:
        raise ValueError("missing 'chunk'")
    name = str(payload.get("name") or "").strip() or f"{map_id}-{chunk_id}"

    # Read the base map now, so a bad id fails the POST rather than a job.
    envelope = cache.read_cache(map_id, ctx.root)

    def work(progress: Progress, _stop: StopCheck) -> dict[str, Any]:
        from fray_claude.unlock import tasks_added_by

        progress(f"deriving {map_id}")
        state = ctx.derivations.load(map_id)
        if chunk_id in state.unlocked:
            raise ValueError(f"chunk {chunk_id} is already unlocked on {map_id}")
        progress(f"deriving {map_id} with {chunk_id}")
        delta = tasks_added_by(
            state.state,
            state.unlocked,
            chunk_id,
            derive_with=lambda st, un: cached_derive(
                st, un, ctx.derivations.digests(), root=ctx.root
            ),
        )
        saved = save_unlock(
            name=name,
            payload=envelope["data"],
            delta=delta,
            base_map=map_id,
            base_fetched_at=envelope.get("fetched_at"),
            root=ctx.root,
        )
        return {
            **saved.as_dict(),
            "tasks": delta.task_count,
            "sections": sum(len(s) for s in delta.new_sections.values()),
            "bis_upgrades": len(delta.bis_upgrades),
            # `read_cache` resolves a one-run batch by its bare name, so this
            # is what the picker should select afterwards.
            "open": saved.name,
        }

    return {"job": ctx.jobs.submit(f"unlock {chunk_id}", work).id}


def _timeline_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Price every step of a run, and store the answer beside its ledger.

    **This is the expensive half and it is a job for one reason:
    `dps_bridge.enrich`.** Measured on the real export, a step costs ~0.01s to
    derive and estimate when the derivation is cached - and ~1.3s more when
    the `dps` extra is installed, because the kill rates are recomputed from
    the map's own BiS gear. A 50-roll run is therefore a minute or so, and
    skipping `enrich` is not the fix: the Estimate tab uses it, and a timeline
    that disagreed with the tab beside it would be worse than a slow one.

    So it is paid once. The result goes to `timeline.json` stamped with what
    it was computed against, and every later viewing is a file read.

    Derivations come from `cached_derive`, so under the default
    `--cache-behaviour all` every step is already on disk and the derive cost
    is zero. Under `extremities` or `none` they are recomputed at ~0.9s each -
    slower, but not an error, and the progress line says which is happening.
    """
    map_id = str(payload.get("map") or "").strip()
    if not map_id:
        raise ValueError("missing 'map'")
    jobs = as_int(payload, "jobs", 0)
    steps = _run_steps(map_id, ctx)

    def work(progress: Progress, _stop: StopCheck) -> dict[str, Any]:
        workers = jobs if jobs > 0 else (os.process_cpu_count() or 1)

        def report(done: int, total: int) -> None:
            # `k/N` is the shape `app.js`'s `countsIn` parses into a real bar.
            progress(f"{done}/{total} slices - {workers} workers")

        progress(f"0/1 slices - {workers} workers")
        added, totals = price_steps(
            map_id=map_id,
            held=[sorted(step.unlocked) for step in steps],
            jobs=jobs,
            root=ctx.root,
            on_progress=report,
        )
        cache.write_timeline(
            map_id,
            {
                "stamp": _timeline_stamp(ctx, enriched=dps_bridge.DPS_AVAILABLE),
                "added": added,
                "totals": totals,
            },
            ctx.root,
        )
        return {"map": map_id, "steps": len(added), "hours": round(totals[-1], 1)}

    return {"job": ctx.jobs.submit(f"timeline {map_id}", work).id}


def _cancel_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Ask a running job to stop.

    **The id is in the body, not the path**, so this joins `_ACTIONS` like
    every other action and inherits the `Sec-Fetch-Site`/`Host` checks rather
    than needing a second dispatch that could forget them.

    **A request, not a kill**, and the reply says so: the work stops where it
    safely can - `run_batch` finishes the roll it is on - so the job is still
    `running` when this answers and the page keeps polling. Cancelling a job
    that has already finished is a no-op rather than an error, because the
    button and the last poll race and "it had already finished" needs no
    handling by anyone.
    """
    job_id = str(payload.get("job") or "").strip()
    if not job_id:
        raise ValueError("missing 'job'")
    job = ctx.jobs.cancel(job_id)
    if job is None:
        raise cache.CacheMissError(f"no such job {job_id!r}")
    return {"job": job.id, "state": str(job.state), "stopping": job.stopping.is_set()}


def _refresh_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Re-download the reference data `fray chunkinfo` and `fray heuristics` get.

    Both in one action because they are one decision - the chunkinfo export and
    the wiki rates are the two static inputs, and refreshing one without the
    other leaves the estimator quoting numbers against a world that moved.
    """
    what = str(payload.get("what") or "chunkinfo")
    if what not in ("chunkinfo", "heuristics"):
        raise ValueError(f"unknown refresh target {what!r}")

    def work(progress: Progress, _stop: StopCheck) -> dict[str, Any]:
        if what == "chunkinfo":
            progress("downloading the chunk export (~10 MiB)")
            info = fetch_chunkinfo(DEFAULT_TIMEOUT)
            cache.write_blob(cache.CHUNKINFO_BLOB_NAME, info, CHUNKINFO_URL, ctx.root)
            progress("downloading the tasks map")
            tasks = fetch_tasks_map(DEFAULT_TIMEOUT)
            cache.write_blob(cache.TASKS_MAP_BLOB_NAME, tasks, TASKS_MAP_URL, ctx.root)
            # The export changed underneath us, so anything parsed from the old
            # one is now wrong. Dropping it is cheaper than reasoning about it.
            ctx.derivations.reset()
            return {"refreshed": "chunkinfo", "chunks": len(info.get("chunks", {}))}

        # `fray heuristics`, run through the same function so the two cannot
        # produce different files. Needs the export parsed - it asks the wiki
        # about the quests and slayer masters *this* export names.
        result = scrape(ctx.derivations.chunk_info(), timeout=DEFAULT_TIMEOUT, progress=progress)
        cache.write_blob(cache.WIKI_RATES_BLOB_NAME, result.config, SCRAPE_SOURCE, ctx.root)
        return {"refreshed": "heuristics", **result.as_dict()}

    return {"job": ctx.jobs.submit(f"refresh {what}", work).id}


def _remove_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Delete cached maps, or every simulated one.

    Fetched maps are refused unless `include_fetched` says otherwise, matching
    `fray maps rm`: a computed map records what made it, and a fetched one
    costs a round trip and is the thing everything else is derived from.
    """
    names = payload.get("names")
    include_fetched = bool(payload.get("include_fetched"))
    if payload.get("all"):
        removed = cache.remove_computed(ctx.root)
        return {"removed": removed}
    if not isinstance(names, list) or not names:
        raise ValueError("missing 'names' to remove")
    removed = []
    for name in names:
        cache.remove_map(str(name), ctx.root, include_fetched=include_fetched)
        removed.append(str(name))
    return {"removed": removed}


def _prune_job(payload: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    """Age out cached derivations. Pure recomputation, so nothing is at risk."""
    # `None` means "all of them", which is what an omitted age asks for.
    raw = payload.get("older_than")
    older_than = None if raw is None or raw == "" else float(raw)
    dropped = cache.prune_derived(ctx.root, max_age_days=older_than)
    return {"dropped": len(dropped), "freed": sum(entry.size for entry in dropped)}


_ACTIONS: dict[str, Callable[[Mapping[str, Any], Context], dict[str, Any]]] = {
    "/api/fetch": _fetch_job,
    "/api/simulate": _simulate_job,
    "/api/unlock": _unlock_job,
    "/api/timeline": _timeline_job,
    "/api/cancel": _cancel_job,
    "/api/refresh": _refresh_job,
    "/api/maps/remove": _remove_job,
    "/api/derived/prune": _prune_job,
    "/api/window": _window_state,
}


def normalise_host(value: str) -> str:
    """A `Host` header or a `--host` value as a bare address, for comparison.

    Strips the port, the brackets an IPv6 literal carries in a URL, and case -
    hostnames are case-insensitive, so `Devbox.tailnet.ts.net` is the machine
    `devbox.tailnet.ts.net` is. A bare IPv6 address is left alone: it is only
    the bracketed form that can carry a port, so `::1` is two colons and not a
    host with a port on it.
    """
    host = value.strip()
    if host.startswith("["):
        host = host.partition("]")[0].lstrip("[")
    elif host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    return host.casefold()


def _origin_ok(
    headers: Mapping[str, str], allowed: frozenset[str] = frozenset()
) -> str | None:
    """Why this POST should be refused, or `None` if it is fine.

    **A loopback bind stops other machines, not other tabs.** Any page you have
    open can POST to 127.0.0.1 and the browser will send it - cross-site
    request forgery. It cannot read the reply, so the exposure here is
    nuisance-grade: burn CPU on a simulation, write junk into `cache/sims/`.
    Two header checks close it for nothing:

    - `Sec-Fetch-Site` must be `same-origin`. Every current browser sends it,
      and a cross-site POST is exactly what it reports.
    - `Host` must **name this server**, which closes DNS rebinding - a hostile
      domain resolving to this address so that its page's origin *is* this
      server.

    **What names this server is loopback plus whatever `--host`/`--allow-host`
    said**, which is why this takes an allowlist rather than testing for
    loopback. Serving a tailnet address is a real use - drive the machine over
    ssh, read the map from a laptop - and hardcoding loopback did not refuse
    that, it *half* served it: every panel rendered and every button 403'd,
    which is a worse outcome than either serving it or refusing to.

    The allowlist is **named, never inferred**. A wildcard bind names no
    address, so `--host 0.0.0.0` alone still refuses; and no name is resolved
    on a request path, since that would be a network call from the module that
    makes none, on the request of whoever sent the header.

    Deliberately no per-launch token: it would put a secret in the URL and
    break bookmarking to buy little more than this. Beyond loopback the address
    is the whole of the access control, which `--host`'s help text says.
    """
    site = headers.get("Sec-Fetch-Site")
    if site is not None and site != "same-origin":
        return f"cross-site request refused (Sec-Fetch-Site: {site})"
    host = normalise_host(headers.get("Host") or "")
    if host and host not in LOOPBACK_HOSTS and host not in allowed:
        return f"unexpected Host header {host!r}"
    return None


def touch(ctx: Context) -> None:
    """Record that a client is still there."""
    ctx.last_seen[0] = time.monotonic()


def idle_seconds(ctx: Context) -> float:
    """How long since a client last asked for anything, or `0.0` if never.

    Zero rather than infinity for the never-seen case, and the difference is
    not academic: `should_stop` compares this against a timeout, so infinity
    would make a server nobody has opened yet stop *immediately* - which is
    exactly what `--no-browser` is, for the seconds between binding and the
    user pasting the URL.
    """
    if not ctx.last_seen[0]:
        return 0.0
    return time.monotonic() - ctx.last_seen[0]


def should_stop(ctx: Context, timeout: float = IDLE_TIMEOUT_SECONDS) -> bool:
    """Whether the last client has gone and nothing is holding the server open.

    Three things hold it open, and only the first is obvious:

    - a client asked for something within `timeout`;
    - **nobody has connected yet** - a server waiting to be opened is not an
      idle one, and `--no-browser` prints a URL for someone to paste;
    - **a job is running.** Closing the tab that started a simulation should
      not throw the simulation away; the browser leaving is not a reason to
      abandon work already begun, which will be in the cache when a window
      next opens.

    `--keep-alive` disarms it entirely: a server left running over ssh is meant
    to outlive the browser that reads it, and stopping fifteen seconds after a
    laptop's tab closed is a server you have to go back and restart.
    """
    if ctx.keep_alive:
        return False
    if not ctx.last_seen[0]:
        return False
    if any(job.state is JobState.RUNNING for job in ctx.jobs.recent()):
        return False
    return idle_seconds(ctx) > timeout


def handle_request(
    method: str,
    path: str,
    query: Mapping[str, list[str]],
    ctx: Context,
    *,
    if_none_match: str | None = None,
    body: bytes = b"",
    headers: Mapping[str, str] | None = None,
) -> Response:
    """Route one request. Pure: strings in, a `Response` out."""
    touch(ctx)
    if method == "POST":
        return _handle_post(path, body, headers or {}, ctx)
    if method not in ("GET", "HEAD"):
        return _error(f"{method} is not supported", HTTPStatus.METHOD_NOT_ALLOWED)

    static = _static(path, ctx)
    if static is not None:
        return static

    # Both names are validated by `cache.py` against an alphabet with no `.`
    # and no `/` in it, and a `ValueError` there is a malformed URL, not a
    # missing file - so it is a 400 rather than the 404 a real miss gets.
    if path.startswith("/assets/section/") and path.endswith(".png"):
        name = path.removeprefix("/assets/section/").removesuffix(".png")
        try:
            target = cache.section_overlay_path(name, ctx.root)
        except ValueError as exc:
            return _error(str(exc), HTTPStatus.BAD_REQUEST)
        return _cached_upstream_asset(
            target, lambda: fetch_section_overlay(name), what=f"section overlay {name}"
        )

    if path.startswith("/assets/skill/") and path.endswith(".png"):
        skill = path.removeprefix("/assets/skill/").removesuffix(".png")
        try:
            target = cache.skill_icon_path(skill, ctx.root)
        except ValueError as exc:
            return _error(str(exc), HTTPStatus.BAD_REQUEST)
        return _cached_upstream_asset(
            target, lambda: fetch_skill_icon(skill), what=f"{skill} icon"
        )

    try:
        if path == "/api/maps":
            return _json(
                [
                    # `size` is the tooltip's, not the library's: `MapEntry`
                    # describes what a map *is*, and how many bytes it happens
                    # to occupy is a fact about this disk.
                    {**entry.as_dict(), "size": cache.map_size(entry.map_id, ctx.root)}
                    for entry in cache.list_maps(ctx.root, expand_runs=True)
                ]
            )

        if path == "/api/build":
            # **Which install is answering, for the page to watermark itself
            # with.** The same question `fray`'s first line answers, asked of
            # the server rather than of the terminal - and worth asking of the
            # server, because with `--host` the page may be on a different
            # machine from the checkout anyone is editing. Two stat calls, on
            # the package's own metadata; see `build_info.py`.
            return _json(read_build().as_dict())

        if path == "/api/reference":
            return _json({"reference": _reference_state(ctx)})

        if path == "/api/areas":
            # Static per export - which region is part of which named place
            # does not depend on any map - so no `map` parameter and no
            # derivation. It does need the export parsed; that is why the
            # browser asks for it once at boot rather than per view.
            return _json({"areas": ctx.derivations.chunk_info().area_names()})

        if path == "/api/tiles":
            return _json(_tile_source(ctx))

        if path == "/api/jobs":
            return _json([job.as_dict() for job in ctx.jobs.recent()])

        if path.startswith("/api/jobs/"):
            job = ctx.jobs.get(path.removeprefix("/api/jobs/"))
            if job is None:
                return _error("no such job", HTTPStatus.NOT_FOUND)
            return _json(job.as_dict())

        if path == "/api/summary":
            map_id = _first(query, "map")
            if map_id is None:
                return _error("missing required parameter 'map'", HTTPStatus.BAD_REQUEST)
            envelope = cache.read_cache(map_id, ctx.root)
            summary = summarise(envelope["data"])
            return _json(
                {
                    "map_id": map_id,
                    "kind": envelope.get("kind", cache.FETCHED),
                    "created_at": envelope.get("fetched_at"),
                    "unlocked_chunks": summary.unlocked_chunks,
                    "chunk_order_entries": summary.chunk_order_entries,
                    "rules_enabled": summary.rules_enabled,
                    "rules_total": summary.rules_total,
                    "active_tasks": summary.active_tasks,
                    "active_task_total": summary.active_task_total,
                }
            )

        if path == "/api/neighbours":
            map_id = _first(query, "map")
            if map_id is None:
                return _error("missing required parameter 'map'", HTTPStatus.BAD_REQUEST)
            state = ctx.derivations.load(map_id)
            entries = eligible_neighbours(state.state, state.unlocked, state.derived)
            return _json({"map_id": map_id, "neighbours": [n.as_dict() for n in entries]})

        if path == "/api/sections":
            map_id = _first(query, "map")
            if map_id is None:
                return _error("missing required parameter 'map'", HTTPStatus.BAD_REQUEST)
            return _json(
                {"map_id": map_id, "chunks": _section_states(ctx.derivations.load(map_id))}
            )

        if path == "/api/diff":
            map1 = _first(query, "map1")
            map2 = _first(query, "map2")
            if map1 is None or map2 is None:
                return _error(
                    "missing required parameter 'map1' or 'map2'", HTTPStatus.BAD_REQUEST
                )
            return _json({"map1": map1, "map2": map2, **_full_diff(map1, map2, ctx)})

        if path == "/api/chunk":
            map_id = _first(query, "map")
            chunk_id = _first(query, "chunk")
            if map_id is None or chunk_id is None:
                return _error(
                    "missing required parameter 'map' or 'chunk'", HTTPStatus.BAD_REQUEST
                )
            state = ctx.derivations.load(map_id)
            return _json(_chunk_detail(state, chunk_id, ctx))

        if path == "/api/unlock":
            map_id = _first(query, "map")
            chunk_id = _first(query, "chunk")
            if map_id is None or chunk_id is None:
                return _error(
                    "missing required parameter 'map' or 'chunk'", HTTPStatus.BAD_REQUEST
                )
            state = ctx.derivations.load(map_id)
            if chunk_id in state.unlocked:
                return _error(f"chunk {chunk_id} is already unlocked", HTTPStatus.BAD_REQUEST)
            return _json(_unlock_preview(state, chunk_id, ctx))

        if path == "/api/search":
            term = _first(query, "q")
            if term is None:
                return _error("missing required parameter 'q'", HTTPStatus.BAD_REQUEST)
            limit = max(1, min(200, int(_first(query, "limit") or 40)))
            # **`unlocked` and `derived` are what make `available` mean
            # anything.** Without them every hit and every one of its
            # locations comes back locked, which is not a cheaper answer -
            # it is a wrong one, and it silently made the whole panel say
            # "nothing here is reachable". `fray search` has always passed
            # both; this is the same call.
            map_id = _first(query, "map")
            against = ctx.derivations.load(map_id) if map_id else None
            info = against.state.chunk_info if against else ctx.derivations.chunk_info()
            results = search(
                build_world_index(info),
                term,
                unlocked=against.unlocked if against else None,
                derived=against.derived if against else None,
                limit=limit,
            )
            return _json({"query": term, "results": [r.as_dict() for r in results]})

        if path == "/api/estimate":
            map_id = _first(query, "map")
            if map_id is None:
                return _error("missing required parameter 'map'", HTTPStatus.BAD_REQUEST)
            return _json(_estimate_payload(ctx.derivations.load(map_id), ctx))

        if path == "/api/tasks":
            map_id = _first(query, "map")
            if map_id is None:
                return _error("missing required parameter 'map'", HTTPStatus.BAD_REQUEST)
            state = ctx.derivations.load(map_id)
            return _json({"map_id": map_id, **task_panel(state.derived)})

        if path == "/api/derived":
            return _json(
                [
                    {
                        "key": cached.key,
                        "size": cached.size,
                        "accessed_at": cached.accessed_at.isoformat(),
                    }
                    for cached in cache.list_derived(ctx.root)
                ]
            )

        if path == "/api/roll":
            map_id = _first(query, "map")
            raw = _first(query, "step")
            if map_id is None or raw is None:
                return _error(
                    "missing required parameter 'map' or 'step'", HTTPStatus.BAD_REQUEST
                )
            try:
                index = int(str(raw))
            except ValueError:
                return _error(f"step {raw!r} is not a number", HTTPStatus.BAD_REQUEST)
            steps = _run_steps(map_id, ctx)
            if not 0 <= index < len(steps):
                return _error(
                    f"step {index} is outside this run's 0..{len(steps) - 1}",
                    HTTPStatus.BAD_REQUEST,
                )
            roll = steps[index]
            # **The names, which `/api/timeline` deliberately leaves out.** One
            # roll of the real export opened 239 tasks; sending every name for
            # every step would be most of a megabyte to draw a bar chart with.
            # This is the same ledger read, asked for one step at a time.
            return _json(
                {
                    **roll.as_dict(),
                    "tasks_by_skill_names": {
                        skill: list(names)
                        for skill, names in sorted(roll.tasks_added.items())
                        if names
                    },
                }
            )

        if path == "/api/timeline":
            map_id = _first(query, "map")
            if map_id is None:
                return _error("missing required parameter 'map'", HTTPStatus.BAD_REQUEST)
            return _json(_timeline_payload(map_id, ctx))

        if path in ("/api/view", "/api/revision"):
            map_id = _first(query, "map")
            if map_id is None:
                return _error("missing required parameter 'map'", HTTPStatus.BAD_REQUEST)
            compare = _first(query, "compare")
            raw_step = _first(query, "step")
            try:
                step = None if raw_step in (None, "") else int(str(raw_step))
            except ValueError:
                return _error(f"step {raw_step!r} is not a number", HTTPStatus.BAD_REQUEST)
            try:
                view = build_map_view(map_id, compare, ctx, step)
            except ValueError as exc:
                return _error(str(exc), HTTPStatus.BAD_REQUEST)
            if path == "/api/revision":
                return _json({"revision": view.revision})
            return _json({**view.as_dict(), "step": step})
    except cache.CacheMissError as exc:
        # The message already names the command that would fix it, which is
        # exactly what the browser should show.
        return _error(str(exc), HTTPStatus.NOT_FOUND)

    return _error(f"no route for {path!r}", HTTPStatus.NOT_FOUND)


def _handle_post(
    path: str, body: bytes, headers: Mapping[str, str], ctx: Context
) -> Response:
    action = _ACTIONS.get(path)
    if action is None:
        return _error(f"no route for {path!r}", HTTPStatus.NOT_FOUND)

    if ctx.check_origin:
        refusal = _origin_ok(headers, ctx.allowed_hosts)
        if refusal is not None:
            return _error(refusal, HTTPStatus.FORBIDDEN)

    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError as exc:
        return _error(f"malformed JSON body: {exc}", HTTPStatus.BAD_REQUEST)
    if not isinstance(payload, dict):
        return _error("expected a JSON object", HTTPStatus.BAD_REQUEST)

    try:
        return _json(action(payload, ctx), HTTPStatus.ACCEPTED)
    except ValueError as exc:
        return _error(str(exc), HTTPStatus.BAD_REQUEST)
    except cache.CacheMissError as exc:
        return _error(str(exc), HTTPStatus.NOT_FOUND)


class MapServer(ThreadingHTTPServer):
    """A threading server carrying the `Context` its handler answers against.

    Threading is not decoration: the 8.4MiB image occupies a connection for a
    moment, and a single-threaded server would stall `/api/view` behind it.

    Subclassed rather than passing the context through `functools.partial`
    because the stub types `RequestHandlerClass` as `type[BaseRequestHandler]`,
    so a partial needs an ignore where an attribute needs one `cast`.
    """

    daemon_threads = True

    def __init__(self, address: tuple[str, int], context: Context) -> None:
        self.context = context
        super().__init__(address, MapHandler)


class MapHandler(BaseHTTPRequestHandler):
    """The adapter. Everything it decides, `handle_request` decided first."""

    server_version = "fray-gui"
    #: Suppresses the `Python/3.14` half of the `Server:` header. The version
    #: of an interpreter is not something a local tool should announce.
    sys_version = ""

    def do_GET(self) -> None:  # noqa: N802 - the stdlib's spelling
        self._respond()

    def do_POST(self) -> None:  # noqa: N802 - the stdlib's spelling
        length = int(self.headers.get("Content-Length") or 0)
        self._respond(body_in=self.rfile.read(length) if length else b"")

    def do_HEAD(self) -> None:  # noqa: N802 - the stdlib's spelling
        self._respond(body=False)

    def _respond(self, *, body: bool = True, body_in: bytes = b"") -> None:
        parts = urlsplit(self.path)
        context = cast(MapServer, self.server).context
        try:
            response = handle_request(
                self.command or "GET",
                parts.path,
                parse_qs(parts.query),
                context,
                if_none_match=self.headers.get("If-None-Match"),
                body=body_in,
                headers={name: value for name, value in self.headers.items()},
            )
        except Exception:  # noqa: BLE001 - a handler must not take the server down
            # The traceback goes to the terminal, never to the browser: it
            # names paths on this machine.
            traceback.print_exc()
            response = _error("internal error; see the terminal", HTTPStatus.INTERNAL_SERVER_ERROR)

        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        for name, value in response.headers.items():
            self.send_header(name, value)
        self.end_headers()
        if body and response.body:
            self.wfile.write(response.body)

    def log_message(self, format: str, *args: Any) -> None:
        """One line per request, and only when asked.

        The stdlib default writes a line per request to stderr, which a poll
        every two seconds turns into an unreadable terminal.
        """
        if os.environ.get("FRAY_GUI_VERBOSE"):
            super().log_message(format, *args)


__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "LOOPBACK_HOSTS",
    "WILDCARD_HOSTS",
    "RESOURCE_DIR",
    "Context",
    "MapHandler",
    "MapServer",
    "IDLE_TIMEOUT_SECONDS",
    "Response",
    "build_map_view",
    "handle_request",
    "idle_seconds",
    "normalise_host",
    "should_stop",
    "touch",
]
