"""The expensive path: routes that need a derivation, and say so.

`/api/{chunk,sections,diff,unlock,estimate,tasks}` and their payload builders.
Every one of these loads a `ChunkInfo` (~0.1s) and derives (~0.8s cold, ~3ms
from `cache/derived/`), which is exactly the cost `routes_view.py` exists to
avoid paying by accident.

`/api/diff` is the one route allowed to be slow: it derives *both* sides,
because "what did those chunks actually give me" is a question about sections,
tasks, sources and BiS and has no cheap answer. The map's own delta uses
`delta.diff_names` instead, in `worldmap.py`, and must stay there.

`_estimate_payload` is a thin shell over `costing/inputs.py`, shared with the
CLI so the two apps cannot price one map differently - read that module before
changing what this returns.
"""

from __future__ import annotations

from typing import Any
from fray_claude.gui.derivation import DerivedState
from fray_claude.derive.delta import MapSide
from fray_claude.model.summary import _mapping
from fray_claude.store.derived_cache import cached_derive
from fray_claude.derive.delta import compare_maps
from fray_claude.gui.worldmap import grid_position
from fray_claude.costing import inputs
from fray_claude.gui.http import Context


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
    from fray_claude.derive.unlock import tasks_added_by

    delta = tasks_added_by(
        state.state,
        state.unlocked,
        chunk_id,
        derive_with=lambda st, un: cached_derive(
            st, un, ctx.derivations.digests(), root=ctx.root
        ),
    )
    return delta.as_dict()


def _estimate_payload(state: DerivedState, ctx: Context) -> dict[str, Any]:
    """`fray estimate`, plus whether the DPS bridge contributed.

    The bridge is an optional extra, so an estimate computed with it and one
    computed without are different numbers - and the screen has to be able to
    say which it is showing.

    **The assembly is `costing.inputs`', not this module's.** It was this
    module's, in a copy of `cli.py`'s that had already lost `pinned_slayer` -
    so the panel and the command could price one map differently, and could
    overwrite each other's answer in `cache/derived/` while doing it. Where
    this panel's time goes is unchanged: `estimate` is 8.8ms and `enrich` is
    662ms, which is why the latter is cached beside the derivation.
    """
    answer = inputs.estimate_answer(
        state.state,
        state.unlocked,
        state.derived,
        ctx.derivations.digests(),
        root=ctx.root,
        reference=ctx.derivations.reference(),
    )
    return answer.as_dict(state.map_id)
