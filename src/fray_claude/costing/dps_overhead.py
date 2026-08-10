"""The harness that fitted the overhead constants, kept rather than deleted.

`measure_overhead` samples real fights to work out how much of a kill is *not*
the fight - banking, running back, the tick the calculator does not model. It
has **no caller anywhere in `src/`**: it produced the numbers now written into
`dps_bridge.KillEstimate`, and its job is to be re-runnable when someone doubts
them.

It lives here rather than in `dps_bridge.py` for that reason. That module is
1,700 lines because the licence boundary says it must be - it is the only module
allowed to import `osrs_dps` - and a benchmarking tool nothing calls is the one
part of it that was paying that cost for nothing. It reaches the library
through `dps_bridge`'s own names, so the boundary is intact: `from __future__
import annotations` means the type references never evaluate at runtime.
"""

from __future__ import annotations

from fray_claude.costing.dps_bridge import (
    GROUP_BOSSES,
    Kit,
    MonsterIndex,
    _require,
    best_kill,
    build_loadouts,
    candidate_targets,
    load_monster_index,
)


from fray_claude.model.chunkinfo import ChunkInfo
from collections.abc import Mapping
from fray_claude.costing.heuristics import Rate
from dataclasses import dataclass


@dataclass(frozen=True)
class OverheadSample:
    """One monster where both a wiki rate and a computed kill time exist."""

    monster: str
    wiki_kph: float
    ttk: float
    #: `3600 / wiki_kph - ttk`. Negative means the computed fight is already
    #: slower than the wiki's whole cycle - see `measure_overhead`.
    overhead: float


def measure_overhead(
    chunk_info: ChunkInfo,
    picks: Mapping[str, str],
    levels: Mapping[str, int],
    wiki_rates: Mapping[str, Rate],
    *,
    index: MonsterIndex | None = None,
    kit: Kit | None = None,
) -> tuple[OverheadSample, ...]:
    """Per-monster overhead implied by the wiki's own rates.

    For any monster the guides cover, `3600 / kph` is a full kill cycle and
    this module can compute the fighting part, so the difference is everything
    else. That is the appealing calibration: fit it where both numbers exist,
    apply it where only one does.

    **Read the samples before believing the fit.** The wiki's rates assume
    near-max gear and this project's `ttk` comes from chunk-restricted BiS, so
    the two are not the same fight. Where the map's gear is worse - which is
    the normal case, that being the point of the game mode - the computed
    `ttk` is longer than the wiki's whole cycle and the implied overhead comes
    out **negative**. A mean over those is meaningless.

    Doing this honestly needs the fighting time at *max* gear, which means a
    BiS pass over the whole equipment table rather than the unlocked subset.
    This function deliberately returns the raw samples rather than a single
    number, so that gap stays visible instead of being averaged away.
    """
    _require()
    monster_index = load_monster_index() if index is None else index
    loadouts = build_loadouts(chunk_info, picks, levels, kit)
    if not loadouts:
        return ()

    samples: list[OverheadSample] = []
    for monster, rate in sorted(wiki_rates.items()):
        if rate.value <= 0 or monster in GROUP_BOSSES:
            continue
        kill = best_kill(
            loadouts,
            monster,
            candidate_targets(monster_index, monster),
            reductions=kit.reductions if kit is not None else None,
            wilderness=monster in kit.wilderness if kit is not None else False,
        )
        if kill is None:
            continue
        samples.append(
            OverheadSample(
                monster=monster,
                wiki_kph=rate.value,
                ttk=kill.ttk,
                overhead=3600.0 / rate.value - kill.ttk,
            )
        )
    return tuple(samples)
