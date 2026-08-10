"""Everything `fray estimate` and the Estimate tab must agree about.

**Two apps computed this twice and had already drifted.** `gui/server.py`'s
`_heuristics_for` said in its own docstring that it "mirrors
`cli._load_heuristics`", which is the shape of a bug rather than a design: the
CLI passed `pinned_slayer` to `dps_bridge.enrich` and the GUI did not, so the
same map priced differently depending on which app you asked.

**And the divergence would not have stayed on screen.** `enrichment_key` hashes
`PricingDigests{rates, overrides, library}`, where `overrides` is a digest of
the *file* `heuristics/overrides.json` - identical for both apps. Nothing in the
key records whether the pins inside that file were actually applied, so the two
apps computed the same key and stored different values under it in a shared
`cache/derived/`, last writer winning. Opening the Estimate tab could change
what `fray estimate` printed for the same map, and the wrong number is a
perfectly plausible one.

It was latent rather than live: `heuristics/overrides.json` ships with `slayer`
and `monsters` both empty, so the two agreed until someone used the file for
what it is checked in for. Fixing the drift by unifying the code is what stops
it recurring - a shared module cannot mirror itself out of step.

Composition, not logic: every function here is the two apps' existing bodies
moved verbatim. It touches disk through `cache.py` and reads the optional DPS
extra through `dps_bridge.py`, which is why it sits beside them rather than in
the pure layer - `cli.py` and `gui/server.py` are its only callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from fray_claude.costing import dps_bridge
from fray_claude.store import cache
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.store.derived_cache import Digests, cached_enrich, pricing_digests
from fray_claude.costing.estimate import EstimateResult, estimate, goal_levels, infer_levels
from fray_claude.costing.heuristics import Heuristics, load, merge
from fray_claude.derive.pipeline import Derived, MapState
from fray_claude.derive.search import build_world_index
from fray_claude.model.summary import _mapping

__all__ = [
    "EstimateAnswer",
    "estimate_answer",
    "level_overrides",
    "load_heuristics",
    "pinned_keys",
    "priced_heuristics",
]


@dataclass(frozen=True)
class EstimateAnswer:
    """One estimate, with the two things a caller must say out loud about it.

    `scraped_rates` and `coverage` are not decoration: an estimate with no
    scrape is thousands of hours light, and one priced with the DPS extra is a
    materially different number from one without (3,969h against 2,816h on the
    real map). Both apps render these; neither may drop them.
    """

    result: EstimateResult
    scraped_rates: bool
    coverage: dps_bridge.DpsCoverage | None

    def as_dict(self, map_id: str) -> dict[str, Any]:
        """The JSON both apps emit. One shape, so `--export-json` and
        `/api/estimate` cannot describe the same answer differently."""
        return {
            "map_id": map_id,
            "scraped_rates": self.scraped_rates,
            "dps": self.coverage.as_dict() if self.coverage is not None else None,
            **self.result.as_dict(),
        }


def load_heuristics(info: ChunkInfo, root: Path | None = None) -> tuple[Heuristics, bool]:
    """The two layers merged, and whether the scraped one was there at all.

    Returns the flag rather than swallowing it: an estimate with no scrape
    still produces a plausible-looking total, and the difference is not small.
    Without it there are no superior mappings and no slayer assignment sizes,
    so every superior drop and every task-gated boss drop goes unpriced - on
    the real map, 19 unpriced items against 3, and a total ~3,000 hours light.
    Printing that quietly would be the worst of both.
    """
    try:
        scraped = cache.read_blob(
            cache.WIKI_RATES_BLOB_NAME, root, hint="run: fray heuristics"
        )["data"]
        scraped_found = True
    except cache.CacheMissError:
        # Still usable: everything falls back to a default. That is honest
        # only if the caller says so, which both of them do.
        scraped, scraped_found = {}, False
    return (
        load(
            merge(scraped, cache.read_overrides(root)),
            boss_monsters=frozenset(_mapping(info.code_items, "bossMonsters")),
            slayer_monsters=frozenset(info.slayer_monsters),
        ),
        scraped_found,
    )


def level_overrides(root: Path | None = None) -> dict[str, int]:
    """The hand-set skill levels from `heuristics/overrides.json`.

    `isinstance(level, bool)` is excluded deliberately - `True` is an `int` in
    Python, and a stray `"Attack": true` would otherwise become level 1.
    """
    overrides = _mapping(cache.read_overrides(root), "levels")
    return {
        skill: int(level)
        for skill, level in overrides.items()
        if isinstance(level, int) and not isinstance(level, bool)
    }


def pinned_keys(root: Path | None = None) -> tuple[frozenset[str], dict[str, frozenset[str]]]:
    """The hand-written rates the computed layer must not overwrite.

    Monsters and slayer tasks, from the one file. Returned together because
    they come from one read and are passed to one call - splitting them is how
    the GUI came to pass the first and forget the second.
    """
    raw = cache.read_overrides(root)
    monsters = frozenset(_mapping(raw, "monsters"))
    slayer = {
        master: frozenset(tasks)
        for master, tasks in _mapping(raw, "slayer").items()
        if isinstance(tasks, dict)
    }
    return monsters, slayer


def priced_heuristics(
    state: MapState,
    unlocked: Mapping[str, bool],
    derived: Derived,
    heuristics: Heuristics,
    levels: dict[str, int],
    digests: Digests,
    *,
    root: Path | None = None,
    refresh: bool = False,
) -> tuple[Heuristics, dps_bridge.DpsCoverage | None]:
    """The computed rates layered over the scraped ones, if the extra is here.

    `None` for the coverage means `osrs-dps` is not installed, which is a
    supported way to run and a different answer rather than a broken one; both
    apps say which they are showing.

    The levels are `goal_levels`, the ones the chunk *ends* at, because that is
    what `slayer.py` already judges a master at and pricing the same fight at
    two different levels inside one command would be indefensible.

    662ms against `estimate`'s 3.1ms, and a pure function of inputs the
    derivation cache already keys on plus three it does not - hence
    `cached_enrich`, and hence `refresh` (`--recompute`) bypassing it the same
    way it bypasses the derivation.
    """
    if not dps_bridge.DPS_AVAILABLE:
        return heuristics, None
    pinned_monsters, pinned_slayer = pinned_keys(root)
    goals = goal_levels(state, derived, {**infer_levels(state), **levels})
    return cached_enrich(
        lambda: dps_bridge.enrich(
            heuristics,
            state.chunk_info,
            derived,
            goals,
            pinned_monsters=pinned_monsters,
            pinned_slayer=pinned_slayer,
        ),
        state,
        unlocked,
        digests,
        pricing_digests(root),
        root=root,
        refresh=refresh,
    )


def estimate_answer(
    state: MapState,
    unlocked: Mapping[str, bool],
    derived: Derived,
    digests: Digests,
    *,
    root: Path | None = None,
    refresh: bool = False,
) -> EstimateAnswer:
    """The whole estimate, assembled once for whichever app asked.

    Everything above, in the one order both apps used: load the layers, read
    the level overrides, let the computed rates beat the scraped ones, then
    price. What is left at the call sites is rendering.
    """
    heuristics, scraped_rates = load_heuristics(state.chunk_info, root)
    levels = level_overrides(root)
    heuristics, coverage = priced_heuristics(
        state, unlocked, derived, heuristics, levels, digests, root=root, refresh=refresh
    )
    result = estimate(
        state,
        derived,
        build_world_index(state.chunk_info),
        heuristics,
        level_overrides=levels,
    )
    return EstimateAnswer(result=result, scraped_rates=scraped_rates, coverage=coverage)
