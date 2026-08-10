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

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from fray_claude.costing import combat_xp, dps_bridge, recipe_rates
from fray_claude.costing.estimate import material_seconds
from fray_claude.store import cache
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.store.derived_cache import Digests, cached_enrich, pricing_digests
from fray_claude.costing.estimate import EstimateResult, estimate
from fray_claude.derive.search import WorldIndex
from fray_claude.remote.recipes import Material as RecipeMaterial, Recipe
from fray_claude.costing.levels import goal_levels, infer_levels, reachable_providers
from fray_claude.costing.heuristics import Heuristics, load, merge
from fray_claude.derive.pipeline import Derived, MapState
from fray_claude.derive.search import build_world_index
from fray_claude.model.summary import _mapping

__all__ = [
    "EstimateAnswer",
    "estimate_answer",
    "level_overrides",
    "load_heuristics",
    "load_recipes",
    "recipe_priced",
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


def load_recipes(root: Path | None = None) -> dict[str, tuple[Recipe, ...]]:
    """The `fray recipes` blob, back as `Recipe`s, or empty if never fetched.

    Empty is a supported way to run, exactly as an absent rate scrape is: every
    method simply keeps whatever the guides and defaults gave it. The caller
    does not have to check - `recipe_rates.apply` over nothing is a no-op.
    """
    try:
        blob = cache.read_blob(cache.RECIPES_BLOB_NAME, root)["data"]
    except cache.CacheMissError:
        return {}
    return {
        skill: tuple(
            Recipe(
                page=str(row.get("page") or ""),
                output=str(row["output"]),
                output_quantity=float(row.get("output_quantity") or 1.0),
                skill=skill,
                level=int(row.get("level") or 1),
                experience=float(row["experience"]),
                ticks=None if row.get("ticks") is None else int(row["ticks"]),
                materials=tuple(
                    RecipeMaterial(str(m["name"]), float(m.get("quantity") or 1.0))
                    for m in row.get("materials") or []
                    if isinstance(m, dict) and m.get("name")
                ),
                variant=str(row.get("variant") or ""),
            )
            for row in rows
            if isinstance(row, dict) and row.get("output") and row.get("experience") is not None
        )
        for skill, rows in blob.items()
        if isinstance(rows, list)
    }


def recipe_priced(
    state: MapState,
    derived: Derived,
    world: WorldIndex,
    heuristics: Heuristics,
    levels: dict[str, int],
    *,
    root: Path | None = None,
) -> tuple[Heuristics, recipe_rates.RecipeCoverage]:
    """`heuristics` with a rate computed for every method the recipes reach.

    **Runs whether or not the DPS extra is installed**, unlike
    `priced_heuristics` - a recipe is wiki data and the item walk is this
    project's own, so neither needs `osrs-dps`. It is folded into the same
    cached call because it costs ~6s on a real map: the walk prices every
    material of every reachable method, and that is the whole expense.
    """
    recipes = load_recipes(root)
    if not recipes:
        return heuristics, recipe_rates.RecipeCoverage()
    pinned = frozenset(_mapping(cache.read_overrides(root), "training"))
    computed, coverage = recipe_rates.computed_rates(
        state.chunk_info,
        derived.challenges.valid,
        recipes,
        material_seconds(
            state, derived, world, heuristics, level_overrides=levels
        ),
    )
    return (
        replace(heuristics, training=recipe_rates.apply(heuristics.training, computed, pinned)),
        coverage,
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
    world: WorldIndex | None = None,
    root: Path | None = None,
    refresh: bool = False,
) -> tuple[Heuristics, dps_bridge.DpsCoverage | None]:
    """Every rate this machine can compute, layered on and cached as one.

    Two computations, deliberately behind one key. `recipe_priced` costs ~6s
    on a real map and `dps_bridge.enrich` ~0.7s, and both are pure functions of
    the same inputs, so splitting them into two cache entries would buy nothing
    and give the two a chance to disagree about which derivation they saw.

    **The recipe half runs with or without the DPS extra**, which is why this
    no longer returns early when the extra is absent. That path used to skip
    the cache entirely; now it stores, because without the extra there is still
    six seconds of item walking to avoid repeating. `None` for the coverage
    still means `osrs-dps` is not installed - a supported way to run and a
    different answer rather than a broken one; both apps say which they show.

    **Order matters: recipes first, then fights.** A recipe rate is priced
    through the item walk, which spends kill rates, so running `enrich` first
    would change what a material costs. It does not run first, and a comment
    here is cheaper than the afternoon spent finding out why two runs of the
    same map disagreed.

    The levels are `goal_levels`, the ones the chunk *ends* at, because that is
    what `slayer.py` already judges a master at and pricing the same fight at
    two different levels inside one command would be indefensible.
    """
    index = build_world_index(state.chunk_info) if world is None else world
    pinned_monsters, pinned_slayer = pinned_keys(root)
    goals = goal_levels(state, derived, {**infer_levels(state), **levels})

    def compute() -> tuple[Heuristics, dps_bridge.DpsCoverage | None]:
        priced, _ = recipe_priced(state, derived, index, heuristics, levels, root=root)
        coverage: dps_bridge.DpsCoverage | None = None
        if dps_bridge.DPS_AVAILABLE:
            priced, coverage = dps_bridge.enrich(
                priced,
                state.chunk_info,
                derived,
                goals,
                pinned_monsters=pinned_monsters,
                pinned_slayer=pinned_slayer,
            )
        # **Last, because it multiplies the kill rates.** Running this before
        # `enrich` would price combat off the scraped rates and then throw the
        # simulated ones away - the numbers would be quietly worse on exactly
        # the maps where the extra had most to say.
        caps = combat_xp.spawn_caps(state.chunk_info, derived)
        by_style: dict[str, dps_bridge.CombatRate] = {}
        if dps_bridge.DPS_AVAILABLE:
            # **The kit is not optional here.** Without it the Magic loadout
            # has no runes and never lands a hit, so `price_combat` returned
            # melee and ranged only - and Magic fell through to the rough
            # fallback, which is the inconsistent model this call exists to
            # replace.
            by_style = dps_bridge.price_combat(
                state.chunk_info,
                derived.bis.picks,
                goals,
                sorted(combat_xp.farmable_providers(derived)),
                kit=dps_bridge.assemble_kit(
                    state.chunk_info,
                    goals,
                    items=derived.challenges.available_items,
                    source_index=derived.source_index,
                ),
                slayer_monsters=frozenset(state.chunk_info.slayer_monsters),
                boss_monsters=frozenset(_mapping(state.chunk_info.code_items, "bossMonsters")),
                multipliers={
                    name: entry.xp_multiplier
                    for name, entry in priced.monster_stats.items()
                },
                caps=caps,
            )
        rates, damage = combat_xp.combat_rates(
            derived,
            priced,
            priced.monster_stats,
            priced.spells,
            goals,
            by_style=by_style,
            caps=caps,
        )
        return replace(priced, combat=rates, combat_damage=damage), coverage

    return cached_enrich(
        compute,
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
    world = build_world_index(state.chunk_info)
    heuristics, coverage = priced_heuristics(
        state,
        unlocked,
        derived,
        heuristics,
        levels,
        digests,
        world=world,
        root=root,
        refresh=refresh,
    )
    result = estimate(state, derived, world, heuristics, level_overrides=levels)
    return EstimateAnswer(result=result, scraped_rates=scraped_rates, coverage=coverage)
